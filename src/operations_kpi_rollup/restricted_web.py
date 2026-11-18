"""Identity-gated HTTP service for restricted Operations KPI drill-downs."""

from __future__ import annotations

from datetime import date, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import mimetypes
import os
from pathlib import Path
import re
import threading
import time
from typing import Any, Dict, Mapping, Optional, Sequence
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

from .restricted import (
    CURRENT_RESTRICTED_METHOD_VERSION,
    RESTRICTED_HISTORY_START,
    refresh_restricted_snapshot,
    validate_restricted_snapshot,
)


STATIC_ROOT = Path(__file__).parent / "restricted_web"
GUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


class RestrictedAccessError(PermissionError):
    pass


class RestrictedRefreshError(RuntimeError):
    pass


class RestrictedAuth:
    """Trust exact Entra identity headers only from configured local proxies."""

    def __init__(self, allowed_object_ids: Sequence[str], trusted_proxy_networks: Sequence[str]) -> None:
        normalized = {value.strip().lower() for value in allowed_object_ids if value.strip()}
        if not normalized or any(not GUID.fullmatch(value) for value in normalized):
            raise ValueError("KPI_RESTRICTED_ALLOWED_OBJECT_IDS must contain one or more exact Entra object IDs.")
        networks = []
        for value in trusted_proxy_networks:
            value = value.strip()
            if value:
                networks.append(ipaddress.ip_network(value, strict=False))
        if not networks:
            raise ValueError("KPI_RESTRICTED_TRUSTED_PROXIES must contain at least one proxy network.")
        self.allowed_object_ids = frozenset(normalized)
        self.trusted_proxy_networks = tuple(networks)

    @classmethod
    def from_environment(cls) -> "RestrictedAuth":
        raw_allowed = os.environ.get("KPI_RESTRICTED_ALLOWED_OBJECT_IDS", "").strip()
        if not raw_allowed:
            credential_dir = os.environ.get("CREDENTIALS_DIRECTORY", "")
            credential_name = os.environ.get(
                "KPI_RESTRICTED_ALLOWED_OBJECT_IDS_CREDENTIAL",
                "operations-kpi-restricted-allowed-object-ids",
            )
            credential_path = Path(credential_dir) / credential_name if credential_dir else None
            if credential_path and credential_path.is_file():
                raw_allowed = credential_path.read_text(encoding="utf-8").strip()
        allowed = re.split(r"[,\s]+", raw_allowed) if raw_allowed else []
        trusted = os.environ.get("KPI_RESTRICTED_TRUSTED_PROXIES", "127.0.0.1/32,::1/128").split(",")
        return cls(allowed, trusted)

    def authorize(self, client_ip: str, headers: Mapping[str, str]) -> Dict[str, str]:
        try:
            address = ipaddress.ip_address(client_ip)
            if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
                address = address.ipv4_mapped
        except ValueError as exc:
            raise RestrictedAccessError("The restricted proxy address is invalid.") from exc
        if not any(address in network for network in self.trusted_proxy_networks):
            raise RestrictedAccessError("Restricted identity headers are accepted only from the trusted proxy.")

        object_id = str(headers.get("X-CLC-Object-Id", "")).strip().lower()
        if not GUID.fullmatch(object_id) or object_id not in self.allowed_object_ids:
            raise RestrictedAccessError("This Entra identity is not approved for the restricted drill-down.")
        user = " ".join(str(headers.get("X-CLC-User", "")).split())[:254].lower()
        name = " ".join(str(headers.get("X-CLC-Name", "")).split())[:200]
        return {"object_id": object_id, "user": user, "name": name or user or "Authorized viewer"}


