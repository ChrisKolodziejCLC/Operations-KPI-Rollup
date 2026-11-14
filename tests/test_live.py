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
        "n71_6164_parts_loaded": "10",
        "unique_pieces_loaded": "91",
        "carts_loaded": "40",
        "production_carts_loaded": "25",
        "bv_carts_loaded": "5",
        "service_carts_loaded": "10",
        "n71_6164_carts_loaded": "2",
        "staged_carts": "11",
        "production_staged_carts": "11",
        "bv_staged_carts": "0",
        "service_staged_carts": "0",
        "staged_pieces": "40",
        "production_staged_pieces": "40",
        "bv_staged_pieces": "0",
        "service_staged_pieces": "0",
        "paint_processed": "35",
        "production_paint_carts": "20",
        "bv_paint_carts": "5",
        "service_paint_carts": "10",
        "n71_6164_paint_carts": "2",
        "paint_pieces_processed": "96",
        "production_paint_pieces_processed": "65",
        "bv_paint_pieces_processed": "5",
        "service_paint_pieces_processed": "26",
        "n71_6164_paint_pieces_processed": "5",
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
        "fuka_paint_fty_repaint_count": "1",
        "bumper_paint_fty_repaint_count": "1",
        "fairing_paint_fty_repaint_count": "1",
        "paint_fty_repair_count": "2",
        "fuka_paint_fty_repair_count": "1",
        "fairing_paint_fty_repair_count": "1",
        "bumper_paint_fty_repair_count": "0",
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
        "receiving_bumper_total": "90",
        "receiving_bumper_approved": "88",
        "receiving_fairing_total": "9",
        "receiving_fairing_approved": "9",
        "finesse_rejected_count": "2",
        "finesse_repair_count": "1",
        "finesse_repaint_count": "1",
        "finesse_pending_count": "0",
        "bumper_finesse_repair_count": "1",
        "fairing_finesse_repair_count": "0",
        "other_finesse_repair_count": "0",
        "receiving_quantity": "98",
        "final_total": "101",
        "final_approved": "100",
        "final_fuka_total": "50",
        "final_fuka_approved": "50",
        "final_bumper_total": "40",
        "final_bumper_approved": "39",
        "final_fairing_total": "11",
        "final_fairing_approved": "11",
        "final_quantity": "100",
        "eol_inspected": "98",
        "painted_parts_shipped": "85",
        "bumpers_shipped": "55",
        "parts_shipped": "90",
        "complete_assy_sets": "12",
        "mic_complete_assy_sets": "4",
        "painted_complete_assy_sets": "8",
        "assembled_bumper_count": "25",
        "mic_assembled_bumper_count": "7",
        "painted_assembled_bumper_count": "18",
        "trailers_prepared": "4",
        "trailers_shipped": "3",
        "fuka_trailers_prepared": "2",
        "bumper_trailers_prepared": "1",
        "fairing_trailers_prepared": "1",
        "other_trailers_prepared": "0",
        "racks_shipped": "17",
        "fuka_racks_shipped": "5",
        "bumper_racks_shipped": "10",
        "n71_6164_racks_shipped": "1",
        "fairing_racks_shipped": "1",
        "other_racks_shipped": "0",
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
            {"report_date": "2026-11-11", "line_set": "FUKA", "pieces_shipped": "20"},
            {"report_date": "2026-11-11", "line_set": "N71-6164", "pieces_shipped": "5"},
            {"report_date": "2026-11-11", "line_set": "Fairings", "pieces_shipped": "10"},
        ]},
    ]


def test_connection_string_parser_handles_braces_and_quoted_values():
    parsed = parse_connection_string("Server={brak};Database='Production Tracking (Version 1.0.0)SQL';UID=user;PWD={p;ass}}word};")
    assert parsed["server"] == "brak"
    assert parsed["database"] == "Production Tracking (Version 1.0.0)SQL"
    assert parsed["pwd"] == "p;ass}word"


