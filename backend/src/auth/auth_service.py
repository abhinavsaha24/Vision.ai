"""
Authentication and authorization service.

Features:
  - JWT token creation and verification
  - bcrypt password hashing
  - FastAPI dependency injection for route protection
  - Role-based access control (admin, user)
"""

import logging
from datetime import datetime, timedelta, timezone
import uuid

import bcrypt
import jwt
import pyotp
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import InvalidTokenError

from backend.src.core.config import settings
from backend.src.database.db import get_connection, release_connection

# --------------------------------------------------
# Security Settings
# --------------------------------------------------

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60
logger = logging.getLogger(__name__)


def _get_secret_key() -> str:
    """Resolve JWT secret from environment-backed settings."""
    secret = (settings.jwt_secret or "").strip()

    if secret:
        return secret

    raise RuntimeError("JWT_SECRET environment variable must be set")


# Bearer token scheme
bearer_scheme = HTTPBearer(auto_error=False)


# --------------------------------------------------
# Password Utilities
# --------------------------------------------------


def hash_password(password: str) -> str:
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode("utf-8"), salt)
    return hashed.decode("utf-8")


def verify_password(password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(
            password.encode("utf-8"),
            hashed_password.encode("utf-8"),
        )
    except Exception:
        return False


# --------------------------------------------------
# Token Creation
# --------------------------------------------------


def create_access_token(data: dict, expires_minutes: int = ACCESS_TOKEN_EXPIRE_MINUTES):
    payload = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=expires_minutes)
    payload.update({"exp": expire, "iat": datetime.now(timezone.utc), "jti": str(uuid.uuid4())})
    token = jwt.encode(payload, _get_secret_key(), algorithm=ALGORITHM)
    return token


def is_token_revoked(token_jti: str) -> bool:
    if not token_jti:
        return False
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT 1 FROM token_revocations WHERE token_jti=%s LIMIT 1",
            (token_jti,),
        )
        return cur.fetchone() is not None
    except Exception:
        return False
    finally:
        if conn is not None:
            release_connection(conn)


def revoke_token_jti(token_jti: str, exp_claim: int | None = None) -> None:
    if not token_jti:
        return
    expires_at = datetime.now(timezone.utc)
    if isinstance(exp_claim, int):
        expires_at = datetime.fromtimestamp(exp_claim, tz=timezone.utc)

    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO token_revocations (token_jti, expires_at, revoked_at)
            VALUES (%s, %s, %s)
            ON CONFLICT (token_jti) DO NOTHING
            """,
            (token_jti, expires_at, datetime.now(timezone.utc)),
        )
        conn.commit()
    except Exception:
        if conn is not None:
            conn.rollback()
    finally:
        if conn is not None:
            release_connection(conn)


# --------------------------------------------------
# Token Verification
# --------------------------------------------------


def decode_token(token: str):
    try:
        payload = jwt.decode(token, _get_secret_key(), algorithms=[ALGORITHM])
        return payload
    except InvalidTokenError:
        return None


# --------------------------------------------------
# FastAPI Dependencies — JWT Protection
# --------------------------------------------------


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
):
    """
    Extract and validate JWT from Authorization header.
    Returns the decoded payload dict with user_id, role, etc.
    """
    header_token = credentials.credentials if credentials is not None else None
    cookie_token = (request.cookies.get(settings.session_cookie_name) or "").strip() or None

    token = header_token or cookie_token

    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_token(token)
    if payload is None and header_token and cookie_token:
        # Graceful fallback when a stale/invalid bearer header coexists with a valid session cookie.
        payload = decode_token(cookie_token)

    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if is_token_revoked(str(payload.get("jti") or "")):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been revoked",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return payload


async def require_admin(
    current_user: dict = Depends(get_current_user),
):
    """
    Dependency that enforces admin role.
    """
    if current_user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return current_user


def _verify_step_up_code(code: str) -> bool:
    secret = (settings.mfa_totp_secret or "").strip()
    if not secret:
        return False
    try:
        totp = pyotp.TOTP(secret)
        return bool(totp.verify(code, valid_window=max(0, int(settings.mfa_step_up_window))))
    except Exception:
        return False


async def require_admin_step_up(
    request: Request,
    current_user: dict = Depends(require_admin),
):
    """
    Enforce MFA step-up for sensitive admin operations when enabled.
    """
    if not bool(settings.mfa_step_up_enabled):
        return current_user

    code = (request.headers.get("X-MFA-Code") or "").strip()
    if not code:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="MFA step-up required",
        )

    if not _verify_step_up_code(code):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid MFA code",
        )

    return current_user
