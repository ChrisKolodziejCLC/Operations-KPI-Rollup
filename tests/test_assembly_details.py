"""Assembly counts by operator and workstation: section, SQL migrations, ODBC call, drill-down wiring, and operator privacy."""

from __future__ import annotations

import base64
import copy
import hashlib
import http.client
import json
import re
import threading
from datetime import date, timedelta
from pathlib import Path

import pytest

import operations_kpi_rollup.drilldown as drilldown_module
from operations_kpi_rollup import odbc
from operations_kpi_rollup.assembly_details import (
    METHOD_VERSION,
    OPERATORS_HIDDEN_NOTE,
    assembly_details_section,
    redact_assembly_operators,
    unavailable_section,
    validate_assembly_details_section,
)
from operations_kpi_rollup.drilldown import DrilldownState
from operations_kpi_rollup.restricted import RestrictedContractError, validate_restricted_snapshot
from operations_kpi_rollup.web import AppState, create_auth_server, create_server
from operations_kpi_rollup.windows_auth import AuthSettings

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "2026-09-16.json"
PROCEDURE = ROOT / "sql/procedures/usp_QPTS_GetOperationsAssemblyDetails.sql"
REPORT_DATE = date(2026, 11, 18)
CHART_START = date(2026, 8, 23)
ALLOWED = "ChrisKolodziej@ELITEENTERPRISESINC.COM"


def _result_sets(report_date=REPORT_DATE):
    chart_start = report_date - timedelta(days=(report_date.weekday() + 1) % 7) - timedelta(weeks=12)
    meta = {
        "method_version": METHOD_VERSION, "report_date": report_date.isoformat(), "week_start": "ignored",
        "chart_start": chart_start.isoformat(), "fact_rows": 1071, "blank_operator_rows": 126, "blank_workstation_rows": 0,
    }
    operators, stations = [], []
    day = chart_start
    while day <= report_date:
        if day.weekday() < 5:
            stamp = day.isoformat()
            operators += [
                {"bucket_start": stamp, "operator": "op.alpha", "pieces": 10, "bumpers": 2},
                {"bucket_start": stamp, "operator": "op.bravo", "pieces": 5, "bumpers": 0},
                {"bucket_start": stamp, "operator": None, "pieces": 2, "bumpers": 0},
            ]
            stations += [
                {"bucket_start": stamp, "workstation": "CLC07-A1", "pieces": 9, "bumpers": 0},
                {"bucket_start": stamp, "workstation": "CLC07-B1", "pieces": 6, "bumpers": 0},
                {"bucket_start": stamp, "workstation": "CLC07-BMPR1", "pieces": 2, "bumpers": 2},
            ]
        day += timedelta(days=1)
    return [{"index": 0, "rows": [meta]}, {"index": 1, "rows": operators}, {"index": 2, "rows": stations}]


def _section(report_date=REPORT_DATE):
    return assembly_details_section(_result_sets(report_date), report_date)


def _base_snapshot():
    return {
        "contract_version": "2.0", "classification": "restricted-operational",
        "scope": {"method_version": "operations-kpi-restricted-v2", "history_start": "2026-09-08", "contains_named_people": False,
                  "contains_employee_ids": True, "contains_part_level_detail": True, "public_wallboard_compatible": False},
        "report_date": "2026-11-18", "generated_at": "2026-11-18T11:59:00-05:00",
        "painter_daily": [], "repaint": {"contributions": [], "details": []}, "finesse": {"summary": [], "details": []},
    }


def test_section_counts_operators_and_workstations_for_the_day_and_13_weeks():
    section = _section()
    assert section["available"] is True and section["method_version"] == METHOD_VERSION
    assert section["chart_start"] == CHART_START.isoformat() and section["weeks"][0] == "2026-08-23" and section["weeks"][-1] == "2026-11-15"
    assert len(section["weeks"]) == 13 and section["operators_visible"] is True and section["fact_rows"] == 1071
    assert section["totals"]["day"] == {"pieces": 17, "bumpers": 2}
    assert section["totals"]["weeks"][-1] == {"pieces": 51, "bumpers": 6} and section["totals"]["weeks"][0] == {"pieces": 85, "bumpers": 10}
    assert [item["key"] for item in section["operators"]] == ["op.alpha", "op.bravo", None]
    alpha = section["operators"][0]
    assert alpha["day"] == {"pieces": 10, "bumpers": 2}
    assert alpha["weeks"][-1] == {"pieces": 30, "bumpers": 6, "days": 3} and alpha["weeks"][0] == {"pieces": 50, "bumpers": 10, "days": 5}
    assert alpha["total"] == {"pieces": 630, "bumpers": 126, "days": 63, "daily_average": 10.0}
    assert section["operators"][2]["total"]["pieces"] == 126 and section["operators"][2]["key"] is None
    assert [item["key"] for item in section["work_centers"]] == ["CLC07-A1", "CLC07-B1", "CLC07-BMPR1"]
    assert section["work_centers"][2]["total"]["bumpers"] == 126 and section["work_centers"][0]["total"]["bumpers"] == 0
    validate_assembly_details_section(section)


