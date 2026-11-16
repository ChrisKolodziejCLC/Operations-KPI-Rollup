"""Translate the bounded legacy rollup contract into an immutable v1 snapshot."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import os
import re
from typing import Any, Dict, Iterable, List, Mapping, Optional
from zoneinfo import ZoneInfo

from .context import validate_snapshot
from .odbc import execute_operations_rollup


DATE_WRAPPER = re.compile(r"^/Date\((\d+)(?:[+-]\d+)?\)/$")
PERIOD_TYPE_ORDER = {"WEEK": 1, "MONTH": 2, "QUARTER": 3}
CURRENT_METHOD_VERSION = "operations-kpi-live-v22-loaded-goal-rates"
LOADED_CHART_FIELDS = (
    "parts_loaded",
    "production_parts_loaded",
    "bv_parts_loaded",
    "service_parts_loaded",
    "unique_pieces_loaded",
    "carts_loaded",
    "production_carts_loaded",
    "bv_carts_loaded",
    "service_carts_loaded",
)
LOADED_BASELINE_START = "2026-09-08"
LOADED_BASELINE_END = "2026-11-15"
LOADED_BASELINE_DAYS = 46
LOADED_BASELINE_CARTS = 4787
LOADED_BASELINE_PIECES = 14214
LOADED_BASELINE_NET_MINUTES = Decimal("34591.218")
LOADED_CART_GOAL_RATE = Decimal("12")
LOADED_PIECE_GOAL_RATE = Decimal("36")
LOADED_TARGET_GAP_FRACTION = Decimal("0.25")
LOADED_LUNCH_ALLOWANCE_MINUTES = 30
LOADED_LUNCH_ELIGIBILITY_SPAN_MINUTES = 360


def _integer(value: Any) -> int:
    if value is None or value == "":
        return 0
    return int(Decimal(str(value)))


def _number(value: Any, places: int = 4) -> float:
    if value is None or value == "":
        return 0.0
    return round(float(Decimal(str(value))), places)


def _loaded_performance_model() -> Dict[str, Any]:
    baseline_hours = LOADED_BASELINE_NET_MINUTES / Decimal("60")
    cart_baseline = Decimal(LOADED_BASELINE_CARTS) / baseline_hours
    piece_baseline = Decimal(LOADED_BASELINE_PIECES) / baseline_hours
    cart_target = cart_baseline + LOADED_TARGET_GAP_FRACTION * (LOADED_CART_GOAL_RATE - cart_baseline)
    piece_target = piece_baseline + LOADED_TARGET_GAP_FRACTION * (LOADED_PIECE_GOAL_RATE - piece_baseline)
    return {
        "effective_date": "2026-11-16",
        "baseline_start": LOADED_BASELINE_START,
        "baseline_end": LOADED_BASELINE_END,
        "baseline_completed_loading_days": LOADED_BASELINE_DAYS,
        "baseline_net_loading_minutes": float(LOADED_BASELINE_NET_MINUTES),
        "baseline_carts_loaded": LOADED_BASELINE_CARTS,
        "baseline_pieces_loaded": LOADED_BASELINE_PIECES,
        "baseline_carts_per_hour": round(float(cart_baseline), 4),
        "baseline_pieces_per_hour": round(float(piece_baseline), 4),
        "target_gap_fraction": float(LOADED_TARGET_GAP_FRACTION),
        "target_carts_per_hour": round(float(cart_target), 4),
        "target_pieces_per_hour": round(float(piece_target), 4),
        "goal_carts_per_hour": float(LOADED_CART_GOAL_RATE),
        "goal_pieces_per_hour": float(LOADED_PIECE_GOAL_RATE),
        "lunch_allowance_minutes": LOADED_LUNCH_ALLOWANCE_MINUTES,
        "lunch_eligibility_span_minutes": LOADED_LUNCH_ELIGIBILITY_SPAN_MINUTES,
        "partial_day_scoring": False,
    }


def _date_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    wrapper = DATE_WRAPPER.match(text)
    if wrapper:
        return datetime.fromtimestamp(int(wrapper.group(1)) / 1000, tz=timezone.utc).date().isoformat()
    return date.fromisoformat(text[:10]).isoformat()


def _timestamp_text(value: Any) -> Optional[str]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None).isoformat(timespec="seconds")
    text = str(value).strip().replace(" ", "T")
    return datetime.fromisoformat(text).replace(tzinfo=None).isoformat(timespec="seconds")


def _bucket_text(value: Any, grain: str) -> str:
    day = _date_text(value)
    if grain == "DAY":
        return day
    text = str(value or "").strip()
    match = re.search(r"[T ](\d{2})", text)
    if not match:
        raise ValueError("The loaded-chart hourly bucket has no hour component.")
    return f"{day}T{int(match.group(1)):02d}:00:00"


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
        "n71_6164_parts_loaded": "n71_6164_parts_loaded",
        "unique_pieces_loaded": "unique_pieces_loaded",
        "carts_loaded": "carts_loaded",
        "production_carts_loaded": "production_carts_loaded",
        "bv_carts_loaded": "bv_carts_loaded",
        "service_carts_loaded": "service_carts_loaded",
        "n71_6164_carts_loaded": "n71_6164_carts_loaded",
        "staged_carts": "staged_carts",
        "production_staged_carts": "production_staged_carts",
        "bv_staged_carts": "bv_staged_carts",
        "service_staged_carts": "service_staged_carts",
        "staged_pieces": "staged_pieces",
        "production_staged_pieces": "production_staged_pieces",
        "bv_staged_pieces": "bv_staged_pieces",
        "service_staged_pieces": "service_staged_pieces",
        "paint_processed": "paint_carts",
        "production_paint_carts": "production_paint_carts",
        "bv_paint_carts": "bv_paint_carts",
        "service_paint_carts": "service_paint_carts",
        "n71_6164_paint_carts": "n71_6164_paint_carts",
        "paint_pieces_processed": "paint_pieces_processed",
        "production_paint_pieces_processed": "production_paint_pieces_processed",
        "bv_paint_pieces_processed": "bv_paint_pieces_processed",
        "service_paint_pieces_processed": "service_paint_pieces_processed",
        "n71_6164_paint_pieces_processed": "n71_6164_paint_pieces_processed",
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
        "repaint_ppy_pending_count": "repaint_ppy_pending_count",
        "paint_fty_total": "paint_fty_total",
        "production_paint_fty_total": "production_paint_fty_total",
        "bv_paint_fty_total": "bv_paint_fty_total",
        "service_paint_fty_total": "service_paint_fty_total",
        "paint_fty_approved": "paint_fty_approved",
        "production_paint_fty_approved": "production_paint_fty_approved",
        "bv_paint_fty_approved": "bv_paint_fty_approved",
        "service_paint_fty_approved": "service_paint_fty_approved",
        "paint_fty_repaint_count": "paint_fty_repaint_count",
        "repaint_fty_pending_count": "repaint_fty_pending_count",
        "fuka_paint_fty_repaint_count": "fuka_paint_fty_repaint_count",
        "bumper_paint_fty_repaint_count": "bumper_paint_fty_repaint_count",
        "fairing_paint_fty_repaint_count": "fairing_paint_fty_repaint_count",
        "paint_fty_repair_count": "paint_fty_repair_count",
        "fuka_paint_fty_repair_count": "fuka_paint_fty_repair_count",
        "fairing_paint_fty_repair_count": "fairing_paint_fty_repair_count",
        "bumper_paint_fty_repair_count": "bumper_paint_fty_repair_count",
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
        "receiving_bumper_total": "receiving_bumper_total",
        "receiving_bumper_approved": "receiving_bumper_approved",
        "receiving_fairing_total": "receiving_fairing_total",
        "receiving_fairing_approved": "receiving_fairing_approved",
        "finesse_rejected_count": "finesse_rejected_count",
        "finesse_repair_count": "finesse_repair_count",
        "finesse_repaint_count": "finesse_repaint_count",
        "finesse_pending_count": "finesse_pending_count",
        "bumper_finesse_repair_count": "bumper_finesse_repair_count",
        "fairing_finesse_repair_count": "fairing_finesse_repair_count",
        "other_finesse_repair_count": "other_finesse_repair_count",
        "receiving_quantity": "receiving_quantity",
        "final_total": "final_total",
        "final_approved": "final_approved",
        "final_fuka_total": "final_fuka_total",
        "final_fuka_approved": "final_fuka_approved",
        "final_bumper_total": "final_bumper_total",
        "final_bumper_approved": "final_bumper_approved",
        "final_fairing_total": "final_fairing_total",
        "final_fairing_approved": "final_fairing_approved",
        "final_quantity": "final_quantity",
        "eol_inspected": "eol_inspected",
        "painted_parts_shipped": "painted_parts_shipped",
        "bumpers_shipped": "bumpers_shipped",
        "parts_shipped": "parts_shipped",
        "complete_assy_sets": "complete_assy_sets",
        "mic_complete_assy_sets": "mic_complete_assy_sets",
        "painted_complete_assy_sets": "painted_complete_assy_sets",
        "assembled_bumper_count": "assembled_bumper_count",
        "mic_assembled_bumper_count": "mic_assembled_bumper_count",
        "painted_assembled_bumper_count": "painted_assembled_bumper_count",
        "trailers_prepared": "trailers_prepared",
        "trailers_shipped": "trailers_shipped",
        "fuka_trailers_prepared": "fuka_trailers_prepared",
        "bumper_trailers_prepared": "bumper_trailers_prepared",
        "fairing_trailers_prepared": "fairing_trailers_prepared",
        "other_trailers_prepared": "other_trailers_prepared",
        "racks_shipped": "racks_shipped",
        "fuka_racks_shipped": "fuka_racks_shipped",
        "bumper_racks_shipped": "bumper_racks_shipped",
        "n71_6164_racks_shipped": "n71_6164_racks_shipped",
        "fairing_racks_shipped": "fairing_racks_shipped",
        "other_racks_shipped": "other_racks_shipped",
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


def _loaded_chart_row(row: Mapping[str, Any]) -> Dict[str, Any]:
    grain = str(row.get("grain") or "").upper()
    if grain not in {"HOUR", "DAY"}:
        raise ValueError("The loaded-chart result contains an unsupported grain.")
    return {
        "bucket": _bucket_text(row.get("bucket_start"), grain),
        "is_partial": bool(_integer(row.get("is_partial"))),
        "data_available": bool(_integer(row.get("data_available"))),
        "represented_day": bool(_integer(row.get("represented_day"))),
        "first_cart_loaded_at": _timestamp_text(row.get("first_cart_loaded_at")),
        "last_cart_loaded_at": _timestamp_text(row.get("last_cart_loaded_at")),
        "load_span_minutes": _number(row.get("load_span_minutes"), 3),
        "lunch_allowance_minutes": _number(row.get("lunch_allowance_minutes"), 3),
        "net_loading_minutes": _number(row.get("net_loading_minutes"), 3),
        "performance_scored": bool(_integer(row.get("performance_scored"))),
        **{field: _integer(row.get(field)) for field in LOADED_CHART_FIELDS},
    }


def _sunday_start(value: date) -> date:
    return value - timedelta(days=(value.weekday() + 1) % 7)


def _loaded_weekly_rows(
    report_date: date,
    daily_rows: List[Dict[str, Any]],
    performance_model: Mapping[str, Any],
) -> List[Dict[str, Any]]:
    """Collapse the bounded daily chart rows into 13 Sunday-start weeks.

    Only represented production days participate in an average. A represented
    day with no loaded carts or pieces contributes an honest zero; dates before
    the authoritative history boundary remain unavailable.
    """
    report_week = _sunday_start(report_date)
    by_date = {date.fromisoformat(row["bucket"]): row for row in daily_rows}
    weeks: List[Dict[str, Any]] = []
    for offset in range(12, -1, -1):
        week_start = report_week - timedelta(weeks=offset)
        full_week_end = week_start + timedelta(days=6)
        observed_end = min(full_week_end, report_date)
        rows = [
            by_date[week_start + timedelta(days=day_offset)]
            for day_offset in range((observed_end - week_start).days + 1)
            if week_start + timedelta(days=day_offset) in by_date
        ]
        represented = [
            row for row in rows
            if row["data_available"] and row["represented_day"]
        ]
        represented_days = len(represented)
        parts_total = sum(int(row["parts_loaded"]) for row in represented)
        carts_total = sum(int(row["carts_loaded"]) for row in represented)
        performance_rows = [
            row for row in represented
            if row["performance_scored"] and float(row["net_loading_minutes"]) > 0
        ]
        performance_days = len(performance_rows)
        net_loading_minutes = round(sum(float(row["net_loading_minutes"]) for row in performance_rows), 3)
        comparable = (
            observed_end == full_week_end
            and performance_days > 0
            and performance_days == represented_days
        )
        net_loading_hours = net_loading_minutes / 60.0
        carts_per_hour = (
            sum(int(row["carts_loaded"]) for row in performance_rows) / net_loading_hours
            if net_loading_hours > 0 else None
        )
        pieces_per_hour = (
            sum(int(row["parts_loaded"]) for row in performance_rows) / net_loading_hours
            if net_loading_hours > 0 else None
        )
        average_target_carts = (
            float(performance_model["target_carts_per_hour"]) * net_loading_hours / performance_days
            if comparable else None
        )
        average_goal_carts = (
            float(performance_model["goal_carts_per_hour"]) * net_loading_hours / performance_days
            if comparable else None
        )
        average_target_pieces = (
            float(performance_model["target_pieces_per_hour"]) * net_loading_hours / performance_days
            if comparable else None
        )
        average_goal_pieces = (
            float(performance_model["goal_pieces_per_hour"]) * net_loading_hours / performance_days
            if comparable else None
        )
        weeks.append({
            "bucket": week_start.isoformat(),
            "bucket_end": observed_end.isoformat(),
            "is_partial": observed_end < full_week_end,
            "data_available": any(row["data_available"] for row in rows),
            "represented_days": represented_days,
            "performance_days": performance_days,
            "performance_comparable": comparable,
            "net_loading_minutes": net_loading_minutes,
            "parts_loaded_total": parts_total,
            "carts_loaded_total": carts_total,
            "average_parts_loaded": round(parts_total / represented_days, 1) if represented_days else None,
            "average_carts_loaded": round(carts_total / represented_days, 1) if represented_days else None,
            "carts_per_net_hour": round(carts_per_hour, 1) if carts_per_hour is not None else None,
            "pieces_per_net_hour": round(pieces_per_hour, 1) if pieces_per_hour is not None else None,
            "average_target_carts": round(average_target_carts, 1) if average_target_carts is not None else None,
            "average_goal_carts": round(average_goal_carts, 1) if average_goal_carts is not None else None,
            "average_target_pieces": round(average_target_pieces, 1) if average_target_pieces is not None else None,
            "average_goal_pieces": round(average_goal_pieces, 1) if average_goal_pieces is not None else None,
        })
    return weeks


def _loaded_selected_day_performance(
    row: Mapping[str, Any],
    performance_model: Mapping[str, Any],
) -> Dict[str, Any]:
    net_minutes = float(row.get("net_loading_minutes") or 0)
    net_hours = net_minutes / 60.0
    scored = bool(row.get("performance_scored")) and net_hours > 0
    return {
        "first_cart_loaded_at": row.get("first_cart_loaded_at"),
        "last_cart_loaded_at": row.get("last_cart_loaded_at"),
        "load_span_minutes": round(float(row.get("load_span_minutes") or 0), 3),
        "lunch_allowance_minutes": round(float(row.get("lunch_allowance_minutes") or 0), 3),
        "net_loading_minutes": round(net_minutes, 3),
        "performance_scored": scored,
        "carts_per_net_hour": round(int(row.get("carts_loaded") or 0) / net_hours, 1) if net_hours > 0 else None,
        "pieces_per_net_hour": round(int(row.get("parts_loaded") or 0) / net_hours, 1) if net_hours > 0 else None,
        "target_carts": round(float(performance_model["target_carts_per_hour"]) * net_hours, 1) if scored else None,
        "goal_carts": round(float(performance_model["goal_carts_per_hour"]) * net_hours, 1) if scored else None,
        "target_pieces": round(float(performance_model["target_pieces_per_hour"]) * net_hours, 1) if scored else None,
        "goal_pieces": round(float(performance_model["goal_pieces_per_hour"]) * net_hours, 1) if scored else None,
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
    loaded_chart_rows = [
        (str(row.get("grain") or "").upper(), _loaded_chart_row(row))
        for row in indexed.get(14, [])
    ]
    loaded_hourly = sorted(
        (row for grain, row in loaded_chart_rows if grain == "HOUR"),
        key=lambda row: row["bucket"],
    )
    loaded_daily_window = sorted(
        (row for grain, row in loaded_chart_rows if grain == "DAY"),
        key=lambda row: row["bucket"],
    )
    chart_start = _sunday_start(report_date) - timedelta(weeks=12)
    expected_daily_buckets = [
        (chart_start + timedelta(days=offset)).isoformat()
        for offset in range((report_date - chart_start).days + 1)
    ]
    if [row["bucket"] for row in loaded_daily_window] != expected_daily_buckets:
        raise ValueError("The loaded-chart daily window is not the ordered 13-week source range.")
    loaded_performance_model = _loaded_performance_model()
    loaded_weekly_13 = _loaded_weekly_rows(report_date, loaded_daily_window, loaded_performance_model)

    report_chart_day = next(
        (row for row in loaded_daily_window if row["bucket"] == report_date.isoformat()),
        None,
    )
    report_daily = next(row for row in daily if row["date"] == report_date.isoformat())
    if report_chart_day is None:
        raise ValueError("The loaded-chart daily window does not contain the report date.")
    for field in LOADED_CHART_FIELDS:
        if int(report_chart_day[field]) != int(report_daily.get(field, 0)):
            raise ValueError(f"The loaded-chart report-day {field} does not reconcile to the daily result.")
    loaded_selected_day = _loaded_selected_day_performance(report_chart_day, loaded_performance_model)

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
        "chart_series": {
            "loaded": {
                "hourly": loaded_hourly,
                "weekly_13": loaded_weekly_13,
                "selected_day": loaded_selected_day,
                "performance_model": loaded_performance_model,
            }
        },
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
            "For non-BV parts, Master Data Table supplies the preserved first EOL disposition and RepaintCount/load_line_repaint retain the reviewed repaint lineage. For BV-origin parts, the first physical Grand Prairie oven exit is the GP initial pass and only a later GP pass or a GP-local repaint disposition makes that pass a GP repaint failure.",
            "Repaint PPY counts non-repaint outcomes across every GP-completed pass. Repaint FTY counts non-repaint outcomes only on GP initial passes. Repaint % is GP initial-pass repaint outcomes divided by GP initial passes; Brownsville paint history alone cannot create a GP repaint.",
            "Reject PPY and Reject FTY retain the existing Master/RepaintCount outcome lineage. Their pending and FTY-denominator fields remain independent from the new GP-local repaint fields; Repair, Repaint, Direct Repaint, and Reject are rejected outcomes and unresolved outcomes remain pending.",
            "Finesse Effectiveness combines GP-paint first-pass rejects with first Receiving rejects. The numerator combines first-pass paint Repair outcomes with completed Receiving/Finesse repairs; the denominator includes every reject in those two governed cohorts, including unresolved Receiving rejects. Product-family repair detail uses Description and preserves Brownsville parts even after a later Origin change.",
            "Product-family detail uses normalized EDI Description: Fender is FUKA, Bumper is Bumpers, and Chassis Fairing is Fairings. EDI Origin remains only where it defines paint-process scope rather than product family.",
            "Pieces Staged mirrors the Paint Prep Wallboard queue: eligible EDI-loaded Origin F cart groups without a tblCarts_Paint booth scan, using three-day normal and seven-day active-repaint windows.",
            "The inspection-time hourly report is a reconciliation source, not the wallboard date grain; daily values can differ and should reconcile over longer periods.",
            "Receiving and final quantities use insp_receive_stamp and insp_final_stamp; their FTY rates continue to use first inspection decisions and expose only reconciled aggregate product-family detail.",
            "Trailers Departed counts completed DriverLog departures dated by TimeOut; it is intentionally separate from EDI trailer-loading state.",
            "The Loaded chart is aggregate-only. Load events stay in their actual hour; a distinct piece or cart is assigned to its first load-event hour so all 24 buckets reconcile exactly to the daily card. The 13-week view averages total carts and pieces over represented production days; unavailable history and the partial selected week are excluded from trend calculations.",
            "Loaded performance time runs from the first distinct cart load to the last distinct cart load. Completed days spanning at least six hours receive the approved 30-minute lunch allowance; partial days are shown but not scored. The frozen September 8 through November 15 baseline retains its carts, pieces, and net-minute denominators, and each interim target closes 25% of the gap from that baseline rate to the approved hourly goal.",
            "Preliminary OEE is the unchanged legacy paint-plan composite and remains excluded from this yield correction and its acceptance criteria.",
            painter_note,
        ],
        "source_evidence": {
            "procedure": "dbo.usp_QPTS_GetOperationsQualityShippingRollup",
            "procedure_definition_sha256": os.environ.get(
                "KPI_SQL_PROCEDURE_HASH",
                "A7365336FFFE5170A3D963D3C4599F158C97E29B2E01FFEBD3C59A4ED817285F",
            ).upper(),
            "detail_result_sets_requested": False,
        },
    }
    validate_snapshot(snapshot)
    return snapshot


def refresh_live_snapshot(report_date: date) -> Dict[str, Any]:
    return snapshot_from_rollup(report_date, execute_operations_rollup(report_date))
