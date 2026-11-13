from datetime import date
from typing import Any, Dict, Iterable, List

from .metrics import enrich_metric_row, format_decimal, format_int, format_percent, safe_ratio


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


def _validate_split(
    row: Dict[str, Any], collection: str, total_field: str, split_fields: tuple[str, ...], label: str,
    require_complete: bool,
) -> None:
    present = [field in row for field in split_fields]
    if not any(present):
        if require_complete:
            raise ValueError(f"{collection} {label} split is incomplete")
        return
    missing = [field for field in split_fields if field not in row]
    legacy_bv_gap = not require_complete and missing and all(field.startswith("bv_") for field in missing)
    if missing and not legacy_bv_gap:
        raise ValueError(f"{collection} {label} split is incomplete")
    if sum(int(row.get(field, 0)) for field in split_fields) != int(row.get(total_field, 0)):
        raise ValueError(f"{collection} {label} split does not equal {total_field}")


def validate_snapshot(snapshot: Dict[str, Any]) -> None:
    missing = sorted(REQUIRED_TOP_LEVEL - set(snapshot))
    if missing:
        raise ValueError("snapshot is missing required fields: " + ", ".join(missing))
    if snapshot["schema_version"] != "operations-kpi-snapshot/v1":
        raise ValueError("unsupported snapshot schema_version")
    date.fromisoformat(snapshot["report_date"])
    if not any(row.get("date") == snapshot["report_date"] for row in snapshot["daily"]):
        raise ValueError("snapshot daily rows do not include report_date")
    require_complete_splits = snapshot.get("scope", {}).get("method_version") in {
        "operations-kpi-live-v5-bv-quality-trailer-split",
        "operations-kpi-live-v6-original-paint-repaint-cohort",
        "operations-kpi-live-v7-daily-unique-pieces",
    }
    for collection in ("daily", "periods"):
        for row in snapshot[collection]:
            if snapshot.get("scope", {}).get("method_version") == "operations-kpi-live-v7-daily-unique-pieces":
                for unique_field, total_field, label in (
                    ("unique_pieces_loaded", "parts_loaded", "loaded unique-piece"),
                    ("unique_pieces_processed", "paint_pieces_processed", "painted unique-piece"),
                ):
                    if unique_field not in row:
                        raise ValueError(f"{collection} {label} count is missing")
                    unique_value = int(row.get(unique_field, 0))
                    if unique_value < 0 or unique_value > int(row.get(total_field, 0)):
                        raise ValueError(f"{collection} {label} count is outside its total")
            _validate_split(
                row, collection, "parts_loaded",
                ("production_parts_loaded", "bv_parts_loaded", "service_parts_loaded"), "load", require_complete_splits,
            )
            _validate_split(
                row, collection, "carts_loaded",
                ("production_carts_loaded", "bv_carts_loaded", "service_carts_loaded"), "cart", require_complete_splits,
            )
            _validate_split(
                row, collection, "paint_carts",
                ("production_paint_carts", "bv_paint_carts", "service_paint_carts"), "paint cart", require_complete_splits,
            )
            _validate_split(
                row, collection, "paint_pieces_processed",
                (
                    "production_paint_pieces_processed",
                    "bv_paint_pieces_processed",
                    "service_paint_pieces_processed",
                ),
                "paint piece", require_complete_splits,
            )
            _validate_split(
                row, collection, "paint_decision_pieces",
                (
                    "production_paint_decision_pieces",
                    "bv_paint_decision_pieces",
                    "service_paint_decision_pieces",
                ),
                "PPY denominator", require_complete_splits,
            )
            _validate_split(
                row, collection, "ppy_approved",
                ("production_ppy_approved", "bv_ppy_approved", "service_ppy_approved"),
                "PPY numerator", require_complete_splits,
            )
            _validate_split(
                row, collection, "paint_fty_total",
                ("production_paint_fty_total", "bv_paint_fty_total", "service_paint_fty_total"),
                "paint FTY denominator", require_complete_splits,
            )
            _validate_split(
                row, collection, "paint_fty_approved",
                (
                    "production_paint_fty_approved",
                    "bv_paint_fty_approved",
                    "service_paint_fty_approved",
                ),
                "paint FTY numerator", require_complete_splits,
            )
            _validate_split(
                row, collection, "trailers_prepared",
                (
                    "fuka_trailers_prepared",
                    "bumper_trailers_prepared",
                    "fairing_trailers_prepared",
                    "other_trailers_prepared",
                ),
                "trailer type", require_complete_splits,
            )


def _sort_by(rows: Iterable[Dict[str, Any]], key: str) -> List[Dict[str, Any]]:
    return sorted(rows, key=lambda row: row.get(key, ""))


def _card(label: str, value: str, detail: str, color: str, status: str = "") -> Dict[str, str]:
    return {"label": label, "value": value, "detail": detail, "color": color, "status": status}


def _load_split(row: Dict[str, Any]) -> tuple[Any, Any, Any]:
    if "production_parts_loaded" not in row and "service_parts_loaded" not in row:
        return row.get("parts_loaded", 0), 0, 0
    return (
        row.get("production_parts_loaded", 0),
        row.get("bv_parts_loaded", 0),
        row.get("service_parts_loaded", 0),
    )


