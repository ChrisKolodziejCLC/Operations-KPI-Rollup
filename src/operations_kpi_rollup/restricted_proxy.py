"""HTTPS Entra authentication proxy for the restricted KPI drill-down.

The proxy is the only LAN-facing component.  It terminates TLS, completes a
single-tenant authorization-code flow with PKCE and certificate client
authentication, resolves the signed-in user through Microsoft Graph, enforces
an exact object-ID and email allowlist, strips caller-supplied identity headers,
and forwards only bounded requests to the loopback restricted backend.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import http.client
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import ssl
import subprocess
import time
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, urlopen


SESSION_COOKIE = "clc_operations_kpi_restricted_session"
OAUTH_COOKIE = "clc_operations_kpi_restricted_oauth"
GUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
MAX_REQUEST_BODY_BYTES = 64 * 1024
MAX_RESPONSE_BODY_BYTES = 32 * 1024 * 1024
PROXY_PATHS = frozenset({
    "/",
    "/index.html",
    "/app.js",
    "/styles.css",
    "/api/health",
    "/api/snapshot",
    "/api/refresh",
})
HOP_BY_HOP_HEADERS = frozenset({
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
})
FORWARDED_REQUEST_HEADERS = frozenset({
    "accept",
    "accept-language",
    "content-type",
    "if-none-match",
    "user-agent",
    "x-operations-kpi-restricted-action",
})


class ProxyAuthError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


class SignedCookieCodec:
    def __init__(self, secret: bytes):
        if len(secret) < 32:
            raise ValueError("The restricted proxy cookie key must contain at least 32 bytes.")
        self.secret = secret

    def encode(self, payload: Mapping[str, Any]) -> str:
        body = b64url_encode(
            json.dumps(dict(payload), separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        )
        signature = b64url_encode(hmac.new(self.secret, body.encode("ascii"), hashlib.sha256).digest())
        return body + "." + signature

    def decode(self, value: str) -> Dict[str, Any]:
        try:
            body, encoded_signature = value.split(".", 1)
            signature = b64url_decode(encoded_signature)
            expected = hmac.new(self.secret, body.encode("ascii"), hashlib.sha256).digest()
            if not hmac.compare_digest(signature, expected):
                raise ValueError("bad signature")
            payload = json.loads(b64url_decode(body).decode("utf-8"))
            if not isinstance(payload, dict) or int(payload.get("exp", 0)) <= int(time.time()):
                raise ValueError("expired")
            return payload
        except (ValueError, TypeError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ProxyAuthError(401, "The restricted KPI sign-in is invalid or expired.") from exc


def _required_environment(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(name + " is required.")
    return value


def _credential_path(name: str) -> Path:
    directory = Path(_required_environment("CREDENTIALS_DIRECTORY"))
    path = directory / name
    if not path.is_file():
        raise ValueError("The systemd credential is unavailable: " + name)
    return path


def _credential_name(environment_name: str, default: str) -> str:
    return os.environ.get(environment_name, default).strip() or default


def normalize_allowed_users(value: Any) -> Dict[str, Dict[str, str]]:
    if not isinstance(value, list):
        raise ValueError("The restricted proxy allowlist must be a JSON list.")
    users: Dict[str, Dict[str, str]] = {}
    for entry in value:
        if not isinstance(entry, dict):
            raise ValueError("Every restricted proxy allowlist entry must be an object.")
        object_id = str(entry.get("objectId") or "").strip().lower()
        email = str(entry.get("email") or "").strip().lower()
        if not GUID.fullmatch(object_id) or not email or "@" not in email:
            raise ValueError("Every restricted proxy allowlist entry needs an exact objectId and email.")
        users[object_id] = {"objectId": object_id, "email": email}
    if not users:
        raise ValueError("At least one restricted proxy user must be allowed.")
    return users


class ProxyConfig:
    def __init__(
        self,
        *,
        tenant_id: str,
        client_id: str,
        base_url: str,
        bind_host: str,
        bind_port: int,
        backend_host: str,
        backend_port: int,
        allowed_users: Mapping[str, Mapping[str, str]],
        cookie_key: bytes,
        tls_certificate: Path,
        tls_private_key: Path,
        client_certificate: Path,
        client_private_key: Path,
    ) -> None:
        self.tenant_id = tenant_id.strip()
        self.client_id = client_id.strip()
        self.base_url = base_url.rstrip("/")
        self.bind_host = bind_host.strip()
        self.bind_port = int(bind_port)
        self.backend_host = backend_host.strip()
        self.backend_port = int(backend_port)
        self.allowed_users = {key: dict(value) for key, value in allowed_users.items()}
        self.cookie_key = cookie_key
        self.tls_certificate = Path(tls_certificate)
        self.tls_private_key = Path(tls_private_key)
        self.client_certificate = Path(client_certificate)
        self.client_private_key = Path(client_private_key)
        self._validate()

    @classmethod
    def from_environment(cls) -> "ProxyConfig":
        allowed_path = _credential_path(
            _credential_name(
                "KPI_RESTRICTED_PROXY_ALLOWED_USERS_CREDENTIAL",
                "operations-kpi-restricted-proxy-allowed-users",
            )
        )
        cookie_path = _credential_path(
            _credential_name(
                "KPI_RESTRICTED_PROXY_COOKIE_KEY_CREDENTIAL",
                "operations-kpi-restricted-proxy-cookie-key",
            )
        )
        return cls(
            tenant_id=_required_environment("KPI_RESTRICTED_PROXY_TENANT_ID"),
            client_id=_required_environment("KPI_RESTRICTED_PROXY_CLIENT_ID"),
            base_url=_required_environment("KPI_RESTRICTED_PROXY_BASE_URL"),
            bind_host=os.environ.get("KPI_RESTRICTED_PROXY_BIND_HOST", "0.0.0.0"),
            bind_port=int(os.environ.get("KPI_RESTRICTED_PROXY_PORT", "5195")),
            backend_host=os.environ.get("KPI_RESTRICTED_PROXY_BACKEND_HOST", "127.0.0.1"),
            backend_port=int(os.environ.get("KPI_RESTRICTED_PROXY_BACKEND_PORT", "5194")),
            allowed_users=normalize_allowed_users(json.loads(allowed_path.read_text(encoding="utf-8"))),
            cookie_key=cookie_path.read_bytes(),
            tls_certificate=_credential_path(
                _credential_name(
                    "KPI_RESTRICTED_PROXY_TLS_CERTIFICATE_CREDENTIAL",
                    "operations-kpi-restricted-proxy-tls-certificate",
                )
            ),
            tls_private_key=_credential_path(
                _credential_name(
                    "KPI_RESTRICTED_PROXY_TLS_KEY_CREDENTIAL",
                    "operations-kpi-restricted-proxy-tls-key",
                )
            ),
            client_certificate=_credential_path(
                _credential_name(
                    "KPI_RESTRICTED_PROXY_CLIENT_CERTIFICATE_CREDENTIAL",
                    "operations-kpi-restricted-proxy-client-certificate",
                )
            ),
            client_private_key=_credential_path(
                _credential_name(
                    "KPI_RESTRICTED_PROXY_CLIENT_KEY_CREDENTIAL",
                    "operations-kpi-restricted-proxy-client-key",
                )
            ),
        )

    @property
    def redirect_uri(self) -> str:
        return self.base_url + "/oauth/callback"

    def _validate(self) -> None:
        if not GUID.fullmatch(self.tenant_id.lower()) or not GUID.fullmatch(self.client_id.lower()):
            raise ValueError("The Entra tenant and client IDs must be GUIDs.")
        parsed = urlsplit(self.base_url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.path not in {"", "/"}:
            raise ValueError("KPI_RESTRICTED_PROXY_BASE_URL must be an HTTPS origin without a path.")
        if parsed.query or parsed.fragment or parsed.username or parsed.password:
            raise ValueError("KPI_RESTRICTED_PROXY_BASE_URL must be a plain HTTPS origin.")
        if not 1024 <= self.bind_port <= 65535 or not 1024 <= self.backend_port <= 65535:
            raise ValueError("Restricted proxy ports must be between 1024 and 65535.")
        backend = ipaddress.ip_address(self.backend_host)
        if not backend.is_loopback:
            raise ValueError("The restricted proxy backend must be loopback.")
        if not self.allowed_users:
            raise ValueError("The restricted proxy allowlist cannot be empty.")
        if len(self.cookie_key) < 32:
            raise ValueError("The restricted proxy cookie key must contain at least 32 bytes.")
        for path in (
            self.tls_certificate,
            self.tls_private_key,
            self.client_certificate,
            self.client_private_key,
        ):
            if not path.is_file():
                raise ValueError("Required restricted proxy certificate material is missing: " + str(path))


class CertificateAssertion:
    def __init__(self, certificate: Path, private_key: Path, client_id: str) -> None:
        self.certificate = certificate
        self.private_key = private_key
        self.client_id = client_id
        result = subprocess.run(
            ["openssl", "x509", "-in", str(certificate), "-outform", "DER"],
            capture_output=True,
            check=False,
        )
        if result.returncode or not result.stdout:
            raise ValueError("The Entra client certificate could not be read.")
        self.thumbprint = b64url_encode(hashlib.sha1(result.stdout).digest())

    def create(self, audience: str, now: Optional[int] = None) -> str:
        issued = int(time.time()) if now is None else int(now)
        header = {"alg": "RS256", "typ": "JWT", "x5t": self.thumbprint}
        claims = {
            "aud": audience,
            "iss": self.client_id,
            "sub": self.client_id,
            "jti": secrets.token_urlsafe(24),
            "nbf": issued - 30,
            "exp": issued + 300,
        }
        unsigned = (
            b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
            + "."
            + b64url_encode(json.dumps(claims, separators=(",", ":")).encode("utf-8"))
        )
        result = subprocess.run(
            ["openssl", "dgst", "-sha256", "-sign", str(self.private_key)],
            input=unsigned.encode("ascii"),
            capture_output=True,
            check=False,
        )
        if result.returncode or not result.stdout:
            raise ProxyAuthError(503, "The restricted KPI Microsoft sign-in certificate is unavailable.")
        return unsigned + "." + b64url_encode(result.stdout)


class EntraOAuth:
    def __init__(self, config: ProxyConfig) -> None:
        self.client_id = config.client_id
        self.redirect_uri = config.redirect_uri
        self.authority = "https://login.microsoftonline.com/{}/oauth2/v2.0".format(config.tenant_id)
        self.assertion = CertificateAssertion(
            config.client_certificate, config.client_private_key, config.client_id
        )

    def authorization_url(self, state: str, verifier: str) -> str:
        challenge = b64url_encode(hashlib.sha256(verifier.encode("ascii")).digest())
        query = urlencode(
            {
                "client_id": self.client_id,
                "response_type": "code",
                "redirect_uri": self.redirect_uri,
                "response_mode": "query",
                "scope": "openid profile email User.Read",
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "prompt": "select_account",
            }
        )
        return self.authority + "/authorize?" + query

    def redeem(self, code: str, verifier: str) -> Dict[str, Any]:
        token_url = self.authority + "/token"
        request = Request(
            token_url,
            data=urlencode(
                {
                    "client_id": self.client_id,
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": self.redirect_uri,
                    "scope": "openid profile email User.Read",
                    "code_verifier": verifier,
                    "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
                    "client_assertion": self.assertion.create(token_url),
                }
            ).encode("ascii"),
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
                "User-Agent": "CLC-Operations-KPI-Restricted/0.34",
            },
        )
        try:
            with urlopen(request, timeout=20) as response:
                payload = json.load(response)
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise ProxyAuthError(401, "Microsoft sign-in could not be completed.") from exc
        token = payload.get("access_token")
        if not isinstance(token, str) or not token:
            raise ProxyAuthError(401, "Microsoft did not return a usable access token.")
        return payload

    def profile(self, token_payload: Mapping[str, Any]) -> Dict[str, str]:
        access_token = str(token_payload.get("access_token") or "")
        request = Request(
            "https://graph.microsoft.com/v1.0/me?$select=id,displayName,mail,userPrincipalName",
            headers={
                "Authorization": "Bearer " + access_token,
                "Accept": "application/json",
                "User-Agent": "CLC-Operations-KPI-Restricted/0.34",
            },
        )
        try:
            with urlopen(request, timeout=20) as response:
                profile = json.load(response)
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise ProxyAuthError(401, "Microsoft profile lookup failed.") from exc
        object_id = str(profile.get("id") or "").lower()
        email = str(profile.get("mail") or profile.get("userPrincipalName") or "").lower()
        if not GUID.fullmatch(object_id) or not email:
            raise ProxyAuthError(401, "Microsoft returned an incomplete profile.")
        return {
            "objectId": object_id,
            "email": email,
            "displayName": str(profile.get("displayName") or email),
        }


class RestrictedProxyApplication:
    def __init__(self, config: ProxyConfig, oauth: Optional[EntraOAuth] = None) -> None:
        self.config = config
        self.cookies = SignedCookieCodec(config.cookie_key)
        self.oauth = oauth or EntraOAuth(config)

    def authorize_profile(self, profile: Mapping[str, str]) -> Dict[str, str]:
        object_id = str(profile.get("objectId") or "").lower()
        email = str(profile.get("email") or "").lower()
        expected = self.config.allowed_users.get(object_id)
        if expected is None or str(expected.get("email") or "").lower() != email:
            raise ProxyAuthError(403, "This Microsoft account is not assigned to the restricted KPI drill-down.")
        return {
            "objectId": object_id,
            "email": email,
            "displayName": str(profile.get("displayName") or email),
        }

    def session_value(self, user: Mapping[str, str]) -> str:
        return self.cookies.encode(
            {
                "sub": user["objectId"],
                "email": user["email"].lower(),
                "name": user["displayName"],
                "exp": int(time.time()) + 8 * 60 * 60,
            }
        )

    def session_user(self, value: Optional[str]) -> Optional[Dict[str, str]]:
        if not value:
            return None
        try:
            payload = self.cookies.decode(value)
            object_id = str(payload.get("sub") or "").lower()
            email = str(payload.get("email") or "").lower()
            expected = self.config.allowed_users.get(object_id)
            if expected is None or str(expected.get("email") or "").lower() != email:
                return None
            return {
                "objectId": object_id,
                "email": email,
                "displayName": str(payload.get("name") or email),
            }
        except ProxyAuthError:
            return None


def forwarded_identity_headers(user: Mapping[str, str]) -> Dict[str, str]:
    email = " ".join(str(user.get("email") or "").split()).lower()[:254]
    name = " ".join(str(user.get("displayName") or email).split())[:200]
    return {
        "X-CLC-Object-Id": str(user["objectId"]).lower(),
        "X-CLC-User": email,
        "X-CLC-Name": name,
    }


def safe_next_path(value: Optional[str]) -> str:
    if (
        not value
        or not value.startswith("/")
        or value.startswith("//")
        or "\r" in value
        or "\n" in value
    ):
        return "/"
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc or parsed.fragment:
        return "/"
    return parsed.path + (("?" + parsed.query) if parsed.query else "")

def cookie_header(name: str, value: str, max_age: int) -> str:
    return "{}={}; Path=/; Max-Age={}; HttpOnly; Secure; SameSite=Lax".format(
        name, value, max_age
    )


def clear_cookie_header(name: str) -> str:
    return "{}=; Path=/; Max-Age=0; HttpOnly; Secure; SameSite=Lax".format(name)


def build_backend_headers(
    request_headers: Mapping[str, str], user: Mapping[str, str], backend_host: str, backend_port: int
) -> Dict[str, str]:
    forwarded: Dict[str, str] = {}
    for name, value in request_headers.items():
        lowered = name.lower()
        if lowered in FORWARDED_REQUEST_HEADERS and lowered not in HOP_BY_HOP_HEADERS:
            forwarded[name] = value
    forwarded["Host"] = "{}:{}".format(backend_host, backend_port)
    forwarded["Connection"] = "close"
    forwarded["X-Forwarded-Proto"] = "https"
    forwarded.update(forwarded_identity_headers(user))
    return forwarded


class RestrictedProxyHandler(BaseHTTPRequestHandler):
    server_version = "OperationsKPIRestrictedProxy/0.34.0"
    sys_version = ""

    @property
    def app(self) -> RestrictedProxyApplication:
        return self.server.application  # type: ignore[attr-defined]

    def do_GET(self) -> None:  # noqa: N802
        self._dispatch()

    def do_HEAD(self) -> None:  # noqa: N802
        self._dispatch()

    def do_POST(self) -> None:  # noqa: N802
        self._dispatch()

    def _dispatch(self) -> None:
        request_id = secrets.token_hex(8)
        status = 500
        try:
            parsed = urlsplit(self.path)
            if parsed.path == "/healthz":
                status = self._json(200, {"status": "ok"})
            elif parsed.path == "/login" and self.command == "GET":
                status = self._begin_oauth(parse_qs(parsed.query).get("next", ["/"])[0])
            elif parsed.path == "/oauth/callback" and self.command == "GET":
                status = self._callback(parse_qs(parsed.query))
            elif parsed.path == "/logout" and self.command == "GET":
                status = self._redirect("/", clear=(SESSION_COOKIE, OAUTH_COOKIE))
            else:
                user = self.app.session_user(self._cookie(SESSION_COOKIE))
                if user is None:
                    status = self._redirect(
                        "/login?" + urlencode({"next": safe_next_path(self.path)})
                    )
                else:
                    status = self._proxy(user)
        except ProxyAuthError as exc:
            status = self._text(exc.status, exc.message)
        except Exception:
            status = self._text(500, "The restricted KPI proxy hit an unexpected error.")
        finally:
            self._audit(request_id, status)

    def _begin_oauth(self, next_path: str) -> int:
        state = secrets.token_urlsafe(24)
        verifier = secrets.token_urlsafe(64)
        value = self.app.cookies.encode(
            {
                "state": state,
                "verifier": verifier,
                "next": safe_next_path(next_path),
                "exp": int(time.time()) + 600,
            }
        )
        self.send_response(302)
        self.send_header("Location", self.app.oauth.authorization_url(state, verifier))
        self.send_header("Set-Cookie", cookie_header(OAUTH_COOKIE, value, 600))
        self.send_header("Content-Length", "0")
        self._security_headers()
        self.end_headers()
        return 302

    def _callback(self, query: Mapping[str, Sequence[str]]) -> int:
        if _first(query, "error"):
            raise ProxyAuthError(401, "Microsoft sign-in was cancelled or denied.")
        code = _first(query, "code")
        state = _first(query, "state")
        oauth_cookie = self._cookie(OAUTH_COOKIE)
        if not code or not state or not oauth_cookie:
            raise ProxyAuthError(401, "Microsoft sign-in response is incomplete.")
        saved = self.app.cookies.decode(oauth_cookie)
        if not hmac.compare_digest(str(saved.get("state") or ""), state):
            raise ProxyAuthError(401, "Microsoft sign-in state did not match.")
        verifier = str(saved.get("verifier") or "")
        if not verifier:
            raise ProxyAuthError(401, "Microsoft sign-in verifier is missing.")
        user = self.app.authorize_profile(
            self.app.oauth.profile(self.app.oauth.redeem(code, verifier))
        )
        self.send_response(303)
        self.send_header("Location", safe_next_path(str(saved.get("next") or "/")))
        self.send_header("Set-Cookie", cookie_header(SESSION_COOKIE, self.app.session_value(user), 28800))
        self.send_header("Content-Length", "0")
        self._security_headers()
        self.end_headers()
        return 303

    def _proxy(self, user: Mapping[str, str]) -> int:
        parsed = urlsplit(self.path)
        if parsed.path not in PROXY_PATHS:
            return self._json(404, {"error": "Not found."})
        if self.command not in {"GET", "HEAD", "POST"}:
            return self._json(405, {"error": "Method not allowed."})
        body: Optional[bytes] = None
        if self.command == "POST":
            try:
                length = int(self.headers.get("Content-Length") or "")
            except ValueError as exc:
                raise ProxyAuthError(411, "A valid Content-Length is required.") from exc
            if length <= 0 or length > MAX_REQUEST_BODY_BYTES:
                raise ProxyAuthError(413, "The restricted KPI request body is too large.")
            body = self.rfile.read(length)
        elif self.headers.get("Content-Length") not in {None, "", "0"}:
            raise ProxyAuthError(400, "A request body is not allowed for this method.")

        target = parsed.path + (("?" + parsed.query) if parsed.query else "")
        connection = http.client.HTTPConnection(
            self.app.config.backend_host,
            self.app.config.backend_port,
            timeout=30,
        )
        try:
            connection.request(
                self.command,
                target,
                body=body,
                headers=build_backend_headers(
                    self.headers,
                    user,
                    self.app.config.backend_host,
                    self.app.config.backend_port,
                ),
            )
            response = connection.getresponse()
            response_body = response.read(MAX_RESPONSE_BODY_BYTES + 1)
            if len(response_body) > MAX_RESPONSE_BODY_BYTES:
                raise ProxyAuthError(502, "The restricted KPI backend response was too large.")
            self.send_response(response.status)
            seen_cache_control = False
            for name, value in response.getheaders():
                lowered = name.lower()
                if lowered in HOP_BY_HOP_HEADERS or lowered in {"content-length", "server", "date", "set-cookie"}:
                    continue
                if lowered == "cache-control":
                    seen_cache_control = True
                self.send_header(name, value)
            if not seen_cache_control:
                self.send_header("Cache-Control", "no-store, private")
            self.send_header("Content-Length", str(len(response_body)))
            self.send_header("Strict-Transport-Security", "max-age=31536000")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(response_body)
            return int(response.status)
        except ProxyAuthError:
            raise
        except (OSError, http.client.HTTPException) as exc:
            raise ProxyAuthError(502, "The restricted KPI backend is unavailable.") from exc
        finally:
            connection.close()

    def _cookie(self, name: str) -> Optional[str]:
        raw = self.headers.get("Cookie")
        if not raw:
            return None
        try:
            parsed = SimpleCookie(raw)
            morsel = parsed.get(name)
            return morsel.value if morsel else None
        except Exception:
            return None

    def _redirect(self, location: str, clear: Tuple[str, ...] = ()) -> int:
        self.send_response(302)
        self.send_header("Location", location)
        for name in clear:
            self.send_header("Set-Cookie", clear_cookie_header(name))
        self.send_header("Content-Length", "0")
        self._security_headers()
        self.end_headers()
        return 302

    def _json(self, status: int, payload: Mapping[str, Any]) -> int:
        body = json.dumps(dict(payload), separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._security_headers()
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)
        return status

    def _text(self, status: int, message: str) -> int:
        body = (message + "\n").encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._security_headers()
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)
        return status

    def _security_headers(self) -> None:
        self.send_header("Cache-Control", "no-store, private")
        self.send_header("Pragma", "no-cache")
        self.send_header("Strict-Transport-Security", "max-age=31536000")
        self.send_header("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'; base-uri 'none'")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")

    def _audit(self, request_id: str, status: int) -> None:
        print(
            json.dumps(
                {
                    "timestamp": int(time.time()),
                    "request_id": request_id,
                    "method": self.command,
                    "path": urlsplit(self.path).path[:160],
                    "status": int(status),
                },
                separators=(",", ":"),
            ),
            flush=True,
        )

    def log_message(self, fmt: str, *args: Any) -> None:
        return


class RestrictedProxyServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 128


def _first(values: Mapping[str, Sequence[str]], key: str) -> Optional[str]:
    items = values.get(key)
    return str(items[0]) if items else None


def create_tls_context(config: ProxyConfig) -> ssl.SSLContext:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.options |= ssl.OP_NO_COMPRESSION
    context.load_cert_chain(str(config.tls_certificate), str(config.tls_private_key))
    return context


def create_proxy_server(
    config: ProxyConfig,
    application: Optional[RestrictedProxyApplication] = None,
    *,
    wrap_tls: bool = True,
) -> RestrictedProxyServer:
    server = RestrictedProxyServer((config.bind_host, config.bind_port), RestrictedProxyHandler)
    server.application = application or RestrictedProxyApplication(config)  # type: ignore[attr-defined]
    if wrap_tls:
        server.socket = create_tls_context(config).wrap_socket(server.socket, server_side=True)
    return server


def main() -> int:
    config = ProxyConfig.from_environment()
    server = create_proxy_server(config)
    print(
        json.dumps(
            {
                "status": "starting",
                "bind": "{}:{}".format(config.bind_host, config.bind_port),
                "backend": "{}:{}".format(config.backend_host, config.backend_port),
                "base_url": config.base_url,
                "access": "entra-exact-allowlist",
            },
            separators=(",", ":"),
        ),
        flush=True,
    )
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
