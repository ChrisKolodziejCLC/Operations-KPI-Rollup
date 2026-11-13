import json
from pathlib import Path
import threading
from urllib.request import Request, urlopen

from operations_kpi_rollup.web import AppState, create_server


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
            assert "Pull current report" in html

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
            assert "rateBreakdown(current, 'ppy_approved', 'paint_decision_pieces')" in javascript
            assert "fuka_trailers_prepared" in javascript
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
