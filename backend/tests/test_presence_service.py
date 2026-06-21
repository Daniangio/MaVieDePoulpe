import unittest

from backend.app.presence_service import PresenceService


class TestPresenceService(unittest.IsolatedAsyncioTestCase):
    async def test_memory_presence_tracks_location_and_disconnect(self):
        service = PresenceService(ttl_seconds=120)

        await service.mark_connected("user_a", username="Alice", session_id="sess_1")
        connected = await service.get_presence("user_a")
        self.assertIsNotNone(connected)
        self.assertEqual(connected["status"], "online")
        self.assertEqual(connected["username"], "Alice")
        self.assertEqual(connected["session_id"], "sess_1")
        self.assertEqual(connected["location"], "lobby")

        await service.set_location("user_a", location="profile")
        on_profile = await service.get_presence("user_a")
        self.assertEqual(on_profile["location"], "profile")
        self.assertEqual(await service.list_online_user_ids(), ["user_a"])

        await service.mark_disconnected("user_a")
        disconnected = await service.get_presence("user_a")
        self.assertEqual(disconnected["status"], "offline")
        self.assertEqual(disconnected["location"], "offline")
        self.assertEqual(await service.list_online_user_ids(), [])
