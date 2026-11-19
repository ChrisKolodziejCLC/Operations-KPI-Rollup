import json
import re
import os
from datetime import date
from pathlib import Path
import stat
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

import operations_kpi_rollup.drilldown as drilldown_module
import operations_kpi_rollup.odbc as odbc
from operations_kpi_rollup.drilldown import DrilldownState, create_drilldown_state
from operations_kpi_rollup.restricted import RestrictedContractError, validate_restricted_snapshot
from operations_kpi_rollup.web import AppState, create_server


EXAMPLE = Path(__file__).parents[1] / "examples" / "2026-09-16.json"
SRC = Path(__file__).parents[1] / "src" / "operations_kpi_rollup"
PROCEDURE_HASH = "9CF72B48DA59BBA526B0943F917793A020865D2C41DDDCA664BBB98850C970AF"


def drilldown_snapshot():
    return {
        "contract_version": "2.0",
        "classification": "restricted-operational",
        "scope": {
            "method_version": "operations-kpi-restricted-v2",
            "history_start": "2026-09-08",
            "contains_named_people": False,
            "contains_employee_ids": True,
            "contains_part_level_detail": True,
            "public_wallboard_compatible": False,
        },
        "report_date": "2026-11-18",
        "generated_at": "2026-11-18T11:59:00-05:00",
        "painter_daily": [
            {
                "date": "2026-11-18", "painter_id": "910001", "booth": 1, "carts": 3, "pieces": 9,
                "minutes": 60, "pieces_per_hour": 9.0, "unique_colors": 2, "fty_total": 9, "fty_approved": 8,
                "fty_repair": 0, "fty_repaint": 1, "fty_pending": 0, "fty_percent": 88.8889,
            }
        ],
        "repaint": {
            "contributions": [
                {"dimension": "painter", "label": "910001", "repaint_events": 1, "unique_parts": 1, "contribution_percent": 100.0}
            ],
            "details": [
                {
                    "event_at": "2026-11-18T10:00:00", "part_id": 1001, "part_number": "PN-001", "sequence": "SEQ-001",
                    "color": "Synthetic Color", "painter_id": "910001", "booth": 1, "repaint_loop_count": 1,
                    "defect": "Synthetic defect",
                }
            ],
        },
        "finesse": {
            "summary": [
                {"date": "2026-11-18", "worker_id": "910001", "outcome": "repaint", "parts": 1, "average_minutes_per_part": 3.5, "max_repaint_count": 1}
            ],
            "details": [
                {
                    "event_at": "2026-11-18T10:15:00", "part_id": 1001, "part_number": "PN-001", "sequence": "SEQ-001",
                    "color": "Synthetic Color", "worker_id": "910001", "outcome": "repaint", "minutes_per_part": 3.5,
                    "repaint_count": 1,
                }
            ],
        },
    }


def perform(url, method="GET", payload=None, headers=None):
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(url, data=body, method=method, headers=headers or {})
    try:
        with urlopen(request, timeout=5) as response:
            return response.status, dict(response.headers), response.read()
    except HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read()


def serve(tmp_path, with_drilldown=True):
    fixture = tmp_path / "drilldown-fixture.json"
    fixture.write_text(json.dumps(drilldown_snapshot()), encoding="utf-8")
    state = AppState("fixture", tmp_path / "snapshots", EXAMPLE)
    drilldown = DrilldownState("fixture", tmp_path / "snapshots" / "drilldown", fixture) if with_drilldown else None
    server = create_server("127.0.0.1", 0, state, drilldown)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, "http://127.0.0.1:" + str(server.server_address[1]), drilldown


def stop(server, thread):
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def test_standard_drilldown_is_served_without_any_identity(tmp_path):
    server, thread, base, _ = serve(tmp_path)
    try:
        for path in ("/drilldown", "/drilldown/"):
            status, headers, body = perform(base + path)
            assert status == 200
            html = body.decode("utf-8")
            assert "Operations KPI Drill-down" in html
            assert "Restricted" not in html and "restricted" not in html
            assert 'href="/"' in html
            assert headers["X-Robots-Tag"] == "noindex, nofollow"
            assert headers["Cache-Control"] == "no-cache"
        status, _, script = perform(base + "/drilldown/app.js")
        assert status == 200
        assert b"/api/drilldown/snapshot" in script and b"/api/drilldown/refresh" in script
        assert b"X-Operations-KPI-Restricted-Action" not in script and b"#viewer" not in script
        status, _, css = perform(base + "/drilldown/styles.css")
        assert status == 200 and b".pilot-badge" in css

        status, headers, body = perform(base + "/api/drilldown/health")
        health = json.loads(body)
        assert status == 200
        assert health["service"] == "operations-kpi-rollup-drilldown"
        assert health["refresh_boundary"] == "standard-wallboard-view"
        assert health["viewer"] is None
        assert headers["Cache-Control"] == "no-store"

        status, _, body = perform(base + "/api/drilldown/snapshot")
        snapshot = json.loads(body)
        assert status == 200
        assert snapshot["painter_daily"][0]["painter_id"] == "910001"
        status, _, body = perform(base + "/api/drilldown/snapshot?report_date=2026-11-17")
        assert status == 404 and "error" in json.loads(body)
        status, _, body = perform(base + "/api/drilldown/snapshot?report_date=not-a-date")
        assert status == 400
    finally:
        stop(server, thread)


