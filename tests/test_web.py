import json
from pathlib import Path
import threading
from datetime import datetime, timedelta
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

import operations_kpi_rollup.web as web
from operations_kpi_rollup.live import CURRENT_METHOD_VERSION
from operations_kpi_rollup.web import AppState, _is_private_address, create_server


FIXTURE = Path(__file__).parents[1] / "examples" / "2026-09-16.json"


def request_json(url, method="GET", payload=None, headers=None):
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(url, data=body, method=method, headers=headers or {})
    with urlopen(request, timeout=5) as response:
        return response.status, json.loads(response.read())


def snapshot_for(report_date):
    snapshot = json.loads(FIXTURE.read_text(encoding="utf-8"))
    date_text = report_date.isoformat()
    snapshot["report_date"] = date_text
    snapshot["generated_at"] = datetime.now(ZoneInfo("America/Indiana/Indianapolis")).isoformat(timespec="seconds")
    snapshot["daily"][-1]["date"] = date_text
    snapshot["scope"]["method_version"] = CURRENT_METHOD_VERSION
    return snapshot


def test_fixture_wallboard_serves_and_persists_refresh(tmp_path, monkeypatch):
    monkeypatch.setenv("KPI_MIN_REFRESH_SECONDS", "0")
    state = AppState("fixture", tmp_path / "snapshots", FIXTURE)
    server = create_server("127.0.0.1", 0, state)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        status, health = request_json(base + "/api/health")
        assert status == 200
        assert health["status"] == "ok"
        assert health["mode"] == "fixture"
        assert health["refresh_boundary"] == "fixture-only"
        assert health["refresh_in_progress"] is False
        assert health["next_auto_refresh_at"] is None
        assert datetime.fromisoformat(health["server_time"]).tzinfo is not None

        status, snapshot = request_json(base + "/api/snapshot")
        assert status == 200
        assert snapshot["report_date"] == "2026-09-16"

        status, dated_snapshot = request_json(base + "/api/snapshot?report_date=2026-09-16")
        assert status == 200
        assert dated_snapshot["report_date"] == "2026-09-16"

        status, refreshed = request_json(
            base + "/api/refresh",
            method="POST",
            payload={"report_date": "2026-09-16", "force": True},
            headers={"Content-Type": "application/json", "X-Operations-KPI-Action": "refresh"},
        )
        assert status == 200
        assert refreshed["report_date"] == "2026-09-16"
        assert (tmp_path / "snapshots" / "latest.json").is_file()
        assert len(list((tmp_path / "snapshots").glob("2026-09-16__*.json"))) == 1

        with urlopen(base + "/", timeout=5) as response:
            html = response.read().decode("utf-8")
            assert response.status == 200
            assert "Operations KPI Rollup" in html
            assert "Load selected day" in html
            assert "Previous" in html
            assert "Today" in html
            assert "Next" in html
            assert 'id="report-range"' in html
            assert "refresh-key" not in html
            assert "0.15.0-yield-detail-rows" in html
            assert 'id="refresh-countdown"' in html

        with urlopen(base + "/app.js", timeout=5) as response:
            javascript = response.read().decode("utf-8")
            assert response.status == 200
            assert "production_parts_loaded" in javascript
            assert "bv_parts_loaded" in javascript
            assert "service_parts_loaded" in javascript
            assert "production_carts_loaded" in javascript
            assert "bv_carts_loaded" in javascript
            assert "service_carts_loaded" in javascript
            assert "production_paint_carts" in javascript
            assert "bv_paint_carts" in javascript
            assert "service_paint_carts" in javascript
            assert "production_paint_pieces_processed" in javascript
            assert "bv_paint_pieces_processed" in javascript
            assert "service_paint_pieces_processed" in javascript
            assert "unique_pieces_loaded" in javascript
            assert "unique_pieces_processed" in javascript
            assert "splitMetricCard('Pieces loaded', current.parts_loaded" in javascript
            assert "splitMetricCard('Pieces painted', current.paint_pieces_processed" in javascript
            assert "unique === undefined ? '—' : integer(unique)" in javascript
            assert "metric-split-total" in javascript
            assert "${integer(row.production)} Prd / ${integer(row.bv)} BV / ${integer(row.service)} Svc" in javascript
            assert "dualYieldCard('PPY (Paint Process Yield)'" in javascript
            assert "dualYieldCard('FTY (First Time Yield)'" in javascript
            assert "metric.details.forEach" in javascript
            assert "'Repaint' : 'Repaints'" in javascript
            assert "`${integer(current.reject_ppy_pending_count)} Pending`" in javascript
            assert "`${integer(current.reject_fty_pending_count)} Pending`" in javascript
            assert "['Repaint %', percent(ratio(current.paint_fty_repaint_count, current.paint_fty_total))" in javascript
            assert "current.ppy_repaint_count" in javascript
            assert "reject_ppy_approved" in javascript
            assert "reject_fty_approved" in javascript
            assert "yieldRatio(metric.numerator, metric.denominator)" in javascript
            assert "fuka_racks_shipped" in javascript
            assert "bumper_racks_shipped" in javascript
            assert "fairing_racks_shipped" in javascript
            assert "Rack detail pending refresh" in javascript
            assert "count === 1 ? 'rack' : 'racks'" in javascript
            assert "return values.join(' / ')" not in javascript
            assert "shippedPieceDetail(snapshot)" in javascript
            assert "`${integer(counts.fuka)} FUKA`" in javascript
            assert "`${integer(counts.bumpers)} Bumpers`" in javascript
            assert "`${integer(counts.fairings)} Fairings`" in javascript
            assert "repaintLineSetDetail(current)" in javascript
            assert "${integer(row.fuka_paint_fty_repaint_count)} FUKA / ${integer(row.bumper_paint_fty_repaint_count)} Bumpers / ${integer(row.fairing_paint_fty_repaint_count)} Fairings" in javascript
            assert "provisional · not standard OEE" in javascript
            assert "N33 / Chassis Fairing · dated by last assembled piece" in javascript
            assert "N71-6171 · AssembledDate" in javascript
            assert "metric-detail-list" in javascript
            assert "metric-detail-row" in javascript
            assert "First Decisions" in javascript
            assert "by receive stamp" not in javascript
            assert "by final stamp" not in javascript
            assert "rangeLabel(snapshot.daily)" in javascript
            assert "WALLBOARD_POLL_MS = 30 * 1000" in javascript
            assert "HEALTH_POLL_MS = 5 * 1000" in javascript
            assert "COUNTDOWN_TICK_MS = 1000" in javascript
            assert "health.next_auto_refresh_at" in javascript
            assert "health.server_time" in javascript
            assert "serverClockOffsetMs" in javascript
            assert "Auto refresh in ${minutes}:${seconds}" in javascript
            assert javascript.index("['Pieces shipped'") > javascript.index("['Assembled bumpers'")
            assert javascript.index("['Pieces shipped'") < javascript.index("['Trailers prepared'")
            assert "loadCachedReport(localDateISO(), true)" in javascript
            assert "refreshReport(localDateISO(), true)" not in javascript
            assert "X-Operations-KPI-Refresh-Key" not in javascript
            assert "sessionStorage" not in javascript

        with urlopen(base + "/styles.css", timeout=5) as response:
            styles = response.read().decode("utf-8")
            assert response.status == 200
            assert ".split-count-card{container-type:inline-size}" in styles
            assert ".metric-detail-list{display:grid" in styles
            assert "font-size:min(7.5cqw,1.75rem)" in styles
            assert "font-size:min(7.5cqw,2.2rem)" in styles
            assert ".dual-yield-grid{display:grid;grid-template-columns:1fr 1fr" in styles
            assert ".dual-yield-value" in styles
            assert ".dual-yield-details{display:grid" in styles
            assert "white-space:nowrap" in styles
            assert ".header-status .refresh-countdown" in styles
            assert ".metric-card .metric-detail-row" in styles
            assert "font-variant-numeric:tabular-nums" in styles
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_live_refresh_uses_private_lan_boundary_without_browser_key(tmp_path, monkeypatch):
    monkeypatch.setenv("KPI_MIN_REFRESH_SECONDS", "0")
    source = json.loads(FIXTURE.read_text(encoding="utf-8"))
    source["scope"]["method_version"] = CURRENT_METHOD_VERSION
    monkeypatch.setattr(web, "refresh_live_snapshot", lambda report_date: source)
    state = AppState("live", tmp_path / "snapshots", FIXTURE)
    server = create_server("127.0.0.1", 0, state)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        status, refreshed = request_json(
            base + "/api/refresh",
            method="POST",
            payload={"report_date": source["report_date"], "force": True},
            headers={"Content-Type": "application/json", "X-Operations-KPI-Action": "refresh"},
        )
        assert status == 200
        assert refreshed["report_date"] == source["report_date"]
        status, health = request_json(base + "/api/health")
        assert status == 200
        assert health["refresh_boundary"] == "private-lan-bounded"
        assert health["last_refresh_source"] == "live-query"
        assert health["last_query_duration_seconds"] is not None
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_refresh_private_address_boundary():
    assert _is_private_address("127.0.0.1")
    assert _is_private_address("192.168.7.137")
    assert _is_private_address("::ffff:192.168.7.137")
    assert not _is_private_address("8.8.8.8")
    assert not _is_private_address("not-an-address")


