import asyncio

from sqlalchemy.orm import sessionmaker

from backend.app.database import Base, _build_engine
from backend.app.player_router import (
    delete_friend,
    get_friends_summary,
    get_player_profile,
    respond_friend_request,
    send_friend_request,
)
from backend.app.schemas import FriendRequestCreate, FriendRequestRespond
from backend.app.user_repository import create_registered_user


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


def test_friend_request_flow_and_profile_status(tmp_path):
    session_factory = build_test_session(f"sqlite:///{tmp_path / 'friends.db'}")
    with session_factory() as db:
        alice = create_registered_user(db, "alice@test.local", "securepassword")
        bob = create_registered_user(db, "bob@test.local", "securepassword")

        summary = asyncio.run(
            send_friend_request(
                FriendRequestCreate(username="bob@test.local"),
                alice,
                db,
            )
        )
        assert len(summary.outgoing_requests) == 1

        bob_summary = asyncio.run(get_friends_summary(bob, db))
        assert len(bob_summary.incoming_requests) == 1
        request_id = bob_summary.incoming_requests[0].request_id

        accepted = asyncio.run(
            respond_friend_request(
                request_id,
                FriendRequestRespond(accept=True),
                bob,
                db,
            )
        )
        assert len(accepted.friends) == 1

        alice_profile = asyncio.run(get_player_profile(bob.id, alice, db))
        bob_profile = asyncio.run(get_player_profile(alice.id, bob, db))
        assert alice_profile.friend_status == "friends"
        assert bob_profile.friend_status == "friends"
        assert alice_profile.friends_count == 1

        after_delete = asyncio.run(delete_friend(bob.id, alice, db))
        assert len(after_delete.friends) == 0
