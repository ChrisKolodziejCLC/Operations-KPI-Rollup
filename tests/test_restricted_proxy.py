import http.client
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading
import time

import pytest

from operations_kpi_rollup.restricted_proxy import (
    OAUTH_COOKIE,
    SESSION_COOKIE,
    ProxyAuthError,
    ProxyConfig,
    RestrictedProxyApplication,
    SignedCookieCodec,
    build_backend_headers,
    clear_cookie_header,
    cookie_header,
    create_proxy_server,
    normalize_allowed_users,
    safe_next_path,
)


CHRIS_OID = "033cd244-8162-4389-a2b3-4f83d6c78bc0"
CHRIS_EMAIL = "chriskolodziej@creativeliquidcoatings.com"
OTHER_OID = "11111111-2222-3333-4444-555555555555"


class FakeOAuth:
    def __init__(self, profile):
        self._profile = profile

    def authorization_url(self, state, verifier):
        assert state and verifier
        return "https://login.microsoftonline.com/tenant/oauth2/v2.0/authorize?state=" + state

    def redeem(self, code, verifier):
        assert code == "approved-code"
        assert verifier
        return {"access_token": "synthetic-token"}

    def profile(self, token_payload):
        assert token_payload == {"access_token": "synthetic-token"}
        return dict(self._profile)


def _material(tmp_path: Path):
    paths = []
    for name in ("tls.pem", "tls.key", "client.pem", "client.key"):
        path = tmp_path / name
        path.write_text("synthetic test material", encoding="utf-8")
        paths.append(path)
    return paths


def _config(tmp_path: Path, *, base_url="https://kpi.example.test:5195", backend_host="127.0.0.1", backend_port=5194):
    tls_cert, tls_key, client_cert, client_key = _material(tmp_path)
    config = ProxyConfig(
        tenant_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        client_id="bbbbbbbb-cccc-dddd-eeee-ffffffffffff",
        base_url=base_url,
        bind_host="127.0.0.1",
        bind_port=55195,
        backend_host=backend_host,
        backend_port=backend_port,
        allowed_users=normalize_allowed_users([
            {"objectId": CHRIS_OID, "email": CHRIS_EMAIL},
        ]),
        cookie_key=b"k" * 48,
        tls_certificate=tls_cert,
        tls_private_key=tls_key,
        client_certificate=client_cert,
        client_private_key=client_key,
    )
    return config


def test_signed_cookie_round_trip_tamper_and_expiry():
    codec = SignedCookieCodec(b"s" * 48)
    value = codec.encode({"sub": CHRIS_OID, "exp": int(time.time()) + 60})
    assert codec.decode(value)["sub"] == CHRIS_OID
    # the last base64url character of an unpadded 32-byte signature has only 4 significant bits, so the replacement
    # must differ in those bits for every possible original character
    replacement = "Q" if value[-1] in "ABCD" else "A"
    with pytest.raises(ProxyAuthError):
        codec.decode(value[:-1] + replacement)
    with pytest.raises(ProxyAuthError):
        codec.decode(codec.encode({"sub": CHRIS_OID, "exp": int(time.time()) - 1}))


def test_allowlist_requires_exact_object_id_and_email(tmp_path):
    config = _config(tmp_path)
    app = RestrictedProxyApplication(config, oauth=FakeOAuth({}))
    allowed = app.authorize_profile({
        "objectId": CHRIS_OID,
        "email": CHRIS_EMAIL.upper(),
        "displayName": "Chris Kolodziej",
    })
    assert allowed["objectId"] == CHRIS_OID
    for profile in (
        {"objectId": OTHER_OID, "email": CHRIS_EMAIL, "displayName": "Wrong OID"},
        {"objectId": CHRIS_OID, "email": "wrong@example.test", "displayName": "Wrong email"},
    ):
        with pytest.raises(ProxyAuthError) as exc:
            app.authorize_profile(profile)
        assert exc.value.status == 403


def test_config_rejects_insecure_origin_and_non_loopback_backend(tmp_path):
    with pytest.raises(ValueError, match="HTTPS origin"):
        _config(tmp_path, base_url="http://kpi.example.test:5195")
    with pytest.raises(ValueError, match="loopback"):
        _config(tmp_path, backend_host="192.0.2.10")


