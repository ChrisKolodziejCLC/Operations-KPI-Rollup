"""Assembly counts by operator and by workstation for the restricted drill-down snapshot.

Counts only: pieces assembled and N71-6171 bumpers assembled, for the selected day and for the 13 Sunday-to-Saturday
weeks ending with it, once per operator (QPTS AssembledLogin) and once per workstation (GPAssyLogin, the work center).
Operator logins identify people, so the open wallboard port never receives the operator rows: the web layer replaces
them with an empty list (see redact_assembly_operators) and only the Windows sign-in listener serves them. There is no
build start time in QPTS yet, so no assembly time is calculated here.
"""

from __future__ import annotations

import copy
from datetime import date, timedelta
from typing import Any, Dict, Iterable, List, Mapping, Optional

METHOD_VERSION = "operations-kpi-assembly-details-v1"
OPERATORS_HIDDEN_NOTE = "Operator rows appear after Windows sign-in."

_SECTION_FIELDS = {
    "available", "method_version", "report_date", "chart_start", "fact_rows", "weeks", "totals",
    "operators_visible", "operators", "work_centers", "operators_note", "reason",
}
_ENTITY_FIELDS = {"key", "day", "weeks", "total"}
_COUNT_FIELDS = {"pieces", "bumpers"}
_WEEK_FIELDS = {"pieces", "bumpers", "days"}
_TOTAL_FIELDS = {"pieces", "bumpers", "days", "daily_average"}
MAX_ENTITIES = 400
MAX_KEY_LENGTH = 100


def unavailable_section(reason: str) -> Dict[str, Any]:
    return {"available": False, "method_version": METHOD_VERSION, "reason": reason}


def _text_date(value: Any) -> str:
    if isinstance(value, date):
        return value.isoformat()
    return str(value)[:10]


def _integer(value: Any) -> int:
    return int(float(value)) if value is not None and value != "" else 0


def _sunday_start(value: date) -> date:
    return value - timedelta(days=(value.weekday() + 1) % 7)


