from pathlib import Path


ROOT = Path(__file__).parents[1]
MIGRATION = ROOT / "sql" / "2026-11-13-correct-product-family-mapping.sql"
SERVICE = ROOT / "deploy" / "operations-kpi-rollup.service"
BASE_HASH = "21149FDE5DB32871914F9846F6E29FCF7D071BC6189D7A2272E9E7E4FC0C2DF3"
CANDIDATE_HASH = "5A4EA0319892EF663E13ED7EA8BC026D852F3DCC748EC450896B6D549464044D"


def test_category_mapping_migration_is_hash_gated_and_reversible():
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "DECLARE @CommitChange bit = 1;" in sql
    assert "DECLARE @RollbackChange bit = 0;" in sql
    assert f"DECLARE @BaseHash varchar(64) = '{BASE_HASH}';" in sql
    assert f"DECLARE @CorrectedHash varchar(64) = '{CANDIDATE_HASH}';" in sql
    assert "CASE WHEN @RollbackChange = 1 THEN @CorrectedHash ELSE @BaseHash END" in sql
    assert "CASE WHEN @RollbackChange = 1 THEN @BaseHash ELSE @CorrectedHash END" in sql
    assert "ASTER_OPERATIONS_KPI_PRODUCT_FAMILY_FORWARD_V1" in sql
    assert "ASTER_OPERATIONS_KPI_PRODUCT_FAMILY_ROLLBACK_V1" in sql
    assert "ROLLBACK TRANSACTION" in sql


def test_all_product_family_rules_use_authoritative_description():
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "e.Description))) = N''Fender'' THEN N''FUKA''" in sql
    assert "e.Description))) = N''Bumper'' THEN N''Bumpers''" in sql
    assert "e.Description))) = N''Chassis Fairing'' THEN N''Fairings''" in sql
    assert "AS repaint_line_set" in sql
    assert "AS inspection_line_set" in sql
    assert "AS bumpers_shipped" in sql
    assert "AS fuka_parts" in sql
    assert "AS bumper_parts" in sql
    assert "AS fairing_parts" in sql
    assert "N''N71-6164''" in sql


def test_migration_does_not_write_qpts_business_rows():
    sql = MIGRATION.read_text(encoding="utf-8").upper()

    assert "INSERT INTO" not in sql
    assert "UPDATE " not in sql
    assert "DELETE " not in sql
    assert "MERGE " not in sql


def test_deployment_unit_has_advanced_past_category_mapping_hash():
    unit = SERVICE.read_text(encoding="utf-8")

    assert f"Environment=KPI_SQL_PROCEDURE_HASH={CANDIDATE_HASH}" not in unit
    assert f"Environment=KPI_SQL_PROCEDURE_HASH={BASE_HASH}" not in unit