def test_safe_next_path_rejects_external_and_header_injection():
    assert safe_next_path("/api/snapshot?report_date=2026-11-18") == "/api/snapshot?report_date=2026-11-18"
    for value in ("", "//evil.example/", "https://evil.example/", "/ok#fragment", "/ok\r\nX-Bad: yes"):
        assert safe_next_path(value) == "/"


def test_proxy_headers_drop_spoofed_identity_and_credentials():
    headers = build_backend_headers(
        {
            "Accept": "application/json",
            "Authorization": "Bearer attacker",
            "Cookie": "attacker=true",
            "X-CLC-Object-Id": OTHER_OID,
            "X-CLC-User": "attacker@example.test",
            "X-Operations-KPI-Restricted-Action": "refresh",
        },
        {"objectId": CHRIS_OID, "email": CHRIS_EMAIL, "displayName": "Chris\r\nInjected: no"},
        "127.0.0.1",
        5194,
    )
    lowered = {name.lower(): value for name, value in headers.items()}
    assert "authorization" not in lowered
    assert "cookie" not in lowered
    assert lowered["x-clc-object-id"] == CHRIS_OID
    assert lowered["x-clc-user"] == CHRIS_EMAIL
    assert "\r" not in lowered["x-clc-name"] and "\n" not in lowered["x-clc-name"]
    assert lowered["x-operations-kpi-restricted-action"] == "refresh"


def test_cookie_attributes_are_secure():
    header = cookie_header(SESSION_COOKIE, "value", 60)
    assert "HttpOnly" in header
    assert "Secure" in header
    assert "SameSite=Lax" in header
    cleared = clear_cookie_header(OAUTH_COOKIE)
    assert "Max-Age=0" in cleared
    assert "Secure" in cleared


def test_authenticated_proxy_forwards_only_validated_identity(tmp_path):
    captured = {}

    class BackendHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            captured.update({name.lower(): value for name, value in self.headers.items()})
            body = json.dumps({"ok": True}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt, *args):
            return

    backend = ThreadingHTTPServer(("127.0.0.1", 0), BackendHandler)
    backend_thread = threading.Thread(target=backend.serve_forever, daemon=True)
    backend_thread.start()
    config = _config(tmp_path, backend_port=backend.server_address[1])
    config.bind_port = 0
    oauth = FakeOAuth({
        "objectId": CHRIS_OID,
        "email": CHRIS_EMAIL,
        "displayName": "Chris Kolodziej",
    })
    app = RestrictedProxyApplication(config, oauth=oauth)
    proxy = create_proxy_server(config, app, wrap_tls=False)
    proxy_thread = threading.Thread(target=proxy.serve_forever, daemon=True)
    proxy_thread.start()
    try:
        connection = http.client.HTTPConnection("127.0.0.1", proxy.server_address[1], timeout=5)
        connection.request("GET", "/api/health", headers={
            "Cookie": SESSION_COOKIE + "=" + app.session_value({
                "objectId": CHRIS_OID,
                "email": CHRIS_EMAIL,
                "displayName": "Chris Kolodziej",
            }),
            "Authorization": "Bearer attacker",
            "X-CLC-Object-Id": OTHER_OID,
            "X-CLC-User": "attacker@example.test",
        })
        response = connection.getresponse()
        assert response.status == 200
        assert json.loads(response.read()) == {"ok": True}
        assert captured["x-clc-object-id"] == CHRIS_OID
        assert captured["x-clc-user"] == CHRIS_EMAIL
        assert "authorization" not in captured
        assert "cookie" not in captured

        connection.close()
        connection = http.client.HTTPConnection("127.0.0.1", proxy.server_address[1], timeout=5)
        connection.request("GET", "/api/health", headers={"X-CLC-Object-Id": CHRIS_OID})
        response = connection.getresponse()
        assert response.status == 302
        assert response.getheader("Location", "").startswith("/login?")
        response.read()

        connection.close()
        connection = http.client.HTTPConnection("127.0.0.1", proxy.server_address[1], timeout=5)
        connection.request("GET", "/healthz")
        response = connection.getresponse()
        assert response.status == 200
        assert json.loads(response.read()) == {"status": "ok"}
        assert response.getheader("Cache-Control") == "no-store, private"
        assert response.getheader("X-Frame-Options") == "DENY"
    finally:
        proxy.shutdown()
        proxy.server_close()
        backend.shutdown()
        backend.server_close()
        proxy_thread.join(timeout=5)
        backend_thread.join(timeout=5)
