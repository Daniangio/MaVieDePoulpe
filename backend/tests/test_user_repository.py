from sqlalchemy.orm import sessionmaker

from backend.app.database import Base, _build_engine
from backend.app.user_repository import (
    create_registered_user,
    ensure_firebase_user,
    get_registered_user_by_email,
    get_registered_user_by_id,
    get_registered_user_by_username,
)


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


def test_registered_user_round_trip(tmp_path):
    session_factory = build_test_session(f"sqlite:///{tmp_path / 'users.db'}")
    with session_factory() as db:
        created_user = create_registered_user(db, "alice", "verysecurepassword")

    with session_factory() as db:
        by_id = get_registered_user_by_id(db, created_user.id)
        by_username = get_registered_user_by_username(db, "alice")

    assert by_id is not None
    assert by_username is not None
    assert by_id.id == created_user.id
    assert by_username.username == "alice"


def test_registered_user_rejects_duplicate_username(tmp_path):
    session_factory = build_test_session(f"sqlite:///{tmp_path / 'duplicate.db'}")
    with session_factory() as db:
        create_registered_user(db, "admin", "adminadmin")
        try:
            create_registered_user(db, "admin", "differentpassword")
        except ValueError as exc:
            assert str(exc) == "Username already registered"
        else:
            raise AssertionError("Expected duplicate username to fail")


def test_ensure_firebase_user_round_trip(tmp_path):
    session_factory = build_test_session(f"sqlite:///{tmp_path / 'firebase_users.db'}")
    with session_factory() as db:
        created_user = ensure_firebase_user(
            db,
            "firebase_uid_123",
            "firebase.user@example.com",
        )

    with session_factory() as db:
        by_id = get_registered_user_by_id(db, "firebase_uid_123")
        by_email = get_registered_user_by_email(db, "firebase.user@example.com")

    assert created_user.id == "firebase_uid_123"
    assert created_user.email == "firebase.user@example.com"
    assert created_user.username == "firebase.user@example.com"
    assert by_id is not None
    assert by_email is not None
    assert by_id.id == "firebase_uid_123"
    assert by_email.id == "firebase_uid_123"
