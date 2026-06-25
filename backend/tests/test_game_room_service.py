import asyncio
import pytest

from backend.app.game_room_service import (
    DEFAULT_ACTIVE_CAPABILITY_ID,
    GameWorker,
    GameRoomService,
    ROOM_STATE_IN_GAME,
    ROOM_STATE_SETUP,
    _apply_tile_visibility,
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


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.sorted_sets = {}
        self.streams = {}
        self.read_offsets = {}
        self.published = []

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value, ex=None, nx=False):
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    async def delete(self, key):
        self.values.pop(key, None)

    async def zadd(self, key, mapping):
        self.sorted_sets.setdefault(key, {}).update(mapping)

    async def zrevrange(self, key, start, end):
        values = sorted((self.sorted_sets.get(key) or {}).items(), key=lambda item: item[1], reverse=True)
        return [value for value, _score in values[start : end + 1]]

    async def xadd(self, key, fields):
        stream = self.streams.setdefault(key, [])
        entry_id = f"{len(stream) + 1}-0"
        stream.append((entry_id, dict(fields)))
        return entry_id

    async def xgroup_create(self, *args, **kwargs):
        return True

    async def xreadgroup(self, *, groupname, consumername, streams, count=1, block=0):
        stream_key = next(iter(streams.keys()))
        offset_key = (groupname, consumername, stream_key)
        start = self.read_offsets.get(offset_key, 0)
        entries = list(self.streams.get(stream_key, []))[start : start + count]
        self.read_offsets[offset_key] = start + len(entries)
        if entries:
            return [(stream_key, entries)]
        await asyncio.sleep(max(0, min(float(block or 0) / 1000, 0.01)))
        return []

    async def xack(self, *args, **kwargs):
        return 1

    async def publish(self, channel, payload):
        self.published.append((channel, payload))
        return 0


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


def test_tile_visibility_reveals_current_neighbors_and_step_two_limits():
    async def scenario():
        service, user, room, _start = await create_started_room()
        state = service._memory_states[room["id"]]
        state["tiles"] = {
            "1A": [
                {"instance_id": "current_1", "tile_id": "tile", "face_up": False},
                {"instance_id": "current_2", "tile_id": "tile", "face_up": False},
                {"instance_id": "current_3", "tile_id": "tile", "face_up": False},
            ],
            "1B": [
                {"instance_id": "neighbor_1", "tile_id": "tile", "face_up": False},
                {"instance_id": "neighbor_2", "tile_id": "tile", "face_up": False},
                {"instance_id": "neighbor_3", "tile_id": "tile", "face_up": False},
            ],
            "1C": [
                {"instance_id": "step2_1", "tile_id": "tile", "face_up": False},
                {"instance_id": "step2_2", "tile_id": "tile", "face_up": False},
                {"instance_id": "step2_3", "tile_id": "tile", "face_up": False},
            ],
            "1D": [
                {"instance_id": "step3_1", "tile_id": "tile", "face_up": False},
            ],
        }
        _apply_tile_visibility(state)

        projection = await service.get_projection(room_id=room["id"], user=user)

        assert [tile["face_up"] for tile in projection["tiles"]["1A"]] == [True, True, True]
        assert [tile.get("face_up") for tile in projection["tiles"]["1B"]] == [True, True, False]
        assert [tile.get("face_up") for tile in projection["tiles"]["1C"]] == [True, False, False]
        assert [tile.get("face_up") for tile in projection["tiles"]["1D"]] == [False]

    run(scenario())


def test_room_and_state_are_rehydrated_from_redis_after_service_restart():
    async def scenario():
        redis = FakeRedis()
        user = User(id="user_1", username="Player One")
        first_service = GameRoomService(redis_client=redis)
        room = await first_service.create_room(user=user, game_type="goldfish")

        restarted_service = GameRoomService(redis_client=redis)
        public_room = await restarted_service.get_room(room_id=room["id"], user=user)
        projection = await restarted_service.get_projection(room_id=room["id"], user=user)

        assert public_room["id"] == room["id"]
        assert public_room["state"] == ROOM_STATE_SETUP
        assert projection["room_id"] == room["id"]
        assert projection["version"] == 0
        assert projection["selected_level_id"] == "test-level"

    run(scenario())


def test_distributed_worker_processes_command_from_redis_stream(monkeypatch):
    async def scenario():
        monkeypatch.setenv("USE_DISTRIBUTED_GAME_RUNTIME", "true")
        monkeypatch.setenv("GAME_COMMAND_RESULT_TIMEOUT_SECONDS", "1.0")
        monkeypatch.setenv("GAME_COMMAND_RESULT_POLL_SECONDS", "0.01")
        redis = FakeRedis()
        user = User(id="user_1", username="Player One")
        gateway_service = GameRoomService(redis_client=redis)
        worker_service = GameRoomService(redis_client=redis)
        room = await gateway_service.create_room(user=user, game_type="goldfish")
        worker = GameWorker(worker_service, enabled=True)
        worker.start()
        try:
            result = await gateway_service.enqueue_game_command(
                room_id=room["id"],
                user=user,
                command={
                    "command_id": "cmd_start_distributed",
                    "room_id": room["id"],
                    "actor_user_id": user.id,
                    "actor_seat_id": "goldfish",
                    "expected_version": 0,
                    "type": "start_goldfish_game",
                    "payload": {},
                },
            )
        finally:
            await worker.stop()

        projection = await gateway_service.get_projection(room_id=room["id"], user=user)
        assert result["ok"] is True
        assert result["version"] == 1
        assert projection["phase"] == "night_idle"
        assert projection["version"] == 1

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


def test_compulsory_same_node_interactions_follow_highest_priority_first():
    async def scenario():
        service, user, room, _start = await create_started_room()
        state = service._memory_states[room["id"]]
        state["phase"] = "night_action"
        state["active_capability_id"] = DEFAULT_ACTIVE_CAPABILITY_ID
        state["capabilities"][DEFAULT_ACTIVE_CAPABILITY_ID]["initiates_event_ids"] = ["shark", "crab"]
        state["tile_catalog"] = {
            "categories": {
                "threat": {"id": "threat", "name": "Threat", "compulsory_on_same_node": True},
                "prey": {"id": "prey", "name": "Prey", "compulsory_on_same_node": False},
            },
            "tiles": {
                "shark-high": {"id": "shark-high", "event_id": "shark", "priority": 9, "interaction_ids": ["hide"]},
                "shark-low": {"id": "shark-low", "event_id": "shark", "priority": 4, "interaction_ids": ["hide"]},
                "crab-tile": {"id": "crab-tile", "event_id": "crab", "priority": 99, "interaction_ids": ["hide"]},
            },
            "events": {
                "shark": {"id": "shark", "category_id": "threat"},
                "crab": {"id": "crab", "category_id": "prey"},
            },
            "interactions": {},
        }
        state["tiles"] = {
            "1A": [
                {"instance_id": "tile_shark_low", "tile_id": "shark-low", "face_up": True},
                {"instance_id": "tile_shark_high", "tile_id": "shark-high", "face_up": True},
                {"instance_id": "tile_crab", "tile_id": "crab-tile", "face_up": True},
            ]
        }

        rejected_low = await send_command(
            service,
            user,
            room,
            command_id="cmd_start_low",
            expected_version=1,
            command_type="start_interaction",
            payload={"capability_id": DEFAULT_ACTIVE_CAPABILITY_ID, "tile_instance_id": "tile_shark_low"},
        )
        rejected_optional = await send_command(
            service,
            user,
            room,
            command_id="cmd_start_optional",
            expected_version=1,
            command_type="start_interaction",
            payload={"capability_id": DEFAULT_ACTIVE_CAPABILITY_ID, "tile_instance_id": "tile_crab"},
        )
        accepted_high = await send_command(
            service,
            user,
            room,
            command_id="cmd_start_high",
            expected_version=1,
            command_type="start_interaction",
            payload={"capability_id": DEFAULT_ACTIVE_CAPABILITY_ID, "tile_instance_id": "tile_shark_high"},
        )

        assert rejected_low["ok"] is False
        assert rejected_low["reason"] == "compulsory_interaction_first"
        assert rejected_optional["ok"] is False
        assert rejected_optional["reason"] == "compulsory_interaction_first"
        assert accepted_high["ok"] is True
        assert accepted_high["projection"]["interaction"]["tile_instance_id"] == "tile_shark_high"

    run(scenario())


def test_success_reward_places_shelter_and_enables_end_night_after_four_hours():
    async def scenario():
        service, user, room, _start = await create_started_room()
        state = service._memory_states[room["id"]]
        state["phase"] = "night_action"
        state["active_capability_id"] = DEFAULT_ACTIVE_CAPABILITY_ID
        state["night_time_spent"] = 16
        state["tile_catalog"] = {
            "tiles": {
                "shelter-tile": {
                    "id": "shelter-tile",
                    "event_id": "crab",
                    "interaction_ids": ["charge"],
                    "success_effects": [{"type": "place_shelter_token", "amount": None}],
                    "counter_attack_effects": [],
                    "failure_effects": [],
                }
            },
            "events": {"crab": {"id": "crab", "category_id": "prey"}},
            "interactions": {},
        }
        state["tiles"] = {"1A": [{"instance_id": "tile_shelter", "tile_id": "shelter-tile", "face_up": True}]}
        state["interaction"] = {
            "tile_instance_id": "tile_shelter",
            "tile_id": "shelter-tile",
            "node_id": "1A",
            "played_cards": [{"card_id": "card_charge", "interaction_id": "charge", "capability_id": DEFAULT_ACTIVE_CAPABILITY_ID}],
        }

        resolved = await send_command(
            service,
            user,
            room,
            command_id="cmd_resolve_shelter",
            expected_version=1,
            command_type="resolve_interaction",
        )
        ended = await send_command(
            service,
            user,
            room,
            command_id="cmd_end_night",
            expected_version=2,
            command_type="end_night",
            payload={"capability_id": DEFAULT_ACTIVE_CAPABILITY_ID},
        )

        assert resolved["ok"] is True
        assert resolved["projection"]["shelters"]["1A"] == 1
        assert ended["ok"] is True
        assert ended["projection"]["phase"] == "day"

    run(scenario())


def test_twenty_fifth_ap_spend_can_lose_game_when_energy_reaches_zero():
    async def scenario():
        service, user, room, _start = await create_started_room()
        state = service._memory_states[room["id"]]
        state["phase"] = "night_action"
        state["active_capability_id"] = DEFAULT_ACTIVE_CAPABILITY_ID
        state["night_time_spent"] = 24
        state["poulpita"]["energy"] = 1
        capability = state["capabilities"][DEFAULT_ACTIVE_CAPABILITY_ID]
        capability["pa"] = 1
        capability["actions_taken_this_control"] = 0

        result = await send_command(
            service,
            user,
            room,
            command_id="cmd_overtime_move",
            expected_version=1,
            command_type="move_poulpita",
            payload={"capability_id": DEFAULT_ACTIVE_CAPABILITY_ID, "target_node_id": "1B"},
        )
        game_result = await service.get_result(room_id=room["id"], user_id=user.id)

        assert result["ok"] is True
        assert result["projection"]["night_time_spent"] == 25
        assert result["projection"]["poulpita"]["energy"] == 0
        assert result["projection"]["phase"] == "game_over"
        assert game_result["outcome"] == "lost"

    run(scenario())
