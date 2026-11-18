import json
from pathlib import Path
import stat
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from operations_kpi_rollup.restricted_web import (
    RestrictedAccessError,
    RestrictedAuth,
    RestrictedState,
    create_restricted_server,
)


ALLOWED_ID = "11111111-2222-3333-4444-555555555555"
DENIED_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def fixture_snapshot():
    return {
        "contract_version": "1.0",
        "classification": "restricted-operational",
        "scope": {
            "method_version": "operations-kpi-restricted-v1",
            "history_start": "2026-09-08",
            "contains_named_people": True,
            "contains_part_level_detail": True,
            "public_wallboard_compatible": False,
        },
        "report_date": "2026-11-18",
        "generated_at": "2026-11-18T11:59:00-05:00",
        "painter_daily": [
            {
                "date": "2026-11-18",
                "painter": "Synthetic Painter",
                "booth": 1,
                "carts": 3,
                "pieces": 9,
                "minutes": 60,
                "pieces_per_hour": 9.0,
                "unique_colors": 2,
                "fty_total": 9,
                "fty_approved": 8,
                "fty_repair": 0,
                "fty_repaint": 1,
                "fty_pending": 0,
                "fty_percent": 88.8889,
            }
        ],
        "repaint": {
            "contributions": [
                {"dimension": "painter", "label": "Synthetic Painter", "repaint_events": 1, "unique_parts": 1, "contribution_percent": 100.0}
            ],
            "details": [
                {
                    "event_at": "2026-11-18T10:00:00",
                    "part_id": 1001,
                    "part_number": "PN-001",
                    "sequence": "SEQ-001",
                    "color": "Synthetic Color",
                    "painter": "Synthetic Painter",
                    "booth": 1,
                    "repaint_loop_count": 1,
                    "defect": "Synthetic defect",
                }
            ],
        },
        "finesse": {
            "summary": [
                {"date": "2026-11-18", "worker": "Synthetic Worker", "outcome": "repaint", "parts": 1, "average_minutes_per_part": 3.5, "max_repaint_count": 1}
            ],
            "details": [
                {
                    "event_at": "2026-11-18T10:15:00",
                    "part_id": 1001,
                    "part_number": "PN-001",
                    "sequence": "SEQ-001",
                    "color": "Synthetic Color",
                    "worker": "Synthetic Worker",
                    "outcome": "repaint",
                    "minutes_per_part": 3.5,
                    "repaint_count": 1,
                }
            ],
        },
    }


def perform(url, headers=None, method="GET", payload=None):
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(url, data=body, method=method, headers=headers or {})
    try:
        with urlopen(request, timeout=5) as response:
            return response.status, dict(response.headers), response.read()
    except HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read()


@pytest.fixture
def restricted_server(tmp_path):
    fixture = tmp_path / "fixture.json"
    fixture.write_text(json.dumps(fixture_snapshot()), encoding="utf-8")
    state = RestrictedState("fixture", tmp_path / "snapshots", fixture)
    auth = RestrictedAuth([ALLOWED_ID], ["127.0.0.1/32"])
    server = create_restricted_server("127.0.0.1", 0, state, auth)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield "http://127.0.0.1:" + str(server.server_address[1]), state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def authorized_headers(object_id=ALLOWED_ID):
    return {
        "X-CLC-Object-Id": object_id,
        "X-CLC-User": "synthetic.user@example.invalid",
        "X-CLC-Name": "Synthetic Reviewer",
    }


def test_auth_configuration_fails_closed_without_allowlist(monkeypatch):
    monkeypatch.delenv("KPI_RESTRICTED_ALLOWED_OBJECT_IDS", raising=False)
    monkeypatch.delenv("CREDENTIALS_DIRECTORY", raising=False)
    with pytest.raises(ValueError, match="one or more exact Entra object IDs"):
        RestrictedAuth.from_environment()


def test_auth_reads_exact_object_ids_from_systemd_credential(monkeypatch, tmp_path):
    credential = tmp_path / "operations-kpi-restricted-allowed-object-ids"
    credential.write_text(ALLOWED_ID + "\n", encoding="utf-8")
    monkeypatch.delenv("KPI_RESTRICTED_ALLOWED_OBJECT_IDS", raising=False)
    monkeypatch.setenv("CREDENTIALS_DIRECTORY", str(tmp_path))
    monkeypatch.setenv(
        "KPI_RESTRICTED_ALLOWED_OBJECT_IDS_CREDENTIAL",
        "operations-kpi-restricted-allowed-object-ids",
    )

    auth = RestrictedAuth.from_environment()

    assert auth.allowed_object_ids == frozenset({ALLOWED_ID})


