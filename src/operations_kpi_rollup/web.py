"""Small dependency-free HTTP service for the on-demand internal dashboard."""

from __future__ import annotations

from datetime import date, datetime, timedelta
import hmac
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import os
from pathlib import Path
import threading
import time
from typing import Any, Dict, Optional
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from .context import validate_snapshot
from .live import refresh_live_snapshot


STATIC_ROOT = Path(__file__).parent / "web"
EARLIEST_SUPPORTED_DATE = date(2026, 9, 8)


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
        self._snapshot_lock = threading.RLock()
        self._refresh_lock = threading.Lock()
        self._last_refresh_monotonic = 0.0
        self._load_initial_snapshot()

    def _load_initial_snapshot(self) -> None:
        latest = self.snapshot_dir / "latest.json"
        source = latest if latest.is_file() else self.fixture_path
        if source and source.is_file():
            snapshot = json.loads(source.read_text(encoding="utf-8"))
            validate_snapshot(snapshot)
            self._snapshot = snapshot

    def snapshot(self) -> Optional[Dict[str, Any]]:
        with self._snapshot_lock:
            return json.loads(json.dumps(self._snapshot)) if self._snapshot is not None else None

    def health(self) -> Dict[str, Any]:
        current = self.snapshot()
        return {
            "status": "ok" if current else "ready_no_snapshot",
            "service": "operations-kpi-rollup",
            "mode": self.mode,
            "report_date": current.get("report_date") if current else None,
            "generated_at": current.get("generated_at") if current else None,
            "refresh_auth": "required" if self.mode == "live" else "fixture-only",
        }

    def refresh(self, report_date: date) -> Dict[str, Any]:
        if not self._refresh_lock.acquire(blocking=False):
            raise RefreshError("A report refresh is already in progress.")
        try:
            minimum_seconds = float(os.environ.get("KPI_MIN_REFRESH_SECONDS", "15"))
            elapsed = time.monotonic() - self._last_refresh_monotonic
            if self._last_refresh_monotonic and elapsed < minimum_seconds:
                raise RefreshError(f"Please wait {minimum_seconds - elapsed:.0f} seconds before refreshing again.")
            if report_date < EARLIEST_SUPPORTED_DATE:
                raise RefreshError(f"The recovered metric contract starts on {EARLIEST_SUPPORTED_DATE.isoformat()}.")
            today = datetime.now(ZoneInfo(os.environ.get("KPI_TIMEZONE", "America/Indiana/Indianapolis"))).date()
            if report_date > today:
                raise RefreshError("A future report date is not allowed.")

            if self.mode == "live":
                snapshot = refresh_live_snapshot(report_date)
            else:
                if not self.fixture_path or not self.fixture_path.is_file():
                    raise RefreshError("The fixture snapshot is unavailable.")
                snapshot = json.loads(self.fixture_path.read_text(encoding="utf-8"))
                validate_snapshot(snapshot)
                if snapshot["report_date"] != report_date.isoformat():
                    raise RefreshError("Fixture mode can only rebuild its recorded report date.")

            self._persist(snapshot)
            with self._snapshot_lock:
                self._snapshot = snapshot
            self._last_refresh_monotonic = time.monotonic()
            return self.snapshot() or snapshot
        finally:
            self._refresh_lock.release()

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


def _refresh_key() -> str:
    credential_dir = os.environ.get("CREDENTIALS_DIRECTORY", "")
    credential_name = os.environ.get("KPI_REFRESH_CREDENTIAL_NAME", "operations-kpi-refresh-key")
    if not credential_dir:
        return ""
    path = Path(credential_dir) / credential_name
    return path.read_text(encoding="utf-8").strip() if path.is_file() else ""


class AppServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, handler, app_state: AppState):
        super().__init__(address, handler)
        self.app_state = app_state


class Handler(BaseHTTPRequestHandler):
    server_version = "OperationsKPI/0.9"
    sys_version = ""

    @property
    def state(self) -> AppState:
        return self.server.app_state  # type: ignore[attr-defined]

    def _security_headers(self, cache_control: str) -> None:
        self.send_header("Cache-Control", cache_control)
        self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")

    def _json(self, status: int, payload: Any) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._security_headers("no-store")
        self.end_headers()
        self.wfile.write(body)

    def _static(self, filename: str) -> None:
        path = (STATIC_ROOT / filename).resolve()
        if path.parent != STATIC_ROOT.resolve() or not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        body = path.read_bytes()
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type + ("; charset=utf-8" if content_type.startswith("text/") or content_type.endswith("javascript") else ""))
        self.send_header("Content-Length", str(len(body)))
        self._security_headers("public, max-age=300" if filename != "index.html" else "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path
        if path in {"/", "/index.html"}:
            self._static("index.html")
        elif path == "/app.js":
            self._static("app.js")
        elif path == "/styles.css":
            self._static("styles.css")
        elif path == "/api/health":
            self._json(HTTPStatus.OK, self.state.health())
        elif path == "/api/snapshot":
            snapshot = self.state.snapshot()
            self._json(HTTPStatus.OK if snapshot else HTTPStatus.NOT_FOUND, snapshot or {"error": "No report snapshot has been generated."})
        else:
            self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        if urlsplit(self.path).path != "/api/refresh":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if self.headers.get("X-Operations-KPI-Action") != "refresh":
            self._json(HTTPStatus.FORBIDDEN, {"error": "The refresh action header is required."})
            return
        if self.state.mode == "live":
            expected = _refresh_key()
            supplied = self.headers.get("X-Operations-KPI-Refresh-Key", "")
            if not expected or not supplied or not hmac.compare_digest(expected, supplied):
                self._json(HTTPStatus.UNAUTHORIZED, {"error": "A valid refresh key is required."})
                return
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            content_length = 0
        if content_length <= 0 or content_length > 4096:
            self._json(HTTPStatus.BAD_REQUEST, {"error": "The request body is missing or too large."})
            return
        try:
            payload = json.loads(self.rfile.read(content_length))
            requested_date = date.fromisoformat(str(payload.get("report_date", "")))
            snapshot = self.state.refresh(requested_date)
            self._json(HTTPStatus.OK, snapshot)
        except (ValueError, RefreshError) as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        except Exception:
            self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "The report refresh failed. Check the service journal for the bounded diagnostic."})
            raise

    def log_message(self, fmt: str, *args: Any) -> None:
        print(json.dumps({"remote": self.client_address[0], "request": fmt % args}, separators=(",", ":")), flush=True)


def create_server(host: str, port: int, state: AppState) -> AppServer:
    return AppServer((host, port), Handler, state)


def main() -> int:
    mode = os.environ.get("KPI_DATA_MODE", "fixture").lower()
    snapshot_dir = Path(os.environ.get("KPI_SNAPSHOT_DIR", "build/web-snapshots"))
    fixture_value = os.environ.get("KPI_FIXTURE_PATH", "")
    fixture_path = Path(fixture_value) if fixture_value else None
    state = AppState(mode=mode, snapshot_dir=snapshot_dir, fixture_path=fixture_path)
    host = os.environ.get("KPI_BIND_HOST", "127.0.0.1")
    port = int(os.environ.get("KPI_PORT", "5193"))
    server = create_server(host, port, state)
    print(json.dumps({"status": "starting", "host": host, "port": port, "mode": mode}), flush=True)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
