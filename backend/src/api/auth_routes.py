"""
Authentication API routes.

Endpoints:
  POST /auth/signup    - create new account
  POST /auth/register  - alias for signup
  POST /auth/login     - authenticate and get JWT
  GET  /auth/me        - get current user info (requires JWT)
    POST /auth/logout    - clear session cookie
"""

from collections import defaultdict, deque
import json
import secrets
import time
from datetime import datetime, timezone
from threading import Lock

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr

from backend.src.auth.auth_service import (bearer_scheme, create_access_token,
                                           decode_token, get_current_user,
                                           hash_password, revoke_token_jti,
                                           verify_password)
from backend.src.core.config import settings
from backend.src.database.db import get_connection, release_connection
from fastapi.security import HTTPAuthorizationCredentials

router = APIRouter()

MIN_PASSWORD_LENGTH = 10
SESSION_COOKIE_SAMESITE = "lax"
_FAILED_LOGIN_ATTEMPTS: dict[str, deque[float]] = defaultdict(deque)
_LOGIN_LOCKED_UNTIL: dict[str, float] = {}
_LOGIN_GUARD_LOCK = Lock()


def _cookie_secure() -> bool:
    if settings.session_cookie_secure is not None:
        return bool(settings.session_cookie_secure)
    return str(settings.environment or "").strip().lower() == "production"


def _set_session_cookie(response: JSONResponse, token: str) -> None:
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        httponly=True,
        secure=_cookie_secure(),
        samesite=SESSION_COOKIE_SAMESITE,
        max_age=int(settings.session_cookie_max_age_seconds),
        path="/",
    )
    response.set_cookie(
        key=settings.csrf_cookie_name,
        value=secrets.token_urlsafe(32),
        httponly=False,
        secure=_cookie_secure(),
        samesite=SESSION_COOKIE_SAMESITE,
        max_age=int(settings.session_cookie_max_age_seconds),
        path="/",
    )


def _clear_session_cookie(response: JSONResponse) -> None:
    response.delete_cookie(
        key=settings.session_cookie_name,
        path="/",
        httponly=True,
        secure=_cookie_secure(),
        samesite=SESSION_COOKIE_SAMESITE,
    )
    response.delete_cookie(
        key=settings.csrf_cookie_name,
        path="/",
        httponly=False,
        secure=_cookie_secure(),
        samesite=SESSION_COOKIE_SAMESITE,
    )


