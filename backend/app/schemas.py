from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


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
    game_type: str = "goldfish"
    map_id: Optional[str] = None
    level_id: Optional[str] = None


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
    map_id: Optional[str] = None
    level_id: Optional[str] = None


class GameRoomJoinResponse(BaseModel):
    room_id: str
    seat_id: str


class GameCommandRequest(BaseModel):
    command_id: str
    type: str
    room_id: Optional[str] = None
    actor_user_id: Optional[str] = None
    actor_seat_id: Optional[str] = None
    expected_version: Optional[int] = None
    expected_revision: Optional[int] = None
    client_timestamp_ms: Optional[int] = None
    payload: Dict[str, Any] = Field(default_factory=dict)


class GameCommandQueuedResponse(BaseModel):
    ok: bool = True
    status: str = "accepted"
    command_id: str
    revision: int = 0
    version: Optional[int] = None
    reason: Optional[str] = None
    message: Optional[str] = None
    current_version: Optional[int] = None
    projection: Optional[Dict[str, Any]] = None
    events: List[Dict[str, Any]] = Field(default_factory=list)


class GameStateResponse(BaseModel):
    version: int
    phase: str
    room_id: str
    projection_mode: str = "goldfish"
    privacy_enforced: bool = False
    mode: str = "goldfish"
    level_id: str
    selected_level_id: Optional[str] = None
    day_index: int = 1
    night_time_spent: int = 0
    selected_map_id: Optional[str] = None
    active_capability_id: Optional[str] = None
    last_active_capability_id: Optional[str] = None
    focused_capability_id: Optional[str] = None
    capability_order: List[str] = Field(default_factory=list)
    capabilities: Dict[str, Any] = Field(default_factory=dict)
    players: List[Dict[str, Any]] = Field(default_factory=list)
    player_boards: List[Dict[str, Any]] = Field(default_factory=list)
    map: Dict[str, Any]
    poulpita: Dict[str, Any]
    events: List[Dict[str, Any]] = Field(default_factory=list)


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
