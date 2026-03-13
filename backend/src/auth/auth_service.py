from datetime import datetime, timedelta
from passlib.context import CryptContext
from jose import jwt, JWTError
import os

# --------------------------------------------------
# Security Settings
# --------------------------------------------------

SECRET_KEY = os.getenv("VISION_AI_SECRET", "vision_ai_secret_key")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

# password hashing
pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto"
)

# --------------------------------------------------
# Password Utilities
# --------------------------------------------------

def hash_password(password: str) -> str:

    return pwd_context.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:

    return pwd_context.verify(password, hashed_password)


# --------------------------------------------------
# Token Creation
# --------------------------------------------------

def create_access_token(data: dict, expires_minutes: int = ACCESS_TOKEN_EXPIRE_MINUTES):

    payload = data.copy()

    expire = datetime.utcnow() + timedelta(minutes=expires_minutes)

    payload.update({"exp": expire})

    token = jwt.encode(
        payload,
        SECRET_KEY,
        algorithm=ALGORITHM
    )

    return token


# --------------------------------------------------
# Token Verification
# --------------------------------------------------

def decode_token(token: str):

    try:

        payload = jwt.decode(
            token,
            SECRET_KEY,
            algorithms=[ALGORITHM]
        )

        return payload

    except JWTError:

        return None