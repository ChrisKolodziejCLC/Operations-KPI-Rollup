import json
from pathlib import Path
import threading
from urllib.request import Request, urlopen

import operations_kpi_rollup.web as web
from operations_kpi_rollup.web import AppState, _is_private_address, create_server


FIXTURE = Path(__file__).parents[1] / "examples" / "2026-09-16.json"


def request_json(url, method="GET", payload=None, headers=None):
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(url, data=body, method=method, headers=headers or {})
    with urlopen(request, timeout=5) as response:
        return response.status, json.loads(response.read())


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

        status, snapshot = request_json(base + "/api/snapshot")
        assert status == 200
        assert snapshot["report_date"] == "2026-09-16"

        status, refreshed = request_json(
            base + "/api/refresh",
            method="POST",
            payload={"report_date": "2026-09-16"},
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
            assert "dualYieldCard('PPY (Paint Process Yield)'" in javascript
            assert "dualYieldCard('FTY (First Time Yield)'" in javascript
            assert "['Repaint %', percent(ratio(current.paint_fty_repaint_count, current.paint_fty_total))" in javascript
            assert "current.ppy_repaint_count" in javascript
            assert "reject_ppy_approved" in javascript
            assert "reject_fty_approved" in javascript
            assert "yieldRatio(metric.numerator, metric.denominator)" in javascript
            assert "fuka_trailers_prepared" in javascript
            assert "rangeLabel(snapshot.daily)" in javascript
            assert "WALLBOARD_REFRESH_MS = 5 * 60 * 1000" in javascript
            assert "refreshReport(localDateISO(), true)" in javascript
            assert "X-Operations-KPI-Refresh-Key" not in javascript
            assert "sessionStorage" not in javascript

        with urlopen(base + "/styles.css", timeout=5) as response:
            styles = response.read().decode("utf-8")
            assert response.status == 200
            assert ".split-count-card{container-type:inline-size}" in styles
            assert "font-size:min(7.5cqw,1.75rem)" in styles
            assert "font-size:min(7.5cqw,2.2rem)" in styles
            assert ".dual-yield-grid{display:grid;grid-template-columns:1fr 1fr" in styles
            assert ".dual-yield-value" in styles
            assert "white-space:nowrap" in styles
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_live_refresh_uses_private_lan_boundary_without_browser_key(tmp_path, monkeypatch):
    monkeypatch.setenv("KPI_MIN_REFRESH_SECONDS", "0")
    source = json.loads(FIXTURE.read_text(encoding="utf-8"))
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
            payload={"report_date": source["report_date"]},
            headers={"Content-Type": "application/json", "X-Operations-KPI-Action": "refresh"},
        )
        assert status == 200
        assert refreshed["report_date"] == source["report_date"]
        status, health = request_json(base + "/api/health")
        assert status == 200
        assert health["refresh_boundary"] == "private-lan-bounded"
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
