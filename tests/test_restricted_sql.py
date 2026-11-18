import hashlib
import re
from pathlib import Path


ROOT = Path(__file__).parents[1]
BASE = ROOT / "sql" / "2026-11-18-add-aggregate-color-demand-details.sql"
FORWARD = ROOT / "sql" / "2026-11-18-add-restricted-kpi-drilldown.sql"
ROLLBACK = ROOT / "sql" / "2026-11-18-rollback-restricted-kpi-drilldown.sql"
OLD_HASH = "C61C9D839DCA1E82EE45186A9D0179110CB141C6A5B3C40D1213015332AD1608"
NEW_HASH = "420A87D4DFE5D8A20B4A8048BF51E4EAA7AAC30AD63D3D13C201B1BD61D9814A"
BEGIN_MARKER = "    /* RESTRICTED_DRILLDOWN_RESULT_SETS_BEGIN */"
END_MARKER = "    /* RESTRICTED_DRILLDOWN_RESULT_SETS_END */"
GATE_BEGIN = "    /* RESTRICTED_DRILLDOWN_LEGACY_PAINTER_GATE_BEGIN */"
GATE_END = "    /* RESTRICTED_DRILLDOWN_LEGACY_PAINTER_GATE_END */"


def _reviewed_definition(sql: str) -> str:
    match = re.search(
        r"DECLARE @ReviewedDefinition nvarchar\(max\) = N'(.*)';\nDECLARE @ReviewedHash",
        sql,
        flags=re.DOTALL,
    )
    assert match, "reviewed procedure definition was not found"
    return match.group(1).replace("''", "'")


def _definition_hash(definition: str) -> str:
    return hashlib.sha256(definition.encode("utf-16le")).hexdigest().upper()


def test_forward_migration_is_hash_gated_apply_ready_and_default_private_off():
    sql = FORWARD.read_text(encoding="utf-8")
    definition = _reviewed_definition(sql)

    assert "DECLARE @CommitChange bit = 1;" in sql
    assert f"DECLARE @ExpectedOldHash varchar(64) = '{OLD_HASH}';" in sql
    assert f"DECLARE @ExpectedNewHash varchar(64) = '{NEW_HASH}';" in sql
    assert "BEGIN TRANSACTION;" in sql
    assert "EXEC sys.sp_executesql @CandidateDefinition;" in sql
    assert "ROLLBACK TRANSACTION" in sql
    assert _definition_hash(definition) == NEW_HASH
    assert "@IncludeRestrictedDetail bit = 0" in definition
    assert "IF @IncludeRestrictedDetail = 1" in definition


def test_restricted_extension_is_additive_and_public_definition_is_otherwise_identical():
    base = _reviewed_definition(BASE.read_text(encoding="utf-8"))
    candidate = _reviewed_definition(FORWARD.read_text(encoding="utf-8"))

    legacy_start = base.index("    /* Painter performance at daily grain.")
    legacy_end = base.index("\n\n    /* Top three defect descriptions", legacy_start)
    legacy_result = base[legacy_start:legacy_end]

    gate_start = candidate.index(GATE_BEGIN)
    gate_end = candidate.index(GATE_END, gate_start) + len(GATE_END)
    without_gate = candidate[:gate_start] + legacy_result + candidate[gate_end:]

    start = without_gate.index(BEGIN_MARKER)
    end = without_gate.index(END_MARKER, start) + len(END_MARKER)
    without_restricted = without_gate[:start] + without_gate[end:]
    without_restricted = without_restricted.replace(
        "    @ReportDateOverride date = NULL,\n    @IncludeRestrictedDetail bit = 0\nAS",
        "    @ReportDateOverride date = NULL\nAS",
        1,
    )
    without_restricted = without_restricted.replace(
        "\n\n\n    /* Top three defect descriptions",
        "\n\n    /* Top three defect descriptions",
        1,
    )
    without_restricted = without_restricted.replace(
        "\n\n\n    DROP TABLE #PeriodMetrics;",
        "\n    DROP TABLE #PeriodMetrics;",
        1,
    )
    assert without_restricted == base


def test_restricted_results_are_separate_and_cover_the_governed_detail_shapes():
    definition = _reviewed_definition(FORWARD.read_text(encoding="utf-8"))
    block = definition[
        definition.index(BEGIN_MARKER) : definition.index(END_MARKER) + len(END_MARKER)
    ]

    for temp_table in (
        "#RestrictedPaintFacts",
        "#RestrictedPainterMinutes",
        "#RestrictedFinesseFacts",
    ):
        assert temp_table in block
    for required in (
        "painter_name",
        "booth_number",
        "parts_per_hour",
        "fty_percent",
        "contribution_percent",
        "repaint_loop_count",
        "defect_description",
        "worker_name",
        "minutes_per_part",
        "COUNT(DISTINCT part_id) AS part_count",
        "LEAD(h.moment_at) OVER",
        "s.next_started_at IS NULL OR h.moment_at < s.next_started_at",
        "N'repair_work_repaired'",
        "N'repair_work_wfp'",
    ):
        assert required in block
    assert "WHERE f.report_date = @ReportDate" in block
    assert "WHERE report_date = @ReportDate" in block


def test_public_result_set_eight_is_schema_only_and_returns_no_employee_rows():
    definition = _reviewed_definition(FORWARD.read_text(encoding="utf-8"))
    gate = definition[
        definition.index(GATE_BEGIN) : definition.index(GATE_END) + len(GATE_END)
    ]
    assert "IF @IncludeRestrictedDetail = 1" in gate
    assert "Preserve result-set index 8 without returning employee data" in gate
    assert "CONVERT(nvarchar(200), NULL) AS painter_name" in gate
    assert "WHERE 1 = 0;" in gate


def test_restricted_procedure_writes_only_to_temp_tables():
    definition = _reviewed_definition(FORWARD.read_text(encoding="utf-8"))
    targets = re.findall(
        r"\b(?:INSERT\s+(?:INTO\s+)?|UPDATE\s+|DELETE\s+FROM\s+|MERGE\s+)([#@\w.\[\]]+)",
        definition,
        flags=re.IGNORECASE,
    )
    assert targets
    assert all(target.startswith("#") for target in targets), targets


def test_reverse_migration_restores_exact_v33_definition():
    sql = ROLLBACK.read_text(encoding="utf-8")
    definition = _reviewed_definition(sql)

    assert "DECLARE @CommitChange bit = 1;" in sql
    assert f"DECLARE @ExpectedOldHash varchar(64) = '{NEW_HASH}';" in sql
    assert f"DECLARE @ExpectedNewHash varchar(64) = '{OLD_HASH}';" in sql
    assert "BEGIN TRANSACTION;" in sql
    assert "ROLLBACK TRANSACTION" in sql
    assert _definition_hash(definition) == OLD_HASH
    assert definition == _reviewed_definition(BASE.read_text(encoding="utf-8"))
    assert "@IncludeRestrictedDetail" not in definition
    assert BEGIN_MARKER not in definition