def _key(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text[:MAX_KEY_LENGTH]


def _entities(rows: Iterable[Mapping[str, Any]], key_field: str, report_date: date, weeks: List[date]) -> List[Dict[str, Any]]:
    chart_start = weeks[0]
    per_key: Dict[Optional[str], Dict[date, List[int]]] = {}
    for row in rows:
        day = date.fromisoformat(_text_date(row.get("bucket_start")))
        if day < chart_start or day > report_date:
            raise ValueError("The assembly-details procedure returned a day outside the 13 weeks.")
        pieces, bumpers = _integer(row.get("pieces")), _integer(row.get("bumpers"))
        if pieces < 0 or bumpers < 0 or bumpers > pieces:
            raise ValueError("An assembly-details count is negative or has more bumpers than pieces.")
        days = per_key.setdefault(_key(row.get(key_field)), {})
        counts = days.setdefault(day, [0, 0])
        counts[0] += pieces
        counts[1] += bumpers
    if len(per_key) > MAX_ENTITIES:
        raise ValueError("The assembly-details procedure returned too many " + key_field + " values.")
    entities: List[Dict[str, Any]] = []
    for key, days in per_key.items():
        week_rows = []
        for week_start in weeks:
            in_week = [counts for day, counts in days.items() if week_start <= day <= week_start + timedelta(days=6)]
            week_rows.append({
                "pieces": sum(counts[0] for counts in in_week),
                "bumpers": sum(counts[1] for counts in in_week),
                "days": sum(1 for counts in in_week if counts[0] > 0),
            })
        total_pieces = sum(row["pieces"] for row in week_rows)
        worked = sum(row["days"] for row in week_rows)
        today = days.get(report_date, [0, 0])
        entities.append({
            "key": key,
            "day": {"pieces": today[0], "bumpers": today[1]},
            "weeks": week_rows,
            "total": {
                "pieces": total_pieces,
                "bumpers": sum(row["bumpers"] for row in week_rows),
                "days": worked,
                "daily_average": round(total_pieces / worked, 1) if worked else None,
            },
        })
    entities.sort(key=lambda item: (item["key"] is None, -item["day"]["pieces"], -item["total"]["pieces"], item["key"] or ""))
    return entities


def _totals(entities: List[Dict[str, Any]], weeks: List[date]) -> Dict[str, Any]:
    return {
        "day": {"pieces": sum(item["day"]["pieces"] for item in entities), "bumpers": sum(item["day"]["bumpers"] for item in entities)},
        "weeks": [
            {"pieces": sum(item["weeks"][index]["pieces"] for item in entities), "bumpers": sum(item["weeks"][index]["bumpers"] for item in entities)}
            for index in range(len(weeks))
        ],
    }


def assembly_details_section(result_sets: Iterable[Mapping[str, Any]], report_date: date) -> Dict[str, Any]:
    by_index: Dict[int, List[Mapping[str, Any]]] = {}
    for item in result_sets:
        by_index[int(item["index"])] = list(item.get("rows", []))
    meta_rows = by_index.get(0) or []
    if not meta_rows:
        raise ValueError("The assembly-details procedure returned no metadata.")
    meta = meta_rows[0]
    if str(meta.get("method_version")) != METHOD_VERSION:
        raise ValueError("The assembly-details procedure returned an unexpected method version.")
    if _text_date(meta.get("report_date")) != report_date.isoformat():
        raise ValueError("The assembly-details procedure did not return the requested report date.")
    report_week = _sunday_start(report_date)
    weeks = [report_week - timedelta(weeks=offset) for offset in range(12, -1, -1)]
    if _text_date(meta.get("chart_start")) != weeks[0].isoformat():
        raise ValueError("The assembly-details procedure returned an unexpected chart start.")
    operators = _entities(by_index.get(1, []), "operator", report_date, weeks)
    work_centers = _entities(by_index.get(2, []), "workstation", report_date, weeks)
    totals = _totals(work_centers, weeks)
    if _totals(operators, weeks) != totals:
        raise ValueError("The assembly-details operator counts do not add up to the workstation counts.")
    section = {
        "available": True,
        "method_version": METHOD_VERSION,
        "report_date": report_date.isoformat(),
        "chart_start": weeks[0].isoformat(),
        "fact_rows": _integer(meta.get("fact_rows")),
        "weeks": [week.isoformat() for week in weeks],
        "totals": totals,
        "operators_visible": True,
        "operators": operators,
        "work_centers": work_centers,
    }
    validate_assembly_details_section(section)
    return section


def _check_counts(value: Mapping[str, Any], fields: set, label: str) -> None:
    if set(value) != fields:
        raise ValueError("assembly " + label + " has unexpected fields")
    for name in fields - {"daily_average"}:
        if not isinstance(value[name], int) or isinstance(value[name], bool) or value[name] < 0:
            raise ValueError("assembly " + label + " counts must be non-negative integers")
    if value["bumpers"] > value["pieces"]:
        raise ValueError("assembly " + label + " has more bumpers than pieces")


def _validate_entities(entities: Any, label: str, weeks: List[str]) -> None:
    if not isinstance(entities, list) or len(entities) > MAX_ENTITIES:
        raise ValueError("assembly " + label + " must be a bounded list")
    seen = set()
    for entity in entities:
        if not isinstance(entity, Mapping) or set(entity) != _ENTITY_FIELDS:
            raise ValueError("assembly " + label + " rows have unexpected fields")
        key = entity["key"]
        if key is not None and (not isinstance(key, str) or not key or len(key) > MAX_KEY_LENGTH):
            raise ValueError("assembly " + label + " keys must be text or null")
        if key in seen:
            raise ValueError("assembly " + label + " lists a value twice")
        seen.add(key)
        _check_counts(entity["day"], _COUNT_FIELDS, label + " day")
        if len(entity["weeks"]) != len(weeks):
            raise ValueError("assembly " + label + " rows need 13 weeks")
        for week in entity["weeks"]:
            _check_counts(week, _WEEK_FIELDS, label + " week")
            if week["days"] > 7:
                raise ValueError("assembly " + label + " days worked cannot exceed 7 in a week")
        total = entity["total"]
        if set(total) != _TOTAL_FIELDS:
            raise ValueError("assembly " + label + " total has unexpected fields")
        for name in ("pieces", "bumpers", "days"):
            if not isinstance(total[name], int) or isinstance(total[name], bool) or total[name] < 0:
                raise ValueError("assembly " + label + " totals must be non-negative integers")
        if total["pieces"] != sum(week["pieces"] for week in entity["weeks"]) or total["bumpers"] != sum(week["bumpers"] for week in entity["weeks"]):
            raise ValueError("assembly " + label + " totals do not add up to the weeks")
        if total["days"] != sum(week["days"] for week in entity["weeks"]):
            raise ValueError("assembly " + label + " days do not add up to the weeks")
        expected = round(total["pieces"] / total["days"], 1) if total["days"] else None
        if total["daily_average"] != expected:
            raise ValueError("assembly " + label + " daily_average must be pieces over days worked")
        if entity["day"]["pieces"] > entity["weeks"][-1]["pieces"]:
            raise ValueError("assembly " + label + " day is larger than its week")


def validate_assembly_details_section(section: Mapping[str, Any]) -> None:
    unknown = set(section) - _SECTION_FIELDS
    if unknown:
        raise ValueError("assembly has unexpected fields: " + ", ".join(sorted(unknown)))
    if section.get("method_version") != METHOD_VERSION:
        raise ValueError("assembly has an unsupported method version")
    if section.get("available") is False:
        if not isinstance(section.get("reason"), str):
            raise ValueError("assembly unavailable section needs a reason")
        return
    report_date = date.fromisoformat(str(section["report_date"]))
    report_week = _sunday_start(report_date)
    weeks = [(report_week - timedelta(weeks=offset)).isoformat() for offset in range(12, -1, -1)]
    if section.get("weeks") != weeks or section.get("chart_start") != weeks[0]:
        raise ValueError("assembly weeks must be 13 consecutive Sunday-start weeks ending with the report week")
    if not isinstance(section.get("fact_rows"), int) or section["fact_rows"] < 0:
        raise ValueError("assembly fact_rows must be a non-negative integer")
    totals = section["totals"]
    if set(totals) != {"day", "weeks"}:
        raise ValueError("assembly totals have unexpected fields")
    _check_counts(totals["day"], _COUNT_FIELDS, "totals day")
    if len(totals["weeks"]) != 13:
        raise ValueError("assembly totals need 13 weeks")
    for week in totals["weeks"]:
        _check_counts(week, _COUNT_FIELDS, "totals week")
    _validate_entities(section["work_centers"], "work_centers", weeks)
    if _totals_of(section["work_centers"], 13) != totals:
        raise ValueError("assembly work-center counts do not add up to the totals")
    if not isinstance(section.get("operators_visible"), bool):
        raise ValueError("assembly operators_visible must be true or false")
    if section["operators_visible"]:
        _validate_entities(section["operators"], "operators", weeks)
        if _totals_of(section["operators"], 13) != totals:
            raise ValueError("assembly operator counts do not add up to the totals")
        if section.get("operators_note") is not None:
            raise ValueError("assembly operators_note is only for the hidden view")
    elif section["operators"] != [] or section.get("operators_note") != OPERATORS_HIDDEN_NOTE:
        raise ValueError("assembly operator rows must be empty with the sign-in note when hidden")


def _totals_of(entities: List[Mapping[str, Any]], weeks: int) -> Dict[str, Any]:
    return {
        "day": {"pieces": sum(item["day"]["pieces"] for item in entities), "bumpers": sum(item["day"]["bumpers"] for item in entities)},
        "weeks": [
            {"pieces": sum(item["weeks"][index]["pieces"] for item in entities), "bumpers": sum(item["weeks"][index]["bumpers"] for item in entities)}
            for index in range(weeks)
        ],
    }


def redact_assembly_operators(snapshot: Mapping[str, Any]) -> Dict[str, Any]:
    """Copy of a restricted snapshot with the assembly operator rows removed (for the open wallboard port)."""
    view = copy.deepcopy(dict(snapshot))
    section = view.get("assembly")
    if isinstance(section, dict) and section.get("available") is not False:
        section["operators"] = []
        section["operators_visible"] = False
        section["operators_note"] = OPERATORS_HIDDEN_NOTE
    return view
