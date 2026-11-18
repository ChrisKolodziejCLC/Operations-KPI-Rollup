import hashlib
import re
from pathlib import Path


ROOT = Path(__file__).parents[1]
FORWARD = ROOT / "sql" / "2026-11-18-add-aggregate-color-demand-details.sql"
ROLLBACK = ROOT / "sql" / "2026-11-18-rollback-aggregate-color-demand-details.sql"
SERVICE = ROOT / "deploy" / "operations-kpi-rollup.service"
OLD_HASH = "DA67E4A283C8317CC69B750B2D6636B1F76F9B6F46FF990591E82F1CA88FDD33"
NEW_HASH = "C61C9D839DCA1E82EE45186A9D0179110CB141C6A5B3C40D1213015332AD1608"
CURRENT_HASH = "08686EB3D38855BAEB6CA1E5760CD3467B58311E1B5BA4C7F502241CF8191D28"


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


def test_forward_migration_is_hash_gated_and_apply_ready():
    sql = FORWARD.read_text(encoding="utf-8")

    assert "DECLARE @CommitChange bit = 1;" in sql
    assert f"DECLARE @ExpectedOldHash varchar(64) = '{OLD_HASH}';" in sql
    assert f"DECLARE @ExpectedNewHash varchar(64) = '{NEW_HASH}';" in sql
    assert "BEGIN TRANSACTION;" in sql
    assert "EXEC sys.sp_executesql @CandidateDefinition;" in sql
    assert "ROLLBACK TRANSACTION" in sql
    assert _definition_hash(_reviewed_definition(sql)) == NEW_HASH


def test_result_set_14_adds_only_aggregate_color_and_demand_fields():
    sql = FORWARD.read_text(encoding="utf-8")

    assert "COUNT(DISTINCT le.color_key) AS unique_colors" in sql
    assert "COUNT(DISTINCT pe.color_key) AS unique_colors" in sql
    assert "StagedColorTotals AS" in sql
    assert "unique_colors," in sql
    assert "pieces_scheduled" in sql
    assert "ORDER BY metric_key, grain DESC, bucket_start" in sql


def test_result_set_15_is_aggregate_only_and_keeps_identifiers_internal():
    sql = FORWARD.read_text(encoding="utf-8")

    for detail_key in (
        "painted_weekly_unique_colors",
        "loaded_color_part_counts",
        "loaded_cart_size_distribution",
    ):
        assert f"N''{detail_key}''" in sql
    assert "DATEADD(day, -84, @WeekStart)" in sql
    assert "w.week_start < @HistoryStart THEN NULL" in sql
    assert "DATEADD(day, 6, w.week_start) > @ReportDate" in sql

    from_marker = "\n    FROM AggregateDetailRows"
    from_at = sql.index(from_marker)
    select_marker = "\n    SELECT\n"
    select_at = sql.rindex(select_marker, 0, from_at)
    columns = sql[select_at + len(select_marker):from_at]
    assert [part.strip().rstrip(",") for part in columns.splitlines()] == [
        "detail_key",
        "metric_key",
        "bucket_start",
        "bucket_end",
        "label",
        "value_count",
        "data_available",
        "is_partial",
    ]
    for forbidden in ("part_id", "PaintCart_ID", "employee", "DriverLog"):
        assert forbidden not in columns


def test_forward_procedure_writes_only_to_temp_tables():
    definition = _reviewed_definition(FORWARD.read_text(encoding="utf-8"))
    targets = re.findall(
        r"\b(?:INSERT\s+(?:INTO\s+)?|UPDATE\s+|DELETE\s+FROM\s+|MERGE\s+)([#@\w.\[\]]+)",
        definition,
        flags=re.IGNORECASE,
    )
    assert targets
    assert all(target.startswith("#") for target in targets), targets


def test_reverse_migration_restores_exact_prior_definition():
    sql = ROLLBACK.read_text(encoding="utf-8")

    assert "DECLARE @CommitChange bit = 1;" in sql
    assert f"DECLARE @ExpectedOldHash varchar(64) = '{NEW_HASH}';" in sql
    assert f"DECLARE @ExpectedNewHash varchar(64) = '{OLD_HASH}';" in sql
    assert "BEGIN TRANSACTION;" in sql
    assert "ROLLBACK TRANSACTION" in sql
    assert _definition_hash(_reviewed_definition(sql)) == OLD_HASH


def test_service_has_advanced_beyond_aggregate_detail_definition_hash():
    unit = SERVICE.read_text(encoding="utf-8")
    assert f"Environment=KPI_SQL_PROCEDURE_HASH={CURRENT_HASH}" in unit
    assert f"Environment=KPI_SQL_PROCEDURE_HASH={NEW_HASH}" not in unit
