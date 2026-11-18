"""Restricted Operations KPI drill-down contract.

This module is intentionally separate from the aggregate wallboard contract.
Named people and part-level rows may exist only in snapshots validated here and
served by the identity-gated restricted service.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterable, List, Mapping, Optional
from zoneinfo import ZoneInfo

from .odbc import execute_restricted_rollup


RESTRICTED_CONTRACT_VERSION = "1.0"
CURRENT_RESTRICTED_METHOD_VERSION = "operations-kpi-restricted-v1"
RESTRICTED_CLASSIFICATION = "restricted-operational"
RESTRICTED_HISTORY_START = date(2026, 9, 8)
MAX_RESTRICTED_ROWS = 5000
RESTRICTED_RESULT_INDEXES = frozenset({16, 17, 18, 19, 20})


class RestrictedContractError(ValueError):
    """Raised when a restricted result or snapshot violates the reviewed contract."""


def _text(value: Any, *, maximum: int = 256, fallback: str = "Unknown") -> str:
    normalized = " ".join(str(value or "").split())
    return (normalized or fallback)[:maximum]


def _optional_text(value: Any, *, maximum: int = 256) -> Optional[str]:
    normalized = " ".join(str(value or "").split())
    return normalized[:maximum] if normalized else None


def _integer(value: Any, default: int = 0) -> int:
    if value in (None, ""):
        return default
    try:
        return int(Decimal(str(value)))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise RestrictedContractError(f"Expected an integer, received {value!r}.") from exc


def _number(value: Any, digits: int = 2) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        return round(float(Decimal(str(value))), digits)
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise RestrictedContractError(f"Expected a number, received {value!r}.") from exc


def _date_text(value: Any) -> str:
    if isinstance(value, datetime):
        parsed = value.date()
    elif isinstance(value, date):
        parsed = value
    else:
        parsed = date.fromisoformat(str(value)[:10])
    if parsed < RESTRICTED_HISTORY_START:
        raise RestrictedContractError(
            f"Restricted history begins on {RESTRICTED_HISTORY_START.isoformat()}."
        )
    return parsed.isoformat()


def _timestamp(value: Any) -> Optional[str]:
    if value in (None, ""):
        return None
    text_value = str(value).strip().replace(" ", "T", 1)
    try:
        parsed = datetime.fromisoformat(text_value)
    except ValueError as exc:
        raise RestrictedContractError(f"Invalid timestamp {value!r}.") from exc
    return parsed.isoformat(timespec="seconds")


def _bounded_rows(rows: Iterable[Mapping[str, Any]], label: str) -> List[Mapping[str, Any]]:
    materialized = list(rows)
    if len(materialized) > MAX_RESTRICTED_ROWS:
        raise RestrictedContractError(
            f"{label} exceeded the {MAX_RESTRICTED_ROWS:,}-row restricted safety cap."
        )
    return materialized


def _index_result_sets(result_sets: Iterable[Mapping[str, Any]]) -> Dict[int, List[Mapping[str, Any]]]:
    indexed: Dict[int, List[Mapping[str, Any]]] = {}
    for result in result_sets:
        index = _integer(result.get("index"), -1)
        if index not in RESTRICTED_RESULT_INDEXES:
            continue
        if index in indexed:
            raise RestrictedContractError(f"Restricted result set {index} was returned twice.")
        rows = result.get("rows", [])
        if not isinstance(rows, list):
            raise RestrictedContractError(f"Restricted result set {index} rows must be a list.")
        indexed[index] = _bounded_rows(rows, f"Restricted result set {index}")
    missing = sorted(RESTRICTED_RESULT_INDEXES - indexed.keys())
    if missing:
        raise RestrictedContractError(f"Missing restricted result sets: {missing}.")
    return indexed


def build_restricted_snapshot(
    report_date: date,
    result_sets: Iterable[Mapping[str, Any]],
    *,
    generated_at: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Build and validate the private browser contract from result sets 16-20."""

    if report_date < RESTRICTED_HISTORY_START:
        raise RestrictedContractError(
            f"Restricted history begins on {RESTRICTED_HISTORY_START.isoformat()}."
        )
    indexed = _index_result_sets(result_sets)

    painter_daily = []
    for row in indexed[16]:
        row_date = _date_text(row.get("report_date"))
        if row_date > report_date.isoformat():
            raise RestrictedContractError("Painter history cannot extend beyond the report date.")
        total = _integer(row.get("fty_total"))
        approved = _integer(row.get("fty_approved"))
        repair = _integer(row.get("fty_repair"))
        repaint = _integer(row.get("fty_repaint"))
        pending = _integer(row.get("fty_pending"))
        if any(value < 0 for value in (total, approved, repair, repaint, pending)):
            raise RestrictedContractError("Painter outcome counts cannot be negative.")
        if approved + repair + repaint + pending > total:
            raise RestrictedContractError("Painter outcome counts exceed the FTY denominator.")
        painter_daily.append(
            {
                "date": row_date,
                "painter": _text(row.get("painter_name"), maximum=200),
                "booth": _integer(row.get("booth_number")),
                "carts": _integer(row.get("carts_painted")),
                "pieces": _integer(row.get("parts_painted")),
                "minutes": _integer(row.get("minutes_logged")),
                "pieces_per_hour": _number(row.get("parts_per_hour")),
                "unique_colors": _integer(row.get("unique_colors")),
                "fty_total": total,
                "fty_approved": approved,
                "fty_repair": repair,
                "fty_repaint": repaint,
                "fty_pending": pending,
                "fty_percent": _number(row.get("fty_percent"), 4),
            }
        )

    repaint_contributions = []
    valid_dimensions = {"painter", "color", "booth"}
    for row in indexed[17]:
        dimension = _text(row.get("dimension"), maximum=20).lower()
        if dimension not in valid_dimensions:
            raise RestrictedContractError(f"Unsupported repaint contribution dimension {dimension!r}.")
        repaint_contributions.append(
            {
                "dimension": dimension,
                "label": _text(row.get("label"), maximum=200),
                "repaint_events": _integer(row.get("repaint_events")),
                "unique_parts": _integer(row.get("unique_parts")),
                "contribution_percent": _number(row.get("contribution_percent"), 4),
            }
        )

    repaint_details = []
    for row in indexed[18]:
        repaint_details.append(
            {
                "event_at": _timestamp(row.get("event_at")),
                "part_id": _integer(row.get("part_id")),
                "part_number": _optional_text(row.get("part_number"), maximum=255),
                "sequence": _optional_text(row.get("sequence"), maximum=255),
                "color": _text(row.get("color"), maximum=255),
                "painter": _text(row.get("painter_name"), maximum=200),
                "booth": _integer(row.get("booth_number")),
                "repaint_loop_count": _integer(row.get("repaint_loop_count")),
                "defect": _text(row.get("defect_description"), maximum=255, fallback="Unspecified"),
            }
        )

    finesse_summary = []
    valid_outcomes = {"approved", "repaired", "repaint", "pending"}
    for row in indexed[19]:
        outcome = _text(row.get("outcome"), maximum=20).lower()
        if outcome not in valid_outcomes:
            raise RestrictedContractError(f"Unsupported finesse outcome {outcome!r}.")
        finesse_summary.append(
            {
                "date": _date_text(row.get("report_date")),
                "worker": _text(row.get("worker_name"), maximum=200),
                "outcome": outcome,
                "parts": _integer(row.get("part_count")),
                "average_minutes_per_part": _number(row.get("average_minutes_per_part")),
                "max_repaint_count": _integer(row.get("max_repaint_count")),
            }
        )

    finesse_details = []
    for row in indexed[20]:
        outcome = _text(row.get("outcome"), maximum=20).lower()
        if outcome not in valid_outcomes:
            raise RestrictedContractError(f"Unsupported finesse detail outcome {outcome!r}.")
        finesse_details.append(
            {
                "event_at": _timestamp(row.get("event_at")),
                "part_id": _integer(row.get("part_id")),
                "part_number": _optional_text(row.get("part_number"), maximum=255),
                "sequence": _optional_text(row.get("sequence"), maximum=255),
                "color": _text(row.get("color"), maximum=255),
                "worker": _text(row.get("worker_name"), maximum=200),
                "outcome": outcome,
                "minutes_per_part": _number(row.get("minutes_per_part")),
                "repaint_count": _integer(row.get("repaint_count")),
            }
        )

    observed_at = generated_at or datetime.now(ZoneInfo("America/Indiana/Indianapolis"))
    snapshot: Dict[str, Any] = {
        "contract_version": RESTRICTED_CONTRACT_VERSION,
        "classification": RESTRICTED_CLASSIFICATION,
        "scope": {
            "method_version": CURRENT_RESTRICTED_METHOD_VERSION,
            "history_start": RESTRICTED_HISTORY_START.isoformat(),
            "contains_named_people": True,
            "contains_part_level_detail": True,
            "public_wallboard_compatible": False,
        },
        "report_date": report_date.isoformat(),
        "generated_at": observed_at.isoformat(timespec="seconds"),
        "painter_daily": painter_daily,
        "repaint": {
            "contributions": repaint_contributions,
            "details": sorted(
                repaint_details,
                key=lambda item: (-item["repaint_loop_count"], item["painter"], item["part_id"]),
            ),
        },
        "finesse": {
            "summary": sorted(
                finesse_summary,
                key=lambda item: (-item["max_repaint_count"], -item["parts"], item["worker"]),
            ),
            "details": sorted(
                finesse_details,
                key=lambda item: (-item["repaint_count"], item["worker"], item["part_id"]),
            ),
        },
    }
    validate_restricted_snapshot(snapshot)
    return snapshot


