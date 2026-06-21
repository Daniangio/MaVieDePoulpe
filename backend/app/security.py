from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session
import bcrypt

from .config import settings
from .firebase_auth import FirebaseAuthError, verify_firebase_token
from .server_models import User
from .database import SessionLocal

# OAuth2 Scheme
# This only parses Bearer headers; Firebase handles the actual auth flow.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/me")

SECRET_KEY = settings.SECRET_KEY
ALGORITHM = "HS256"
# Use the configured lifetime (default: see backend/app/config.py)
ACCESS_TOKEN_EXPIRE_MINUTES = settings.ACCESS_TOKEN_EXPIRE_MINUTES

def get_password_hash(password: str) -> str:
    """Hash a password using bcrypt"""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

def _load_guest_user_from_token_payload(payload: dict) -> User:
    user_id = payload.get("sub")
    username = payload.get("username")
    if user_id is None or payload.get("typ") != "guest":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    fallback_username = username or user_id
    return User(id=user_id, username=fallback_username)

def get_current_user(token: str = Depends(oauth2_scheme)):
    """Decodes a JWT token and returns the current user."""
    db = SessionLocal()
    try:
        return get_current_user_with_db(token, db)
    finally:
        db.close()


def get_current_user_with_db(token: str, db: Session) -> User:
    """Validates Firebase Bearer tokens and falls back only for server-issued guest tokens."""
    from .account_bootstrap import ensure_user_bootstrap
    from .user_repository import ensure_firebase_user

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        identity = verify_firebase_token(token)
        user = ensure_firebase_user(db, identity.uid, identity.email)
        user = ensure_user_bootstrap(db, user)
        user.email = identity.email or user.email
        user.username = user.email or user.username or user.id
        user.auth_provider = identity.auth_provider
        return user
    except (FirebaseAuthError, ValueError):
        try:
            header = jwt.get_unverified_header(token)
            if str(header.get("alg") or "").upper() != ALGORITHM:
                raise credentials_exception
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            return _load_guest_user_from_token_payload(payload)
        except JWTError as exc:
            raise credentials_exception from exc

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    """Creates a new JWT access token."""
    to_encode = data.copy()
    lifetime = expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    expire = datetime.now(timezone.utc) + lifetime
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt
