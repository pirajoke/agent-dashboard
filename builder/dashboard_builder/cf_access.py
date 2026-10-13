"""Recognise the owner signed in through Cloudflare Access (Google or e-mail code).

Cloudflare Access sits in front of command.meshly.fr and adds a signed JWT in the
``Cf-Access-Jwt-Assertion`` header to every request it lets through. The server
checks that JWT itself (signature against the team's published keys, audience,
issuer, expiry) and the e-mail in it, so a forged header never unlocks anything.

Configuration lives outside the repo in ``~/.agent-bridge/cf_access.json``::

    {"team_domain": "<team>.cloudflareaccess.com", "aud": "<Application Audience tag>",
     "emails": ["owner@example.com"]}

Without that file nothing changes: the dashboard keeps asking for the owner token.
"""
from __future__ import annotations

import base64
import json
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any, Mapping

try:  # The Mac mini's system Python has it; without it Access sign-in stays off.
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding, rsa
except ImportError:  # pragma: no cover - depends on the host
    rsa = None

CONFIG_FILE = Path.home() / ".agent-bridge" / "cf_access.json"
HEADER = "Cf-Access-Jwt-Assertion"
KEYS_TTL_SECONDS = 3600
LEEWAY_SECONDS = 60

_keys_lock = threading.Lock()
_keys_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def load_config(path: Path = CONFIG_FILE) -> dict[str, Any] | None:
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    team = str(config.get("team_domain") or "").strip().lower().removeprefix("https://").rstrip("/")
    aud = str(config.get("aud") or "").strip()
    emails = {str(email).strip().lower() for email in config.get("emails") or [] if str(email).strip()}
    if not team.endswith(".cloudflareaccess.com") or not aud or not emails:
        return None
    return {"team_domain": team, "aud": aud, "emails": emails}


def _b64(segment: str) -> bytes:
    return base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))


def _int(segment: str) -> int:
    return int.from_bytes(_b64(segment), "big")


def _fetch_keys(team_domain: str) -> dict[str, rsa.RSAPublicKey]:
    url = f"https://{team_domain}/cdn-cgi/access/certs"
    with urllib.request.urlopen(url, timeout=5) as response:
        jwks = json.loads(response.read().decode("utf-8"))
    keys = {}
    for key in jwks.get("keys") or []:
        if key.get("kty") == "RSA" and key.get("kid") and key.get("n") and key.get("e"):
            keys[key["kid"]] = rsa.RSAPublicNumbers(_int(key["e"]), _int(key["n"])).public_key()
    return keys


def _key(team_domain: str, kid: str, fetch=_fetch_keys) -> rsa.RSAPublicKey | None:
    with _keys_lock:
        cached = _keys_cache.get(team_domain)
        if not cached or time.time() - cached[0] > KEYS_TTL_SECONDS or kid not in cached[1]:
            try:
                cached = (time.time(), fetch(team_domain))
            except Exception:  # noqa: BLE001 - no keys means no owner, never an error page
                return None
            _keys_cache[team_domain] = cached
        return cached[1].get(kid)


def owner_email(headers: Mapping[str, str], config: dict[str, Any] | None = None, *,
                now: float | None = None, fetch=_fetch_keys) -> str | None:
    """The owner's e-mail when the request carries a valid Access JWT for an allowed address."""
    if rsa is None:
        return None
    config = config if config is not None else load_config()
    token = (headers.get(HEADER) or "").strip()
    if not config or not token or token.count(".") != 2:
        return None
    head_b64, body_b64, sig_b64 = token.split(".")
    try:
        header = json.loads(_b64(head_b64))
        claims = json.loads(_b64(body_b64))
        signature = _b64(sig_b64)
    except (ValueError, TypeError):
        return None
    if header.get("alg") != "RS256" or not header.get("kid"):
        return None
    key = _key(config["team_domain"], str(header["kid"]), fetch)
    if key is None:
        return None
    try:
        key.verify(signature, f"{head_b64}.{body_b64}".encode("ascii"), padding.PKCS1v15(), hashes.SHA256())
    except (InvalidSignature, ValueError):
        return None
    moment = time.time() if now is None else now
    aud = claims.get("aud")
    audiences = aud if isinstance(aud, list) else [aud]
    if config["aud"] not in audiences:
        return None
    if claims.get("iss") != f"https://{config['team_domain']}":
        return None
    if not isinstance(claims.get("exp"), (int, float)) or claims["exp"] + LEEWAY_SECONDS < moment:
        return None
    if isinstance(claims.get("nbf"), (int, float)) and claims["nbf"] - LEEWAY_SECONDS > moment:
        return None
    email = str(claims.get("email") or "").strip().lower()
    return email if email in config["emails"] else None