class RestrictedState:
    def __init__(self, mode: str, snapshot_dir: Path, fixture_path: Optional[Path] = None) -> None:
        if mode not in {"fixture", "live"}:
            raise ValueError("KPI_RESTRICTED_DATA_MODE must be fixture or live.")
        self.mode = mode
        self.snapshot_dir = snapshot_dir
        self.fixture_path = fixture_path
        self._snapshot: Optional[Dict[str, Any]] = None
        self._snapshots_by_date: Dict[str, Dict[str, Any]] = {}
        self._snapshot_lock = threading.RLock()
        self._refresh_lock = threading.Lock()
        self._last_refresh_monotonic = 0.0
        self._last_refresh_error: Optional[str] = None
        self._last_refresh_source = "startup"
        self._last_query_duration_seconds: Optional[float] = None
        self._auto_refresh_stop = threading.Event()
        self._auto_refresh_thread: Optional[threading.Thread] = None
        self.refresh_freshness_seconds = self._bounded_seconds(
            "KPI_RESTRICTED_REFRESH_FRESHNESS_SECONDS", 600.0, 60.0, 3600.0
        )
        self.auto_refresh_seconds = self._bounded_seconds(
            "KPI_RESTRICTED_AUTO_REFRESH_SECONDS", 600.0, 60.0, 3600.0
        )
        self._load_initial_snapshot()

    @staticmethod
    def _bounded_seconds(name: str, default: float, minimum: float, maximum: float) -> float:
        try:
            value = float(os.environ.get(name, str(default)))
        except ValueError as exc:
            raise ValueError(f"{name} must be a number.") from exc
        if value < minimum or value > maximum:
            raise ValueError(f"{name} must be between {minimum:g} and {maximum:g} seconds.")
        return value

    @staticmethod
    def _clone(snapshot: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        return json.loads(json.dumps(snapshot)) if snapshot is not None else None

    def _remember(self, snapshot: Dict[str, Any], *, latest: bool = True) -> None:
        with self._snapshot_lock:
            self._snapshots_by_date[snapshot["report_date"]] = snapshot
            if latest:
                self._snapshot = snapshot

    def _read_snapshot(self, path: Path) -> Dict[str, Any]:
        snapshot = json.loads(path.read_text(encoding="utf-8"))
        validate_restricted_snapshot(snapshot)
        return snapshot

    def _load_initial_snapshot(self) -> None:
        latest = self.snapshot_dir / "latest.json"
        source = latest if latest.is_file() else self.fixture_path
        if source and source.is_file():
            self._remember(self._read_snapshot(source))

    def snapshot(self, report_date: Optional[date] = None) -> Optional[Dict[str, Any]]:
        if report_date is None:
            with self._snapshot_lock:
                return self._clone(self._snapshot)
        date_text = report_date.isoformat()
        with self._snapshot_lock:
            remembered = self._snapshots_by_date.get(date_text)
        if remembered is not None:
            return self._clone(remembered)
        candidates = sorted(self.snapshot_dir.glob(f"{date_text}__*.json"), reverse=True)
        if not candidates:
            return None
        snapshot = self._read_snapshot(candidates[0])
        if snapshot["report_date"] != date_text:
            raise RestrictedRefreshError("The saved restricted snapshot has the wrong report date.")
        self._remember(snapshot, latest=False)
        return self._clone(snapshot)

    def _today(self) -> date:
        zone = ZoneInfo(os.environ.get("KPI_TIMEZONE", "America/Indiana/Indianapolis"))
        return datetime.now(zone).date()

    def _snapshot_age_seconds(self, snapshot: Dict[str, Any]) -> float:
        zone = ZoneInfo(os.environ.get("KPI_TIMEZONE", "America/Indiana/Indianapolis"))
        observed = datetime.fromisoformat(str(snapshot["generated_at"]))
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=zone)
        return max(0.0, (datetime.now(zone) - observed.astimezone(zone)).total_seconds())

    def _persist(self, snapshot: Dict[str, Any]) -> None:
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        self.snapshot_dir.chmod(0o700)
        encoded = (json.dumps(snapshot, indent=2, sort_keys=True) + "\n").encode("utf-8")
        immutable = self.snapshot_dir / f"{snapshot['report_date']}__{time.time_ns()}.json"
        immutable.write_bytes(encoded)
        immutable.chmod(0o600)
        temporary = self.snapshot_dir / f".latest.{os.getpid()}.{time.time_ns()}.tmp"
        temporary.write_bytes(encoded)
        temporary.chmod(0o600)
        os.replace(temporary, self.snapshot_dir / "latest.json")

    def refresh(self, report_date: date, *, force: bool = False) -> Dict[str, Any]:
        today = self._today()
        if report_date < RESTRICTED_HISTORY_START:
            raise RestrictedRefreshError(
                f"Restricted history starts on {RESTRICTED_HISTORY_START.isoformat()}."
            )
        if report_date > today:
            raise RestrictedRefreshError("A future report date is not allowed.")
        cached = self.snapshot(report_date)
        if not force and cached is not None:
            if report_date < today or self._snapshot_age_seconds(cached) < self.refresh_freshness_seconds:
                self._last_refresh_source = "cache"
                return cached
        if not self._refresh_lock.acquire(blocking=False):
            if cached is not None:
                self._last_refresh_source = "cache-during-refresh"
                return cached
            raise RestrictedRefreshError("A restricted refresh is already in progress.")
        try:
            minimum_seconds = max(1.0, float(os.environ.get("KPI_RESTRICTED_MIN_REFRESH_SECONDS", "15")))
            elapsed = time.monotonic() - self._last_refresh_monotonic
            if force and self._last_refresh_monotonic and elapsed < minimum_seconds:
                raise RestrictedRefreshError(
                    f"Please wait {minimum_seconds - elapsed:.0f} seconds before refreshing again."
                )
            started = time.monotonic()
            if self.mode == "live":
                snapshot = refresh_restricted_snapshot(report_date)
            else:
                if not self.fixture_path or not self.fixture_path.is_file():
                    raise RestrictedRefreshError("The restricted fixture is unavailable.")
                snapshot = self._read_snapshot(self.fixture_path)
                if snapshot["report_date"] != report_date.isoformat():
                    raise RestrictedRefreshError("Fixture mode can refresh only its recorded report date.")
            self._persist(snapshot)
            self._remember(snapshot)
            self._last_refresh_monotonic = time.monotonic()
            self._last_query_duration_seconds = round(time.monotonic() - started, 3)
            self._last_refresh_source = "live-query" if self.mode == "live" else "fixture-refresh"
            self._last_refresh_error = None
            return self._clone(snapshot) or snapshot
        except Exception as exc:
            self._last_refresh_error = f"{type(exc).__name__}: {str(exc)[:240]}"
            raise
        finally:
            self._refresh_lock.release()

    def start_auto_refresh(self) -> None:
        if self.mode != "live" or (self._auto_refresh_thread and self._auto_refresh_thread.is_alive()):
            return
        self._auto_refresh_stop.clear()
        self._auto_refresh_thread = threading.Thread(
            target=self._auto_refresh_loop, name="operations-kpi-restricted-refresh", daemon=True
        )
        self._auto_refresh_thread.start()

    def _auto_refresh_loop(self) -> None:
        while not self._auto_refresh_stop.is_set():
            try:
                self.refresh(self._today())
                delay = self.auto_refresh_seconds
            except Exception as exc:
                print(
                    json.dumps(
                        {"event": "restricted-auto-refresh-error", "error": f"{type(exc).__name__}: {str(exc)[:240]}"},
                        separators=(",", ":"),
                    ),
                    flush=True,
                )
                delay = min(60.0, self.auto_refresh_seconds)
            if self._auto_refresh_stop.wait(delay):
                break

    def stop_auto_refresh(self) -> None:
        self._auto_refresh_stop.set()
        if self._auto_refresh_thread:
            self._auto_refresh_thread.join(timeout=5)

    def health(self, viewer: Optional[Mapping[str, str]] = None) -> Dict[str, Any]:
        current = self.snapshot()
        return {
            "status": "ok" if current else "ready_no_snapshot",
            "service": "operations-kpi-restricted",
            "mode": self.mode,
            "method_version": CURRENT_RESTRICTED_METHOD_VERSION,
            "report_date": current.get("report_date") if current else None,
            "generated_at": current.get("generated_at") if current else None,
            "refresh_boundary": "identity-gated-loopback-proxy",
            "refresh_in_progress": self._refresh_lock.locked(),
            "last_refresh_source": self._last_refresh_source,
            "last_query_duration_seconds": self._last_query_duration_seconds,
            "last_refresh_error": self._last_refresh_error,
            "viewer": {"user": viewer.get("user", ""), "name": viewer.get("name", "")} if viewer else None,
        }


class RestrictedServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, handler, state: RestrictedState, auth: RestrictedAuth):
        super().__init__(address, handler)
        self.state = state
        self.auth = auth


class RestrictedHandler(BaseHTTPRequestHandler):
    server_version = "OperationsKPIRestricted/0.34.0"
    sys_version = ""

    @property
    def state(self) -> RestrictedState:
        return self.server.state  # type: ignore[attr-defined]

    @property
    def auth(self) -> RestrictedAuth:
        return self.server.auth  # type: ignore[attr-defined]

    def _security_headers(self) -> None:
        self.send_header("Cache-Control", "no-store, private")
        self.send_header("Pragma", "no-cache")
        self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'; object-src 'none'")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=(), usb=()")

    def _json(self, status: int, payload: Any) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._security_headers()
        self.end_headers()
        self.wfile.write(body)

    def _identity(self) -> Optional[Dict[str, str]]:
        try:
            return self.auth.authorize(self.client_address[0], self.headers)
        except RestrictedAccessError as exc:
            self._json(HTTPStatus.FORBIDDEN, {"error": str(exc)})
            return None

    def _static(self, filename: str) -> None:
        path = (STATIC_ROOT / filename).resolve()
        if path.parent != STATIC_ROOT.resolve() or not path.is_file():
            self._json(HTTPStatus.NOT_FOUND, {"error": "Not found."})
            return
        body = path.read_bytes()
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header(
            "Content-Type",
            content_type + ("; charset=utf-8" if content_type.startswith("text/") or content_type.endswith("javascript") else ""),
        )
        self.send_header("Content-Length", str(len(body)))
        self._security_headers()
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlsplit(self.path)
        if parsed.path == "/healthz":
            self._json(HTTPStatus.OK, {"status": "ok", "service": "operations-kpi-restricted"})
            return
        viewer = self._identity()
        if viewer is None:
            return
        if parsed.path in {"/", "/index.html"}:
            self._static("index.html")
        elif parsed.path == "/app.js":
            self._static("app.js")
        elif parsed.path == "/styles.css":
            self._static("styles.css")
        elif parsed.path == "/api/health":
            self._json(HTTPStatus.OK, self.state.health(viewer))
        elif parsed.path == "/api/snapshot":
            try:
                values = parse_qs(parsed.query).get("report_date", [])
                requested = date.fromisoformat(values[0]) if values else None
                snapshot = self.state.snapshot(requested)
                self._json(
                    HTTPStatus.OK if snapshot else HTTPStatus.NOT_FOUND,
                    snapshot or {"error": "No restricted snapshot is available for that date."},
                )
            except (ValueError, RestrictedRefreshError) as exc:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        else:
            self._json(HTTPStatus.NOT_FOUND, {"error": "Not found."})

    def do_POST(self) -> None:  # noqa: N802
        viewer = self._identity()
        if viewer is None:
            return
        if urlsplit(self.path).path != "/api/refresh":
            self._json(HTTPStatus.NOT_FOUND, {"error": "Not found."})
            return
        if self.headers.get("X-Operations-KPI-Restricted-Action") != "refresh":
            self._json(HTTPStatus.FORBIDDEN, {"error": "The restricted refresh action header is required."})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0 or length > 4096:
            self._json(HTTPStatus.BAD_REQUEST, {"error": "The request body is missing or too large."})
            return
        try:
            payload = json.loads(self.rfile.read(length))
            requested = date.fromisoformat(str(payload.get("report_date", "")))
            force = payload.get("force", False)
            if not isinstance(force, bool):
                raise ValueError("force must be true or false.")
            snapshot = self.state.refresh(requested, force=force)
            self._json(HTTPStatus.OK, snapshot)
        except (ValueError, RestrictedRefreshError) as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        except Exception:
            self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "The restricted refresh failed."})
            raise

    def log_message(self, fmt: str, *args: Any) -> None:
        print(
            json.dumps({"remote": self.client_address[0], "request": fmt % args}, separators=(",", ":")),
            flush=True,
        )