def _cart_split(row: Dict[str, Any]) -> tuple[Any, Any, Any]:
    if "production_carts_loaded" not in row and "service_carts_loaded" not in row:
        return row.get("carts_loaded", 0), 0, 0
    return row.get("production_carts_loaded", 0), row.get("bv_carts_loaded", 0), row.get("service_carts_loaded", 0)


def _paint_cart_split(row: Dict[str, Any]) -> tuple[Any, Any, Any]:
    if "production_paint_carts" not in row and "service_paint_carts" not in row:
        return row.get("paint_carts", 0), 0, 0
    return row.get("production_paint_carts", 0), row.get("bv_paint_carts", 0), row.get("service_paint_carts", 0)


def _paint_piece_split(row: Dict[str, Any]) -> tuple[Any, Any, Any]:
    if "production_paint_pieces_processed" not in row and "service_paint_pieces_processed" not in row:
        return row.get("paint_pieces_processed", 0), 0, 0
    return (
        row.get("production_paint_pieces_processed", 0),
        row.get("bv_paint_pieces_processed", 0),
        row.get("service_paint_pieces_processed", 0),
    )


def _rate_split(row: Dict[str, Any], numerator: str, denominator: str) -> str:
    values = []
    for prefix, label in (("production_", "Prd"), ("bv_", "BV"), ("service_", "Svc")):
        values.append(format_percent(safe_ratio(row.get(prefix + numerator), row.get(prefix + denominator))))
    return f"Prd {values[0]} / BV {values[1]} / Svc {values[2]}"


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
    production_loaded, bv_loaded, service_loaded = _load_split(current)
    production_carts, bv_carts, service_carts = _cart_split(current)
    production_paint_carts, bv_paint_carts, service_paint_carts = _paint_cart_split(current)
    production_paint_pieces, bv_paint_pieces, service_paint_pieces = _paint_piece_split(current)
    trailer_detail = (
        f"{format_int(current.get('fuka_trailers_prepared'))} FUKA / "
        f"{format_int(current.get('bumper_trailers_prepared'))} Bumpers / "
        f"{format_int(current.get('fairing_trailers_prepared'))} Fairings"
    )
    if current.get("other_trailers_prepared", 0):
        trailer_detail += f" / {format_int(current.get('other_trailers_prepared'))} Other"

    cards = [
        _card(
            "Pieces loaded",
            f"{format_int(current.get('parts_loaded'))} Total / {format_int(current['unique_pieces_loaded']) if 'unique_pieces_loaded' in current else '—'} Unique",
            f"Carts {format_int(production_carts)} Prd / {format_int(bv_carts)} BV / {format_int(service_carts)} Svc · Pieces {format_int(production_loaded)} Prd / {format_int(bv_loaded)} BV / {format_int(service_loaded)} Svc",
            "#147d86",
        ),
        _card(
            "Pieces painted",
            f"{format_int(current.get('paint_pieces_processed'))} Total / {format_int(current['unique_pieces_processed']) if 'unique_pieces_processed' in current else '—'} Unique",
            f"Carts {format_int(production_paint_carts)} Prd / {format_int(bv_paint_carts)} BV / {format_int(service_paint_carts)} Svc · Pieces {format_int(production_paint_pieces)} Prd / {format_int(bv_paint_pieces)} BV / {format_int(service_paint_pieces)} Svc",
            "#2f6f9f",
        ),
        _card("PPY", format_percent(current["ppy"]), _rate_split(current, "ppy_approved", "paint_decision_pieces"), "#d78d23"),
        _card("Paint FTY", format_percent(current["paint_fty"]), _rate_split(current, "paint_fty_approved", "paint_fty_total"), "#2f6f9f"),
        _card("Receiving FTY", format_percent(current["receiving_fty"]), f"{format_int(current.get('receiving_approved'))} / {format_int(current.get('receiving_total'))} first decisions", "#38856d"),
        _card("Final FTY", format_percent(current["final_fty"]), f"{format_int(current.get('final_approved'))} / {format_int(current.get('final_total'))} first decisions", "#8a6aa8"),
        _card("Repaint", format_percent(current["repaint_percentage"]), f"{format_int(current.get('paint_fty_repaint_count'))} first-pass repaints", "#bb514b"),
        _card("Paint plan composite", format_percent(current["paint_plan_composite"]), "proxy — not standard OEE", "#8a6aa8", "PROVISIONAL"),
        _card("Pieces shipped", format_int(current.get("parts_shipped")), "non-service total", "#bb514b"),
        _card("Complete assy sets", format_int(current.get("complete_assy_sets")), "N33 four-piece patterns", "#147d86"),
        _card("Assembled bumpers", format_int(current.get("assembled_bumper_count")), "N71-6171", "#2f6f9f"),
        _card("Trailers prepared", format_int(current.get("trailers_prepared")), trailer_detail, "#d78d23"),
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
