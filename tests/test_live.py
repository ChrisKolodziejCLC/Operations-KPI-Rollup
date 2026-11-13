from datetime import date, datetime
from zoneinfo import ZoneInfo

from operations_kpi_rollup.live import snapshot_from_rollup
from operations_kpi_rollup.context import prepare_context, validate_snapshot
from operations_kpi_rollup import odbc
from operations_kpi_rollup.odbc import parse_connection_string


def metric_row(period_type, start, end, available=1, days=1):
    return {
        "period_label": start,
        "period_type": period_type,
        "period_start": start,
        "period_end": end,
        "data_available": str(available),
        "calendar_days": "1",
        "data_days": str(days),
        "parts_loaded": "100",
        "production_parts_loaded": "75",
        "service_parts_loaded": "25",
        "carts_loaded": "40",
        "production_carts_loaded": "30",
        "service_carts_loaded": "10",
        "paint_processed": "35",
        "production_paint_carts": "25",
        "service_paint_carts": "10",
        "paint_pieces_processed": "96",
        "production_paint_pieces_processed": "70",
        "service_paint_pieces_processed": "26",
        "paint_decision_pieces": "95",
        "ppy_approved": "90",
        "paint_fty_total": "92",
        "paint_fty_approved": "88",
        "paint_fty_repaint_count": "3",
        "receiving_total": "99",
        "receiving_approved": "97",
        "final_total": "101",
        "final_approved": "100",
        "eol_inspected": "98",
        "painted_parts_shipped": "85",
        "bumpers_shipped": "55",
        "parts_shipped": "90",
        "complete_assy_sets": "12",
        "assembled_bumper_count": "25",
        "trailers_prepared": "4",
        "pieces_scheduled": "100",
        "hours_scheduled": "10",
        "paint_hours": "9",
    }


def result_sets():
    return [
        {"index": 0, "rows": [{"history_start": "2026-09-08", "report_date": "2026-11-11"}]},
        {"index": 2, "rows": [metric_row("DAY", "2026-11-10", "2026-11-10"), metric_row("DAY", "2026-11-11", "2026-11-11")]},
        {"index": 3, "rows": [metric_row("WEEK", "2026-11-08", "2026-11-11", days=3)]},
        {"index": 4, "rows": [metric_row("MONTH", "2026-11-01", "2026-11-11", days=8)]},
        {"index": 5, "rows": [metric_row("QUARTER", "2026-10-01", "2026-11-11", days=30)]},
        {"index": 9, "rows": [{"inspection_step": "End of Line", "defect_description": "Dirt", "defect_count": "7"}]},
        {"index": 12, "rows": [{"report_date": "2026-11-11", "line_set": "Bumpers", "pieces_shipped": "55"}]},
    ]


def test_connection_string_parser_handles_braces_and_quoted_values():
    parsed = parse_connection_string("Server={brak};Database='Production Tracking (Version 1.0.0)SQL';UID=user;PWD={p;ass}}word};")
    assert parsed["server"] == "brak"
    assert parsed["database"] == "Production Tracking (Version 1.0.0)SQL"
    assert parsed["pwd"] == "p;ass}word"


