from pathlib import Path


ROOT = Path(__file__).parents[1]
FORWARD = ROOT / "sql" / "2026-11-16-refine-loaded-13-week-trends.sql"
ROLLBACK = ROOT / "sql" / "2026-11-16-rollback-loaded-13-week-trends.sql"
OLD_HASH = "3293844115F1580DBEC0E39D0083125EB2F4517C31022E30CA54630A6F546E0A"
NEW_HASH = "C099469E8FC2F0C27A5B34B2A7D1AFEB27223CEA17148E0F05766D86698A57EB"
PENDING_HASH = "PENDING_V20_CANDIDATE_SHA256"


def test_v20_forward_is_hash_gated_and_pinned():
    sql = FORWARD.read_text(encoding="utf-8")

    assert "DECLARE @CommitChange bit = 1;" in sql
    assert f"DECLARE @ExpectedOldHash varchar(64) = '{OLD_HASH}';" in sql
    assert f"DECLARE @ExpectedNewHash varchar(64) = '{NEW_HASH}';" in sql
    assert f"DECLARE @PendingHash varchar(64) = '{PENDING_HASH}';" in sql
    assert "@CommitChange = 1 AND @ExpectedNewHash = @PendingHash" in sql
    assert "ROLLBACK TRANSACTION" in sql
    unit = (ROOT / "deploy" / "operations-kpi-rollup.service").read_text(encoding="utf-8")
    assert f"Environment=KPI_SQL_PROCEDURE_HASH={NEW_HASH}" in unit


def test_v20_extends_only_the_aggregate_chart_window_and_marks_represented_days():
    sql = FORWARD.read_text(encoding="utf-8")

    assert "SELECT DATEADD(day, -84, @WeekStart) AS report_date" in sql
    assert "OPTION (MAXRECURSION 90)" in sql
    assert "AS represented_day" in sql
    assert "COALESCE(m.parts_loaded, 0) > 0" in sql
    assert "COALESCE(m.paint_processed, 0) > 0" in sql
    assert "COALESCE(m.parts_shipped, 0) > 0" in sql
    assert "COALESCE(m.parts_assembled, 0) > 0" in sql
    assert "DROP TABLE #PeriodMetrics" not in sql
    assert "@ChartBlock" not in sql


def test_v20_rollback_restores_v19_shape_and_hash():
    sql = ROLLBACK.read_text(encoding="utf-8")

    assert f"DECLARE @ExpectedOldHash varchar(64) = '{NEW_HASH}';" in sql
    assert f"DECLARE @ExpectedNewHash varchar(64) = '{OLD_HASH}';" in sql
    assert "SELECT DATEADD(day, -29, @ReportDate) AS report_date" in sql
    assert "OPTION (MAXRECURSION 29)" in sql
    assert "ASTER_OPERATIONS_KPI_LOADED_13_WEEK_ROLLBACK_V1" in sql
    assert "rollback hash mismatch" in sql


def test_v20_migrations_do_not_write_qpts_business_rows():
    for path in (FORWARD, ROLLBACK):
        sql = path.read_text(encoding="utf-8").upper()
        assert "INSERT INTO" not in sql
        assert "UPDATE " not in sql
        assert "DELETE " not in sql
        assert "MERGE " not in sql
