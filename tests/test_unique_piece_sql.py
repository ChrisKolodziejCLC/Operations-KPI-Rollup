from pathlib import Path


ROOT = Path(__file__).parents[1]
OLD_HASH = "CCB07D366B30B7B3ACB08836307DCC053D25C8A69614905CE56BF50AEECA3539"
NEW_HASH = "CB983D8F63982AB833019AEDD0D13067C644FD8231A25E8580B752BD36954714"


def test_unique_piece_migration_counts_distinct_part_ids_and_is_hash_gated():
    sql = (ROOT / "sql/2026-11-13-add-unique-piece-counts.sql").read_text(encoding="utf-8")

    assert "COUNT(DISTINCT le.part_id) AS unique_pieces_loaded" in sql
    assert "COUNT(DISTINCT pe.part_id) AS unique_pieces_processed" in sql
    assert OLD_HASH in sql
    assert NEW_HASH in sql
    assert "ASTER_OPERATIONS_KPI_UNIQUE_PIECES_V1" in sql


def test_unique_piece_migration_has_exact_hash_gated_reverse():
    sql = (ROOT / "sql/2026-11-13-rollback-unique-piece-counts.sql").read_text(encoding="utf-8")

    assert NEW_HASH in sql
    assert OLD_HASH in sql
    assert "ASTER_OPERATIONS_KPI_UNIQUE_PIECES_ROLLBACK_V1" in sql
