from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr
from backend.src.database.db import get_connection
from backend.src.auth.auth_service import (
    hash_password,
    verify_password,
    create_access_token
)

router = APIRouter()


# -----------------------------
# Request Models
# -----------------------------

class SignupRequest(BaseModel):

    email: EmailStr
    password: str


class LoginRequest(BaseModel):

    email: EmailStr
    password: str


# -----------------------------
# Signup
# -----------------------------

@router.post("/signup")
def signup(req: SignupRequest):

    if len(req.password) < 6:
        raise HTTPException(
            status_code=400,
            detail="Password must be at least 6 characters"
        )

    conn = get_connection()
    cursor = conn.cursor()

    # check if user exists
    cursor.execute(
        "SELECT id FROM users WHERE email=?",
        (req.email,)
    )

    existing = cursor.fetchone()

    if existing:
        conn.close()
        raise HTTPException(
            status_code=400,
            detail="User already exists"
        )

    hashed = hash_password(req.password)

    cursor.execute(
        "INSERT INTO users (email,password) VALUES (?,?)",
        (req.email, hashed)
    )

    conn.commit()
    conn.close()

    return {
        "status": "user created"
    }


# -----------------------------
# Login
# -----------------------------

@router.post("/login")
def login(req: LoginRequest):

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT id,password FROM users WHERE email=?",
        (req.email,)
    )

    user = cursor.fetchone()

    conn.close()

    if not user:
        raise HTTPException(
            status_code=401,
            detail="Invalid credentials"
        )

    user_id, hashed = user

    if not verify_password(req.password, hashed):

        raise HTTPException(
            status_code=401,
            detail="Invalid credentials"
        )

    token = create_access_token(
        {"user_id": user_id}
    )

    return {
        "access_token": token,
        "token_type": "bearer"
    }