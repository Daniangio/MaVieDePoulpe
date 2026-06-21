from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from .db_models import UserProfileRecord
from .firebase_auth import is_admin_email
from .server_models import User
from .user_repository import list_registered_users


def _upsert_profile(db: Session, user: User, *, is_admin: bool) -> UserProfileRecord:
    profile = db.get(UserProfileRecord, user.id)
    if profile is None:
        profile = UserProfileRecord(
            user_id=user.id,
            is_admin=is_admin,
            display_name=user.username or user.email or user.id,
        )
        db.add(profile)
        db.commit()
        db.refresh(profile)
        return profile

    changed = False
    if is_admin and not profile.is_admin:
        profile.is_admin = True
        changed = True
    if not profile.display_name:
        profile.display_name = user.username or user.email or user.id
        changed = True
    if changed:
        db.add(profile)
        db.commit()
        db.refresh(profile)
    return profile


def ensure_user_bootstrap(db: Session, user: User, *, force_admin: Optional[bool] = None) -> User:
    is_admin = user.is_admin or bool(force_admin) or is_admin_email(user.email)
    profile = _upsert_profile(db, user, is_admin=is_admin)
    user.is_admin = bool(profile.is_admin)
    if profile.display_name:
        user.username = profile.display_name
    return user


def bootstrap_all_registered_users(db: Session) -> None:
    for user in list_registered_users(db):
        ensure_user_bootstrap(db, user)
