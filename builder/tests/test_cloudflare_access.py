from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import random
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dashboard_builder import cloudflare_access as ca


BUILDER_DIR = Path(__file__).resolve().parents[1]
SERVER_SPEC = importlib.util.spec_from_file_location("dashboard_server_m4_access", BUILDER_DIR / "dashboard-server-m4.py")
SERVER = importlib.util.module_from_spec(SERVER_SPEC)
assert SERVER_SPEC and SERVER_SPEC.loader
SERVER_SPEC.loader.exec_module(SERVER)

TEAM = "markteam.cloudflareaccess.com"
AUD = "a" * 64
NOW = 1_800_000_000


def _probable_prime(bits: int, rng: random.Random) -> int:
    small = [p for p in range(3, 2000, 2) if all(p % q for q in range(3, int(p ** 0.5) + 1, 2))]
    while True:
        n = rng.getrandbits(bits) | (1 << (bits - 1)) | 1
        if any(n % p == 0 for p in small):
            continue
        d, r = n - 1, 0
        while d % 2 == 0:
            d, r = d // 2, r + 1
        for _ in range(20):
            x = pow(rng.randrange(2, n - 2), d, n)
            if x in (1, n - 1):
                continue
            for _ in range(r - 1):
                x = pow(x, 2, n)
                if x == n - 1:
                    break
            else:
                break
        else:
            return n


