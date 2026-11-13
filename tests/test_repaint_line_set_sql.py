from pathlib import Path


ROOT = Path(__file__).parents[1]
FORWARD = ROOT / "sql" / "2026-11-13-add-repaint-line-set-counts.sql"
ROLLBACK = ROOT / "sql" / "2026-11-13-rollback-repaint-line-set-counts.sql"
OLD_HASH = "87B95E7AF33FCAE6F9FD3C9BC0D5F76D3E270ACDB1115A4E5E7C1F407A9D3422"
NEW_HASH = "80689CEC1019830F14445EB5AE5B4CBE35A9CFFB7494688BB12D8481413B0C7A"


def test_forward_migration_is_hash_gated_and_aggregate_only():
    sql = FORWARD.read_text(encoding="utf-8")
    assert "DECLARE @CommitChange bit = 1;" in sql
    assert OLD_HASH in sql
    assert NEW_HASH in sql
    assert "repaint_line_set" in sql
    assert "fuka_paint_fty_repaint_count" in sql
    assert "bumper_paint_fty_repaint_count" in sql
    assert "fairing_paint_fty_repaint_count" in sql
    assert "p.is_initial_pass = 1 AND p.is_repaint_failure = 1" in sql
    assert "COUNT(DISTINCT" not in sql
    assert "INSERT " not in sql.upper()
    assert "UPDATE " not in sql.upper()
    assert "DELETE " not in sql.upper()


def test_reverse_migration_restores_the_pinned_definition():
    sql = ROLLBACK.read_text(encoding="utf-8")
    assert "DECLARE @CommitChange bit = 1;" in sql
    assert OLD_HASH in sql
    assert NEW_HASH in sql
    assert "@YieldReplacement" in sql
    assert "@PeriodMetricReplacement" in sql
    assert "Dashboard repaint line-set rollback candidate hash mismatch." in sql
