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
        "production_parts_loaded": "70",
        "bv_parts_loaded": "5",
        "service_parts_loaded": "25",
        "unique_pieces_loaded": "91",
        "carts_loaded": "40",
        "production_carts_loaded": "25",
        "bv_carts_loaded": "5",
        "service_carts_loaded": "10",
        "paint_processed": "35",
        "production_paint_carts": "20",
        "bv_paint_carts": "5",
        "service_paint_carts": "10",
        "paint_pieces_processed": "96",
        "production_paint_pieces_processed": "65",
        "bv_paint_pieces_processed": "5",
        "service_paint_pieces_processed": "26",
        "unique_pieces_processed": "84",
        "paint_decision_pieces": "95",
        "production_paint_decision_pieces": "80",
        "bv_paint_decision_pieces": "5",
        "service_paint_decision_pieces": "10",
        "ppy_approved": "90",
        "production_ppy_approved": "75",
        "bv_ppy_approved": "5",
        "service_ppy_approved": "10",
        "ppy_repaint_count": "4",
        "paint_fty_total": "90",
        "production_paint_fty_total": "75",
        "bv_paint_fty_total": "5",
        "service_paint_fty_total": "10",
        "paint_fty_approved": "86",
        "production_paint_fty_approved": "71",
        "bv_paint_fty_approved": "5",
        "service_paint_fty_approved": "10",
        "paint_fty_repaint_count": "3",
        "reject_ppy_total": "95",
        "reject_ppy_approved": "89",
        "reject_ppy_rejected_count": "5",
        "reject_ppy_pending_count": "1",
        "reject_fty_total": "90",
        "reject_fty_approved": "84",
        "reject_fty_rejected_count": "5",
        "reject_fty_pending_count": "1",
        "receiving_total": "99",
        "receiving_approved": "97",
        "receiving_quantity": "98",
        "final_total": "101",
        "final_approved": "100",
        "final_quantity": "100",
        "eol_inspected": "98",
        "painted_parts_shipped": "85",
        "bumpers_shipped": "55",
        "parts_shipped": "90",
        "complete_assy_sets": "12",
        "assembled_bumper_count": "25",
        "trailers_prepared": "4",
        "fuka_trailers_prepared": "2",
        "bumper_trailers_prepared": "1",
        "fairing_trailers_prepared": "1",
        "other_trailers_prepared": "0",
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
        {"index": 12, "rows": [
            {"report_date": "2026-11-11", "line_set": "Bumpers", "pieces_shipped": "55"},
            {"report_date": "2026-11-11", "line_set": "Fenders", "pieces_shipped": "20"},
            {"report_date": "2026-11-11", "line_set": "Chassis Fairings", "pieces_shipped": "15"},
        ]},
    ]


def test_connection_string_parser_handles_braces_and_quoted_values():
    parsed = parse_connection_string("Server={brak};Database='Production Tracking (Version 1.0.0)SQL';UID=user;PWD={p;ass}}word};")
    assert parsed["server"] == "brak"
    assert parsed["database"] == "Production Tracking (Version 1.0.0)SQL"
    assert parsed["pwd"] == "p;ass}word"


