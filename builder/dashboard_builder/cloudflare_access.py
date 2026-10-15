"""Recognise the owner behind Cloudflare Access on the public host.

When command.meshly.fr sits behind a Cloudflare Access application, Cloudflare
lets a browser through only after its login (a one-time code to the owner's
Gmail, or Google sign-in) and signs every request it forwards with the
``Cf-Access-Jwt-Assertion`` header.  The Access policy is the owner list, so a
token that Cloudflare signed for this very application means the owner.

Nothing here needs configuring.  The team domain and the application's
audience tag are read from Cloudflare's own login redirect for our public host
(or from an optional JSON file when that redirect can't be read), and the
signing keys from the team's certs endpoint.  A caller cannot choose
either, so a token from another Cloudflare team or another application fails.
Until Access is switched on there is no redirect, nothing is trusted and the
owner token keeps working as before.  Standard library only: RS256 is checked
with plain integer arithmetic.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import re
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import parse_qs, urljoin, urlsplit

TEAM_SUFFIX = ".cloudflareaccess.com"
_AUD_RE = re.compile(r"[0-9a-f]{64}")
# DER prefix of a SHA-256 DigestInfo (RFC 8017, EMSA-PKCS1-v1_5).
_SHA256_DIGEST_INFO = bytes.fromhex("3031300d060960864801650304020105000420")
_MAX_TOKEN_LENGTH = 8192
_CLOCK_SKEW_SECONDS = 60

APP_RECHECK_SECONDS = 600
APP_RETRY_SECONDS = 60
KEYS_RECHECK_SECONDS = 3600
KEYS_RETRY_SECONDS = 60


def _b64url_decode(part: str) -> bytes:
    return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # noqa: D401 - urllib hook
        return None


def _login_redirect(url: str, timeout: float) -> str:
    opener = urllib.request.build_opener(_NoRedirect)
    # Ask like a browser would, so Access answers with its login redirect.
    request = urllib.request.Request(url, headers={"User-Agent": "command-center-access-check", "Accept": "text/html"})
    try:
        with opener.open(request, timeout=timeout):
            return ""
    except urllib.error.HTTPError as exc:
        if exc.code in (301, 302, 303, 307, 308):
            return exc.headers.get("Location", "") or ""
        return ""


def access_app_from_redirect(location: str) -> tuple[str, str] | None:
    """(team domain, audience tag) from a Cloudflare Access login URL, or None."""
    parsed = urlsplit(location)
    team = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or parsed.port is not None or not team.endswith(TEAM_SUFFIX):
        return None
    if not parsed.path.startswith("/cdn-cgi/access/login"):
        return None
    aud = parse_qs(parsed.query).get("kid", [""])[0].lower()
    if not _AUD_RE.fullmatch(aud):
        return None
    return team, aud


def discover_access_app(host: str, *, timeout: float = 5.0, login_redirect=_login_redirect) -> tuple[str, str] | None:
    """Ask Cloudflare which Access application guards ``host``; None when there is none."""
    url = f"https://{host}/"
    for _ in range(3):
        try:
            location = login_redirect(url, timeout)
        except (urllib.error.URLError, OSError, ValueError):
            return None
        if not location:
            return None
        url = urljoin(url, location)
        app = access_app_from_redirect(url)
        if app:
            return app
        if (urlsplit(url).hostname or "").lower() != host:
            return None
    return None


def configured_access_app(path) -> tuple[str, str] | None:
    """(team, aud) from an optional JSON file, for when the login redirect can't be read."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    team = str(data.get("team", "")).strip().lower()
    aud = str(data.get("aud", "")).strip().lower()
    if not team.endswith(TEAM_SUFFIX) or not re.fullmatch(r"[a-z0-9-]+" + re.escape(TEAM_SUFFIX), team):
        return None
    return (team, aud) if _AUD_RE.fullmatch(aud) else None


