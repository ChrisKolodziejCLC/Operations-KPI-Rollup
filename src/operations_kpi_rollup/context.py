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
        "operations-kpi-live-v8-physical-pass-metrics",
        "operations-kpi-live-v9-repaint-reject-yields",
        "operations-kpi-live-v10-master-repaintcount-yields",
        "operations-kpi-live-v11-repaint-line-set-counts",
        "operations-kpi-live-v12-shipped-rack-counts",
    }
    for collection in ("daily", "periods"):
        for row in snapshot[collection]:
            if snapshot.get("scope", {}).get("method_version") in {
                "operations-kpi-live-v7-daily-unique-pieces",
                "operations-kpi-live-v8-physical-pass-metrics",
                "operations-kpi-live-v9-repaint-reject-yields",
                "operations-kpi-live-v10-master-repaintcount-yields",
                "operations-kpi-live-v11-repaint-line-set-counts",
                "operations-kpi-live-v12-shipped-rack-counts",
            }:
                for unique_field, total_field, label in (
                    ("unique_pieces_loaded", "parts_loaded", "loaded unique-piece"),
                    ("unique_pieces_processed", "paint_pieces_processed", "painted unique-piece"),
                ):
                    if unique_field not in row:
                        raise ValueError(f"{collection} {label} count is missing")
                    unique_value = int(row.get(unique_field, 0))
                    if unique_value < 0 or unique_value > int(row.get(total_field, 0)):
                        raise ValueError(f"{collection} {label} count is outside its total")
            if snapshot.get("scope", {}).get("method_version") in {
                "operations-kpi-live-v8-physical-pass-metrics",
                "operations-kpi-live-v9-repaint-reject-yields",
                "operations-kpi-live-v10-master-repaintcount-yields",
                "operations-kpi-live-v11-repaint-line-set-counts",
                "operations-kpi-live-v12-shipped-rack-counts",
            }:
                for quantity_field in ("receiving_quantity", "final_quantity"):
                    if quantity_field not in row:
                        raise ValueError(f"{collection} {quantity_field} is missing")
                    if int(row.get(quantity_field, 0)) < 0:
                        raise ValueError(f"{collection} {quantity_field} is negative")
            method_version = snapshot.get("scope", {}).get("method_version")
            if method_version in {
                "operations-kpi-live-v9-repaint-reject-yields",
                "operations-kpi-live-v10-master-repaintcount-yields",
                "operations-kpi-live-v11-repaint-line-set-counts",
                "operations-kpi-live-v12-shipped-rack-counts",
            }:
                required_yield_fields = (
                    "reject_ppy_total", "reject_ppy_approved", "reject_ppy_rejected_count",
                    "reject_ppy_pending_count", "reject_fty_total", "reject_fty_approved",
                    "reject_fty_rejected_count", "reject_fty_pending_count",
                )
                if method_version in {
                    "operations-kpi-live-v10-master-repaintcount-yields",
                    "operations-kpi-live-v11-repaint-line-set-counts",
                    "operations-kpi-live-v12-shipped-rack-counts",
                }:
                    required_yield_fields += ("ppy_repaint_count",)
                missing_yield_fields = [field for field in required_yield_fields if field not in row]
                if missing_yield_fields:
                    raise ValueError(
                        f"{collection} reject yield fields are missing: " + ", ".join(missing_yield_fields)
                    )
                if any(int(row[field]) < 0 for field in required_yield_fields):
                    raise ValueError(f"{collection} reject yield count is negative")
                if int(row["reject_ppy_total"]) != int(row.get("paint_decision_pieces", 0)):
                    raise ValueError(f"{collection} reject PPY total does not equal physical paint passes")
                if int(row["reject_fty_total"]) != int(row.get("paint_fty_total", 0)):
                    raise ValueError(f"{collection} reject FTY total does not equal initial paint passes")
                if method_version in {
                    "operations-kpi-live-v10-master-repaintcount-yields",
                    "operations-kpi-live-v11-repaint-line-set-counts",
                    "operations-kpi-live-v12-shipped-rack-counts",
                }:
                    if int(row["reject_ppy_approved"]) + int(row["reject_ppy_rejected_count"]) + int(row["reject_ppy_pending_count"]) != int(row["reject_ppy_total"]):
                        raise ValueError(f"{collection} reject PPY outcomes do not equal its total")
                    if int(row["reject_fty_approved"]) + int(row["reject_fty_rejected_count"]) + int(row["reject_fty_pending_count"]) != int(row["reject_fty_total"]):
                        raise ValueError(f"{collection} reject FTY outcomes do not equal its total")
                    if int(row.get("ppy_approved", 0)) + int(row.get("ppy_repaint_count", 0)) + int(row["reject_ppy_pending_count"]) != int(row.get("paint_decision_pieces", 0)):
                        raise ValueError(f"{collection} repaint PPY outcomes do not equal physical paint passes")
                    if int(row.get("paint_fty_approved", 0)) + int(row.get("paint_fty_repaint_count", 0)) + int(row["reject_fty_pending_count"]) != int(row.get("paint_fty_total", 0)):
                        raise ValueError(f"{collection} repaint FTY outcomes do not equal initial paint passes")
                    if method_version in {
                        "operations-kpi-live-v11-repaint-line-set-counts",
                        "operations-kpi-live-v12-shipped-rack-counts",
                    }:
                        repaint_split_fields = (
                            "fuka_paint_fty_repaint_count",
                            "bumper_paint_fty_repaint_count",
                            "fairing_paint_fty_repaint_count",
                        )
                        missing_repaint_split = [field for field in repaint_split_fields if field not in row]
                        if missing_repaint_split:
                            raise ValueError(
                                f"{collection} repaint line-set fields are missing: "
                                + ", ".join(missing_repaint_split)
                            )
                        if any(int(row[field]) < 0 for field in repaint_split_fields):
                            raise ValueError(f"{collection} repaint line-set count is negative")
                        if sum(int(row[field]) for field in repaint_split_fields) != int(row["paint_fty_repaint_count"]):
                            raise ValueError(f"{collection} repaint line-set split does not equal paint_fty_repaint_count")
                else:
                    if int(row["reject_ppy_approved"]) + int(row["reject_ppy_rejected_count"]) != int(row["reject_ppy_total"]):
                        raise ValueError(f"{collection} reject PPY outcomes do not equal its total")
                    if int(row["reject_fty_approved"]) + int(row["reject_fty_rejected_count"]) != int(row["reject_fty_total"]):
                        raise ValueError(f"{collection} reject FTY outcomes do not equal its total")
                if int(row["reject_ppy_pending_count"]) > int(row["reject_ppy_total"]):
                    raise ValueError(f"{collection} reject PPY pending count exceeds its total")
                if int(row["reject_fty_pending_count"]) > int(row["reject_fty_total"]):
                    raise ValueError(f"{collection} reject FTY pending count exceeds its total")
                if method_version == "operations-kpi-live-v9-repaint-reject-yields" and int(row.get("paint_fty_approved", 0)) != int(row.get("paint_fty_total", 0)) - int(row.get("paint_fty_repaint_count", 0)):
                    raise ValueError(f"{collection} repaint FTY counts do not match the exit-day formula")
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
            _validate_split(
                row, collection, "racks_shipped",
                (
                    "fuka_racks_shipped",
                    "bumper_racks_shipped",
                    "fairing_racks_shipped",
                    "other_racks_shipped",
                ),
                "rack type",
                method_version == "operations-kpi-live-v12-shipped-rack-counts",
            )