def test_rollup_result_sets_become_valid_immutable_snapshot(monkeypatch):
    monkeypatch.setenv("KPI_SQL_PROCEDURE_HASH", "87b95e7af33fcae6f9fd3c9bc0d5f76d3e270acdb1115a4e5e7c1f407a9d3422")
    generated = datetime(2026, 11, 12, 12, 30, tzinfo=ZoneInfo("America/Indiana/Indianapolis"))
    snapshot = snapshot_from_rollup(date(2026, 11, 11), result_sets(), generated_at=generated)

    assert snapshot["report_date"] == "2026-11-11"
    assert snapshot["generated_at"] == "2026-11-12T12:30:00-05:00"
    assert snapshot["daily"][-1]["paint_carts"] == 35
    assert snapshot["daily"][-1]["production_paint_carts"] == 20
    assert snapshot["daily"][-1]["bv_paint_carts"] == 5
    assert snapshot["daily"][-1]["service_paint_carts"] == 10
    assert snapshot["daily"][-1]["paint_pieces_processed"] == 96
    assert snapshot["daily"][-1]["production_paint_pieces_processed"] == 65
    assert snapshot["daily"][-1]["bv_paint_pieces_processed"] == 5
    assert snapshot["daily"][-1]["service_paint_pieces_processed"] == 26
    assert snapshot["daily"][-1]["production_parts_loaded"] == 70
    assert snapshot["daily"][-1]["bv_parts_loaded"] == 5
    assert snapshot["daily"][-1]["service_parts_loaded"] == 25
    assert snapshot["daily"][-1]["unique_pieces_loaded"] == 91
    assert snapshot["daily"][-1]["unique_pieces_processed"] == 84
    assert snapshot["daily"][-1]["production_carts_loaded"] == 25
    assert snapshot["daily"][-1]["bv_carts_loaded"] == 5
    assert snapshot["daily"][-1]["service_carts_loaded"] == 10
    cards = prepare_context(snapshot)["cards"]
    assert cards[0]["label"] == "Pieces loaded"
    assert cards[0]["value"] == "100 Total / 91 Unique"
    assert cards[0]["detail"] == "Carts 25 Prd / 5 BV / 10 Svc · Pieces 70 Prd / 5 BV / 25 Svc"
    assert cards[1]["label"] == "Pieces painted"
    assert cards[1]["value"] == "96 Total / 84 Unique"
    assert cards[1]["detail"] == "Carts 20 Prd / 5 BV / 10 Svc · Pieces 65 Prd / 5 BV / 26 Svc"
    assert cards[2]["label"] == "Repaint PPY"
    assert cards[2]["value"] == "94.7%"
    assert cards[2]["detail"] == "90 / 95 exits"
    assert cards[3]["label"] == "Reject PPY"
    assert cards[3]["value"] == "93.7%"
    assert cards[3]["detail"] == "89 / 95 exits · 1 pending"
    assert cards[4]["label"] == "Repaint FTY"
    assert cards[4]["value"] == "95.6%"
    assert cards[5]["label"] == "Reject FTY"
    assert cards[5]["value"] == "93.3%"
    assert cards[6]["label"] == "Repaint %"
    assert cards[6]["value"] == "3.3%"
    assert cards[7]["detail"] == "97 / 99 first decisions · Qty 98 by receive stamp"
    assert cards[8]["detail"] == "100 / 101 first decisions · Qty 100 by final stamp"
    assert cards[-2]["label"] == "Pieces shipped"
    assert cards[-2]["value"] == "90"
    assert cards[-2]["detail"] == "55 Bumpers / 20 Fenders / 15 Fairings"
    assert cards[-1]["detail"] == "2 FUKA / 1 Bumpers / 1 Fairings"
    assert [row["period_type"] for row in snapshot["periods"]] == ["WEEK", "MONTH", "QUARTER"]
    assert snapshot["top_defects"] == [{"step": "End of Line", "description": "Dirt", "count": 7}]
    assert [row["pieces"] for row in snapshot["shipping"]] == [55, 20, 15]
    assert snapshot["painters"] == []
    assert snapshot["source_evidence"]["detail_result_sets_requested"] is False
    assert snapshot["source_evidence"]["procedure_definition_sha256"] == "87B95E7AF33FCAE6F9FD3C9BC0D5F76D3E270ACDB1115A4E5E7C1F407A9D3422"
    assert snapshot["scope"]["method_version"] == "operations-kpi-live-v10-master-repaintcount-yields"


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


def test_daily_unique_piece_counts_must_be_present_and_not_exceed_event_totals():
    generated = datetime(2026, 11, 12, 12, 30, tzinfo=ZoneInfo("America/Indiana/Indianapolis"))
    snapshot = snapshot_from_rollup(date(2026, 11, 11), result_sets(), generated_at=generated)
    snapshot["daily"][-1]["unique_pieces_processed"] = 97
    try:
        validate_snapshot(snapshot)
    except ValueError as error:
        assert str(error) == "daily painted unique-piece count is outside its total"
    else:
        raise AssertionError("invalid daily unique-piece count was accepted")


