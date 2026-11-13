from pathlib import Path


ROOT = Path(__file__).parents[1]
OLD_HASH = "CB983D8F63982AB833019AEDD0D13067C644FD8231A25E8580B752BD36954714"
NEW_HASH = "4DFA932D94BF9CC9FF3991EA1787F95EEB43EFAF3B0B4559373734255ECE3ED9"


def test_metric_definition_migration_uses_physical_passes_and_requested_dates():
    sql = (ROOT / "sql/2026-11-13-align-metric-definitions.sql").read_text(encoding="utf-8")

    assert "CASE WHEN o.paint_pass_number > 1 THEN 1 ELSE 0 END AS is_repaint_loop" in sql
    assert "CASE WHEN o.paint_pass_number = 2 THEN 1 ELSE 0 END AS is_first_repaint_loop" in sql
    assert "SUM(p.is_initial_pass) AS ppy_approved" in sql
    assert "SUM(p.is_first_repaint_loop) AS paint_fty_repaint_count" in sql
    assert "COUNT(DISTINCT e.[Part ID]) AS receiving_quantity" in sql
    assert "COUNT(DISTINCT e.[Part ID]) AS final_quantity" in sql
    assert "MAX(CONVERT(date, e.AssembledDate)) AS report_date" in sql
    assert "LTRIM(RTRIM(CONVERT(nvarchar(255), e.Description))) = N''Chassis Fairing''" in sql
    assert OLD_HASH in sql
    assert NEW_HASH in sql
    assert "ASTER_OPERATIONS_KPI_METRIC_DEFINITIONS_V1" in sql


def test_metric_definition_migration_has_exact_hash_gated_reverse():
    sql = (ROOT / "sql/2026-11-13-rollback-metric-definitions.sql").read_text(encoding="utf-8")

    assert NEW_HASH in sql
    assert OLD_HASH in sql
    assert "ASTER_OPERATIONS_KPI_METRIC_DEFINITIONS_ROLLBACK_V1" in sql