def test_rollup_result_sets_become_valid_immutable_snapshot(monkeypatch):
    monkeypatch.setenv("KPI_SQL_PROCEDURE_HASH", "ac7dfdadc5c86c638385cd59265da5e78a35c6a6a50f7cd869a014f7f02639be")
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
    assert [card["label"] for card in cards[:5]] == [
        "Pieces loaded", "Pieces staged", "Pieces painted", "Repaint %", "Finesse %"
    ]
    cards_by_label = {card["label"]: card for card in cards}
    assert cards_by_label["Pieces loaded"]["value"] == "100 Total / 91 Unique"
    assert cards_by_label["Pieces loaded"]["detail"] == "Carts 25 Prd / 5 BV / 10 Svc · Pieces 70 Prd / 5 BV / 25 Svc"
    assert cards_by_label["Pieces staged"]["value"] == "11 Carts / 40 Pieces"
    assert cards_by_label["Pieces staged"]["detail"] == "Carts 11 Prd / 0 BV / 0 Svc · Pieces 40 Prd / 0 BV / 0 Svc"
    assert cards_by_label["Pieces painted"]["value"] == "96 Total / 84 Unique"
    assert cards_by_label["Pieces painted"]["detail"] == "Carts 20 Prd / 5 BV / 10 Svc · Pieces 65 Prd / 5 BV / 26 Svc"
    assert cards_by_label["Repaint %"]["value"] == "3.3%"
    assert cards_by_label["Repaint %"]["detail"] == "3 / 90 initial passes"
    assert cards_by_label["Repaint %"]["secondary_detail"] == "1 FUKA / 1 Bumpers / 1 Fairings"
    assert cards_by_label["Finesse %"]["value"] == "42.9%"
    assert cards_by_label["Finesse %"]["detail"] == "3 Repaired / 7 Rejected\n1 FUKA Repaired\n1 Bumpers Repaired\n1 Fairings Repaired"
    assert cards_by_label["Repaint PPY"]["value"] == "94.7%"
    assert cards_by_label["Reject PPY"]["value"] == "93.7%"
    assert cards_by_label["Repaint FTY"]["value"] == "95.6%"
    assert cards_by_label["Reject FTY"]["value"] == "93.3%"
    assert cards_by_label["Receiving FTY"]["detail"] == "Bumpers 97.8% · 88 / 90\nFairings 100.0% · 9 / 9"
    assert cards_by_label["Final FTY"]["detail"] == "FUKA 100.0% · 50 / 50\nBumpers 97.5% · 39 / 40\nFairings 100.0% · 11 / 11"
    assert cards[-2]["label"] == "Pieces shipped"
    assert cards[-2]["value"] == "90"
    assert cards[-2]["detail"] == "20 FUKA / 55 Bumpers / 5 N71-6164 / 10 Fairings"
    assert cards[-1]["label"] == "Trailers"
    assert cards[-1]["value"] == "4 Prepped / 3 Shipped"
    assert cards[-1]["detail"] == "10 Bumper Racks\n5 FUKA Racks\n1 Fairing Racks"
    assert [row["period_type"] for row in snapshot["periods"]] == ["WEEK", "MONTH", "QUARTER"]
    assert snapshot["top_defects"] == [{"step": "End of Line", "description": "Dirt", "count": 7}]
    assert [row["pieces"] for row in snapshot["shipping"]] == [55, 20, 5, 10]
    assert snapshot["painters"] == []
    assert snapshot["source_evidence"]["detail_result_sets_requested"] is False
    assert snapshot["source_evidence"]["procedure_definition_sha256"] == "AC7DFDADC5C86C638385CD59265DA5E78A35C6A6A50F7CD869A014F7F02639BE"
    assert snapshot["scope"]["method_version"] == "operations-kpi-live-v17-combined-finesse-two-row"


def test_repaint_line_set_split_must_equal_total():
    generated = datetime(2026, 11, 12, 12, 30, tzinfo=ZoneInfo("America/Indiana/Indianapolis"))
    snapshot = snapshot_from_rollup(date(2026, 11, 11), result_sets(), generated_at=generated)
    snapshot["daily"][-1]["fuka_paint_fty_repaint_count"] = 2

    try:
        validate_snapshot(snapshot)
    except ValueError as error:
        assert str(error) == "daily repaint line-set split does not equal paint_fty_repaint_count"
    else:
        raise AssertionError("invalid repaint line-set split was accepted")


def test_shipped_rack_split_must_equal_total():
    generated = datetime(2026, 11, 12, 12, 30, tzinfo=ZoneInfo("America/Indiana/Indianapolis"))
    snapshot = snapshot_from_rollup(date(2026, 11, 11), result_sets(), generated_at=generated)
    snapshot["daily"][-1]["fairing_racks_shipped"] = 0

    try:
        validate_snapshot(snapshot)
    except ValueError as error:
        assert str(error) == "daily rack type split does not equal racks_shipped"
    else:
        raise AssertionError("invalid shipped rack split was accepted")


