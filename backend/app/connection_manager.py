from typing import Dict, List, Optional

try:
    from fastapi import WebSocket
    from fastapi import WebSocketDisconnect
except ImportError:  # pragma: no cover - fallback for test environments without FastAPI installed
    class WebSocket:  # type: ignore[override]
        async def send_json(self, _message: dict):
            return None

    class WebSocketDisconnect(Exception):  # type: ignore[override]
        pass

class ConnectionManager:
    """Manages active WebSocket connections."""
    def __init__(self):
        # Maps user_id to their active WebSocket connection
        self.active_connections: Dict[str, WebSocket] = {}
        self.connection_session_ids: Dict[str, str] = {}
        self._backplane = None

    def set_backplane(self, backplane) -> None:
        self._backplane = backplane

    async def add_connection(
        self,
        user_id: str,
        websocket: WebSocket,
        *,
        session_id: Optional[str] = None,
    ):
        """Adds an already accepted WebSocket connection to the manager."""
        previous = self.active_connections.get(user_id)
        previous_session_id = self.connection_session_ids.get(user_id, "")
        if previous is not None and previous is not websocket:
            close_code = 4002 if previous_session_id and session_id and previous_session_id != session_id else 4001
            try:
                await previous.close(code=close_code)
            except Exception:
                pass
        self.active_connections[user_id] = websocket
        if session_id:
            self.connection_session_ids[user_id] = session_id
        print(f"User connected: {user_id}. Total connections: {len(self.active_connections)}")

    def is_current_connection(self, user_id: str, websocket: Optional[WebSocket]) -> bool:
        if websocket is None:
            return False
        return self.active_connections.get(user_id) is websocket

    def disconnect(self, user_id: str, websocket: Optional[WebSocket] = None):
        """Removes a WebSocket connection."""
        if websocket is not None and self.active_connections.get(user_id) is not websocket:
            return
        if user_id in self.active_connections:
            del self.active_connections[user_id]
            self.connection_session_ids.pop(user_id, None)
            print(f"User disconnected: {user_id}. Total connections: {len(self.active_connections)}")

    async def send_to_user(self, user_id: str, message: dict):
        """Sends a JSON message to a specific user."""
        await self.send_to_user_local(user_id, message)
        if self._backplane is not None:
            await self._backplane.publish_to_user(user_id, message)

    async def send_to_user_local(self, user_id: str, message: dict):
        websocket = self.active_connections.get(user_id)
        if websocket is None:
            return
        try:
            await websocket.send_json(message)
        except (RuntimeError, WebSocketDisconnect):
            self.disconnect(user_id, websocket)

    async def broadcast_to_users(self, user_ids: List[str], message: dict):
        """Sends a JSON message to a list of users."""
        for user_id in user_ids:
            await self.send_to_user(user_id, message)
    
    async def broadcast_to_all(self, message: dict):
        """Sends a JSON message to all connected users."""
        for user_id in list(self.active_connections.keys()):
             await self.send_to_user(user_id, message)
