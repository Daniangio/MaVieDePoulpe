import asyncio
import pytest

from backend.app.game_room_service import (
    DEFAULT_ACTIVE_CAPABILITY_ID,
    GameRoomService,
    ROOM_STATE_IN_GAME,
    ROOM_STATE_SETUP,
)
from backend.app.server_models import User

TEST_MAP = {
    "id": "test-map",
    "name": "Test map",
    "starting_node_id": "1A",
    "image_filename": None,
    "image_url": None,
    "image_width": None,
    "image_height": None,
    "nodes": {
        f"{row}{column}": {
            "id": f"{row}{column}",
            "tier": 1,
            "x": (column_index + 1) / 5,
            "y": row / 5,
        }
        for row in range(1, 5)
        for column_index, column in enumerate(["A", "B", "C", "D"])
    },
    "adjacency": {
        "1A": ["1B"],
        "1B": ["1A", "1C"],
        "1C": ["1B", "1D"],
        "1D": ["1C"],
        "2A": ["2B"],
        "2B": ["2A", "2C"],
        "2C": ["2B", "2D"],
        "2D": ["2C"],
        "3A": ["3B"],
        "3B": ["3A", "3C"],
        "3C": ["3B", "3D"],
        "3D": ["3C"],
        "4A": ["4B"],
        "4B": ["4A", "4C"],
        "4C": ["4B", "4D"],
        "4D": ["4C"],
    },
}

TEST_LEVEL = {
    "id": "test-level",
    "name": "Test level",
    "map_id": "test-map",
    "node_tile_counts": {node_id: 0 for node_id in TEST_MAP["nodes"]},
    "node_group_ids": {node_id: "main" for node_id in TEST_MAP["nodes"]},
    "groups": [{"id": "main", "name": "Main", "tile_counts": {}}],
}


@pytest.fixture(autouse=True)
def explicit_test_map(monkeypatch):
    def get_test_map(map_id=None):
        if map_id in (None, "", "test-map"):
            return TEST_MAP
        raise LookupError("Map not found.")

    monkeypatch.setattr("backend.app.game_room_service.get_map", get_test_map)
    monkeypatch.setattr("backend.app.game_room_service.get_level_config", lambda level_id=None: TEST_LEVEL)
    monkeypatch.setattr(
        "backend.app.game_room_service.get_game_content_catalog",
        lambda: {"tiles": {}, "events": {}, "interactions": {}},
    )
    monkeypatch.setattr("backend.app.game_room_service.random.randint", lambda _min, _max: 1)


def run(coro):
    return asyncio.run(coro)


async def create_started_room():
    service = GameRoomService()
    user = User(id="user_1", username="Player One")
    room = await service.create_room(user=user, game_type="goldfish")
    start = await service.enqueue_game_command(
        room_id=room["id"],
        user=user,
        command={
            "command_id": "cmd_start",
            "room_id": room["id"],
            "actor_user_id": user.id,
            "actor_seat_id": "goldfish",
            "expected_version": 0,
            "type": "start_goldfish_game",
            "payload": {},
        },
    )
    return service, user, room, start


async def send_command(service, user, room, *, command_id, expected_version, command_type, payload=None):
    return await service.enqueue_game_command(
        room_id=room["id"],
        user=user,
        command={
            "command_id": command_id,
            "room_id": room["id"],
            "actor_user_id": user.id,
            "actor_seat_id": "goldfish",
            "expected_version": expected_version,
            "type": command_type,
            "payload": payload or {},
        },
    )


async def prepare_active_capability_with_ap(service, user, room):
    control = await send_command(
        service,
        user,
        room,
        command_id="cmd_take_control",
        expected_version=1,
        command_type="take_control",
        payload={"capability_id": DEFAULT_ACTIVE_CAPABILITY_ID},
    )
    collect = await send_command(
        service,
        user,
        room,
        command_id="cmd_collect_ap",
        expected_version=2,
        command_type="collect_action_points",
        payload={"capability_id": DEFAULT_ACTIVE_CAPABILITY_ID},
    )
    return control, collect