def validate_restricted_snapshot(snapshot: Mapping[str, Any]) -> None:
    if snapshot.get("contract_version") != RESTRICTED_CONTRACT_VERSION:
        raise RestrictedContractError("Unsupported restricted contract version.")
    if snapshot.get("classification") != RESTRICTED_CLASSIFICATION:
        raise RestrictedContractError("The restricted snapshot classification is missing.")
    report_date = date.fromisoformat(str(snapshot.get("report_date", "")))
    if report_date < RESTRICTED_HISTORY_START:
        raise RestrictedContractError("The restricted snapshot predates the governed history window.")
    datetime.fromisoformat(str(snapshot.get("generated_at", "")))
    scope = snapshot.get("scope")
    if not isinstance(scope, Mapping):
        raise RestrictedContractError("The restricted scope is missing.")
    if scope.get("method_version") != CURRENT_RESTRICTED_METHOD_VERSION:
        raise RestrictedContractError("The restricted method version does not match this service.")
    if scope.get("contains_named_people") is not True or scope.get("contains_part_level_detail") is not True:
        raise RestrictedContractError("The restricted content flags are incomplete.")
    if scope.get("public_wallboard_compatible") is not False:
        raise RestrictedContractError("Restricted data must be marked incompatible with the public wallboard.")

    lists = [snapshot.get("painter_daily")]
    repaint = snapshot.get("repaint")
    finesse = snapshot.get("finesse")
    if not isinstance(repaint, Mapping) or not isinstance(finesse, Mapping):
        raise RestrictedContractError("Restricted repaint/finesse sections are missing.")
    lists.extend([repaint.get("contributions"), repaint.get("details"), finesse.get("summary"), finesse.get("details")])
    for value in lists:
        if not isinstance(value, list):
            raise RestrictedContractError("Restricted detail collections must be lists.")
        if len(value) > MAX_RESTRICTED_ROWS:
            raise RestrictedContractError("A restricted detail collection exceeded the safety cap.")


def refresh_restricted_snapshot(report_date: date) -> Dict[str, Any]:
    return build_restricted_snapshot(report_date, execute_restricted_rollup(report_date))
