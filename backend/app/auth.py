"""
Authentication helpers: password hashing and JWT access tokens.

Password hashing uses Python's built-in `hashlib.pbkdf2_hmac` (PBKDF2-HMAC-SHA256,
600,000 iterations per OWASP's current minimum recommendation) rather than
bcrypt/argon2. This is a deliberate simplicity trade-off for a project meant
to be easy to `pip install` on any machine (bcrypt needs a compiled C
extension, which occasionally causes install headaches on Windows) -- PBKDF2
via the standard library needs nothing extra. It's meaningfully weaker than
argon2id against a determined, well-resourced attacker with the hash in hand,
but is a reasonable choice for a local/small-scale tool. If you deploy this
somewhere with real adversaries, swap this module for `passlib[argon2]`.

JWT access tokens (via PyJWT) carry the user's id as `sub` and an expiry;
the frontend sends them back as `Authorization: Bearer <token>`.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import os

import jwt

from app.config import settings

_PBKDF2_ITERATIONS = 600_000
_SALT_BYTES = 16


def hash_password(password: str) -> str:
    salt = os.urandom(_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    return f"{salt.hex()}${digest.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        salt_hex, digest_hex = stored_hash.split("$", 1)
    except ValueError:
        return False
    salt = bytes.fromhex(salt_hex)
    expected = bytes.fromhex(digest_hex)
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    return hmac.compare_digest(actual, expected)  # constant-time comparison, avoids timing attacks


def create_access_token(user_id: str) -> str:
    now = dt.datetime.utcnow()
    payload = {
        "sub": user_id,
        "iat": now,
        "exp": now + dt.timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> str | None:
    """Returns the user_id (sub claim) if the token is valid and unexpired, else None."""
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        return payload.get("sub")
    except jwt.PyJWTError:
        return None
