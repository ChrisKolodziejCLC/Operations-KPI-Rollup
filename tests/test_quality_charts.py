"""Quality-chart section, SQL migrations, ODBC call, and wallboard wiring."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from operations_kpi_rollup import live, odbc
from operations_kpi_rollup.quality_charts import (
    METHOD_VERSION,
    UNRECOGNIZED_CODE,
    safe_defect_description,
    METRIC_KEYS,
    normalize_stored_quality_charts,
    quality_charts_section,
    unavailable_section,
    validate_quality_charts_section,
)

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "operations_kpi_rollup"
REPORT_DATE = date(2026, 11, 19)
CHART_START = date(2026, 8, 23)
HISTORY_START = date(2026, 9, 8)


def _result_sets(defects=None):
    meta = {
        "method_version": METHOD_VERSION, "report_date": "2026-11-19", "chart_start": "2026-08-23",
        "history_start": "2026-09-08", "fact_rows": 5000, "paint_passes_in_window": 3000,
    }
    daily = []
    day = CHART_START
    while day <= REPORT_DATE:
        for position, key in enumerate(METRIC_KEYS):
            available = day >= HISTORY_START
            produced = available and day.weekday() < 5
            denominator = 100 + position if produced else 0
            daily.append({
                "metric_key": key, "bucket_start": day.isoformat(), "data_available": int(available),
                "represented_day": int(produced), "quality_numerator": 90 if produced else 0,
                "quality_denominator": denominator, "pending_count": 2 if produced else 0,
            })
        day += timedelta(days=1)
    hourly = []
    for key in METRIC_KEYS:
        for hour in range(24):
            busy = 6 <= hour <= 15
            hourly.append({
                "metric_key": key, "bucket_start": "2026-11-19 %02d:00:00" % hour, "data_available": 1, "represented_day": 1,
                "quality_numerator": 9 if busy else 0, "quality_denominator": 10 if busy else 0, "pending_count": 1 if busy else 0,
            })
    rows = defects if defects is not None else [
        {"bucket_start": "2026-11-19", "inspection_step": "Receiving", "defect_description": "Scratch", "defect_count": 4},
        {"bucket_start": "2026-11-19", "inspection_step": "End of Line", "defect_description": "Dirt", "defect_count": 7},
        {"bucket_start": "2026-11-18", "inspection_step": "Final", "defect_description": "Unspecified", "defect_count": 1},
    ]
    return [{"index": 0, "rows": [meta]}, {"index": 1, "rows": daily}, {"index": 2, "rows": hourly}, {"index": 3, "rows": rows}]


def _section():
    return quality_charts_section(_result_sets(), REPORT_DATE, datetime(2026, 11, 19, 11, 30))


def test_section_is_complete_counts_only_and_valid():
    section = _section()
    assert section["available"] is True and section["method_version"] == METHOD_VERSION
    assert list(section["series"]) == list(METRIC_KEYS)
    for key in METRIC_KEYS:
        entry = section["series"][key]
        assert set(entry) == {"hourly", "weekly_13"}
        assert len(entry["hourly"]) == 24 and len(entry["weekly_13"]) == 13
        assert entry["hourly"][0]["bucket"] == "2026-11-19T00:00:00"
    assert [row["bucket"] for row in section["series"]["receiving"]["weekly_13"]][0] == "2026-08-23"
    assert section["series"]["receiving"]["weekly_13"][-1]["bucket"] == "2026-11-15"
    assert len(section["defects"]) == 3 and section["defects"][-1] == {"date": "2026-11-19", "step": "Receiving", "description": "Scratch", "count": 4}
    serialized = repr(section).lower()
    for forbidden in ("part_id", "cart_id", "painter", "worker", "employee", "user_name"):
        assert forbidden not in serialized
    validate_quality_charts_section(section)


def test_weekly_rows_count_represented_days_and_mark_the_current_week_partial():
    section = _section()
    weeks = section["series"]["ppy_repaint"]["weekly_13"]
    assert weeks[-1]["is_partial"] is True and weeks[-1]["bucket_end"] == "2026-11-19"
    assert weeks[-1]["represented_days"] == 4 and weeks[-1]["quality_denominator"] == 400 and weeks[-1]["quality_numerator"] == 360
    assert weeks[-1]["pending_count"] == 8 and weeks[-1]["rate_percent"] == 90.0
    assert weeks[-2]["is_partial"] is False and weeks[-2]["represented_days"] == 5 and weeks[-2]["quality_denominator"] == 500
    assert weeks[0]["data_available"] is False and weeks[0]["represented_days"] == 0 and weeks[0]["rate_percent"] is None
    assert weeks[2]["bucket"] == "2026-09-06" and weeks[2]["data_available"] is True and weeks[2]["represented_days"] == 4
    assert weeks[0]["rate_percent"] is None and weeks[1]["data_available"] is False


def test_hourly_rows_flag_only_the_running_hour_as_partial():
    section = _section()
    flagged = [row["bucket"] for row in section["series"]["final"]["hourly"] if row["is_partial"]]
    assert flagged == ["2026-11-19T11:00:00"]
    past = quality_charts_section(_result_sets(), REPORT_DATE, datetime(2026, 11, 20, 8, 0))
    assert not any(row["is_partial"] for row in past["series"]["final"]["hourly"])
    assert not past["series"]["final"]["weekly_13"][-1]["is_partial"] or past["series"]["final"]["weekly_13"][-1]["bucket_end"] == "2026-11-19"


def test_section_rejects_wrong_date_method_metric_and_bad_counts():
    wrong_date = _result_sets()
    wrong_date[0]["rows"][0]["report_date"] = "2026-11-18"
    with pytest.raises(ValueError, match="requested report date"):
        quality_charts_section(wrong_date, REPORT_DATE)
    wrong_method = _result_sets()
    wrong_method[0]["rows"][0]["method_version"] = "other"
    with pytest.raises(ValueError, match="method version"):
        quality_charts_section(wrong_method, REPORT_DATE)
    unknown = _result_sets()
    unknown[1]["rows"][0]["metric_key"] = "made_up"
    with pytest.raises(ValueError, match="unknown metric"):
        quality_charts_section(unknown, REPORT_DATE)
    over = _result_sets()
    over[1]["rows"][-1]["quality_numerator"] = over[1]["rows"][-1]["quality_denominator"] + 1
    with pytest.raises(ValueError, match="exceeds"):
        quality_charts_section(over, REPORT_DATE)
    with pytest.raises(ValueError, match="no metadata"):
        quality_charts_section([{"index": 0, "rows": []}], REPORT_DATE)
    section = _section()
    section["series"]["ppy_repaint"]["hourly"][0]["part_id"] = 7
    with pytest.raises(ValueError, match="unexpected fields"):
        validate_quality_charts_section(section)
    section = _section()
    section["defects"][0]["step"] = "Elsewhere"
    with pytest.raises(ValueError, match="unknown inspection step"):
        validate_quality_charts_section(section)


def test_unavailable_section_validates_and_older_saved_methods_are_replaced():
    validate_quality_charts_section(unavailable_section("not deployed"))
    snapshot = {"quality_charts": {"available": True, "method_version": "operations-kpi-quality-charts-v0"}}
    assert normalize_stored_quality_charts(snapshot)["quality_charts"]["available"] is False
    assert "earlier quality-chart method" in snapshot["quality_charts"]["reason"]
    current = {"quality_charts": unavailable_section("placeholder")}
    assert normalize_stored_quality_charts(current)["quality_charts"]["reason"] == "placeholder"
    assert "quality_charts" not in normalize_stored_quality_charts({})


def test_execute_quality_charts_needs_a_pinned_hash_and_uses_a_guarded_batch(monkeypatch):
    captured = {}

    def fake(query, wanted, credential_name):
        captured.update(query=query, wanted=wanted, credential=credential_name)
        return ["ok"]

    monkeypatch.setattr(odbc, "execute_result_sets", fake)
    monkeypatch.delenv("KPI_QUALITY_CHARTS_PROCEDURE_HASH", raising=False)
    with pytest.raises(odbc.OdbcError, match="must pin"):
        odbc.execute_quality_charts(REPORT_DATE)
    monkeypatch.setenv("KPI_QUALITY_CHARTS_PROCEDURE_HASH", "ab" * 32)
    assert odbc.execute_quality_charts(REPORT_DATE) == ["ok"]
    query = captured["query"]
    assert query.startswith("SET NOCOUNT ON;") and "THROW 51004" in query
    assert ("AB" * 32) in query and "EXEC dbo.usp_QPTS_GetOperationsQualityCharts @ReportDateOverride = '2026-11-19';" in query
    assert captured["wanted"] == {0, 1, 2, 3}


def test_snapshot_gets_quality_charts_only_when_the_procedure_is_pinned(monkeypatch):
    monkeypatch.delenv("KPI_QUALITY_CHARTS_PROCEDURE_HASH", raising=False)
    assert live._quality_charts_for_snapshot(REPORT_DATE, None) is None
    monkeypatch.setenv("KPI_QUALITY_CHARTS_PROCEDURE_HASH", "cd" * 32)
    monkeypatch.setattr(live, "execute_quality_charts", lambda report_date: _result_sets())
    assert live._quality_charts_for_snapshot(REPORT_DATE, datetime(2026, 11, 19, 11, 30))["available"] is True

    def broken(report_date):
        raise RuntimeError("boom with secret detail")

    monkeypatch.setattr(live, "execute_quality_charts", broken)
    section = live._quality_charts_for_snapshot(REPORT_DATE, None)
    assert section["available"] is False and "RuntimeError" in section["reason"] and "secret" not in section["reason"]


def test_quality_chart_migrations_are_hash_gated_and_reversible():
    definition = (ROOT / "sql/procedures/usp_QPTS_GetOperationsQualityCharts.sql").read_text(encoding="utf-8")
    digest = hashlib.sha256(definition.encode("utf-16-le")).hexdigest().upper()
    forward = (ROOT / "sql/2026-11-19-add-operations-quality-charts.sql").read_text(encoding="utf-8")
    rollback = (ROOT / "sql/2026-11-19-rollback-operations-quality-charts.sql").read_text(encoding="utf-8")
    assert f"@ExpectedHash varchar(64) = '{digest}'" in forward and f"@ExpectedHash varchar(64) = '{digest}'" in rollback
    assert "refusing to replace it" in forward and "DATABASE_PRINCIPAL_ID(N'OperationsKpiRollup_RO')" in forward
    assert forward.count("GRANT ") == 2 and "VIEW DEFINITION" in forward and "TO [OperationsKpiRollup_RO]" in forward
    assert "DROP PROCEDURE dbo.usp_QPTS_GetOperationsQualityCharts;" in rollback and "refusing to drop" in rollback
    reviewed = re.search(r"DECLARE @ReviewedDefinition nvarchar\(max\) = N'(.*?)';\nDECLARE @ReviewedHash", forward, re.S).group(1)
    assert reviewed.replace("''", "'") == definition
    assert "operations-kpi-quality-charts-v1" in definition and "READ UNCOMMITTED" in definition
    for banned in ("INSERT ", "UPDATE ", "DELETE ", "MERGE ", "TRUNCATE ", "ALTER TABLE", "DROP TABLE DBO."):
        assert banned not in definition.upper().replace("DROP TABLE #", "")
    unit = (ROOT / "deploy/operations-kpi-rollup.service").read_text(encoding="utf-8")
    assert f"KPI_QUALITY_CHARTS_PROCEDURE_HASH={digest}" in unit


def test_quality_chart_procedure_copies_the_reviewed_rollup_pass_model():
    definition = (ROOT / "sql/procedures/usp_QPTS_GetOperationsQualityCharts.sql").read_text(encoding="utf-8")
    source = (ROOT / "sql/2026-11-18-painter-ids-restricted-drilldown.sql").read_text(encoding="utf-8")
    reviewed = re.search(r"DECLARE @ReviewedDefinition nvarchar\(max\) = N'(.*?)';\nDECLARE @ReviewedHash", source, re.S).group(1).replace("''", "'")
    begin = "    SELECT\n        h.id,\n        h.part_id,\n        h.PaintCart_ID,"
    end = "    CREATE INDEX IX_RollupPaintDate ON #PaintPasses(event_date, part_id);\n"
    copied = reviewed[reviewed.index(begin):reviewed.index(end) + len(end)]
    assert copied in definition
    assert hashlib.sha256(reviewed.encode("utf-16-le")).hexdigest().upper() == "7AA6DCC3A056553C3945EF7474FE15B44565BD9C450E97030DD9970CBF569936"


def test_snapshot_validation_accepts_the_quality_charts_section():
    from operations_kpi_rollup.context import validate_snapshot

    snapshot = json.loads((ROOT / "examples" / "2026-09-16.json").read_text(encoding="utf-8"))
    snapshot["quality_charts"] = _section()
    validate_snapshot(snapshot)
    snapshot["quality_charts"]["series"]["final"]["hourly"][0]["part_id"] = 1
    with pytest.raises(ValueError):
        validate_snapshot(snapshot)


def test_wallboard_wires_the_yield_charts_and_pareto():
    script = (SRC / "web" / "app.js").read_text(encoding="utf-8")
    for name in ("const YIELD_TILES = {", "function renderYieldCharts(", "function paretoCard(", "function paretoTotals(", "function yieldHourlySummary(", "function yieldWeeklySummary("):
        assert name in script
    for key in ("ppy-paint-process-yield", "fty-first-time-yield", "receiving-fty", "final-fty"):
        assert "'" + key + "'" in script
    for metric in METRIC_KEYS:
        assert "key: '" + metric + "'" in script
    assert "if (YIELD_TILES[selectedChartKey]) {" in script and "renderYieldCharts(snapshot, selectedChartKey); return;" in script
    assert "snapshot.quality_charts" in script and "section.series?.[metric.key]" in script
    assert "axisMaximum:100" in script and "options.axisMaximum" in script
    assert "No rejections recorded in this period." in script
    css = (SRC / "web" / "styles.css").read_text(encoding="utf-8")
    for selector in (".pareto-card", ".pareto-row", ".pareto-track", ".pareto-other"):
        assert selector in css


def test_yield_tiles_match_the_wallboard_card_labels():
    script = (SRC / "web" / "app.js").read_text(encoding="utf-8")
    for label, key in (("PPY (Paint Process Yield)", "ppy-paint-process-yield"), ("FTY (First Time Yield)", "fty-first-time-yield"), ("Receiving FTY", "receiving-fty"), ("Final FTY", "final-fty")):
        assert label in script
        assert re.sub(r"^-|-$", "", re.sub(r"[^a-z0-9]+", "-", label.strip().lower())) == key


def test_public_snapshot_section_never_carries_identifiers():
    section = _section()
    keys = set()

    def walk(value):
        if isinstance(value, dict):
            for name, item in value.items():
                keys.add(name)
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(section)
    banned = {"part_id", "part", "cart_id", "painter", "worker", "worker_id", "employee", "employee_id", "user_name", "name", "serial"}
    assert not (keys & banned)


def test_unmapped_raw_codes_are_shown_as_unrecognized_and_merged():
    assert safe_defect_description("2029468521") == UNRECOGNIZED_CODE == "Unrecognized code"
    assert safe_defect_description(" 1234567 ") == UNRECOGNIZED_CODE
    assert safe_defect_description("123456") == "123456"
    assert safe_defect_description("Dirt 2029468") == "Dirt 2029468"
    assert safe_defect_description("") == "Unspecified" and safe_defect_description(None) == "Unspecified"
    rows = [
        {"bucket_start": "2026-11-19", "inspection_step": "Final", "defect_description": "2029468521", "defect_count": 1},
        {"bucket_start": "2026-11-19", "inspection_step": "Final", "defect_description": "9988776655", "defect_count": 2},
        {"bucket_start": "2026-11-19", "inspection_step": "Final", "defect_description": "Scratch", "defect_count": 3},
        {"bucket_start": "2026-11-18", "inspection_step": "Final", "defect_description": "2029468521", "defect_count": 4},
    ]
    section = quality_charts_section(_result_sets(rows), REPORT_DATE, datetime(2026, 11, 19, 11, 30))
    assert section["defects"] == [
        {"date": "2026-11-18", "step": "Final", "description": "Unrecognized code", "count": 4},
        {"date": "2026-11-19", "step": "Final", "description": "Scratch", "count": 3},
        {"date": "2026-11-19", "step": "Final", "description": "Unrecognized code", "count": 3},
    ]
    validate_quality_charts_section(section)


def test_wallboard_polish_is_wired():
    script = (SRC / "web" / "app.js").read_text(encoding="utf-8")
    assert "const regular = index % step === 0 && last - index >= Math.ceil(step * 0.75);" in script
    assert "if (!regular && index !== last) return;" in script
    assert "stroke: '#fff', 'stroke-width': 3, 'paint-order': 'stroke', 'stroke-linejoin': 'round', 'font-size': 11" in script
    live_source = (SRC / "live.py").read_text(encoding="utf-8")
    assert "identity-gated" not in live_source and "restricted drill-down" not in live_source
    assert "This public wallboard carries no employee names or IDs; employee-level detail lives only in the drill-down." in live_source


def test_targets_and_goals_are_chris_numbers_and_ride_in_the_section():
    from operations_kpi_rollup.quality_charts import load_targets

    marks = load_targets()
    assert set(marks) == set(METRIC_KEYS)
    for key in ("ppy_repaint", "ppy_reject", "fty_repaint", "fty_reject"):
        assert marks[key] == {"target_percent": 75.0, "goal_percent": 85.0}
    assert marks["receiving"] == {"target_percent": 90.0, "goal_percent": 95.0}
    assert marks["final"] == {"target_percent": 95.0, "goal_percent": 100.0}
    assert _section()["targets"] == marks


def test_target_loader_is_strict_and_a_missing_file_means_no_marks(tmp_path):
    import json

    import pytest

    from operations_kpi_rollup.quality_charts import load_targets

    assert load_targets(tmp_path / "absent.json") == {key: {"target_percent": None, "goal_percent": None} for key in METRIC_KEYS}
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    assert load_targets(broken)["final"] == {"target_percent": None, "goal_percent": None}
    reversed_marks = tmp_path / "reversed.json"
    reversed_marks.write_text(json.dumps({"final": {"target_percent": 95, "goal_percent": 90}}), encoding="utf-8")
    with pytest.raises(ValueError):
        load_targets(reversed_marks)
    out_of_range = tmp_path / "range.json"
    out_of_range.write_text(json.dumps({"receiving": {"target_percent": 0, "goal_percent": 120}}), encoding="utf-8")
    with pytest.raises(ValueError):
        load_targets(out_of_range)
    partial = tmp_path / "partial.json"
    partial.write_text(json.dumps({"receiving": {"target_percent": 88}, "bogus": {"target_percent": 1}}), encoding="utf-8")
    assert load_targets(partial)["receiving"] == {"target_percent": 88.0, "goal_percent": None}


def test_section_validation_rejects_bad_targets_and_saved_days_get_the_current_marks():
    import copy

    import pytest

    from operations_kpi_rollup.quality_charts import load_targets, normalize_stored_quality_charts, validate_quality_charts_section

    section = _section()
    validate_quality_charts_section(section)
    bad = copy.deepcopy(section)
    bad["targets"]["final"]["goal_percent"] = 50.0
    with pytest.raises(ValueError):
        validate_quality_charts_section(bad)
    bad = copy.deepcopy(section)
    bad["targets"].pop("receiving")
    with pytest.raises(ValueError):
        validate_quality_charts_section(bad)
    saved = copy.deepcopy(section)
    saved.pop("targets")
    validate_quality_charts_section(saved)
    normalized = normalize_stored_quality_charts({"quality_charts": saved})
    assert normalized["quality_charts"]["targets"] == load_targets()
    earlier = copy.deepcopy(section)
    earlier["method_version"] = "operations-kpi-quality-charts-v0"
    assert "targets" not in normalize_stored_quality_charts({"quality_charts": earlier})["quality_charts"]
    assert normalize_stored_quality_charts({"other": 1}) == {"other": 1}


def test_wallboard_draws_target_and_goal_lines_on_the_yield_charts():
    script = (SRC / "web" / "app.js").read_text(encoding="utf-8")
    assert "const marks = (section.targets || {})[metric.key] || {};" in script
    assert "'Target ' + markText(targetMark)" in script and "'Goal ' + markText(goalMark)" in script
    assert "color:palette.amber" in script and "color:palette.red" in script
    assert "references:[...markReferences(false)," in script and "references:[...markReferences(true)," in script
    assert script.count("targetAssessment:markAssessment") == 2
    assert "reference.tooltip || (reference.label" in script
    assert "no interim target or goal is set yet" not in script
    assert "The amber line is the target and the red line the goal" in script