def test_an_entity_with_no_work_on_the_report_day_still_reports_its_13_weeks():
    result = _result_sets()
    result[1]["rows"] = [row for row in result[1]["rows"] if not (row["operator"] == "op.bravo" and row["bucket_start"] == "2026-11-18")]
    result[2]["rows"] = [row for row in result[2]["rows"] if not (row["workstation"] == "CLC07-B1" and row["bucket_start"] == "2026-11-18")]
    for row in result[2]["rows"]:
        if row["bucket_start"] == "2026-11-18" and row["workstation"] == "CLC07-A1":
            row["pieces"] = 4
    for row in result[1]["rows"]:
        if row["bucket_start"] == "2026-11-18" and row["operator"] == "op.alpha":
            row["pieces"] = 6  # 6 pieces: 4 at CLC07-A1 and 2 bumpers at CLC07-BMPR1, so both groupings add up
            row["bumpers"] = 2
        if row["bucket_start"] == "2026-11-18" and row["operator"] is None:
            row["pieces"] = 0
    section = assembly_details_section(result, REPORT_DATE)
    bravo = next(item for item in section["operators"] if item["key"] == "op.bravo")
    assert bravo["day"] == {"pieces": 0, "bumpers": 0} and bravo["weeks"][-1]["days"] == 2


def test_operator_and_workstation_counts_must_add_up():
    drifted = _result_sets()
    drifted[1]["rows"].pop()
    with pytest.raises(ValueError, match="do not add up"):
        assembly_details_section(drifted, REPORT_DATE)


def test_section_rejects_wrong_date_method_chart_start_range_and_counts():
    wrong_date = _result_sets()
    wrong_date[0]["rows"][0]["report_date"] = "2026-11-17"
    with pytest.raises(ValueError, match="requested report date"):
        assembly_details_section(wrong_date, REPORT_DATE)
    wrong_method = _result_sets()
    wrong_method[0]["rows"][0]["method_version"] = "other"
    with pytest.raises(ValueError, match="method version"):
        assembly_details_section(wrong_method, REPORT_DATE)
    wrong_start = _result_sets()
    wrong_start[0]["rows"][0]["chart_start"] = "2026-08-30"
    with pytest.raises(ValueError, match="chart start"):
        assembly_details_section(wrong_start, REPORT_DATE)
    outside = _result_sets()
    outside[1]["rows"].append({"bucket_start": "2026-11-19", "operator": "op.alpha", "pieces": 1, "bumpers": 0})
    with pytest.raises(ValueError, match="outside the 13 weeks"):
        assembly_details_section(outside, REPORT_DATE)
    negative = _result_sets()
    negative[2]["rows"][0]["pieces"] = -1
    with pytest.raises(ValueError, match="negative"):
        assembly_details_section(negative, REPORT_DATE)
    too_many = _result_sets()
    too_many[1]["rows"][0]["bumpers"] = 99
    with pytest.raises(ValueError, match="more bumpers than pieces"):
        assembly_details_section(too_many, REPORT_DATE)
    with pytest.raises(ValueError, match="no metadata"):
        assembly_details_section([{"index": 0, "rows": []}], REPORT_DATE)


