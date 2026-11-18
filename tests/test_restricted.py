from datetime import date, datetime
from pathlib import Path

import pytest

from operations_kpi_rollup import odbc
from operations_kpi_rollup.restricted import (
    MAX_RESTRICTED_ROWS,
    RestrictedContractError,
    build_restricted_snapshot,
    validate_restricted_snapshot,
)


def synthetic_result_sets():
    return [
        {
            "index": 16,
            "rows": [
                {
                    "report_date": "2026-11-17",
                    "painter_name": "Painter Alpha",
                    "booth_number": 1,
                    "carts_painted": 8,
                    "parts_painted": 24,
                    "minutes_logged": 180,
                    "parts_per_hour": 8,
                    "unique_colors": 3,
                    "fty_total": 24,
                    "fty_approved": 20,
                    "fty_repair": 2,
                    "fty_repaint": 1,
                    "fty_pending": 1,
                    "fty_percent": 83.3333,
                },
                {
                    "report_date": "2026-11-18",
                    "painter_name": "Painter Beta",
                    "booth_number": 2,
                    "carts_painted": 10,
                    "parts_painted": 30,
                    "minutes_logged": 210,
                    "parts_per_hour": 8.5714,
                    "unique_colors": 4,
                    "fty_total": 30,
                    "fty_approved": 27,
                    "fty_repair": 1,
                    "fty_repaint": 2,
                    "fty_pending": 0,
                    "fty_percent": 90,
                },
            ],
        },
        {
            "index": 17,
            "rows": [
                {"dimension": "painter", "label": "Painter Beta", "repaint_events": 2, "unique_parts": 2, "contribution_percent": 100},
                {"dimension": "color", "label": "Color Z", "repaint_events": 2, "unique_parts": 2, "contribution_percent": 100},
                {"dimension": "booth", "label": "Booth 2", "repaint_events": 2, "unique_parts": 2, "contribution_percent": 100},
            ],
        },
        {
            "index": 18,
            "rows": [
                {
                    "event_at": "2026-11-18T10:15:00",
                    "part_id": 1002,
                    "part_number": "PN-002",
                    "sequence": "SEQ-002",
                    "color": "Color Z",
                    "painter_name": "Painter Beta",
                    "booth_number": 2,
                    "repaint_loop_count": 1,
                    "defect_description": "Synthetic defect",
                },
                {
                    "event_at": "2026-11-18T11:45:00",
                    "part_id": 1001,
                    "part_number": "PN-001",
                    "sequence": "SEQ-001",
                    "color": "Color Z",
                    "painter_name": "Painter Beta",
                    "booth_number": 2,
                    "repaint_loop_count": 3,
                    "defect_description": "Synthetic defect",
                },
            ],
        },
        {
            "index": 19,
            "rows": [
                {"report_date": "2026-11-18", "worker_name": "Worker Alpha", "outcome": "approved", "part_count": 8, "average_minutes_per_part": 2.5, "max_repaint_count": 0},
                {"report_date": "2026-11-18", "worker_name": "Worker Alpha", "outcome": "repaint", "part_count": 2, "average_minutes_per_part": 5.5, "max_repaint_count": 3},
            ],
        },
        {
            "index": 20,
            "rows": [
                {
                    "event_at": "2026-11-18T12:05:00",
                    "part_id": 1001,
                    "part_number": "PN-001",
                    "sequence": "SEQ-001",
                    "color": "Color Z",
                    "worker_name": "Worker Alpha",
                    "outcome": "repaint",
                    "minutes_per_part": 5.5,
                    "repaint_count": 3,
                }
            ],
        },
    ]


def synthetic_snapshot():
    return build_restricted_snapshot(
        date(2026, 11, 18),
        synthetic_result_sets(),
        generated_at=datetime.fromisoformat("2026-11-18T11:59:00-05:00"),
    )


def test_build_restricted_snapshot_is_private_and_sorted():
    snapshot = synthetic_snapshot()
    validate_restricted_snapshot(snapshot)
    assert snapshot["classification"] == "restricted-operational"
    assert snapshot["scope"]["contains_named_people"] is True
    assert snapshot["scope"]["contains_part_level_detail"] is True
    assert snapshot["scope"]["public_wallboard_compatible"] is False
    assert snapshot["repaint"]["details"][0]["repaint_loop_count"] == 3
    assert snapshot["finesse"]["summary"][0]["max_repaint_count"] == 3
    assert snapshot["painter_daily"][1]["fty_percent"] == 90.0


def test_missing_restricted_result_set_fails_closed():
    with pytest.raises(RestrictedContractError, match="Missing restricted result sets"):
        build_restricted_snapshot(date(2026, 11, 18), synthetic_result_sets()[:-1])


def test_invalid_outcome_fails_closed():
    sets = synthetic_result_sets()
    sets[3]["rows"][0]["outcome"] = "not-reviewed"
    with pytest.raises(RestrictedContractError, match="Unsupported finesse outcome"):
        build_restricted_snapshot(date(2026, 11, 18), sets)


def test_result_set_safety_cap_fails_closed():
    sets = synthetic_result_sets()
    sets[2]["rows"] = [sets[2]["rows"][0]] * (MAX_RESTRICTED_ROWS + 1)
    with pytest.raises(RestrictedContractError, match="safety cap"):
        build_restricted_snapshot(date(2026, 11, 18), sets)


def test_public_odbc_never_requests_named_result_set(monkeypatch):
    observed = {}

    def fake_execute(query, wanted, credential):
        observed.update(query=query, wanted=set(wanted), credential=credential)
        return []

    monkeypatch.setattr(odbc, "execute_result_sets", fake_execute)
    monkeypatch.setenv("KPI_INCLUDE_PAINTERS", "true")
    odbc.execute_operations_rollup(date(2026, 11, 18))
    assert observed["wanted"] == {0, 2, 3, 4, 5, 9, 12, 14, 15}
    assert 8 not in observed["wanted"]
    assert "@IncludeRestrictedDetail = 0" in observed["query"]
    assert "@IncludeRestrictedDetail = 1" not in observed["query"]


def test_restricted_odbc_requires_explicit_hash(monkeypatch):
    monkeypatch.delenv("KPI_RESTRICTED_SQL_PROCEDURE_HASH", raising=False)
    with pytest.raises(odbc.OdbcError, match="must pin"):
        odbc.execute_restricted_rollup(date(2026, 11, 18))


def test_restricted_odbc_fetches_only_reviewed_sets(monkeypatch):
    observed = {}

    def fake_execute(query, wanted, credential):
        observed.update(query=query, wanted=set(wanted), credential=credential)
        return []

    monkeypatch.setattr(odbc, "execute_result_sets", fake_execute)
    monkeypatch.setenv("KPI_RESTRICTED_SQL_PROCEDURE_HASH", "A" * 64)
    odbc.execute_restricted_rollup(date(2026, 11, 18))
    assert observed["wanted"] == {16, 17, 18, 19, 20}
    assert "@IncludeRestrictedDetail = 1" in observed["query"]
    assert "'" + "A" * 64 + "'" in observed["query"]


def test_restricted_frontend_uses_dom_safe_rendering():
    root = Path(__file__).parents[1] / "src" / "operations_kpi_rollup" / "restricted_web"
    script = (root / "app.js").read_text(encoding="utf-8")
    page = (root / "index.html").read_text(encoding="utf-8")
    assert "innerHTML" not in script
    assert "document.write" not in script
    assert "Restricted operational data" in page
    assert "Not part of the wallboard contract" in page
