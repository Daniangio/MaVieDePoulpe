from __future__ import annotations

import asyncio
import json
import time
import uuid
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import WebSocket

from .server_models import User


ROOM_STATE_SETUP = "SETUP"
ROOM_STATE_IN_GAME = "IN_GAME"
ROOM_STATE_FINISHED = "FINISHED"
COMMAND_STREAM_KEY = "game:commands"
PHASE_SETUP = "setup"
PHASE_NIGHT_ACTION = "night_action"
PHASE_FINISHED = "game_over"
DEFAULT_ACTIVE_CAPABILITY_ID = "poulpita"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _history_key(user_id: str) -> str:
    return f"game:user:{user_id}:history"


def _iso_to_epoch(value: Any) -> float:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return time.time()


def _public_room(room: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": room.get("id", ""),
        "owner_user_id": room.get("owner_user_id", ""),
        "mode": room.get("mode", "goldfish"),
        "game_type": room.get("game_type", "goldfish"),
        "state": room.get("state", ROOM_STATE_SETUP),
        "created_at": room.get("created_at", ""),
        "started_at": room.get("started_at") or "",
        "ended_at": room.get("ended_at") or None,
        "result_id": room.get("result_id") or None,
    }


def _load_map_config() -> dict[str, Any]:
    path = Path(__file__).resolve().parent / "content" / "map.json"
    with path.open("r", encoding="utf-8") as handle:
        config = json.load(handle)
    _validate_map_config(config)
    return config


def _validate_map_config(config: dict[str, Any]) -> None:
    nodes = config.get("nodes") or {}
    if len(nodes) != 16:
        raise ValueError("Map config must define exactly 16 nodes.")
    starting_node_id = str(config.get("starting_node_id") or "")
    if starting_node_id not in nodes:
        raise ValueError("Map starting_node_id must reference an existing node.")
    for node_id, node in nodes.items():
        tier = int(node.get("tier") or 0)
        if tier < 1:
            raise ValueError(f"Map node {node_id} has an invalid tier.")
        for adjacent_id in node.get("adjacent") or []:
            if adjacent_id not in nodes:
                raise ValueError(f"Map node {node_id} references unknown adjacent node {adjacent_id}.")
            if node_id not in (nodes[adjacent_id].get("adjacent") or []):
                raise ValueError(f"Map adjacency must be symmetric between {node_id} and {adjacent_id}.")


MAP_CONFIG = _load_map_config()


@dataclass
class CommandRejection(Exception):
    command_id: str
    reason: str
    message: str
    current_version: int

    def payload(self, projection: dict[str, Any] | None = None) -> dict[str, Any]:
        data: dict[str, Any] = {
            "ok": False,
            "status": "rejected",
            "command_id": self.command_id,
            "revision": self.current_version,
            "reason": self.reason,
            "message": self.message,
            "current_version": self.current_version,
        }
        if projection is not None:
            data["projection"] = projection
        return data


def _setup_state(room_id: str) -> dict[str, Any]:
    return {
        "room_id": room_id,
        "mode": "goldfish",
        "version": 0,
        "phase": PHASE_SETUP,
        "level_id": "goldfish_movement",
        "active_capability_id": None,
        "last_active_capability_id": None,
        "map": {"nodes": {}, "adjacency": {}},
        "poulpita": {"node_id": None, "previous_node_id": None},
        "event_log": [],
    }


def _goldfish_state(room_id: str) -> dict[str, Any]:
    nodes = {}
    adjacency = {}
    for node_id, node in MAP_CONFIG["nodes"].items():
        nodes[node_id] = {
            "id": node_id,
            "tier": int(node["tier"]),
            "x": int(node.get("x") or 0),
            "y": int(node.get("y") or 0),
        }
        adjacency[node_id] = list(node.get("adjacent") or [])
    return {
        "room_id": room_id,
        "mode": "goldfish",
        "version": 1,
        "phase": PHASE_NIGHT_ACTION,
        "level_id": "goldfish_movement",
        "active_capability_id": DEFAULT_ACTIVE_CAPABILITY_ID,
        "last_active_capability_id": None,
        "map": {"nodes": nodes, "adjacency": adjacency},
        "poulpita": {
            "node_id": str(MAP_CONFIG["starting_node_id"]),
            "previous_node_id": None,
        },
        "event_log": [
            {
                "event_id": f"evt_{uuid.uuid4().hex}",
                "type": "goldfish_game_started",
                "version": 1,
                "created_at": _now_iso(),
            }
        ],
    }