def _keypair(bits: int, seed: int) -> tuple[int, int, int]:
    rng = random.Random(seed)
    e = 65537
    while True:
        p, q = _probable_prime(bits // 2, rng), _probable_prime(bits // 2, rng)
        phi = (p - 1) * (q - 1)
        if p != q and phi % e:
            return p * q, e, pow(e, -1, phi)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _jwk(n: int, e: int, kid: str) -> dict:
    return {"kid": kid, "kty": "RSA", "alg": "RS256", "use": "sig",
            "n": _b64(n.to_bytes((n.bit_length() + 7) // 8, "big")), "e": _b64(e.to_bytes(3, "big"))}


def _sign(claims: dict, key: tuple[int, int, int], *, kid: str = "k1", alg: str = "RS256") -> str:
    n, _, d = key
    head = _b64(json.dumps({"alg": alg, "kid": kid, "typ": "JWT"}).encode())
    body = _b64(json.dumps(claims).encode())
    size = (n.bit_length() + 7) // 8
    digest = bytes.fromhex("3031300d060960864801650304020105000420") + hashlib.sha256(f"{head}.{body}".encode()).digest()
    encoded = b"\x00\x01" + b"\xff" * (size - len(digest) - 3) + b"\x00" + digest
    signature = pow(int.from_bytes(encoded, "big"), d, n).to_bytes(size, "big")
    return f"{head}.{body}.{_b64(signature)}"


def _claims(**overrides) -> dict:
    claims = {"aud": [AUD], "iss": f"https://{TEAM}", "email": "owner@example.com",
              "exp": NOW + 3600, "iat": NOW - 10, "nbf": NOW - 10, "type": "app"}
    claims.update(overrides)
    return claims


class CloudflareAccessTokenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = _keypair(2048, seed=7)
        cls.keys = {"k1": _jwk(cls.key[0], cls.key[1], "k1")}

    def _email(self, token: str, **kwargs) -> str | None:
        params = {"team": TEAM, "aud": AUD, "keys": self.keys, "now": NOW}
        params.update(kwargs)
        return ca.verified_email(token, **params)

    def test_token_signed_for_this_app_gives_the_email(self):
        self.assertEqual(self._email(_sign(_claims(), self.key)), "owner@example.com")
        self.assertEqual(self._email(_sign(_claims(aud=AUD), self.key)), "owner@example.com")

    def test_other_app_other_team_or_expired_token_is_refused(self):
        self.assertIsNone(self._email(_sign(_claims(aud=["b" * 64]), self.key)))
        self.assertIsNone(self._email(_sign(_claims(iss="https://evil.cloudflareaccess.com"), self.key)))
        self.assertIsNone(self._email(_sign(_claims(exp=NOW - 1), self.key)))
        self.assertIsNone(self._email(_sign(_claims(nbf=NOW + 3600), self.key)))
        self.assertIsNone(self._email(_sign(_claims(exp="soon"), self.key)))

    def test_service_tokens_without_an_email_are_not_the_owner(self):
        claims = _claims()
        del claims["email"]
        self.assertIsNone(self._email(_sign(claims, self.key)))

    def test_tampered_unsigned_or_unknown_key_tokens_are_refused(self):
        token = _sign(_claims(), self.key)
        head, _, signature = token.split(".")
        forged_body = _b64(json.dumps(_claims(email="attacker@example.com")).encode())
        self.assertIsNone(self._email(f"{head}.{forged_body}.{signature}"))
        self.assertIsNone(self._email(_sign(_claims(), self.key, alg="HS256")))
        self.assertIsNone(self._email(_sign(_claims(), self.key, kid="other")))
        self.assertIsNone(self._email(token[:-4] + "AAAA"))
        self.assertIsNone(self._email("not.a.token"))
        self.assertIsNone(self._email(""))
        other = _keypair(2048, seed=11)
        self.assertIsNone(self._email(_sign(_claims(), other)))

    def test_short_keys_are_refused(self):
        small = _keypair(1024, seed=3)
        token = _sign(_claims(), small)
        self.assertIsNone(self._email(token, keys={"k1": _jwk(small[0], small[1], "k1")}))


class CloudflareAccessDiscoveryTests(unittest.TestCase):
    LOGIN = f"https://{TEAM}/cdn-cgi/access/login/command.meshly.fr?kid={AUD}&redirect_url=%2F&meta=x"

    def test_login_redirect_names_the_team_and_app(self):
        self.assertEqual(ca.access_app_from_redirect(self.LOGIN), (TEAM, AUD))

    def test_other_redirects_are_not_an_access_app(self):
        for location in (
            "https://accounts.google.com/o/oauth2/auth",
            f"http://{TEAM}/cdn-cgi/access/login/x?kid={AUD}",
            f"https://{TEAM}/cdn-cgi/access/login/x",
            f"https://{TEAM}/cdn-cgi/access/login/x?kid=short",
            f"https://{TEAM}:8443/cdn-cgi/access/login/x?kid={AUD}",
            f"https://{TEAM}/elsewhere?kid={AUD}",
            "",
        ):
            self.assertIsNone(ca.access_app_from_redirect(location), location)

    def test_discovery_follows_a_hop_on_our_own_host(self):
        hops = {"https://command.meshly.fr/": "/cdn-cgi/access/login?x=1",
                "https://command.meshly.fr/cdn-cgi/access/login?x=1": self.LOGIN}
        self.assertEqual(ca.discover_access_app("command.meshly.fr", login_redirect=lambda url, t: hops.get(url, "")), (TEAM, AUD))

    def test_no_redirect_or_a_foreign_one_means_no_access(self):
        self.assertIsNone(ca.discover_access_app("command.meshly.fr", login_redirect=lambda url, t: ""))
        self.assertIsNone(ca.discover_access_app("command.meshly.fr", login_redirect=lambda url, t: "https://example.com/"))

        def offline(url, timeout):
            raise OSError("offline")

        self.assertIsNone(ca.discover_access_app("command.meshly.fr", login_redirect=offline))

    def test_configured_app_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cloudflare_access.json"
            self.assertIsNone(ca.configured_access_app(path))
            path.write_text(json.dumps({"team": TEAM, "aud": AUD}))
            self.assertEqual(ca.configured_access_app(path), (TEAM, AUD))
            path.write_text(json.dumps({"team": "evil.example.com", "aud": AUD}))
            self.assertIsNone(ca.configured_access_app(path))


class AccessGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = _keypair(2048, seed=7)
        cls.keys = {"k1": _jwk(cls.key[0], cls.key[1], "k1")}

    def setUp(self):
        self.now = NOW
        self.discovered = []
        self.fetched = []

    def _gate(self, app=(TEAM, AUD)):
        def discover(host):
            self.discovered.append(host)
            return app

        def fetch(team):
            self.fetched.append(team)
            return self.keys

        return ca.AccessGate("command.meshly.fr", discover=discover, fetch_keys=fetch, clock=lambda: self.now)

    def test_owner_is_recognised_and_lookups_are_cached(self):
        gate = self._gate()
        token = _sign(_claims(), self.key)
        self.assertEqual(gate.owner_email(token), "owner@example.com")
        self.assertEqual(gate.owner_email(token), "owner@example.com")
        self.assertEqual((self.discovered, self.fetched), (["command.meshly.fr"], [TEAM]))

    def test_without_access_nothing_is_trusted_and_no_keys_are_fetched(self):
        gate = self._gate(app=None)
        self.assertIsNone(gate.owner_email(_sign(_claims(), self.key)))
        self.assertEqual(self.fetched, [])

    def test_unknown_key_refetches_at_most_once_a_minute(self):
        gate = self._gate()
        gate.owner_email(_sign(_claims(), self.key))
        for _ in range(3):
            gate.owner_email(_sign(_claims(), self.key, kid="rotated"))
        self.assertEqual(len(self.fetched), 1)
        self.now += ca.KEYS_RETRY_SECONDS
        for _ in range(3):
            gate.owner_email(_sign(_claims(), self.key, kid="rotated"))
        self.assertEqual(len(self.fetched), 2)


class ServerAccessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = _keypair(2048, seed=7)
        keys = {"k1": _jwk(cls.key[0], cls.key[1], "k1")}
        cls.gate = ca.AccessGate("command.meshly.fr", discover=lambda host: (TEAM, AUD), fetch_keys=lambda team: keys, clock=lambda: NOW)

    def _handler(self, headers: dict, command: str = "GET"):
        handler = SERVER.Handler.__new__(SERVER.Handler)
        handler.headers = {"Host": "command.meshly.fr", **headers}
        handler.command = command
        return handler

    def _authorized(self, headers: dict, command: str = "GET") -> tuple[bool, bool]:
        handler = self._handler(headers, command)
        with patch.object(SERVER, "OWNER_ACCESS", self.gate), patch.object(SERVER, "_dashboard_run_token", return_value="owner-token"):
            return handler._dashboard_run_authorized(), handler._decision_owner_authorized()

    def test_signed_in_owner_sees_everything_without_the_key(self):
        token = _sign(_claims(), self.key)
        self.assertEqual(self._authorized({"Cf-Access-Jwt-Assertion": token}), (True, True))

    def test_writes_need_the_page_itself_as_origin(self):
        token = _sign(_claims(), self.key)
        self.assertEqual(self._authorized({"Cf-Access-Jwt-Assertion": token}, "POST"), (False, False))
        self.assertEqual(self._authorized({"Cf-Access-Jwt-Assertion": token, "Origin": "https://evil.example"}, "POST"), (False, False))
        self.assertEqual(self._authorized({"Cf-Access-Jwt-Assertion": token, "Origin": "https://command.meshly.fr"}, "POST"), (True, True))

    def test_forged_header_falls_back_to_the_owner_key(self):
        forged = _sign(_claims(), _keypair(2048, seed=11))
        self.assertEqual(self._authorized({"Cf-Access-Jwt-Assertion": forged}), (False, False))
        self.assertEqual(self._authorized({"Cf-Access-Jwt-Assertion": forged, "X-Dashboard-Run-Token": "owner-token"}), (True, True))

    def test_no_access_header_keeps_the_old_rules(self):
        self.assertEqual(self._authorized({}), (False, False))
        self.assertEqual(self._authorized({"X-Dashboard-Run-Token": "owner-token"}), (True, True))


if __name__ == "__main__":
    unittest.main()