def _sort_by(rows: Iterable[Dict[str, Any]], key: str) -> List[Dict[str, Any]]:
    return sorted(rows, key=lambda row: row.get(key, ""))


def _card(
    label: str,
    value: str,
    detail: str,
    color: str,
    status: str = "",
    secondary_detail: str = "",
) -> Dict[str, str]:
    return {
        "label": label,
        "value": value,
        "detail": detail,
        "secondary_detail": secondary_detail,
        "color": color,
        "status": status,
    }


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


def _shipped_piece_detail(snapshot: Dict[str, Any], report_date: str) -> str:
    counts = {"fuka": 0, "bumpers": 0, "fairings": 0}
    for row in snapshot.get("shipping", []):
        if row.get("date") != report_date:
            continue
        line_set = str(row.get("line_set") or "").strip().lower()
        pieces = int(row.get("pieces") or 0)
        if line_set == "bumpers":
            counts["bumpers"] += pieces
        elif line_set in {"fenders", "fuka"}:
            counts["fuka"] += pieces
        elif line_set in {"chassis fairings", "fairings"}:
            counts["fairings"] += pieces
    return (
        f"{format_int(counts['fuka'])} FUKA / "
        f"{format_int(counts['bumpers'])} Bumpers / "
        f"{format_int(counts['fairings'])} Fairings"
    )