def _project_state(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "room_id": state["room_id"],
        "projection_mode": "goldfish",
        "privacy_enforced": False,
        "mode": state["mode"],
        "version": int(state["version"]),
        "phase": state["phase"],
        "level_id": state["level_id"],
        "active_capability_id": state.get("active_capability_id"),
        "last_active_capability_id": state.get("last_active_capability_id"),
        "map": deepcopy(state["map"]),
        "poulpita": deepcopy(state["poulpita"]),
        "events": list(state.get("event_log") or [])[-20:],
    }


class GameRoomService:
    def __init__(self, redis_client=None) -> None:
        self.redis = redis_client
        self._memory_rooms: dict[str, dict[str, Any]] = {}
        self._memory_states: dict[str, dict[str, Any]] = {}
        self._memory_results: dict[str, dict[str, Any]] = {}
        self._memory_history: dict[str, list[str]] = {}
        self._room_locks: dict[str, asyncio.Lock] = {}
        self._room_sockets: dict[str, set[WebSocket]] = {}

    def configure_redis(self, redis_client) -> None:
        self.redis = redis_client

    async def create_room(self, *, user: User, game_type: str = "goldfish") -> dict[str, Any]:
        normalized_game_type = str(game_type or "goldfish").strip() or "goldfish"
        room_id = f"room_{uuid.uuid4().hex[:16]}"
        now = _now_iso()
        room = {
            "id": room_id,
            "owner_user_id": user.id,
            "owner_username": user.username or user.email or user.id,
            "mode": "goldfish",
            "game_type": normalized_game_type,
            "state": ROOM_STATE_SETUP,
            "created_at": now,
            "started_at": "",
            "ended_at": "",
            "result_id": "",
        }
        self._memory_rooms[room_id] = room
        self._memory_states[room_id] = _setup_state(room_id)
        self._room_locks[room_id] = asyncio.Lock()
        return _public_room(room)

    async def get_room(self, *, room_id: str, user: User) -> dict[str, Any] | None:
        room = self._memory_rooms.get(room_id)
        if not room or room.get("owner_user_id") != user.id:
            return None
        return _public_room(room)

    async def join_room(self, *, room_id: str, user: User) -> dict[str, str] | None:
        room = self._memory_rooms.get(room_id)
        if not room or room.get("owner_user_id") != user.id:
            return None
        return {"room_id": room_id, "seat_id": "goldfish"}

    async def get_projection(self, *, room_id: str, user: User) -> dict[str, Any] | None:
        room = self._memory_rooms.get(room_id)
        if not room or room.get("owner_user_id") != user.id:
            return None
        return _project_state(self._memory_states[room_id])

    async def get_game_state(self, *, room_id: str, user: User, selected_tile: str | None = None) -> dict[str, Any] | None:
        return await self.get_projection(room_id=room_id, user=user)

    async def enqueue_game_command(
        self,
        *,
        room_id: str,
        user: User,
        command: dict[str, Any],
    ) -> dict[str, Any]:
        return await self.apply_command(room_id=room_id, user=user, command=command)

    async def apply_command(self, *, room_id: str, user: User, command: dict[str, Any]) -> dict[str, Any]:
        room = self._memory_rooms.get(room_id)
        if not room or room.get("owner_user_id") != user.id:
            raise LookupError("Game room not found.")
        lock = self._room_locks.setdefault(room_id, asyncio.Lock())
        async with lock:
            state = self._memory_states[room_id]
            try:
                next_state, events = self._reduce(state, command, user=user, room_id=room_id)
            except CommandRejection as rejection:
                return rejection.payload(_project_state(state))
            self._memory_states[room_id] = next_state
            if next_state["phase"] != PHASE_SETUP:
                room.update({"state": ROOM_STATE_IN_GAME, "started_at": room.get("started_at") or _now_iso()})
                self._memory_rooms[room_id] = room
            projection = _project_state(next_state)
        await self.broadcast_projection(room_id)
        return {
            "ok": True,
            "status": "accepted",
            "command_id": str(command.get("command_id") or ""),
            "revision": int(next_state["version"]),
            "version": int(next_state["version"]),
            "events": events,
            "projection": projection,
        }

    def _reject(self, state: dict[str, Any], command_id: str, reason: str, message: str) -> None:
        raise CommandRejection(
            command_id=command_id,
            reason=reason,
            message=message,
            current_version=int(state.get("version") or 0),
        )

    def _reduce(
        self,
        state: dict[str, Any],
        command: dict[str, Any],
        *,
        user: User,
        room_id: str,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        command_id = str(command.get("command_id") or "").strip() or f"cmd_{uuid.uuid4().hex}"
        command_type = str(command.get("type") or "").strip()
        expected_version = command.get("expected_version")
        if expected_version is None:
            expected_version = command.get("expected_revision")
        if expected_version is not None:
            try:
                normalized_expected_version = int(expected_version)
            except (TypeError, ValueError):
                self._reject(state, command_id, "invalid_expected_version", "expected_version must be an integer.")
            if normalized_expected_version != int(state["version"]):
                self._reject(
                    state,
                    command_id,
                    "state_version_conflict",
                    "The room has already advanced. Refresh the board and try again.",
                )
        if command.get("room_id") and str(command.get("room_id")) != room_id:
            self._reject(state, command_id, "room_mismatch", "Command room_id does not match the URL room.")
        if command.get("actor_user_id") and str(command.get("actor_user_id")) != user.id:
            self._reject(state, command_id, "actor_mismatch", "Command actor does not match the authenticated user.")

        if command_type == "start_goldfish_game":
            if state["phase"] != PHASE_SETUP:
                self._reject(state, command_id, "game_already_started", "This goldfish game has already started.")
            next_state = _goldfish_state(room_id)
            event = next_state["event_log"][0]
            return next_state, [event]

        if command_type == "move_poulpita":
            if state["phase"] != PHASE_NIGHT_ACTION:
                self._reject(state, command_id, "phase_not_movable", "Poulpita can move only after the goldfish game has started.")
            payload = command.get("payload") or {}
            if not isinstance(payload, dict):
                self._reject(state, command_id, "invalid_payload", "Command payload must be an object.")
            capability_id = str(payload.get("capability_id") or "")
            target_node_id = str(payload.get("target_node_id") or "")
            if capability_id != state.get("active_capability_id"):
                self._reject(state, command_id, "not_active_capability", "Only the active capability can move Poulpita.")
            nodes = state["map"]["nodes"]
            if target_node_id not in nodes:
                self._reject(state, command_id, "unknown_target_node", "Target node does not exist.")
            current_node_id = str(state["poulpita"]["node_id"])
            if target_node_id not in (state["map"]["adjacency"].get(current_node_id) or []):
                self._reject(state, command_id, "non_adjacent_node", "Poulpita can move only to an adjacent node.")
            next_state = deepcopy(state)
            next_state["version"] = int(state["version"]) + 1
            next_state["poulpita"]["previous_node_id"] = current_node_id
            next_state["poulpita"]["node_id"] = target_node_id
            event = {
                "event_id": f"evt_{uuid.uuid4().hex}",
                "type": "poulpita_moved",
                "command_id": command_id,
                "from_node_id": current_node_id,
                "to_node_id": target_node_id,
                "version": int(next_state["version"]),
                "created_at": _now_iso(),
            }
            next_state.setdefault("event_log", []).append(event)
            return next_state, [event]

        self._reject(state, command_id, "unknown_command", f"Unknown command type: {command_type or '<missing>'}.")

    async def connect_room_socket(self, *, room_id: str, user: User, websocket: WebSocket) -> bool:
        room = self._memory_rooms.get(room_id)
        if not room or room.get("owner_user_id") != user.id:
            return False
        await websocket.accept()
        self._room_sockets.setdefault(room_id, set()).add(websocket)
        await websocket.send_json({"type": "state_projection", "payload": _project_state(self._memory_states[room_id])})
        return True

    def disconnect_room_socket(self, *, room_id: str, websocket: WebSocket) -> None:
        sockets = self._room_sockets.get(room_id)
        if sockets is None:
            return
        sockets.discard(websocket)
        if not sockets:
            self._room_sockets.pop(room_id, None)

    async def broadcast_projection(self, room_id: str) -> None:
        sockets = list(self._room_sockets.get(room_id) or [])
        if not sockets or room_id not in self._memory_states:
            return
        message = {"type": "state_projection", "payload": _project_state(self._memory_states[room_id])}
        stale: list[WebSocket] = []
        for websocket in sockets:
            try:
                await websocket.send_json(message)
            except Exception:
                stale.append(websocket)
        for websocket in stale:
            self.disconnect_room_socket(room_id=room_id, websocket=websocket)

    async def enqueue_end_room(self, *, room_id: str, user: User) -> dict[str, Any]:
        room = self._memory_rooms.get(room_id)
        if not room or room.get("owner_user_id") != user.id:
            raise LookupError("Game room not found.")
        if room.get("state") == ROOM_STATE_FINISHED:
            return _public_room(room)
        await self.finish_room(room_id=room_id, user_id=user.id)
        await self.broadcast_projection(room_id)
        return _public_room(self._memory_rooms[room_id])

    async def finish_room(self, *, room_id: str, user_id: str) -> dict[str, Any] | None:
        room = self._memory_rooms.get(room_id)
        if not room or room.get("owner_user_id") != user_id:
            return None
        if room.get("state") == ROOM_STATE_FINISHED:
            return await self.get_result(room_id=room_id, user_id=user_id)
        now = _now_iso()
        state = self._memory_states.get(room_id) or _setup_state(room_id)
        result = {
            "id": room_id,
            "room_id": room_id,
            "user_id": user_id,
            "mode": room.get("mode", "goldfish"),
            "game_type": room.get("game_type", "goldfish"),
            "outcome": "completed",
            "score": "0",
            "turns": str(max(0, int(state.get("version") or 0) - 1)),
            "duration_seconds": str(max(1, int(time.time() - _iso_to_epoch(room.get("started_at") or room.get("created_at"))))),
            "summary": "Goldfish prototype room ended.",
            "created_at": now,
        }
        next_state = deepcopy(state)
        next_state["phase"] = PHASE_FINISHED
        next_state["version"] = int(next_state.get("version") or 0) + 1
        room.update({"state": ROOM_STATE_FINISHED, "ended_at": now, "result_id": room_id})
        self._memory_rooms[room_id] = room
        self._memory_states[room_id] = next_state
        self._memory_results[room_id] = result
        self._memory_history.setdefault(user_id, [])
        if room_id not in self._memory_history[user_id]:
            self._memory_history[user_id].append(room_id)
        if self.redis is not None:
            await self.redis.zadd(_history_key(user_id), {room_id: time.time()})
        return self._public_result(result)

    async def get_result(self, *, room_id: str, user_id: str) -> dict[str, Any] | None:
        result = self._memory_results.get(room_id)
        if not result or result.get("user_id") != user_id:
            return None
        return self._public_result(result)

    async def list_history(self, *, user_id: str, limit: int = 25) -> list[dict[str, Any]]:
        normalized_limit = max(1, min(100, int(limit or 25)))
        room_ids = list(reversed(self._memory_history.get(user_id, [])))[:normalized_limit]
        results: list[dict[str, Any]] = []
        for room_id in room_ids:
            result = await self.get_result(room_id=str(room_id), user_id=user_id)
            if result is not None:
                results.append(result)
        return results

    def _public_result(self, result: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": result.get("id", ""),
            "room_id": result.get("room_id", ""),
            "mode": result.get("mode", "goldfish"),
            "game_type": result.get("game_type", "goldfish"),
            "outcome": result.get("outcome", "completed"),
            "score": int(result.get("score") or 0),
            "turns": int(result.get("turns") or 0),
            "duration_seconds": int(result.get("duration_seconds") or 0),
            "summary": result.get("summary", ""),
            "created_at": result.get("created_at", ""),
        }


class GameWorker:
    def __init__(self, service: GameRoomService, *, stream_key: str = COMMAND_STREAM_KEY) -> None:
        self.service = service
        self.stream_key = stream_key
        self._task: Optional[asyncio.Task] = None
        self._stopped = asyncio.Event()

    def start(self) -> None:
        self._stopped.clear()

    async def stop(self) -> None:
        self._stopped.set()