def test_validator_rejects_unexpected_fields_totals_and_shapes():
    section = _section()
    section["operators"][0]["login"] = "x"
    with pytest.raises(ValueError, match="unexpected fields"):
        validate_assembly_details_section(section)
    section = _section()
    section["extra"] = 1
    with pytest.raises(ValueError, match="unexpected fields"):
        validate_assembly_details_section(section)
    section = _section()
    section["work_centers"][0]["total"]["daily_average"] = 99.0
    with pytest.raises(ValueError, match="daily_average"):
        validate_assembly_details_section(section)
    section = _section()
    section["weeks"][0], section["weeks"][1] = section["weeks"][1], section["weeks"][0]
    with pytest.raises(ValueError, match="13 consecutive Sunday-start weeks"):
        validate_assembly_details_section(section)
    section = _section()
    section["operators"][0]["weeks"][3]["days"] = 8
    with pytest.raises(ValueError):
        validate_assembly_details_section(section)
    section = _section()
    section["operators"][1]["key"] = "op.alpha"
    with pytest.raises(ValueError, match="twice"):
        validate_assembly_details_section(section)
    section = _section()
    section["totals"]["day"]["pieces"] += 1
    with pytest.raises(ValueError, match="do not add up"):
        validate_assembly_details_section(section)


def test_unavailable_section_validates_and_redaction_leaves_it_alone():
    section = unavailable_section("not deployed")
    validate_assembly_details_section(section)
    snapshot = {"assembly": section}
    assert redact_assembly_operators(snapshot) == snapshot


def test_redaction_removes_only_the_operator_rows_and_validates():
    snapshot = _base_snapshot()
    snapshot["assembly"] = _section()
    original = copy.deepcopy(snapshot)
    view = redact_assembly_operators(snapshot)
    assert snapshot == original  # the stored snapshot is not touched
    assert view["assembly"]["operators"] == [] and view["assembly"]["operators_visible"] is False
    assert view["assembly"]["operators_note"] == OPERATORS_HIDDEN_NOTE
    assert view["assembly"]["work_centers"] == snapshot["assembly"]["work_centers"]
    validate_assembly_details_section(view["assembly"])
    assert "op.alpha" not in json.dumps(view) and "op.bravo" not in json.dumps(view)
    leaked = copy.deepcopy(view["assembly"])
    leaked["operators"] = snapshot["assembly"]["operators"]
    with pytest.raises(ValueError, match="empty with the sign-in note"):
        validate_assembly_details_section(leaked)


def test_restricted_snapshot_accepts_and_checks_the_assembly_section():
    snapshot = _base_snapshot()
    validate_restricted_snapshot(snapshot)
    snapshot["assembly"] = _section()
    validate_restricted_snapshot(snapshot)
    snapshot["assembly"]["work_centers"][0]["day"]["pieces"] += 5
    with pytest.raises(RestrictedContractError, match="assembly section is invalid"):
        validate_restricted_snapshot(snapshot)
    snapshot["assembly"] = unavailable_section("could not be read")
    validate_restricted_snapshot(snapshot)


def test_execute_assembly_details_needs_a_pinned_hash_and_uses_a_guarded_batch(monkeypatch):
    captured = {}

    def fake(query, wanted, credential_name):
        captured.update(query=query, wanted=wanted, credential=credential_name)
        return ["ok"]

    monkeypatch.setattr(odbc, "execute_result_sets", fake)
    monkeypatch.delenv("KPI_ASSEMBLY_DETAILS_PROCEDURE_HASH", raising=False)
    with pytest.raises(odbc.OdbcError, match="must pin"):
        odbc.execute_assembly_details(REPORT_DATE)
    monkeypatch.setenv("KPI_ASSEMBLY_DETAILS_PROCEDURE_HASH", "ef" * 32)
    assert odbc.execute_assembly_details(REPORT_DATE) == ["ok"]
    query = captured["query"]
    assert query.startswith("SET NOCOUNT ON;") and "THROW 51007" in query and ("EF" * 32) in query
    assert "EXEC dbo.usp_QPTS_GetOperationsAssemblyDetails @ReportDateOverride = '2026-11-18';" in query
    assert captured["wanted"] == {0, 1, 2} and captured["credential"] == "operations-kpi-qpts-ro"


