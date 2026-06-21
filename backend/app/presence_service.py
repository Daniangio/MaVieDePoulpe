from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional


class PresenceService:
    def __init__(self, redis_client=None, ttl_seconds: int = 120):
        self.redis = redis_client
        self.ttl_seconds = ttl_seconds
        self._memory_presence: Dict[str, Dict[str, Any]] = {}
        self._memory_online_users: set[str] = set()

    def configure_redis(self, redis_client) -> None:
        self.redis = redis_client

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    @staticmethod
    def _user_key(user_id: str) -> str:
        return f"presence:user:{user_id}"

    async def _get_presence(self, user_id: str) -> Dict[str, Any]:
        if self.redis is not None:
            payload = await self.redis.hgetall(self._user_key(user_id))
            return dict(payload or {})
        return dict(self._memory_presence.get(user_id, {}))

    async def _store_presence(self, user_id: str, payload: Dict[str, Any]) -> None:
        previous = await self._get_presence(user_id)
        merged = {
            "user_id": user_id,
            "username": payload.get("username") or previous.get("username") or "",
            "session_id": payload.get("session_id") or previous.get("session_id") or "",
            "status": payload.get("status") or previous.get("status") or "online",
            "location": payload.get("location") or previous.get("location") or "lobby",
            "connected_at": previous.get("connected_at") or payload.get("connected_at") or self._now_iso(),
            "last_seen": payload.get("last_seen") or self._now_iso(),
            "disconnected_at": payload.get("disconnected_at") or "",
        }
        is_online = merged["status"] == "online"
        if self.redis is not None:
            if is_online:
                await self.redis.sadd("presence:online_users", user_id)
            else:
                await self.redis.srem("presence:online_users", user_id)
            await self.redis.hset(self._user_key(user_id), mapping=merged)
            await self.redis.expire(self._user_key(user_id), self.ttl_seconds)
        else:
            if is_online:
                self._memory_online_users.add(user_id)
            else:
                self._memory_online_users.discard(user_id)
            self._memory_presence[user_id] = merged

    async def mark_connected(
        self,
        user_id: str,
        *,
        username: str = "",
        session_id: str = "",
    ) -> None:
        await self._store_presence(
            user_id,
            {
                "username": username,
                "session_id": session_id,
                "status": "online",
                "location": "lobby",
                "last_seen": self._now_iso(),
                "disconnected_at": "",
            },
        )

    async def touch(self, user_id: str) -> None:
        previous = await self._get_presence(user_id)
        if not previous:
            return
        await self._store_presence(
            user_id,
            {
                "username": previous.get("username") or "",
                "session_id": previous.get("session_id") or "",
                "status": previous.get("status") or "online",
                "location": previous.get("location") or "lobby",
                "connected_at": previous.get("connected_at") or self._now_iso(),
                "last_seen": self._now_iso(),
                "disconnected_at": previous.get("disconnected_at") or "",
            },
        )

    async def set_location(self, user_id: str, *, location: str) -> None:
        previous = await self._get_presence(user_id)
        await self._store_presence(
            user_id,
            {
                "username": previous.get("username") or "",
                "session_id": previous.get("session_id") or "",
                "status": "online",
                "location": str(location or "lobby").strip() or "lobby",
                "connected_at": previous.get("connected_at") or self._now_iso(),
                "last_seen": self._now_iso(),
                "disconnected_at": "",
            },
        )

    async def mark_disconnected(self, user_id: str) -> None:
        previous = await self._get_presence(user_id)
        if not previous:
            return
        await self._store_presence(
            user_id,
            {
                "username": previous.get("username") or "",
                "session_id": previous.get("session_id") or "",
                "status": "offline",
                "location": "offline",
                "connected_at": previous.get("connected_at") or self._now_iso(),
                "last_seen": self._now_iso(),
                "disconnected_at": self._now_iso(),
            },
        )

    async def get_presence(self, user_id: str) -> Optional[Dict[str, Any]]:
        payload = await self._get_presence(user_id)
        return payload or None

    async def list_online_user_ids(self) -> list[str]:
        if self.redis is not None:
            members = await self.redis.smembers("presence:online_users")
            return sorted(members or [])
        return sorted(self._memory_online_users)
