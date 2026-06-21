import unittest

from backend.app.game_room_service import GameRoomService, ROOM_STATE_FINISHED, ROOM_STATE_IN_GAME
from backend.app.server_models import User


class TestGameRoomService(unittest.IsolatedAsyncioTestCase):
    async def test_memory_room_lifecycle_records_history(self):
        service = GameRoomService()
        user = User(id="user_1", username="Player One")

        room = await service.create_room(user=user, game_type="quick_match")
        self.assertEqual(room["state"], ROOM_STATE_IN_GAME)
        self.assertEqual(room["mode"], "solo")
        self.assertEqual(room["game_type"], "quick_match")

        await service.enqueue_end_room(room_id=room["id"], user=user)
        finished = await service.get_room(room_id=room["id"], user=user)
        result = await service.get_result(room_id=room["id"], user_id=user.id)
        history = await service.list_history(user_id=user.id)

        self.assertEqual(finished["state"], ROOM_STATE_FINISHED)
        self.assertEqual(result["room_id"], room["id"])
        self.assertEqual(result["outcome"], "completed")
        self.assertEqual([entry["room_id"] for entry in history], [room["id"]])

    async def test_other_users_cannot_read_room_or_result(self):
        service = GameRoomService()
        owner = User(id="owner", username="Owner")
        other = User(id="other", username="Other")

        room = await service.create_room(user=owner, game_type="quick_match")
        await service.enqueue_end_room(room_id=room["id"], user=owner)

        self.assertIsNone(await service.get_room(room_id=room["id"], user=other))
        self.assertIsNone(await service.get_result(room_id=room["id"], user_id=other.id))

    async def test_accepts_arbitrary_placeholder_game_type(self):
        service = GameRoomService()
        user = User(id="user_1", username="Player One")

        room = await service.create_room(user=user, game_type="campaign")
        self.assertEqual(room["game_type"], "campaign")
