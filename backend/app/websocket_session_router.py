from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Optional

from fastapi import HTTPException
from fastapi import WebSocket

from backend.app import security

from .connection_manager import ConnectionManager
from .presence_service import PresenceService
from .runtime_registry import remember_user
from .security import get_current_user
from .server_models import User


@dataclass
class WebSocketSessionContext:
    user: User
    token: str
    session_id: str = ""


class WebSocketSessionRouter:
    def __init__(
        self,
        *,
        connection_manager: ConnectionManager,
        presence_service: PresenceService,
    ) -> None:
        self.connection_manager = connection_manager
        self.presence_service = presence_service

    async def authenticate(self, websocket: WebSocket) -> WebSocketSessionContext:
        token = websocket.query_params.get("token")
        guest_mode = str(websocket.query_params.get("guest") or "").lower() in {
            "1",
            "true",
            "yes",
        }
        await websocket.accept()
        if token:
            try:
                auth_user = get_current_user(token=token)
            except HTTPException:
                await websocket.send_json(
                    {
                        "type": "auth_error",
                        "payload": {"message": "Could not validate credentials"},
                    }
                )
                await websocket.close(code=4401)
                raise
            remember_user(auth_user)
            user = auth_user
            session_id = getattr(auth_user, "session_id", "") or ""
            await websocket.send_json(
                {
                    "type": "auth_success",
                    "payload": user.model_dump(),
                    "token": token,
                }
            )
            return WebSocketSessionContext(
                user=user,
                token=token,
                session_id=session_id,
            )
        guest_id = f"guest_{str(uuid.uuid4())[:8]}"
        user = User(id=guest_id, username=guest_id)
        guest_token = security.create_access_token(
            data={
                "sub": user.id,
                "username": user.username,
                "is_admin": False,
                "typ": "guest",
            }
        )
        remember_user(user)
        await websocket.send_json(
            {
                "type": "guest_auth_success",
                "payload": user.model_dump(),
                "token": guest_token,
            }
        )
        return WebSocketSessionContext(user=user, token=guest_token, session_id="")

    async def establish(
        self,
        context: WebSocketSessionContext,
        websocket: WebSocket,
    ) -> bool:
        await self.connection_manager.add_connection(
            context.user.id,
            websocket,
            session_id=context.session_id,
        )
        await self.presence_service.mark_connected(
            context.user.id,
            username=context.user.username,
            session_id=context.session_id,
        )
        return False

    async def cleanup(self, user_id: Optional[str], websocket: Optional[WebSocket]) -> None:
        if not user_id or not self.connection_manager.is_current_connection(user_id, websocket):
            return
        self.connection_manager.disconnect(user_id, websocket)
        await self.presence_service.mark_disconnected(user_id)
