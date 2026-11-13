"""Translate the bounded legacy rollup contract into an immutable v1 snapshot."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import os
import re
from typing import Any, Dict, Iterable, List, Mapping, Optional
from zoneinfo import ZoneInfo

from .context import validate_snapshot
from .odbc import execute_operations_rollup


DATE_WRAPPER = re.compile(r"^/Date\((\d+)(?:[+-]\d+)?\)/$")
PERIOD_TYPE_ORDER = {"WEEK": 1, "MONTH": 2, "QUARTER": 3}
CURRENT_METHOD_VERSION = "operations-kpi-live-v11-repaint-line-set-counts"


def _integer(value: Any) -> int:
    if value is None or value == "":
        return 0
    return int(Decimal(str(value)))


def _number(value: Any, places: int = 4) -> float:
    if value is None or value == "":
        return 0.0
    return round(float(Decimal(str(value))), places)


def _date_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    wrapper = DATE_WRAPPER.match(text)
    if wrapper:
        return datetime.fromtimestamp(int(wrapper.group(1)) / 1000, tz=timezone.utc).date().isoformat()
    return date.fromisoformat(text[:10]).isoformat()


def _sets_by_index(result_sets: Iterable[Mapping[str, Any]]) -> Dict[int, List[Dict[str, Any]]]:
    indexed: Dict[int, List[Dict[str, Any]]] = {}
    for result_set in result_sets:
        indexed[int(result_set["index"])] = [dict(row) for row in result_set.get("rows", [])]
    return indexed


def _metric_fields(row: Mapping[str, Any]) -> Dict[str, int]:
    source_to_snapshot = {
        "parts_loaded": "parts_loaded",
        "production_parts_loaded": "production_parts_loaded",
        "bv_parts_loaded": "bv_parts_loaded",
        "service_parts_loaded": "service_parts_loaded",
        "unique_pieces_loaded": "unique_pieces_loaded",
        "carts_loaded": "carts_loaded",
        "production_carts_loaded": "production_carts_loaded",
        "bv_carts_loaded": "bv_carts_loaded",
        "service_carts_loaded": "service_carts_loaded",
        "paint_processed": "paint_carts",
        "production_paint_carts": "production_paint_carts",
        "bv_paint_carts": "bv_paint_carts",
        "service_paint_carts": "service_paint_carts",
        "paint_pieces_processed": "paint_pieces_processed",
        "production_paint_pieces_processed": "production_paint_pieces_processed",
        "bv_paint_pieces_processed": "bv_paint_pieces_processed",
        "service_paint_pieces_processed": "service_paint_pieces_processed",
        "unique_pieces_processed": "unique_pieces_processed",
        "paint_decision_pieces": "paint_decision_pieces",
        "production_paint_decision_pieces": "production_paint_decision_pieces",
        "bv_paint_decision_pieces": "bv_paint_decision_pieces",
        "service_paint_decision_pieces": "service_paint_decision_pieces",
        "ppy_approved": "ppy_approved",
        "production_ppy_approved": "production_ppy_approved",
        "bv_ppy_approved": "bv_ppy_approved",
        "service_ppy_approved": "service_ppy_approved",
        "ppy_repaint_count": "ppy_repaint_count",
        "paint_fty_total": "paint_fty_total",
        "production_paint_fty_total": "production_paint_fty_total",
        "bv_paint_fty_total": "bv_paint_fty_total",
        "service_paint_fty_total": "service_paint_fty_total",
        "paint_fty_approved": "paint_fty_approved",
        "production_paint_fty_approved": "production_paint_fty_approved",
        "bv_paint_fty_approved": "bv_paint_fty_approved",
        "service_paint_fty_approved": "service_paint_fty_approved",
        "paint_fty_repaint_count": "paint_fty_repaint_count",
        "fuka_paint_fty_repaint_count": "fuka_paint_fty_repaint_count",
        "bumper_paint_fty_repaint_count": "bumper_paint_fty_repaint_count",
        "fairing_paint_fty_repaint_count": "fairing_paint_fty_repaint_count",
        "reject_ppy_total": "reject_ppy_total",
        "reject_ppy_approved": "reject_ppy_approved",
        "reject_ppy_rejected_count": "reject_ppy_rejected_count",
        "reject_ppy_pending_count": "reject_ppy_pending_count",
        "reject_fty_total": "reject_fty_total",
        "reject_fty_approved": "reject_fty_approved",
        "reject_fty_rejected_count": "reject_fty_rejected_count",
        "reject_fty_pending_count": "reject_fty_pending_count",
        "receiving_total": "receiving_total",
        "receiving_approved": "receiving_approved",
        "receiving_quantity": "receiving_quantity",
        "final_total": "final_total",
        "final_approved": "final_approved",
        "final_quantity": "final_quantity",
        "eol_inspected": "eol_inspected",
        "painted_parts_shipped": "painted_parts_shipped",
        "bumpers_shipped": "bumpers_shipped",
        "parts_shipped": "parts_shipped",
        "complete_assy_sets": "complete_assy_sets",
        "assembled_bumper_count": "assembled_bumper_count",
        "trailers_prepared": "trailers_prepared",
        "fuka_trailers_prepared": "fuka_trailers_prepared",
        "bumper_trailers_prepared": "bumper_trailers_prepared",
        "fairing_trailers_prepared": "fairing_trailers_prepared",
        "other_trailers_prepared": "other_trailers_prepared",
        "pieces_scheduled": "pieces_scheduled",
        "hours_scheduled": "hours_scheduled",
        "paint_hours": "paint_hours",
    }
    return {target: _integer(row.get(source)) for source, target in source_to_snapshot.items()}


def _daily_row(row: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "date": _date_text(row.get("period_start")),
        "production_day": bool(_integer(row.get("data_available"))) and _integer(row.get("data_days")) > 0,
        **_metric_fields(row),
    }


def _period_row(row: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "period_type": str(row.get("period_type") or "").upper(),
        "label": str(row.get("period_label") or ""),
        "period_start": _date_text(row.get("period_start")),
        "period_end": _date_text(row.get("period_end")),
        "calendar_days": _integer(row.get("calendar_days")),
        "data_days": _integer(row.get("data_days")),
        **_metric_fields(row),
    }


def snapshot_from_rollup(
    report_date: date,
    result_sets: Iterable[Mapping[str, Any]],
    generated_at: Optional[datetime] = None,
) -> Dict[str, Any]:
    indexed = _sets_by_index(result_sets)
    metadata = indexed.get(0, [{}])[0] if indexed.get(0) else {}
    daily = sorted((_daily_row(row) for row in indexed.get(2, [])), key=lambda row: row["date"])
    if not any(row["date"] == report_date.isoformat() for row in daily):
        raise ValueError("The rollup procedure did not return the requested report date.")

    periods = [
        _period_row(row)
        for index in (3, 4, 5)
        for row in indexed.get(index, [])
        if str(row.get("period_type") or "").upper() in PERIOD_TYPE_ORDER
        and _integer(row.get("data_available")) > 0
    ]
    periods.sort(key=lambda row: (PERIOD_TYPE_ORDER[row["period_type"]], row["period_start"]))

    painters = [
        {
            "date": _date_text(row.get("report_date")),
            "painter": str(row.get("painter_name") or "Unknown"),
            "booth": _integer(row.get("booth_number")),
            "parts": _integer(row.get("parts_painted")),
            "minutes": _integer(row.get("minutes_logged")),
            "parts_per_hour": _number(row.get("parts_per_hour"), 1),
        }
        for row in indexed.get(8, [])
    ]
    top_defects = [
        {
            "step": str(row.get("inspection_step") or "Unknown"),
            "description": str(row.get("defect_description") or "Unspecified"),
            "count": _integer(row.get("defect_count")),
        }
        for row in indexed.get(9, [])
    ]
    shipping = [
        {
            "date": _date_text(row.get("report_date")),
            "line_set": str(row.get("line_set") or "Other"),
            "pieces": _integer(row.get("pieces_shipped")),
        }
        for row in indexed.get(12, [])
    ]

    timezone_name = os.environ.get("KPI_TIMEZONE", "America/Indiana/Indianapolis")
    observed_at = generated_at or datetime.now(ZoneInfo(timezone_name))
    history_start = _date_text(metadata.get("history_start")) if metadata.get("history_start") else "2026-09-08"
    painter_note = (
        "Painter names are included for this restricted pilot."
        if painters
        else "Employee-level painter detail is disabled in the initial internal pilot."
    )
    snapshot: Dict[str, Any] = {
        "schema_version": "operations-kpi-snapshot/v1",
        "report_date": report_date.isoformat(),
        "generated_at": observed_at.isoformat(timespec="seconds"),
        "scope": {
            "label": "Grand Prairie operations; read-only on-demand pilot",
            "method_version": CURRENT_METHOD_VERSION,
            "history_start": history_start,
            "timezone": timezone_name,
        },
        "daily": daily,
        "periods": periods,
        "painters": painters,
        "shipping": shipping,
        "top_defects": top_defects,
        "attention": {
            "items": [
                {
                    "title": "Pilot metric contract",
                    "detail": "This build corrects labels and denominators but still reads the recovered legacy rollup procedure. Leadership promotion requires metric-owner validation.",
                },
                {
                    "title": "Historical values are snapshotted",
                    "detail": "Each refresh writes an immutable JSON snapshot so later QPTS state changes do not silently rewrite the displayed report.",
                },
                {
                    "title": "High-repaint appendix suppressed",
                    "detail": "The legacy unbounded part-detail query is never requested by this service.",
                },
            ]
        },
        "data_quality_notes": [
            "Period averages use represented production days rather than every calendar date.",
            "Every displayed quality rate is recalculated from its saved numerator and denominator.",
            "Every paint pass is dated by its authoritative oven-out timestamp. Item history links parts to carts; it does not supply the preserved first-pass outcome.",
            "Master Data Table supplies the preserved first EOL disposition. RepaintCount and load_line_repaint identify completed repaint passes; the current EDI EOL disposition supplies the latest completed repaint outcome.",
            "Repaint PPY counts non-repaint outcomes across every completed pass. Repaint FTY counts non-repaint outcomes only on initial passes. Repaint % is initial-pass repaint outcomes divided by initial passes.",
            "Reject PPY counts Approved outcomes across every completed pass. Reject FTY counts Approved outcomes only on initial passes. Repair, Repaint, Direct Repaint, and Reject are rejected outcomes; unresolved outcomes remain pending.",
            "The inspection-time hourly report is a reconciliation source, not the wallboard date grain; daily values can differ and should reconcile over longer periods.",
            "Receiving and final quantities use insp_receive_stamp and insp_final_stamp; their FTY rates continue to use first inspection decisions.",
            "The legacy Paint plan composite is unchanged and excluded from this yield correction and its acceptance criteria.",
            painter_note,
        ],
        "source_evidence": {
            "procedure": "dbo.usp_QPTS_GetOperationsQualityShippingRollup",
            "procedure_definition_sha256": os.environ.get(
                "KPI_SQL_PROCEDURE_HASH",
                "80689CEC1019830F14445EB5AE5B4CBE35A9CFFB7494688BB12D8481413B0C7A",
            ).upper(),
            "detail_result_sets_requested": False,
        },
    }
    validate_snapshot(snapshot)
    return snapshot


def refresh_live_snapshot(report_date: date) -> Dict[str, Any]:
    return snapshot_from_rollup(report_date, execute_operations_rollup(report_date))