def test_auth_requires_trusted_proxy_and_exact_object_id():
    auth = RestrictedAuth([ALLOWED_ID], ["127.0.0.1/32"])
    viewer = auth.authorize("127.0.0.1", authorized_headers())
    assert viewer["object_id"] == ALLOWED_ID
    with pytest.raises(RestrictedAccessError, match="not approved"):
        auth.authorize("127.0.0.1", authorized_headers(DENIED_ID))
    with pytest.raises(RestrictedAccessError, match="trusted proxy"):
        auth.authorize("203.0.113.10", authorized_headers())


def test_restricted_service_refuses_non_loopback_bind(tmp_path):
    fixture = tmp_path / "fixture.json"
    fixture.write_text(json.dumps(fixture_snapshot()), encoding="utf-8")
    state = RestrictedState("fixture", tmp_path / "snapshots", fixture)
    auth = RestrictedAuth([ALLOWED_ID], ["127.0.0.1/32"])
    with pytest.raises(ValueError, match="must bind to loopback"):
        create_restricted_server("0.0.0.0", 0, state, auth)


def test_healthz_is_minimal_and_does_not_require_identity(restricted_server):
    base, _ = restricted_server
    status, headers, body = perform(base + "/healthz")
    payload = json.loads(body)
    assert status == 200
    assert payload == {"status": "ok", "service": "operations-kpi-restricted"}
    assert "no-store" in headers["Cache-Control"]
    assert "viewer" not in payload
    assert "report_date" not in payload


def test_every_page_and_data_route_requires_identity(restricted_server):
    base, _ = restricted_server
    for path in ["/", "/styles.css", "/app.js", "/api/health", "/api/snapshot"]:
        status, _, body = perform(base + path)
        assert status == 403
        assert "not approved" in json.loads(body)["error"]


def test_exact_identity_can_read_restricted_page_and_snapshot(restricted_server):
    base, _ = restricted_server
    status, headers, body = perform(base + "/", authorized_headers())
    assert status == 200
    assert b"Operations KPI Restricted Drill-down" in body
    assert headers["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]
    assert "no-store" in headers["Cache-Control"]

    status, headers, body = perform(base + "/api/snapshot?report_date=2026-11-18", authorized_headers())
    payload = json.loads(body)
    assert status == 200
    assert payload["classification"] == "restricted-operational"
    assert payload["scope"]["public_wallboard_compatible"] is False
    assert payload["painter_daily"][0]["painter"] == "Synthetic Painter"
    assert "no-store" in headers["Cache-Control"]


def test_wrong_object_id_is_denied_even_with_valid_proxy_headers(restricted_server):
    base, _ = restricted_server
    status, _, body = perform(base + "/api/snapshot", authorized_headers(DENIED_ID))
    assert status == 403
    assert "not approved" in json.loads(body)["error"]


def test_refresh_requires_explicit_action_header(restricted_server):
    base, _ = restricted_server
    status, _, body = perform(
        base + "/api/refresh",
        dict(authorized_headers(), **{"Content-Type": "application/json"}),
        method="POST",
        payload={"report_date": "2026-11-18", "force": False},
    )
    assert status == 403
    assert "action header" in json.loads(body)["error"]


def test_restricted_snapshots_are_written_with_private_permissions(tmp_path):
    fixture = tmp_path / "fixture.json"
    fixture.write_text(json.dumps(fixture_snapshot()), encoding="utf-8")
    snapshot_dir = tmp_path / "snapshots"
    state = RestrictedState("fixture", snapshot_dir, fixture)
    state._persist(fixture_snapshot())
    assert stat.S_IMODE(snapshot_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE((snapshot_dir / "latest.json").stat().st_mode) == 0o600
    immutable = [path for path in snapshot_dir.glob("*.json") if path.name != "latest.json"]
    assert len(immutable) == 1
    assert stat.S_IMODE(immutable[0].stat().st_mode) == 0o600
