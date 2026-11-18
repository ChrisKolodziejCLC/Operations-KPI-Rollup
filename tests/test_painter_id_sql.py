import hashlib
import re
from pathlib import Path


ROOT = Path(__file__).parents[1]
V35_FORWARD = ROOT / "sql" / "2026-11-18-add-restricted-kpi-drilldown.sql"
FORWARD = ROOT / "sql" / "2026-11-18-painter-ids-restricted-drilldown.sql"
ROLLBACK = ROOT / "sql" / "2026-11-18-rollback-painter-ids-restricted-drilldown.sql"
OLD_HASH = "9CF72B48DA59BBA526B0943F917793A020865D2C41DDDCA664BBB98850C970AF"
NEW_HASH = "7AA6DCC3A056553C3945EF7474FE15B44565BD9C450E97030DD9970CBF569936"
START = "DECLARE @ReviewedDefinition nvarchar(max) = N'"
END = "';\nDECLARE @ReviewedHash varchar(64)"
BEGIN_MARK = "/* RESTRICTED_DRILLDOWN_RESULT_SETS_BEGIN */"
END_MARK = "/* RESTRICTED_DRILLDOWN_RESULT_SETS_END */"


def definition(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    start = text.index(START) + len(START)
    return text[start:text.index(END)].replace("''", "'")


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-16-le")).hexdigest().upper()


def restricted_block(value: str) -> str:
    return value[value.index(BEGIN_MARK):value.index(END_MARK)]


def test_forward_migration_is_hash_gated_and_apply_ready():
    sql = FORWARD.read_text(encoding="utf-8")
    assert sql.count("DECLARE @CommitChange bit = 1;") == 1
    assert f"DECLARE @ExpectedOldHash varchar(64) = '{OLD_HASH}';" in sql
    assert f"DECLARE @ExpectedNewHash varchar(64) = '{NEW_HASH}';" in sql
    assert "ROLLBACK TRANSACTION" in sql
    assert digest(definition(FORWARD)) == NEW_HASH


def test_reverse_migration_restores_the_exact_v35_definition():
    sql = ROLLBACK.read_text(encoding="utf-8")
    assert sql.count("DECLARE @CommitChange bit = 1;") == 1
    assert f"DECLARE @ExpectedOldHash varchar(64) = '{NEW_HASH}';" in sql
    assert f"DECLARE @ExpectedNewHash varchar(64) = '{OLD_HASH}';" in sql
    assert "ROLLBACK TRANSACTION" in sql
    assert digest(definition(ROLLBACK)) == OLD_HASH
    assert definition(ROLLBACK) == definition(V35_FORWARD)


def test_aggregate_section_is_identical_to_the_reviewed_v35_definition():
    old = definition(V35_FORWARD)
    new = definition(FORWARD)
    assert old[:old.index(BEGIN_MARK)] == new[:new.index(BEGIN_MARK)]
    assert old[old.index(END_MARK):] == new[new.index(END_MARK):]


def test_restricted_block_carries_employee_ids_and_no_names():
    block = restricted_block(definition(FORWARD))
    for forbidden in ("painter_name", "worker_name", "PainterNameAtLogin", "Painter_Name"):
        assert forbidden not in block
    for required in ("AS painter_id", "AS worker_id", "dbo.tblPaintBoothEmployees", "EmployeeID", "repair_employee_id"):
        assert required in block
    # The history user name is only used to look up an employee ID.
    assert block.count("LOWER(s.started_by)") == 1
    assert "started_by AS" not in block


def test_restricted_window_is_month_aligned_and_clipped_to_history_start():
    block = restricted_block(definition(FORWARD))
    assert "DATEADD(month, -12, DATEFROMPARTS(YEAR(@ReportDate), MONTH(@ReportDate), 1))" in block
    assert "THEN @HistoryStart" in block
    assert "DATEADD(day, -84, @WeekStart)" not in block


def test_restricted_block_still_writes_only_to_temp_tables():
    block = restricted_block(definition(FORWARD))
    for keyword in ("UPDATE ", "DELETE ", "MERGE ", "TRUNCATE "):
        assert keyword not in block.upper().replace("DELETE_", "")
    for target in re.findall(r"INSERT\s+INTO\s+([^\s(]+)", block, flags=re.IGNORECASE):
        assert target.startswith("#"), target