def test_v14_inspection_and_finesse_splits_are_guarded():
    generated = datetime(2026, 11, 12, 12, 30, tzinfo=ZoneInfo("America/Indiana/Indianapolis"))
    snapshot = snapshot_from_rollup(date(2026, 11, 11), result_sets(), generated_at=generated)
    snapshot["daily"][-1]["receiving_fairing_total"] = 10
    try:
        validate_snapshot(snapshot)
    except ValueError as error:
        assert str(error) == "daily receiving family totals do not equal receiving_total"
    else:
        raise AssertionError("invalid receiving family split was accepted")

    snapshot = snapshot_from_rollup(date(2026, 11, 11), result_sets(), generated_at=generated)
    snapshot["daily"][-1]["final_fairing_approved"] = 10
    try:
        validate_snapshot(snapshot)
    except ValueError as error:
        assert str(error) == "daily final family approvals do not equal final_approved"
    else:
        raise AssertionError("invalid final family split was accepted")

    snapshot = snapshot_from_rollup(date(2026, 11, 11), result_sets(), generated_at=generated)
    snapshot["daily"][-1]["fuka_paint_fty_repair_count"] = 2
    try:
        validate_snapshot(snapshot)
    except ValueError as error:
        assert str(error) == "daily finesse family repair counts do not equal paint_fty_repair_count"
    else:
        raise AssertionError("invalid finesse family split was accepted")

    snapshot = snapshot_from_rollup(date(2026, 11, 11), result_sets(), generated_at=generated)
    snapshot["daily"][-1]["production_staged_carts"] = 10
    try:
        validate_snapshot(snapshot)
    except ValueError as error:
        assert str(error) == "daily staged cart split does not equal staged_carts"
    else:
        raise AssertionError("invalid staged cart split was accepted")


def test_v16_receiving_finesse_cohort_is_balanced():
    generated = datetime(2026, 11, 12, 12, 30, tzinfo=ZoneInfo("America/Indiana/Indianapolis"))
    snapshot = snapshot_from_rollup(date(2026, 11, 11), result_sets(), generated_at=generated)
    snapshot["daily"][-1]["finesse_rejected_count"] = 3
    try:
        validate_snapshot(snapshot)
    except ValueError as error:
        assert str(error) == "daily Finesse rejected count does not equal first Receiving rejects"
    else:
        raise AssertionError("an invalid Receiving reject cohort was accepted")

    snapshot = snapshot_from_rollup(date(2026, 11, 11), result_sets(), generated_at=generated)
    snapshot["daily"][-1]["finesse_pending_count"] = 1
    try:
        validate_snapshot(snapshot)
    except ValueError as error:
        assert str(error) == "daily Finesse outcomes do not equal first Receiving rejects"
    else:
        raise AssertionError("unbalanced Finesse outcomes were accepted")

    snapshot = snapshot_from_rollup(date(2026, 11, 11), result_sets(), generated_at=generated)
    snapshot["daily"][-1]["other_finesse_repair_count"] = 1
    try:
        validate_snapshot(snapshot)
    except ValueError as error:
        assert str(error) == "daily Finesse repair family split does not equal finesse_repair_count"
    else:
        raise AssertionError("an invalid Finesse family split was accepted")


def test_v13_mic_and_n71_breakdowns_are_guarded():
    generated = datetime(2026, 11, 12, 12, 30, tzinfo=ZoneInfo("America/Indiana/Indianapolis"))
    snapshot = snapshot_from_rollup(date(2026, 11, 11), result_sets(), generated_at=generated)
    snapshot["daily"][-1]["painted_complete_assy_sets"] = 7

    try:
        validate_snapshot(snapshot)
    except ValueError as error:
        assert str(error) == "daily complete assembly MIC/Painted split does not equal complete_assy_sets"
    else:
        raise AssertionError("invalid complete assembly split was accepted")

    snapshot = snapshot_from_rollup(date(2026, 11, 11), result_sets(), generated_at=generated)
    snapshot["daily"][-1]["n71_6164_paint_pieces_processed"] = 66
    try:
        validate_snapshot(snapshot)
    except ValueError as error:
        assert str(error) == "daily painted N71-6164 count exceeds its production bucket"
    else:
        raise AssertionError("invalid N71-6164 paint count was accepted")


def test_v11_saved_snapshot_can_load_before_first_v12_refresh():
    generated = datetime(2026, 11, 12, 12, 30, tzinfo=ZoneInfo("America/Indiana/Indianapolis"))
    snapshot = snapshot_from_rollup(date(2026, 11, 11), result_sets(), generated_at=generated)
    snapshot["scope"]["method_version"] = "operations-kpi-live-v11-repaint-line-set-counts"
    rack_fields = (
        "racks_shipped", "fuka_racks_shipped", "bumper_racks_shipped",
        "n71_6164_racks_shipped", "fairing_racks_shipped", "other_racks_shipped",
    )
    for collection in ("daily", "periods"):
        for row in snapshot[collection]:
            for field in rack_fields:
                row.pop(field)
    validate_snapshot(snapshot)
    assert prepare_context(snapshot)["cards"][-1]["label"] == "Trailers"


