from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import firebase_admin
from firebase_admin import auth as firebase_admin_auth
from firebase_admin import credentials

from .config import settings


class FirebaseAuthError(Exception):
    pass


@dataclass
class VerifiedFirebaseIdentity:
    uid: str
    email: str | None
    auth_provider: str | None
    claims: dict[str, Any]


_firebase_app = None
_admin_email_cache: set[str] | None = None


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def resolve_repo_path(raw_path: str) -> Path:
    path = Path(str(raw_path or "").strip())
    if path.is_absolute():
        return path
    return _project_root() / path


def initialize_firebase_admin() -> None:
    global _firebase_app
    if _firebase_app is not None:
        return
    try:
        _firebase_app = firebase_admin.get_app()
        return
    except ValueError:
        pass
    credentials_path = resolve_repo_path(settings.FIREBASE_ADMIN_CREDENTIALS)
    if not credentials_path.exists():
        raise FileNotFoundError(f"Firebase admin credentials not found: {credentials_path}")
    firebase_credentials = credentials.Certificate(str(credentials_path))
    options: dict[str, Any] = {}
    if settings.FIREBASE_PROJECT_ID:
        options["projectId"] = settings.FIREBASE_PROJECT_ID
    _firebase_app = firebase_admin.initialize_app(firebase_credentials, options or None)


def verify_firebase_token(id_token: str) -> VerifiedFirebaseIdentity:
    try:
        initialize_firebase_admin()
        claims = firebase_admin_auth.verify_id_token(id_token, app=_firebase_app)
    except Exception as exc:  # noqa: BLE001
        raise FirebaseAuthError("Could not validate Firebase credentials") from exc
    uid = str(claims.get("uid") or "").strip()
    if not uid:
        raise FirebaseAuthError("Firebase token does not include uid")
    email = str(claims.get("email") or "").strip() or None
    provider = (
        str(((claims.get("firebase") or {}).get("sign_in_provider") or claims.get("sign_in_provider") or "")).strip()
        or None
    )
    return VerifiedFirebaseIdentity(
        uid=uid,
        email=email,
        auth_provider=provider,
        claims=claims,
    )


def load_admin_email_config() -> set[str]:
    global _admin_email_cache
    if _admin_email_cache is not None:
        return _admin_email_cache
    raw_email = str(settings.FIREBASE_PRIMARY_ADMIN_EMAIL or "").strip().lower()
    _admin_email_cache = {raw_email} if raw_email else set()
    return _admin_email_cache


def is_admin_email(email: str | None) -> bool:
    normalized = str(email or "").strip().lower()
    if not normalized:
        return False
    return normalized in load_admin_email_config()
