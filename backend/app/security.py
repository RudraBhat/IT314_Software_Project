"""Password hashing (Argon2id), signed tokens (JWT HS256) and TOTP MFA secrets."""

import secrets
import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings

_hasher = PasswordHasher()  # Argon2id with library-recommended parameters
# Verified against when the account does not exist, so response time does not
# reveal whether an email is registered.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))

ACCESS = "access"
MFA = "mfa"
_ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        # A malformed stored hash (e.g. a seed placeholder) is a failed login, never a crash.
        return False


def _secret() -> str:
    secret = get_settings().require("jwt_secret")
    if len(secret) < 32:
        raise RuntimeError("JWT_SECRET must be at least 32 characters")
    return secret


def issue_token(
    user_id: uuid.UUID, token_version: int, purpose: str, minutes: int, mfa: bool = False
) -> str:
    now = datetime.now(UTC)
    claims = {
        "sub": str(user_id),
        "tv": token_version,
        "purpose": purpose,
        "mfa": mfa,
        "iat": now,
        "exp": now + timedelta(minutes=minutes),
        "jti": secrets.token_hex(8),
    }
    return jwt.encode(claims, _secret(), algorithm=_ALGORITHM)


def decode_token(token: str, purpose: str) -> dict | None:
    try:
        claims = jwt.decode(
            token,
            _secret(),
            algorithms=[_ALGORITHM],
            options={"require": ["sub", "tv", "purpose", "exp", "iat"]},
        )
    except jwt.PyJWTError:
        return None
    if claims.get("purpose") != purpose:
        return None
    return claims


def _fernet() -> Fernet:
    key = get_settings().mfa_encryption_key
    if not key:
        # Derive a stable 32-byte Fernet key from JWT_SECRET when explicit key is omitted
        import base64
        import hashlib

        secret_bytes = _secret().encode()
        key = base64.urlsafe_b64encode(hashlib.sha256(secret_bytes).digest()).decode()
    return Fernet(key.encode())


def new_totp_secret() -> str:
    return pyotp.random_base32()


def encrypt_mfa_secret(secret: str) -> bytes:
    return _fernet().encrypt(secret.encode())


def decrypt_mfa_secret(blob: bytes | memoryview | None) -> str | None:
    if blob is None:
        return None
    try:
        return _fernet().decrypt(bytes(blob)).decode()
    except InvalidToken:
        return None


def verify_totp(secret: str, code: str) -> bool:
    code = code.strip().replace(" ", "")
    if not code.isdigit() or len(code) != 6:
        return False
    return pyotp.TOTP(secret).verify(code, valid_window=1)


def provisioning_uri(secret: str, email: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name="ResQ")
