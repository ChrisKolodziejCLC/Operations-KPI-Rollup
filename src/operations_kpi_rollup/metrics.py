from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, Iterable, Optional


ZERO = Decimal("0")
ONE = Decimal("1")


def as_decimal(value: Any) -> Decimal:
    if value is None or value == "":
        return ZERO
    return Decimal(str(value))


def safe_ratio(numerator: Any, denominator: Any) -> Optional[Decimal]:
    denominator_value = as_decimal(denominator)
    if denominator_value <= 0:
        return None
    return as_decimal(numerator) / denominator_value


def bounded_yield_ratio(numerator: Any, denominator: Any) -> Optional[Decimal]:
    """Return a yield only when the saved counts form a valid 0..1 ratio."""

    denominator_value = as_decimal(denominator)
    numerator_value = as_decimal(numerator)
    if denominator_value <= 0 or numerator_value < 0 or numerator_value > denominator_value:
        return None
    return numerator_value / denominator_value


def average_per_data_day(total: Any, data_days: Any) -> Optional[Decimal]:
    return safe_ratio(total, data_days)


def clamp(value: Optional[Decimal], minimum: Decimal = ZERO, maximum: Decimal = ONE) -> Optional[Decimal]:
    if value is None:
        return None
    return max(minimum, min(maximum, value))


def paint_plan_composite(row: Dict[str, Any]) -> Optional[Decimal]:
    """Legacy composite, deliberately not called standard OEE.

    schedule attainment × no-repaint quality × active-hour coverage.
    Each component and the final product are bounded to 100%.
    """

    attainment = clamp(safe_ratio(row.get("paint_pieces_processed"), row.get("pieces_scheduled")))
    quality = bounded_yield_ratio(
        as_decimal(row.get("paint_fty_total")) - as_decimal(row.get("paint_fty_repaint_count")),
        row.get("paint_fty_total"),
    )
    active_coverage = clamp(safe_ratio(row.get("paint_hours"), row.get("hours_scheduled")))
    if attainment is None or quality is None or active_coverage is None:
        return None
    return clamp(attainment * quality * active_coverage)


def format_int(value: Any) -> str:
    if value is None:
        return "No Data"
    return f"{int(as_decimal(value)):,}"


def format_decimal(value: Optional[Decimal], places: int = 1) -> str:
    if value is None:
        return "No Data"
    quantum = Decimal("1") if places == 0 else Decimal("1." + ("0" * places))
    rounded = value.quantize(quantum, rounding=ROUND_HALF_UP)
    return f"{rounded:,.{places}f}"


def format_percent(value: Optional[Decimal], places: int = 1) -> str:
    if value is None:
        return "No Data"
    return f"{format_decimal(value * Decimal('100'), places)}%"


def enrich_metric_row(row: Dict[str, Any]) -> Dict[str, Any]:
    enriched = dict(row)
    data_days = row.get("data_days", 1 if row.get("production_day") else 0)

    for field in (
        "parts_loaded",
        "paint_pieces_processed",
        "eol_inspected",
        "painted_parts_shipped",
        "bumpers_shipped",
        "parts_shipped",
    ):
        enriched[field + "_avg"] = average_per_data_day(row.get(field, 0), data_days)

    enriched["repaint_ppy"] = bounded_yield_ratio(
        row.get("ppy_approved"), row.get("paint_decision_pieces")
    )
    enriched["repaint_fty"] = bounded_yield_ratio(
        row.get("paint_fty_approved"), row.get("paint_fty_total")
    )
    enriched["reject_ppy"] = bounded_yield_ratio(
        row.get("reject_ppy_approved"), row.get("reject_ppy_total")
    )
    enriched["reject_fty"] = bounded_yield_ratio(
        row.get("reject_fty_approved"), row.get("reject_fty_total")
    )
    # Compatibility aliases retained for older report templates and saved snapshots.
    enriched["ppy"] = enriched["repaint_ppy"]
    enriched["paint_fty"] = enriched["repaint_fty"]
    enriched["receiving_fty"] = safe_ratio(row.get("receiving_approved"), row.get("receiving_total"))
    enriched["final_fty"] = safe_ratio(row.get("final_approved"), row.get("final_total"))
    enriched["repaint_percentage"] = safe_ratio(
        row.get("paint_fty_repaint_count"), row.get("paint_fty_total")
    )
    enriched["finesse_percentage"] = (
        safe_ratio(row.get("paint_fty_repair_count"), row.get("reject_fty_rejected_count"))
        if "paint_fty_repair_count" in row
        else None
    )
    enriched["schedule_attainment"] = safe_ratio(
        row.get("paint_pieces_processed"), row.get("pieces_scheduled")
    )
    enriched["paint_plan_composite"] = paint_plan_composite(row)
    return enriched


def sum_fields(rows: Iterable[Dict[str, Any]], fields: Iterable[str]) -> Dict[str, int]:
    totals = {field: 0 for field in fields}
    for row in rows:
        for field in fields:
            totals[field] += int(row.get(field, 0) or 0)
    return totals
