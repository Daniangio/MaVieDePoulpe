from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .database import get_db
from .friend_service import (
    create_friend_request,
    get_friend_status,
    list_friends_summary,
    remove_friendship,
    respond_to_friend_request,
)
from .runtime_state import get_presence_service
from .schemas import (
    FriendRequestCreate,
    FriendRequestRespond,
    FriendsSummaryResponse,
    LobbyStateResponse,
    PlayerProfile,
    SessionStateResponse,
    UserPublic,
)
from .security import get_current_user
from .server_models import User
from .user_repository import get_registered_user_by_id, list_registered_users


router = APIRouter()


async def _is_online(user_id: str) -> bool:
    presence_service = get_presence_service()
    if presence_service is None:
        return False
    presence = await presence_service.get_presence(user_id)
    return str((presence or {}).get("status") or "") == "online"


@router.get("/players/{user_id}", response_model=PlayerProfile)
async def get_player_profile(
    user_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user = get_registered_user_by_id(db, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Player not found")
    friends_summary = list_friends_summary(db, user_id)
    is_self = current_user.id == user.id
    can_see_email = is_self or bool(current_user.is_admin)
    return PlayerProfile(
        user=UserPublic(
            id=user.id,
            username=user.username,
            email=user.email if can_see_email else None,
            is_admin=bool(user.is_admin),
            online=await _is_online(user.id),
        ),
        is_self=is_self,
        friend_status=get_friend_status(db, current_user.id, user.id),
        friends_count=len(friends_summary["friends"]),
    )


@router.get("/friends", response_model=FriendsSummaryResponse)
async def get_friends_summary(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return FriendsSummaryResponse(**list_friends_summary(db, current_user.id))


@router.post("/friends/requests", response_model=FriendsSummaryResponse)
async def send_friend_request(
    payload: FriendRequestCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        create_friend_request(
            db,
            requester=current_user,
            target_user_id=payload.target_user_id,
            target_username=payload.username,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return FriendsSummaryResponse(**list_friends_summary(db, current_user.id))


@router.post("/friends/requests/{request_id}", response_model=FriendsSummaryResponse)
async def respond_friend_request(
    request_id: str,
    payload: FriendRequestRespond,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        respond_to_friend_request(
            db,
            request_id=request_id,
            responder=current_user,
            accept=bool(payload.accept),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return FriendsSummaryResponse(**list_friends_summary(db, current_user.id))


@router.delete("/friends/{friend_user_id}", response_model=FriendsSummaryResponse)
async def delete_friend(
    friend_user_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        remove_friendship(db, user_id=current_user.id, friend_user_id=friend_user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return FriendsSummaryResponse(**list_friends_summary(db, current_user.id))


@router.get("/session/state", response_model=SessionStateResponse)
async def get_session_state(current_user: User = Depends(get_current_user)):
    return SessionStateResponse(user_id=current_user.id)


@router.get("/lobby/state", response_model=LobbyStateResponse)
async def get_lobby_state(
    _current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    users = list_registered_users(db)
    users.sort(key=lambda user: (str(user.username or "").casefold(), str(user.id)))
    return LobbyStateResponse(
        users=[
            UserPublic(
                id=user.id,
                username=user.username,
                is_admin=bool(user.is_admin),
                online=await _is_online(user.id),
            )
            for user in users
        ]
    )
