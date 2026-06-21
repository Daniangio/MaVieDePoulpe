from __future__ import annotations

from typing import Optional

from .server_models import User
from .user_repository import get_registered_user_by_id


compat_runtime_users: dict[str, User] = {}


def _normalize(value: str | None) -> str:
    return str(value or "").strip()


def remember_user(user: Optional[User]) -> None:
    if user is None:
        return
    user_id = _normalize(getattr(user, "id", ""))
    if user_id:
        compat_runtime_users[user_id] = user


def forget_user(user_id: str) -> None:
    normalized_user_id = _normalize(user_id)
    if normalized_user_id:
        compat_runtime_users.pop(normalized_user_id, None)


def get_runtime_user(user_id: str, *, include_persisted: bool = True) -> Optional[User]:
    normalized_user_id = _normalize(user_id)
    if not normalized_user_id:
        return None
    cached_user = compat_runtime_users.get(normalized_user_id)
    if cached_user is not None:
        return cached_user
    if not include_persisted:
        return None
    try:
        from .database import SessionLocal

        with SessionLocal() as db:
            persisted = get_registered_user_by_id(db, normalized_user_id)
            if persisted is not None:
                remember_user(persisted)
                return persisted
    except Exception:
        return None
    return None
