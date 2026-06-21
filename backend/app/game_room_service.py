from __future__ import annotations

import asyncio
import json
import time
import uuid
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import WebSocket

from .map_service import DEFAULT_MAP_ID, get_map
from .server_models import User


ROOM_STATE_SETUP = "SETUP"
ROOM_STATE_IN_GAME = "IN_GAME"
ROOM_STATE_FINISHED = "FINISHED"
COMMAND_STREAM_KEY = "game:commands"
PHASE_SETUP = "setup"
PHASE_NIGHT_IDLE = "night_idle"
PHASE_NIGHT_ACTION = "night_action"
PHASE_FINISHED = "game_over"
DEFAULT_FOCUSED_CAPABILITY_ID = "agility"
DEFAULT_ACTIVE_CAPABILITY_ID = DEFAULT_FOCUSED_CAPABILITY_ID
CAPABILITY_ORDER = ["agility", "camouflage", "force", "propulsion", "intelligence"]
CAPABILITY_NAMES = {
    "agility": "Agilite",
    "camouflage": "Camouflage",
    "force": "Force",
    "propulsion": "Propulsion",
    "intelligence": "Intelligence",
}


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
        "map_id": room.get("map_id") or DEFAULT_MAP_ID,
    }


def _validate_map_config(config: dict[str, Any]) -> None:
    nodes = config.get("nodes") or {}
    starting_node_id = str(config.get("starting_node_id") or "")
    if starting_node_id not in nodes:
        raise ValueError("Map starting_node_id must reference an existing node.")
    adjacency = config.get("adjacency") or {}
    for node_id, node in nodes.items():
        tier = int(node.get("tier") or 0)
        if tier < 1:
            raise ValueError(f"Map node {node_id} has an invalid tier.")
        for adjacent_id in adjacency.get(node_id) or []:
            if adjacent_id not in nodes:
                raise ValueError(f"Map node {node_id} references unknown adjacent node {adjacent_id}.")
            if node_id not in (adjacency.get(adjacent_id) or []):
                raise ValueError(f"Map adjacency must be symmetric between {node_id} and {adjacent_id}.")


def _map_projection(map_config: dict[str, Any]) -> dict[str, Any]:
    nodes = {}
    adjacency = {}
    for node_id, node in map_config["nodes"].items():
        nodes[node_id] = {
            "id": node_id,
            "tier": int(node["tier"]),
            "x": float(node.get("x") or 0),
            "y": float(node.get("y") or 0),
        }
        adjacency[node_id] = list((map_config.get("adjacency") or {}).get(node_id) or [])
    return {
        "id": map_config["id"],
        "name": map_config["name"],
        "nodes": nodes,
        "adjacency": adjacency,
        "image_url": map_config.get("image_url"),
        "image_width": map_config.get("image_width"),
        "image_height": map_config.get("image_height"),
    }


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


def _setup_state(room_id: str, *, map_id: str | None = None) -> dict[str, Any]:
    map_config = get_map(map_id)
    _validate_map_config(map_config)
    return {
        "room_id": room_id,
        "mode": "goldfish",
        "version": 0,
        "phase": PHASE_SETUP,
        "level_id": "goldfish_movement",
        "day_index": 1,
        "night_time_spent": 0,
        "selected_map_id": map_config["id"],
        "active_capability_id": None,
        "last_active_capability_id": None,
        "focused_capability_id": DEFAULT_FOCUSED_CAPABILITY_ID,
        "map": _map_projection(map_config),
        "poulpita": {"node_id": None, "previous_node_id": None},
        "capabilities": _initial_capabilities(),
        "event_log": [],
    }


def _initial_capabilities() -> dict[str, dict[str, Any]]:
    return {
        capability_id: {
            "id": capability_id,
            "name": CAPABILITY_NAMES[capability_id],
            "pa": 0,
            "control_takes_this_night": 0,
            "actions_taken_this_control": 0,
            "max_actions_per_control": 3,
            "max_control_takes_per_night": 3,
        }
        for capability_id in CAPABILITY_ORDER
    }