def _auth_audit(
    action: str,
    status: str,
    details: dict,
    request: Request | None = None,
    user_id: int | None = None,
) -> None:
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        request_id = None
        if request is not None:
            request_id = (
                request.headers.get("X-Request-ID")
                or request.headers.get("X-Correlation-ID")
                or None
            )
        payload = json.dumps(details, default=str)
        cur.execute(
            """
            INSERT INTO audit_log (user_id, action, status, details_json, request_id, created_at)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                user_id,
                action,
                status,
                payload,
                request_id,
                datetime.now(timezone.utc),
            ),
        )
        conn.commit()
    except Exception:
        if conn is not None:
            conn.rollback()
    finally:
        if conn is not None:
            release_connection(conn)


def _validate_password_strength(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"Password must be at least {MIN_PASSWORD_LENGTH} characters",
        )
    if not any(ch.isalpha() for ch in password) or not any(ch.isdigit() for ch in password):
        raise HTTPException(
            status_code=400,
            detail="Password must include at least one letter and one number",
        )


def _client_ip(request: Request | None) -> str:
    if request is None or request.client is None:
        return "unknown"
    return str(request.client.host or "unknown")


def _login_key(email: str, request: Request | None) -> str:
    return f"{email.strip().lower()}|{_client_ip(request)}"


def _is_signup_allowed() -> bool:
    env_name = str(settings.environment or "").strip().lower()
    if env_name in {"development", "dev", "local", "test"}:
        return True
    return bool(settings.allow_public_signup)


def _check_login_lock(login_key: str) -> int:
    now = time.time()
    with _LOGIN_GUARD_LOCK:
        expires_at = _LOGIN_LOCKED_UNTIL.get(login_key)
        if expires_at is None:
            return 0
        if expires_at <= now:
            _LOGIN_LOCKED_UNTIL.pop(login_key, None)
            return 0
        return max(1, int(expires_at - now))


def _record_failed_login(login_key: str) -> bool:
    now = time.time()
    window = max(int(settings.auth_lockout_window_seconds), 1)
    threshold = max(int(settings.auth_lockout_threshold), 1)
    duration = max(int(settings.auth_lockout_duration_seconds), 1)

    with _LOGIN_GUARD_LOCK:
        attempts = _FAILED_LOGIN_ATTEMPTS[login_key]
        while attempts and (now - attempts[0]) > window:
            attempts.popleft()
        attempts.append(now)
        if len(attempts) >= threshold:
            _LOGIN_LOCKED_UNTIL[login_key] = now + duration
            attempts.clear()
            return True
    return False


def _clear_login_failures(login_key: str) -> None:
    with _LOGIN_GUARD_LOCK:
        _FAILED_LOGIN_ATTEMPTS.pop(login_key, None)
        _LOGIN_LOCKED_UNTIL.pop(login_key, None)


# --------------------------------------------------
# Request Models
# --------------------------------------------------


class SignupRequest(BaseModel):
    email: EmailStr
    password: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


# --------------------------------------------------
# Signup / Register
# --------------------------------------------------


def _do_signup(req: SignupRequest, request: Request):
    """Shared signup logic for both /signup and /register."""
    _validate_password_strength(req.password)

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM users WHERE email=%s", (req.email,))
    existing = cursor.fetchone()

    if existing:
        release_connection(conn)
        # Return generic success response to reduce account enumeration signal.
        _auth_audit(
            action="auth_signup",
            status="exists",
            details={"email": req.email},
            request=request,
        )
        return {"status": "user created"}

    hashed = hash_password(req.password)

    cursor.execute(
        "INSERT INTO users (email, password, role, is_active) VALUES (%s, %s, 'user', 1)",
        (req.email, hashed),
    )

    conn.commit()
    release_connection(conn)

    _auth_audit(
        action="auth_signup",
        status="success",
        details={"email": req.email},
        request=request,
    )

    return {"status": "user created"}


@router.post("/signup")
def signup(req: SignupRequest, request: Request):
    if not _is_signup_allowed():
        _auth_audit(
            action="auth_signup",
            status="denied",
            details={"email": req.email, "reason": "public_signup_disabled"},
            request=request,
        )
        raise HTTPException(
            status_code=403,
            detail="Public signup is disabled in this environment",
        )

    try:
        return _do_signup(req, request)
    except HTTPException as exc:
        _auth_audit(
            action="auth_signup",
            status="error",
            details={"email": req.email, "error": str(exc.detail)},
            request=request,
        )
        raise


@router.post("/register")
def register(req: SignupRequest, request: Request):
    return signup(req, request)


# --------------------------------------------------
# Login
# --------------------------------------------------


@router.post("/login")
def login(req: LoginRequest, request: Request):
    login_key = _login_key(req.email, request)
    retry_after = _check_login_lock(login_key)
    if retry_after > 0:
        _auth_audit(
            action="auth_login",
            status="locked",
            details={"email": req.email, "retry_after_seconds": retry_after},
            request=request,
        )
        raise HTTPException(
            status_code=429,
            detail="Too many failed login attempts. Try again later.",
            headers={"Retry-After": str(retry_after)},
        )

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT id, password, role, is_active FROM users WHERE email=%s",
        (req.email,),
    )
    user = cursor.fetchone()
    release_connection(conn)

    if not user:
        locked_now = _record_failed_login(login_key)
        _auth_audit(
            action="auth_login",
            status="locked" if locked_now else "denied",
            details={
                "email": req.email,
                "reason": "invalid_credentials",
                "locked": locked_now,
            },
            request=request,
        )
        if locked_now:
            raise HTTPException(
                status_code=429,
                detail="Too many failed login attempts. Try again later.",
                headers={"Retry-After": str(int(settings.auth_lockout_duration_seconds))},
            )
        raise HTTPException(status_code=401, detail="Invalid credentials")

    user_id, hashed = user[0], user[1]
    role = user[2] if len(user) > 2 else "user"
    is_active = user[3] if len(user) > 3 else 1

    if not is_active:
        _auth_audit(
            action="auth_login",
            status="denied",
            details={"email": req.email, "reason": "account_disabled"},
            request=request,
            user_id=user_id,
        )
        raise HTTPException(status_code=403, detail="Account disabled")

    if not verify_password(req.password, hashed):
        locked_now = _record_failed_login(login_key)
        _auth_audit(
            action="auth_login",
            status="locked" if locked_now else "denied",
            details={
                "email": req.email,
                "reason": "invalid_credentials",
                "locked": locked_now,
            },
            request=request,
            user_id=user_id,
        )
        if locked_now:
            raise HTTPException(
                status_code=429,
                detail="Too many failed login attempts. Try again later.",
                headers={"Retry-After": str(int(settings.auth_lockout_duration_seconds))},
            )
        raise HTTPException(status_code=401, detail="Invalid credentials")

    _clear_login_failures(login_key)

    token = create_access_token(
        {
            "user_id": user_id,
            "role": role,
        }
    )

    response = JSONResponse(
        {
        "access_token": token,
        "token": token,
        "token_type": "bearer",
        }
    )
    _set_session_cookie(response, token)
    _auth_audit(
        action="auth_login",
        status="success",
        details={"email": req.email, "role": role},
        request=request,
        user_id=user_id,
    )
    return response


# --------------------------------------------------
# Me (protected)
# --------------------------------------------------


@router.get("/me")
async def get_me(current_user: dict = Depends(get_current_user)):
    """Return current authenticated user info."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT id, email, role, is_active, created_at FROM users WHERE id=%s",
        (current_user.get("user_id"),),
    )
    user = cursor.fetchone()
    release_connection(conn)

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return {
        "user_id": user[0],
        "email": user[1],
        "role": user[2] if len(user) > 2 else "user",
        "is_active": bool(user[3]) if len(user) > 3 else True,
        "created_at": user[4] if len(user) > 4 else None,
    }


# --------------------------------------------------
# Logout (client-side token invalidation)
# --------------------------------------------------


@router.post("/logout")
async def logout(
    request: Request,
    current_user: dict = Depends(get_current_user),
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
):
    """
    Logout endpoint. Since we use stateless JWTs, the client
    should discard the token. This endpoint confirms the action.
    """
    token = None
    if credentials is not None:
        token = credentials.credentials
    if not token:
        token = (request.cookies.get(settings.session_cookie_name) or "").strip() or None
    if token:
        payload = decode_token(token)
        if payload is not None:
            revoke_token_jti(str(payload.get("jti") or ""), payload.get("exp"))

    response = JSONResponse(
        {
            "status": "logged out",
            "message": "Session cookie cleared",
        }
    )
    _clear_session_cookie(response)
    _auth_audit(
        action="auth_logout",
        status="success",
        details={"user_id": current_user.get("user_id")},
        request=request,
        user_id=current_user.get("user_id"),
    )
    return response
