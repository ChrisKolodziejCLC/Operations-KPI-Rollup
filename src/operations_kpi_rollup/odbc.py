"""Minimal read-only ODBC client for the GP-AI01 service.

The production host already carries unixODBC and Microsoft's SQL Server driver.
Keeping this adapter in the standard library avoids installing a second Python
runtime stack on a shared operations server.
"""

from __future__ import annotations

import ctypes
from datetime import date
import os
from pathlib import Path
import re
from typing import Dict, Iterable, List, Optional


SQL_SUCCESS = 0
SQL_SUCCESS_WITH_INFO = 1
SQL_NO_DATA = 100
SQL_HANDLE_ENV = 1
SQL_HANDLE_DBC = 2
SQL_HANDLE_STMT = 3
SQL_ATTR_ODBC_VERSION = 200
SQL_ATTR_QUERY_TIMEOUT = 0
SQL_OV_ODBC3 = 3
SQL_DRIVER_NOPROMPT = 0
SQL_C_CHAR = 1
SQL_NTS = -3
SQL_NULL_DATA = -1


class OdbcError(RuntimeError):
    pass


def parse_connection_string(value: str) -> Dict[str, str]:
    items: List[str] = []
    current: List[str] = []
    quote = ""
    brace_depth = 0
    index = 0
    while index < len(value):
        char = value[index]
        if quote:
            current.append(char)
            if char == quote:
                if index + 1 < len(value) and value[index + 1] == quote:
                    current.append(value[index + 1])
                    index += 1
                else:
                    quote = ""
        elif brace_depth:
            current.append(char)
            if char == "}" and index + 1 < len(value) and value[index + 1] == "}":
                current.append(value[index + 1])
                index += 1
            elif char == "}":
                brace_depth -= 1
        elif char in {'"', "'"}:
            quote = char
            current.append(char)
        elif char == "{":
            brace_depth += 1
            current.append(char)
        elif char == ";":
            items.append("".join(current))
            current = []
        else:
            current.append(char)
        index += 1
    items.append("".join(current))

    result: Dict[str, str] = {}
    for item in items:
        if "=" not in item:
            continue
        key, item_value = item.split("=", 1)
        item_value = item_value.strip()
        if len(item_value) >= 2 and item_value[0] == item_value[-1] and item_value[0] in {'"', "'"}:
            item_value = item_value[1:-1].replace(item_value[0] * 2, item_value[0])
        elif len(item_value) >= 2 and item_value[0] == "{" and item_value[-1] == "}":
            item_value = item_value[1:-1].replace("}}", "}")
        result[key.strip().lower()] = item_value
    return result


def _braced(value: str) -> str:
    return "{" + value.replace("}", "}}") + "}"


def _diagnostic(lib: ctypes.CDLL, handle_type: int, handle: ctypes.c_void_p) -> str:
    records: List[str] = []
    record = 1
    while True:
        state = ctypes.create_string_buffer(6)
        native = ctypes.c_int()
        message = ctypes.create_string_buffer(2048)
        length = ctypes.c_short()
        rc = lib.SQLGetDiagRecA(
            handle_type,
            handle,
            record,
            state,
            ctypes.byref(native),
            message,
            len(message),
            ctypes.byref(length),
        )
        if rc == SQL_NO_DATA:
            break
        if rc not in (SQL_SUCCESS, SQL_SUCCESS_WITH_INFO):
            break
        records.append(
            f"{state.value.decode('ascii', 'replace')}:{native.value}:"
            f"{message.value.decode('utf-8', 'replace')}"
        )
        record += 1
    return " | ".join(records)


def _credential_path(name: str) -> Path:
    credential_dir = os.environ.get("CREDENTIALS_DIRECTORY", "")
    if not credential_dir:
        raise OdbcError("The systemd credential directory is unavailable.")
    path = Path(credential_dir) / name
    if not path.is_file():
        raise OdbcError(f"The protected {name} credential was not loaded.")
    return path


