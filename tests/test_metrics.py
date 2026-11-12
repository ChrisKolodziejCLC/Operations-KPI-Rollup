import json
from decimal import Decimal
from pathlib import Path

from operations_kpi_rollup.metrics import average_per_data_day, enrich_metric_row, safe_ratio


FIXTURE = Path(__file__).parents[1] / "examples" / "2026-09-16.json"


def load_fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_zero_denominator_is_no_data():
    assert safe_ratio(0, 0) is None
    assert average_per_data_day(100, 0) is None


def test_partial_week_uses_three_production_days():
    snapshot = load_fixture()
    row = next(
        item
        for item in snapshot["periods"]
        if item["period_type"] == "WEEK" and item["period_start"] == "2026-09-13"
    )
    enriched = enrich_metric_row(row)

    assert row["calendar_days"] == 4
    assert row["data_days"] == 3
    assert enriched["parts_loaded_avg"] == Decimal("303")
    assert enriched["paint_pieces_processed_avg"] == Decimal("301")
    assert enriched["eol_inspected_avg"] == Decimal("887") / Decimal("3")
    assert enriched["painted_parts_shipped_avg"] == Decimal("667") / Decimal("3")
    assert enriched["bumpers_shipped_avg"] == Decimal("638") / Decimal("3")


def test_period_yield_is_weighted_from_saved_counts():
    snapshot = load_fixture()
    row = next(
        item
        for item in snapshot["periods"]
        if item["period_type"] == "WEEK" and item["period_start"] == "2026-09-13"
    )
    enriched = enrich_metric_row(row)

    assert enriched["ppy"] == Decimal("795") / Decimal("891")
    assert enriched["paint_fty"] == Decimal("733") / Decimal("818")
    assert enriched["receiving_fty"] == Decimal("686") / Decimal("753")
    assert enriched["final_fty"] == Decimal("1516") / Decimal("1518")


def test_recovered_report_day_composite_is_provisional_legacy_formula():
    snapshot = load_fixture()
    row = next(item for item in snapshot["daily"] if item["date"] == "2026-09-16")
    enriched = enrich_metric_row(row)
    expected = (
        (Decimal("323") / Decimal("330"))
        * (Decimal("280") / Decimal("299"))
        * (Decimal("14") / Decimal("14"))
    )

    assert enriched["paint_plan_composite"] == expected
    assert enriched["paint_plan_composite"].quantize(Decimal("0.001")) == Decimal("0.917")