def create_restricted_server(
    host: str, port: int, state: RestrictedState, auth: RestrictedAuth
) -> RestrictedServer:
    address = ipaddress.ip_address(host)
    if not address.is_loopback:
        raise ValueError("The restricted service must bind to loopback behind the authenticated proxy.")
    return RestrictedServer((host, port), RestrictedHandler, state, auth)


def main() -> int:
    mode = os.environ.get("KPI_RESTRICTED_DATA_MODE", "fixture").lower()
    snapshot_dir = Path(os.environ.get("KPI_RESTRICTED_SNAPSHOT_DIR", "build/restricted-snapshots"))
    fixture_value = os.environ.get("KPI_RESTRICTED_FIXTURE_PATH", "")
    fixture_path = Path(fixture_value) if fixture_value else None
    state = RestrictedState(mode, snapshot_dir, fixture_path)
    auth = RestrictedAuth.from_environment()
    host = os.environ.get("KPI_RESTRICTED_BIND_HOST", "127.0.0.1")
    port = int(os.environ.get("KPI_RESTRICTED_PORT", "5194"))
    server = create_restricted_server(host, port, state, auth)
    state.start_auto_refresh()
    print(
        json.dumps(
            {"status": "starting", "host": host, "port": port, "mode": mode, "access": "restricted"},
            separators=(",", ":"),
        ),
        flush=True,
    )
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        state.stop_auto_refresh()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
