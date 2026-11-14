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
        "operations-kpi-live-v13-mic-n71-breakdowns",
        "operations-kpi-live-v14-trailer-inspection-details",
        "operations-kpi-live-v15-description-family-mapping",
        "operations-kpi-live-v16-receiving-finesse",
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
                "operations-kpi-live-v13-mic-n71-breakdowns",
                "operations-kpi-live-v14-trailer-inspection-details",
                "operations-kpi-live-v15-description-family-mapping",
                "operations-kpi-live-v16-receiving-finesse",
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
                "operations-kpi-live-v13-mic-n71-breakdowns",
                "operations-kpi-live-v14-trailer-inspection-details",
                "operations-kpi-live-v15-description-family-mapping",
                "operations-kpi-live-v16-receiving-finesse",
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
                "operations-kpi-live-v13-mic-n71-breakdowns",
                "operations-kpi-live-v14-trailer-inspection-details",
                "operations-kpi-live-v15-description-family-mapping",
                "operations-kpi-live-v16-receiving-finesse",
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
                    "operations-kpi-live-v13-mic-n71-breakdowns",
                    "operations-kpi-live-v14-trailer-inspection-details",
                    "operations-kpi-live-v15-description-family-mapping",
                    "operations-kpi-live-v16-receiving-finesse",
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
                    "operations-kpi-live-v13-mic-n71-breakdowns",
                    "operations-kpi-live-v14-trailer-inspection-details",
                    "operations-kpi-live-v15-description-family-mapping",
                    "operations-kpi-live-v16-receiving-finesse",
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
                        "operations-kpi-live-v13-mic-n71-breakdowns",
                        "operations-kpi-live-v14-trailer-inspection-details",
                        "operations-kpi-live-v15-description-family-mapping",
                        "operations-kpi-live-v16-receiving-finesse",
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
            if (
                method_version in {
                    "operations-kpi-live-v13-mic-n71-breakdowns",
                    "operations-kpi-live-v14-trailer-inspection-details",
                    "operations-kpi-live-v15-description-family-mapping",
                    "operations-kpi-live-v16-receiving-finesse",
                }
                or "n71_6164_racks_shipped" in row
            ):
                required_breakdown_fields = (
                    "n71_6164_parts_loaded",
                    "n71_6164_carts_loaded",
                    "n71_6164_paint_carts",
                    "n71_6164_paint_pieces_processed",
                    "mic_complete_assy_sets",
                    "painted_complete_assy_sets",
                    "mic_assembled_bumper_count",
                    "painted_assembled_bumper_count",
                    "n71_6164_racks_shipped",
                )
                missing_breakdown_fields = [field for field in required_breakdown_fields if field not in row]
                if missing_breakdown_fields:
                    raise ValueError(
                        f"{collection} MIC/N71 breakdown fields are missing: "
                        + ", ".join(missing_breakdown_fields)
                    )
                if any(int(row[field]) < 0 for field in required_breakdown_fields):
                    raise ValueError(f"{collection} MIC/N71 breakdown count is negative")
                for detail_field, parent_field, label in (
                    ("n71_6164_parts_loaded", "production_parts_loaded", "loaded N71-6164"),
                    ("n71_6164_carts_loaded", "production_carts_loaded", "loaded-cart N71-6164"),
                    ("n71_6164_paint_carts", "production_paint_carts", "paint-cart N71-6164"),
                    (
                        "n71_6164_paint_pieces_processed",
                        "production_paint_pieces_processed",
                        "painted N71-6164",
                    ),
                ):
                    if int(row[detail_field]) > int(row.get(parent_field, 0)):
                        raise ValueError(f"{collection} {label} count exceeds its production bucket")
                if int(row["mic_complete_assy_sets"]) + int(row["painted_complete_assy_sets"]) != int(row.get("complete_assy_sets", 0)):
                    raise ValueError(f"{collection} complete assembly MIC/Painted split does not equal complete_assy_sets")
                if int(row["mic_assembled_bumper_count"]) + int(row["painted_assembled_bumper_count"]) != int(row.get("assembled_bumper_count", 0)):
                    raise ValueError(f"{collection} bumper MIC/Painted split does not equal assembled_bumper_count")
            if method_version in {
                "operations-kpi-live-v14-trailer-inspection-details",
                "operations-kpi-live-v15-description-family-mapping",
                "operations-kpi-live-v16-receiving-finesse",
            }:
                inspection_fields = (
                    "trailers_shipped",
                    "receiving_bumper_total",
                    "receiving_bumper_approved",
                    "receiving_fairing_total",
                    "receiving_fairing_approved",
                    "final_fuka_total",
                    "final_fuka_approved",
                    "final_bumper_total",
                    "final_bumper_approved",
                    "final_fairing_total",
                    "final_fairing_approved",
                    "paint_fty_repair_count",
                    "fuka_paint_fty_repair_count",
                    "fairing_paint_fty_repair_count",
                    "bumper_paint_fty_repair_count",
                    "staged_carts",
                    "production_staged_carts",
                    "bv_staged_carts",
                    "service_staged_carts",
                    "staged_pieces",
                    "production_staged_pieces",
                    "bv_staged_pieces",
                    "service_staged_pieces",
                )
                missing_inspection_fields = [field for field in inspection_fields if field not in row]
                if missing_inspection_fields:
                    raise ValueError(
                        f"{collection} trailer/inspection detail fields are missing: "
                        + ", ".join(missing_inspection_fields)
                    )
                if any(int(row[field]) < 0 for field in inspection_fields):
                    raise ValueError(f"{collection} trailer/inspection detail count is negative")
                for family, prefix in (
                    ("receiving Bumpers", "receiving_bumper"),
                    ("receiving Fairings", "receiving_fairing"),
                    ("final FUKA", "final_fuka"),
                    ("final Bumpers", "final_bumper"),
                    ("final Fairings", "final_fairing"),
                ):
                    if int(row[f"{prefix}_approved"]) > int(row[f"{prefix}_total"]):
                        raise ValueError(f"{collection} {family} approved count exceeds its total")
                if int(row["receiving_bumper_total"]) + int(row["receiving_fairing_total"]) != int(row.get("receiving_total", 0)):
                    raise ValueError(f"{collection} receiving family totals do not equal receiving_total")
                if int(row["receiving_bumper_approved"]) + int(row["receiving_fairing_approved"]) != int(row.get("receiving_approved", 0)):
                    raise ValueError(f"{collection} receiving family approvals do not equal receiving_approved")
                if sum(int(row[field]) for field in ("final_fuka_total", "final_bumper_total", "final_fairing_total")) != int(row.get("final_total", 0)):
                    raise ValueError(f"{collection} final family totals do not equal final_total")
                if sum(int(row[field]) for field in ("final_fuka_approved", "final_bumper_approved", "final_fairing_approved")) != int(row.get("final_approved", 0)):
                    raise ValueError(f"{collection} final family approvals do not equal final_approved")
                if sum(int(row[field]) for field in ("fuka_paint_fty_repair_count", "fairing_paint_fty_repair_count", "bumper_paint_fty_repair_count")) != int(row["paint_fty_repair_count"]):
                    raise ValueError(f"{collection} finesse family repair counts do not equal paint_fty_repair_count")
                if int(row["paint_fty_repair_count"]) > int(row.get("reject_fty_rejected_count", 0)):
                    raise ValueError(f"{collection} finesse repairs exceed first-pass rejected outcomes")
                if sum(int(row[field]) for field in ("production_staged_carts", "bv_staged_carts", "service_staged_carts")) != int(row["staged_carts"]):
                    raise ValueError(f"{collection} staged cart split does not equal staged_carts")
                if sum(int(row[field]) for field in ("production_staged_pieces", "bv_staged_pieces", "service_staged_pieces")) != int(row["staged_pieces"]):
                    raise ValueError(f"{collection} staged piece split does not equal staged_pieces")
            if method_version == "operations-kpi-live-v16-receiving-finesse":
                finesse_fields = (
                    "finesse_rejected_count",
                    "finesse_repair_count",
                    "finesse_repaint_count",
                    "finesse_pending_count",
                    "bumper_finesse_repair_count",
                    "fairing_finesse_repair_count",
                    "other_finesse_repair_count",
                )
                missing_finesse_fields = [field for field in finesse_fields if field not in row]
                if missing_finesse_fields:
                    raise ValueError(
                        f"{collection} Receiving/Finesse fields are missing: "
                        + ", ".join(missing_finesse_fields)
                    )
                if any(int(row[field]) < 0 for field in finesse_fields):
                    raise ValueError(f"{collection} Receiving/Finesse count is negative")
                if int(row["finesse_rejected_count"]) != int(row.get("receiving_total", 0)) - int(row.get("receiving_approved", 0)):
                    raise ValueError(f"{collection} Finesse rejected count does not equal first Receiving rejects")
                if sum(
                    int(row[field])
                    for field in (
                        "finesse_repair_count",
                        "finesse_repaint_count",
                        "finesse_pending_count",
                    )
                ) != int(row["finesse_rejected_count"]):
                    raise ValueError(f"{collection} Finesse outcomes do not equal first Receiving rejects")
                if sum(
                    int(row[field])
                    for field in (
                        "bumper_finesse_repair_count",
                        "fairing_finesse_repair_count",
                        "other_finesse_repair_count",
                    )
                ) != int(row["finesse_repair_count"]):
                    raise ValueError(f"{collection} Finesse repair family split does not equal finesse_repair_count")
            rack_split_fields = (
                "fuka_racks_shipped",
                "bumper_racks_shipped",
                "fairing_racks_shipped",
                "other_racks_shipped",
            )
            if (
                method_version in {
                    "operations-kpi-live-v13-mic-n71-breakdowns",
                    "operations-kpi-live-v14-trailer-inspection-details",
                    "operations-kpi-live-v15-description-family-mapping",
                    "operations-kpi-live-v16-receiving-finesse",
                }
                or "n71_6164_racks_shipped" in row
            ):
                rack_split_fields = (
                    "fuka_racks_shipped",
                    "bumper_racks_shipped",
                    "n71_6164_racks_shipped",
                    "fairing_racks_shipped",
                    "other_racks_shipped",
                )
            _validate_split(
                row, collection, "racks_shipped",
                rack_split_fields,
                "rack type",
                method_version in {
                    "operations-kpi-live-v12-shipped-rack-counts",
                    "operations-kpi-live-v13-mic-n71-breakdowns",
                    "operations-kpi-live-v14-trailer-inspection-details",
                    "operations-kpi-live-v15-description-family-mapping",
                    "operations-kpi-live-v16-receiving-finesse",
                },
            )

    if snapshot.get("scope", {}).get("method_version") in {
        "operations-kpi-live-v13-mic-n71-breakdowns",
        "operations-kpi-live-v14-trailer-inspection-details",
        "operations-kpi-live-v15-description-family-mapping",
        "operations-kpi-live-v16-receiving-finesse",
    }:
        allowed_line_sets = {"FUKA", "Bumpers", "N71-6164", "Fairings", "Other"}
        report_shipping = [row for row in snapshot.get("shipping", []) if row.get("date") == snapshot["report_date"]]
        unexpected_line_sets = sorted(
            {str(row.get("line_set") or "") for row in report_shipping} - allowed_line_sets
        )
        if unexpected_line_sets:
            raise ValueError("report-date shipping has unexpected line sets: " + ", ".join(unexpected_line_sets))
        report_daily = next(row for row in snapshot["daily"] if row.get("date") == snapshot["report_date"])
        if sum(int(row.get("pieces", 0)) for row in report_shipping) != int(report_daily.get("parts_shipped", 0)):
            raise ValueError("report-date shipping detail does not equal parts_shipped")


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
    return (
        row.get("production_carts_loaded", 0),
        row.get("bv_carts_loaded", 0),
        row.get("service_carts_loaded", 0),
    )


