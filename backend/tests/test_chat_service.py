import unittest
from unittest.mock import AsyncMock

from backend.app.chat_service import ChatService


class TestChatService(unittest.IsolatedAsyncioTestCase):
    async def test_memory_chat_stores_history_and_share_payload(self):
        service = ChatService(stream_prefix="chat", retention_seconds=60, history_limit=2)

        first = await service.add_message(
            chat_id="global",
            sender_id="p1",
            sender_name="Player 1",
            text="hello",
        )
        second = await service.add_message(
            chat_id="global",
            sender_id="p2",
            sender_name="Player 2",
            text="",
            share={"type": "link", "url": "https://example.test/profile/user_1"},
        )

        history = await service.history(chat_id="global")

        self.assertEqual([message["sender_id"] for message in history], ["p1", "p2"])
        self.assertEqual(first["text"], "hello")
        self.assertEqual(second["share"]["url"], "https://example.test/profile/user_1")

    async def test_redis_chat_uses_minid_trim_and_expire(self):
        redis = AsyncMock()
        redis.exists = AsyncMock(return_value=0)
        redis.hset = AsyncMock()
        redis.sadd = AsyncMock()
        redis.sismember = AsyncMock(return_value=False)
        redis.hgetall = AsyncMock(
            return_value={
                "id": "global:global",
                "kind": "global",
                "name": "Global",
                "created_by": "system",
                "created_at": "2026-04-29T10:00:00+00:00",
                "retention_seconds": "86400",
            }
        )
        redis.xadd = AsyncMock(return_value="1700000000000-0")
        redis.xtrim = AsyncMock()
        redis.expire = AsyncMock()
        redis.xrevrange = AsyncMock(
            return_value=[
                (
                    "1700000000000-0",
                    {
                        "sender_id": "p1",
                        "sender_name": "Player 1",
                        "chat_id": "global:global",
                        "text": "hi",
                        "sent_at": "2026-04-29T10:00:00+00:00",
                        "share": "",
                    },
                )
            ]
        )
        service = ChatService(
            redis_client=redis,
            stream_prefix="chat",
            retention_seconds=86400,
            history_limit=80,
        )

        message = await service.add_message(
            chat_id="global",
            sender_id="p1",
            sender_name="Player 1",
            text="hi",
        )
        history = await service.history(chat_id="global", limit=10)

        self.assertEqual(message["entry_id"], "1700000000000-0")
        redis.xadd.assert_awaited_once()
        stream_key, fields = redis.xadd.await_args.args
        self.assertEqual(stream_key, "chat:stream:global:global")
        self.assertEqual(fields["sender_id"], "p1")
        self.assertEqual(redis.xadd.await_args.kwargs["maxlen"], 1000)
        self.assertTrue(redis.xadd.await_args.kwargs["approximate"])
        redis.xtrim.assert_awaited_once()
        self.assertIn("minid", redis.xtrim.await_args.kwargs)
        redis.expire.assert_awaited_once_with("chat:stream:global:global", 86400)
        redis.xrevrange.assert_awaited_once_with("chat:stream:global:global", count=10)
        self.assertEqual(history[0]["text"], "hi")

    async def test_group_membership_controls_access(self):
        service = ChatService()
        channel = await service.create_channel(
            creator_id="p1",
            creator_name="Player 1",
            name="Raid Group",
            member_ids=["p2"],
        )

        await service.add_message(
            chat_id=channel["id"],
            sender_id="p2",
            sender_name="Player 2",
            text="inside",
        )

        with self.assertRaisesRegex(PermissionError, "not available"):
            await service.add_message(
                chat_id=channel["id"],
                sender_id="p3",
                sender_name="Player 3",
                text="outside",
            )

    async def test_only_admin_can_create_global_channel(self):
        service = ChatService()

        with self.assertRaisesRegex(PermissionError, "Only admins"):
            await service.create_channel(
                creator_id="p1",
                creator_name="Player 1",
                name="Announcements",
                kind="global",
                is_admin=False,
            )

        channel = await service.create_channel(
            creator_id="admin",
            creator_name="Admin",
            name="Announcements",
            kind="global",
            retention_seconds=3600,
            is_admin=True,
        )

        self.assertEqual(channel["kind"], "global")
        self.assertEqual(channel["retention_seconds"], 3600)

    async def test_admin_can_exclude_and_reintegrate_user_from_global_channel(self):
        service = ChatService()
        await service.ensure_default_global_channel()

        self.assertTrue(await service.can_access(chat_id="global", user_id="p2"))
        await service.kick_member(
            chat_id="global",
            actor_id="admin",
            member_id="p2",
            is_admin=True,
        )
        self.assertFalse(await service.can_access(chat_id="global", user_id="p2"))
        await service.add_members(
            chat_id="global",
            actor_id="admin",
            member_ids=["p2"],
            is_admin=True,
        )
        self.assertTrue(await service.can_access(chat_id="global", user_id="p2"))

    async def test_direct_channel_is_deterministic_and_member_only(self):
        service = ChatService()
        first = await service.create_direct_channel(
            creator_id="p1",
            creator_name="Player 1",
            friend_id="p2",
            friend_name="Player 2",
        )
        second = await service.create_direct_channel(
            creator_id="p2",
            creator_name="Player 2",
            friend_id="p1",
            friend_name="Player 1",
        )

        self.assertEqual(first["id"], second["id"])
        self.assertEqual(first["kind"], "direct")
        self.assertTrue(await service.can_access(chat_id=first["id"], user_id="p1"))
        self.assertTrue(await service.can_access(chat_id=first["id"], user_id="p2"))
        self.assertFalse(await service.can_access(chat_id=first["id"], user_id="p3"))

    async def test_empty_messages_are_rejected(self):
        service = ChatService()

        with self.assertRaisesRegex(ValueError, "Message is empty"):
            await service.add_message(
                chat_id="global",
                sender_id="p1",
                sender_name="Player 1",
                text="   ",
            )


if __name__ == "__main__":
    unittest.main()
