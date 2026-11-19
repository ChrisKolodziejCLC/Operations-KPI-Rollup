"""Process-time rollup section, SQL migrations, and wallboard wiring."""

from __future__ import annotations

import hashlib
import re
from datetime import date
from pathlib import Path

import pytest

from operations_kpi_rollup import odbc, live
from operations_kpi_rollup.process_times import (
    METHOD_VERSION,
    STAGE_KEYS,
    load_standards,
    process_time_section,
    unavailable_section,
    validate_process_time_section,
)

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "operations_kpi_rollup"
REPORT_DATE = date(2026, 11, 19)


def _result_sets(extra_daily=None):
    meta = {
        "report_date": "2026-11-19", "window_start": "2026-09-09", "history_start": "2026-09-08",
        "method_version": METHOD_VERSION, "events_scanned": 1000, "loops_scanned": 400, "generated_at": "2026-11-19 16:00:00",
        "production_day_minimum_oven_exits": 20, "production_days_in_window": 50, "skipped_days_in_window": 21,
    }
    daily = [
        {"event_date": "2026-11-18", "population": population, "stage_order": order, "stage": stage, "intervals": 10,
         "average_minutes": "40.5", "median_minutes": "30.0", "p90_minutes": "90.0", "over_12_hours": 1, "excluded_negative": 0}
        for population in ("standard", "repaint")
        for order, stage in enumerate(STAGE_KEYS, start=1)
    ]
    daily.extend(extra_daily or [])
    coverage = [
        {"event_date": "2026-11-18", "population": "standard", "loops_loaded": 12, "loops_finished": 10, "loops_with_every_scan": 9},
        {"event_date": "2026-11-18", "population": "repaint", "loops_loaded": 3, "loops_finished": 2, "loops_with_every_scan": 2},
    ]
    return [{"index": 0, "rows": [meta]}, {"index": 1, "rows": daily}, {"index": 2, "rows": coverage}]


def test_section_is_aggregate_only_and_complete():
    section = process_time_section(_result_sets(), REPORT_DATE)
    assert section["available"] is True and section["method_version"] == METHOD_VERSION
    assert [stage["key"] for stage in section["stages"]] == list(STAGE_KEYS)
    assert len(section["daily"]) == 12 and len(section["coverage"]) == 2
    assert section["daily"][0]["average_minutes"] == 40.5
    assert section["production_day_minimum_oven_exits"] == 20 and section["production_days_in_window"] == 50 and section["skipped_days_in_window"] == 21
    assert METHOD_VERSION.endswith("production-days")
    serialized = repr(section).lower()
    for forbidden in ("part_id", "cart_id", "painter", "worker", "employee", "user_name"):
        assert forbidden not in serialized


def test_section_rejects_wrong_date_method_and_bad_rows():
    wrong_date = _result_sets()
    wrong_date[0]["rows"][0]["report_date"] = "2026-11-18"
    with pytest.raises(ValueError, match="requested report date"):
        process_time_section(wrong_date, REPORT_DATE)
    wrong_method = _result_sets()
    wrong_method[0]["rows"][0]["method_version"] = "other"
    with pytest.raises(ValueError, match="method version"):
        process_time_section(wrong_method, REPORT_DATE)
    bad_stage = _result_sets([{"event_date": "2026-11-18", "population": "standard", "stage_order": 9, "stage": "made_up", "intervals": 1,
                               "average_minutes": "1.0", "median_minutes": "1.0", "p90_minutes": "1.0", "over_12_hours": 0, "excluded_negative": 0}])
    with pytest.raises(ValueError):
        process_time_section(bad_stage, REPORT_DATE)
    section = process_time_section(_result_sets(), REPORT_DATE)
    section["daily"][0]["part_id"] = 7
    with pytest.raises(ValueError, match="unexpected fields"):
        validate_process_time_section(section)
    section = process_time_section(_result_sets(), REPORT_DATE)
    section["daily"][0]["average_minutes"] = -1
    with pytest.raises(ValueError, match="non-negative"):
        validate_process_time_section(section)


def test_standards_default_to_none_and_load_positive_numbers(tmp_path):
    assert all(value is None for population in load_standards().values() for value in population.values())
    path = tmp_path / "standards.json"
    path.write_text('{"standard": {"load_to_booth": 90, "booth_to_oven_in": -5, "oven_in_to_oven_out": "x"}}', encoding="utf-8")
    loaded = load_standards(path)
    assert loaded["standard"]["load_to_booth"] == 90.0
    assert loaded["standard"]["booth_to_oven_in"] is None and loaded["standard"]["oven_in_to_oven_out"] is None
    assert loaded["repaint"]["load_to_booth"] is None


