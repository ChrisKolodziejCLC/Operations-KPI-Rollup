"""Process-time rollup section for the public, aggregate-only wallboard snapshot.

The section carries daily averages, medians, and 90th percentiles of the minutes between the
cart-load, booth, oven-in, oven-out, end-of-line-approval, and final-approval scans for first-pass
loops and for repaint loops. It contains counts and minutes only: no part, cart, person, or ID values.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

METHOD_VERSION = "operations-kpi-process-time-v3-production-days-exact"
POPULATIONS = ("standard", "repaint")

STAGES = (
    {"key": "load_to_booth", "order": 1, "label": "Cart loaded to booth scan", "short": "Loaded to booth"},
    {"key": "booth_to_oven_in", "order": 2, "label": "Booth scan to oven-in scan", "short": "Booth to oven in"},
    {"key": "oven_in_to_oven_out", "order": 3, "label": "Oven-in scan to oven-out scan", "short": "In oven"},
    {"key": "oven_out_to_eol_approved", "order": 4, "label": "Oven-out scan to EOL approval", "short": "Oven out to EOL"},
    {"key": "eol_approved_to_final_approved", "order": 5, "label": "EOL approval to final inspection", "short": "EOL to final"},
    {"key": "total_load_to_final_approved", "order": 6, "label": "Total, cart loaded to final inspection", "short": "Total"},
)
STAGE_KEYS = tuple(stage["key"] for stage in STAGES)
STANDARDS_PATH = Path(__file__).with_name("process_standards.json")

_DAILY_FIELDS = {
    "date", "population", "stage", "intervals", "average_minutes", "median_minutes", "p90_minutes",
    "over_12_hours", "excluded_negative",
}
_COVERAGE_FIELDS = {"date", "population", "loops_loaded", "loops_finished", "loops_with_every_scan"}
_SECTION_FIELDS = {
    "available", "method_version", "report_date", "window_start", "history_start", "events_scanned",
    "loops_scanned", "production_day_minimum_oven_exits", "production_days_in_window", "skipped_days_in_window",
    "step_intervals_off_production_days", "stages", "daily", "coverage", "standards", "reason",
}


def _text_date(value: Any) -> str:
    if isinstance(value, date):
        return value.isoformat()
    return str(value)[:10]


def _integer(value: Any) -> int:
    return int(value) if value is not None else 0


def _minutes(value: Any) -> Optional[float]:
    if value is None:
        return None
    return round(float(value), 1)


def load_standards(path: Path = STANDARDS_PATH) -> Dict[str, Dict[str, Optional[float]]]:
    """Return per-population standard minutes per stage; missing or null values mean no standard yet."""
    standards: Dict[str, Dict[str, Optional[float]]] = {
        population: {key: None for key in STAGE_KEYS} for population in POPULATIONS
    }
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return standards
    for population in POPULATIONS:
        section = raw.get(population) if isinstance(raw, dict) else None
        if not isinstance(section, dict):
            continue
        for key in STAGE_KEYS:
            value = section.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
                standards[population][key] = round(float(value), 1)
    return standards


def unavailable_section(reason: str) -> Dict[str, Any]:
    return {"available": False, "method_version": METHOD_VERSION, "reason": reason}


def normalize_stored_process_time(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """Keep saved snapshots written under an earlier process-time method loadable.

    A section whose method differs from the current one is replaced by an unavailable notice instead of
    failing validation, so a release that changes the method can still start on top of the snapshots that
    are already on disk. The next refresh of that day recomputes the section.
    """
    section = snapshot.get("process_time")
    if isinstance(section, dict) and section.get("method_version") != METHOD_VERSION:
        snapshot["process_time"] = unavailable_section(
            "This saved day was produced with an earlier process-time method; refresh it to recompute."
        )
    return snapshot


def process_time_section(
    result_sets: Iterable[Mapping[str, Any]],
    report_date: date,
    standards: Optional[Dict[str, Dict[str, Optional[float]]]] = None,
) -> Dict[str, Any]:
    by_index: Dict[int, List[Mapping[str, Any]]] = {}
    for item in result_sets:
        by_index[int(item["index"])] = list(item.get("rows", []))
    meta_rows = by_index.get(0) or []
    if not meta_rows:
        raise ValueError("The process-time procedure returned no metadata.")
    meta = meta_rows[0]
    if str(meta.get("method_version")) != METHOD_VERSION:
        raise ValueError("The process-time procedure returned an unexpected method version.")
    if _text_date(meta.get("report_date")) != report_date.isoformat():
        raise ValueError("The process-time procedure did not return the requested report date.")
    daily = [
        {
            "date": _text_date(row.get("event_date")),
            "population": str(row.get("population")),
            "stage": str(row.get("stage")),
            "intervals": _integer(row.get("intervals")),
            "average_minutes": _minutes(row.get("average_minutes")),
            "median_minutes": _minutes(row.get("median_minutes")),
            "p90_minutes": _minutes(row.get("p90_minutes")),
            "over_12_hours": _integer(row.get("over_12_hours")),
            "excluded_negative": _integer(row.get("excluded_negative")),
        }
        for row in by_index.get(1, [])
    ]
    daily.sort(key=lambda row: (row["population"], STAGE_KEYS.index(row["stage"]) if row["stage"] in STAGE_KEYS else 99, row["date"]))
    coverage = [
        {
            "date": _text_date(row.get("event_date")),
            "population": str(row.get("population")),
            "loops_loaded": _integer(row.get("loops_loaded")),
            "loops_finished": _integer(row.get("loops_finished")),
            "loops_with_every_scan": _integer(row.get("loops_with_every_scan")),
        }
        for row in by_index.get(2, [])
    ]
    coverage.sort(key=lambda row: (row["population"], row["date"]))
    section = {
        "available": True,
        "method_version": METHOD_VERSION,
        "report_date": report_date.isoformat(),
        "window_start": _text_date(meta.get("window_start")),
        "history_start": _text_date(meta.get("history_start")),
        "events_scanned": _integer(meta.get("events_scanned")),
        "loops_scanned": _integer(meta.get("loops_scanned")),
        "production_day_minimum_oven_exits": _integer(meta.get("production_day_minimum_oven_exits")),
        "production_days_in_window": _integer(meta.get("production_days_in_window")),
        "skipped_days_in_window": _integer(meta.get("skipped_days_in_window")),
        "step_intervals_off_production_days": _integer(meta.get("step_intervals_off_production_days")),
        "stages": [dict(stage) for stage in STAGES],
        "daily": daily,
        "coverage": coverage,
        "standards": standards if standards is not None else load_standards(),
    }
    validate_process_time_section(section)
    return section


def validate_process_time_section(section: Mapping[str, Any]) -> None:
    unknown = set(section) - _SECTION_FIELDS
    if unknown:
        raise ValueError("process_time has unexpected fields: " + ", ".join(sorted(unknown)))
    if section.get("method_version") != METHOD_VERSION:
        raise ValueError("process_time has an unsupported method version")
    if section.get("available") is False:
        if not isinstance(section.get("reason"), str):
            raise ValueError("process_time unavailable section needs a reason")
        return
    date.fromisoformat(str(section["report_date"]))
    date.fromisoformat(str(section["window_start"]))
    for field in ("production_day_minimum_oven_exits", "production_days_in_window", "skipped_days_in_window", "step_intervals_off_production_days"):
        if not isinstance(section.get(field), int) or section[field] < 0:
            raise ValueError("process_time " + field + " must be a non-negative integer")
    for row in section["daily"]:
        if set(row) != _DAILY_FIELDS:
            raise ValueError("process_time daily rows have unexpected fields")
        if row["population"] not in POPULATIONS or row["stage"] not in STAGE_KEYS:
            raise ValueError("process_time daily row has an unknown population or stage")
        date.fromisoformat(row["date"])
        if row["intervals"] < 0 or row["excluded_negative"] < 0 or row["over_12_hours"] < 0:
            raise ValueError("process_time daily counts must not be negative")
        if row["over_12_hours"] > row["intervals"] + row["excluded_negative"]:
            raise ValueError("process_time over-12-hour count exceeds its intervals")
        for field in ("average_minutes", "median_minutes", "p90_minutes"):
            value = row[field]
            if value is not None and (not isinstance(value, (int, float)) or value < 0):
                raise ValueError("process_time minutes must be null or non-negative")
    for row in section["coverage"]:
        if set(row) != _COVERAGE_FIELDS:
            raise ValueError("process_time coverage rows have unexpected fields")
        if row["population"] not in POPULATIONS:
            raise ValueError("process_time coverage row has an unknown population")
        if row["loops_with_every_scan"] > row["loops_finished"]:
            raise ValueError("process_time complete loops exceed finished loops")
    standards = section["standards"]
    for population in POPULATIONS:
        for key in STAGE_KEYS:
            value = standards[population][key]
            if value is not None and value <= 0:
                raise ValueError("process_time standards must be null or positive")