def test_rollup_result_sets_become_valid_immutable_snapshot(monkeypatch):
    monkeypatch.setenv("KPI_SQL_PROCEDURE_HASH", "7a2992fa73cc9bf282148a2179789e651141057a1225475a5c1360c0c655083e")
    generated = datetime(2026, 11, 12, 12, 30, tzinfo=ZoneInfo("America/Indiana/Indianapolis"))
    snapshot = snapshot_from_rollup(date(2026, 11, 11), result_sets(), generated_at=generated)

    assert snapshot["report_date"] == "2026-11-11"
    assert snapshot["generated_at"] == "2026-11-12T12:30:00-05:00"
    assert snapshot["daily"][-1]["paint_carts"] == 35
    assert snapshot["daily"][-1]["production_paint_carts"] == 25
    assert snapshot["daily"][-1]["service_paint_carts"] == 10
    assert snapshot["daily"][-1]["paint_pieces_processed"] == 96
    assert snapshot["daily"][-1]["production_paint_pieces_processed"] == 70
    assert snapshot["daily"][-1]["service_paint_pieces_processed"] == 26
    assert snapshot["daily"][-1]["production_parts_loaded"] == 75
    assert snapshot["daily"][-1]["service_parts_loaded"] == 25
    assert snapshot["daily"][-1]["production_carts_loaded"] == 30
    assert snapshot["daily"][-1]["service_carts_loaded"] == 10
    cards = prepare_context(snapshot)["cards"]
    assert cards[0]["value"] == "30 Prd / 10 Svc"
    assert cards[0]["detail"] == "Carts · 75 Prd / 25 Svc parts"
    assert cards[1]["value"] == "25 Prd / 10 Svc"
    assert cards[1]["detail"] == "Carts · 70 Prd / 26 Svc pieces"
    assert [row["period_type"] for row in snapshot["periods"]] == ["WEEK", "MONTH", "QUARTER"]
    assert snapshot["top_defects"] == [{"step": "End of Line", "description": "Dirt", "count": 7}]
    assert snapshot["shipping"][0]["pieces"] == 55
    assert snapshot["painters"] == []
    assert snapshot["source_evidence"]["detail_result_sets_requested"] is False
    assert snapshot["source_evidence"]["procedure_definition_sha256"] == "7A2992FA73CC9BF282148A2179789E651141057A1225475A5C1360C0C655083E"
    assert snapshot["scope"]["method_version"] == "operations-kpi-live-v4-paint-service-split"


def test_load_split_must_equal_total():
    generated = datetime(2026, 11, 12, 12, 30, tzinfo=ZoneInfo("America/Indiana/Indianapolis"))
    snapshot = snapshot_from_rollup(date(2026, 11, 11), result_sets(), generated_at=generated)
    snapshot["daily"][-1]["service_parts_loaded"] = 24

    try:
        validate_snapshot(snapshot)
    except ValueError as error:
        assert str(error) == "daily load split does not equal parts_loaded"
    else:
        raise AssertionError("invalid load split was accepted")


def test_cart_split_must_equal_total():
    generated = datetime(2026, 11, 12, 12, 30, tzinfo=ZoneInfo("America/Indiana/Indianapolis"))
    snapshot = snapshot_from_rollup(date(2026, 11, 11), result_sets(), generated_at=generated)
    snapshot["daily"][-1]["service_carts_loaded"] = 9

    try:
        validate_snapshot(snapshot)
    except ValueError as error:
        assert str(error) == "daily cart split does not equal carts_loaded"
    else:
        raise AssertionError("invalid cart split was accepted")


def test_paint_cart_split_must_equal_total():
    generated = datetime(2026, 11, 12, 12, 30, tzinfo=ZoneInfo("America/Indiana/Indianapolis"))
    snapshot = snapshot_from_rollup(date(2026, 11, 11), result_sets(), generated_at=generated)
    snapshot["daily"][-1]["service_paint_carts"] = 9

    try:
        validate_snapshot(snapshot)
    except ValueError as error:
        assert str(error) == "daily paint cart split does not equal paint_carts"
    else:
        raise AssertionError("invalid paint cart split was accepted")


def test_paint_piece_split_must_equal_total():
    generated = datetime(2026, 11, 12, 12, 30, tzinfo=ZoneInfo("America/Indiana/Indianapolis"))
    snapshot = snapshot_from_rollup(date(2026, 11, 11), result_sets(), generated_at=generated)
    snapshot["daily"][-1]["service_paint_pieces_processed"] = 25

    try:
        validate_snapshot(snapshot)
    except ValueError as error:
        assert str(error) == "daily paint piece split does not equal paint_pieces_processed"
    else:
        raise AssertionError("invalid paint piece split was accepted")


def test_live_rollup_fails_closed_on_definition_drift_and_skips_detail_sets(monkeypatch):
    captured = {}

    def fake_execute(query, wanted, credential_name):
        captured.update(query=query, wanted=set(wanted), credential_name=credential_name)
        return []

    monkeypatch.setattr(odbc, "execute_result_sets", fake_execute)
    odbc.execute_operations_rollup(date(2026, 11, 11))

    assert "HASHBYTES('SHA2_256'" in captured["query"]
    assert "7A2992FA73CC9BF282148A2179789E651141057A1225475A5C1360C0C655083E" in captured["query"]
    assert 10 not in captured["wanted"]
    assert 13 not in captured["wanted"]
