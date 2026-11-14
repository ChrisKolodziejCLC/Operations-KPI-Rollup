from pathlib import Path


ROOT = Path(__file__).parents[1]
MIGRATION = ROOT / "sql" / "2026-11-13-driverlog-trailer-inspection-details.sql"
SERVICE = ROOT / "deploy" / "operations-kpi-rollup.service"
BASE_HASH = "415953E2A0675AADA2C99A7BABC4F43DBB04B21ACB7BB8D9361AF094C96B7CE3"
CANDIDATE_HASH = "21149FDE5DB32871914F9846F6E29FCF7D071BC6189D7A2272E9E7E4FC0C2DF3"


def test_migration_is_exact_hash_gated_and_reversible():
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "DECLARE @CommitChange bit = 1;" in sql
    assert "DECLARE @RollbackChange bit = 0;" in sql
    assert f"DECLARE @BaseHash varchar(64) = '{BASE_HASH}';" in sql
    assert f"DECLARE @DetailHash varchar(64) = '{CANDIDATE_HASH}';" in sql
    assert "CASE WHEN @RollbackChange = 1 THEN @DetailHash ELSE @BaseHash END" in sql
    assert "CASE WHEN @RollbackChange = 1 THEN @BaseHash ELSE @DetailHash END" in sql
    assert "ASTER_OPERATIONS_KPI_TRAILER_INSPECTION_DETAILS_FORWARD_V1" in sql
    assert "ASTER_OPERATIONS_KPI_TRAILER_INSPECTION_DETAILS_ROLLBACK_V1" in sql
    assert "IF @CommitChange = 1" in sql
    assert "ROLLBACK TRANSACTION" in sql


def test_migration_adds_only_aggregate_owner_approved_sources():
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "FROM dbo.DriverLog AS d" in sql
    assert "CONVERT(date, d.TimeOut)" in sql
    assert "d.TrailerID" in sql
    assert "receiving_bumper_total" in sql
    assert "receiving_fairing_total" in sql
    assert "final_fuka_total" in sql
    assert "final_bumper_total" in sql
    assert "final_fairing_total" in sql
    assert "pass_disposition = N''Repair''" in sql
    assert "paint_fty_repair_count" in sql
    assert "fuka_paint_fty_repair_count" in sql
    assert "fairing_paint_fty_repair_count" in sql
    assert "bumper_paint_fty_repair_count" in sql


def test_staged_queue_matches_the_paint_prep_wallboard_contract():
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "FROM dbo.[EDI Data Table] AS e" in sql
    assert "LEFT JOIN dbo.tblCarts_Paint AS cp" in sql
    assert "cp.[Cart ID] IS NULL" in sql
    assert "e.Origin = N''F''" in sql
    assert "e.[Paint Block] NOT LIKE N''Arc%''" in sql
    assert "DATEADD(day, -2, @ReportDate)" in sql
    assert "DATEADD(day, -6, @ReportDate)" in sql
    assert "GROUP BY block_id, cart_id" in sql
    assert "staged_carts" in sql
    assert "staged_pieces" in sql


def test_migration_does_not_write_qpts_business_rows():
    sql = MIGRATION.read_text(encoding="utf-8").upper()

    assert "INSERT INTO" not in sql
    assert "UPDATE " not in sql
    assert "DELETE " not in sql
    assert "MERGE " not in sql


def test_deployment_unit_pins_the_reviewed_candidate_hash():
    unit = SERVICE.read_text(encoding="utf-8")

    assert f"Environment=KPI_SQL_PROCEDURE_HASH={CANDIDATE_HASH}" in unit
    assert f"Environment=KPI_SQL_PROCEDURE_HASH={BASE_HASH}" not in unit