def test_v12_saved_snapshot_can_load_before_first_v13_refresh():
    generated = datetime(2026, 11, 12, 12, 30, tzinfo=ZoneInfo("America/Indiana/Indianapolis"))
    snapshot = snapshot_from_rollup(date(2026, 11, 11), result_sets(), generated_at=generated)
    snapshot["scope"]["method_version"] = "operations-kpi-live-v12-shipped-rack-counts"
    new_fields = (
        "n71_6164_parts_loaded", "n71_6164_carts_loaded", "n71_6164_paint_carts",
        "n71_6164_paint_pieces_processed", "mic_complete_assy_sets",
        "painted_complete_assy_sets", "mic_assembled_bumper_count",
        "painted_assembled_bumper_count", "n71_6164_racks_shipped",
    )
    for collection in ("daily", "periods"):
        for row in snapshot[collection]:
            row["fairing_racks_shipped"] += row["n71_6164_racks_shipped"]
            for field in new_fields:
                row.pop(field)
    validate_snapshot(snapshot)
    cards = prepare_context(snapshot)["cards"]
    cards_by_label = {card["label"]: card for card in cards}
    assert cards_by_label["Complete assy sets"]["detail"] == "N33 / Chassis Fairing · dated by last assembled piece"
    assert cards_by_label["Assembled bumpers"]["detail"] == "N71-6171 · AssembledDate"


def test_v13_saved_snapshot_can_load_before_first_v14_refresh():
    generated = datetime(2026, 11, 12, 12, 30, tzinfo=ZoneInfo("America/Indiana/Indianapolis"))
    snapshot = snapshot_from_rollup(date(2026, 11, 11), result_sets(), generated_at=generated)
    snapshot["scope"]["method_version"] = "operations-kpi-live-v13-mic-n71-breakdowns"
    v14_fields = (
        "trailers_shipped",
        "receiving_bumper_total", "receiving_bumper_approved",
        "receiving_fairing_total", "receiving_fairing_approved",
        "final_fuka_total", "final_fuka_approved",
        "final_bumper_total", "final_bumper_approved",
        "final_fairing_total", "final_fairing_approved",
        "paint_fty_repair_count", "fuka_paint_fty_repair_count",
        "fairing_paint_fty_repair_count", "bumper_paint_fty_repair_count",
        "finesse_rejected_count", "finesse_repair_count", "finesse_repaint_count",
        "finesse_pending_count", "bumper_finesse_repair_count",
        "fairing_finesse_repair_count", "other_finesse_repair_count",
        "staged_carts", "production_staged_carts", "bv_staged_carts", "service_staged_carts",
        "staged_pieces", "production_staged_pieces", "bv_staged_pieces", "service_staged_pieces",
    )
    for collection in ("daily", "periods"):
        for row in snapshot[collection]:
            for field in v14_fields:
                row.pop(field)
    validate_snapshot(snapshot)
    cards_by_label = {card["label"]: card for card in prepare_context(snapshot)["cards"]}
    assert cards_by_label["Trailers"]["value"] == "4 Prepped / No Data Shipped"
    assert cards_by_label["Finesse %"]["value"] == "No Data"


def test_v15_saved_snapshot_can_load_before_first_v16_refresh():
    generated = datetime(2026, 11, 12, 12, 30, tzinfo=ZoneInfo("America/Indiana/Indianapolis"))
    snapshot = snapshot_from_rollup(date(2026, 11, 11), result_sets(), generated_at=generated)
    snapshot["scope"]["method_version"] = "operations-kpi-live-v15-description-family-mapping"
    v16_fields = (
        "finesse_rejected_count", "finesse_repair_count", "finesse_repaint_count",
        "finesse_pending_count", "bumper_finesse_repair_count",
        "fairing_finesse_repair_count", "other_finesse_repair_count",
    )
    for collection in ("daily", "periods"):
        for row in snapshot[collection]:
            for field in v16_fields:
                row.pop(field)
    validate_snapshot(snapshot)
    finesse = {card["label"]: card for card in prepare_context(snapshot)["cards"]}["Finesse %"]
    assert finesse["value"] == "40.0%"
    assert finesse["detail"] == "2 Repaired / 5 Rejected\n1 FUKA Repaired\n0 Bumpers Repaired\n1 Fairings Repaired"


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
    cards_by_label = {card["label"]: card for card in cards}
    assert cards_by_label["Pieces painted"]["value"] == "96 Total / — Unique"


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
    assert "AC7DFDADC5C86C638385CD59265DA5E78A35C6A6A50F7CD869A014F7F02639BE" in captured["query"]
    assert 10 not in captured["wanted"]
    assert 13 not in captured["wanted"]
