"""
Authentication API routes.

Endpoints:
  POST /auth/signup    — create new account
  POST /auth/register  — alias for signup
  POST /auth/login     — authenticate and get JWT
  GET  /auth/me        — get current user info (requires JWT)
  POST /auth/logout    — invalidate token (client-side)
"""

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, EmailStr

from backend.src.database.db import get_connection
from backend.src.auth.auth_service import (
    hash_password,
    verify_password,
    create_access_token,
    get_current_user,
)

router = APIRouter()


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
    if len(req.password) < 6:
        raise HTTPException(
            status_code=400,
            detail="Password must be at least 6 characters",
        )

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM users WHERE email=?", (req.email,))
    existing = cursor.fetchone()

    if existing:
        conn.close()
        raise HTTPException(status_code=400, detail="User already exists")

    hashed = hash_password(req.password)

    cursor.execute(
        "INSERT INTO users (email, password, role, is_active) VALUES (?, ?, 'user', 1)",
        (req.email, hashed),
    )

    conn.commit()
    conn.close()

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
        "SELECT id, password, role, is_active FROM users WHERE email=?",
        (req.email,),
    )
    user = cursor.fetchone()
    conn.close()

    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    user_id, hashed = user[0], user[1]
    role = user[2] if len(user) > 2 else "user"
    is_active = user[3] if len(user) > 3 else 1

    if not is_active:
        raise HTTPException(status_code=403, detail="Account disabled")

    if not verify_password(req.password, hashed):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_access_token({
        "user_id": user_id,
        "role": role,
    })

    return {
        "access_token": token,
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
        "SELECT id, email, role, is_active, created_at FROM users WHERE id=?",
        (current_user.get("user_id"),),
    )
    user = cursor.fetchone()
    conn.close()

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