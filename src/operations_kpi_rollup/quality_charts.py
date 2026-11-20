"""Quality-chart section for the public, aggregate-only wallboard snapshot.

The section carries, for six yield rates behind the PPY, FTY, Receiving FTY, and Final FTY tiles, hourly (selected
day) and Sunday-to-Saturday 13-week numerators, denominators, and pending counts plus the defect counts behind every
rejection by inspection step. It contains counts only: no part, cart, person, or ID values. Every value follows the same definition as
the tile for that date because the procedure that produces it copies the rollup's pass model unchanged.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, List, Mapping, Optional

METHOD_VERSION = "operations-kpi-quality-charts-v1"

METRICS = (
    {"key": "ppy_repaint", "tile": "ppy", "label": "PPY · repaint basis"},
    {"key": "ppy_reject", "tile": "ppy", "label": "PPY · reject basis"},
    {"key": "fty_repaint", "tile": "fty", "label": "FTY · repaint basis"},
    {"key": "fty_reject", "tile": "fty", "label": "FTY · reject basis"},
    {"key": "receiving", "tile": "receiving", "label": "Receiving FTY"},
    {"key": "final", "tile": "final", "label": "Final FTY"},
)
METRIC_KEYS = tuple(metric["key"] for metric in METRICS)
STEPS = ("Receiving", "End of Line", "Final")

_SERIES_FIELDS = {"hourly", "weekly_13"}
_ROW_FIELDS = {"bucket", "is_partial", "data_available", "represented_day", "quality_numerator", "quality_denominator", "pending_count", "rate_percent"}
_WEEK_FIELDS = {"bucket", "bucket_end", "is_partial", "data_available", "represented_days", "quality_numerator", "quality_denominator", "pending_count", "rate_percent"}
_DEFECT_FIELDS = {"date", "step", "description", "count"}
_SECTION_FIELDS = {
    "available", "method_version", "report_date", "chart_start", "history_start", "fact_rows",
    "paint_passes_in_window", "series", "defects", "reason",
}


def _text_date(value: Any) -> str:
    if isinstance(value, date):
        return value.isoformat()
    return str(value)[:10]


def _integer(value: Any) -> int:
    return int(float(value)) if value is not None and value != "" else 0


def _rate(numerator: int, denominator: int) -> Optional[float]:
    return round(numerator * 100.0 / denominator, 4) if denominator else None


def _sunday_start(value: date) -> date:
    return value - timedelta(days=(value.weekday() + 1) % 7)


def unavailable_section(reason: str) -> Dict[str, Any]:
    return {"available": False, "method_version": METHOD_VERSION, "reason": reason}


def normalize_stored_quality_charts(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """Keep saved snapshots written under another quality-chart method loadable (see process_times)."""
    section = snapshot.get("quality_charts")
    if isinstance(section, dict) and section.get("method_version") != METHOD_VERSION:
        snapshot["quality_charts"] = unavailable_section(
            "This saved day was produced with an earlier quality-chart method; refresh it to recompute."
        )
    return snapshot


def _hour_text(value: Any) -> str:
    text = str(value).strip().replace(" ", "T")
    parsed = datetime.fromisoformat(text)
    return parsed.replace(minute=0, second=0, microsecond=0, tzinfo=None).isoformat(timespec="seconds")


def quality_charts_section(
    result_sets: Iterable[Mapping[str, Any]],
    report_date: date,
    generated_at: Optional[datetime] = None,
) -> Dict[str, Any]:
    by_index: Dict[int, List[Mapping[str, Any]]] = {}
    for item in result_sets:
        by_index[int(item["index"])] = list(item.get("rows", []))
    meta_rows = by_index.get(0) or []
    if not meta_rows:
        raise ValueError("The quality-chart procedure returned no metadata.")
    meta = meta_rows[0]
    if str(meta.get("method_version")) != METHOD_VERSION:
        raise ValueError("The quality-chart procedure returned an unexpected method version.")
    if _text_date(meta.get("report_date")) != report_date.isoformat():
        raise ValueError("The quality-chart procedure did not return the requested report date.")

    now = (generated_at or datetime.now()).replace(tzinfo=None)
    today_in_progress = report_date == now.date()
    daily_by_metric: Dict[str, List[Dict[str, Any]]] = {key: [] for key in METRIC_KEYS}
    for row in by_index.get(1, []):
        key = str(row.get("metric_key"))
        if key not in daily_by_metric:
            raise ValueError("The quality-chart procedure returned an unknown metric: " + key)
        numerator = _integer(row.get("quality_numerator"))
        denominator = _integer(row.get("quality_denominator"))
        if numerator < 0 or denominator < 0 or numerator > denominator:
            raise ValueError("A quality-chart daily numerator exceeds its denominator or is negative.")
        bucket = _text_date(row.get("bucket_start"))
        daily_by_metric[key].append({
            "bucket": bucket,
            "is_partial": bucket == report_date.isoformat() and today_in_progress,
            "data_available": bool(_integer(row.get("data_available"))),
            "represented_day": bool(_integer(row.get("represented_day"))),
            "quality_numerator": numerator,
            "quality_denominator": denominator,
            "pending_count": _integer(row.get("pending_count")),
            "rate_percent": _rate(numerator, denominator),
        })
    hourly_by_metric: Dict[str, List[Dict[str, Any]]] = {key: [] for key in METRIC_KEYS}
    for row in by_index.get(2, []):
        key = str(row.get("metric_key"))
        if key not in hourly_by_metric:
            raise ValueError("The quality-chart procedure returned an unknown hourly metric: " + key)
        numerator = _integer(row.get("quality_numerator"))
        denominator = _integer(row.get("quality_denominator"))
        if numerator < 0 or denominator < 0 or numerator > denominator:
            raise ValueError("A quality-chart hourly numerator exceeds its denominator or is negative.")
        bucket = _hour_text(row.get("bucket_start"))
        hour = int(bucket[11:13])
        hourly_by_metric[key].append({
            "bucket": bucket,
            "is_partial": bool(today_in_progress and hour == now.hour),
            "data_available": bool(_integer(row.get("data_available"))),
            "represented_day": bool(_integer(row.get("represented_day"))),
            "quality_numerator": numerator,
            "quality_denominator": denominator,
            "pending_count": _integer(row.get("pending_count")),
            "rate_percent": _rate(numerator, denominator),
        })
    series: Dict[str, Dict[str, Any]] = {}
    for key in METRIC_KEYS:
        daily = sorted(daily_by_metric[key], key=lambda row: row["bucket"])
        hourly = sorted(hourly_by_metric[key], key=lambda row: row["bucket"])
        series[key] = {"hourly": hourly, "weekly_13": _weekly_rows(report_date, daily)}
    defects = [
        {
            "date": _text_date(row.get("bucket_start")),
            "step": str(row.get("inspection_step") or "Unknown"),
            "description": str(row.get("defect_description") or "Unspecified"),
            "count": _integer(row.get("defect_count")),
        }
        for row in by_index.get(3, [])
    ]
    defects.sort(key=lambda row: (row["date"], row["step"], -row["count"], row["description"]))
    section = {
        "available": True,
        "method_version": METHOD_VERSION,
        "report_date": report_date.isoformat(),
        "chart_start": _text_date(meta.get("chart_start")),
        "history_start": _text_date(meta.get("history_start")),
        "fact_rows": _integer(meta.get("fact_rows")),
        "paint_passes_in_window": _integer(meta.get("paint_passes_in_window")),
        "series": series,
        "defects": defects,
    }
    validate_quality_charts_section(section)
    return section


def _weekly_rows(report_date: date, daily_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    report_week = _sunday_start(report_date)
    by_date = {date.fromisoformat(row["bucket"]): row for row in daily_rows}
    weeks: List[Dict[str, Any]] = []
    for offset in range(12, -1, -1):
        week_start = report_week - timedelta(weeks=offset)
        full_week_end = week_start + timedelta(days=6)
        observed_end = min(full_week_end, report_date)
        rows = [
            by_date[week_start + timedelta(days=step)]
            for step in range((observed_end - week_start).days + 1)
            if week_start + timedelta(days=step) in by_date
        ]
        represented = [row for row in rows if row["data_available"] and row["represented_day"]]
        numerator = sum(row["quality_numerator"] for row in represented)
        denominator = sum(row["quality_denominator"] for row in represented)
        weeks.append({
            "bucket": week_start.isoformat(),
            "bucket_end": observed_end.isoformat(),
            "is_partial": observed_end < full_week_end,
            "data_available": any(row["data_available"] for row in rows),
            "represented_days": len(represented),
            "quality_numerator": numerator,
            "quality_denominator": denominator,
            "pending_count": sum(row["pending_count"] for row in represented),
            "rate_percent": _rate(numerator, denominator),
        })
    return weeks


def validate_quality_charts_section(section: Mapping[str, Any]) -> None:
    unknown = set(section) - _SECTION_FIELDS
    if unknown:
        raise ValueError("quality_charts has unexpected fields: " + ", ".join(sorted(unknown)))
    if section.get("method_version") != METHOD_VERSION:
        raise ValueError("quality_charts has an unsupported method version")
    if section.get("available") is False:
        if not isinstance(section.get("reason"), str):
            raise ValueError("quality_charts unavailable section needs a reason")
        return
    date.fromisoformat(str(section["report_date"]))
    date.fromisoformat(str(section["chart_start"]))
    series = section["series"]
    if set(series) != set(METRIC_KEYS):
        raise ValueError("quality_charts must carry every metric series")
    for key in METRIC_KEYS:
        entry = series[key]
        if set(entry) != _SERIES_FIELDS:
            raise ValueError("quality_charts series have unexpected fields")
        if len(entry["hourly"]) != 24 or len(entry["weekly_13"]) != 13:
            raise ValueError("quality_charts series have the wrong number of buckets")
        for group, fields in (("hourly", _ROW_FIELDS), ("weekly_13", _WEEK_FIELDS)):
            for row in entry[group]:
                if set(row) != fields:
                    raise ValueError("quality_charts " + group + " rows have unexpected fields")
                if row["quality_numerator"] < 0 or row["quality_denominator"] < 0 or row["pending_count"] < 0:
                    raise ValueError("quality_charts counts must not be negative")
                if row["quality_numerator"] > row["quality_denominator"]:
                    raise ValueError("quality_charts numerator exceeds its denominator")
                rate = row["rate_percent"]
                if rate is not None and not 0 <= rate <= 100:
                    raise ValueError("quality_charts rate must be null or between 0 and 100")
    for row in section["defects"]:
        if set(row) != _DEFECT_FIELDS:
            raise ValueError("quality_charts defect rows have unexpected fields")
        if row["step"] not in STEPS and row["step"] != "Unknown":
            raise ValueError("quality_charts defect row has an unknown inspection step")
        date.fromisoformat(row["date"])
        if row["count"] < 0:
            raise ValueError("quality_charts defect counts must not be negative")