def test_drilldown_attaches_assembly_details_only_when_pinned_and_never_blocks(monkeypatch, tmp_path):
    monkeypatch.delenv("KPI_ASSEMBLY_DETAILS_PROCEDURE_HASH", raising=False)
    assert drilldown_module._assembly_details_for_snapshot(REPORT_DATE) is None
    monkeypatch.setenv("KPI_ASSEMBLY_DETAILS_PROCEDURE_HASH", "ef" * 32)
    monkeypatch.setattr(drilldown_module, "execute_assembly_details", lambda report_date: _result_sets())
    monkeypatch.setattr(drilldown_module, "execute_standard_drilldown", lambda report_date: [])
    monkeypatch.setattr(drilldown_module, "build_restricted_snapshot", lambda report_date, sets: _base_snapshot())
    state = DrilldownState("fixture", tmp_path / "drilldown", tmp_path / "unused.json")
    snapshot = state._fetch_live(REPORT_DATE)
    assert snapshot["assembly"]["available"] is True and snapshot["assembly"]["totals"]["day"]["pieces"] == 17

    def broken(report_date):
        raise RuntimeError("boom with secret detail")

    monkeypatch.setattr(drilldown_module, "execute_assembly_details", broken)
    snapshot = state._fetch_live(REPORT_DATE)
    assert snapshot["assembly"]["available"] is False and "RuntimeError" in snapshot["assembly"]["reason"] and "secret" not in snapshot["assembly"]["reason"]
    monkeypatch.delenv("KPI_ASSEMBLY_DETAILS_PROCEDURE_HASH")
    assert "assembly" not in state._fetch_live(REPORT_DATE)


def _drilldown_state(tmp_path):
    snapshot = _base_snapshot()
    snapshot["assembly"] = _section()
    fixture = tmp_path / "drilldown-fixture.json"
    fixture.write_text(json.dumps(snapshot), encoding="utf-8")
    return DrilldownState("fixture", tmp_path / "snapshots" / "drilldown", fixture)


def _get(port, path, headers=None):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    connection.request("GET", path, headers=headers or {})
    response = connection.getresponse()
    body = response.read()
    result = (response.status, {key.lower(): value for key, value in response.getheaders()}, body)
    connection.close()
    return result


def test_the_open_port_never_serves_operator_rows(tmp_path):
    drilldown = _drilldown_state(tmp_path)
    server = create_server("127.0.0.1", 0, AppState("fixture", tmp_path / "snapshots", EXAMPLE), drilldown)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, _, body = _get(server.server_address[1], "/api/drilldown/snapshot")
        assert status == 200
        served = json.loads(body)
        assert served["assembly"]["operators"] == [] and served["assembly"]["operators_visible"] is False
        assert served["assembly"]["operators_note"] == OPERATORS_HIDDEN_NOTE
        assert [item["key"] for item in served["assembly"]["work_centers"]] == ["CLC07-A1", "CLC07-B1", "CLC07-BMPR1"]
        assert b"op.alpha" not in body and b"op.bravo" not in body
        assert drilldown.snapshot()["assembly"]["operators_visible"] is True  # the stored snapshot keeps them
    finally:
        server.shutdown()
        server.server_close()


class _Acceptor:
    def accept(self, token: bytes):
        if token == b"allowed":
            return ALLOWED, b"mutual-reply"
        raise RuntimeError("bad ticket")


def test_the_sign_in_listener_serves_operator_rows_to_an_allowlisted_session(tmp_path):
    allowlist = tmp_path / "allowed.json"
    allowlist.write_text(json.dumps({"version": 1, "principals": [{"sam": "ChrisKolodziej", "name": "ChrisKolodziej"}]}), encoding="utf-8")
    settings = AuthSettings(port=0, bind_host="127.0.0.1", keytab=tmp_path / "http.keytab", tls_cert=tmp_path / "c.pem", tls_key=tmp_path / "k.pem",
                            allowlist=allowlist, service_principal="HTTP/kpi.example.test@EXAMPLE.TEST")
    drilldown = _drilldown_state(tmp_path)
    server = create_auth_server(settings, AppState("fixture", tmp_path / "snapshots", EXAMPLE), drilldown, acceptor=_Acceptor(), roster=None, tls=False)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        status, _, _ = _get(port, "/api/drilldown/snapshot")
        assert status == 401  # no session, nothing served
        status, headers, _ = _get(port, "/api/session", {"Authorization": "Negotiate " + base64.b64encode(b"allowed").decode("ascii")})
        assert status == 200
        cookie = headers["set-cookie"].split(";", 1)[0]
        status, _, body = _get(port, "/api/drilldown/snapshot", {"Cookie": cookie})
        assert status == 200
        served = json.loads(body)
        assert served["assembly"]["operators_visible"] is True
        assert [item["key"] for item in served["assembly"]["operators"]] == ["op.alpha", "op.bravo", None]
    finally:
        server.shutdown()
        server.server_close()


