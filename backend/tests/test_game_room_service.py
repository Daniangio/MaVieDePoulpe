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


def test_draw_requires_discard_when_hand_limit_is_reached():
    async def scenario():
        service, user, room, _start = await create_started_room()
        await prepare_active_capability_with_ap(service, user, room)
        capability = service._memory_states[room["id"]]["capabilities"][DEFAULT_ACTIVE_CAPABILITY_ID]
        capability["current_max_cards_in_hand"] = 2
        capability["hand"] = [
            {"card_id": "card_keep", "interaction_id": "charge", "owner_capability_id": DEFAULT_ACTIVE_CAPABILITY_ID},
            {"card_id": "card_discard", "interaction_id": "tighten", "owner_capability_id": DEFAULT_ACTIVE_CAPABILITY_ID},
        ]
        capability["draw_pile"] = [
            {"card_id": "card_drawn", "interaction_id": "hide", "owner_capability_id": DEFAULT_ACTIVE_CAPABILITY_ID}
        ]
        capability["discard"] = []

        rejected = await send_command(
            service,
            user,
            room,
            command_id="cmd_draw_without_discard",
            expected_version=3,
            command_type="draw_action_card",
            payload={"capability_id": DEFAULT_ACTIVE_CAPABILITY_ID},
        )
        accepted = await send_command(
            service,
            user,
            room,
            command_id="cmd_draw_with_discard",
            expected_version=3,
            command_type="draw_action_card",
            payload={"capability_id": DEFAULT_ACTIVE_CAPABILITY_ID, "discard_card_id": "card_discard"},
        )

        next_capability = accepted["projection"]["capabilities"][DEFAULT_ACTIVE_CAPABILITY_ID]
        assert rejected["ok"] is False
        assert rejected["reason"] == "discard_required"
        assert accepted["ok"] is True
        assert accepted["version"] == 4
        assert [card["card_id"] for card in next_capability["hand"]] == ["card_keep", "card_drawn"]
        assert next_capability["discard"] == []
        assert [card["card_id"] for card in next_capability["draw_pile"]] == ["card_discard"]

    run(scenario())


def test_draw_refills_empty_deck_from_discard(monkeypatch):
    async def scenario():
        service, user, room, _start = await create_started_room()
        await prepare_active_capability_with_ap(service, user, room)
        capability = service._memory_states[room["id"]]["capabilities"][DEFAULT_ACTIVE_CAPABILITY_ID]
        capability["current_max_cards_in_hand"] = 3
        capability["hand"] = []
        capability["draw_pile"] = []
        capability["discard"] = [
            {"card_id": "card_recycled_1", "interaction_id": "charge", "owner_capability_id": DEFAULT_ACTIVE_CAPABILITY_ID},
            {"card_id": "card_recycled_2", "interaction_id": "tighten", "owner_capability_id": DEFAULT_ACTIVE_CAPABILITY_ID},
        ]

        monkeypatch.setattr("backend.app.game_room_service.random.shuffle", lambda cards: None)

        result = await send_command(
            service,
            user,
            room,
            command_id="cmd_draw_recycled",
            expected_version=3,
            command_type="draw_action_card",
            payload={"capability_id": DEFAULT_ACTIVE_CAPABILITY_ID},
        )

        next_capability = result["projection"]["capabilities"][DEFAULT_ACTIVE_CAPABILITY_ID]
        assert result["ok"] is True
        assert [card["card_id"] for card in next_capability["hand"]] == ["card_recycled_1"]
        assert [card["card_id"] for card in next_capability["draw_pile"]] == ["card_recycled_2"]
        assert next_capability["discard"] == []

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


def test_failed_interaction_can_move_poulpita_and_tile_to_previous_node():
    async def scenario():
        service, user, room, _start = await create_started_room()
        state = service._memory_states[room["id"]]
        state["poulpita"]["node_id"] = "1B"
        state["poulpita"]["previous_node_id"] = "1A"
        state["tile_catalog"] = {
            "tiles": {
                "crab-tile": {
                    "id": "crab-tile",
                    "event_id": "crab",
                    "failure_effects": [
                        {"type": "pulpita_move_previous", "amount": None},
                        {"type": "move_tile_previous", "amount": None},
                    ],
                }
            },
            "events": {"crab": {"id": "crab", "category_id": "prey"}},
            "interactions": {},
        }
        state["tiles"] = {
            "1A": [],
            "1B": [{"instance_id": "tile_crab", "tile_id": "crab-tile", "face_up": True}],
        }
        state["interaction"] = {
            "tile_instance_id": "tile_crab",
            "tile_id": "crab-tile",
            "node_id": "1B",
            "played_cards": [],
        }

        result = await send_command(
            service,
            user,
            room,
            command_id="cmd_fail_previous",
            expected_version=1,
            command_type="fail_interaction",
        )

        projection = result["projection"]
        assert result["ok"] is True
        assert projection["poulpita"]["node_id"] == "1A"
        assert projection["poulpita"]["previous_node_id"] == "1B"
        assert projection["tiles"]["1B"] == []
        assert projection["tiles"]["1A"][0]["instance_id"] == "tile_crab"

    run(scenario())


def test_failed_interaction_free_move_requires_adjacent_target():
    async def scenario():
        service, user, room, _start = await create_started_room()
        state = service._memory_states[room["id"]]
        state["tile_catalog"] = {
            "tiles": {
                "crab-tile": {
                    "id": "crab-tile",
                    "event_id": "crab",
                    "failure_effects": [{"type": "pulpita_move_free", "amount": None}],
                }
            },
            "events": {"crab": {"id": "crab", "category_id": "prey"}},
            "interactions": {},
        }
        state["tiles"] = {"1A": [{"instance_id": "tile_crab", "tile_id": "crab-tile", "face_up": True}]}
        state["interaction"] = {
            "tile_instance_id": "tile_crab",
            "tile_id": "crab-tile",
            "node_id": "1A",
            "played_cards": [],
        }

        rejected = await send_command(
            service,
            user,
            room,
            command_id="cmd_fail_no_target",
            expected_version=1,
            command_type="fail_interaction",
        )
        accepted = await send_command(
            service,
            user,
            room,
            command_id="cmd_fail_free_move",
            expected_version=1,
            command_type="fail_interaction",
            payload={"target_node_id": "1B"},
        )

        assert rejected["ok"] is False
        assert rejected["reason"] == "free_move_target_required"
        assert accepted["ok"] is True
        assert accepted["projection"]["poulpita"]["node_id"] == "1B"
        assert accepted["projection"]["poulpita"]["previous_node_id"] == "1A"

    run(scenario())


def test_failed_interaction_removes_tiles_by_selected_category_on_node():
    async def scenario():
        service, user, room, _start = await create_started_room()
        state = service._memory_states[room["id"]]
        state["tile_catalog"] = {
            "tiles": {
                "crab-tile": {"id": "crab-tile", "event_id": "crab", "failure_effects": [{"type": "remove_preys", "amount": None, "category_id": "prey"}]},
                "fish-tile": {"id": "fish-tile", "event_id": "fish", "failure_effects": []},
                "rock-tile": {"id": "rock-tile", "event_id": "rock", "failure_effects": []},
            },
            "events": {
                "crab": {"id": "crab", "category_id": "prey"},
                "fish": {"id": "fish", "category_id": "prey"},
                "rock": {"id": "rock", "category_id": "exploration"},
            },
            "interactions": {},
        }
        state["tiles"] = {
            "1A": [
                {"instance_id": "tile_crab", "tile_id": "crab-tile", "face_up": True},
                {"instance_id": "tile_fish", "tile_id": "fish-tile", "face_up": True},
                {"instance_id": "tile_rock", "tile_id": "rock-tile", "face_up": True},
            ]
        }
        state["interaction"] = {
            "tile_instance_id": "tile_crab",
            "tile_id": "crab-tile",
            "node_id": "1A",
            "played_cards": [],
        }

        result = await send_command(
            service,
            user,
            room,
            command_id="cmd_fail_remove_preys",
            expected_version=1,
            command_type="fail_interaction",
        )

        assert result["ok"] is True
        assert [tile["instance_id"] for tile in result["projection"]["tiles"]["1A"]] == ["tile_rock"]

    run(scenario())
