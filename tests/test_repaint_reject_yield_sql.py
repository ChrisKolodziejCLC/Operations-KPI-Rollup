from pathlib import Path


ROOT = Path(__file__).parents[1]
OLD_HASH = "4DFA932D94BF9CC9FF3991EA1787F95EEB43EFAF3B0B4559373734255ECE3ED9"
NEW_HASH = "A425832E9F652F84E55401DD45E917A8D421132442BBBA3EE37FD5136F4B26F5"


def test_repaint_reject_migration_uses_exit_day_passes_and_eol_outcomes():
    sql = (ROOT / "sql/2026-11-13-add-repaint-reject-yields.sql").read_text(encoding="utf-8")

    assert "DECLARE @CommitChange bit = 1;" in sql
    assert "h.PaintCart_ID = o.PaintCart_ID" in sql
    assert "CASE WHEN q.quality_category IS NULL THEN 1 ELSE 0 END AS is_eol_pending" in sql
    assert "N''end_of_line_repair'', N''end_of_line_repaint''" in sql
    assert "SUM(p.is_initial_pass) - SUM(p.is_first_repaint_loop) AS paint_fty_approved" in sql
    assert "COUNT(*) - SUM(p.is_eol_reject) AS reject_ppy_approved" in sql
    assert "SUM(CASE WHEN p.is_initial_pass = 1 THEN p.is_eol_reject ELSE 0 END) AS reject_fty_rejected_count" in sql
    assert "reject_ppy_pending_count" in sql
    assert "reject_fty_pending_count" in sql
    assert OLD_HASH in sql
    assert NEW_HASH in sql
    assert "ASTER_OPERATIONS_KPI_REPAINT_REJECT_YIELDS_V1" in sql


def test_repaint_reject_migration_has_exact_hash_gated_reverse():
    sql = (ROOT / "sql/2026-11-13-rollback-repaint-reject-yields.sql").read_text(encoding="utf-8")

    assert NEW_HASH in sql
    assert OLD_HASH in sql
    assert "ASTER_OPERATIONS_KPI_REPAINT_REJECT_YIELDS_ROLLBACK_V1" in sql