def test_assembly_details_migrations_are_hash_gated_and_reversible():
    definition = PROCEDURE.read_text(encoding="utf-8")
    digest = hashlib.sha256(definition.encode("utf-16-le")).hexdigest().upper()
    forward = (ROOT / "sql/2026-11-23-add-operations-assembly-details.sql").read_text(encoding="utf-8")
    rollback = (ROOT / "sql/2026-11-23-rollback-operations-assembly-details.sql").read_text(encoding="utf-8")
    assert f"@ExpectedHash varchar(64) = '{digest}'" in forward and f"@ExpectedHash varchar(64) = '{digest}'" in rollback
    assert "refusing to replace it" in forward and "DATABASE_PRINCIPAL_ID(N'OperationsKpiRollup_RO')" in forward
    assert forward.count("GRANT ") == 2 and "VIEW DEFINITION" in forward and "TO [OperationsKpiRollup_RO]" in forward
    assert "DROP PROCEDURE dbo.usp_QPTS_GetOperationsAssemblyDetails;" in rollback and "refusing to drop" in rollback
    assert "DECLARE @CommitChange bit = 1;" in forward and "DECLARE @CommitChange bit = 1;" in rollback
    reviewed = re.search(r"DECLARE @ReviewedDefinition nvarchar\(max\) = N'(.*?)';\nDECLARE @ReviewedHash", forward, re.S).group(1)
    assert reviewed.replace("''", "'") == definition
    assert "operations-kpi-assembly-details-v1" in definition and "READ UNCOMMITTED" in definition
    for banned in ("INSERT ", "UPDATE ", "DELETE ", "MERGE ", "TRUNCATE ", "ALTER TABLE", "DROP TABLE DBO."):
        assert banned not in definition.upper().replace("DROP TABLE #", "")
    unit = (ROOT / "deploy/operations-kpi-rollup.service").read_text(encoding="utf-8")
    assert f"KPI_ASSEMBLY_DETAILS_PROCEDURE_HASH={digest}" in unit
    throws = set(re.findall(r"THROW (\d+)", forward + rollback))
    others = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "sql").glob("*.sql") if "assembly-details" not in path.name)
    assert throws.isdisjoint(set(re.findall(r"THROW (\d+)", others)))


def test_assembly_details_procedure_uses_the_reviewed_filters_and_the_two_login_columns():
    definition = PROCEDURE.read_text(encoding="utf-8")
    chart = (ROOT / "sql/procedures/usp_QPTS_GetOperationsAssemblyCharts.sql").read_text(encoding="utf-8")
    for rule in (
        "ISNULL(e.Model, N'') <> N'Service'",
        "CASE WHEN LTRIM(CONVERT(nvarchar(255), e.[Part Number])) LIKE N'N71-6171%' THEN 1 ELSE 0 END AS is_bumper",
        "e.AssembledDate >= @ChartStartAt",
        "e.AssembledDate < @WindowEndExclusive",
    ):
        assert rule in definition and rule in chart
    assert "e.AssembledLogin" in definition and "e.GPAssyLogin" in definition
    assert "NULLIF(LTRIM(RTRIM(CONVERT(nvarchar(100), e.AssembledLogin))), N'') AS operator" in definition
    assert "NULLIF(LTRIM(RTRIM(CONVERT(nvarchar(100), e.GPAssyLogin))), N'') AS workstation" in definition
    assert "DROP TABLE #AssemblyScans;" in definition and definition.count("COUNT(DISTINCT part_id)") == 2


def test_drilldown_page_has_an_assembly_panel_wired_to_the_snapshot_section():
    page = (ROOT / "src/operations_kpi_rollup/drilldown_web/index.html").read_text(encoding="utf-8")
    script = (ROOT / "src/operations_kpi_rollup/drilldown_web/app.js").read_text(encoding="utf-8")
    css = (ROOT / "src/operations_kpi_rollup/drilldown_web/styles.css").read_text(encoding="utf-8")
    for element in (
        "assembly-kpis", "assembly-day-work-centers", "assembly-day-operators", "assembly-trend-work-centers",
        "assembly-trend-operators", "assembly-footnote", "assembly-work-center-table", "assembly-operator-table",
        "assembly-operator-wrap", "assembly-operator-note",
    ):
        assert 'id="' + element + '"' in page
        assert "#" + element in script
    assert "Assembly production" in page and "By work center" in page and "By operator" in page
    assert "renderAssembly(view);" in script and "function renderAssembly(snapshot)" in script
    assert "snapshot.assembly" in script and "section.operators_visible" in script and "section.operators_note" in script
    assert "No operator recorded" in script and "No work center recorded" in script
    assert "Assembly counts are not available for this snapshot." in script
    assert ".assembly-table" in css and ".table-wrap[hidden]" in css
    assert "?v=0.47.0-assembly-r1" in page and "0.38.0-chart-clarity-r1" not in page