def _approved_connection_string(credential_name: str) -> str:
    protected = _credential_path(credential_name).read_text(encoding="utf-8").strip()
    parts = parse_connection_string(protected)
    server = parts.get("server") or parts.get("data source") or ""
    database = parts.get("database") or parts.get("initial catalog") or ""
    user = parts.get("user id") or parts.get("uid") or ""
    password = parts.get("password") or parts.get("pwd") or ""

    expected_server = os.environ.get("KPI_SQL_EXPECTED_SERVER", "brak").lower()
    expected_database = os.environ.get(
        "KPI_SQL_EXPECTED_DATABASE", "Production Tracking (Version 1.0.0)SQL"
    )
    expected_user = os.environ.get("KPI_SQL_EXPECTED_USER", "OperationsKpiRollup_RO")
    if (
        expected_server not in server.lower()
        or database != expected_database
        or user.lower() != expected_user.lower()
        or not password
    ):
        raise OdbcError("The protected SQL credential does not match the approved read-only contract.")

    connection_string = ";".join(
        [
            "DRIVER={ODBC Driver 18 for SQL Server}",
            "SERVER=" + _braced(server),
            "DATABASE=" + _braced(database),
            "UID=" + _braced(user),
            "PWD=" + _braced(password),
            "Encrypt=yes",
            "TrustServerCertificate=no",
            "ApplicationIntent=ReadOnly",
            "APP=Operations KPI Rollup Read-Only",
        ]
    ) + ";"
    protected = ""
    password = ""
    return connection_string


def _column_names(lib: ctypes.CDLL, statement: ctypes.c_void_p, count: int) -> List[str]:
    names: List[str] = []
    for column in range(1, count + 1):
        name = ctypes.create_string_buffer(512)
        name_length = ctypes.c_short()
        data_type = ctypes.c_short()
        column_size = ctypes.c_ulong()
        decimal_digits = ctypes.c_short()
        nullable = ctypes.c_short()
        rc = lib.SQLDescribeColA(
            statement,
            column,
            name,
            len(name),
            ctypes.byref(name_length),
            ctypes.byref(data_type),
            ctypes.byref(column_size),
            ctypes.byref(decimal_digits),
            ctypes.byref(nullable),
        )
        if rc not in (SQL_SUCCESS, SQL_SUCCESS_WITH_INFO):
            raise OdbcError("Could not describe SQL result columns: " + _diagnostic(lib, SQL_HANDLE_STMT, statement))
        names.append(name.value.decode("utf-8", "replace"))
    return names


