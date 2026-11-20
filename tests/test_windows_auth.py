"""Windows sign-in listener: allowlist, session cookie, Negotiate flow, roster, TLS."""

from __future__ import annotations

import base64
import http.client
import json
import shutil
import ssl
import subprocess
import threading
import time
from pathlib import Path

import pytest

from operations_kpi_rollup.roster import MAX_IDS, RosterService, RosterUnavailable, clean_ids, roster_from_rows
from operations_kpi_rollup.web import AppState, create_auth_server, create_server
from operations_kpi_rollup.windows_auth import (
    SESSION_COOKIE,
    Allowlist,
    AuthConfigError,
    AuthSettings,
    SessionCodec,
    parse_negotiate_header,
    sam_of,
    settings_from_env,
)

FIXTURE = Path(__file__).parents[1] / "examples" / "2026-09-16.json"
ALLOWED = "ChrisKolodziej@ELITEENTERPRISESINC.COM"
OTHER = "somebody@ELITEENTERPRISESINC.COM"
PEOPLE = ["TommieAlexander", "annetteandrade", "erikaozuna", "DylanYoung", "ZabdiVentura", "anelsoto", "AntoniaTodd", "ChrisKolodziej"]


def write_allowlist(path: Path, people=PEOPLE, realms=None):
    document = {"version": 1, "principals": [{"sam": sam, "name": sam} for sam in people]}
    if realms is not None:
        document["realms"] = realms
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


class FakeAcceptor:
    def __init__(self):
        self.calls = 0

    def accept(self, token: bytes):
        self.calls += 1
        if token == b"allowed":
            return ALLOWED, b"mutual-reply"
        if token == b"denied":
            return OTHER, None
        if token == b"multi":
            return None, b"continue"
        raise RuntimeError("bad ticket")


def settings(tmp_path: Path) -> AuthSettings:
    return AuthSettings(port=0, bind_host="127.0.0.1", keytab=tmp_path / "http.keytab", tls_cert=tmp_path / "c.pem", tls_key=tmp_path / "k.pem",
                        allowlist=write_allowlist(tmp_path / "allowed.json"), service_principal="HTTP/kpi.example.test@EXAMPLE.TEST")