def _goldfish_state(room_id: str, *, map_id: str | None = None) -> dict[str, Any]:
    map_config = get_map(map_id)
    _validate_map_config(map_config)
    return {
        "room_id": room_id,
        "mode": "goldfish",
        "version": 1,
        "phase": PHASE_NIGHT_IDLE,
        "level_id": "goldfish_movement",
        "day_index": 1,
        "night_time_spent": 0,
        "selected_map_id": map_config["id"],
        "active_capability_id": None,
        "last_active_capability_id": None,
        "focused_capability_id": DEFAULT_FOCUSED_CAPABILITY_ID,
        "map": _map_projection(map_config),
        "poulpita": {
            "node_id": str(map_config["starting_node_id"]),
            "previous_node_id": None,
        },
        "capabilities": _initial_capabilities(),
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
    capabilities = deepcopy(state.get("capabilities") or {})
    capability_order = list(CAPABILITY_ORDER)
    player_boards = [capabilities[capability_id] for capability_id in capability_order if capability_id in capabilities]
    return {
        "room_id": state["room_id"],
        "projection_mode": "goldfish",
        "privacy_enforced": False,
        "mode": state["mode"],
        "version": int(state["version"]),
        "phase": state["phase"],
        "level_id": state["level_id"],
        "day_index": int(state.get("day_index") or 1),
        "night_time_spent": int(state.get("night_time_spent") or 0),
        "selected_map_id": state.get("selected_map_id") or DEFAULT_MAP_ID,
        "active_capability_id": state.get("active_capability_id"),
        "last_active_capability_id": state.get("last_active_capability_id"),
        "focused_capability_id": state.get("focused_capability_id") or DEFAULT_FOCUSED_CAPABILITY_ID,
        "capability_order": capability_order,
        "capabilities": capabilities,
        "players": [
            {
                "id": capability_id,
                "seat_id": capability_id,
                "display_name": capabilities.get(capability_id, {}).get("name", CAPABILITY_NAMES.get(capability_id, capability_id)),
            }
            for capability_id in capability_order
            if capability_id in capabilities
        ],
        "player_boards": player_boards,
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

    async def create_room(self, *, user: User, game_type: str = "goldfish", map_id: str | None = None) -> dict[str, Any]:
        normalized_game_type = str(game_type or "goldfish").strip() or "goldfish"
        selected_map = get_map(map_id)
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
            "map_id": selected_map["id"],
        }
        self._memory_rooms[room_id] = room
        self._memory_states[room_id] = _setup_state(room_id, map_id=selected_map["id"])
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
                next_state, events = self._reduce(state, command, user=user, room_id=room_id, room=room)
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
        room: dict[str, Any],
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
            next_state = _goldfish_state(room_id, map_id=room.get("map_id") or state.get("selected_map_id"))
            event = next_state["event_log"][0]
            return next_state, [event]

        if command_type == "select_map":
            if state["phase"] != PHASE_SETUP:
                self._reject(state, command_id, "game_already_started", "Map can be changed only before the game starts.")
            payload = command.get("payload") or {}
            if not isinstance(payload, dict):
                self._reject(state, command_id, "invalid_payload", "Command payload must be an object.")
            map_id = str(payload.get("map_id") or "")
            try:
                map_config = get_map(map_id)
                _validate_map_config(map_config)
            except (LookupError, ValueError):
                self._reject(state, command_id, "unknown_map", "Selected map does not exist or is invalid.")
            next_state = deepcopy(state)
            next_state["version"] = int(state["version"]) + 1
            next_state["selected_map_id"] = map_config["id"]
            next_state["map"] = _map_projection(map_config)
            room["map_id"] = map_config["id"]
            event = {
                "event_id": f"evt_{uuid.uuid4().hex}",
                "type": "map_selected",
                "command_id": command_id,
                "map_id": map_config["id"],
                "version": int(next_state["version"]),
                "created_at": _now_iso(),
            }
            next_state.setdefault("event_log", []).append(event)
            return next_state, [event]

        if command_type == "move_poulpita":
            if state["phase"] != PHASE_NIGHT_ACTION:
                self._reject(state, command_id, "phase_not_movable", "Take control before moving Poulpita.")
            payload = command.get("payload") or {}
            if not isinstance(payload, dict):
                self._reject(state, command_id, "invalid_payload", "Command payload must be an object.")
            capability_id = str(payload.get("capability_id") or "")
            target_node_id = str(payload.get("target_node_id") or "")
            if capability_id != state.get("active_capability_id"):
                self._reject(state, command_id, "not_active_capability", "Only the active capability can move Poulpita.")
            capability = (state.get("capabilities") or {}).get(capability_id)
            if capability is None:
                self._reject(state, command_id, "unknown_capability", "Unknown capability.")
            if int(capability.get("pa") or 0) < 1:
                self._reject(state, command_id, "insufficient_pa", "Moving costs 1 AP.")
            if int(capability.get("actions_taken_this_control") or 0) >= int(capability.get("max_actions_per_control") or 3):
                self._reject(state, command_id, "action_limit_reached", "This capability has already taken 3 actions during this control.")
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
            next_capability = next_state["capabilities"][capability_id]
            next_capability["pa"] = int(next_capability.get("pa") or 0) - 1
            next_capability["actions_taken_this_control"] = int(next_capability.get("actions_taken_this_control") or 0) + 1
            next_state["night_time_spent"] = int(next_state.get("night_time_spent") or 0) + 1
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

        if command_type == "take_control":
            if state["phase"] not in {PHASE_NIGHT_IDLE, PHASE_NIGHT_ACTION}:
                self._reject(state, command_id, "phase_not_controllable", "Control can be taken only during the night.")
            payload = command.get("payload") or {}
            if not isinstance(payload, dict):
                self._reject(state, command_id, "invalid_payload", "Command payload must be an object.")
            capability_id = str(payload.get("capability_id") or "")
            capabilities = state.get("capabilities") or {}
            capability = capabilities.get(capability_id)
            if capability is None:
                self._reject(state, command_id, "unknown_capability", "Unknown capability.")
            if capability_id == state.get("active_capability_id"):
                self._reject(state, command_id, "already_active_capability", "This capability already controls Poulpita.")
            if int(capability.get("control_takes_this_night") or 0) >= int(capability.get("max_control_takes_per_night") or 3):
                self._reject(state, command_id, "control_limit_reached", "This capability has already taken control 3 times tonight.")
            next_state = deepcopy(state)
            previous_active = next_state.get("active_capability_id")
            if previous_active:
                next_state["last_active_capability_id"] = previous_active
            next_state["active_capability_id"] = capability_id
            next_state["focused_capability_id"] = capability_id
            next_state["phase"] = PHASE_NIGHT_ACTION
            next_state["version"] = int(state["version"]) + 1
            next_capability = next_state["capabilities"][capability_id]
            next_capability["control_takes_this_night"] = int(next_capability.get("control_takes_this_night") or 0) + 1
            next_capability["actions_taken_this_control"] = 0
            event = {
                "event_id": f"evt_{uuid.uuid4().hex}",
                "type": "control_taken",
                "command_id": command_id,
                "capability_id": capability_id,
                "previous_active_capability_id": previous_active,
                "version": int(next_state["version"]),
                "created_at": _now_iso(),
            }
            next_state.setdefault("event_log", []).append(event)
            return next_state, [event]

        if command_type == "collect_action_points":
            if state["phase"] != PHASE_NIGHT_ACTION:
                self._reject(state, command_id, "phase_not_actionable", "Take control before collecting AP.")
            payload = command.get("payload") or {}
            if not isinstance(payload, dict):
                self._reject(state, command_id, "invalid_payload", "Command payload must be an object.")
            capability_id = str(payload.get("capability_id") or "")
            if capability_id != state.get("active_capability_id"):
                self._reject(state, command_id, "not_active_capability", "Only the active capability can collect AP.")
            capability = (state.get("capabilities") or {}).get(capability_id)
            if capability is None:
                self._reject(state, command_id, "unknown_capability", "Unknown capability.")
            if int(capability.get("actions_taken_this_control") or 0) >= int(capability.get("max_actions_per_control") or 3):
                self._reject(state, command_id, "action_limit_reached", "This capability has already taken 3 actions during this control.")
            amount = 1
            next_state = deepcopy(state)
            next_state["version"] = int(state["version"]) + 1
            next_capability = next_state["capabilities"][capability_id]
            next_capability["pa"] = int(next_capability.get("pa") or 0) + amount
            next_capability["actions_taken_this_control"] = int(next_capability.get("actions_taken_this_control") or 0) + 1
            event = {
                "event_id": f"evt_{uuid.uuid4().hex}",
                "type": "action_points_collected",
                "command_id": command_id,
                "capability_id": capability_id,
                "amount": amount,
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
        state = self._memory_states.get(room_id) or _setup_state(room_id, map_id=room.get("map_id"))
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