def test_quality_and_trailer_splits_must_equal_totals():
    generated = datetime(2026, 11, 12, 12, 30, tzinfo=ZoneInfo("America/Indiana/Indianapolis"))
    snapshot = snapshot_from_rollup(date(2026, 11, 11), result_sets(), generated_at=generated)
    snapshot["daily"][-1]["bv_ppy_approved"] = 4
    try:
        validate_snapshot(snapshot)
    except ValueError as error:
        assert str(error) == "daily PPY numerator split does not equal ppy_approved"
    else:
        raise AssertionError("invalid PPY split was accepted")

    snapshot = snapshot_from_rollup(date(2026, 11, 11), result_sets(), generated_at=generated)
    snapshot["daily"][-1]["fairing_trailers_prepared"] = 0
    try:
        validate_snapshot(snapshot)
    except ValueError as error:
        assert str(error) == "daily trailer type split does not equal trailers_prepared"
    else:
        raise AssertionError("invalid trailer split was accepted")


def test_v4_saved_snapshot_can_load_before_first_v5_refresh():
    generated = datetime(2026, 11, 12, 12, 30, tzinfo=ZoneInfo("America/Indiana/Indianapolis"))
    snapshot = snapshot_from_rollup(date(2026, 11, 11), result_sets(), generated_at=generated)
    snapshot["scope"]["method_version"] = "operations-kpi-live-v4-paint-service-split"
    for collection in ("daily", "periods"):
        for row in snapshot[collection]:
            for production_field, bv_field in (
                ("production_parts_loaded", "bv_parts_loaded"),
                ("production_carts_loaded", "bv_carts_loaded"),
                ("production_paint_carts", "bv_paint_carts"),
                ("production_paint_pieces_processed", "bv_paint_pieces_processed"),
            ):
                row[production_field] += row[bv_field]
            for field in tuple(row):
                if field.startswith("bv_"):
                    row.pop(field)
            for field in (
                "production_paint_decision_pieces", "service_paint_decision_pieces",
                "production_ppy_approved", "service_ppy_approved",
                "production_paint_fty_total", "service_paint_fty_total",
                "production_paint_fty_approved", "service_paint_fty_approved",
                "fuka_trailers_prepared", "bumper_trailers_prepared",
                "fairing_trailers_prepared", "other_trailers_prepared",
            ):
                row.pop(field, None)
    validate_snapshot(snapshot)


def test_v6_saved_snapshot_can_load_before_first_v7_refresh():
    generated = datetime(2026, 11, 12, 12, 30, tzinfo=ZoneInfo("America/Indiana/Indianapolis"))
    snapshot = snapshot_from_rollup(date(2026, 11, 11), result_sets(), generated_at=generated)
    snapshot["scope"]["method_version"] = "operations-kpi-live-v6-original-paint-repaint-cohort"
    for collection in ("daily", "periods"):
        for row in snapshot[collection]:
            row.pop("unique_pieces_loaded")
            row.pop("unique_pieces_processed")
    validate_snapshot(snapshot)
    cards = prepare_context(snapshot)["cards"]
    assert cards[0]["value"] == "100 Total / — Unique"
    assert cards[1]["value"] == "96 Total / — Unique"


def test_v7_saved_snapshot_can_load_before_first_v8_refresh():
    generated = datetime(2026, 11, 12, 12, 30, tzinfo=ZoneInfo("America/Indiana/Indianapolis"))
    snapshot = snapshot_from_rollup(date(2026, 11, 11), result_sets(), generated_at=generated)
    snapshot["scope"]["method_version"] = "operations-kpi-live-v7-daily-unique-pieces"
    for collection in ("daily", "periods"):
        for row in snapshot[collection]:
            row.pop("receiving_quantity")
            row.pop("final_quantity")
    validate_snapshot(snapshot)


