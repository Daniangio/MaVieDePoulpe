import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException, WebSocketDisconnect

from backend.app.chat_service import ChatService
from backend.app.connection_manager import ConnectionManager
from backend.app.presence_service import PresenceService
from backend.app.server_models import User
from backend.app.websocket_gateway import WebSocketGateway
from backend.app.websocket_session_router import WebSocketSessionContext, WebSocketSessionRouter


class DummyWebSocket:
    def __init__(self, query_params=None, incoming_messages=None):
        self.query_params = query_params or {}
        self.incoming_messages = list(incoming_messages or [])
        self.sent_messages = []
        self.accepted = False
        self.closed_codes = []

    async def accept(self):
        self.accepted = True

    async def send_json(self, message):
        self.sent_messages.append(message)

    async def receive_json(self):
        if not self.incoming_messages:
            raise WebSocketDisconnect()
        next_message = self.incoming_messages.pop(0)
        if isinstance(next_message, Exception):
            raise next_message
        return next_message

    async def close(self, code=1000):
        self.closed_codes.append(code)


class TestWebSocketSessionRouter(unittest.IsolatedAsyncioTestCase):
    async def test_guest_authentication_accepts_and_returns_guest_context(self):
        connection_manager = ConnectionManager()
        presence_service = AsyncMock(spec=PresenceService)
        router = WebSocketSessionRouter(
            connection_manager=connection_manager,
            presence_service=presence_service,
        )
        websocket = DummyWebSocket(query_params={"guest": "1"})

        context = await router.authenticate(websocket)

        self.assertTrue(websocket.accepted)
        self.assertTrue(context.user.id.startswith("guest_"))
        self.assertEqual(websocket.sent_messages[-1]["type"], "guest_auth_success")

    async def test_authenticate_closes_socket_on_invalid_token(self):
        connection_manager = ConnectionManager()
        presence_service = AsyncMock(spec=PresenceService)
        router = WebSocketSessionRouter(
            connection_manager=connection_manager,
            presence_service=presence_service,
        )
        websocket = DummyWebSocket(query_params={"token": "expired"})

        with patch(
            "backend.app.websocket_session_router.get_current_user",
            side_effect=HTTPException(status_code=401, detail="Could not validate credentials"),
        ):
            with self.assertRaises(HTTPException):
                await router.authenticate(websocket)

        self.assertTrue(websocket.accepted)
        self.assertEqual(websocket.closed_codes[-1], 4401)
        self.assertEqual(websocket.sent_messages[-1]["type"], "auth_error")

    async def test_establish_and_cleanup_mark_presence(self):
        connection_manager = AsyncMock(spec=ConnectionManager)
        connection_manager.is_current_connection.return_value = True
        presence_service = AsyncMock(spec=PresenceService)
        router = WebSocketSessionRouter(
            connection_manager=connection_manager,
            presence_service=presence_service,
        )
        websocket = DummyWebSocket()
        context = WebSocketSessionContext(
            user=User(id="user_a", username="user_a"),
            token="token_a",
            session_id="session_a",
        )

        await router.establish(context, websocket)
        await router.cleanup("user_a", websocket)

        connection_manager.add_connection.assert_awaited_once()
        presence_service.mark_connected.assert_awaited_once_with(
            "user_a",
            username="user_a",
            session_id="session_a",
        )
        connection_manager.disconnect.assert_called_once_with("user_a", websocket)
        presence_service.mark_disconnected.assert_awaited_once_with("user_a")


class TestWebSocketGateway(unittest.IsolatedAsyncioTestCase):
    async def test_chat_message_is_stored_and_broadcast_to_online_users(self):
        connection_manager = AsyncMock(spec=ConnectionManager)
        presence_service = AsyncMock(spec=PresenceService)
        presence_service.list_online_user_ids.return_value = ["user_a", "user_b"]
        session_router = AsyncMock(spec=WebSocketSessionRouter)
        gateway = WebSocketGateway(
            connection_manager=connection_manager,
            presence_service=presence_service,
            session_router=session_router,
            chat_service=ChatService(),
        )
        user = User(id="user_a", username="user_a")

        await gateway._handle_send_chat_message(
            user,
            {"chat_id": "global", "text": "hello", "share": {"type": "link", "url": "https://example.test"}},
        )

        connection_manager.broadcast_to_users.assert_awaited_once()
        user_ids, message = connection_manager.broadcast_to_users.await_args.args
        self.assertEqual(user_ids, ["user_a", "user_b"])
        self.assertEqual(message["type"], "chat_message")
        self.assertEqual(message["payload"]["text"], "hello")

    async def test_chat_history_sends_recent_messages_to_requester(self):
        connection_manager = AsyncMock(spec=ConnectionManager)
        presence_service = AsyncMock(spec=PresenceService)
        session_router = AsyncMock(spec=WebSocketSessionRouter)
        chat_service = ChatService()
        gateway = WebSocketGateway(
            connection_manager=connection_manager,
            presence_service=presence_service,
            session_router=session_router,
            chat_service=chat_service,
        )
        user = User(id="user_a", username="user_a")
        await chat_service.add_message(
            chat_id="global",
            sender_id="user_b",
            sender_name="user_b",
            text="stored",
        )

        await gateway._handle_request_chat_history(user, {"chat_id": "global", "limit": 10})

        connection_manager.send_to_user.assert_awaited_once()
        recipient_id, message = connection_manager.send_to_user.await_args.args
        self.assertEqual(recipient_id, "user_a")
        self.assertEqual(message["type"], "chat_history")
        self.assertEqual(message["payload"]["messages"][0]["text"], "stored")

    async def test_gateway_dispatches_heartbeats_and_cleans_up(self):
        connection_manager = AsyncMock(spec=ConnectionManager)
        presence_service = AsyncMock(spec=PresenceService)
        session_router = AsyncMock(spec=WebSocketSessionRouter)
        session_router.authenticate.return_value = WebSocketSessionContext(
            user=User(id="user_a", username="user_a"),
            token="token",
            session_id="session_a",
        )
        gateway = WebSocketGateway(
            connection_manager=connection_manager,
            presence_service=presence_service,
            session_router=session_router,
        )
        websocket = DummyWebSocket(
            incoming_messages=[
                {"action": "heartbeat", "payload": {}},
                {"action": "unknown_action", "payload": {}},
                WebSocketDisconnect(),
            ]
        )

        await gateway.handle_connection(websocket)

        self.assertEqual(presence_service.touch.await_count, 2)
        session_router.cleanup.assert_awaited_once_with("user_a", websocket)

    async def test_gateway_returns_cleanly_when_authentication_fails(self):
        connection_manager = AsyncMock(spec=ConnectionManager)
        presence_service = AsyncMock(spec=PresenceService)
        session_router = AsyncMock(spec=WebSocketSessionRouter)
        session_router.authenticate.side_effect = HTTPException(
            status_code=401,
            detail="Could not validate credentials",
        )
        gateway = WebSocketGateway(
            connection_manager=connection_manager,
            presence_service=presence_service,
            session_router=session_router,
        )

        await gateway.handle_connection(DummyWebSocket())

        session_router.cleanup.assert_not_called()


if __name__ == "__main__":
    unittest.main()
