from pathlib import Path


ROOT = Path(__file__).parents[1]
FORWARD = ROOT / "sql" / "2026-11-13-add-shipped-rack-counts.sql"
ROLLBACK = ROOT / "sql" / "2026-11-13-rollback-shipped-rack-counts.sql"
OLD_HASH = "80689CEC1019830F14445EB5AE5B4CBE35A9CFFB7494688BB12D8481413B0C7A"
NEW_HASH = "142E3C5764E0E80D4694D085C42DAF82EC153CEBEA757C965BE02B19A61FF373"


def test_forward_migration_is_hash_gated_aggregate_only_and_uses_physical_racks():
    sql = FORWARD.read_text(encoding="utf-8")
    assert "DECLARE @CommitChange bit = 1;" in sql
    assert OLD_HASH in sql
    assert NEW_HASH in sql
    assert "LTRIM(RTRIM(CONVERT(nvarchar(255), e.Rack))) AS rack_id" in sql
    assert "CONVERT(nvarchar(255), e.ship_status) = N''SHIPPED''" in sql
    assert "COUNT(*) AS racks_shipped" in sql
    assert "fuka_racks_shipped" in sql
    assert "bumper_racks_shipped" in sql
    assert "fairing_racks_shipped" in sql
    assert "other_racks_shipped" in sql
    assert "rack_id" not in sql.split("DECLARE @DailyToken", 1)[1]
    assert "INSERT " not in sql.upper()
    assert "UPDATE " not in sql.upper()
    assert "DELETE " not in sql.upper()


def test_reverse_migration_restores_the_pinned_definition():
    sql = ROLLBACK.read_text(encoding="utf-8")
    assert "DECLARE @CommitChange bit = 1;" in sql
    assert OLD_HASH in sql
    assert NEW_HASH in sql
    assert "@CteReplacement" in sql
    assert "@DailyReplacement" in sql
    assert "@JoinReplacement" in sql
    assert "@PeriodReplacement" in sql
    assert "Dashboard shipped-rack rollback candidate hash mismatch." in sql
