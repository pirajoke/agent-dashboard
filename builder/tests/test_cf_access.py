from __future__ import annotations

import base64
import json
from pathlib import Path
import sys
import tempfile
import unittest

try:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding, rsa
except ImportError:  # pragma: no cover
    rsa = None

BUILDER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BUILDER_DIR))

from dashboard_builder import cf_access  # noqa: E402

TEAM = "owner-team.cloudflareaccess.com"
AUD = "aud-tag-123"
NOW = 1_800_000_000


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


@unittest.skipIf(rsa is None, "cryptography is not installed")
class CloudflareAccessTest(unittest.TestCase):
    def setUp(self):
        cf_access._keys_cache.clear()
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.config = {"team_domain": TEAM, "aud": AUD, "emails": {"owner@example.com"}}
        self.fetch = lambda team: {"k1": self.key.public_key()}

    def _token(self, key=None, kid="k1", **overrides) -> str:
        claims = {"aud": [AUD], "iss": f"https://{TEAM}", "email": "Owner@Example.com",
                  "exp": NOW + 600, "nbf": NOW - 10}
        claims.update(overrides)
        head = _b64(json.dumps({"alg": "RS256", "kid": kid}).encode())
        body = _b64(json.dumps(claims).encode())
        signature = (key or self.key).sign(f"{head}.{body}".encode(), padding.PKCS1v15(), hashes.SHA256())
        return f"{head}.{body}.{_b64(signature)}"

    def _email(self, token: str | None, config=None):
        headers = {cf_access.HEADER: token} if token is not None else {}
        return cf_access.owner_email(headers, self.config if config is None else config, now=NOW, fetch=self.fetch)

    def test_valid_sign_in_of_the_owner_is_recognised(self):
        self.assertEqual(self._email(self._token()), "owner@example.com")

    def test_forged_expired_or_foreign_tokens_unlock_nothing(self):
        self.assertIsNone(self._email(None))
        self.assertIsNone(self._email("not-a-jwt"))
        self.assertIsNone(self._email(self._token(key=self.other)))
        self.assertIsNone(self._email(self._token(kid="unknown")))
        self.assertIsNone(self._email(self._token(exp=NOW - 3600)))
        self.assertIsNone(self._email(self._token(nbf=NOW + 3600)))
        self.assertIsNone(self._email(self._token(aud=["another-app"])))
        self.assertIsNone(self._email(self._token(iss="https://evil.cloudflareaccess.com")))
        self.assertIsNone(self._email(self._token(email="someone@example.com")))

    def test_without_configuration_the_owner_token_stays_the_only_way_in(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "cf_access.json"
            self.assertIsNone(cf_access.load_config(missing))
            missing.write_text(json.dumps({"team_domain": "example.com", "aud": AUD, "emails": ["a@b.c"]}))
            self.assertIsNone(cf_access.load_config(missing))
            missing.write_text(json.dumps({"team_domain": f"https://{TEAM}/", "aud": AUD, "emails": ["A@B.C"]}))
            self.assertEqual(cf_access.load_config(missing),
                             {"team_domain": TEAM, "aud": AUD, "emails": {"a@b.c"}})
        self.assertIsNone(self._email(self._token(), config={}))


if __name__ == "__main__":
    unittest.main()