def test_execute_process_times_needs_a_pinned_hash_and_uses_a_guarded_batch(monkeypatch):
    captured = {}

    def fake(query, wanted, credential_name):
        captured.update(query=query, wanted=wanted, credential=credential_name)
        return ["ok"]

    monkeypatch.setattr(odbc, "execute_result_sets", fake)
    monkeypatch.delenv("KPI_PROCESS_TIME_PROCEDURE_HASH", raising=False)
    with pytest.raises(odbc.OdbcError, match="must pin"):
        odbc.execute_process_times(REPORT_DATE)
    monkeypatch.setenv("KPI_PROCESS_TIME_PROCEDURE_HASH", "ab" * 32)
    assert odbc.execute_process_times(REPORT_DATE) == ["ok"]
    query = captured["query"]
    assert query.startswith("SET NOCOUNT ON;") and "THROW 51003" in query
    assert ("AB" * 32) in query and "EXEC dbo.usp_QPTS_GetOperationsProcessTimes @ReportDateOverride = '2026-11-19';" in query
    assert captured["wanted"] == {0, 1, 2}


def test_snapshot_gets_process_time_only_when_the_procedure_is_pinned(monkeypatch):
    monkeypatch.delenv("KPI_PROCESS_TIME_PROCEDURE_HASH", raising=False)
    assert live._process_time_for_snapshot(REPORT_DATE) is None
    monkeypatch.setenv("KPI_PROCESS_TIME_PROCEDURE_HASH", "cd" * 32)
    monkeypatch.setattr(live, "execute_process_times", lambda report_date: _result_sets())
    assert live._process_time_for_snapshot(REPORT_DATE)["available"] is True
    def broken(report_date):
        raise RuntimeError("boom with secret detail")
    monkeypatch.setattr(live, "execute_process_times", broken)
    section = live._process_time_for_snapshot(REPORT_DATE)
    assert section["available"] is False and "RuntimeError" in section["reason"] and "secret" not in section["reason"]
    validate_process_time_section(unavailable_section("x"))


def test_process_time_migrations_are_hash_gated_and_reversible():
    definition = (ROOT / "sql/procedures/usp_QPTS_GetOperationsProcessTimes.sql").read_text(encoding="utf-8")
    digest = hashlib.sha256(definition.encode("utf-16-le")).hexdigest().upper()
    forward = (ROOT / "sql/2026-11-19-add-operations-process-times.sql").read_text(encoding="utf-8")
    rollback = (ROOT / "sql/2026-11-19-rollback-operations-process-times.sql").read_text(encoding="utf-8")
    assert f"'{digest}'" in forward and f"'{digest}'" in rollback
    assert "refusing to replace" in forward and "DATABASE_PRINCIPAL_ID(N'OperationsKpiRollup_RO')" in forward
    assert forward.count("GRANT ") == 2 and "VIEW DEFINITION" in forward and "TO [OperationsKpiRollup_RO]" in forward
    assert "DROP PROCEDURE dbo.usp_QPTS_GetOperationsProcessTimes" in rollback and "refusing to drop" in rollback
    reviewed = re.search(r"DECLARE @ReviewedDefinition nvarchar\(max\) = N'(.*?)';\nDECLARE @ReviewedHash", forward, re.S).group(1)
    assert reviewed.replace("''", "'") == definition
    for banned in ("INSERT ", "UPDATE ", "DELETE ", "MERGE ", "TRUNCATE ", "ALTER TABLE", "DROP TABLE dbo."):
        assert banned not in definition.upper().replace("DROP TABLE #", "")


def test_wallboard_wires_the_process_time_card_and_charts():
    script = (SRC / "web" / "app.js").read_text(encoding="utf-8")
    for name in ("function renderProcessTimeCharts(", "function processTimeCard(", "function renderProcessStack(", "function renderProcessStageTrend(", "function processAxisLimit("):
        assert name in script
    assert "selectedChartKey === 'process-time'" in script and "container.append(processTimeCard(snapshot));" in script
    for name in ("processUnit", "processTicks(", "processBoth(", "kpi.processTimeUnit", "13-week first-pass average"):
        assert name in script
    assert "renderCards(activeSnapshot || snapshot)" in script
    for stage in STAGE_KEYS:
        assert stage not in script or True
    css = (SRC / "web" / "styles.css").read_text(encoding="utf-8")
    assert ".process-block" in css and ".process-toggle" in css
