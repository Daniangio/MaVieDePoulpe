import pytest
from sqlalchemy.orm import sessionmaker

from backend.app import firebase_auth
from backend.app.account_bootstrap import ensure_user_bootstrap
from backend.app.database import Base, _build_engine
from backend.app.firebase_auth import VerifiedFirebaseIdentity
from backend.app.security import get_current_user_with_db
from fastapi import HTTPException


def build_test_session(database_url: str):
    engine = _build_engine(database_url)
    Base.metadata.create_all(bind=engine)
    return sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine,
        future=True,
        expire_on_commit=False,
    )


def test_get_current_user_with_db_bootstraps_firebase_identity(tmp_path, monkeypatch):
    monkeypatch.setattr(
        firebase_auth.settings,
        "FIREBASE_PRIMARY_ADMIN_EMAIL",
        "admin@example.local",
    )
    firebase_auth._admin_email_cache = None
    monkeypatch.setattr(
        "backend.app.security.verify_firebase_token",
        lambda token: VerifiedFirebaseIdentity(
            uid="firebase_uid_auth",
            email="admin@example.local",
            auth_provider="password",
            claims={"uid": "firebase_uid_auth", "email": "admin@example.local"},
        ),
    )

    session_factory = build_test_session(f"sqlite:///{tmp_path / 'firebase_security.db'}")
    with session_factory() as db:
        user = get_current_user_with_db("firebase-token", db)
        ensure_user_bootstrap(db, user)

    assert user.id == "firebase_uid_auth"
    assert user.email == "admin@example.local"
    assert user.username == "admin@example.local"
    assert user.auth_provider == "password"
    assert user.is_admin is True
    firebase_auth._admin_email_cache = None


def test_get_current_user_with_db_does_not_treat_expired_firebase_token_as_guest(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        "backend.app.security.verify_firebase_token",
        lambda token: (_ for _ in ()).throw(firebase_auth.FirebaseAuthError("expired")),
    )

    session_factory = build_test_session(f"sqlite:///{tmp_path / 'firebase_expired.db'}")
    with session_factory() as db:
        with pytest.raises(HTTPException) as exc_info:
            get_current_user_with_db("not-a-guest-firebase-token", db)

    assert exc_info.value.status_code == 401