def test_drilldown_assembly_panel_shows_counts_only_and_no_assembly_time():
    script = (ROOT / "src/operations_kpi_rollup/drilldown_web/app.js").read_text(encoding="utf-8")
    block = script[script.index("// ---------- assembly production"):script.index("function render(snapshot)")]
    for column in ("Selected day", "Bumpers (day)", "13-wk pieces", "13-wk bumpers", "Days active", "Avg / active day"):
        assert column in block
    lowered = block.lower()
    for banned in ("build time", "minutes", "assembly time:", "start_time", "duration"):
        assert banned not in lowered.replace("no assembly time is shown yet", "").replace("not when a build started", "")
    assert "not when a build started" in block
    assert "operators_visible" in block and "operators_note" in block
    # Operator logins are shown exactly as recorded: the roster name lookup does not cover them.
    names = script[script.index("function snapshotIds(snapshot)"):script.index("async function loadNames")]
    assert "assembly" not in names


def _saved_day_without_assembly(tmp_path):
    directory = tmp_path / "drilldown"
    state = DrilldownState("live", directory)
    old = _base_snapshot()
    state._persist(old)
    state._remember(old)
    return state, old


def test_a_saved_day_without_assembly_counts_is_rebuilt_once_the_procedure_is_pinned(monkeypatch, tmp_path):
    state, old = _saved_day_without_assembly(tmp_path)
    monkeypatch.delenv("KPI_ASSEMBLY_DETAILS_PROCEDURE_HASH", raising=False)
    assert state.snapshot(REPORT_DATE)["report_date"] == REPORT_DATE.isoformat()  # feature off: the saved copy is served as before
    monkeypatch.setenv("KPI_ASSEMBLY_DETAILS_PROCEDURE_HASH", "ab" * 32)
    assert state.snapshot(REPORT_DATE) is None  # pinned: treated as not saved, so the page builds the day on demand
    assert state.snapshot() is not None  # the latest-snapshot view (health) is untouched
    rebuilt = copy.deepcopy(old)
    rebuilt["assembly"] = _section()
    monkeypatch.setattr(state, "_fetch_live", lambda report_date: rebuilt)
    fresh = state.refresh(REPORT_DATE)  # a past day: no force needed, the missing section is what triggers the build
    assert fresh["assembly"]["available"] is True
    assert state.snapshot(REPORT_DATE)["assembly"]["available"] is True  # served from memory now, no second build
    assert len(list((tmp_path / "drilldown").glob(REPORT_DATE.isoformat() + "__*.json"))) == 2  # the older saved file is kept


def test_a_failed_assembly_build_is_stored_as_unavailable_and_never_rebuilt_in_a_loop(monkeypatch, tmp_path):
    state, old = _saved_day_without_assembly(tmp_path)
    monkeypatch.setenv("KPI_ASSEMBLY_DETAILS_PROCEDURE_HASH", "ab" * 32)
    calls = []

    def build(report_date):
        calls.append(report_date)
        snapshot = copy.deepcopy(old)
        snapshot["assembly"] = unavailable_section("The assembly-details procedure could not be read (RuntimeError).")
        return snapshot

    monkeypatch.setattr(state, "_fetch_live", build)
    state.refresh(REPORT_DATE)
    state.refresh(REPORT_DATE)
    assert calls == [REPORT_DATE]
    assert state.snapshot(REPORT_DATE)["assembly"]["available"] is False


def test_drilldown_panel_tells_the_viewer_how_to_fill_a_saved_day_that_predates_the_counts():
    script = (ROOT / "src/operations_kpi_rollup/drilldown_web/app.js").read_text(encoding="utf-8")
    assert "This saved day predates the assembly counts. Refresh it to build them." in script
    block = script[script.index("function renderAssembly(snapshot)"):script.index("function render(snapshot)")]
    assert "const saved = snapshot.assembly;" in block and "!saved ? ASSEMBLY_PREDATES" in block and "saved.reason" in block