def test_historical_refresh_reuses_newest_immutable_snapshot(tmp_path, monkeypatch):
    monkeypatch.setenv("KPI_MIN_REFRESH_SECONDS", "0")
    source = json.loads(FIXTURE.read_text(encoding="utf-8"))
    source["scope"]["method_version"] = CURRENT_METHOD_VERSION
    report_date = datetime.fromisoformat(source["report_date"]).date()
    calls = []

    def fake_refresh(requested_date):
        calls.append(requested_date)
        return json.loads(json.dumps(source))

    monkeypatch.setattr(web, "refresh_live_snapshot", fake_refresh)
    state = AppState("live", tmp_path / "snapshots")

    first = state.refresh(report_date, force=True)
    second = state.refresh(report_date)

    assert first == second
    assert calls == [report_date]
    assert len(list((tmp_path / "snapshots").glob("2026-09-16__*.json"))) == 1
    assert state.health()["last_refresh_source"] == "historical-cache"


def test_current_day_refresh_is_deduplicated_inside_freshness_window(tmp_path, monkeypatch):
    monkeypatch.setenv("KPI_MIN_REFRESH_SECONDS", "0")
    monkeypatch.setenv("KPI_REFRESH_FRESHNESS_SECONDS", "600")
    state = AppState("live", tmp_path / "snapshots")
    today = state._today()
    source = snapshot_for(today)
    calls = []

    def fake_refresh(requested_date):
        calls.append(requested_date)
        return json.loads(json.dumps(source))

    monkeypatch.setattr(web, "refresh_live_snapshot", fake_refresh)

    first = state.refresh(today, force=True)
    second = state.refresh(today)

    assert first == second
    assert calls == [today]
    health = state.health()
    assert health["last_refresh_source"] == "fresh-cache"
    assert health["refresh_freshness_seconds"] == 600
    next_refresh = datetime.fromisoformat(health["next_auto_refresh_at"])
    generated_at = datetime.fromisoformat(first["generated_at"])
    assert (next_refresh - generated_at).total_seconds() == 600


