"""Assembly-chart section, SQL migrations, ODBC call, and wallboard wiring."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from operations_kpi_rollup import live, odbc
from operations_kpi_rollup.assembly_charts import (
    METHOD_VERSION,
    METRIC_KEYS,
    METRICS,
    assembly_charts_section,
    normalize_stored_assembly_charts,
    unavailable_section,
    validate_assembly_charts_section,
)

ROOT = Path(__file__).resolve().parents[1]
REPORT_DATE = date(2026, 11, 19)
CHART_START = date(2026, 8, 23)
PROCEDURE = ROOT / "sql/procedures/usp_QPTS_GetOperationsAssemblyCharts.sql"


def _result_sets(report_date=REPORT_DATE):
    chart_start = report_date - timedelta(days=(report_date.weekday() + 1) % 7) - timedelta(weeks=12)
    meta = {
        "method_version": METHOD_VERSION, "report_date": report_date.isoformat(), "week_start": "ignored",
        "chart_start": chart_start.isoformat(), "fact_rows": 5000,
    }
    daily = []
    day = chart_start
    while day <= report_date:
        busy = day.weekday() < 5
        daily.append({"bucket_start": day.isoformat(), "pieces": 120 if busy else 0, "bumpers": 30 if busy else 0, "complete_sets": 10 if busy else 0})
        day += timedelta(days=1)
    hourly = []
    for hour in range(24):
        busy = 6 <= hour <= 15 and report_date.weekday() < 5
        hourly.append({
            "bucket_start": report_date.isoformat() + " %02d:00:00" % hour,
            "pieces": 12 if busy else 0, "bumpers": 3 if busy else 0, "complete_sets": 1 if busy else 0,
        })
    return [{"index": 0, "rows": [meta]}, {"index": 1, "rows": daily}, {"index": 2, "rows": hourly}]


def _section(report_date=REPORT_DATE, now=datetime(2026, 11, 19, 11, 30)):
    return assembly_charts_section(_result_sets(report_date), report_date, now)


def test_section_is_complete_counts_only_and_valid():
    section = _section()
    assert section["available"] is True and section["method_version"] == METHOD_VERSION
    assert [metric["key"] for metric in section["metrics"]] == list(METRIC_KEYS) == ["sets", "pieces", "bumpers"]
    assert section["metrics"] == [dict(metric) for metric in METRICS]
    assert section["daily_totals"] == {"sets": 10, "pieces": 120, "bumpers": 30}
    assert section["chart_start"] == CHART_START.isoformat() and section["fact_rows"] == 5000
    for key in METRIC_KEYS:
        entry = section["series"][key]
        assert set(entry) == {"hourly", "weekly_13"}
        assert len(entry["hourly"]) == 24 and len(entry["weekly_13"]) == 13
        assert entry["hourly"][0]["bucket"] == "2026-11-19T00:00:00" and entry["hourly"][23]["bucket"] == "2026-11-19T23:00:00"
    assert section["series"]["pieces"]["weekly_13"][0]["bucket"] == "2026-08-23"
    assert section["series"]["pieces"]["weekly_13"][-1]["bucket"] == "2026-11-15"
    serialized = repr(section).lower()
    for forbidden in ("part_id", "cart_id", "login", "user", "painter", "employee", "assembled_by"):
        assert forbidden not in serialized
    validate_assembly_charts_section(section)


def test_weekly_rows_total_the_week_count_assembly_days_and_mark_the_current_week_partial():
    weeks = _section()["series"]["pieces"]["weekly_13"]
    assert weeks[-1]["is_partial"] is True and weeks[-1]["bucket_end"] == "2026-11-19"
    assert weeks[-1]["represented_days"] == 4 and weeks[-1]["total"] == 480 and weeks[-1]["daily_average"] == 120.0
    assert weeks[-2]["is_partial"] is False and weeks[-2]["represented_days"] == 5 and weeks[-2]["total"] == 600
    assert weeks[-2]["bucket_end"] == "2026-11-14" and weeks[-2]["daily_average"] == 120.0
    sets = _section()["series"]["sets"]["weekly_13"]
    assert sets[-1]["total"] == 40 and sets[-2]["total"] == 50 and sets[-2]["daily_average"] == 10.0
    bumpers = _section()["series"]["bumpers"]["weekly_13"]
    assert bumpers[-1]["total"] == 120 and bumpers[0]["total"] == 150


def test_a_report_date_that_ends_the_week_is_a_full_week():
    saturday = date(2026, 11, 14)
    section = _section(saturday, datetime(2026, 11, 15, 8, 0))
    last = section["series"]["pieces"]["weekly_13"][-1]
    assert last["bucket"] == "2026-11-08" and last["bucket_end"] == "2026-11-14" and last["is_partial"] is False
    assert section["daily_totals"] == {"sets": 0, "pieces": 0, "bumpers": 0}


def test_hourly_rows_flag_only_the_running_hour_as_partial():
    section = _section()
    flagged = [row["bucket"] for row in section["series"]["sets"]["hourly"] if row["is_partial"]]
    assert flagged == ["2026-11-19T11:00:00"]
    past = assembly_charts_section(_result_sets(), REPORT_DATE, datetime(2026, 11, 20, 8, 0))
    assert not any(row["is_partial"] for row in past["series"]["sets"]["hourly"])


def test_section_rejects_wrong_date_method_chart_start_gaps_and_bad_counts():
    wrong_date = _result_sets()
    wrong_date[0]["rows"][0]["report_date"] = "2026-11-18"
    with pytest.raises(ValueError, match="requested report date"):
        assembly_charts_section(wrong_date, REPORT_DATE)
    wrong_method = _result_sets()
    wrong_method[0]["rows"][0]["method_version"] = "other"
    with pytest.raises(ValueError, match="method version"):
        assembly_charts_section(wrong_method, REPORT_DATE)
    wrong_start = _result_sets()
    wrong_start[0]["rows"][0]["chart_start"] = "2026-08-30"
    with pytest.raises(ValueError, match="chart start"):
        assembly_charts_section(wrong_start, REPORT_DATE)
    missing_day = _result_sets()
    del missing_day[1]["rows"][10]
    with pytest.raises(ValueError, match="every day"):
        assembly_charts_section(missing_day, REPORT_DATE)
    twice = _result_sets()
    twice[1]["rows"].append(dict(twice[1]["rows"][0]))
    with pytest.raises(ValueError, match="day twice"):
        assembly_charts_section(twice, REPORT_DATE)
    short = _result_sets()
    del short[2]["rows"][5]
    with pytest.raises(ValueError, match="24 hourly"):
        assembly_charts_section(short, REPORT_DATE)
    negative = _result_sets()
    negative[2]["rows"][8]["pieces"] = -1
    with pytest.raises(ValueError, match="negative"):
        assembly_charts_section(negative, REPORT_DATE)
    with pytest.raises(ValueError, match="no metadata"):
        assembly_charts_section([{"index": 0, "rows": []}], REPORT_DATE)


def test_hourly_counts_must_add_up_to_the_day():
    drifted = _result_sets()
    drifted[2]["rows"][8]["complete_sets"] += 1
    with pytest.raises(ValueError, match="do not add up"):
        assembly_charts_section(drifted, REPORT_DATE)


def test_validator_rejects_unexpected_fields_and_shapes():
    section = _section()
    section["series"]["sets"]["hourly"][0]["part_id"] = 7
    with pytest.raises(ValueError, match="unexpected fields"):
        validate_assembly_charts_section(section)
    section = _section()
    section["login"] = "someone"
    with pytest.raises(ValueError, match="unexpected fields"):
        validate_assembly_charts_section(section)
    section = _section()
    section["series"]["sets"]["weekly_13"][3]["daily_average"] = 99.0
    with pytest.raises(ValueError, match="daily_average"):
        validate_assembly_charts_section(section)
    section = _section()
    section["series"]["pieces"]["weekly_13"][0], section["series"]["pieces"]["weekly_13"][1] = (
        section["series"]["pieces"]["weekly_13"][1], section["series"]["pieces"]["weekly_13"][0])
    with pytest.raises(ValueError, match="13 consecutive Sunday-start weeks"):
        validate_assembly_charts_section(section)
    section = _section()
    section["metrics"][0]["label"] = "Something else"
    with pytest.raises(ValueError, match="reviewed metrics"):
        validate_assembly_charts_section(section)
    section = _section()
    section["series"]["bumpers"]["weekly_13"][-1]["total"] = 2
    section["series"]["bumpers"]["weekly_13"][-1]["daily_average"] = 0.5  # 2 over 4 days, still below the 30 of the report day
    with pytest.raises(ValueError, match="report week"):
        validate_assembly_charts_section(section)


def test_unavailable_section_validates_and_older_saved_methods_are_replaced():
    validate_assembly_charts_section(unavailable_section("not deployed"))
    snapshot = {"assembly_charts": {"available": True, "method_version": "operations-kpi-assembly-charts-v0"}}
    assert normalize_stored_assembly_charts(snapshot)["assembly_charts"]["available"] is False
    assert "earlier assembly-chart method" in snapshot["assembly_charts"]["reason"]
    current = {"assembly_charts": unavailable_section("placeholder")}
    assert normalize_stored_assembly_charts(current)["assembly_charts"]["reason"] == "placeholder"
    assert "assembly_charts" not in normalize_stored_assembly_charts({})


def test_execute_assembly_charts_needs_a_pinned_hash_and_uses_a_guarded_batch(monkeypatch):
    captured = {}

    def fake(query, wanted, credential_name):
        captured.update(query=query, wanted=wanted, credential=credential_name)
        return ["ok"]

    monkeypatch.setattr(odbc, "execute_result_sets", fake)
    monkeypatch.delenv("KPI_ASSEMBLY_CHARTS_PROCEDURE_HASH", raising=False)
    with pytest.raises(odbc.OdbcError, match="must pin"):
        odbc.execute_assembly_charts(REPORT_DATE)
    monkeypatch.setenv("KPI_ASSEMBLY_CHARTS_PROCEDURE_HASH", "ab" * 32)
    assert odbc.execute_assembly_charts(REPORT_DATE) == ["ok"]
    query = captured["query"]
    assert query.startswith("SET NOCOUNT ON;") and "THROW 51006" in query
    assert ("AB" * 32) in query and "EXEC dbo.usp_QPTS_GetOperationsAssemblyCharts @ReportDateOverride = '2026-11-19';" in query
    assert captured["wanted"] == {0, 1, 2} and captured["credential"] == "operations-kpi-qpts-ro"


def _card(sets=10, bumpers=30):
    return {"daily": [{"date": "2026-11-19", "complete_assy_sets": sets, "assembled_bumper_count": bumpers}]}


def test_snapshot_gets_assembly_charts_only_when_the_procedure_is_pinned(monkeypatch):
    monkeypatch.delenv("KPI_ASSEMBLY_CHARTS_PROCEDURE_HASH", raising=False)
    assert live._assembly_charts_for_snapshot(REPORT_DATE, None, _card()) is None
    monkeypatch.setenv("KPI_ASSEMBLY_CHARTS_PROCEDURE_HASH", "cd" * 32)
    monkeypatch.setattr(live, "execute_assembly_charts", lambda report_date: _result_sets())
    monkeypatch.setattr(live, "business_today", lambda: REPORT_DATE)
    assert live._assembly_charts_for_snapshot(REPORT_DATE, datetime(2026, 11, 19, 11, 30), _card())["available"] is True

    def broken(report_date):
        raise RuntimeError("boom with secret detail")

    monkeypatch.setattr(live, "execute_assembly_charts", broken)
    section = live._assembly_charts_for_snapshot(REPORT_DATE, None, _card())
    assert section["available"] is False and "RuntimeError" in section["reason"] and "secret" not in section["reason"]


def test_a_finished_day_must_equal_its_tiles_but_the_current_day_is_not_cross_checked(monkeypatch):
    monkeypatch.setenv("KPI_ASSEMBLY_CHARTS_PROCEDURE_HASH", "cd" * 32)
    monkeypatch.setattr(live, "execute_assembly_charts", lambda report_date: _result_sets())
    stamp = datetime(2026, 11, 20, 8, 0)
    monkeypatch.setattr(live, "business_today", lambda: date(2026, 11, 20))
    assert live._assembly_charts_for_snapshot(REPORT_DATE, stamp, _card())["available"] is True
    off_sets = live._assembly_charts_for_snapshot(REPORT_DATE, stamp, _card(sets=11))
    assert off_sets["available"] is False and "do not add up to the tiles" in off_sets["reason"]
    off_bumpers = live._assembly_charts_for_snapshot(REPORT_DATE, stamp, _card(bumpers=29))
    assert off_bumpers["available"] is False
    monkeypatch.setattr(live, "business_today", lambda: REPORT_DATE)
    assert live._assembly_charts_for_snapshot(REPORT_DATE, datetime(2026, 11, 19, 11, 30), _card(sets=11))["available"] is True


def test_assembly_chart_migrations_are_hash_gated_and_reversible():
    definition = PROCEDURE.read_text(encoding="utf-8")
    digest = hashlib.sha256(definition.encode("utf-16-le")).hexdigest().upper()
    forward = (ROOT / "sql/2026-11-23-add-operations-assembly-charts.sql").read_text(encoding="utf-8")
    rollback = (ROOT / "sql/2026-11-23-rollback-operations-assembly-charts.sql").read_text(encoding="utf-8")
    assert f"@ExpectedHash varchar(64) = '{digest}'" in forward and f"@ExpectedHash varchar(64) = '{digest}'" in rollback
    assert "refusing to replace it" in forward and "DATABASE_PRINCIPAL_ID(N'OperationsKpiRollup_RO')" in forward
    assert forward.count("GRANT ") == 2 and "VIEW DEFINITION" in forward and "TO [OperationsKpiRollup_RO]" in forward
    assert "DROP PROCEDURE dbo.usp_QPTS_GetOperationsAssemblyCharts;" in rollback and "refusing to drop" in rollback
    assert "DECLARE @CommitChange bit = 1;" in forward and "DECLARE @CommitChange bit = 1;" in rollback
    reviewed = re.search(r"DECLARE @ReviewedDefinition nvarchar\(max\) = N'(.*?)';\nDECLARE @ReviewedHash", forward, re.S).group(1)
    assert reviewed.replace("''", "'") == definition
    assert "operations-kpi-assembly-charts-v1" in definition and "READ UNCOMMITTED" in definition
    for banned in ("INSERT ", "UPDATE ", "DELETE ", "MERGE ", "TRUNCATE ", "ALTER TABLE", "DROP TABLE DBO."):
        assert banned not in definition.upper().replace("DROP TABLE #", "")
    for person_level in ("AssembledLogin", "user_name", "insp_assemble_user"):
        assert person_level not in definition
    unit = (ROOT / "deploy/operations-kpi-rollup.service").read_text(encoding="utf-8")
    assert f"KPI_ASSEMBLY_CHARTS_PROCEDURE_HASH={digest}" in unit
    throws = set(re.findall(r"THROW (\d+)", forward + rollback))
    others = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "sql").glob("*.sql") if "assembly-charts" not in path.name)
    assert throws.isdisjoint(set(re.findall(r"THROW (\d+)", others)))


def test_assembly_chart_procedure_copies_the_reviewed_bumper_and_set_rules():
    definition = PROCEDURE.read_text(encoding="utf-8")
    source = (ROOT / "sql/2026-11-18-painter-ids-restricted-drilldown.sql").read_text(encoding="utf-8")
    rollup = re.search(r"DECLARE @ReviewedDefinition nvarchar\(max\) = N'(.*?)';\nDECLARE @ReviewedHash", source, re.S).group(1).replace("''", "'")
    for rule in (
        "CASE WHEN LTRIM(CONVERT(nvarchar(255), e.[Part Number])) LIKE N'N71-6171%' THEN 1 ELSE 0 END AS is_bumper",
        "OR LTRIM(RTRIM(CONVERT(nvarchar(255), e.Description))) = N'Chassis Fairing'",
        "AND NULLIF(LTRIM(RTRIM(CONVERT(nvarchar(255), e.[Sequence]))), N'') IS NOT NULL",
        "ISNULL(e.Model, N'') <> N'Service'",
    ):
        assert rule in definition and rule in rollup
    # The exactly-four-distinct-pieces rule is the same; the procedure applies it as of the end of each day and for the report date.
    assert "HAVING COUNT(DISTINCT e.[Part ID]) = 4" in rollup
    assert "HAVING COUNT(DISTINCT part_id) = 4" in definition
    assert "SELECT COUNT(DISTINCT set_pieces.part_id)" in definition
    assert "AND set_pieces.assembled_at < DATEADD(day, 1, CONVERT(datetime2(0), set_days.day_assembled))" in definition
    assert ") = 4\n        GROUP BY set_days.day_assembled" in definition
    for temp in ("#AssembledPieces", "#SetPieces", "#SetDays", "#CompleteSets"):
        assert "DROP TABLE " + temp + ";" in definition


def test_snapshot_validation_accepts_the_assembly_charts_section():
    from operations_kpi_rollup.context import validate_snapshot

    snapshot = json.loads((ROOT / "examples" / "2026-09-16.json").read_text(encoding="utf-8"))
    snapshot["assembly_charts"] = _section(date(2026, 9, 16), datetime(2026, 9, 17, 8, 0))
    validate_snapshot(snapshot)
    snapshot["assembly_charts"]["series"]["sets"]["hourly"][0]["worker"] = "x"
    with pytest.raises(ValueError, match="unexpected fields"):
        validate_snapshot(snapshot)
    snapshot["assembly_charts"] = unavailable_section("not deployed")
    validate_snapshot(snapshot)

def test_wallboard_script_renders_the_assembly_charts_for_the_two_tiles():
    script = (ROOT / "src" / "operations_kpi_rollup" / "web" / "app.js").read_text(encoding="utf-8")
    assert "const ASSEMBLY_TILES = {" in script
    assert "'complete-assy-sets': {" in script and "'assembled-bumpers': {" in script
    for key in ("sets", "pieces", "bumpers"):
        assert "{key:'%s'," % key in script
    assert "function renderAssemblyCharts(snapshot, tileKey) {" in script
    assert "snapshot.assembly_charts" in script
    assert "This saved snapshot predates the assembly charts." in script
    assert "section.reason || 'The assembly charts are not available right now.'" in script
    # The tile click reaches the renderer before the yield tiles, and the 13-week bars show the per-assembly-day average.
    dispatcher = script[script.index("function renderMetricCharts(snapshot) {"):]
    assert dispatcher.index("ASSEMBLY_TILES[selectedChartKey]") < dispatcher.index("YIELD_TILES[selectedChartKey]")
    assert "renderAssemblyCharts(snapshot, selectedChartKey); return;" in dispatcher
    block = script[script.index("const ASSEMBLY_TILES = {"):script.index("function renderMetricCharts(snapshot) {")]
    assert "field:'daily_average'" in block and "field:'value'" in block and "omitNull:true" in block and "chartType:'bar'" in block
    assert "data_available: Number(row.represented_days || 0) > 0" in block
    assert "data_available: true" in block  # hourly rows need the flag or the chart draws nothing
    assert "const assemblyUnit = (count, metric) =>" in block
    assert "total over" in block and "assembly days" in block
    for forbidden in ("login", "user", "worker", "employee", "painter", "part_id"):
        assert forbidden not in block.lower()