def execute_result_sets(
    query: str,
    wanted_indexes: Iterable[int],
    credential_name: str = "operations-kpi-qpts-ro",
) -> List[Dict[str, object]]:
    """Execute a fixed read-only batch and return only explicitly requested sets."""

    if not query.lstrip().upper().startswith(("SET ", "EXEC ")):
        raise OdbcError("Only fixed SET/EXEC read-only batches are supported.")
    wanted = frozenset(wanted_indexes)
    connection_string = _approved_connection_string(credential_name)
    lib = ctypes.cdll.LoadLibrary("libodbc.so.2")
    environment = ctypes.c_void_p()
    connection = ctypes.c_void_p()
    statement = ctypes.c_void_p()
    captured: List[Dict[str, object]] = []
    try:
        if lib.SQLAllocHandle(SQL_HANDLE_ENV, None, ctypes.byref(environment)) not in (SQL_SUCCESS, SQL_SUCCESS_WITH_INFO):
            raise OdbcError("Could not allocate the ODBC environment.")
        if lib.SQLSetEnvAttr(environment, SQL_ATTR_ODBC_VERSION, ctypes.c_void_p(SQL_OV_ODBC3), 0) not in (SQL_SUCCESS, SQL_SUCCESS_WITH_INFO):
            raise OdbcError("Could not select ODBC version 3.")
        if lib.SQLAllocHandle(SQL_HANDLE_DBC, environment, ctypes.byref(connection)) not in (SQL_SUCCESS, SQL_SUCCESS_WITH_INFO):
            raise OdbcError("Could not allocate the ODBC connection.")

        output = ctypes.create_string_buffer(4096)
        output_length = ctypes.c_short()
        rc = lib.SQLDriverConnectA(
            connection,
            None,
            connection_string.encode("utf-8"),
            SQL_NTS,
            output,
            len(output),
            ctypes.byref(output_length),
            SQL_DRIVER_NOPROMPT,
        )
        if rc not in (SQL_SUCCESS, SQL_SUCCESS_WITH_INFO):
            raise OdbcError("Read-only SQL connection failed: " + _diagnostic(lib, SQL_HANDLE_DBC, connection))
        if lib.SQLAllocHandle(SQL_HANDLE_STMT, connection, ctypes.byref(statement)) not in (SQL_SUCCESS, SQL_SUCCESS_WITH_INFO):
            raise OdbcError("Could not allocate the ODBC statement.")
        query_timeout = max(1, min(int(os.environ.get("KPI_SQL_QUERY_TIMEOUT_SECONDS", "120")), 300))
        if lib.SQLSetStmtAttrA(statement, SQL_ATTR_QUERY_TIMEOUT, ctypes.c_void_p(query_timeout), 0) not in (SQL_SUCCESS, SQL_SUCCESS_WITH_INFO):
            raise OdbcError("Could not apply the bounded SQL query timeout.")
        rc = lib.SQLExecDirectA(statement, query.encode("utf-8"), SQL_NTS)
        if rc not in (SQL_SUCCESS, SQL_SUCCESS_WITH_INFO):
            raise OdbcError("Read-only rollup query failed: " + _diagnostic(lib, SQL_HANDLE_STMT, statement))

        result_index = 0
        while True:
            column_count = ctypes.c_short()
            if lib.SQLNumResultCols(statement, ctypes.byref(column_count)) not in (SQL_SUCCESS, SQL_SUCCESS_WITH_INFO):
                raise OdbcError("Could not inspect the SQL result set.")
            columns: List[str] = []
            rows: List[Dict[str, Optional[str]]] = []
            if result_index in wanted and column_count.value > 0:
                columns = _column_names(lib, statement, column_count.value)
                while True:
                    rc = lib.SQLFetch(statement)
                    if rc == SQL_NO_DATA:
                        break
                    if rc not in (SQL_SUCCESS, SQL_SUCCESS_WITH_INFO):
                        raise OdbcError("Could not fetch the SQL result row: " + _diagnostic(lib, SQL_HANDLE_STMT, statement))
                    if len(rows) >= 5000:
                        raise OdbcError("A requested SQL result set exceeded the 5,000-row safety cap.")
                    row: Dict[str, Optional[str]] = {}
                    for column, name in enumerate(columns, start=1):
                        buffer = ctypes.create_string_buffer(65536)
                        indicator = ctypes.c_ssize_t()
                        value_rc = lib.SQLGetData(
                            statement,
                            column,
                            SQL_C_CHAR,
                            buffer,
                            len(buffer),
                            ctypes.byref(indicator),
                        )
                        if value_rc not in (SQL_SUCCESS, SQL_SUCCESS_WITH_INFO) and indicator.value != SQL_NULL_DATA:
                            raise OdbcError("Could not read a SQL result value: " + _diagnostic(lib, SQL_HANDLE_STMT, statement))
                        row[name] = None if indicator.value == SQL_NULL_DATA else buffer.value.decode("utf-8", "replace")
                    rows.append(row)
                captured.append({"index": result_index, "columns": columns, "rows": rows})

            more = lib.SQLMoreResults(statement)
            if more == SQL_NO_DATA:
                break
            if more not in (SQL_SUCCESS, SQL_SUCCESS_WITH_INFO):
                raise OdbcError("Could not advance the SQL result sets: " + _diagnostic(lib, SQL_HANDLE_STMT, statement))
            result_index += 1
        return captured
    finally:
        if statement.value:
            lib.SQLFreeHandle(SQL_HANDLE_STMT, statement)
        if connection.value:
            lib.SQLDisconnect(connection)
            lib.SQLFreeHandle(SQL_HANDLE_DBC, connection)
        if environment.value:
            lib.SQLFreeHandle(SQL_HANDLE_ENV, environment)
        connection_string = ""


def execute_operations_rollup(report_date: date) -> List[Dict[str, object]]:
    iso_date = report_date.isoformat()
    expected_hash = os.environ.get(
        "KPI_SQL_PROCEDURE_HASH",
        "7AA6DCC3A056553C3945EF7474FE15B44565BD9C450E97030DD9970CBF569936",
    ).upper()
    if not re.fullmatch(r"[0-9A-F]{64}", expected_hash):
        raise OdbcError("The configured procedure definition hash is invalid.")
    query = (
        "SET NOCOUNT ON; "
        "DECLARE @ObservedDefinitionHash varchar(64) = CONVERT(varchar(64), "
        "HASHBYTES('SHA2_256', CONVERT(varbinary(max), COALESCE(OBJECT_DEFINITION("
        "OBJECT_ID(N'dbo.usp_QPTS_GetOperationsQualityShippingRollup')), N''))), 2); "
        f"IF @ObservedDefinitionHash <> '{expected_hash}' "
        "THROW 51000, 'The Operations KPI rollup procedure differs from the reviewed contract.', 1; "
        "EXEC dbo.usp_QPTS_GetOperationsQualityShippingRollup "
        f"@ReportDateOverride = '{iso_date}', @IncludeRestrictedDetail = 0;"
    )
    # The public wallboard is aggregate-only. Result set 8 contains named
    # painter data and must never be fetched into its process, even if a stale
    # environment variable remains on a host. Restricted detail has its own
    # service and explicit result-set contract below.
    wanted = {0, 2, 3, 4, 5, 9, 12, 14, 15}
    credential_name = os.environ.get("KPI_SQL_CREDENTIAL_NAME", "operations-kpi-qpts-ro")
    return execute_result_sets(query, wanted, credential_name)


