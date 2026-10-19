"""Sign-in with OpenID Connect against a simulated identity provider."""

import base64
import hashlib
import json
import time
from urllib.parse import parse_qs, urlparse

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from deskside.config import ConfigError, Settings, load
from deskside.main import create_app

ISSUER = "https://sso.example.org/application/o/deskside/"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class FakeIdp:
    def __init__(self):
        self.groups = ["IT"]
        self.nonce = None
        self.challenge = None
        self.sign_with = KEY
        self.override_nonce = None

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/.well-known/openid-configuration"):
            return httpx.Response(200, json={
                "issuer": ISSUER, "authorization_endpoint": "https://sso.example.org/authorize/",
                "token_endpoint": "https://sso.example.org/token/", "jwks_uri": "https://sso.example.org/jwks/",
                "end_session_endpoint": "https://sso.example.org/end/"})
        if path == "/jwks/":
            jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(KEY.public_key()))
            jwk.update(kid="k1", use="sig", alg="RS256")
            return httpx.Response(200, json={"keys": [jwk]})
        if path == "/token/":
            form = parse_qs(request.content.decode())
            verifier = form["code_verifier"][0]
            calc = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
            if form["code"] != ["good-code"] or calc != self.challenge or form["client_secret"] != ["s3cret"]:
                return httpx.Response(400, json={"error": "invalid_grant"})
            t = int(time.time())
            claims = {"iss": ISSUER, "aud": "deskside-client", "sub": "u-1", "iat": t, "exp": t + 300,
                      "nonce": self.override_nonce or self.nonce, "preferred_username": "ada", "groups": self.groups}
            token = jwt.encode(claims, self.sign_with, algorithm="RS256", headers={"kid": "k1"})
            return httpx.Response(200, json={"access_token": "x", "id_token": token, "token_type": "Bearer"})
        return httpx.Response(404)


def make_client(tmp_path, local_login=False):
    s = Settings(database_url=f"sqlite:///{tmp_path}/t.db", secret_key="k" * 40, local_login=local_login,
                 public_url="https://deskside.example.org", admin_password="initial-password",
                 oidc={"issuer": ISSUER, "client_id": "deskside-client", "client_secret": "s3cret",
                       "label": "Example SSO", "roles": {"admin": ["IT"], "viewer": ["Staff"]}})
    s.raw = {"dns": {"reverse": False}}
    return TestClient(create_app(s), base_url="https://deskside.example.org", follow_redirects=False)


def sign_in(c, idp, code="good-code", tamper_state=False):
    r = c.get("/api/auth/start", params={"next": "/?view=map"})
    assert r.status_code == 303
    q = parse_qs(urlparse(r.headers["location"]).query)
    assert q["code_challenge_method"] == ["S256"] and q["redirect_uri"] == ["https://deskside.example.org/api/auth/callback"]
    idp.nonce, idp.challenge = q["nonce"][0], q["code_challenge"][0]
    state = "forged" if tamper_state else q["state"][0]
    return c.get("/api/auth/callback", params={"code": code, "state": state})


@pytest.fixture
def setup(tmp_path):
    idp = FakeIdp()
    with make_client(tmp_path) as c:
        c.app.state.oidc.transport = httpx.MockTransport(idp.handler)
        yield c, idp


def test_sign_in_maps_groups_to_role_and_keeps_the_target(setup):
    c, idp = setup
    assert c.get("/api/auth/config").json() == {"local_login": False, "sso": "Example SSO"}
    r = sign_in(c, idp)
    assert r.status_code == 303 and r.headers["location"] == "/?view=map"
    assert c.get("/api/me").json()["username"] == "ada" and c.get("/api/me").json()["role"] == "admin"
    assert any(u["username"] == "ada" and u["source"] == "sso" for u in c.get("/api/users").json())


def test_groups_are_checked_on_every_sign_in(setup):
    c, idp = setup
    sign_in(c, idp)
    idp.groups = ["Staff"]
    sign_in(c, idp)
    assert c.get("/api/me").json()["role"] == "viewer"
    idp.groups = ["Kitchen"]
    r = sign_in(c, idp)
    assert "login_error=" in r.headers["location"] and "group" in r.headers["location"]


@pytest.mark.parametrize("problem", ["state", "nonce", "key", "code"])
def test_refuses_forged_or_foreign_responses(setup, problem):
    c, idp = setup
    if problem == "nonce":
        idp.override_nonce = "someone-elses"
    if problem == "key":
        idp.sign_with = OTHER_KEY
    r = sign_in(c, idp, code="bad" if problem == "code" else "good-code", tamper_state=problem == "state")
    assert "login_error=" in r.headers["location"]
    assert c.get("/api/me").status_code == 401


def test_local_login_switched_off(setup):
    c, idp = setup
    assert c.post("/api/login", json={"username": "admin", "password": "initial-password"}).status_code == 403


def test_sso_accounts_cannot_use_a_password(tmp_path):
    idp = FakeIdp()
    with make_client(tmp_path, local_login=True) as c:
        c.app.state.oidc.transport = httpx.MockTransport(idp.handler)
        sign_in(c, idp)
        c.cookies.clear()
        assert c.post("/api/login", json={"username": "ada", "password": "!sso"}).status_code == 401
        assert c.post("/api/login", json={"username": "admin", "password": "initial-password"}).status_code == 200


def test_config_needs_a_way_in(tmp_path):
    cfg = tmp_path / "c.yaml"
    cfg.write_text("server:\n  secret_key: " + "k" * 40 + "\nauth:\n  local_login: false\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load(str(cfg))
    cfg.write_text("server:\n  secret_key: " + "k" * 40 + "\nauth:\n  oidc:\n    issuer: https://sso.example.org/\n"
                   "    client_id: a\n    client_secret: b\n    roles: {admin: []}\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="at least one group"):
        load(str(cfg))
