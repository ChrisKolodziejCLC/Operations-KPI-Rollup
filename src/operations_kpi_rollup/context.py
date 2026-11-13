from datetime import date
from typing import Any, Dict, Iterable, List

from .metrics import enrich_metric_row, format_decimal, format_int, format_percent


REQUIRED_TOP_LEVEL = {
    "schema_version",
    "report_date",
    "generated_at",
    "scope",
    "daily",
    "periods",
    "painters",
    "shipping",
    "top_defects",
}


def validate_snapshot(snapshot: Dict[str, Any]) -> None:
    missing = sorted(REQUIRED_TOP_LEVEL - set(snapshot))
    if missing:
        raise ValueError("snapshot is missing required fields: " + ", ".join(missing))
    if snapshot["schema_version"] != "operations-kpi-snapshot/v1":
        raise ValueError("unsupported snapshot schema_version")
    date.fromisoformat(snapshot["report_date"])
    if not any(row.get("date") == snapshot["report_date"] for row in snapshot["daily"]):
        raise ValueError("snapshot daily rows do not include report_date")
    for collection in ("daily", "periods"):
        for row in snapshot[collection]:
            has_production = "production_parts_loaded" in row
            has_service = "service_parts_loaded" in row
            if has_production != has_service:
                raise ValueError(f"{collection} load split is incomplete")
            if has_production and (
                int(row["production_parts_loaded"]) + int(row["service_parts_loaded"])
                != int(row.get("parts_loaded", 0))
            ):
                raise ValueError(f"{collection} load split does not equal parts_loaded")


def _sort_by(rows: Iterable[Dict[str, Any]], key: str) -> List[Dict[str, Any]]:
    return sorted(rows, key=lambda row: row.get(key, ""))


def _card(label: str, value: str, detail: str, color: str, status: str = "") -> Dict[str, str]:
    return {"label": label, "value": value, "detail": detail, "color": color, "status": status}


def _load_split(row: Dict[str, Any]) -> tuple[Any, Any]:
    if "production_parts_loaded" not in row and "service_parts_loaded" not in row:
        return row.get("parts_loaded", 0), 0
    return row.get("production_parts_loaded", 0), row.get("service_parts_loaded", 0)


def prepare_context(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    validate_snapshot(snapshot)
    report_date = snapshot["report_date"]
    daily = [enrich_metric_row(row) for row in _sort_by(snapshot["daily"], "date")]
    periods = [enrich_metric_row(row) for row in snapshot["periods"]]
    current = next(row for row in daily if row["date"] == report_date)

    weeks = [row for row in periods if row.get("period_type") == "WEEK"]
    months = [row for row in periods if row.get("period_type") == "MONTH"]
    quarters = [row for row in periods if row.get("period_type") == "QUARTER"]
    current_week = max(weeks, key=lambda row: row.get("period_start", "")) if weeks else None
    production_loaded, service_loaded = _load_split(current)

    cards = [
        _card(
            "Parts loaded",
            format_int(current.get("parts_loaded")),
            f"{format_int(current.get('carts_loaded'))} Carts / "
            f"{format_int(production_loaded)} Prd / {format_int(service_loaded)} Svc",
            "#147d86",
        ),
        _card("Paint processed", format_int(current.get("paint_carts")), f"{format_int(current.get('paint_pieces_processed'))} pieces", "#2f6f9f"),
        _card("PPY", format_percent(current["ppy"]), f"{format_int(current.get('ppy_approved'))} / {format_int(current.get('paint_decision_pieces'))} dispositions", "#d78d23"),
        _card("Paint FTY", format_percent(current["paint_fty"]), f"{format_int(current.get('paint_fty_approved'))} / {format_int(current.get('paint_fty_total'))} first-pass", "#2f6f9f"),
        _card("Receiving FTY", format_percent(current["receiving_fty"]), f"{format_int(current.get('receiving_approved'))} / {format_int(current.get('receiving_total'))} first decisions", "#38856d"),
        _card("Final FTY", format_percent(current["final_fty"]), f"{format_int(current.get('final_approved'))} / {format_int(current.get('final_total'))} first decisions", "#8a6aa8"),
        _card("Repaint", format_percent(current["repaint_percentage"]), f"{format_int(current.get('paint_fty_repaint_count'))} first-pass repaints", "#bb514b"),
        _card("Paint plan composite", format_percent(current["paint_plan_composite"]), "proxy — not standard OEE", "#8a6aa8", "PROVISIONAL"),
        _card("Pieces shipped", format_int(current.get("parts_shipped")), "non-service total", "#bb514b"),
        _card("Complete assy sets", format_int(current.get("complete_assy_sets")), "N33 four-piece patterns", "#147d86"),
        _card("Assembled bumpers", format_int(current.get("assembled_bumper_count")), "N71-6171", "#2f6f9f"),
        _card("Trailers prepared", format_int(current.get("trailers_prepared")), "snapshot value", "#d78d23"),
    ]

    throughput_fields = [
        ("paint_pieces_processed", "Paint pieces avg/day"),
        ("eol_inspected", "EOL avg/day"),
        ("painted_parts_shipped", "Paint ship avg/day"),
        ("bumpers_shipped", "Bumpers avg/day"),
    ]
    period_table = []
    for row in periods:
        period_table.append(
            {
                **row,
                "averages": [format_decimal(row[field + "_avg"], 1) for field, _ in throughput_fields],
                "ppy_text": format_percent(row["ppy"]),
                "paint_fty_text": format_percent(row["paint_fty"]),
                "receiving_fty_text": format_percent(row["receiving_fty"]),
                "final_fty_text": format_percent(row["final_fty"]),
                "repaint_text": format_percent(row["repaint_percentage"]),
                "composite_text": format_percent(row["paint_plan_composite"]),
            }
        )

    active_daily = [row for row in daily if row.get("production_day")]
    return {
        "snapshot": snapshot,
        "report_date": report_date,
        "generated_at": snapshot["generated_at"],
        "scope": snapshot["scope"],
        "cards": cards,
        "daily": daily,
        "active_daily": active_daily,
        "periods": period_table,
        "weeks": weeks,
        "months": months,
        "quarters": quarters,
        "current_week": current_week,
        "painters": _sort_by(snapshot["painters"], "date"),
        "shipping": _sort_by(snapshot["shipping"], "date"),
        "top_defects": snapshot["top_defects"],
        "attention": snapshot.get("attention", {}),
        "data_quality_notes": snapshot.get("data_quality_notes", []),
        "throughput_headers": [label for _, label in throughput_fields],
        "format_int": format_int,
        "format_decimal": format_decimal,
        "format_percent": format_percent,
    }
