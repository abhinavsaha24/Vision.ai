"""
Authentication API routes.

Endpoints:
  POST /auth/signup    - create new account
  POST /auth/register  - alias for signup
  POST /auth/login     - authenticate and get JWT
  GET  /auth/me        - get current user info (requires JWT)
  POST /auth/logout    - invalidate token (client-side)
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr

from backend.src.auth.auth_service import (create_access_token,
                                           get_current_user, hash_password,
                                           verify_password)
from backend.src.database.db import get_connection, release_connection

router = APIRouter()

MIN_PASSWORD_LENGTH = 10


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


def _do_signup(req: SignupRequest):
    """Shared signup logic for both /signup and /register."""
    _validate_password_strength(req.password)

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM users WHERE email=%s", (req.email,))
    existing = cursor.fetchone()

    if existing:
        release_connection(conn)
        # Return generic success response to reduce account enumeration signal.
        return {"status": "user created"}

    hashed = hash_password(req.password)

    cursor.execute(
        "INSERT INTO users (email, password, role, is_active) VALUES (%s, %s, 'user', 1)",
        (req.email, hashed),
    )

    conn.commit()
    release_connection(conn)

    return {"status": "user created"}


@router.post("/signup")
def signup(req: SignupRequest):
    return _do_signup(req)


@router.post("/register")
def register(req: SignupRequest):
    return _do_signup(req)


# --------------------------------------------------
# Login
# --------------------------------------------------


@router.post("/login")
def login(req: LoginRequest):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT id, password, role, is_active FROM users WHERE email=%s",
        (req.email,),
    )
    user = cursor.fetchone()
    release_connection(conn)

    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    user_id, hashed = user[0], user[1]
    role = user[2] if len(user) > 2 else "user"
    is_active = user[3] if len(user) > 3 else 1

    if not is_active:
        raise HTTPException(status_code=403, detail="Account disabled")

    if not verify_password(req.password, hashed):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_access_token(
        {
            "user_id": user_id,
            "role": role,
        }
    )

    return {
        "access_token": token,
        "token": token,
        "token_type": "bearer",
    }


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
async def logout(current_user: dict = Depends(get_current_user)):
    """
    Logout endpoint. Since we use stateless JWTs, the client
    should discard the token. This endpoint confirms the action.
    """
    return {
        "status": "logged out",
        "message": "Token should be discarded by client",
    }
