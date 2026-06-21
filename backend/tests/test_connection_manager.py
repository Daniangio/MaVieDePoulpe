import unittest

from backend.app.connection_manager import ConnectionManager


class DummyWebSocket:
    def __init__(self):
        self.closed = []
        self.messages = []
        self.raise_on_send = False

    async def close(self, code=1000):
        self.closed.append(code)

    async def send_json(self, message):
        if self.raise_on_send:
            raise RuntimeError("socket already closed")
        self.messages.append(message)


class TestConnectionManager(unittest.IsolatedAsyncioTestCase):
    async def test_replacing_connection_closes_previous_socket(self):
        manager = ConnectionManager()
        old_socket = DummyWebSocket()
        new_socket = DummyWebSocket()

        await manager.add_connection("user_a", old_socket, session_id="sess_a")
        await manager.add_connection("user_a", new_socket, session_id="sess_b")

        self.assertEqual(old_socket.closed, [4002])
        self.assertTrue(manager.is_current_connection("user_a", new_socket))
        self.assertFalse(manager.is_current_connection("user_a", old_socket))

    async def test_disconnect_ignores_stale_socket(self):
        manager = ConnectionManager()
        old_socket = DummyWebSocket()
        new_socket = DummyWebSocket()

        await manager.add_connection("user_a", old_socket, session_id="sess_a")
        await manager.add_connection("user_a", new_socket, session_id="sess_a")

        manager.disconnect("user_a", old_socket)
        self.assertTrue(manager.is_current_connection("user_a", new_socket))

        manager.disconnect("user_a", new_socket)
        self.assertFalse(manager.is_current_connection("user_a", new_socket))

    async def test_send_to_user_drops_broken_socket(self):
        manager = ConnectionManager()
        socket = DummyWebSocket()
        socket.raise_on_send = True

        await manager.add_connection("user_a", socket, session_id="sess_a")
        await manager.send_to_user("user_a", {"type": "ping"})

        self.assertFalse(manager.is_current_connection("user_a", socket))