def test_aggregate_wallboard_contract_and_assets_remain_free_of_named_detail(tmp_path):
    server, thread, base, _ = serve(tmp_path)
    try:
        status, _, body = perform(base + "/api/snapshot")
        assert status == 200
        text = body.decode("utf-8")
        for forbidden in ("910001", "painter_id", "painter_daily", "part_number", "repaint_loop_count"):
            assert forbidden not in text
        status, _, html = perform(base + "/")
        assert status == 200 and b'href="/drilldown/"' in html
    finally:
        stop(server, thread)
    for name in ("app.js", "index.html", "styles.css"):
        content = (SRC / "web" / name).read_text(encoding="utf-8")
        for forbidden in ("painter_daily", "repaint_loop_count", "/api/drilldown", "X-Operations-KPI-Restricted-Action"):
            assert forbidden not in content


def test_drilldown_refresh_requires_the_action_header_and_persists_privately(tmp_path):
    server, thread, base, state = serve(tmp_path)
    try:
        url = base + "/api/drilldown/refresh"
        payload = {"report_date": "2026-11-18", "force": True}
        status, _, _ = perform(url, "POST", payload, {"Content-Type": "application/json"})
        assert status == 403
        status, _, body = perform(
            url, "POST", payload,
            {"Content-Type": "application/json", "X-Operations-KPI-Action": "refresh"},
        )
        assert status == 200
        assert json.loads(body)["report_date"] == "2026-11-18"
        snapshots = tmp_path / "snapshots" / "drilldown"
        latest = snapshots / "latest.json"
        assert latest.is_file()
        assert stat.S_IMODE(latest.stat().st_mode) == 0o600
        assert stat.S_IMODE(snapshots.stat().st_mode) == 0o700
        # The aggregate wallboard snapshot directory never receives drill-down files.
        assert not list((tmp_path / "snapshots").glob("2026-11-18__*.json"))
        status, _, _ = perform(
            url, "POST", {"report_date": "2026-11-18", "force": "yes"},
            {"Content-Type": "application/json", "X-Operations-KPI-Action": "refresh"},
        )
        assert status == 400
    finally:
        stop(server, thread)


def test_drilldown_routes_are_absent_when_it_is_disabled(tmp_path):
    server, thread, base, _ = serve(tmp_path, with_drilldown=False)
    try:
        for path in ("/drilldown", "/drilldown/", "/drilldown/app.js", "/api/drilldown/health", "/api/drilldown/snapshot"):
            status, _, _ = perform(base + path)
            assert status == 404
        status, _, _ = perform(
            base + "/api/drilldown/refresh", "POST", {"report_date": "2026-11-18", "force": False},
            {"Content-Type": "application/json", "X-Operations-KPI-Action": "refresh"},
        )
        assert status == 404
        status, _, _ = perform(base + "/api/health")
        assert status == 200
    finally:
        stop(server, thread)


