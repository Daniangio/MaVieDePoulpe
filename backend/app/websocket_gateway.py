from __future__ import annotations

import json
import traceback
from typing import Awaitable, Callable, Dict

from fastapi import HTTPException
from fastapi import WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from .chat_service import ChatService
from .connection_manager import ConnectionManager
from .config import settings
from .presence_service import PresenceService
from .redis_client import get_redis
from .server_models import User
from .websocket_session_router import WebSocketSessionContext, WebSocketSessionRouter


ActionHandler = Callable[[User, dict], Awaitable[None]]


class WebSocketGateway:
    def __init__(
        self,
        *,
        connection_manager: ConnectionManager,
        presence_service: PresenceService,
        session_router: WebSocketSessionRouter,
        chat_service: ChatService | None = None,
    ) -> None:
        self.connection_manager = connection_manager
        self.presence_service = presence_service
        self.chat_service = chat_service or ChatService()
        self.session_router = session_router
        self.action_handlers: Dict[str, ActionHandler] = {
            "send_chat_message": self._handle_send_chat_message,
            "request_chat_history": self._handle_request_chat_history,
            "request_chat_channels": self._handle_request_chat_channels,
            "create_chat_channel": self._handle_create_chat_channel,
            "remove_chat_channel": self._handle_remove_chat_channel,
            "leave_chat_channel": self._handle_leave_chat_channel,
            "set_chat_muted": self._handle_set_chat_muted,
            "add_chat_members": self._handle_add_chat_members,
            "kick_chat_member": self._handle_kick_chat_member,
            "start_direct_chat": self._handle_start_direct_chat,
        }

    async def handle_connection(self, websocket: WebSocket) -> None:
        try:
            context: WebSocketSessionContext = await self.session_router.authenticate(websocket)
        except HTTPException:
            return
        user_id_for_cleanup = context.user.id
        try:
            await self.session_router.establish(context, websocket)
            while True:
                data = await websocket.receive_json()
                action = data.get("action")
                payload = data.get("payload", {})
                await self.presence_service.touch(context.user.id)
                if action == "heartbeat":
                    continue
                await self.dispatch_action(context.user, action, payload)
        except WebSocketDisconnect:
            await self.session_router.cleanup(user_id_for_cleanup, websocket)
        except Exception as exc:
            print(f"An error occurred with user {user_id_for_cleanup or 'unknown'}: {exc}")
            traceback.print_exc()
            await self.session_router.cleanup(user_id_for_cleanup, websocket)

    async def dispatch_action(self, user: User, action: str, payload: dict) -> None:
        handler = self.action_handlers.get(action)
        if handler is None:
            return
        await handler(user, payload)

    async def _handle_send_chat_message(self, user: User, payload: dict) -> None:
        try:
            message = await self.chat_service.add_message(
                chat_id=str((payload or {}).get("chat_id") or "global"),
                sender_id=user.id,
                sender_name=user.username or user.email or user.id,
                text=str((payload or {}).get("text") or ""),
                share=(payload or {}).get("share") if isinstance((payload or {}).get("share"), dict) else None,
            )
        except (ValueError, PermissionError) as exc:
            await self.connection_manager.send_to_user(
                user.id,
                {"type": "error", "payload": {"message": str(exc)}},
            )
            return
        online_user_ids = await self.presence_service.list_online_user_ids()
        recipient_user_ids = await self.chat_service.recipients_for_channel(
            chat_id=message.get("chat_id"),
            candidate_user_ids=online_user_ids,
        )
        await self.connection_manager.broadcast_to_users(
            recipient_user_ids,
            {"type": "chat_message", "payload": message},
        )

    async def _handle_request_chat_history(self, user: User, payload: dict) -> None:
        chat_id = str((payload or {}).get("chat_id") or "global")
        try:
            messages = await self.chat_service.history(
                chat_id=chat_id,
                user_id=user.id,
                limit=_coalesce_int(_parse_int_or_none((payload or {}).get("limit")), settings.CHAT_HISTORY_LIMIT),
            )
        except (ValueError, PermissionError) as exc:
            await self.connection_manager.send_to_user(
                user.id,
                {"type": "error", "payload": {"message": str(exc)}},
            )
            return
        await self.connection_manager.send_to_user(
            user.id,
            {
                "type": "chat_history",
                "payload": {"chat_id": self.chat_service.normalize_chat_id(chat_id), "messages": messages},
            },
        )

    async def _handle_request_chat_channels(self, user: User, payload: dict) -> None:
        await self._send_chat_channels(user)

    async def _handle_create_chat_channel(self, user: User, payload: dict) -> None:
        try:
            await self.chat_service.create_channel(
                creator_id=user.id,
                creator_name=user.username or user.email or user.id,
                name=str((payload or {}).get("name") or ""),
                kind=str((payload or {}).get("kind") or "group"),
                retention_seconds=_parse_int_or_none((payload or {}).get("retention_seconds")),
                is_admin=bool(user.is_admin),
                member_ids=(payload or {}).get("member_ids") if isinstance((payload or {}).get("member_ids"), list) else [],
            )
        except (ValueError, PermissionError) as exc:
            await self.connection_manager.send_to_user(user.id, {"type": "error", "payload": {"message": str(exc)}})
            return
        await self._send_chat_channels(user)

    async def _handle_start_direct_chat(self, user: User, payload: dict) -> None:
        friend_id = str((payload or {}).get("friend_user_id") or "").strip()
        if not friend_id:
            await self.connection_manager.send_to_user(
                user.id,
                {"type": "error", "payload": {"message": "Select a friend first"}},
            )
            return
        try:
            from .database import SessionLocal
            from .friend_service import get_friend_status
            from .user_repository import get_registered_user_by_id

            with SessionLocal() as db:
                if get_friend_status(db, user.id, friend_id) != "friends":
                    raise PermissionError("Direct chat is available only with friends")
                friend = get_registered_user_by_id(db, friend_id)
                if friend is None:
                    raise ValueError("Friend not found")
            channel = await self.chat_service.create_direct_channel(
                creator_id=user.id,
                creator_name=user.username or user.email or user.id,
                friend_id=friend.id,
                friend_name=friend.username or friend.email or friend.id,
            )
        except (ValueError, PermissionError) as exc:
            await self.connection_manager.send_to_user(user.id, {"type": "error", "payload": {"message": str(exc)}})
            return
        await self._send_chat_channels(user)
        await self.connection_manager.send_to_user(
            user.id,
            {"type": "chat_direct_started", "payload": {"chat_id": channel["id"]}},
        )

    async def _handle_remove_chat_channel(self, user: User, payload: dict) -> None:
        try:
            await self.chat_service.remove_channel(
                chat_id=str((payload or {}).get("chat_id") or ""),
                user_id=user.id,
                is_admin=bool(user.is_admin),
            )
        except (ValueError, PermissionError) as exc:
            await self.connection_manager.send_to_user(user.id, {"type": "error", "payload": {"message": str(exc)}})
            return
        await self._send_chat_channels(user)

    async def _handle_leave_chat_channel(self, user: User, payload: dict) -> None:
        try:
            await self.chat_service.leave_channel(
                chat_id=str((payload or {}).get("chat_id") or ""),
                user_id=user.id,
            )
        except (ValueError, PermissionError) as exc:
            await self.connection_manager.send_to_user(user.id, {"type": "error", "payload": {"message": str(exc)}})
            return
        await self._send_chat_channels(user)

    async def _handle_set_chat_muted(self, user: User, payload: dict) -> None:
        try:
            await self.chat_service.set_muted(
                chat_id=str((payload or {}).get("chat_id") or ""),
                user_id=user.id,
                muted=bool((payload or {}).get("muted")),
            )
        except (ValueError, PermissionError) as exc:
            await self.connection_manager.send_to_user(user.id, {"type": "error", "payload": {"message": str(exc)}})
            return
        await self._send_chat_channels(user)

    async def _handle_add_chat_members(self, user: User, payload: dict) -> None:
        try:
            await self.chat_service.add_members(
                chat_id=str((payload or {}).get("chat_id") or ""),
                actor_id=user.id,
                member_ids=(payload or {}).get("member_ids") if isinstance((payload or {}).get("member_ids"), list) else [],
                is_admin=bool(user.is_admin),
            )
        except (ValueError, PermissionError) as exc:
            await self.connection_manager.send_to_user(user.id, {"type": "error", "payload": {"message": str(exc)}})
            return
        await self._send_chat_channels(user)

    async def _handle_kick_chat_member(self, user: User, payload: dict) -> None:
        try:
            await self.chat_service.kick_member(
                chat_id=str((payload or {}).get("chat_id") or ""),
                actor_id=user.id,
                member_id=str((payload or {}).get("member_id") or ""),
                is_admin=bool(user.is_admin),
            )
        except (ValueError, PermissionError) as exc:
            await self.connection_manager.send_to_user(user.id, {"type": "error", "payload": {"message": str(exc)}})
            return
        await self._send_chat_channels(user)

    async def _send_chat_channels(self, user: User) -> None:
        channels = await self.chat_service.list_channels(user_id=user.id)
        await self.connection_manager.send_to_user(
            user.id,
            {"type": "chat_channels", "payload": {"channels": channels}},
        )

def _parse_int_or_none(value) -> int | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _coalesce_int(primary: int | None, fallback: int | None) -> int | None:
    return fallback if primary is None else primary