def test_v8_saved_snapshot_can_load_before_first_v9_refresh():
    generated = datetime(2026, 11, 12, 12, 30, tzinfo=ZoneInfo("America/Indiana/Indianapolis"))
    snapshot = snapshot_from_rollup(date(2026, 11, 11), result_sets(), generated_at=generated)
    snapshot["scope"]["method_version"] = "operations-kpi-live-v8-physical-pass-metrics"
    for collection in ("daily", "periods"):
        for row in snapshot[collection]:
            for field in tuple(row):
                if field.startswith("reject_ppy_") or field.startswith("reject_fty_"):
                    row.pop(field)
    validate_snapshot(snapshot)


def test_v9_saved_snapshot_can_load_before_first_v10_refresh():
    generated = datetime(2026, 11, 12, 12, 30, tzinfo=ZoneInfo("America/Indiana/Indianapolis"))
    snapshot = snapshot_from_rollup(date(2026, 11, 11), result_sets(), generated_at=generated)
    snapshot["scope"]["method_version"] = "operations-kpi-live-v9-repaint-reject-yields"
    for collection in ("daily", "periods"):
        for row in snapshot[collection]:
            row["reject_ppy_approved"] += row["reject_ppy_pending_count"]
            row["reject_fty_approved"] += row["reject_fty_pending_count"]
            row["paint_fty_approved"] = row["paint_fty_total"] - row["paint_fty_repaint_count"]
            row["production_paint_fty_approved"] = row["production_paint_fty_total"] - row["paint_fty_repaint_count"]
            row["bv_paint_fty_approved"] = row["bv_paint_fty_total"]
            row["service_paint_fty_approved"] = row["service_paint_fty_total"]
    validate_snapshot(snapshot)


def test_v10_snapshot_requires_complete_reject_yield_counts():
    generated = datetime(2026, 11, 12, 12, 30, tzinfo=ZoneInfo("America/Indiana/Indianapolis"))
    snapshot = snapshot_from_rollup(date(2026, 11, 11), result_sets(), generated_at=generated)
    snapshot["daily"][-1].pop("reject_ppy_pending_count")
    try:
        validate_snapshot(snapshot)
    except ValueError as error:
        assert str(error) == "daily reject yield fields are missing: reject_ppy_pending_count"
    else:
        raise AssertionError("missing v10 reject yield count was accepted")


def test_v8_snapshot_requires_stamp_quantities():
    generated = datetime(2026, 11, 12, 12, 30, tzinfo=ZoneInfo("America/Indiana/Indianapolis"))
    snapshot = snapshot_from_rollup(date(2026, 11, 11), result_sets(), generated_at=generated)
    snapshot["daily"][-1].pop("receiving_quantity")
    try:
        validate_snapshot(snapshot)
    except ValueError as error:
        assert str(error) == "daily receiving_quantity is missing"
    else:
        raise AssertionError("missing v8 receiving quantity was accepted")


def test_v5_snapshot_requires_bv_fields():
    generated = datetime(2026, 11, 12, 12, 30, tzinfo=ZoneInfo("America/Indiana/Indianapolis"))
    snapshot = snapshot_from_rollup(date(2026, 11, 11), result_sets(), generated_at=generated)
    snapshot["daily"][-1].pop("bv_parts_loaded")
    try:
        validate_snapshot(snapshot)
    except ValueError as error:
        assert str(error) == "daily load split is incomplete"
    else:
        raise AssertionError("incomplete v5 split was accepted")


def test_live_rollup_fails_closed_on_definition_drift_and_skips_detail_sets(monkeypatch):
    captured = {}

    def fake_execute(query, wanted, credential_name):
        captured.update(query=query, wanted=set(wanted), credential_name=credential_name)
        return []

    monkeypatch.setattr(odbc, "execute_result_sets", fake_execute)
    odbc.execute_operations_rollup(date(2026, 11, 11))

    assert "HASHBYTES('SHA2_256'" in captured["query"]
    assert "87B95E7AF33FCAE6F9FD3C9BC0D5F76D3E270ACDB1115A4E5E7C1F407A9D3422" in captured["query"]
    assert 10 not in captured["wanted"]
    assert 13 not in captured["wanted"]