def execute_process_times(report_date: date) -> List[Dict[str, object]]:
    """Read the aggregate process-time rollup through its own hash-pinned, read-only procedure."""
    iso_date = report_date.isoformat()
    expected_hash = os.environ.get("KPI_PROCESS_TIME_PROCEDURE_HASH", "").strip().upper()
    if not re.fullmatch(r"[0-9A-F]{64}", expected_hash):
        raise OdbcError("KPI_PROCESS_TIME_PROCEDURE_HASH must pin the reviewed process-time procedure.")
    query = (
        "SET NOCOUNT ON; "
        "DECLARE @ObservedDefinitionHash varchar(64) = CONVERT(varchar(64), "
        "HASHBYTES('SHA2_256', CONVERT(varbinary(max), COALESCE(OBJECT_DEFINITION("
        "OBJECT_ID(N'dbo.usp_QPTS_GetOperationsProcessTimes')), N''))), 2); "
        f"IF @ObservedDefinitionHash <> '{expected_hash}' "
        "THROW 51003, 'The process-time procedure differs from the reviewed contract.', 1; "
        "EXEC dbo.usp_QPTS_GetOperationsProcessTimes "
        f"@ReportDateOverride = '{iso_date}';"
    )
    credential_name = os.environ.get("KPI_SQL_CREDENTIAL_NAME", "operations-kpi-qpts-ro")
    return execute_result_sets(query, {0, 1, 2}, credential_name)


def execute_quality_charts(report_date: date) -> List[Dict[str, object]]:
    """Read the aggregate quality-chart series through their own hash-pinned, read-only procedure."""
    iso_date = report_date.isoformat()
    expected_hash = os.environ.get("KPI_QUALITY_CHARTS_PROCEDURE_HASH", "").strip().upper()
    if not re.fullmatch(r"[0-9A-F]{64}", expected_hash):
        raise OdbcError("KPI_QUALITY_CHARTS_PROCEDURE_HASH must pin the reviewed quality-chart procedure.")
    query = (
        "SET NOCOUNT ON; "
        "DECLARE @ObservedDefinitionHash varchar(64) = CONVERT(varchar(64), "
        "HASHBYTES('SHA2_256', CONVERT(varbinary(max), COALESCE(OBJECT_DEFINITION("
        "OBJECT_ID(N'dbo.usp_QPTS_GetOperationsQualityCharts')), N''))), 2); "
        f"IF @ObservedDefinitionHash <> '{expected_hash}' "
        "THROW 51004, 'The quality-chart procedure differs from the reviewed contract.', 1; "
        "EXEC dbo.usp_QPTS_GetOperationsQualityCharts "
        f"@ReportDateOverride = '{iso_date}';"
    )
    credential_name = os.environ.get("KPI_SQL_CREDENTIAL_NAME", "operations-kpi-qpts-ro")
    return execute_result_sets(query, {0, 1, 2, 3}, credential_name)


def execute_assembly_charts(report_date: date) -> List[Dict[str, object]]:
    """Read the aggregate assembly-chart series through their own hash-pinned, read-only procedure."""
    iso_date = report_date.isoformat()
    expected_hash = os.environ.get("KPI_ASSEMBLY_CHARTS_PROCEDURE_HASH", "").strip().upper()
    if not re.fullmatch(r"[0-9A-F]{64}", expected_hash):
        raise OdbcError("KPI_ASSEMBLY_CHARTS_PROCEDURE_HASH must pin the reviewed assembly-chart procedure.")
    query = (
        "SET NOCOUNT ON; "
        "DECLARE @ObservedDefinitionHash varchar(64) = CONVERT(varchar(64), "
        "HASHBYTES('SHA2_256', CONVERT(varbinary(max), COALESCE(OBJECT_DEFINITION("
        "OBJECT_ID(N'dbo.usp_QPTS_GetOperationsAssemblyCharts')), N''))), 2); "
        f"IF @ObservedDefinitionHash <> '{expected_hash}' "
        "THROW 51006, 'The assembly-chart procedure differs from the reviewed contract.', 1; "
        "EXEC dbo.usp_QPTS_GetOperationsAssemblyCharts "
        f"@ReportDateOverride = '{iso_date}';"
    )
    credential_name = os.environ.get("KPI_SQL_CREDENTIAL_NAME", "operations-kpi-qpts-ro")
    return execute_result_sets(query, {0, 1, 2}, credential_name)