def _repaint_line_set_detail(row: Dict[str, Any]) -> str:
    fields = (
        "fuka_paint_fty_repaint_count",
        "bumper_paint_fty_repaint_count",
        "fairing_paint_fty_repaint_count",
    )
    if not all(field in row for field in fields):
        return "Line-set detail pending refresh"
    return (
        f"{format_int(row['fuka_paint_fty_repaint_count'])} FUKA / "
        f"{format_int(row['bumper_paint_fty_repaint_count'])} Bumpers / "
        f"{format_int(row['fairing_paint_fty_repaint_count'])} Fairings"
    )


def _rack_detail(row: Dict[str, Any]) -> str:
    fields = (
        ("fuka_racks_shipped", "FUKA"),
        ("bumper_racks_shipped", "Bumper"),
        ("fairing_racks_shipped", "Fairing"),
    )
    if not all(field in row for field, _ in fields):
        return "Rack detail pending refresh"

    detail = []
    for field, label in fields:
        count = int(row.get(field, 0))
        detail.append(f"{format_int(count)} {label} {'rack' if count == 1 else 'racks'}")
    other = int(row.get("other_racks_shipped", 0))
    if other:
        detail.append(f"{format_int(other)} Other {'rack' if other == 1 else 'racks'}")
    return " / ".join(detail)


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
    trailer_detail = _rack_detail(current)
    shipped_piece_detail = _shipped_piece_detail(snapshot, report_date)

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
        _card("Repaint PPY", format_percent(current["repaint_ppy"]), f"{format_int(current.get('ppy_approved'))} / {format_int(current.get('paint_decision_pieces'))} exits", "#d78d23"),
        _card("Reject PPY", format_percent(current["reject_ppy"]), f"{format_int(current.get('reject_ppy_approved'))} / {format_int(current.get('reject_ppy_total'))} exits · {format_int(current.get('reject_ppy_pending_count'))} pending", "#bb514b"),
        _card("Repaint FTY", format_percent(current["repaint_fty"]), f"{format_int(current.get('paint_fty_approved'))} / {format_int(current.get('paint_fty_total'))} first exits", "#2f6f9f"),
        _card("Reject FTY", format_percent(current["reject_fty"]), f"{format_int(current.get('reject_fty_approved'))} / {format_int(current.get('reject_fty_total'))} first exits · {format_int(current.get('reject_fty_pending_count'))} pending", "#8a6aa8"),
        _card(
            "Repaint %",
            format_percent(current["repaint_percentage"]),
            f"{format_int(current.get('paint_fty_repaint_count'))} / {format_int(current.get('paint_fty_total'))} initial passes",
            "#d78d23",
            secondary_detail=_repaint_line_set_detail(current),
        ),
        _card("Receiving FTY", format_percent(current["receiving_fty"]), f"{format_int(current.get('receiving_approved'))} / {format_int(current.get('receiving_total'))} first decisions · Qty {format_int(current.get('receiving_quantity'))} by receive stamp", "#38856d"),
        _card("Final FTY", format_percent(current["final_fty"]), f"{format_int(current.get('final_approved'))} / {format_int(current.get('final_total'))} first decisions · Qty {format_int(current.get('final_quantity'))} by final stamp", "#8a6aa8"),
        _card("Paint plan composite", format_percent(current["paint_plan_composite"]), "proxy — not standard OEE", "#8a6aa8", "PROVISIONAL"),
        _card("Complete assy sets", format_int(current.get("complete_assy_sets")), "N33 / Chassis Fairing · dated by last assembled piece", "#147d86"),
        _card("Assembled bumpers", format_int(current.get("assembled_bumper_count")), "N71-6171 · AssembledDate", "#2f6f9f"),
        _card("Pieces shipped", format_int(current.get("parts_shipped")), shipped_piece_detail, "#bb514b"),
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
                "repaint_ppy_text": format_percent(row["repaint_ppy"]),
                "reject_ppy_text": format_percent(row["reject_ppy"]),
                "repaint_fty_text": format_percent(row["repaint_fty"]),
                "reject_fty_text": format_percent(row["reject_fty"]),
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
