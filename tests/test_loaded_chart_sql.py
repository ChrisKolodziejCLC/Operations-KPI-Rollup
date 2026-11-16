from pathlib import Path


ROOT = Path(__file__).parents[1]
FORWARD = ROOT / "sql" / "2026-11-16-add-loaded-chart-series.sql"
ROLLBACK = ROOT / "sql" / "2026-11-16-rollback-loaded-chart-series.sql"
SERVICE = ROOT / "deploy" / "operations-kpi-rollup.service"
OLD_HASH = "0B45A0737682B316113771E61A64F183EC04698FCEE48AF7F8B4CC94DABB7DC3"
NEW_HASH = "3293844115F1580DBEC0E39D0083125EB2F4517C31022E30CA54630A6F546E0A"
CURRENT_HASH = "C099469E8FC2F0C27A5B34B2A7D1AFEB27223CEA17148E0F05766D86698A57EB"


def test_forward_migration_is_hash_gated_and_apply_ready():
    sql = FORWARD.read_text(encoding="utf-8")

    assert "DECLARE @CommitChange bit = 1;" in sql
    assert f"DECLARE @ExpectedOldHash varchar(64) = '{OLD_HASH}';" in sql
    assert f"DECLARE @ExpectedNewHash varchar(64) = '{NEW_HASH}';" in sql
    assert "ASTER_OPERATIONS_KPI_LOADED_CHART_V1" in sql
    assert "IF @CommitChange = 1" in sql
    assert "ROLLBACK TRANSACTION" in sql


def test_loaded_chart_reuses_aggregate_temp_tables_and_zero_fills_buckets():
    sql = FORWARD.read_text(encoding="utf-8")

    assert "h.moment_at AS loaded_at" in sql
    assert "FROM #LoadedEvents AS le" in sql
    assert "INNER JOIN #LoadedCartClasses AS lc" in sql
    assert "LEFT JOIN #DailyMetrics AS m" in sql
    assert "WHERE bucket_number < 23" in sql
    assert "DATEADD(day, -29, @ReportDate)" in sql
    assert "COUNT(*) AS parts_loaded" in sql
    assert "DATEPART(hour, MIN(le.loaded_at)) AS bucket_number" in sql
    assert "N''HOUR'' AS grain" in sql
    assert "N''DAY'' AS grain" in sql


def test_chart_contract_does_not_shift_existing_result_sets_or_expose_detail():
    sql = FORWARD.read_text(encoding="utf-8")

    assert "DECLARE @ChartInsertMarker nvarchar(max) = N'    DROP TABLE #PeriodMetrics;'" in sql
    assert "@ChartBlock + @ChartInsertMarker" in sql
    assert "SELECT\n        N''HOUR'' AS grain" in sql
    assert "bucket_start" in sql


def test_reverse_migration_restores_the_exact_prior_hash():
    sql = ROLLBACK.read_text(encoding="utf-8")

    assert "DECLARE @CommitChange bit = 1;" in sql
    assert f"DECLARE @ExpectedOldHash varchar(64) = '{NEW_HASH}';" in sql
    assert f"DECLARE @ExpectedNewHash varchar(64) = '{OLD_HASH}';" in sql
    assert "ASTER_OPERATIONS_KPI_LOADED_CHART_ROLLBACK_V1" in sql
    assert "Dashboard loaded-chart rollback hash mismatch." in sql


def test_loaded_chart_migration_does_not_write_qpts_business_rows():
    sql = FORWARD.read_text(encoding="utf-8").upper()

    assert "INSERT INTO" not in sql
    assert "UPDATE " not in sql
    assert "DELETE " not in sql
    assert "MERGE " not in sql


def test_service_pins_the_current_definition_hash():
    unit = SERVICE.read_text(encoding="utf-8")

    assert f"Environment=KPI_SQL_PROCEDURE_HASH={CURRENT_HASH}" in unit
