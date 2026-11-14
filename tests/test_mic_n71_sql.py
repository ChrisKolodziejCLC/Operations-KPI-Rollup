from pathlib import Path


ROOT = Path(__file__).parents[1]
FORWARD = ROOT / "sql" / "2026-11-13-add-mic-n71-breakdowns.sql"
ROLLBACK = ROOT / "sql" / "2026-11-13-rollback-mic-n71-breakdowns.sql"
OLD_HASH = "142E3C5764E0E80D4694D085C42DAF82EC153CEBEA757C965BE02B19A61FF373"
NEW_HASH = "415953E2A0675AADA2C99A7BABC4F43DBB04B21ACB7BB8D9361AF094C96B7CE3"


def test_forward_migration_is_hash_gated_and_preserves_aggregate_grain():
    sql = FORWARD.read_text(encoding="utf-8")

    assert "DECLARE @CommitChange bit = 1;" in sql
    assert f"DECLARE @ExpectedOldHash varchar(64) = '{OLD_HASH}';" in sql
    assert f"DECLARE @ExpectedNewHash varchar(64) = '{NEW_HASH}';" in sql
    assert "LIKE N''N71-6164%''" in sql
    assert "UPPER(LTRIM(RTRIM(CONVERT(nvarchar(255), e.Color)))) = N''MIC''" in sql
    assert "mic_complete_assy_sets" in sql
    assert "painted_complete_assy_sets" in sql
    assert "mic_assembled_bumper_count" in sql
    assert "painted_assembled_bumper_count" in sql
    assert "n71_6164_parts_loaded" in sql
    assert "n71_6164_paint_pieces_processed" in sql
    assert "n71_6164_racks_shipped" in sql
    assert "WHEN LTRIM(CONVERT(nvarchar(255), e.[Part Number])) LIKE N''N71-6164%'' THEN N''N71-6164''" in sql
    assert "No part IDs, sequences," in sql
    assert "INSERT " not in sql.upper()
    assert "UPDATE " not in sql.upper()
    assert "DELETE " not in sql.upper()


def test_reverse_migration_is_hash_gated_and_restores_exact_old_definition():
    sql = ROLLBACK.read_text(encoding="utf-8")

    assert "DECLARE @CommitChange bit = 1;" in sql
    assert f"DECLARE @ExpectedOldHash varchar(64) = '{NEW_HASH}';" in sql
    assert f"DECLARE @ExpectedNewHash varchar(64) = '{OLD_HASH}';" in sql
    assert "REPLACE(@CandidateDefinition, @NewPartClass, @OldPartClass)" in sql
    assert "REPLACE(@CandidateDefinition, @NewAssembly, @OldAssembly)" in sql
    assert "REPLACE(@CandidateDefinition, @NewRack, @OldRack)" in sql
    assert "REPLACE(@CandidateDefinition, @NewShippingCase, @OldShippingCase)" in sql
    assert "Dashboard MIC/N71 rollback candidate hash mismatch." in sql
    assert "ASTER_OPERATIONS_KPI_MIC_N71_BREAKDOWNS_ROLLBACK_V1" in sql
