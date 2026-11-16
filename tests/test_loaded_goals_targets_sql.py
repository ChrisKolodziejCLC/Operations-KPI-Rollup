from pathlib import Path


ROOT = Path(__file__).parents[1]
FORWARD = ROOT / "sql" / "2026-11-16-add-loaded-goals-targets.sql"
ROLLBACK = ROOT / "sql" / "2026-11-16-rollback-loaded-goals-targets.sql"
SERVICE = ROOT / "deploy" / "operations-kpi-rollup.service"
OLD_HASH = "C099469E8FC2F0C27A5B34B2A7D1AFEB27223CEA17148E0F05766D86698A57EB"
NEW_HASH = "A7365336FFFE5170A3D963D3C4599F158C97E29B2E01FFEBD3C59A4ED817285F"
PENDING_HASH = "PENDING_V21_CANDIDATE_SHA256"


def test_v21_forward_is_hash_gated_apply_ready_and_service_pinned():
    sql = FORWARD.read_text(encoding="utf-8")

    assert "DECLARE @CommitChange bit = 1;" in sql
    assert f"DECLARE @ExpectedOldHash varchar(64) = '{OLD_HASH}';" in sql
    assert f"DECLARE @ExpectedNewHash varchar(64) = '{NEW_HASH}';" in sql
    assert f"DECLARE @PendingHash varchar(64) = '{PENDING_HASH}';" in sql
    assert "migration hashes must be pinned before commit" in sql
    assert "ASTER_OPERATIONS_KPI_LOADED_GOALS_TARGETS_V1" in sql
    assert "ROLLBACK TRANSACTION" in sql
    unit = SERVICE.read_text(encoding="utf-8")
    assert f"Environment=KPI_SQL_PROCEDURE_HASH={NEW_HASH}" in unit


def test_v21_adds_only_aggregate_loading_window_contract():
    sql = FORWARD.read_text(encoding="utf-8")

    assert "DailyCartFirst" in sql
    assert "DailyLoadWindow" in sql
    assert "MIN(cart_loaded_at) AS first_cart_loaded_at" in sql
    assert "MAX(cart_loaded_at) AS last_cart_loaded_at" in sql
    assert "load_span_minutes" in sql
    assert "lunch_allowance_minutes" in sql
    assert "net_loading_minutes" in sql
    assert "performance_scored" in sql
    assert "COALESCE(w.load_span_minutes, 0) >= 360 THEN 30" in sql
    assert "d.report_date < CONVERT(date, GETDATE())" in sql
    assert "@ChartStartMarker" in sql
    assert "@ChartEndMarker" in sql


def test_v21_rollback_restores_exact_v20_hash_and_shape():
    sql = ROLLBACK.read_text(encoding="utf-8")

    assert f"DECLARE @ExpectedOldHash varchar(64) = '{NEW_HASH}';" in sql
    assert f"DECLARE @ExpectedNewHash varchar(64) = '{OLD_HASH}';" in sql
    assert "ASTER_OPERATIONS_KPI_LOADED_GOALS_TARGETS_ROLLBACK_V1" in sql
    assert "CHARINDEX(N'DailyLoadWindow', @CandidateDefinition) > 0" in sql
    assert "rollback candidate hash mismatch" in sql


def test_v21_migrations_do_not_write_qpts_business_rows():
    for path in (FORWARD, ROLLBACK):
        sql = path.read_text(encoding="utf-8").upper()
        assert "INSERT INTO" not in sql
        assert "UPDATE " not in sql
        assert "DELETE " not in sql
        assert "MERGE " not in sql
