from pathlib import Path


ROOT = Path(__file__).parents[1]
OLD_HASH = "A425832E9F652F84E55401DD45E917A8D421132442BBBA3EE37FD5136F4B26F5"
NEW_HASH = "87B95E7AF33FCAE6F9FD3C9BC0D5F76D3E270ACDB1115A4E5E7C1F407A9D3422"


def test_master_repaintcount_yield_migration_is_hash_gated_and_uses_owner_sources():
    sql = (ROOT / "sql/2026-11-13-use-master-repaintcount-yields.sql").read_text(encoding="utf-8")

    assert "dbo.[Master Data Table]" in sql
    assert "m.RepaintCount" in sql
    assert "h.moment_category = N''load_line_repaint''" in sql
    assert "h.moment_category = N''paint_oven_exited''" in sql
    assert "dbo.tblCarts_Paint_Oven_Out" in sql
    assert "yp.current_eol_at >= p.oven_out_at" in sql
    assert "SUM(p.is_repaint_failure) AS ppy_repaint_count" in sql
    assert "SUM(p.is_eol_approved) AS reject_ppy_approved" in sql
    assert "SUM(CASE WHEN p.is_initial_pass = 1 THEN p.is_eol_approved ELSE 0 END) AS reject_fty_approved" in sql
    assert "Paint plan composite" not in sql
    assert OLD_HASH in sql
    assert NEW_HASH in sql
    assert "ASTER_OPERATIONS_KPI_MASTER_REPAINTCOUNT_YIELDS_V1" in sql


def test_master_repaintcount_yield_migration_has_exact_hash_gated_reverse():
    sql = (ROOT / "sql/2026-11-13-rollback-master-repaintcount-yields.sql").read_text(encoding="utf-8")

    assert NEW_HASH in sql
    assert OLD_HASH in sql
    assert "ASTER_OPERATIONS_KPI_MASTER_REPAINTCOUNT_YIELDS_ROLLBACK_V1" in sql
