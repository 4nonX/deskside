"""Sign-in with OpenID Connect (Authorization Code flow with PKCE).

The browser is sent to the identity provider; the code that comes back is
exchanged for tokens by the backend, never in the browser. The ID token is
checked against the provider's published keys (JWKS) for signature, issuer,
audience, lifetime and the nonce of this very sign-in. The groups in the token
decide the role: the first role whose group list matches wins, checked from
admin down to viewer. Someone in none of the configured groups is not let in.

Configuration (``auth.oidc``)::

    issuer: https://sso.example.org/application/o/deskside/
    client_id_file: /run/secrets/oidc_client_id
    client_secret_file: /run/secrets/oidc_client_secret
    roles: {admin: [IT], editor: [], viewer: []}

Optional: ``scopes`` (default openid profile email), ``username_claim``
(default preferred_username), ``groups_claim`` (default groups), ``label`` for
the sign-in button, ``redirect_url`` (default ``<public_url>/api/auth/callback``),
``verify_tls`` and ``ca_file`` (see tls.py).
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import time
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from . import tls

ROLE_ORDER = ("admin", "editor", "viewer")
STATE_COOKIE = "deskside_oidc"
STATE_MAX_AGE = 600
ALGORITHMS = ["RS256", "RS384", "RS512", "ES256", "ES384", "ES512", "PS256"]


class OidcError(Exception):
    """Configuration or sign-in problem; the message is safe to show."""


class Oidc:
    def __init__(self, conf: dict[str, Any], secret_key: str, public_url: str | None) -> None:
        for key in ("issuer", "client_id", "client_secret"):
            if not conf.get(key):
                raise OidcError(f"auth.oidc.{key} is required")
        self.conf = conf
        self.issuer = str(conf["issuer"]).rstrip("/") + "/"
        self.client_id = str(conf["client_id"])
        self.client_secret = str(conf["client_secret"])
        self.scopes = conf.get("scopes") or ["openid", "profile", "email"]
        if "openid" not in self.scopes:
            raise OidcError("auth.oidc.scopes must contain openid")
        self.username_claim = conf.get("username_claim", "preferred_username")
        self.groups_claim = conf.get("groups_claim", "groups")
        self.label = conf.get("label") or "Single sign-on"
        roles = conf.get("roles") or {}
        if not isinstance(roles, dict) or set(roles) - set(ROLE_ORDER):
            raise OidcError("auth.oidc.roles maps admin, editor and viewer to lists of groups")
        self.roles = {r: {str(g).lower() for g in roles.get(r) or []} for r in ROLE_ORDER}
        if not any(self.roles.values()):
            raise OidcError("auth.oidc.roles must name at least one group, otherwise nobody could sign in")
        base = (conf.get("redirect_url") or "").strip()
        if not base:
            if not public_url:
                raise OidcError("set server.public_url or auth.oidc.redirect_url for the sign-in callback")
            base = public_url.rstrip("/") + "/api/auth/callback"
        self.redirect_url = base
        self.state = URLSafeTimedSerializer(secret_key, salt="deskside-oidc-state")
        self.transport: httpx.BaseTransport | None = None    # tests replace this
        self._meta: dict[str, Any] | None = None
        self._meta_at = 0.0
        self._jwks: dict[str, Any] | None = None

    # --- provider metadata and keys -----------------------------------------------------------
    def _client(self) -> httpx.Client:
        return httpx.Client(timeout=15, verify=tls.verify(self.conf), transport=self.transport)

    def metadata(self) -> dict[str, Any]:
        if self._meta is None or time.time() - self._meta_at > 3600:
            with self._client() as cl:
                r = cl.get(self.issuer + ".well-known/openid-configuration")
            if r.is_error:
                raise OidcError(f"the identity provider's discovery document answered {r.status_code}")
            meta = r.json()
            if meta.get("issuer", "").rstrip("/") + "/" != self.issuer:
                raise OidcError("the identity provider reports a different issuer than configured")
            self._meta, self._meta_at, self._jwks = meta, time.time(), None
        return self._meta

    def _keys(self, refresh: bool = False) -> dict[str, Any]:
        if self._jwks is None or refresh:
            with self._client() as cl:
                r = cl.get(self.metadata()["jwks_uri"])
            if r.is_error:
                raise OidcError(f"the identity provider's key list answered {r.status_code}")
            self._jwks = r.json()
        return self._jwks

    def _key_for(self, token: str) -> Any:
        kid = jwt.get_unverified_header(token).get("kid")
        for refresh in (False, True):            # keys rotate; fetch once more before giving up
            for k in self._keys(refresh).get("keys", []):
                if kid is None or k.get("kid") == kid:
                    return jwt.PyJWK(k).key
        raise OidcError("the ID token is signed with an unknown key")

    # --- the flow -------------------------------------------------------------------------------
    def start(self, next_path: str = "/") -> tuple[str, str]:
        """URL to send the browser to, and the signed state for the short-lived cookie."""
        verifier = secrets.token_urlsafe(48)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        state, nonce = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
        params = {"response_type": "code", "client_id": self.client_id, "redirect_uri": self.redirect_url,
                  "scope": " ".join(self.scopes), "state": state, "nonce": nonce,
                  "code_challenge": challenge, "code_challenge_method": "S256"}
        url = self.metadata()["authorization_endpoint"] + "?" + urlencode(params)
        cookie = self.state.dumps({"s": state, "n": nonce, "v": verifier,
                                   "next": next_path if next_path.startswith("/") and not next_path.startswith("//") else "/"})
        return url, cookie

    def finish(self, code: str, state: str, cookie: str) -> dict[str, Any]:
        """Exchange the code, check the ID token, and return the user's name, groups and role."""
        try:
            saved = self.state.loads(cookie, max_age=STATE_MAX_AGE)
        except (BadSignature, SignatureExpired) as exc:
            raise OidcError("the sign-in took too long or was started elsewhere; please try again") from exc
        if not secrets.compare_digest(str(saved.get("s")), state):
            raise OidcError("the sign-in response does not belong to this browser; please try again")
        meta = self.metadata()
        with self._client() as cl:
            r = cl.post(meta["token_endpoint"], data={
                "grant_type": "authorization_code", "code": code, "redirect_uri": self.redirect_url,
                "code_verifier": saved["v"], "client_id": self.client_id, "client_secret": self.client_secret})
        if r.is_error:
            raise OidcError(f"the identity provider refused the sign-in code ({r.status_code})")
        token = r.json().get("id_token")
        if not token:
            raise OidcError("the identity provider sent no ID token")
        try:
            claims = jwt.decode(token, self._key_for(token), algorithms=ALGORITHMS, audience=self.client_id,
                                issuer=meta["issuer"], options={"require": ["exp", "iat", "iss", "aud", "sub"]},
                                leeway=60)
        except jwt.PyJWTError as exc:
            raise OidcError(f"the ID token is not valid: {exc}") from exc
        if not secrets.compare_digest(str(claims.get("nonce", "")), str(saved["n"])):
            raise OidcError("the ID token does not belong to this sign-in")
        username = str(claims.get(self.username_claim) or claims.get("sub"))
        groups = claims.get(self.groups_claim) or []
        groups = [groups] if isinstance(groups, str) else list(groups)
        role = self.role_for(groups)
        return {"username": username[:100], "groups": groups, "role": role, "next": saved.get("next", "/"),
                "logout_url": meta.get("end_session_endpoint")}

    def role_for(self, groups: list[str]) -> str | None:
        have = {str(g).lower() for g in groups}
        for role in ROLE_ORDER:
            if self.roles[role] & have:
                return role
        return None
