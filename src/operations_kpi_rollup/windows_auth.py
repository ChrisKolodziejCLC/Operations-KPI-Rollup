"""Windows (Kerberos/Negotiate) sign-in for the names view of the Operations KPI drill-down.

The public wallboard on its own port is unchanged. A second, TLS-protected listener accepts only Kerberos
tickets issued for the service principal in the protected keytab and lets in only the Windows identities on a
protected allowlist file. A signed, expiring session cookie avoids re-negotiating on every request. Nothing in
this module writes a name, ticket, token, or cookie to disk or to the log.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, FrozenSet, Mapping, Optional, Tuple

SESSION_COOKIE = "kpi_session"
SESSION_SECONDS = 8 * 3600
DEFAULT_REALMS = ("ELITEENTERPRISESINC.COM",)
DEFAULT_SERVICE_PRINCIPAL = "HTTP/kpi.eliteenterprisesinc.com@ELITEENTERPRISESINC.COM"
ALLOWLIST_VERSION = 1


class AuthConfigError(RuntimeError):
    """Raised when the sign-in listener cannot be configured safely."""


@dataclass(frozen=True)
class AuthSettings:
    port: int
    bind_host: str
    keytab: Path
    tls_cert: Path
    tls_key: Path
    allowlist: Path
    service_principal: str


def settings_from_env(env: Optional[Mapping[str, str]] = None) -> Optional[AuthSettings]:
    """Return the sign-in settings, or None when KPI_AUTH_PORT is not set (the feature is off)."""

    values = os.environ if env is None else env
    raw_port = values.get("KPI_AUTH_PORT", "").strip()
    if not raw_port:
        return None
    try:
        port = int(raw_port)
    except ValueError as exc:
        raise AuthConfigError("KPI_AUTH_PORT must be a number.") from exc
    if not 1024 <= port <= 65535:
        raise AuthConfigError("KPI_AUTH_PORT must be between 1024 and 65535.")
    paths = {}
    for key in ("KPI_AUTH_KEYTAB", "KPI_AUTH_TLS_CERT", "KPI_AUTH_TLS_KEY", "KPI_AUTH_ALLOWLIST"):
        value = values.get(key, "").strip()
        if not value:
            raise AuthConfigError(key + " must be set when KPI_AUTH_PORT is set.")
        paths[key] = Path(value)
    service = values.get("KPI_AUTH_SERVICE_PRINCIPAL", DEFAULT_SERVICE_PRINCIPAL).strip()
    if "/" not in service or "@" not in service:
        raise AuthConfigError("KPI_AUTH_SERVICE_PRINCIPAL must look like HTTP/host@REALM.")
    return AuthSettings(
        port=port,
        bind_host=values.get("KPI_AUTH_BIND_HOST", "0.0.0.0").strip() or "0.0.0.0",
        keytab=paths["KPI_AUTH_KEYTAB"],
        tls_cert=paths["KPI_AUTH_TLS_CERT"],
        tls_key=paths["KPI_AUTH_TLS_KEY"],
        allowlist=paths["KPI_AUTH_ALLOWLIST"],
        service_principal=service,
    )


class Allowlist:
    """Windows identities allowed to sign in, read from a protected JSON file and reloaded when it changes."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._mtime_ns: Optional[int] = None
        self._principals: FrozenSet[str] = frozenset()
        self._realms: FrozenSet[str] = frozenset(DEFAULT_REALMS)
        self.reload()

    def reload(self) -> None:
        """Strict parse; a missing or malformed file raises so startup fails closed."""

        stat = self.path.stat()
        document = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(document, dict) or document.get("version") != ALLOWLIST_VERSION:
            raise AuthConfigError("The allowlist must be a JSON object with version 1.")
        entries = document.get("principals")
        if not isinstance(entries, list) or not entries:
            raise AuthConfigError("The allowlist needs at least one principal.")
        principals = set()
        for entry in entries:
            sam = entry.get("sam") if isinstance(entry, dict) else entry
            if not isinstance(sam, str) or not sam.strip() or "@" in sam:
                raise AuthConfigError("Each allowlist principal needs a sAMAccountName without a realm.")
            principals.add(sam.strip().lower())
        realms = document.get("realms", list(DEFAULT_REALMS))
        if not isinstance(realms, list) or not realms or not all(isinstance(item, str) and item.strip() for item in realms):
            raise AuthConfigError("The allowlist realms must be a non-empty list of names.")
        with self._lock:
            self._principals = frozenset(principals)
            self._realms = frozenset(item.strip().upper() for item in realms)
            self._mtime_ns = stat.st_mtime_ns

    def _fresh(self) -> None:
        try:
            if self.path.stat().st_mtime_ns != self._mtime_ns:
                self.reload()
        except (OSError, ValueError, AuthConfigError):
            # A file that disappears or becomes unreadable or invalid denies everyone until it is fixed.
            with self._lock:
                self._principals = frozenset()

    @property
    def count(self) -> int:
        with self._lock:
            return len(self._principals)

    def allows(self, principal: str) -> bool:
        self._fresh()
        sam, separator, realm = principal.partition("@")
        if not separator or not sam:
            return False
        with self._lock:
            return realm.upper() in self._realms and sam.lower() in self._principals


