"""Password hashing (Argon2id), JWT access tokens, opaque refresh tokens."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import settings
from app.core.errors import unauthenticated

_ph = PasswordHasher()  # argon2id defaults
_DUMMY_HASH = _ph.hash("timing-equaliser-password")


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    try:
        return _ph.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def create_access_token(user_id: uuid.UUID) -> str:
    now = datetime.now(UTC)
    claims: dict[str, Any] = {
        "sub": str(user_id),
        "type": "access",
        "iat": now,
        "exp": now + timedelta(seconds=settings.ACCESS_TOKEN_TTL_SECONDS),
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(claims, settings.jwt_secret, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> uuid.UUID:
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.JWT_ALGORITHM],
            options={"require": ["sub", "exp", "iat", "type"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise unauthenticated("Access token expired", code="TOKEN_EXPIRED") from exc
    except jwt.PyJWTError as exc:
        raise unauthenticated("Invalid access token") from exc
    if claims.get("type") != "access":
        raise unauthenticated("Invalid token type")
    try:
        return uuid.UUID(claims["sub"])
    except ValueError as exc:
        raise unauthenticated("Invalid token subject") from exc


def new_refresh_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def key_hint(secret: str) -> str:
    return "••••" + (secret[-4:] if len(secret) >= 8 else "")