def test_room_creation_returns_setup_state():
    async def scenario():
        service = GameRoomService()
        user = User(id="user_1", username="Player One")

        room = await service.create_room(user=user, game_type="goldfish")
        projection = await service.get_projection(room_id=room["id"], user=user)

        assert room["id"].startswith("room_")
        assert room["state"] == ROOM_STATE_SETUP
        assert projection["version"] == 0
        assert projection["phase"] == "setup"
        assert projection["selected_map_id"] == "test-map"
        assert len(projection["player_boards"]) == 5
        assert projection["player_boards"][0]["id"] == DEFAULT_ACTIVE_CAPABILITY_ID

    run(scenario())


def test_goldfish_join_seat_is_stable_for_owner():
    async def scenario():
        service = GameRoomService()
        user = User(id="user_1", username="Player One")

        room = await service.create_room(user=user, game_type="goldfish")
        joined = await service.join_room(room_id=room["id"], user=user)

        assert joined == {"room_id": room["id"], "seat_id": "goldfish"}

    run(scenario())


def test_start_goldfish_game_initializes_16_node_board():
    async def scenario():
        service, user, room, start = await create_started_room()
        projection = await service.get_projection(room_id=room["id"], user=user)
        public_room = await service.get_room(room_id=room["id"], user=user)

        assert start["ok"] is True
        assert start["version"] == 1
        assert public_room["state"] == ROOM_STATE_IN_GAME
        assert projection["phase"] == "night_idle"
        assert projection["active_capability_id"] is None
        assert projection["focused_capability_id"] == DEFAULT_ACTIVE_CAPABILITY_ID
        assert len(projection["capabilities"]) == 5
        assert len(projection["map"]["nodes"]) == 16
        assert projection["poulpita"]["node_id"] == "1A"
        assert projection["poulpita"]["previous_node_id"] is None

    run(scenario())


def test_adjacent_movement_is_accepted_and_increments_version():
    async def scenario():
        service, user, room, _start = await create_started_room()
        control, collect = await prepare_active_capability_with_ap(service, user, room)

        result = await send_command(
            service,
            user,
            room,
            command_id="cmd_move_1",
            expected_version=3,
            command_type="move_poulpita",
            payload={"capability_id": DEFAULT_ACTIVE_CAPABILITY_ID, "target_node_id": "1B"},
        )
        projection = await service.get_projection(room_id=room["id"], user=user)

        assert control["version"] == 2
        assert collect["version"] == 3
        assert result["ok"] is True
        assert result["version"] == 4
        assert projection["version"] == 4
        assert projection["poulpita"]["node_id"] == "1B"
        assert projection["poulpita"]["previous_node_id"] == "1A"
        assert projection["capabilities"][DEFAULT_ACTIVE_CAPABILITY_ID]["pa"] == 0
        assert projection["capabilities"][DEFAULT_ACTIVE_CAPABILITY_ID]["actions_taken_this_control"] == 2
        assert result["events"][0]["type"] == "poulpita_moved"

    run(scenario())


def test_non_adjacent_movement_is_structured_rejection_without_version_increment():
    async def scenario():
        service, user, room, _start = await create_started_room()
        await prepare_active_capability_with_ap(service, user, room)

        result = await send_command(
            service,
            user,
            room,
            command_id="cmd_bad_move",
            expected_version=3,
            command_type="move_poulpita",
            payload={"capability_id": DEFAULT_ACTIVE_CAPABILITY_ID, "target_node_id": "4D"},
        )
        projection = await service.get_projection(room_id=room["id"], user=user)

        assert result["ok"] is False
        assert result["reason"] == "non_adjacent_node"
        assert result["current_version"] == 3
        assert projection["version"] == 3
        assert projection["poulpita"]["node_id"] == "1A"

    run(scenario())


def test_state_version_conflict_is_structured_rejection():
    async def scenario():
        service, user, room, _start = await create_started_room()

        result = await service.enqueue_game_command(
            room_id=room["id"],
            user=user,
            command={
                "command_id": "cmd_conflict",
                "room_id": room["id"],
                "actor_user_id": user.id,
                "actor_seat_id": "goldfish",
                "expected_version": 0,
                "type": "move_poulpita",
                "payload": {
                    "capability_id": DEFAULT_ACTIVE_CAPABILITY_ID,
                    "target_node_id": "1B",
                },
            },
        )

        assert result["ok"] is False
        assert result["reason"] == "state_version_conflict"
        assert result["current_version"] == 1

    run(scenario())