class SessionCodec:
    """Signed, expiring session cookie values. The signing secret lives only in memory."""

    def __init__(self, secret: Optional[bytes] = None, ttl_seconds: int = SESSION_SECONDS, clock: Callable[[], float] = time.time) -> None:
        self._secret = secret or secrets.token_bytes(32)
        self.ttl_seconds = ttl_seconds
        self._clock = clock

    @staticmethod
    def _b64(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")

    @staticmethod
    def _unb64(value: str) -> bytes:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))

    def _sign(self, payload: str) -> str:
        return self._b64(hmac.new(self._secret, payload.encode("ascii"), hashlib.sha256).digest())

    def issue(self, principal: str) -> str:
        body = json.dumps({"p": principal, "e": int(self._clock()) + self.ttl_seconds}, separators=(",", ":"))
        payload = self._b64(body.encode("utf-8"))
        return payload + "." + self._sign(payload)

    def verify(self, value: str) -> Optional[str]:
        try:
            payload, _, signature = value.partition(".")
            if not payload or not hmac.compare_digest(signature, self._sign(payload)):
                return None
            body = json.loads(self._unb64(payload))
            principal = body["p"]
            if not isinstance(principal, str) or not principal or int(body["e"]) < self._clock():
                return None
            return principal
        except (ValueError, KeyError, TypeError, binascii.Error, UnicodeError):
            return None

    def cookie_header(self, principal: str) -> str:
        return "%s=%s; Path=/; Max-Age=%d; Secure; HttpOnly; SameSite=Strict" % (SESSION_COOKIE, self.issue(principal), self.ttl_seconds)


class NegotiateAcceptor:
    """Accept SPNEGO/Kerberos tokens with the service keytab through python-gssapi."""

    def __init__(self, keytab: Path, service_principal: str) -> None:
        import gssapi  # Imported here so the wallboard never depends on it.

        self._gssapi = gssapi
        name = gssapi.Name(service_principal, gssapi.NameType.kerberos_principal)
        self._credentials = gssapi.Credentials(name=name, usage="accept", store={"keytab": str(keytab)})

    def accept(self, token: bytes) -> Tuple[Optional[str], Optional[bytes]]:
        """Return (initiator principal or None, reply token or None). Multi-leg exchanges are treated as failures."""

        context = self._gssapi.SecurityContext(creds=self._credentials, usage="accept")
        reply = context.step(token)
        if context.complete:
            return str(context.initiator_name), reply
        return None, reply


def parse_negotiate_header(value: str) -> Optional[bytes]:
    """Return the token bytes from an Authorization: Negotiate header, or None when it is absent or malformed."""

    scheme, _, rest = value.strip().partition(" ")
    if scheme.lower() != "negotiate" or not rest.strip():
        return None
    try:
        return base64.b64decode(rest.strip(), validate=True)
    except (binascii.Error, ValueError):
        return None


def sam_of(principal: str) -> str:
    return principal.partition("@")[0]
