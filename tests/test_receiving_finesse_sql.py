from pathlib import Path


ROOT = Path(__file__).parents[1]
MIGRATION = ROOT / "sql" / "2026-11-14-correct-receiving-finesse.sql"
SERVICE = ROOT / "deploy" / "operations-kpi-rollup.service"
BASE_HASH = "5A4EA0319892EF663E13ED7EA8BC026D852F3DCC748EC450896B6D549464044D"
CANDIDATE_HASH = "AC7DFDADC5C86C638385CD59265DA5E78A35C6A6A50F7CD869A014F7F02639BE"


def test_receiving_finesse_migration_is_exact_hash_gated_and_reversible():
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "DECLARE @CommitChange bit = 1;" in sql
    assert "DECLARE @RollbackChange bit = 0;" in sql
    assert f"DECLARE @BaseHash varchar(64) = '{BASE_HASH}';" in sql
    assert f"DECLARE @CorrectedHash varchar(64) = '{CANDIDATE_HASH}';" in sql
    assert "CASE WHEN @RollbackChange = 1 THEN @CorrectedHash ELSE @BaseHash END" in sql
    assert "CASE WHEN @RollbackChange = 1 THEN @BaseHash ELSE @CorrectedHash END" in sql
    assert "ASTER_OPERATIONS_KPI_RECEIVING_FINESSE_FORWARD_V1" in sql
    assert "ASTER_OPERATIONS_KPI_RECEIVING_FINESSE_ROLLBACK_V1" in sql
    assert "IF @CommitChange = 1" in sql
    assert "ROLLBACK TRANSACTION" in sql


def test_receiving_finesse_uses_first_receiving_rejects_without_origin_filter():
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "ROW_NUMBER() OVER (PARTITION BY h.part_id ORDER BY h.moment_at, h.id) AS rn" in sql
    assert "h.moment_category IN (N''receiving_approved'', N''receiving_reject'')" in sql
    assert "moment_category = N''receiving_reject''" in sql
    assert "e.repair_disposition" in sql
    assert "N''Repaired''" in sql
    assert "N''WFP''" in sql
    assert "e.insp_line_end_disposition" in sql
    assert "N''Pending''" in sql
    assert "e.Origin" not in sql


def test_receiving_finesse_exposes_balanced_aggregate_fields():
    sql = MIGRATION.read_text(encoding="utf-8")

    for field in (
        "finesse_rejected_count",
        "finesse_repair_count",
        "finesse_repaint_count",
        "finesse_pending_count",
        "bumper_finesse_repair_count",
        "fairing_finesse_repair_count",
        "other_finesse_repair_count",
    ):
        assert field in sql
    assert "inspection_line_set" in sql
    assert "N''Bumpers''" in sql
    assert "N''Fairings''" in sql


def test_migration_does_not_write_qpts_business_rows():
    sql = MIGRATION.read_text(encoding="utf-8").upper()

    assert "INSERT INTO" not in sql
    assert "UPDATE " not in sql
    assert "DELETE " not in sql
    assert "MERGE " not in sql


def test_deployment_unit_pins_the_receiving_finesse_hash():
    unit = SERVICE.read_text(encoding="utf-8")

    assert f"Environment=KPI_SQL_PROCEDURE_HASH={CANDIDATE_HASH}" in unit