def test_drilldown_state_configuration_switches(tmp_path, monkeypatch):
    for name in (
        "KPI_DRILLDOWN_ENABLED", "KPI_DRILLDOWN_DATA_MODE", "KPI_DRILLDOWN_SNAPSHOT_DIR", "KPI_DRILLDOWN_FIXTURE_PATH",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("KPI_DRILLDOWN_INITIAL_DELAY_SECONDS", "0")
    live = create_drilldown_state("live", tmp_path / "wallboard")
    assert isinstance(live, DrilldownState)
    assert live.mode == "live" and live.snapshot_dir == tmp_path / "wallboard" / "drilldown"
    assert create_drilldown_state("fixture", tmp_path / "wallboard") is None
    monkeypatch.setenv("KPI_DRILLDOWN_SNAPSHOT_DIR", str(tmp_path / "elsewhere"))
    assert create_drilldown_state("live", tmp_path / "wallboard").snapshot_dir == tmp_path / "elsewhere"
    monkeypatch.setenv("KPI_DRILLDOWN_ENABLED", "0")
    assert create_drilldown_state("live", tmp_path / "wallboard") is None


def test_drilldown_live_refresh_uses_the_standard_detail_query(tmp_path, monkeypatch):
    monkeypatch.setenv("KPI_DRILLDOWN_INITIAL_DELAY_SECONDS", "0")
    calls = []
    monkeypatch.setattr(drilldown_module, "execute_standard_drilldown", lambda report_date: calls.append(report_date) or ["rows"])
    monkeypatch.setattr(drilldown_module, "build_restricted_snapshot", lambda report_date, rows: (calls.append(rows) or drilldown_snapshot()))
    monkeypatch.setattr(DrilldownState, "_today", lambda self: date(2026, 11, 18))
    state = DrilldownState("live", tmp_path / "drilldown")
    snapshot = state.refresh(date(2026, 11, 18), force=True)
    assert snapshot["report_date"] == "2026-11-18"
    assert calls == [date(2026, 11, 18), ["rows"]]
    assert (tmp_path / "drilldown" / "latest.json").is_file()
    with pytest.raises(drilldown_module.RestrictedRefreshError, match="Drill-down history starts on 2026-09-08"):
        state.refresh(date(2026, 9, 7), force=True)


def test_standard_drilldown_query_pins_the_wallboard_hash_and_requests_detail_sets(monkeypatch):
    captured = {}

    def fake_execute(query, wanted, credential_name):
        captured.update(query=query, wanted=set(wanted), credential_name=credential_name)
        return []

    monkeypatch.setattr(odbc, "execute_result_sets", fake_execute)
    monkeypatch.setenv("KPI_SQL_PROCEDURE_HASH", PROCEDURE_HASH.lower())
    monkeypatch.delenv("KPI_SQL_CREDENTIAL_NAME", raising=False)
    odbc.execute_standard_drilldown(date(2026, 11, 18))
    assert f"<> '{PROCEDURE_HASH}'" in captured["query"]
    assert "@ReportDateOverride = '2026-11-18'" in captured["query"]
    assert "@IncludeRestrictedDetail = 1" in captured["query"]
    assert captured["wanted"] == {16, 17, 18, 19, 20}
    assert captured["credential_name"] == "operations-kpi-qpts-ro"
    monkeypatch.setenv("KPI_SQL_PROCEDURE_HASH", "not-a-hash")
    with pytest.raises(odbc.OdbcError, match="KPI_SQL_PROCEDURE_HASH"):
        odbc.execute_standard_drilldown(date(2026, 11, 18))
    monkeypatch.delenv("KPI_SQL_PROCEDURE_HASH")
    with pytest.raises(odbc.OdbcError, match="KPI_SQL_PROCEDURE_HASH"):
        odbc.execute_standard_drilldown(date(2026, 11, 18))


def test_public_wallboard_query_still_excludes_detail_result_sets(monkeypatch):
    captured = {}
    monkeypatch.setattr(odbc, "execute_result_sets", lambda query, wanted, name: captured.update(query=query, wanted=set(wanted)) or [])
    monkeypatch.setenv("KPI_SQL_PROCEDURE_HASH", PROCEDURE_HASH)
    odbc.execute_operations_rollup(date(2026, 11, 18))
    assert "@IncludeRestrictedDetail = 0" in captured["query"]
    assert captured["wanted"].isdisjoint({8, 16, 17, 18, 19, 20})


def test_drilldown_page_always_opens_on_todays_date():
    script = (SRC / "drilldown_web" / "app.js").read_text(encoding="utf-8")
    start = script[script.index("async function start()"):]
    assert "localDateISO()" in start
    assert "health.report_date" not in start


def test_validator_rejects_snapshots_that_carry_person_names():
    validate_restricted_snapshot(drilldown_snapshot())
    for key in ("painter", "painter_name"):
        snapshot = drilldown_snapshot()
        snapshot["painter_daily"][0][key] = "Someone"
        with pytest.raises(RestrictedContractError, match="employee IDs, not names"):
            validate_restricted_snapshot(snapshot)
    snapshot = drilldown_snapshot()
    snapshot["finesse"]["summary"][0]["worker"] = "Someone"
    with pytest.raises(RestrictedContractError, match="employee IDs, not names"):
        validate_restricted_snapshot(snapshot)
    snapshot = drilldown_snapshot()
    snapshot["scope"]["contains_named_people"] = True
    with pytest.raises(RestrictedContractError):
        validate_restricted_snapshot(snapshot)


def test_snapshot_retention_keeps_the_newest_three_files_per_report_date(tmp_path):
    state = DrilldownState("live", tmp_path / "drilldown")
    snapshot = drilldown_snapshot()
    for _ in range(6):
        state._persist(snapshot)
    files = sorted((tmp_path / "drilldown").glob("2026-11-18__*.json"))
    assert len(files) == 3
    assert (tmp_path / "drilldown" / "latest.json").is_file()


def test_incompatible_old_snapshots_are_discarded_instead_of_disabling_the_drilldown(tmp_path):
    directory = tmp_path / "drilldown"
    directory.mkdir()
    old = drilldown_snapshot()
    old["contract_version"] = "1.0"
    old["scope"]["method_version"] = "operations-kpi-restricted-v1"
    old["scope"]["contains_named_people"] = True
    old["scope"].pop("contains_employee_ids")
    for name in ("latest.json", "2026-11-18__1.json", "2026-11-17__2.json"):
        (directory / name).write_text(json.dumps(old), encoding="utf-8")
    state = DrilldownState("live", directory)
    assert state.snapshot(date(2026, 11, 18)) is None
    assert not list(directory.glob("*.json"))
    state._persist(drilldown_snapshot())
    assert DrilldownState("live", directory).snapshot(date(2026, 11, 18))["report_date"] == "2026-11-18"


def test_drilldown_ui_shows_ids_plain_part_ids_and_trend_charts():
    script = (SRC / "drilldown_web" / "app.js").read_text(encoding="utf-8")
    page = (SRC / "drilldown_web" / "index.html").read_text(encoding="utf-8")
    assert script.count("{key: 'part_id', label: 'Part ID', format: plainId}") == 2
    assert "format: integer}" not in script.split("label: 'Part ID'")[1].split("\n")[0]
    for name in ("renderTrends", "renderPeriodStack", "renderPeriodLines", "periodKeys"):
        assert "function " + name + "(" in script
    assert "renderTrends(snapshot);" in script
    assert "Last 13 weeks" in script and "'Monthly'" in script
    for container in ("painter-trends", "repaint-trends", "finesse-trends"):
        assert 'id="' + container + '"' in page
    assert "painter-history" not in page and "renderPainterHistory" not in script
    assert "row.painter)" not in script and "row.worker)" not in script
    assert "Painter ID" in script and "Worker ID" in script

def _chart_kit(script):
    start = script.index("// <chart-kit>")
    end_marker = "// </chart-kit>\n"
    return script[start:script.index(end_marker) + len(end_marker)]


def test_wallboard_and_drilldown_share_one_chart_kit():
    wallboard = (SRC / "web" / "app.js").read_text(encoding="utf-8")
    drilldown = (SRC / "drilldown_web" / "app.js").read_text(encoding="utf-8")
    assert _chart_kit(wallboard) == _chart_kit(drilldown)
    kit = _chart_kit(drilldown)
    for name in ("CHART_SERIES_COLORS", "CHART_SERIES_MARKERS", "chartMarker", "chartLegendKey", "bindSeriesHighlight"):
        assert name in kit
    assert "stroke-dasharray" in kit and "data-series" in kit
    assert len(set(re.findall(r"#[0-9A-Fa-f]{6}", kit.split("CHART_SERIES_COLORS = ")[1].split("]")[0]))) == 8


def test_chart_series_and_legends_support_hover_highlight_and_dashed_swatches():
    wallboard = (SRC / "web" / "app.js").read_text(encoding="utf-8")
    drilldown = (SRC / "drilldown_web" / "app.js").read_text(encoding="utf-8")
    for script in (wallboard, drilldown):
        assert "bindSeriesHighlight(container)" in script
        assert "'data-series'" in script
    assert "dash: '6 4'" in drilldown and "line: true" in drilldown
    assert "dash:reference.dash" in wallboard and "dash:'7 5'" in wallboard
    for sheet in ("web", "drilldown_web"):
        css = (SRC / sheet / "styles.css").read_text(encoding="utf-8")
        assert ".has-highlight" in css and "[data-series]" in css and ".legend-swatch-holder" in css


def test_unassigned_categories_are_left_out_of_charts_with_a_footnote():
    script = (SRC / "drilldown_web" / "app.js").read_text(encoding="utf-8")
    page = (SRC / "drilldown_web" / "index.html").read_text(encoding="utf-8")
    for name in ("isUnassigned", "unassignedCounts", "renderUnassignedNote"):
        assert "function " in script and name in script
    for note in ("painter-footnote", "repaint-footnote", "finesse-footnote"):
        assert 'id="' + note + '"' in page
        assert "'#" + note + "'" in script
    assert "!isUnassigned(row.painter_id)" in script and "!isUnassigned(row.worker_id)" in script
    assert "Unassigned records found" in script