def execute_roster() -> List[Dict[str, object]]:
    """Read the ID-to-name roster through its own hash-pinned, read-only procedure. Names are never stored."""
    expected_hash = os.environ.get("KPI_ROSTER_PROCEDURE_HASH", "").strip().upper()
    if not re.fullmatch(r"[0-9A-F]{64}", expected_hash):
        raise OdbcError("KPI_ROSTER_PROCEDURE_HASH must pin the reviewed roster procedure.")
    query = (
        "SET NOCOUNT ON; "
        "DECLARE @ObservedDefinitionHash varchar(64) = CONVERT(varchar(64), "
        "HASHBYTES('SHA2_256', CONVERT(varbinary(max), COALESCE(OBJECT_DEFINITION("
        "OBJECT_ID(N'dbo.usp_QPTS_GetOperationsPersonRoster')), N''))), 2); "
        f"IF @ObservedDefinitionHash <> '{expected_hash}' "
        "THROW 51005, 'The roster procedure differs from the reviewed contract.', 1; "
        "EXEC dbo.usp_QPTS_GetOperationsPersonRoster;"
    )
    credential_name = os.environ.get("KPI_SQL_CREDENTIAL_NAME", "operations-kpi-qpts-ro")
    return execute_result_sets(query, {0}, credential_name)


def execute_restricted_rollup(report_date: date) -> List[Dict[str, object]]:
    """Fetch only the reviewed restricted drill-down result sets.

    This path deliberately requires an explicit post-migration procedure hash;
    there is no permissive default. It is called only by the separately bound,
    identity-gated restricted service.
    """

    iso_date = report_date.isoformat()
    expected_hash = os.environ.get("KPI_RESTRICTED_SQL_PROCEDURE_HASH", "").upper()
    if not re.fullmatch(r"[0-9A-F]{64}", expected_hash):
        raise OdbcError(
            "KPI_RESTRICTED_SQL_PROCEDURE_HASH must pin the reviewed restricted-detail procedure."
        )
    query = (
        "SET NOCOUNT ON; "
        "DECLARE @ObservedDefinitionHash varchar(64) = CONVERT(varchar(64), "
        "HASHBYTES('SHA2_256', CONVERT(varbinary(max), COALESCE(OBJECT_DEFINITION("
        "OBJECT_ID(N'dbo.usp_QPTS_GetOperationsQualityShippingRollup')), N''))), 2); "
        f"IF @ObservedDefinitionHash <> '{expected_hash}' "
        "THROW 51001, 'The restricted KPI procedure differs from the reviewed contract.', 1; "
        "EXEC dbo.usp_QPTS_GetOperationsQualityShippingRollup "
        f"@ReportDateOverride = '{iso_date}', @IncludeRestrictedDetail = 1;"
    )
    credential_name = os.environ.get(
        "KPI_RESTRICTED_SQL_CREDENTIAL_NAME", "operations-kpi-qpts-ro"
    )
    return execute_result_sets(query, {16, 17, 18, 19, 20}, credential_name)


def execute_standard_drilldown(report_date: date) -> List[Dict[str, object]]:
    """Fetch the reviewed painter, repaint, and Finesse drill-down result sets.

    This is the wallboard's standard drill-down view, served from the same
    process as the aggregate wallboard but from a separate snapshot. It reuses
    the wallboard's pinned procedure hash and read-only SQL credential and has
    no permissive default: the hash must be present and exactly 64 hex digits.
    """

    iso_date = report_date.isoformat()
    expected_hash = os.environ.get("KPI_SQL_PROCEDURE_HASH", "").upper()
    if not re.fullmatch(r"[0-9A-F]{64}", expected_hash):
        raise OdbcError("KPI_SQL_PROCEDURE_HASH must pin the reviewed drill-down procedure.")
    query = (
        "SET NOCOUNT ON; "
        "DECLARE @ObservedDefinitionHash varchar(64) = CONVERT(varchar(64), "
        "HASHBYTES('SHA2_256', CONVERT(varbinary(max), COALESCE(OBJECT_DEFINITION("
        "OBJECT_ID(N'dbo.usp_QPTS_GetOperationsQualityShippingRollup')), N''))), 2); "
        f"IF @ObservedDefinitionHash <> '{expected_hash}' "
        "THROW 51002, 'The drill-down KPI procedure differs from the reviewed contract.', 1; "
        "EXEC dbo.usp_QPTS_GetOperationsQualityShippingRollup "
        f"@ReportDateOverride = '{iso_date}', @IncludeRestrictedDetail = 1;"
    )
    credential_name = os.environ.get("KPI_SQL_CREDENTIAL_NAME", "operations-kpi-qpts-ro")
    return execute_result_sets(query, {16, 17, 18, 19, 20}, credential_name)