class Running:
    def __init__(self, tmp_path, roster=None, tls=False, acceptor=None):
        monkey_state = AppState("fixture", tmp_path / "snapshots", FIXTURE)
        self.acceptor = acceptor or FakeAcceptor()
        self.server = create_auth_server(settings(tmp_path), monkey_state, None, acceptor=self.acceptor, roster=roster, tls=tls)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]

    def get(self, path, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        connection.request("GET", path, headers=headers or {})
        response = connection.getresponse()
        body = response.read()
        result = (response.status, {key.lower(): value for key, value in response.getheaders()}, body)
        connection.close()
        return result

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def negotiate(token: bytes) -> dict:
    return {"Authorization": "Negotiate " + base64.b64encode(token).decode("ascii")}


def cookie_from(headers: dict) -> str:
    return headers["set-cookie"].split(";", 1)[0]


def test_settings_are_off_by_default_and_validated():
    assert settings_from_env({}) is None
    full = {"KPI_AUTH_PORT": "5196", "KPI_AUTH_KEYTAB": "/k", "KPI_AUTH_TLS_CERT": "/c", "KPI_AUTH_TLS_KEY": "/t", "KPI_AUTH_ALLOWLIST": "/a"}
    parsed = settings_from_env(full)
    assert parsed.port == 5196 and parsed.bind_host == "0.0.0.0"
    assert parsed.service_principal == "HTTP/kpi.eliteenterprisesinc.com@ELITEENTERPRISESINC.COM"
    for broken in ({"KPI_AUTH_PORT": "80"}, {"KPI_AUTH_PORT": "abc"}, {"KPI_AUTH_KEYTAB": ""}, {"KPI_AUTH_SERVICE_PRINCIPAL": "nonsense"}):
        with pytest.raises(AuthConfigError):
            settings_from_env({**full, **broken})


def test_allowlist_matches_case_insensitively_checks_realm_and_fails_closed(tmp_path):
    path = write_allowlist(tmp_path / "allowed.json")
    allowlist = Allowlist(path)
    assert allowlist.count == 8
    assert allowlist.allows("chriskolodziej@eliteenterprisesinc.com")
    assert allowlist.allows("TommieAlexander@ELITEENTERPRISESINC.COM")
    assert not allowlist.allows("ChrisKolodziej@OTHER.REALM")
    assert not allowlist.allows("nobody@ELITEENTERPRISESINC.COM")
    assert not allowlist.allows("ChrisKolodziej") and not allowlist.allows("@ELITEENTERPRISESINC.COM")
    assert not allowlist.allows("HTTP/kpi.eliteenterprisesinc.com@ELITEENTERPRISESINC.COM")
    time.sleep(0.01)
    write_allowlist(path, people=["anelsoto"], realms=["ELITEENTERPRISESINC.COM", "EXAMPLE.TEST"])
    assert allowlist.allows("anelsoto@example.test") and not allowlist.allows("ChrisKolodziej@ELITEENTERPRISESINC.COM")
    time.sleep(0.01)
    path.write_text("not json", encoding="utf-8")
    assert not allowlist.allows("anelsoto@example.test")
    for bad in ({"version": 2, "principals": ["a"]}, {"version": 1, "principals": []}, {"version": 1, "principals": ["a@realm"]}, {"version": 1, "principals": ["a"], "realms": []}):
        broken = tmp_path / "broken.json"
        broken.write_text(json.dumps(bad), encoding="utf-8")
        with pytest.raises(AuthConfigError):
            Allowlist(broken)
    with pytest.raises(OSError):
        Allowlist(tmp_path / "missing.json")


def test_session_cookie_round_trip_tamper_expiry_and_wrong_secret():
    now = [1000.0]
    codec = SessionCodec(secret=b"s" * 32, ttl_seconds=60, clock=lambda: now[0])
    value = codec.issue(ALLOWED)
    assert codec.verify(value) == ALLOWED
    payload, signature = value.split(".")
    assert codec.verify(payload + "." + signature[:-2] + "AA") is None
    assert codec.verify(payload + "A." + signature) is None
    assert codec.verify("") is None and codec.verify("nodot") is None and codec.verify("a.b") is None
    assert SessionCodec(secret=b"t" * 32, clock=lambda: now[0]).verify(value) is None
    now[0] = 1061.0
    assert codec.verify(value) is None
    header = SessionCodec(secret=b"s" * 32).cookie_header(ALLOWED)
    assert header.startswith(SESSION_COOKIE + "=") and all(flag in header for flag in ("Secure", "HttpOnly", "SameSite=Strict", "Path=/", "Max-Age=28800"))


def test_negotiate_header_parsing_and_sam():
    assert parse_negotiate_header("Negotiate " + base64.b64encode(b"abc").decode()) == b"abc"
    assert parse_negotiate_header("negotiate " + base64.b64encode(b"abc").decode()) == b"abc"
    for bad in ("", "Negotiate", "Negotiate !!!", "Basic abc", "Negotiate  "):
        assert parse_negotiate_header(bad) is None
    assert sam_of(ALLOWED) == "ChrisKolodziej" and sam_of("plain") == "plain"


def test_unauthenticated_requests_get_a_negotiate_challenge_and_no_data(tmp_path):
    running = Running(tmp_path)
    try:
        for path in ("/", "/api/snapshot", "/api/session", "/api/roster?ids=1", "/drilldown/", "/api/drilldown/snapshot"):
            status, headers, body = running.get(path)
            assert status == 401 and headers["www-authenticate"] == "Negotiate", path
            assert b"Windows sign-in required" in body and b"report_date" not in body
            assert b'<a href="http://kpi.eliteenterprisesinc.com:5193/">Open the wallboard without signing in (worker IDs, no names)</a>' in body
            assert headers["cache-control"] == "no-store" and headers["x-robots-tag"].startswith("noindex")
        status, headers, body = running.get("/", {"Authorization": "Basic Zm9vOmJhcg=="})
        assert status == 401
    finally:
        running.close()


def test_allowlisted_signin_sets_cookie_serves_the_wallboard_and_reuses_the_session(tmp_path):
    running = Running(tmp_path)
    try:
        status, headers, body = running.get("/api/session", negotiate(b"allowed"))
        assert status == 200
        assert json.loads(body) == {"authenticated": True, "principal": "ChrisKolodziej", "names_allowed": False}
        assert headers["www-authenticate"] == "Negotiate " + base64.b64encode(b"mutual-reply").decode()
        cookie = headers["set-cookie"]
        assert "Secure" in cookie and "HttpOnly" in cookie and "SameSite=Strict" in cookie
        calls = running.acceptor.calls
        status, headers, body = running.get("/api/snapshot", {"Cookie": cookie_from(headers)})
        assert status == 200 and json.loads(body)["report_date"] == "2026-09-16"
        assert running.acceptor.calls == calls and "set-cookie" not in headers
        status, headers, body = running.get("/", {"Cookie": "other=1; " + cookie.split(";", 1)[0]})
        assert status == 200 and b"<html" in body.lower()
    finally:
        running.close()


def test_signed_in_but_not_allowlisted_is_forbidden_without_a_session(tmp_path):
    running = Running(tmp_path)
    try:
        status, headers, body = running.get("/api/snapshot", negotiate(b"denied"))
        assert status == 403 and b"somebody" in body and b"report_date" not in body
        assert b'<a href="http://kpi.eliteenterprisesinc.com:5193/">Open the wallboard without signing in (worker IDs, no names)</a>' in body
        assert "set-cookie" not in headers and "www-authenticate" not in headers
    finally:
        running.close()


def test_bad_tokens_cookies_and_multi_leg_exchanges_are_rejected(tmp_path):
    running = Running(tmp_path)
    try:
        assert running.get("/api/session", negotiate(b"garbage"))[0] == 401
        assert running.get("/api/session", {"Authorization": "Negotiate !!!"})[0] == 401
        status, headers, _ = running.get("/api/session", negotiate(b"multi"))
        assert status == 401 and headers["www-authenticate"] == "Negotiate " + base64.b64encode(b"continue").decode()
        good = running.get("/api/session", negotiate(b"allowed"))[1]["set-cookie"].split(";", 1)[0]
        tampered = good[:-3] + ("AAA" if not good.endswith("AAA") else "BBB")
        assert running.get("/api/session", {"Cookie": tampered})[0] == 401
        assert running.get("/api/session", {"Cookie": "kpi_session=;;;="})[0] == 401
    finally:
        running.close()


def test_cookie_stops_working_when_the_person_leaves_the_allowlist(tmp_path):
    running = Running(tmp_path)
    try:
        cookie = running.get("/api/session", negotiate(b"allowed"))[1]["set-cookie"].split(";", 1)[0]
        assert running.get("/api/session", {"Cookie": cookie})[0] == 200
        time.sleep(0.01)
        write_allowlist(tmp_path / "allowed.json", people=["anelsoto"])
        assert running.get("/api/session", {"Cookie": cookie})[0] == 401
    finally:
        running.close()


def test_roster_endpoint_returns_names_only_for_requested_clean_ids(tmp_path):
    fetches = []

    def fetch():
        fetches.append(1)
        return {"503254": "Pat Painter", "750257": "Sam Sprayer", "999999": "Not Requested"}

    running = Running(tmp_path, roster=RosterService(fetch))
    try:
        session = running.get("/api/session", negotiate(b"allowed"))
        assert json.loads(session[2])["names_allowed"] is True
        cookie = {"Cookie": session[1]["set-cookie"].split(";", 1)[0]}
        status, headers, body = running.get("/api/roster?ids=503254,750257,Unassigned,bad%20id,1234", cookie)
        assert status == 200 and json.loads(body) == {"people": {"503254": "Pat Painter", "750257": "Sam Sprayer"}}
        assert headers["cache-control"] == "no-store" and "999999" not in body.decode()
        assert running.get("/api/roster?ids=503254&ids=750257", cookie)[0] == 200
        assert len(fetches) == 1
        assert json.loads(running.get("/api/roster", cookie)[2]) == {"people": {}}
    finally:
        running.close()


def test_roster_outage_and_missing_configuration_answer_503(tmp_path):
    def broken():
        raise RuntimeError("sql down")

    running = Running(tmp_path, roster=RosterService(broken))
    try:
        cookie = {"Cookie": running.get("/api/session", negotiate(b"allowed"))[1]["set-cookie"].split(";", 1)[0]}
        status, _, body = running.get("/api/roster?ids=503254", cookie)
        assert status == 503 and "unavailable" in json.loads(body)["error"]
    finally:
        running.close()
    plain = Running(tmp_path / "second", roster=None) if (tmp_path / "second").mkdir() is None else None
    try:
        cookie = {"Cookie": plain.get("/api/session", negotiate(b"allowed"))[1]["set-cookie"].split(";", 1)[0]}
        assert plain.get("/api/roster?ids=503254", cookie)[0] == 503
    finally:
        plain.close()


def test_roster_service_caching_stale_fallback_and_cleaning():
    now = [0.0]
    answers = [{"1": "One"}, RuntimeError("down"), {"1": "One", "2": "Two"}]

    def fetch():
        item = answers.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    service = RosterService(fetch, clock=lambda: now[0])
    assert service.names_for(["1", "2"]) == {"1": "One"}
    now[0] = 601.0
    assert service.names_for(["1"]) == {"1": "One"}  # refresh failed, stale copy served
    now[0] = 601.0 + 3601.0
    with pytest.raises(RosterUnavailable):
        RosterService(lambda: (_ for _ in ()).throw(RuntimeError("x")), clock=lambda: now[0]).names_for(["1"])
    assert clean_ids(["1", " 1 ", "Unassigned", "unassigned", "a b", "x" * 33, "ok_id-2"]) == ["1", "ok_id-2"]
    assert len(clean_ids([str(number) for number in range(1000)])) == MAX_IDS
    assert roster_from_rows([{"person_id": " 7 ", "display_name": "  Ann   Lee "}, {"person_id": "7", "display_name": "Dup"}, {"person_id": "8", "display_name": ""}, {"person_id": "", "display_name": "x"}]) == {"7": "Ann Lee"}


def test_the_public_listener_has_no_session_or_roster_routes(tmp_path):
    state = AppState("fixture", tmp_path / "snapshots", FIXTURE)
    server = create_server("127.0.0.1", 0, state)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        for path in ("/api/session", "/api/roster?ids=1"):
            connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
            connection.request("GET", path)
            assert connection.getresponse().status == 404
            connection.close()
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.skipif(shutil.which("openssl") is None, reason="openssl is needed to make a throwaway certificate")
def test_tls_listener_wraps_the_socket_and_refuses_plain_http(tmp_path):
    cert, key = tmp_path / "c.pem", tmp_path / "k.pem"
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(key), "-out", str(cert), "-days", "1",
                    "-subj", "/CN=localhost", "-addext", "subjectAltName=DNS:localhost,IP:127.0.0.1"], check=True, capture_output=True)
    config = AuthSettings(port=0, bind_host="127.0.0.1", keytab=tmp_path / "k", tls_cert=cert, tls_key=key,
                          allowlist=write_allowlist(tmp_path / "allowed.json"), service_principal="HTTP/kpi.example.test@EXAMPLE.TEST")
    state = AppState("fixture", tmp_path / "snapshots", FIXTURE)
    server = create_auth_server(config, state, None, acceptor=FakeAcceptor(), roster=None, tls=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    try:
        context = ssl.create_default_context(cafile=str(cert))
        connection = http.client.HTTPSConnection("127.0.0.1", port, context=context, timeout=5)
        connection.connect()
        version = connection.sock.version()
        connection.request("GET", "/api/session")
        response = connection.getresponse()
        assert response.status == 401 and response.getheader("WWW-Authenticate") == "Negotiate"
        assert version in {"TLSv1.2", "TLSv1.3"}
        connection.close()
        plain = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
        with pytest.raises((http.client.HTTPException, OSError)):
            plain.request("GET", "/api/session")
            plain.getresponse().read()
        plain.close()
    finally:
        server.shutdown()
        server.server_close()


def test_drilldown_names_toggle_is_hidden_by_default_and_wired_to_the_signin_routes():
    base = Path(__file__).parents[1] / "src" / "operations_kpi_rollup" / "drilldown_web"
    script = (base / "app.js").read_text(encoding="utf-8")
    page = (base / "index.html").read_text(encoding="utf-8")
    styles = (base / "styles.css").read_text(encoding="utf-8")
    assert 'id="names-toggle-label" class="names-toggle" hidden' in page and 'id="names-toggle" type="checkbox"' in page
    assert "let namesOn = false;" in script and "let namesAllowed = false;" in script
    assert "fetchJson('/api/session')" in script and "session.names_allowed" in script
    assert "fetchJson('/api/roster?ids=' + encodeURIComponent(missing.join(',')))" in script
    assert "sessionStorage" in script and "localStorage" not in script
    assert "function namedSnapshot(snapshot)" in script and "shared[name] > 1" in script
    for field in ("row.painter_id = nameOf(row.painter_id)", "row.worker_id = nameOf(row.worker_id)", "row.dimension === 'painter') row.label = nameOf(row.label)"):
        assert field in script
    assert "$('#names-toggle').addEventListener('change'" in script and "await initNames();" in script
    assert ".names-toggle[hidden]{display:none}" in styles
    # people who are not on the short list can reach the sign-in page from the open drill-down; it stays hidden on the sign-in site
    assert 'id="names-signin-link" class="back-link" href="https://kpi.eliteenterprisesinc.com:5196/drilldown/" hidden' in page
    assert "function offerNamesSignIn()" in script and "signIn.origin !== location.origin" in script and "  offerNamesSignIn();\n}" in script
    assert ".back-link[hidden]{display:none}" in styles
    # the snapshot served to everyone stays free of names
    assert "contains_named_people" not in script


def test_service_unit_pins_the_roster_procedure_and_configures_the_signin_listener():
    unit = (Path(__file__).parents[1] / "deploy" / "operations-kpi-rollup.service").read_text(encoding="utf-8")
    for line in (
        "Environment=KPI_ROSTER_PROCEDURE_HASH=0EACA9821E82112D9C93DD21A4CBE78B49D5F2A8E2DAF197AD40BA07BFD2E159",
        "Environment=KPI_AUTH_PORT=5196",
        "Environment=KPI_AUTH_KEYTAB=/etc/clc/operations-kpi-rollup/auth/http.keytab",
        "Environment=KPI_AUTH_TLS_CERT=/etc/clc/operations-kpi-rollup/auth/tls-fullchain.pem",
        "Environment=KPI_AUTH_TLS_KEY=/etc/clc/operations-kpi-rollup/auth/tls.key",
        "Environment=KPI_AUTH_ALLOWLIST=/etc/clc/operations-kpi-rollup/auth/allowed-principals.json",
        "Environment=KPI_AUTH_SERVICE_PRINCIPAL=HTTP/kpi.eliteenterprisesinc.com@ELITEENTERPRISESINC.COM",
        "Environment=KRB5RCACHETYPE=none",
    ):
        assert unit.count(line) == 1, line
    assert "KPI_PORT=5193" in unit and "KPI_BIND_HOST=0.0.0.0" in unit


def test_roster_migration_is_hash_gated_reversible_and_read_only():
    import hashlib
    import re as regex

    root = Path(__file__).parents[1]
    definition = (root / "sql/procedures/usp_QPTS_GetOperationsPersonRoster.sql").read_text(encoding="utf-8")
    digest = hashlib.sha256(definition.encode("utf-16-le")).hexdigest().upper()
    forward = (root / "sql/2026-11-19-add-operations-person-roster.sql").read_text(encoding="utf-8")
    rollback = (root / "sql/2026-11-19-rollback-operations-person-roster.sql").read_text(encoding="utf-8")
    assert digest == "0EACA9821E82112D9C93DD21A4CBE78B49D5F2A8E2DAF197AD40BA07BFD2E159"
    assert f"@ExpectedHash varchar(64) = '{digest}'" in forward and f"@ExpectedHash varchar(64) = '{digest}'" in rollback
    assert "refusing to replace it" in forward and forward.count("GRANT ") == 2 and "TO [OperationsKpiRollup_RO]" in forward
    assert "DROP PROCEDURE dbo.usp_QPTS_GetOperationsPersonRoster;" in rollback and "refusing to drop it" in rollback
    reviewed = regex.search(r"DECLARE @ReviewedDefinition nvarchar\(max\) = N'(.*?)';\nDECLARE @ReviewedHash", forward, regex.S).group(1)
    assert reviewed.replace("''", "'") == definition
    upper = definition.upper()
    for banned in ("INSERT ", "UPDATE ", "DELETE ", "MERGE ", "TRUNCATE ", "ALTER ", "DROP ", "EXEC "):
        assert banned not in upper.split("CREATE   PROCEDURE", 1)[1]
    assert "FROM dbo.tblPaintBoothEmployees" in definition and "PainterName" in definition and "READ UNCOMMITTED" in definition


def test_execute_roster_needs_a_pinned_hash_and_uses_a_guarded_batch(monkeypatch):
    from operations_kpi_rollup import odbc

    captured = {}
    monkeypatch.setattr(odbc, "execute_result_sets", lambda query, wanted, credential: captured.update(query=query, wanted=wanted) or ["ok"])
    monkeypatch.delenv("KPI_ROSTER_PROCEDURE_HASH", raising=False)
    with pytest.raises(odbc.OdbcError, match="must pin"):
        odbc.execute_roster()
    monkeypatch.setenv("KPI_ROSTER_PROCEDURE_HASH", "ef" * 32)
    assert odbc.execute_roster() == ["ok"]
    assert "THROW 51005" in captured["query"] and ("EF" * 32) in captured["query"] and captured["query"].endswith("EXEC dbo.usp_QPTS_GetOperationsPersonRoster;")
    assert captured["wanted"] == {0}
