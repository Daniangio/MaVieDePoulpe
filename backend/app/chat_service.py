from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


DEFAULT_GLOBAL_CHANNEL_ID = "global:global"
DEFAULT_CHAT_MAXLEN = 1000


class ChatService:
    def __init__(
        self,
        redis_client=None,
        *,
        stream_prefix: str = "chat",
        retention_seconds: int = 86400,
        history_limit: int = 80,
        max_stream_length: int = DEFAULT_CHAT_MAXLEN,
    ) -> None:
        self.redis = redis_client
        self.stream_prefix = str(stream_prefix or "chat").strip() or "chat"
        self.retention_seconds = max(60, int(retention_seconds or 86400))
        self.history_limit = max(1, min(250, int(history_limit or 80)))
        self.max_stream_length = max(100, int(max_stream_length or DEFAULT_CHAT_MAXLEN))
        self._memory_messages: dict[str, list[dict[str, Any]]] = {}
        self._memory_channels: dict[str, dict[str, Any]] = {}
        self._memory_members: dict[str, set[str]] = {}
        self._memory_muted: dict[str, set[str]] = {}
        self._memory_excluded: dict[str, set[str]] = {}

    def configure_redis(self, redis_client) -> None:
        self.redis = redis_client

    def stream_key(self, chat_id: str = DEFAULT_GLOBAL_CHANNEL_ID) -> str:
        return f"{self.stream_prefix}:stream:{self.normalize_chat_id(chat_id)}"

    def channel_key(self, chat_id: str) -> str:
        return f"{self.stream_prefix}:channel:{self.normalize_chat_id(chat_id)}"

    def members_key(self, chat_id: str) -> str:
        return f"{self.stream_prefix}:members:{self.normalize_chat_id(chat_id)}"

    def muted_key(self, chat_id: str) -> str:
        return f"{self.stream_prefix}:muted:{self.normalize_chat_id(chat_id)}"

    def excluded_key(self, chat_id: str) -> str:
        return f"{self.stream_prefix}:excluded:{self.normalize_chat_id(chat_id)}"

    @property
    def channels_key(self) -> str:
        return f"{self.stream_prefix}:channels"

    @staticmethod
    def normalize_chat_id(chat_id: str | None) -> str:
        text = str(chat_id or "").strip()
        if not text or text == "global":
            return DEFAULT_GLOBAL_CHANNEL_ID
        if ":" not in text:
            return f"group:{text}"
        return text

    @staticmethod
    def direct_chat_id(user_a: str, user_b: str) -> str:
        left, right = sorted([str(user_a or "").strip(), str(user_b or "").strip()])
        if not left or not right:
            raise ValueError("Direct chat requires two users")
        if left == right:
            raise ValueError("Cannot start a direct chat with yourself")
        return f"direct:{left}:{right}"

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _normalize_message_text(text: object) -> str:
        return str(text or "").replace("\x00", "").strip()[:1000]

    @staticmethod
    def _normalize_channel_name(name: object) -> str:
        return re.sub(r"\s+", " ", str(name or "").replace("\x00", " ")).strip()[:60]

    @staticmethod
    def _slug(value: object) -> str:
        normalized = re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")
        return normalized[:42] or uuid4().hex[:10]

    async def list_channels(self, *, user_id: str) -> list[dict]:
        await self.ensure_default_global_channel()
        if self.redis is None:
            return self._memory_list_channels(user_id=user_id)
        channel_ids = await self.redis.smembers(self.channels_key)
        channels = []
        for chat_id in sorted(str(entry) for entry in (channel_ids or [])):
            metadata = await self._redis_channel_metadata(chat_id)
            if not metadata:
                continue
            if metadata["kind"] in {"group", "direct"}:
                is_member = await self.redis.sismember(self.members_key(chat_id), user_id)
                if not is_member:
                    continue
            muted = await self.redis.sismember(self.muted_key(chat_id), user_id)
            channels.append({**metadata, "muted": bool(muted)})
        return channels

    async def ensure_default_global_channel(self) -> None:
        if self.redis is None:
            if DEFAULT_GLOBAL_CHANNEL_ID not in self._memory_channels:
                self._memory_channels[DEFAULT_GLOBAL_CHANNEL_ID] = self._channel_payload(
                    {
                        "id": DEFAULT_GLOBAL_CHANNEL_ID,
                        "kind": "global",
                        "name": "Global",
                        "created_by": "system",
                        "created_at": self._now().isoformat(),
                        "retention_seconds": self.retention_seconds,
                    }
                )
            return
        exists = await self.redis.exists(self.channel_key(DEFAULT_GLOBAL_CHANNEL_ID))
        if exists:
            await self.redis.sadd(self.channels_key, DEFAULT_GLOBAL_CHANNEL_ID)
            return
        now = self._now().isoformat()
        metadata = {
            "id": DEFAULT_GLOBAL_CHANNEL_ID,
            "kind": "global",
            "name": "Global",
            "created_by": "system",
            "created_at": now,
            "retention_seconds": str(self.retention_seconds),
        }
        await self.redis.hset(self.channel_key(DEFAULT_GLOBAL_CHANNEL_ID), mapping=metadata)
        await self.redis.sadd(self.channels_key, DEFAULT_GLOBAL_CHANNEL_ID)

    async def create_channel(
        self,
        *,
        creator_id: str,
        creator_name: str,
        name: str,
        kind: str = "group",
        retention_seconds: int | None = None,
        is_admin: bool = False,
        member_ids: list[str] | None = None,
    ) -> dict:
        normalized_kind = str(kind or "group").strip().lower()
        if normalized_kind not in {"global", "group", "direct"}:
            raise ValueError("Unsupported chat channel kind")
        if normalized_kind == "global" and not is_admin:
            raise PermissionError("Only admins can create global channels")
        if normalized_kind == "direct":
            normalized_members = sorted({
                str(member_id).strip()
                for member_id in [creator_id, *(member_ids or [])]
                if str(member_id).strip()
            })
            if len(normalized_members) != 2:
                raise ValueError("Direct chat requires exactly two users")
            channel_id = self.direct_chat_id(normalized_members[0], normalized_members[1])
        else:
            normalized_members = sorted({
                str(member_id).strip()
                for member_id in [creator_id, *(member_ids or [])]
                if str(member_id).strip()
            })
        normalized_name = self._normalize_channel_name(name)
        if not normalized_name and normalized_kind != "direct":
            raise ValueError("Channel name is required")
        if normalized_kind == "global":
            channel_id = f"global:{self._slug(normalized_name)}"
        elif normalized_kind == "group":
            channel_id = f"group:{uuid4().hex}"
        display_name = normalized_name or "Direct Chat"
        resolved_retention = (
            max(60, int(retention_seconds or self.retention_seconds))
            if normalized_kind == "global" and is_admin
            else self.retention_seconds
        )
        now = self._now().isoformat()
        metadata = {
            "id": channel_id,
            "kind": normalized_kind,
            "name": display_name,
            "created_by": str(creator_id),
            "created_by_name": str(creator_name or creator_id),
            "created_at": now,
            "retention_seconds": str(resolved_retention),
        }
        members = set(normalized_members)

        if self.redis is None:
            if channel_id in self._memory_channels:
                return {**self._memory_channels[channel_id], "muted": creator_id in self._memory_muted.get(channel_id, set())}
            self._memory_channels[channel_id] = self._channel_payload(metadata)
            if normalized_kind in {"group", "direct"}:
                self._memory_members[channel_id] = members
            return {**self._memory_channels[channel_id], "muted": False}

        if await self.redis.exists(self.channel_key(channel_id)):
            existing = await self._redis_channel_metadata(channel_id)
            muted = await self.redis.sismember(self.muted_key(channel_id), creator_id)
            return {**existing, "muted": bool(muted)}
        await self.redis.hset(self.channel_key(channel_id), mapping=metadata)
        await self.redis.sadd(self.channels_key, channel_id)
        if normalized_kind in {"group", "direct"}:
            await self.redis.sadd(self.members_key(channel_id), *members)
        return {**self._channel_payload(metadata), "muted": False}

    async def create_direct_channel(
        self,
        *,
        creator_id: str,
        creator_name: str,
        friend_id: str,
        friend_name: str,
    ) -> dict:
        return await self.create_channel(
            creator_id=creator_id,
            creator_name=creator_name,
            name=f"{creator_name or creator_id}, {friend_name or friend_id}",
            kind="direct",
            member_ids=[friend_id],
        )

    async def remove_channel(self, *, chat_id: str, user_id: str, is_admin: bool = False) -> dict:
        normalized_chat_id = self.normalize_chat_id(chat_id)
        metadata = await self.get_channel(chat_id=normalized_chat_id)
        if not metadata:
            raise ValueError("Chat channel not found")
        if metadata["kind"] == "global" and not is_admin:
            raise PermissionError("Only admins can remove global channels")
        if metadata["kind"] in {"group", "direct"} and metadata.get("created_by") != user_id and not is_admin:
            raise PermissionError("Only the group creator can disband this group")
        if normalized_chat_id == DEFAULT_GLOBAL_CHANNEL_ID:
            raise ValueError("Default global channel cannot be removed")

        if self.redis is None:
            self._memory_channels.pop(normalized_chat_id, None)
            self._memory_members.pop(normalized_chat_id, None)
            self._memory_muted.pop(normalized_chat_id, None)
            self._memory_messages.pop(normalized_chat_id, None)
        else:
            await self.redis.srem(self.channels_key, normalized_chat_id)
            await self.redis.delete(
                self.channel_key(normalized_chat_id),
                self.members_key(normalized_chat_id),
                self.muted_key(normalized_chat_id),
                self.excluded_key(normalized_chat_id),
                self.stream_key(normalized_chat_id),
            )
        return {"chat_id": normalized_chat_id, "removed": True}

    async def leave_channel(self, *, chat_id: str, user_id: str) -> dict:
        normalized_chat_id = self.normalize_chat_id(chat_id)
        metadata = await self.get_channel(chat_id=normalized_chat_id)
        if not metadata or metadata["kind"] not in {"group", "direct"}:
            raise ValueError("Only custom groups can be left")
        if metadata.get("created_by") == user_id:
            raise ValueError("Group creator must disband the group")
        if self.redis is None:
            self._memory_members.setdefault(normalized_chat_id, set()).discard(user_id)
            self._memory_muted.setdefault(normalized_chat_id, set()).discard(user_id)
        else:
            await self.redis.srem(self.members_key(normalized_chat_id), user_id)
            await self.redis.srem(self.muted_key(normalized_chat_id), user_id)
        return {"chat_id": normalized_chat_id, "left": True}

    async def set_muted(self, *, chat_id: str, user_id: str, muted: bool) -> dict:
        normalized_chat_id = self.normalize_chat_id(chat_id)
        if not await self.can_access(chat_id=normalized_chat_id, user_id=user_id):
            raise PermissionError("Chat channel is not available")
        if self.redis is None:
            muted_users = self._memory_muted.setdefault(normalized_chat_id, set())
            if muted:
                muted_users.add(user_id)
            else:
                muted_users.discard(user_id)
        else:
            if muted:
                await self.redis.sadd(self.muted_key(normalized_chat_id), user_id)
            else:
                await self.redis.srem(self.muted_key(normalized_chat_id), user_id)
        return {"chat_id": normalized_chat_id, "muted": bool(muted)}

    async def add_members(
        self,
        *,
        chat_id: str,
        actor_id: str,
        member_ids: list[str],
        is_admin: bool = False,
    ) -> dict:
        normalized_chat_id = self.normalize_chat_id(chat_id)
        metadata = await self.get_channel(chat_id=normalized_chat_id)
        if not metadata:
            raise ValueError("Chat channel not found")
        if metadata["kind"] == "direct":
            raise ValueError("Members cannot be added to direct chats")
        if metadata["kind"] == "global":
            if not is_admin:
                raise PermissionError("Only admins can reintegrate users in global channels")
            normalized_members = sorted({str(member_id).strip() for member_id in member_ids if str(member_id).strip()})
            if not normalized_members:
                raise ValueError("No users selected")
            if self.redis is None:
                excluded = self._memory_excluded.setdefault(normalized_chat_id, set())
                for member_id in normalized_members:
                    excluded.discard(member_id)
            else:
                await self.redis.srem(self.excluded_key(normalized_chat_id), *normalized_members)
            return {"chat_id": normalized_chat_id, "members": normalized_members}
        if metadata["kind"] != "group":
            raise ValueError("Members can only be added to custom groups")
        if metadata.get("created_by") != actor_id and not is_admin:
            raise PermissionError("Only the group creator can add members")
        normalized_members = sorted({str(member_id).strip() for member_id in member_ids if str(member_id).strip()})
        if not normalized_members:
            raise ValueError("No users selected")
        if self.redis is None:
            self._memory_members.setdefault(normalized_chat_id, set()).update(normalized_members)
        else:
            await self.redis.sadd(self.members_key(normalized_chat_id), *normalized_members)
        return {"chat_id": normalized_chat_id, "members": normalized_members}

    async def kick_member(
        self,
        *,
        chat_id: str,
        actor_id: str,
        member_id: str,
        is_admin: bool = False,
    ) -> dict:
        normalized_chat_id = self.normalize_chat_id(chat_id)
        target_member_id = str(member_id or "").strip()
        metadata = await self.get_channel(chat_id=normalized_chat_id)
        if not metadata:
            raise ValueError("Chat channel not found")
        if metadata["kind"] == "direct":
            raise ValueError("Members cannot be kicked from direct chats")
        if metadata["kind"] == "global":
            if not is_admin:
                raise PermissionError("Only admins can kick users from global channels")
            if self.redis is None:
                self._memory_excluded.setdefault(normalized_chat_id, set()).add(target_member_id)
            else:
                await self.redis.sadd(self.excluded_key(normalized_chat_id), target_member_id)
            return {"chat_id": normalized_chat_id, "member_id": target_member_id, "kicked": True}
        if metadata["kind"] != "group":
            raise ValueError("Members can only be removed from custom groups")
        if metadata.get("created_by") != actor_id and not is_admin:
            raise PermissionError("Only the group creator can kick members")
        if target_member_id == metadata.get("created_by"):
            raise ValueError("Group creator cannot be kicked")
        if self.redis is None:
            self._memory_members.setdefault(normalized_chat_id, set()).discard(target_member_id)
            self._memory_muted.setdefault(normalized_chat_id, set()).discard(target_member_id)
        else:
            await self.redis.srem(self.members_key(normalized_chat_id), target_member_id)
            await self.redis.srem(self.muted_key(normalized_chat_id), target_member_id)
        return {"chat_id": normalized_chat_id, "member_id": target_member_id, "kicked": True}

    async def get_channel(self, *, chat_id: str) -> dict | None:
        await self.ensure_default_global_channel()
        normalized_chat_id = self.normalize_chat_id(chat_id)
        if self.redis is None:
            return self._memory_channels.get(normalized_chat_id)
        return await self._redis_channel_metadata(normalized_chat_id)

    async def can_access(self, *, chat_id: str, user_id: str) -> bool:
        metadata = await self.get_channel(chat_id=chat_id)
        if not metadata:
            return False
        if metadata["kind"] == "global":
            if self.redis is None:
                return user_id not in self._memory_excluded.get(metadata["id"], set())
            return not bool(await self.redis.sismember(self.excluded_key(metadata["id"]), user_id))
        if self.redis is None:
            return user_id in self._memory_members.get(metadata["id"], set())
        return bool(await self.redis.sismember(self.members_key(metadata["id"]), user_id))

    async def is_muted(self, *, chat_id: str, user_id: str) -> bool:
        normalized_chat_id = self.normalize_chat_id(chat_id)
        if self.redis is None:
            return user_id in self._memory_muted.get(normalized_chat_id, set())
        return bool(await self.redis.sismember(self.muted_key(normalized_chat_id), user_id))

    async def recipients_for_channel(self, *, chat_id: str, candidate_user_ids: list[str]) -> list[str]:
        normalized_chat_id = self.normalize_chat_id(chat_id)
        recipients = []
        for user_id in candidate_user_ids or []:
            normalized_user_id = str(user_id or "").strip()
            if not normalized_user_id:
                continue
            if not await self.can_access(chat_id=normalized_chat_id, user_id=normalized_user_id):
                continue
            if await self.is_muted(chat_id=normalized_chat_id, user_id=normalized_user_id):
                continue
            recipients.append(normalized_user_id)
        return recipients

    async def add_message(
        self,
        *,
        chat_id: str = DEFAULT_GLOBAL_CHANNEL_ID,
        sender_id: str,
        sender_name: str,
        text: str,
        share: dict | None = None,
    ) -> dict:
        normalized_chat_id = self.normalize_chat_id(chat_id)
        if not await self.can_access(chat_id=normalized_chat_id, user_id=sender_id):
            raise PermissionError("Chat channel is not available")
        metadata = await self.get_channel(chat_id=normalized_chat_id)
        normalized_text = self._normalize_message_text(text)
        if not normalized_text and not share:
            raise ValueError("Message is empty")
        now = self._now()
        fields = {
            "chat_id": normalized_chat_id,
            "sender_id": str(sender_id or ""),
            "sender_name": str(sender_name or sender_id or ""),
            "text": normalized_text,
            "sent_at": now.isoformat(),
            "share": "" if not isinstance(share, dict) else self._encode_share(share),
        }
        retention_seconds = int(metadata.get("retention_seconds") or self.retention_seconds)
        if self.redis is None:
            message = {"entry_id": f"memory-{int(now.timestamp() * 1000)}", **fields}
            self._memory_messages.setdefault(normalized_chat_id, []).append(message)
            self._memory_messages[normalized_chat_id] = self._memory_messages[normalized_chat_id][
                -self.max_stream_length :
            ]
            return self._message_payload(message)

        threshold_ms = int((now.timestamp() - retention_seconds) * 1000)
        stream_key = self.stream_key(normalized_chat_id)
        entry_id = await self.redis.xadd(
            stream_key,
            fields,
            maxlen=self.max_stream_length,
            approximate=True,
        )
        try:
            await self.redis.xtrim(stream_key, minid=str(threshold_ms), approximate=True)
        except TypeError:
            await self.redis.xtrim(stream_key, minid=str(threshold_ms))
        await self.redis.expire(stream_key, retention_seconds)
        return self._message_payload({"entry_id": str(entry_id), **fields})

    async def history(self, *, chat_id: str = DEFAULT_GLOBAL_CHANNEL_ID, user_id: str = "", limit: int | None = None) -> list[dict]:
        normalized_chat_id = self.normalize_chat_id(chat_id)
        if user_id and not await self.can_access(chat_id=normalized_chat_id, user_id=user_id):
            raise PermissionError("Chat channel is not available")
        normalized_limit = max(1, min(250, int(limit or self.history_limit)))
        if self.redis is None:
            return [
                self._message_payload(message)
                for message in self._memory_messages.get(normalized_chat_id, [])[-normalized_limit:]
            ]
        entries = await self.redis.xrevrange(self.stream_key(normalized_chat_id), count=normalized_limit)
        return [
            self._message_payload({"entry_id": str(entry_id), **dict(fields or {})})
            for entry_id, fields in reversed(list(entries or []))
        ]

    async def _redis_channel_metadata(self, chat_id: str) -> dict | None:
        raw = await self.redis.hgetall(self.channel_key(chat_id))
        if not raw:
            return None
        return self._channel_payload(raw)

    def _memory_list_channels(self, *, user_id: str) -> list[dict]:
        channels = []
        for channel_id in sorted(self._memory_channels):
            metadata = self._memory_channels[channel_id]
            if metadata["kind"] == "group" and user_id not in self._memory_members.get(channel_id, set()):
                continue
            channels.append({**metadata, "muted": user_id in self._memory_muted.get(channel_id, set())})
        return channels

    def _channel_payload(self, raw: dict) -> dict:
        retention = int(raw.get("retention_seconds") or self.retention_seconds)
        return {
            "id": str(raw.get("id") or DEFAULT_GLOBAL_CHANNEL_ID),
            "kind": str(raw.get("kind") or "global"),
            "name": str(raw.get("name") or "Global"),
            "created_by": str(raw.get("created_by") or ""),
            "created_by_name": str(raw.get("created_by_name") or raw.get("created_by") or ""),
            "created_at": str(raw.get("created_at") or ""),
            "retention_seconds": retention,
        }

    @staticmethod
    def _encode_share(share: dict) -> str:
        return json.dumps(share, default=str, separators=(",", ":"))[:2000]

    @staticmethod
    def _decode_share(raw: object) -> dict | None:
        text = str(raw or "").strip()
        if not text:
            return None
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None

    def _message_payload(self, raw: dict) -> dict:
        return {
            "entry_id": str(raw.get("entry_id") or ""),
            "chat_id": self.normalize_chat_id(str(raw.get("chat_id") or DEFAULT_GLOBAL_CHANNEL_ID)),
            "sender_id": str(raw.get("sender_id") or ""),
            "sender_name": str(raw.get("sender_name") or raw.get("sender_id") or ""),
            "text": str(raw.get("text") or ""),
            "sent_at": str(raw.get("sent_at") or ""),
            "share": self._decode_share(raw.get("share")),
        }
