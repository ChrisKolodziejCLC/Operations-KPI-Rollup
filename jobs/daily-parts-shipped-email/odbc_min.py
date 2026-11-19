"""Minimal ODBC client over ctypes (libodbc.so.2 + ODBC Driver 18 for SQL Server): connect and run a batch that may return several result sets. Standard library only."""
import ctypes

SQL_HANDLE_ENV, SQL_HANDLE_DBC, SQL_HANDLE_STMT = 1, 2, 3
SQL_SUCCESS, SQL_SUCCESS_WITH_INFO, SQL_NO_DATA = 0, 1, 100
SQL_ATTR_ODBC_VERSION, SQL_OV_ODBC3 = 200, 3
SQL_NTS = -3
SQL_DRIVER_NOPROMPT = 0
SQL_C_CHAR = 1
SQL_NULL_DATA = -1


class OdbcError(Exception):
    pass


_lib = ctypes.cdll.LoadLibrary("libodbc.so.2")


def _diag(handle_type, handle):
    state = ctypes.create_string_buffer(6)
    native = ctypes.c_int()
    message = ctypes.create_string_buffer(1024)
    length = ctypes.c_short()
    messages = []
    record = 1
    while record < 4:
        rc = _lib.SQLGetDiagRecA(ctypes.c_short(handle_type), handle, ctypes.c_short(record), state, ctypes.byref(native),
                                 message, ctypes.c_short(1024), ctypes.byref(length))
        if rc not in (SQL_SUCCESS, SQL_SUCCESS_WITH_INFO):
            break
        messages.append(state.value.decode("ascii", "replace") + " " + message.value.decode("utf-8", "replace"))
        record += 1
    return " | ".join(messages) or "no ODBC diagnostics"


def _braced(value):
    return "{" + value.replace("}", "}}") + "}"


def build_connection_string(server, database, user, password, application="clc-shipped-count-email"):
    return ";".join([
        "Driver={ODBC Driver 18 for SQL Server}",
        "Server=" + _braced(server),
        "Database=" + _braced(database),
        "UID=" + _braced(user),
        "PWD=" + _braced(password),
        "Encrypt=yes",
        "TrustServerCertificate=no",
        "Connection Timeout=20",
        "Application Name=" + application,
    ])


class Connection:
    def __init__(self, connection_string):
        self._env = ctypes.c_void_p()
        self._dbc = ctypes.c_void_p()
        if _lib.SQLAllocHandle(ctypes.c_short(SQL_HANDLE_ENV), None, ctypes.byref(self._env)) != SQL_SUCCESS:
            raise OdbcError("cannot allocate the ODBC environment")
        _lib.SQLSetEnvAttr(self._env, ctypes.c_int(SQL_ATTR_ODBC_VERSION), ctypes.c_void_p(SQL_OV_ODBC3), ctypes.c_int(0))
        if _lib.SQLAllocHandle(ctypes.c_short(SQL_HANDLE_DBC), self._env, ctypes.byref(self._dbc)) != SQL_SUCCESS:
            raise OdbcError("cannot allocate the ODBC connection")
        out = ctypes.create_string_buffer(1024)
        out_length = ctypes.c_short()
        rc = _lib.SQLDriverConnectA(self._dbc, None, connection_string.encode("utf-8"), ctypes.c_short(SQL_NTS), out,
                                    ctypes.c_short(1024), ctypes.byref(out_length), ctypes.c_ushort(SQL_DRIVER_NOPROMPT))
        if rc not in (SQL_SUCCESS, SQL_SUCCESS_WITH_INFO):
            raise OdbcError("connect failed: " + _diag(SQL_HANDLE_DBC, self._dbc))

    def run_batch(self, sql):
        """Run a batch and return the list of result sets, each a list of rows (lists of str or None)."""
        statement = ctypes.c_void_p()
        if _lib.SQLAllocHandle(ctypes.c_short(SQL_HANDLE_STMT), self._dbc, ctypes.byref(statement)) != SQL_SUCCESS:
            raise OdbcError("cannot allocate a statement")
        sets = []
        try:
            rc = _lib.SQLExecDirectA(statement, sql.encode("utf-8"), ctypes.c_int(SQL_NTS))
            if rc not in (SQL_SUCCESS, SQL_SUCCESS_WITH_INFO):
                raise OdbcError("execute failed: " + _diag(SQL_HANDLE_STMT, statement))
            while True:
                columns = ctypes.c_short()
                _lib.SQLNumResultCols(statement, ctypes.byref(columns))
                if columns.value > 0:
                    rows = []
                    while True:
                        rc = _lib.SQLFetch(statement)
                        if rc == SQL_NO_DATA:
                            break
                        if rc not in (SQL_SUCCESS, SQL_SUCCESS_WITH_INFO):
                            raise OdbcError("fetch failed: " + _diag(SQL_HANDLE_STMT, statement))
                        row = []
                        for column in range(1, columns.value + 1):
                            pieces = []
                            null = False
                            while True:
                                buffer = ctypes.create_string_buffer(8192)
                                indicator = ctypes.c_ssize_t()
                                rc = _lib.SQLGetData(statement, ctypes.c_ushort(column), ctypes.c_short(SQL_C_CHAR), buffer,
                                                     ctypes.c_ssize_t(8192), ctypes.byref(indicator))
                                if rc == SQL_NO_DATA:
                                    break
                                if rc not in (SQL_SUCCESS, SQL_SUCCESS_WITH_INFO):
                                    raise OdbcError("read failed: " + _diag(SQL_HANDLE_STMT, statement))
                                if indicator.value == SQL_NULL_DATA:
                                    null = True
                                    break
                                if rc == SQL_SUCCESS:
                                    pieces.append(buffer.value if indicator.value < 0 else buffer.raw[:indicator.value])
                                    break
                                pieces.append(buffer.raw[:8191])
                            row.append(None if null else b"".join(pieces).decode("utf-8", "replace"))
                        rows.append(row)
                    sets.append(rows)
                rc = _lib.SQLMoreResults(statement)
                if rc == SQL_NO_DATA:
                    break
                if rc not in (SQL_SUCCESS, SQL_SUCCESS_WITH_INFO):
                    raise OdbcError("next result failed: " + _diag(SQL_HANDLE_STMT, statement))
            return sets
        finally:
            _lib.SQLFreeHandle(ctypes.c_short(SQL_HANDLE_STMT), statement)

    def close(self):
        if self._dbc:
            _lib.SQLDisconnect(self._dbc)
            _lib.SQLFreeHandle(ctypes.c_short(SQL_HANDLE_DBC), self._dbc)
            self._dbc = ctypes.c_void_p()
        if self._env:
            _lib.SQLFreeHandle(ctypes.c_short(SQL_HANDLE_ENV), self._env)
            self._env = ctypes.c_void_p()
