"""Assembly-chart section for the public, aggregate-only wallboard snapshot.

For pieces assembled, N71-6171 bumpers assembled, and complete four-piece assembly sets, the section carries hourly
(selected day) and Sunday-to-Saturday 13-week counts. It contains counts only: no part, cart, person, login, or ID
values. Bumper and set counts follow the same definition as the Assembled bumpers and Complete assy sets tiles
because the procedure that produces them copies the rollup's rules unchanged; pieces are every non-service piece
scanned assembled. Every figure is dated by the assembly scan (plant clock time); a set counts when its last piece is scanned.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, List, Mapping, Optional

METHOD_VERSION = "operations-kpi-assembly-charts-v1"

METRICS = (
    {"key": "sets", "tile": "complete_assy_sets", "label": "Complete assy sets"},
    {"key": "pieces", "tile": "complete_assy_sets", "label": "Pieces assembled"},
    {"key": "bumpers", "tile": "assembled_bumpers", "label": "Assembled bumpers"},
)
METRIC_KEYS = tuple(metric["key"] for metric in METRICS)
# Procedure column behind each metric key.
_COLUMNS = {"sets": "complete_sets", "pieces": "pieces", "bumpers": "bumpers"}

_SERIES_FIELDS = {"hourly", "weekly_13"}
_ROW_FIELDS = {"bucket", "is_partial", "value"}
_WEEK_FIELDS = {"bucket", "bucket_end", "is_partial", "represented_days", "total", "daily_average"}
_SECTION_FIELDS = {
    "available", "method_version", "report_date", "chart_start", "fact_rows", "metrics", "series", "daily_totals", "reason",
}


def unavailable_section(reason: str) -> Dict[str, Any]:
    return {"available": False, "method_version": METHOD_VERSION, "reason": reason}


def normalize_stored_assembly_charts(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """Keep saved snapshots written under another assembly-chart method loadable (see quality_charts)."""
    section = snapshot.get("assembly_charts")
    if isinstance(section, dict) and section.get("method_version") != METHOD_VERSION:
        snapshot["assembly_charts"] = unavailable_section(
            "This saved day was produced with an earlier assembly-chart method; refresh it to recompute."
        )
    return snapshot


def _text_date(value: Any) -> str:
    if isinstance(value, date):
        return value.isoformat()
    return str(value)[:10]


def _hour_text(value: Any) -> str:
    text = str(value).strip().replace(" ", "T")
    parsed = datetime.fromisoformat(text)
    return parsed.replace(minute=0, second=0, microsecond=0, tzinfo=None).isoformat(timespec="seconds")


def _integer(value: Any) -> int:
    return int(float(value)) if value is not None and value != "" else 0


def _sunday_start(value: date) -> date:
    return value - timedelta(days=(value.weekday() + 1) % 7)


def assembly_charts_section(
    result_sets: Iterable[Mapping[str, Any]],
    report_date: date,
    generated_at: Optional[datetime] = None,
) -> Dict[str, Any]:
    by_index: Dict[int, List[Mapping[str, Any]]] = {}
    for item in result_sets:
        by_index[int(item["index"])] = list(item.get("rows", []))
    meta_rows = by_index.get(0) or []
    if not meta_rows:
        raise ValueError("The assembly-chart procedure returned no metadata.")
    meta = meta_rows[0]
    if str(meta.get("method_version")) != METHOD_VERSION:
        raise ValueError("The assembly-chart procedure returned an unexpected method version.")
    if _text_date(meta.get("report_date")) != report_date.isoformat():
        raise ValueError("The assembly-chart procedure did not return the requested report date.")

    now = (generated_at or datetime.now()).replace(tzinfo=None)
    today_in_progress = report_date == now.date()
    chart_start = _sunday_start(report_date) - timedelta(weeks=12)
    if _text_date(meta.get("chart_start")) != chart_start.isoformat():
        raise ValueError("The assembly-chart procedure returned an unexpected chart start.")

    daily: Dict[date, Dict[str, int]] = {}
    for row in by_index.get(1, []):
        day = date.fromisoformat(_text_date(row.get("bucket_start")))
        if day in daily:
            raise ValueError("The assembly-chart procedure returned a day twice.")
        counts = {key: _integer(row.get(_COLUMNS[key])) for key in METRIC_KEYS}
        if any(value < 0 for value in counts.values()):
            raise ValueError("An assembly-chart daily count is negative.")
        daily[day] = counts
    expected_days = [chart_start + timedelta(days=step) for step in range((report_date - chart_start).days + 1)]
    if sorted(daily) != expected_days:
        raise ValueError("The assembly-chart procedure did not return every day of the 13 weeks.")

    hourly: Dict[str, List[Dict[str, Any]]] = {key: [] for key in METRIC_KEYS}
    hour_rows = by_index.get(2, [])
    if len(hour_rows) != 24:
        raise ValueError("The assembly-chart procedure did not return 24 hourly buckets.")
    for row in hour_rows:
        bucket = _hour_text(row.get("bucket_start"))
        for key in METRIC_KEYS:
            value = _integer(row.get(_COLUMNS[key]))
            if value < 0:
                raise ValueError("An assembly-chart hourly count is negative.")
            hourly[key].append({
                "bucket": bucket,
                "is_partial": bool(today_in_progress and int(bucket[11:13]) == now.hour),
                "value": value,
            })
    series: Dict[str, Dict[str, Any]] = {}
    for key in METRIC_KEYS:
        series[key] = {
            "hourly": sorted(hourly[key], key=lambda row: row["bucket"]),
            "weekly_13": _weekly_rows(report_date, key, daily),
        }
    section = {
        "available": True,
        "method_version": METHOD_VERSION,
        "report_date": report_date.isoformat(),
        "chart_start": chart_start.isoformat(),
        "fact_rows": _integer(meta.get("fact_rows")),
        "metrics": [dict(metric) for metric in METRICS],
        "series": series,
        "daily_totals": {key: daily[report_date][key] for key in METRIC_KEYS},
    }
    validate_assembly_charts_section(section)
    return section


def _weekly_rows(report_date: date, key: str, daily: Mapping[date, Mapping[str, int]]) -> List[Dict[str, Any]]:
    report_week = _sunday_start(report_date)
    weeks: List[Dict[str, Any]] = []
    for offset in range(12, -1, -1):
        week_start = report_week - timedelta(weeks=offset)
        full_week_end = week_start + timedelta(days=6)
        observed_end = min(full_week_end, report_date)
        days = [week_start + timedelta(days=step) for step in range((observed_end - week_start).days + 1)]
        rows = [daily[day] for day in days if day in daily]
        represented = [row for row in rows if row["pieces"] > 0]
        total = sum(row[key] for row in rows)
        weeks.append({
            "bucket": week_start.isoformat(),
            "bucket_end": observed_end.isoformat(),
            "is_partial": observed_end < full_week_end,
            "represented_days": len(represented),
            "total": total,
            "daily_average": round(total / len(represented), 1) if represented else None,
        })
    return weeks


def validate_assembly_charts_section(section: Mapping[str, Any]) -> None:
    unknown = set(section) - _SECTION_FIELDS
    if unknown:
        raise ValueError("assembly_charts has unexpected fields: " + ", ".join(sorted(unknown)))
    if section.get("method_version") != METHOD_VERSION:
        raise ValueError("assembly_charts has an unsupported method version")
    if section.get("available") is False:
        if not isinstance(section.get("reason"), str):
            raise ValueError("assembly_charts unavailable section needs a reason")
        return
    report_date = date.fromisoformat(str(section["report_date"]))
    chart_start = date.fromisoformat(str(section["chart_start"]))
    report_week = _sunday_start(report_date)
    if chart_start != report_week - timedelta(weeks=12):
        raise ValueError("assembly_charts chart_start must be 12 weeks before the report week")
    if not isinstance(section.get("fact_rows"), int) or section["fact_rows"] < 0:
        raise ValueError("assembly_charts fact_rows must be a non-negative integer")
    if section.get("metrics") != [dict(metric) for metric in METRICS]:
        raise ValueError("assembly_charts metrics are not the reviewed metrics")
    series = section["series"]
    if set(series) != set(METRIC_KEYS):
        raise ValueError("assembly_charts must carry every metric series")
    totals = section["daily_totals"]
    if set(totals) != set(METRIC_KEYS):
        raise ValueError("assembly_charts daily_totals must cover every metric")
    for key in METRIC_KEYS:
        entry = series[key]
        if set(entry) != _SERIES_FIELDS:
            raise ValueError("assembly_charts series have unexpected fields")
        if len(entry["hourly"]) != 24 or len(entry["weekly_13"]) != 13:
            raise ValueError("assembly_charts series have the wrong number of buckets")
        hourly_sum = 0
        for hour, row in enumerate(entry["hourly"]):
            if set(row) != _ROW_FIELDS:
                raise ValueError("assembly_charts hourly rows have unexpected fields")
            if row["bucket"] != report_date.isoformat() + "T%02d:00:00" % hour:
                raise ValueError("assembly_charts hourly buckets must be the 24 clock hours of the report date")
            if not isinstance(row["value"], int) or isinstance(row["value"], bool) or row["value"] < 0:
                raise ValueError("assembly_charts counts must be non-negative integers")
            hourly_sum += row["value"]
        if not isinstance(totals[key], int) or isinstance(totals[key], bool) or totals[key] < 0:
            raise ValueError("assembly_charts daily totals must be non-negative integers")
        if hourly_sum != totals[key]:
            raise ValueError("assembly_charts hourly counts do not add up to the day")
        for index, row in enumerate(entry["weekly_13"]):
            if set(row) != _WEEK_FIELDS:
                raise ValueError("assembly_charts weekly rows have unexpected fields")
            week_start = report_week - timedelta(weeks=12 - index)
            if row["bucket"] != week_start.isoformat():
                raise ValueError("assembly_charts weeks must be 13 consecutive Sunday-start weeks ending with the report week")
            if not isinstance(row["total"], int) or isinstance(row["total"], bool) or row["total"] < 0:
                raise ValueError("assembly_charts counts must be non-negative integers")
            if not isinstance(row["represented_days"], int) or not 0 <= row["represented_days"] <= 7:
                raise ValueError("assembly_charts represented_days must be between 0 and 7")
            average = row["daily_average"]
            if row["represented_days"] == 0:
                if average is not None or row["total"] != 0:
                    raise ValueError("assembly_charts weeks without assembly days must be empty")
            elif average != round(row["total"] / row["represented_days"], 1):
                raise ValueError("assembly_charts daily_average must be total over represented days")
        if entry["weekly_13"][-1]["total"] < totals[key]:
            raise ValueError("assembly_charts report week is smaller than the report day")
