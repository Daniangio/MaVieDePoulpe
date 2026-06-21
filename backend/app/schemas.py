from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class UserPublic(BaseModel):
    id: str
    username: str
    email: Optional[str] = None
    is_admin: bool = False
    online: bool = False


class PlayerProfile(BaseModel):
    user: UserPublic
    is_self: bool = False
    friend_status: str = "none"
    friends_count: int = 0


class FriendUserSummary(BaseModel):
    id: str
    username: str


class FriendRequestCreate(BaseModel):
    username: Optional[str] = None
    target_user_id: Optional[str] = None


class FriendRequestRespond(BaseModel):
    accept: bool


class FriendListEntry(BaseModel):
    user: FriendUserSummary
    since: Optional[datetime] = None


class PendingFriendRequestEntry(BaseModel):
    request_id: str
    user: FriendUserSummary
    created_at: datetime


class FriendsSummaryResponse(BaseModel):
    friends: List[FriendListEntry]
    incoming_requests: List[PendingFriendRequestEntry]
    outgoing_requests: List[PendingFriendRequestEntry]


class SessionStateResponse(BaseModel):
    user_id: str


class LobbyStateResponse(BaseModel):
    users: List[UserPublic]


class GameRoomCreateRequest(BaseModel):
    mode: str = "solo"
    game_type: str = "proxy_room"


class GameRoomResponse(BaseModel):
    id: str
    owner_user_id: str
    mode: str
    game_type: str
    state: str
    created_at: str
    started_at: str
    ended_at: Optional[str] = None
    result_id: Optional[str] = None


class GameCommandRequest(BaseModel):
    command_id: str
    type: str
    expected_revision: Optional[int] = None
    client_timestamp_ms: Optional[int] = None


class GameCommandQueuedResponse(BaseModel):
    status: str
    command_id: str
    revision: int


class GameStateResponse(BaseModel):
    revision: int
    phase: str
    room_id: str
    game_type: str = "proxy_room"
    status: str = "waiting_for_game_logic"
    message: str = ""
    available_actions: List[Dict[str, Any]]


class GameResultResponse(BaseModel):
    id: str
    room_id: str
    mode: str
    game_type: str
    outcome: str
    score: int
    turns: int
    duration_seconds: int
    summary: str
    created_at: str


class GameHistoryResponse(BaseModel):
    results: List[GameResultResponse]


class AuthMeResponse(BaseModel):
    uid: str
    email: Optional[str] = None
    username: str
    auth_provider: Optional[str] = None
    player_exists: bool
    is_admin: bool = False


class AdminUserSummary(BaseModel):
    id: str
    username: str
    email: Optional[str] = None
    is_admin: bool
    online: bool = False


class AdminUserAdminUpdate(BaseModel):
    is_admin: bool


class AdminUserDetail(BaseModel):
    user: UserPublic
    friends_count: int = 0
    incoming_requests_count: int = 0
    outgoing_requests_count: int = 0


class AdminMutationStatus(BaseModel):
    status: str
    message: Optional[str] = None


class AdminAuditLogEntry(BaseModel):
    id: str
    admin_user_id: str
    admin_username: str
    action: str
    target_type: str
    target_id: str
    payload: Dict[str, Any]
    created_at: datetime
