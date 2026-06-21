from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import and_, or_, select, delete
from sqlalchemy.orm import Session

from .db_models import FriendRequestRecord
from .server_models import User
from .user_repository import get_registered_user_by_id, get_registered_user_by_username


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _pair_condition(user_a: str, user_b: str):
    return or_(
        and_(
            FriendRequestRecord.requester_id == user_a,
            FriendRequestRecord.addressee_id == user_b,
        ),
        and_(
            FriendRequestRecord.requester_id == user_b,
            FriendRequestRecord.addressee_id == user_a,
        ),
    )


def _to_public_user(user_id: str, username: str) -> dict:
    return {"id": user_id, "username": username or user_id}


def _find_latest_relationship(db: Session, user_a: str, user_b: str) -> Optional[FriendRequestRecord]:
    return (
        db.execute(
            select(FriendRequestRecord)
            .where(_pair_condition(user_a, user_b))
            .order_by(FriendRequestRecord.created_at.desc())
        )
        .scalars()
        .first()
    )


def get_friend_status(db: Session, viewer_id: str, target_id: str) -> str:
    if not viewer_id or not target_id:
        return "none"
    if viewer_id == target_id:
        return "self"
    relationship = _find_latest_relationship(db, viewer_id, target_id)
    if relationship is None:
        return "none"
    status = str(relationship.status or "").lower()
    if status == "accepted":
        return "friends"
    if status == "pending":
        return "incoming_request" if relationship.addressee_id == viewer_id else "outgoing_request"
    return "none"


def create_friend_request(
    db: Session,
    *,
    requester: User,
    target_user_id: Optional[str] = None,
    target_username: Optional[str] = None,
) -> FriendRequestRecord:
    target: Optional[User] = None
    if target_user_id:
        target = get_registered_user_by_id(db, target_user_id)
    elif target_username:
        target = get_registered_user_by_username(db, target_username)
    if target is None:
        raise ValueError("Player not found")
    if target.id == requester.id:
        raise ValueError("Cannot add yourself as a friend")
    relationship = _find_latest_relationship(db, requester.id, target.id)
    if relationship is not None:
        status = str(relationship.status or "").lower()
        if status == "accepted":
            raise ValueError("You are already friends")
        if status == "pending":
            raise ValueError("A friend request is already pending between these players")
    row = FriendRequestRecord(
        id=uuid.uuid4().hex,
        requester_id=requester.id,
        requester_username=requester.username or requester.id,
        addressee_id=target.id,
        addressee_username=target.username or target.id,
        status="pending",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def respond_to_friend_request(
    db: Session,
    *,
    request_id: str,
    responder: User,
    accept: bool,
) -> FriendRequestRecord:
    row = db.get(FriendRequestRecord, request_id)
    if row is None:
        raise ValueError("Friend request not found")
    if row.addressee_id != responder.id:
        raise ValueError("You cannot respond to this friend request")
    if str(row.status or "").lower() != "pending":
        raise ValueError("Friend request is no longer pending")
    row.status = "accepted" if accept else "declined"
    row.responded_at = _utc_now()
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def remove_friendship(db: Session, *, user_id: str, friend_user_id: str) -> None:
    relationship = _find_latest_relationship(db, user_id, friend_user_id)
    if relationship is None or str(relationship.status or "").lower() != "accepted":
        raise ValueError("Friendship not found")
    db.execute(
        delete(FriendRequestRecord).where(
            FriendRequestRecord.id == relationship.id,
        )
    )
    db.commit()


def list_friends_summary(db: Session, user_id: str) -> dict:
    rows = (
        db.execute(
            select(FriendRequestRecord).where(
                or_(
                    FriendRequestRecord.requester_id == user_id,
                    FriendRequestRecord.addressee_id == user_id,
                )
            )
        )
        .scalars()
        .all()
    )
    accepted = []
    incoming = []
    outgoing = []
    for row in rows:
        status = str(row.status or "").lower()
        if status == "accepted":
            friend_id = row.addressee_id if row.requester_id == user_id else row.requester_id
            friend_username = (
                row.addressee_username if row.requester_id == user_id else row.requester_username
            )
            accepted.append(
                {
                    "user": _to_public_user(friend_id, friend_username),
                    "since": row.responded_at or row.created_at,
                }
            )
        elif status == "pending" and row.addressee_id == user_id:
            incoming.append(
                {
                    "request_id": row.id,
                    "user": _to_public_user(row.requester_id, row.requester_username),
                    "created_at": row.created_at,
                }
            )
        elif status == "pending" and row.requester_id == user_id:
            outgoing.append(
                {
                    "request_id": row.id,
                    "user": _to_public_user(row.addressee_id, row.addressee_username),
                    "created_at": row.created_at,
                }
            )
    accepted.sort(key=lambda item: item["since"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    incoming.sort(key=lambda item: item["created_at"], reverse=True)
    outgoing.sort(key=lambda item: item["created_at"], reverse=True)
    return {
        "friends": accepted,
        "incoming_requests": incoming,
        "outgoing_requests": outgoing,
    }
