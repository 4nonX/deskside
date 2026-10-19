"""Local accounts and sessions.

Passwords are hashed with scrypt from the standard library. Sessions are
signed cookies (itsdangerous) holding the user id, valid for 12 hours.
OpenID Connect sign-in is planned for a later milestone and will map to the
same roles.

Roles, from least to most: ``viewer`` (read), ``editor`` (devices, notes),
``admin`` (users and everything else).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os

from fastapi import Depends, HTTPException, Request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import select

from .db import Database, User

ROLES = ("viewer", "editor", "admin")
COOKIE = "deskside_session"
MAX_AGE = 12 * 3600
_N, _R, _P = 2**14, 8, 1


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return "scrypt${}${}${}${}${}".format(_N, _R, _P, base64.b64encode(salt).decode(), base64.b64encode(digest).decode())


def verify_password(password: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, digest = stored.split("$")
        calc = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p),
                              dklen=len(base64.b64decode(digest)))
        return hmac.compare_digest(calc, base64.b64decode(digest))
    except (ValueError, TypeError):
        return False


class Sessions:
    def __init__(self, secret: str) -> None:
        self.ser = URLSafeTimedSerializer(secret, salt="deskside-session")

    def issue(self, user: User) -> str:
        return self.ser.dumps({"uid": user.id})

    def read(self, token: str) -> int | None:
        try:
            return int(self.ser.loads(token, max_age=MAX_AGE)["uid"])
        except (BadSignature, SignatureExpired, KeyError, ValueError, TypeError):
            return None


def ensure_admin(db: Database, password: str | None) -> str | None:
    """Create the first admin account if there is no user yet. Returns a message for the log."""
    with db.session() as s:
        if s.scalar(select(User.id).limit(1)) is not None:
            return None
        if not password:
            return ("no users exist and no admin password is configured; set DESKSIDE_ADMIN_PASSWORD "
                    "(or server.admin_password) and restart to create the 'admin' account")
        s.add(User(username="admin", password_hash=hash_password(password), role="admin"))
        return "created the initial 'admin' account"


def current_user(request: Request) -> User:
    app = request.app.state
    uid = app.sessions.read(request.cookies.get(COOKIE, ""))
    if uid is None:
        raise HTTPException(401, "Please sign in.")
    with app.db.session() as s:
        user = s.get(User, uid)
        if user is None:
            raise HTTPException(401, "Please sign in.")
        s.expunge(user)
        return user


def require(role: str):
    """Dependency factory: the signed-in user must have at least ``role``."""
    need = ROLES.index(role)

    def dep(request: Request, user: User = Depends(current_user)) -> User:
        if ROLES.index(user.role) < need:
            raise HTTPException(403, f"This needs the {role} role.")
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            # State-changing requests must be JSON. Browsers cannot send that cross-site without a
            # CORS preflight, which deskside never allows, so this blocks cross-site request forgery.
            ctype = request.headers.get("content-type", "")
            if request.method != "DELETE" and not ctype.startswith("application/json"):
                raise HTTPException(415, "Send JSON.")
            if request.method == "DELETE" and request.headers.get("x-requested-with") != "deskside":
                raise HTTPException(400, "Missing X-Requested-With header.")
        return user

    return dep
