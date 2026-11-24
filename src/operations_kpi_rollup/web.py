"""Small dependency-free HTTP service for the on-demand internal dashboard."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import html
import ipaddress
import base64
import json
import mimetypes
import os
from pathlib import Path
import ssl
import sys
import threading
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlsplit

from .business_time import business_clock_fields, business_now, business_timezone_name, business_today, business_zone
from .context import validate_snapshot
from .process_times import normalize_stored_process_time
from .assembly_charts import normalize_stored_assembly_charts
from .assembly_details import redact_assembly_operators
from .quality_charts import normalize_stored_quality_charts
from .drilldown import DrilldownState, create_drilldown_state, disabled_event
from .live import CURRENT_METHOD_VERSION, refresh_live_snapshot
from .restricted_web import RestrictedRefreshError
from .roster import RosterService, RosterUnavailable, clean_ids, roster_from_rows
from .windows_auth import (
    SESSION_COOKIE,
    Allowlist,
    AuthSettings,
    NegotiateAcceptor,
    SessionCodec,
    parse_negotiate_header,
    sam_of,
    settings_from_env,
)


STATIC_ROOT = Path(__file__).parent / "web"
DRILLDOWN_STATIC_ROOT = Path(__file__).parent / "drilldown_web"
DRILLDOWN_ASSETS = {"/drilldown/app.js": "app.js", "/drilldown/styles.css": "styles.css"}
EARLIEST_SUPPORTED_DATE = date(2026, 9, 8)
# Offered on the sign-in pages so nobody dead-ends: the open wallboard shows worker IDs, not names.
OPEN_VIEW_LINKS: Tuple[Tuple[str, str], ...] = (
    ("http://kpi.eliteenterprisesinc.com:5193/", "Open the wallboard without signing in (worker IDs, no names)"),
)


class RefreshError(RuntimeError):
    pass


class AppState:
    def __init__(
        self,
        mode: str,
        snapshot_dir: Path,
        fixture_path: Optional[Path] = None,
    ) -> None:
        if mode not in {"fixture", "live"}:
            raise ValueError("KPI_DATA_MODE must be fixture or live")
        self.mode = mode
        self.snapshot_dir = snapshot_dir
        self.fixture_path = fixture_path
        self._snapshot: Optional[Dict[str, Any]] = None
        self._snapshots_by_date: Dict[str, Dict[str, Any]] = {}
        self._snapshot_lock = threading.RLock()
        self._refresh_lock = threading.Lock()
        self._last_refresh_monotonic = 0.0
        self._last_query_duration_seconds: Optional[float] = None
        self._last_query_completed_at: Optional[str] = None
        self._last_refresh_source = "startup"
        self._last_refresh_error: Optional[str] = None
        self._auto_refresh_stop = threading.Event()
        self._auto_refresh_thread: Optional[threading.Thread] = None
        self.refresh_freshness_seconds = self._bounded_seconds(
            "KPI_REFRESH_FRESHNESS_SECONDS", 600.0, 15.0, 3600.0
        )
        self.auto_refresh_seconds = self._bounded_seconds(
            "KPI_AUTO_REFRESH_SECONDS", 600.0, 60.0, 3600.0
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

    def _remember(self, snapshot: Dict[str, Any], make_latest: bool = True) -> None:
        with self._snapshot_lock:
            self._snapshots_by_date[snapshot["report_date"]] = snapshot
            if make_latest:
                self._snapshot = snapshot

    def _load_initial_snapshot(self) -> None:
        latest = self.snapshot_dir / "latest.json"
        source = latest if latest.is_file() else self.fixture_path
        if source and source.is_file():
            snapshot = json.loads(source.read_text(encoding="utf-8"))
            normalize_stored_process_time(snapshot)
            normalize_stored_quality_charts(snapshot)
            normalize_stored_assembly_charts(snapshot)
            validate_snapshot(snapshot)
            self._remember(snapshot)

    def _load_saved_snapshot(self, report_date: date) -> Optional[Dict[str, Any]]:
        date_text = report_date.isoformat()
        with self._snapshot_lock:
            remembered = self._snapshots_by_date.get(date_text)
        if remembered is not None:
            return self._clone(remembered)

        candidates = sorted(self.snapshot_dir.glob(f"{date_text}__*.json"), reverse=True)
        if not candidates:
            return None
        source = candidates[0]
        try:
            snapshot = json.loads(source.read_text(encoding="utf-8"))
            normalize_stored_process_time(snapshot)
            normalize_stored_quality_charts(snapshot)
            normalize_stored_assembly_charts(snapshot)
            validate_snapshot(snapshot)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise RefreshError(f"The saved {date_text} snapshot is invalid.") from exc
        if snapshot.get("report_date") != date_text:
            raise RefreshError(f"The saved {date_text} snapshot has the wrong report date.")
        self._remember(snapshot, make_latest=False)
        return self._clone(snapshot)

    def snapshot(self, report_date: Optional[date] = None) -> Optional[Dict[str, Any]]:
        if report_date is not None:
            return self._load_saved_snapshot(report_date)
        with self._snapshot_lock:
            return self._clone(self._snapshot)

    def _today(self) -> date:
        return business_today()

    def _snapshot_age_seconds(self, snapshot: Dict[str, Any]) -> float:
        zone = business_zone()
        observed = datetime.fromisoformat(str(snapshot["generated_at"]))
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=zone)
        return max(0.0, (datetime.now(zone) - observed.astimezone(zone)).total_seconds())

    def _cached_snapshot(self, report_date: date, today: date) -> Optional[Dict[str, Any]]:
        snapshot = self.snapshot(report_date)
        if snapshot is None:
            return None
        if self.mode == "live" and snapshot.get("scope", {}).get("method_version") != CURRENT_METHOD_VERSION:
            return None
        if report_date < today:
            return snapshot
        if self._snapshot_age_seconds(snapshot) < self.refresh_freshness_seconds:
            return snapshot
        return None

    def _record_refresh_state(
        self,
        source: str,
        *,
        duration_seconds: Optional[float] = None,
        error: Optional[str] = None,
        clear_error: bool = False,
    ) -> None:
        with self._snapshot_lock:
            self._last_refresh_source = source
            if error is not None or clear_error:
                self._last_refresh_error = error
            if duration_seconds is not None:
                self._last_query_duration_seconds = round(duration_seconds, 3)
                self._last_query_completed_at = business_now().isoformat(timespec="seconds")

    def health(self) -> Dict[str, Any]:
        current = self.snapshot()
        current_day = self.snapshot(self._today())
        zone = business_zone()
        clock = business_clock_fields()
        next_auto_refresh_at = None
        if self.mode == "live" and current_day is not None:
            try:
                observed = datetime.fromisoformat(str(current_day["generated_at"]))
                if observed.tzinfo is None:
                    observed = observed.replace(tzinfo=zone)
                next_auto_refresh_at = (
                    observed.astimezone(zone) + timedelta(seconds=self.auto_refresh_seconds)
                ).isoformat(timespec="seconds")
            except (KeyError, TypeError, ValueError):
                next_auto_refresh_at = None
        return {
            "status": "ok" if current else "ready_no_snapshot",
            "service": "operations-kpi-rollup",
            "mode": self.mode,
            "report_date": current.get("report_date") if current else None,
            "generated_at": current.get("generated_at") if current else None,
            "refresh_boundary": "private-lan-bounded" if self.mode == "live" else "fixture-only",
            "server_time": clock["server_time"],
            "business_date": clock["business_date"],
            "business_timezone": clock["business_timezone"],
            "refresh_freshness_seconds": self.refresh_freshness_seconds,
            "auto_refresh_seconds": self.auto_refresh_seconds if self.mode == "live" else None,
            "auto_refresh_running": bool(self._auto_refresh_thread and self._auto_refresh_thread.is_alive()),
            "next_auto_refresh_at": next_auto_refresh_at,
            "refresh_in_progress": self._refresh_lock.locked(),
            "last_refresh_source": self._last_refresh_source,
            "last_query_duration_seconds": self._last_query_duration_seconds,
            "last_query_completed_at": self._last_query_completed_at,
            "last_refresh_error": self._last_refresh_error,
            "reconciliation_status": (current or {}).get("scope", {}).get("reconciliation_status"),
            "reconciliation_warnings": (current or {}).get("scope", {}).get("reconciliation_warnings", []),
        }

    def refresh(self, report_date: date, force: bool = False) -> Dict[str, Any]:
        today = self._today()
        if report_date < EARLIEST_SUPPORTED_DATE:
            raise RefreshError(f"The recovered metric contract starts on {EARLIEST_SUPPORTED_DATE.isoformat()}.")
        if report_date > today:
            raise RefreshError("A future report date is not allowed.")

        if not force:
            cached = self._cached_snapshot(report_date, today)
            if cached is not None:
                self._record_refresh_state("historical-cache" if report_date < today else "fresh-cache")
                return cached

        if not self._refresh_lock.acquire(blocking=False):
            cached = self.snapshot(report_date)
            if cached is not None:
                self._record_refresh_state("cache-during-refresh")
                return cached
            raise RefreshError("A report refresh is already in progress.")
        try:
            if not force:
                cached = self._cached_snapshot(report_date, today)
                if cached is not None:
                    self._record_refresh_state("historical-cache" if report_date < today else "fresh-cache")
                    return cached
            minimum_seconds = float(os.environ.get("KPI_MIN_REFRESH_SECONDS", "15"))
            elapsed = time.monotonic() - self._last_refresh_monotonic
            if self._last_refresh_monotonic and elapsed < minimum_seconds:
                cached = self.snapshot(report_date)
                if cached is not None:
                    self._record_refresh_state("rate-limit-cache")
                    return cached
                raise RefreshError(f"Please wait {minimum_seconds - elapsed:.0f} seconds before refreshing again.")

            started = time.monotonic()
            if self.mode == "live":
                snapshot = refresh_live_snapshot(report_date)
            else:
                if not self.fixture_path or not self.fixture_path.is_file():
                    raise RefreshError("The fixture snapshot is unavailable.")
                snapshot = json.loads(self.fixture_path.read_text(encoding="utf-8"))
                normalize_stored_process_time(snapshot)
                normalize_stored_quality_charts(snapshot)
                normalize_stored_assembly_charts(snapshot)
                validate_snapshot(snapshot)
                if snapshot["report_date"] != report_date.isoformat():
                    raise RefreshError("Fixture mode can only rebuild its recorded report date.")

            self._persist(snapshot)
            self._remember(snapshot)
            self._last_refresh_monotonic = time.monotonic()
            self._record_refresh_state(
                "live-query" if self.mode == "live" else "fixture-refresh",
                duration_seconds=time.monotonic() - started,
                clear_error=True,
            )
            return self.snapshot(report_date) or snapshot
        except Exception as exc:
            self._record_refresh_state("refresh-error", error=f"{type(exc).__name__}: {str(exc)[:240]}")
            raise
        finally:
            self._refresh_lock.release()

    def _auto_refresh_loop(self) -> None:
        while not self._auto_refresh_stop.is_set():
            today = self._today()
            try:
                self.refresh(today)
                current = self.snapshot(today)
                age_seconds = self._snapshot_age_seconds(current) if current else 0.0
                if self._refresh_lock.locked():
                    delay_seconds = min(15.0, self.auto_refresh_seconds)
                else:
                    delay_seconds = max(1.0, self.auto_refresh_seconds - age_seconds)
            except Exception as exc:
                print(json.dumps({"event": "auto-refresh-error", "error": f"{type(exc).__name__}: {str(exc)[:240]}"}, separators=(",", ":")), flush=True)
                delay_seconds = min(60.0, self.auto_refresh_seconds)
            if self._auto_refresh_stop.wait(delay_seconds):
                break

    def start_auto_refresh(self) -> None:
        if self.mode != "live" or (self._auto_refresh_thread and self._auto_refresh_thread.is_alive()):
            return
        self._auto_refresh_stop.clear()
        self._auto_refresh_thread = threading.Thread(
            target=self._auto_refresh_loop,
            name="operations-kpi-auto-refresh",
            daemon=True,
        )
        self._auto_refresh_thread.start()

    def stop_auto_refresh(self) -> None:
        self._auto_refresh_stop.set()
        if self._auto_refresh_thread:
            self._auto_refresh_thread.join(timeout=5)

    def _persist(self, snapshot: Dict[str, Any]) -> None:
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        encoded = (json.dumps(snapshot, indent=2, sort_keys=True) + "\n").encode("utf-8")
        immutable = self.snapshot_dir / f"{snapshot['report_date']}__{time.time_ns()}.json"
        immutable.write_bytes(encoded)
        immutable.chmod(0o600)
        temporary = self.snapshot_dir / f".latest.{os.getpid()}.{time.time_ns()}.tmp"
        temporary.write_bytes(encoded)
        temporary.chmod(0o600)
        os.replace(temporary, self.snapshot_dir / "latest.json")


def _is_private_address(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    return address.is_private or address.is_loopback


class AppServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, handler, app_state: AppState, drilldown_state: Optional[DrilldownState] = None):
        super().__init__(address, handler)
        self.app_state = app_state
        self.drilldown_state = drilldown_state


class Handler(BaseHTTPRequestHandler):
    server_version = "OperationsKPI/0.47.1"
    sys_version = ""
    # The open wallboard port never serves operator logins; the Windows sign-in listener (AuthHandler) does.
    signed_in = False

    @property
    def state(self) -> AppState:
        return self.server.app_state  # type: ignore[attr-defined]

    @property
    def drilldown(self) -> Optional[DrilldownState]:
        return getattr(self.server, "drilldown_state", None)

    def _security_headers(self, cache_control: str, noindex: bool = False) -> None:
        if noindex:
            self.send_header("X-Robots-Tag", "noindex, nofollow")
        self.send_header("Cache-Control", cache_control)
        self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")

    def _json(self, status: int, payload: Any, noindex: bool = False) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._security_headers("no-store", noindex)
        self.end_headers()
        self.wfile.write(body)

    def _static(self, filename: str, root: Path = STATIC_ROOT, cache_control: Optional[str] = None, noindex: bool = False) -> None:
        path = (root / filename).resolve()
        if path.parent != root.resolve() or not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        body = path.read_bytes()
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type + ("; charset=utf-8" if content_type.startswith("text/") or content_type.endswith("javascript") else ""))
        self.send_header("Content-Length", str(len(body)))
        self._security_headers(cache_control or ("public, max-age=300" if filename != "index.html" else "no-cache"), noindex)
        self.end_headers()
        self.wfile.write(body)

    def _drilldown_static(self, filename: str) -> None:
        if self.drilldown is None:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self._static(filename, DRILLDOWN_STATIC_ROOT, "no-cache", True)

    def _drilldown_snapshot(self, parsed) -> None:
        drilldown = self.drilldown
        if drilldown is None:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            values = parse_qs(parsed.query).get("report_date", [])
            requested_date = date.fromisoformat(values[0]) if values else None
            snapshot = drilldown.snapshot(requested_date)
            if snapshot and not self.signed_in:
                snapshot = redact_assembly_operators(snapshot)
            self._json(
                HTTPStatus.OK if snapshot else HTTPStatus.NOT_FOUND,
                snapshot or {"error": "No drill-down snapshot is available for that date yet. Use Refresh data to build it."},
                True,
            )
        except (ValueError, RestrictedRefreshError) as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)}, True)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlsplit(self.path)
        path = parsed.path
        if path in {"/", "/index.html"}:
            self._static("index.html")
        elif path == "/app.js":
            self._static("app.js")
        elif path == "/styles.css":
            self._static("styles.css")
        elif path == "/api/health":
            self._json(HTTPStatus.OK, self.state.health())
        elif path == "/api/snapshot":
            try:
                values = parse_qs(parsed.query).get("report_date", [])
                requested_date = date.fromisoformat(values[0]) if values else None
                snapshot = self.state.snapshot(requested_date)
                self._json(HTTPStatus.OK if snapshot else HTTPStatus.NOT_FOUND, snapshot or {"error": "No report snapshot has been generated for that date."})
            except (ValueError, RefreshError) as exc:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        elif path in {"/drilldown", "/drilldown/"}:
            self._drilldown_static("index.html")
        elif path in DRILLDOWN_ASSETS:
            self._drilldown_static(DRILLDOWN_ASSETS[path])
        elif path == "/api/drilldown/health":
            if self.drilldown is None:
                self.send_error(HTTPStatus.NOT_FOUND)
            else:
                self._json(HTTPStatus.OK, self.drilldown.health(), True)
        elif path == "/api/drilldown/snapshot":
            self._drilldown_snapshot(parsed)
        else:
            self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path
        if path == "/api/refresh":
            self._post_refresh(
                self.state.refresh,
                (ValueError, RefreshError),
                "The report refresh failed. Check the service journal for the bounded diagnostic.",
            )
        elif path == "/api/drilldown/refresh" and self.drilldown is not None:
            self._post_refresh(
                self._drilldown_refresh,
                (ValueError, RestrictedRefreshError),
                "The drill-down refresh failed. Check the service journal for the bounded diagnostic.",
                True,
            )
        else:
            self.send_error(HTTPStatus.NOT_FOUND)

    def _drilldown_refresh(self, report_date: date, force: bool = False) -> Dict[str, Any]:
        """Refresh response for the drill-down: the open wallboard port never receives assembly operator rows, here or in the GET view."""
        snapshot = self.drilldown.refresh(report_date, force=force)
        if snapshot and not self.signed_in:
            snapshot = redact_assembly_operators(snapshot)
        return snapshot

    def _post_refresh(self, refresh, expected_errors, failure_message: str, noindex: bool = False) -> None:
        if self.headers.get("X-Operations-KPI-Action") != "refresh":
            self._json(HTTPStatus.FORBIDDEN, {"error": "The refresh action header is required."}, noindex)
            return
        if not _is_private_address(self.client_address[0]):
            self._json(HTTPStatus.FORBIDDEN, {"error": "Report refresh is limited to private-network clients."}, noindex)
            return
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            content_length = 0
        if content_length <= 0 or content_length > 4096:
            self._json(HTTPStatus.BAD_REQUEST, {"error": "The request body is missing or too large."}, noindex)
            return
        try:
            payload = json.loads(self.rfile.read(content_length))
            requested_date = date.fromisoformat(str(payload.get("report_date", "")))
            force = payload.get("force", False)
            if not isinstance(force, bool):
                raise ValueError("force must be true or false.")
            snapshot = refresh(requested_date, force=force)
            self._json(HTTPStatus.OK, snapshot, noindex)
        except expected_errors as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)}, noindex)
        except Exception:
            self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": failure_message}, noindex)
            raise

    def log_message(self, fmt: str, *args: Any) -> None:
        print(json.dumps({"remote": self.client_address[0], "request": fmt % args}, separators=(",", ":")), flush=True)


class AuthContext:
    """What the sign-in listener needs: a ticket acceptor, the session codec, the allowlist, and an optional roster."""

    def __init__(self, acceptor: Any, sessions: SessionCodec, allowlist: Allowlist, roster: Optional[RosterService]) -> None:
        self.acceptor = acceptor
        self.sessions = sessions
        self.allowlist = allowlist
        self.roster = roster


class AuthServer(AppServer):
    def __init__(self, address, handler, app_state: AppState, drilldown_state: Optional[DrilldownState], auth: AuthContext):
        super().__init__(address, handler, app_state, drilldown_state)
        self.auth = auth

    def handle_error(self, request, client_address) -> None:  # noqa: D401 - keep failed TLS handshakes to one short line
        error = sys.exc_info()[1]
        print(json.dumps({"event": "auth-connection-error", "error": type(error).__name__}, separators=(",", ":")), flush=True)


class AuthHandler(Handler):
    """The same wallboard and drill-down, behind Windows sign-in. Only allowlisted identities get in."""

    timeout = 30
    signed_in = True

    def setup(self) -> None:
        self._extra_headers: List[Tuple[str, str]] = []
        super().setup()

    def end_headers(self) -> None:
        for name, value in self._extra_headers:
            self.send_header(name, value)
        super().end_headers()

    @property
    def auth(self) -> AuthContext:
        return self.server.auth  # type: ignore[attr-defined]

    def _page(self, status: int, title: str, message: str, headers: Tuple[Tuple[str, str], ...] = (),
              links: Tuple[Tuple[str, str], ...] = ()) -> None:
        extra = "".join("<p><a href=\"" + html.escape(url, quote=True) + "\">" + html.escape(label) + "</a></p>" for url, label in links)
        body = ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><title>" + html.escape(title)
                + "</title></head><body><h1>" + html.escape(title) + "</h1><p>" + html.escape(message) + "</p>" + extra
                + "</body></html>").encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        for name, value in headers:
            self.send_header(name, value)
        self._security_headers("no-store", True)
        self.end_headers()
        self.wfile.write(body)

    def _challenge(self, token: Optional[bytes] = None) -> None:
        value = "Negotiate" + ((" " + base64.b64encode(token).decode("ascii")) if token else "")
        self._page(
            HTTPStatus.UNAUTHORIZED,
            "Windows sign-in required",
            "This page signs you in with your Windows account. If your browser asks for a password, use your CLC account. "
            "If you were not asked and still see this message, open https://kpi.eliteenterprisesinc.com:5196/ from a CLC computer.",
            (("WWW-Authenticate", value),),
            OPEN_VIEW_LINKS,
        )

    def _forbidden(self, principal: str) -> None:
        self._page(
            HTTPStatus.FORBIDDEN,
            "Not on the access list",
            "You are signed in as " + sam_of(principal) + ", which is not on the short list for this site. Ask IT if you need access.",
            links=OPEN_VIEW_LINKS,
        )

    def _cookie_principal(self) -> Optional[str]:
        raw = self.headers.get("Cookie")
        if not raw:
            return None
        try:
            jar = SimpleCookie()
            jar.load(raw)
        except Exception:  # noqa: BLE001 - a malformed cookie is simply not a session
            return None
        morsel = jar.get(SESSION_COOKIE)
        return self.auth.sessions.verify(morsel.value) if morsel else None

    def _principal(self) -> Optional[str]:
        """Return the allowlisted principal, or send the 401/403 response and return None."""

        cached = self._cookie_principal()
        if cached and self.auth.allowlist.allows(cached):
            return cached
        token = parse_negotiate_header(self.headers.get("Authorization", ""))
        if token is None:
            self._challenge()
            return None
        try:
            principal, reply = self.auth.acceptor.accept(token)
        except Exception as exc:  # noqa: BLE001 - a bad ticket is a failed sign-in, not a server error
            print(json.dumps({"event": "auth-token-rejected", "error": type(exc).__name__}, separators=(",", ":")), flush=True)
            self._challenge()
            return None
        if not principal:
            self._challenge(reply)
            return None
        if not self.auth.allowlist.allows(principal):
            print(json.dumps({"event": "auth-denied", "principal": sam_of(principal)}, separators=(",", ":")), flush=True)
            self._forbidden(principal)
            return None
        self._extra_headers.append(("Set-Cookie", self.auth.sessions.cookie_header(principal)))
        if reply:
            self._extra_headers.append(("WWW-Authenticate", "Negotiate " + base64.b64encode(reply).decode("ascii")))
        print(json.dumps({"event": "auth-session-start", "principal": sam_of(principal)}, separators=(",", ":")), flush=True)
        return principal

    def _roster(self, parsed, principal: str) -> None:
        roster = self.auth.roster
        if roster is None:
            self._json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "Names are not configured on this server."}, True)
            return
        requested = clean_ids(",".join(parse_qs(parsed.query).get("ids", [])).split(","))
        try:
            people = roster.names_for(requested)
        except RosterUnavailable as exc:
            self._json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": str(exc)}, True)
            return
        print(json.dumps({"event": "roster-served", "principal": sam_of(principal), "requested": len(requested), "returned": len(people)}, separators=(",", ":")), flush=True)
        self._json(HTTPStatus.OK, {"people": people}, True)

    def do_GET(self) -> None:  # noqa: N802
        principal = self._principal()
        if principal is None:
            return
        parsed = urlsplit(self.path)
        if parsed.path == "/api/session":
            self._json(HTTPStatus.OK, {"authenticated": True, "principal": sam_of(principal), "names_allowed": self.auth.roster is not None}, True)
        elif parsed.path == "/api/roster":
            self._roster(parsed, principal)
        else:
            super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        if self._principal() is None:
            return
        super().do_POST()


def create_server(host: str, port: int, state: AppState, drilldown: Optional[DrilldownState] = None) -> AppServer:
    return AppServer((host, port), Handler, state, drilldown)


def create_auth_server(
    settings: AuthSettings,
    state: AppState,
    drilldown: Optional[DrilldownState] = None,
    acceptor: Any = None,
    roster: Optional[RosterService] = None,
    tls: bool = True,
) -> AuthServer:
    allowlist = Allowlist(settings.allowlist)
    if acceptor is None:
        acceptor = NegotiateAcceptor(settings.keytab, settings.service_principal)
    server = AuthServer((settings.bind_host, settings.port), AuthHandler, state, drilldown, AuthContext(acceptor, SessionCodec(), allowlist, roster))
    if tls:
        try:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            context.load_cert_chain(str(settings.tls_cert), str(settings.tls_key))
            server.socket = context.wrap_socket(server.socket, server_side=True, do_handshake_on_connect=False)
        except Exception:
            server.server_close()
            raise
    return server


def _roster_service() -> Optional[RosterService]:
    if not os.environ.get("KPI_ROSTER_PROCEDURE_HASH", "").strip():
        return None
    from .odbc import execute_roster

    return RosterService(lambda: roster_from_rows(execute_roster()))


def main() -> int:
    mode = os.environ.get("KPI_DATA_MODE", "fixture").lower()
    snapshot_dir = Path(os.environ.get("KPI_SNAPSHOT_DIR", "build/web-snapshots"))
    fixture_value = os.environ.get("KPI_FIXTURE_PATH", "")
    fixture_path = Path(fixture_value) if fixture_value else None
    state = AppState(mode=mode, snapshot_dir=snapshot_dir, fixture_path=fixture_path)
    drilldown: Optional[DrilldownState] = None
    try:
        drilldown = create_drilldown_state(mode, snapshot_dir)
    except Exception as exc:  # The aggregate wallboard must never depend on the drill-down.
        print(disabled_event(exc), flush=True)
    host = os.environ.get("KPI_BIND_HOST", "127.0.0.1")
    port = int(os.environ.get("KPI_PORT", "5193"))
    server = create_server(host, port, state, drilldown)
    # The sign-in listener is optional and can never take the aggregate wallboard down with it.
    auth_server: Optional[AuthServer] = None
    try:
        auth_settings = settings_from_env()
        if auth_settings is not None:
            auth_server = create_auth_server(auth_settings, state, drilldown, roster=_roster_service())
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"event": "auth-listener-disabled", "error": type(exc).__name__ + ": " + str(exc)[:200]}, separators=(",", ":")), flush=True)
    state.start_auto_refresh()
    if drilldown is not None:
        drilldown.start_auto_refresh()
    print(json.dumps({"status": "starting", "host": host, "port": port, "mode": mode, "auto_refresh_seconds": state.auto_refresh_seconds if mode == "live" else None, "drilldown": drilldown is not None}), flush=True)
    if auth_server is not None:
        threading.Thread(target=auth_server.serve_forever, kwargs={"poll_interval": 0.5}, name="operations-kpi-auth-listener", daemon=True).start()
        print(json.dumps({"event": "auth-listener-started", "host": auth_server.server_address[0], "port": auth_server.server_address[1], "allowlist_entries": auth_server.auth.allowlist.count, "names_configured": auth_server.auth.roster is not None}, separators=(",", ":")), flush=True)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        if auth_server is not None:
            auth_server.shutdown()
            auth_server.server_close()
        state.stop_auto_refresh()
        if drilldown is not None:
            drilldown.stop_auto_refresh()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
