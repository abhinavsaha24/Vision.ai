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

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import InvalidTokenError

from backend.src.core.config import settings

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
    payload.update({"exp": expire})
    token = jwt.encode(payload, _get_secret_key(), algorithm=ALGORITHM)
    return token


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
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
):
    """
    Extract and validate JWT from Authorization header.
    Returns the decoded payload dict with user_id, role, etc.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_token(credentials.credentials)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
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