def test_historical_cache_is_recovered_after_a_newer_current_snapshot(tmp_path, monkeypatch):
    monkeypatch.setenv("KPI_MIN_REFRESH_SECONDS", "0")
    snapshot_dir = tmp_path / "snapshots"
    historical = json.loads(FIXTURE.read_text(encoding="utf-8"))
    legacy_method = historical["scope"]["method_version"]
    monkeypatch.setattr(web, "CURRENT_METHOD_VERSION", legacy_method)
    historical_date = datetime.fromisoformat(historical["report_date"]).date()
    first_state = AppState("live", snapshot_dir)
    today = first_state._today()
    current = snapshot_for(today)
    current["scope"]["method_version"] = legacy_method

    def first_refresh(requested_date):
        source = historical if requested_date == historical_date else current
        return json.loads(json.dumps(source))

    monkeypatch.setattr(web, "refresh_live_snapshot", first_refresh)
    first_state.refresh(historical_date, force=True)
    first_state.refresh(today, force=True)

    second_state = AppState("live", snapshot_dir)

    def unexpected_refresh(_requested_date):
        raise AssertionError("historical cache should avoid a live query")

    monkeypatch.setattr(web, "refresh_live_snapshot", unexpected_refresh)
    recovered = second_state.refresh(historical_date)

    assert recovered["report_date"] == historical_date.isoformat()
    assert second_state.health()["last_refresh_source"] == "historical-cache"


def test_stale_current_snapshot_runs_the_live_query(tmp_path, monkeypatch):
    monkeypatch.setenv("KPI_MIN_REFRESH_SECONDS", "0")
    monkeypatch.setenv("KPI_REFRESH_FRESHNESS_SECONDS", "600")
    state = AppState("live", tmp_path / "snapshots")
    today = state._today()
    stale = snapshot_for(today)
    stale["generated_at"] = (
        datetime.now(ZoneInfo("America/Indiana/Indianapolis")) - timedelta(minutes=20)
    ).isoformat(timespec="seconds")
    fresh = snapshot_for(today)
    responses = [stale, fresh]
    calls = []

    def fake_refresh(requested_date):
        calls.append(requested_date)
        return json.loads(json.dumps(responses.pop(0)))

    monkeypatch.setattr(web, "refresh_live_snapshot", fake_refresh)
    state.refresh(today, force=True)
    state.refresh(today)

    assert calls == [today, today]
    assert state.health()["last_refresh_source"] == "live-query"


def test_live_state_runs_one_server_owned_initial_refresh(tmp_path, monkeypatch):
    state = AppState("live", tmp_path / "snapshots", FIXTURE)
    called = threading.Event()
    calls = []

    def fake_refresh(report_date, force=False):
        calls.append((report_date, force))
        called.set()
        return json.loads(FIXTURE.read_text(encoding="utf-8"))

    monkeypatch.setattr(state, "refresh", fake_refresh)
    state.start_auto_refresh()
    try:
        assert called.wait(timeout=2)
        assert calls == [(state._today(), False)]
        assert state.health()["auto_refresh_running"] is True
    finally:
        state.stop_auto_refresh()