def fetch_signing_keys(team: str, *, timeout: float = 5.0) -> dict[str, dict]:
    """The team's current RSA signing keys, by key id."""
    request = urllib.request.Request(
        f"https://{team}/cdn-cgi/access/certs",
        headers={"User-Agent": "command-center-access-check"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = json.loads(response.read(65536))
    keys = {}
    for key in data.get("keys", []) if isinstance(data, dict) else []:
        if (
            isinstance(key, dict)
            and key.get("kty") == "RSA"
            and isinstance(key.get("kid"), str)
            and isinstance(key.get("n"), str)
            and isinstance(key.get("e"), str)
        ):
            keys[key["kid"]] = key
    return keys


def rs256_signature_valid(signing_input: bytes, signature: bytes, key: dict) -> bool:
    """RSASSA-PKCS1-v1_5 with SHA-256, compared on the whole encoded message."""
    try:
        n = int.from_bytes(_b64url_decode(key["n"]), "big")
        e = int.from_bytes(_b64url_decode(key["e"]), "big")
    except (KeyError, ValueError, binascii.Error):
        return False
    size = (n.bit_length() + 7) // 8
    if size < 256 or e < 3 or len(signature) != size:
        return False
    value = int.from_bytes(signature, "big")
    if value >= n:
        return False
    encoded = pow(value, e, n).to_bytes(size, "big")
    digest = _SHA256_DIGEST_INFO + hashlib.sha256(signing_input).digest()
    expected = b"\x00\x01" + b"\xff" * (size - len(digest) - 3) + b"\x00" + digest
    return hmac.compare_digest(encoded, expected)


def verified_email(token: str, *, team: str, aud: str, keys: dict[str, dict], now: float) -> str | None:
    """The signed-in email when ``token`` is a valid Access token for this team and app."""
    if not isinstance(token, str) or not token or len(token) > _MAX_TOKEN_LENGTH:
        return None
    parts = token.split(".")
    if len(parts) != 3:
        return None
    try:
        signing_input = f"{parts[0]}.{parts[1]}".encode("ascii")
        header = json.loads(_b64url_decode(parts[0]))
        claims = json.loads(_b64url_decode(parts[1]))
        signature = _b64url_decode(parts[2])
    except (UnicodeError, ValueError, binascii.Error):
        return None
    if not isinstance(header, dict) or not isinstance(claims, dict) or header.get("alg") != "RS256":
        return None
    key = keys.get(header.get("kid")) if isinstance(header.get("kid"), str) else None
    if not key or not rs256_signature_valid(signing_input, signature, key):
        return None
    if claims.get("iss") != f"https://{team}":
        return None
    audience = claims.get("aud")
    if isinstance(audience, str):
        audience = [audience]
    if not isinstance(audience, list) or aud not in audience:
        return None
    expires = claims.get("exp")
    if isinstance(expires, bool) or not isinstance(expires, (int, float)) or expires <= now:
        return None
    not_before = claims.get("nbf", claims.get("iat"))
    if isinstance(not_before, (int, float)) and not isinstance(not_before, bool) and not_before > now + _CLOCK_SKEW_SECONDS:
        return None
    email = claims.get("email")
    # Service tokens carry no email: they are machines, not the owner.
    return email if isinstance(email, str) and "@" in email else None


class AccessGate:
    """Caches what Cloudflare says about our public host; safe to share between threads."""

    def __init__(self, host: str, *, discover=discover_access_app, fetch_keys=fetch_signing_keys, clock=time.time):
        self.host = host
        self._discover = discover
        self._fetch_keys = fetch_keys
        self._clock = clock
        self._lock = threading.Lock()
        self._app: tuple[str, str] | None = None
        self._app_next = float("-inf")
        self._keys: dict[str, dict] = {}
        self._keys_team = ""
        self._keys_loaded = float("-inf")
        self._keys_tried = float("-inf")

    def _current_app(self, now: float) -> tuple[str, str] | None:
        if now >= self._app_next:
            try:
                app = self._discover(self.host)
            except Exception:  # noqa: BLE001 - a failed check must never grant access
                app = None
            self._app = app
            self._app_next = now + (APP_RECHECK_SECONDS if app else APP_RETRY_SECONDS)
        return self._app

    def _current_keys(self, team: str, kid: str, now: float) -> dict[str, dict]:
        if team != self._keys_team:
            self._keys, self._keys_team = {}, team
            self._keys_loaded = self._keys_tried = float("-inf")
        due = kid not in self._keys or now - self._keys_loaded >= KEYS_RECHECK_SECONDS
        if due and now - self._keys_tried >= KEYS_RETRY_SECONDS:
            self._keys_tried = now
            try:
                keys = self._fetch_keys(team)
            except Exception:  # noqa: BLE001
                keys = {}
            if keys:
                self._keys, self._keys_loaded = keys, now
        return self._keys

    def owner_email(self, token: str) -> str | None:
        if not token or len(token) > _MAX_TOKEN_LENGTH or token.count(".") != 2:
            return None
        try:
            header = json.loads(_b64url_decode(token.split(".", 1)[0]))
        except (ValueError, binascii.Error):
            return None
        kid = header.get("kid") if isinstance(header, dict) else None
        if not isinstance(kid, str):
            return None
        with self._lock:
            now = self._clock()
            app = self._current_app(now)
            if not app:
                return None
            team, aud = app
            keys = self._current_keys(team, kid, now)
        return verified_email(token, team=team, aud=aud, keys=keys, now=now)
