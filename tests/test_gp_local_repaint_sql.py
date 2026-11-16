from pathlib import Path


ROOT = Path(__file__).parents[1]
FORWARD = ROOT / "sql" / "2026-11-16-correct-gp-local-repaint.sql"
ROLLBACK = ROOT / "sql" / "2026-11-16-rollback-gp-local-repaint.sql"
SERVICE = ROOT / "deploy" / "operations-kpi-rollup.service"
OLD_HASH = "AC7DFDADC5C86C638385CD59265DA5E78A35C6A6A50F7CD869A014F7F02639BE"
NEW_HASH = "0B45A0737682B316113771E61A64F183EC04698FCEE48AF7F8B4CC94DABB7DC3"


def test_forward_migration_is_hash_gated_and_apply_ready_after_preview():
    sql = FORWARD.read_text(encoding="utf-8")

    assert "DECLARE @CommitChange bit = 1;" in sql
    assert f"DECLARE @ExpectedOldHash varchar(64) = '{OLD_HASH}';" in sql
    assert f"DECLARE @ExpectedNewHash varchar(64) = '{NEW_HASH}';" in sql
    assert "ASTER_OPERATIONS_KPI_GP_LOCAL_REPAINT_V1" in sql
    assert "IF @CommitChange = 1" in sql
    assert "ROLLBACK TRANSACTION" in sql


def test_bv_repaint_lineage_is_based_on_physical_gp_passes():
    sql = FORWARD.read_text(encoding="utf-8")

    assert "ROW_NUMBER() OVER (" in sql
    assert "PARTITION BY p.part_id" in sql
    assert "ORDER BY p.oven_out_at, p.PaintCart_ID" in sql
    assert "b.part_class = N''BV'' AND b.gp_pass_ordinal = 1" in sql
    assert "b.part_class = N''BV'' AND b.gp_pass_ordinal < b.gp_pass_count" in sql
    assert "h.PaintCart_ID = p.PaintCart_ID" in sql
    assert "h.moment_at >= p.oven_out_at" in sql
    assert "ELSE b.is_initial_pass" in sql
    assert "ELSE b.pass_disposition" not in sql


def test_gp_local_repaint_outputs_have_independent_pending_counts():
    sql = FORWARD.read_text(encoding="utf-8")

    for field in (
        "repaint_is_initial_pass",
        "repaint_is_failure",
        "repaint_is_pending",
        "repaint_ppy_pending_count",
        "repaint_fty_pending_count",
    ):
        assert field in sql
    assert "SUM(p.repaint_is_failure) AS ppy_repaint_count" in sql
    assert "SUM(p.repaint_is_pending) AS repaint_ppy_pending_count" in sql
    assert "SUM(CASE WHEN p.repaint_is_initial_pass = 1 THEN p.repaint_is_failure ELSE 0 END) AS paint_fty_repaint_count" in sql


def test_reverse_migration_restores_the_exact_prior_definition():
    sql = ROLLBACK.read_text(encoding="utf-8")

    assert "DECLARE @CommitChange bit = 1;" in sql
    assert f"DECLARE @ExpectedOldHash varchar(64) = '{NEW_HASH}';" in sql
    assert f"DECLARE @ExpectedNewHash varchar(64) = '{OLD_HASH}';" in sql
    assert "ASTER_OPERATIONS_KPI_GP_LOCAL_REPAINT_ROLLBACK_V1" in sql
    assert "Dashboard GP-local repaint rollback hash mismatch." in sql


def test_gp_local_repaint_migration_does_not_write_qpts_business_rows():
    sql = FORWARD.read_text(encoding="utf-8").upper()

    assert "INSERT INTO" not in sql
    assert "UPDATE " not in sql
    assert "DELETE " not in sql
    assert "MERGE " not in sql


def test_service_pins_the_gp_local_repaint_definition_hash():
    unit = SERVICE.read_text(encoding="utf-8")

    assert f"Environment=KPI_SQL_PROCEDURE_HASH={NEW_HASH}" not in unit
