from pathlib import Path


ROOT = Path(__file__).parents[1]
FORWARD = ROOT / "sql" / "2026-11-16-add-staged-painted-quality-chart-series.sql"
ROLLBACK = ROOT / "sql" / "2026-11-16-rollback-staged-painted-quality-chart-series.sql"
OLD_HASH = "A7365336FFFE5170A3D963D3C4599F158C97E29B2E01FFEBD3C59A4ED817285F"
NEW_HASH = "DA67E4A283C8317CC69B750B2D6636B1F76F9B6F46FF990591E82F1CA88FDD33"


def test_forward_extended_chart_migration_is_hash_gated_and_apply_ready():
    sql = FORWARD.read_text(encoding="utf-8")

    assert "DECLARE @CommitChange bit = 1;" in sql
    assert f"DECLARE @ExpectedOldHash varchar(64) = '{OLD_HASH}';" in sql
    assert f"DECLARE @ExpectedNewHash varchar(64) = '{NEW_HASH}';" in sql
    assert "ASTER_OPERATIONS_KPI_EXTENDED_CHARTS_V1" in sql
    assert "IF @CommitChange = 1" in sql
    assert "ROLLBACK TRANSACTION" in sql


def test_result_set_14_is_metric_keyed_and_aggregate_only():
    sql = FORWARD.read_text(encoding="utf-8")

    for metric in ("loaded", "staged", "painted", "repaint", "finesse"):
        assert f"N''{metric}''" in sql
    assert "N''HOUR'' AS grain" in sql
    assert "N''DAY''" in sql
    assert "quality_numerator" in sql
    assert "quality_denominator" in sql
    assert "ORDER BY metric_key, grain DESC, bucket_start" in sql
    assert "WHERE bucket_number < 23" in sql
    assert "DATEADD(day, -84, @WeekStart)" in sql


def test_staged_painted_and_quality_sources_reuse_governed_aggregates():
    sql = FORWARD.read_text(encoding="utf-8")

    assert "StagedCartGroups AS" in sql
    assert "COUNT_BIG(*) AS staged_carts" in sql
    assert "PaintedHourlyEvents AS" in sql
    assert "PaintedHourlyCartFirst AS" in sql
    assert "FROM #PaintExitEvents AS pe" in sql
    assert "FROM #PaintPasses AS p" in sql
    assert "FinesseReceivingHourly AS" in sql
    assert "FinessePaintHourly AS" in sql
    assert "COALESCE(a.paint_fty_repaint_count, 0), COALESCE(a.paint_fty_total, 0)" in sql
    assert "COALESCE(a.finesse_repair_count, 0) + COALESCE(a.paint_fty_repair_count, 0)" in sql
    assert "COALESCE(a.finesse_rejected_count, 0) + COALESCE(a.reject_fty_rejected_count, 0)" in sql


def test_extended_chart_migration_does_not_write_qpts_business_rows():
    sql = FORWARD.read_text(encoding="utf-8").upper()

    assert "INSERT INTO" not in sql
    assert "UPDATE " not in sql
    assert "DELETE " not in sql
    assert "MERGE " not in sql


def test_reverse_migration_restores_exact_v22_definition_hash():
    sql = ROLLBACK.read_text(encoding="utf-8")

    assert "DECLARE @CommitChange bit = 1;" in sql
    assert f"DECLARE @ExpectedOldHash varchar(64) = '{NEW_HASH}';" in sql
    assert f"DECLARE @ExpectedNewHash varchar(64) = '{OLD_HASH}';" in sql
    assert "ASTER_OPERATIONS_KPI_EXTENDED_CHARTS_ROLLBACK_V1" in sql
    assert "/* Aggregate loaded-chart series." in sql
    assert "N''staged''" not in sql
    assert "N''painted''" not in sql
