from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_repaint_migration_attributes_permanent_disposition_to_initial_paint_cohort():
    sql = (ROOT / "sql/2026-11-13-attribute-repaints-to-original-paint-date.sql").read_text(encoding="utf-8")

    assert "is_repaint_classified" in sql
    assert "e.insp_line_end_disposition" in sql
    assert "e.repair_disposition" in sql
    assert "p.is_initial_pass = 1 AND p.is_repaint_classified = 1" in sql
    assert "CCB07D366B30B7B3ACB08836307DCC053D25C8A69614905CE56BF50AEECA3539" in sql


def test_repaint_migration_has_exact_hash_gated_reverse():
    sql = (ROOT / "sql/2026-11-13-rollback-repaint-cohort-attribution.sql").read_text(encoding="utf-8")

    assert "CCB07D366B30B7B3ACB08836307DCC053D25C8A69614905CE56BF50AEECA3539" in sql
    assert "7D1034139E5AE0A008CFD39A8403A26C260FD6AC6B1BDE758E03EAB78867D7F8" in sql
