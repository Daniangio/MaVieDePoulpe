from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError, ProgrammingError

from . import security
from .db_models import RegisteredUserRecord, UserProfileRecord
from .firebase_auth import is_admin_email
from .server_models import User


def _to_user(record: RegisteredUserRecord, profile: Optional[UserProfileRecord] = None) -> User:
    email = str(record.email or "").strip() or None
    profile_name = str(getattr(profile, "display_name", "") or "").strip() if profile else ""
    username = profile_name or str(record.username or "").strip() or email or record.id
    return User(
        id=record.id,
        username=username,
        email=email,
        is_admin=(bool(profile.is_admin) if profile else False) or is_admin_email(email),
    )


def _get_profile(db: Session, user_id: str) -> Optional[UserProfileRecord]:
    try:
        return db.get(UserProfileRecord, user_id)
    except (OperationalError, ProgrammingError):
        return None


def get_registered_user_by_id(db: Session, user_id: str) -> Optional[User]:
    try:
        record = db.get(RegisteredUserRecord, user_id)
    except (OperationalError, ProgrammingError):
        return None
    if record is None:
        return None
    return _to_user(record, _get_profile(db, record.id))


def get_registered_user_by_username(db: Session, username: str) -> Optional[User]:
    try:
        record = db.execute(
            select(RegisteredUserRecord).where(RegisteredUserRecord.username == username)
        ).scalar_one_or_none()
    except (OperationalError, ProgrammingError):
        return None
    if record is None:
        return None
    return _to_user(record, _get_profile(db, record.id))


def get_registered_user_by_email(db: Session, email: str) -> Optional[User]:
    normalized_email = str(email or "").strip().lower()
    if not normalized_email:
        return None
    try:
        record = db.execute(
            select(RegisteredUserRecord).where(RegisteredUserRecord.email == normalized_email)
        ).scalar_one_or_none()
    except (OperationalError, ProgrammingError):
        return None
    if record is None:
        return None
    return _to_user(record, _get_profile(db, record.id))


def create_registered_user(
    db: Session,
    username: str,
    password: str,
    *,
    user_id: str | None = None,
    email: str | None = None,
) -> User:
    existing = get_registered_user_by_username(db, username)
    if existing is not None:
        raise ValueError("Username already registered")
    normalized_email = str(email or "").strip().lower() or (
        str(username).strip().lower() if "@" in str(username or "") else None
    )
    if normalized_email and get_registered_user_by_email(db, normalized_email) is not None:
        raise ValueError("Email already registered")
    record = RegisteredUserRecord(
        id=str(user_id or uuid.uuid4().hex),
        username=username,
        email=normalized_email,
        hashed_password=security.get_password_hash(password),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return _to_user(record)


def list_registered_users(db: Session) -> list[User]:
    try:
        records = db.execute(select(RegisteredUserRecord)).scalars().all()
        profiles = {
            profile.user_id: profile
            for profile in db.execute(select(UserProfileRecord)).scalars().all()
        }
    except (OperationalError, ProgrammingError):
        return []
    return [_to_user(record, profiles.get(record.id)) for record in records]


def ensure_firebase_user(db: Session, uid: str, email: str | None = None) -> User:
    normalized_uid = str(uid or "").strip()
    if not normalized_uid:
        raise ValueError("Firebase uid is required")
    normalized_email = str(email or "").strip().lower() or None
    record = db.get(RegisteredUserRecord, normalized_uid)
    if record is None:
        if normalized_email:
            existing_by_email = get_registered_user_by_email(db, normalized_email)
            if existing_by_email is not None and existing_by_email.id != normalized_uid:
                raise ValueError("A different player record already uses this email")
        display_name = normalized_email or normalized_uid
        record = RegisteredUserRecord(
            id=normalized_uid,
            username=display_name,
            email=normalized_email,
            hashed_password=security.get_password_hash(uuid.uuid4().hex),
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        return _to_user(record, _get_profile(db, record.id))
    mutated = False
    if normalized_email and record.email != normalized_email:
        record.email = normalized_email
        record.username = normalized_email
        mutated = True
    if mutated:
        db.add(record)
        db.commit()
        db.refresh(record)
    return _to_user(record, _get_profile(db, record.id))