def _paint_cart_split(row: Dict[str, Any]) -> tuple[Any, Any, Any]:
    if "production_paint_carts" not in row and "service_paint_carts" not in row:
        return row.get("paint_carts", 0), 0, 0
    return (
        row.get("production_paint_carts", 0),
        row.get("bv_paint_carts", 0),
        row.get("service_paint_carts", 0),
    )


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
    counts = {"fuka": 0, "bumpers": 0, "n71_6164": 0, "fairings": 0, "other": 0}
    for row in snapshot.get("shipping", []):
        if row.get("date") != report_date:
            continue
        line_set = str(row.get("line_set") or "").strip().lower()
        pieces = int(row.get("pieces") or 0)
        if line_set == "bumpers":
            counts["bumpers"] += pieces
        elif line_set == "n71-6164":
            counts["n71_6164"] += pieces
        elif line_set in {"fenders", "fuka"}:
            counts["fuka"] += pieces
        elif line_set in {"chassis fairings", "fairings"}:
            counts["fairings"] += pieces
        elif line_set == "other":
            counts["other"] += pieces
    detail = (
        f"{format_int(counts['fuka'])} FUKA / "
        f"{format_int(counts['bumpers'])} Bumpers / "
        f"{format_int(counts['n71_6164'])} N71-6164 / "
        f"{format_int(counts['fairings'])} Fairings"
    )
    if counts["other"]:
        detail += f" / {format_int(counts['other'])} Other"
    return detail


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


def _inspection_family_detail(
    row: Dict[str, Any],
    fields: tuple[tuple[str, str], ...],
) -> str:
    lines = []
    for prefix, label in fields:
        approved = row.get(f"{prefix}_approved")
        total = row.get(f"{prefix}_total")
        lines.append(
            f"{label} {format_percent(safe_ratio(approved, total))} · "
            f"{format_int(approved)} / {format_int(total)}"
        )
    return "\n".join(lines)


def _finesse_detail(row: Dict[str, Any]) -> str:
    if "finesse_repair_count" in row:
        repaired = int(row.get("finesse_repair_count") or 0)
        repaint = int(row.get("finesse_repaint_count") or 0)
        lines = [
            f"{format_int(repaired)} Repaired / {format_int(repaired + repaint)} Resolved Receiving Rejects",
            f"{format_int(repaint)} Repaint / {format_int(row.get('finesse_pending_count'))} Pending",
            f"{format_int(row.get('bumper_finesse_repair_count'))} Bumpers Repaired",
            f"{format_int(row.get('fairing_finesse_repair_count'))} Fairings Repaired",
        ]
        if int(row.get("other_finesse_repair_count") or 0):
            lines.append(f"{format_int(row.get('other_finesse_repair_count'))} Other Repaired")
        return "\n".join(lines)
    return "\n".join(
        (
            f"FUKA {format_int(row.get('fuka_paint_fty_repair_count'))} repaired",
            f"Fairings {format_int(row.get('fairing_paint_fty_repair_count'))} repaired",
            f"Bumpers {format_int(row.get('bumper_paint_fty_repair_count'))} repaired",
        )
    )


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
    shipped_piece_detail = _shipped_piece_detail(snapshot, report_date)
    complete_assy_detail = (
        f"{format_int(current.get('mic_complete_assy_sets'))} MIC / {format_int(current.get('painted_complete_assy_sets'))} Painted"
        if "mic_complete_assy_sets" in current and "painted_complete_assy_sets" in current
        else "N33 / Chassis Fairing · dated by last assembled piece"
    )
    assembled_bumper_detail = (
        f"{format_int(current.get('mic_assembled_bumper_count'))} MIC / {format_int(current.get('painted_assembled_bumper_count'))} Painted"
        if "mic_assembled_bumper_count" in current and "painted_assembled_bumper_count" in current
        else "N71-6171 · AssembledDate"
    )

    cards = [
        _card(
            "Pieces loaded",
            f"{format_int(current.get('parts_loaded'))} Total / {format_int(current['unique_pieces_loaded']) if 'unique_pieces_loaded' in current else '—'} Unique",
            f"Carts {format_int(production_carts)} Prd / {format_int(bv_carts)} BV / {format_int(service_carts)} Svc · Pieces {format_int(production_loaded)} Prd / {format_int(bv_loaded)} BV / {format_int(service_loaded)} Svc",
            "#147d86",
        ),
        _card(
            "Pieces staged",
            f"{format_int(current.get('staged_carts'))} Carts / {format_int(current.get('staged_pieces'))} Pieces",
            f"Carts {format_int(current.get('production_staged_carts'))} Prd / {format_int(current.get('bv_staged_carts'))} BV / {format_int(current.get('service_staged_carts'))} Svc · Pieces {format_int(current.get('production_staged_pieces'))} Prd / {format_int(current.get('bv_staged_pieces'))} BV / {format_int(current.get('service_staged_pieces'))} Svc",
            "#38856d",
        ),
        _card(
            "Pieces painted",
            f"{format_int(current.get('paint_pieces_processed'))} Total / {format_int(current['unique_pieces_processed']) if 'unique_pieces_processed' in current else '—'} Unique",
            f"Carts {format_int(production_paint_carts)} Prd / {format_int(bv_paint_carts)} BV / {format_int(service_paint_carts)} Svc · Pieces {format_int(production_paint_pieces)} Prd / {format_int(bv_paint_pieces)} BV / {format_int(service_paint_pieces)} Svc",
            "#2f6f9f",
        ),
        _card(
            "Repaint %",
            format_percent(current["repaint_percentage"]),
            f"{format_int(current.get('paint_fty_repaint_count'))} / {format_int(current.get('paint_fty_total'))} initial passes",
            "#d78d23",
            secondary_detail=_repaint_line_set_detail(current),
        ),
        _card(
            "Finesse %",
            format_percent(current["finesse_percentage"]),
            _finesse_detail(current),
            "#38856d",
        ),
        _card("Repaint PPY", format_percent(current["repaint_ppy"]), f"{format_int(current.get('ppy_approved'))} / {format_int(current.get('paint_decision_pieces'))} exits", "#d78d23"),
        _card("Reject PPY", format_percent(current["reject_ppy"]), f"{format_int(current.get('reject_ppy_approved'))} / {format_int(current.get('reject_ppy_total'))} exits · {format_int(current.get('reject_ppy_pending_count'))} pending", "#bb514b"),
        _card("Repaint FTY", format_percent(current["repaint_fty"]), f"{format_int(current.get('paint_fty_approved'))} / {format_int(current.get('paint_fty_total'))} first exits", "#2f6f9f"),
        _card("Reject FTY", format_percent(current["reject_fty"]), f"{format_int(current.get('reject_fty_approved'))} / {format_int(current.get('reject_fty_total'))} first exits · {format_int(current.get('reject_fty_pending_count'))} pending", "#8a6aa8"),
        _card(
            "Receiving FTY",
            format_percent(current["receiving_fty"]),
            _inspection_family_detail(
                current,
                (("receiving_bumper", "Bumpers"), ("receiving_fairing", "Fairings")),
            ),
            "#38856d",
        ),
        _card(
            "Final FTY",
            format_percent(current["final_fty"]),
            _inspection_family_detail(
                current,
                (("final_fuka", "FUKA"), ("final_bumper", "Bumpers"), ("final_fairing", "Fairings")),
            ),
            "#8a6aa8",
        ),
        _card("Paint plan composite", format_percent(current["paint_plan_composite"]), "proxy — not standard OEE", "#8a6aa8", "PROVISIONAL"),
        _card(
            "Complete assy sets",
            format_int(current.get("complete_assy_sets")),
            complete_assy_detail,
            "#147d86",
        ),
        _card(
            "Assembled bumpers",
            format_int(current.get("assembled_bumper_count")),
            assembled_bumper_detail,
            "#2f6f9f",
        ),
        _card("Pieces shipped", format_int(current.get("parts_shipped")), shipped_piece_detail, "#bb514b"),
        _card(
            "Trailers",
            f"{format_int(current.get('trailers_prepared'))} Prepped / {format_int(current.get('trailers_shipped'))} Shipped",
            "DriverLog TimeOut departures",
            "#d78d23",
        ),
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
