import asyncio
import pytest

from backend.app.game_room_service import (
    DEFAULT_ACTIVE_CAPABILITY_ID,
    GameWorker,
    GameRoomService,
    ROOM_STATE_IN_GAME,
    ROOM_STATE_SETUP,
    _apply_tile_visibility,
    _goldfish_state,
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
    "starting_energy": 3,
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


def test_solo_with_bots_assigns_one_human_three_bots_and_shared_intelligence():
    async def scenario():
        service = GameRoomService()
        user = User(id="user_1", username="Player One")

        room = await service.create_room(user=user, mode="solo_with_bots", game_type="goldfish", human_ability_id="force")
        setup_projection = await service.get_projection(room_id=room["id"], user=user)
        start = await service.enqueue_game_command(
            room_id=room["id"],
            user=user,
            command={
                "command_id": "cmd_start_bots",
                "room_id": room["id"],
                "actor_user_id": user.id,
                "actor_seat_id": "goldfish",
                "expected_version": 0,
                "type": "start_goldfish_game",
                "payload": {},
            },
        )

        projection = start["projection"]
        assert room["mode"] == "solo_with_bots"
        assert setup_projection["mode"] == "solo_with_bots"
        assert setup_projection["bot_config"]["human_ability_id"] == "force"
        assert projection["mode"] == "solo_with_bots"
        assert projection["focused_capability_id"] == "force"
        assert projection["capabilities"]["force"]["controller_type"] == "human"
        assert projection["capabilities"]["intelligence"]["controller_type"] == "shared"
        assert {
            capability_id
            for capability_id, capability in projection["capabilities"].items()
            if capability.get("controller_type") == "bot"
        } == {"agility", "camouflage", "propulsion"}

    run(scenario())


def test_solo_with_bots_rejects_intelligence_as_human_seat():
    async def scenario():
        service = GameRoomService()
        user = User(id="user_1", username="Player One")

        with pytest.raises(ValueError):
            await service.create_room(user=user, mode="solo_with_bots", game_type="goldfish", human_ability_id="intelligence")

    run(scenario())


def test_solo_with_bots_generates_public_bot_plan_proposals():
    async def scenario():
        service = GameRoomService()
        user = User(id="user_1", username="Player One")

        room = await service.create_room(user=user, mode="solo_with_bots", game_type="goldfish", human_ability_id="force")
        await service.enqueue_game_command(
            room_id=room["id"],
            user=user,
            command={
                "command_id": "cmd_start_bot_plans",
                "room_id": room["id"],
                "actor_user_id": user.id,
                "actor_seat_id": "goldfish",
                "expected_version": 0,
                "type": "start_goldfish_game",
                "payload": {},
            },
        )

        plans = await service.get_bot_plans(room_id=room["id"], user=user)

        assert plans["status"] == "awaiting_selection"
        assert plans["generated_from_version"] == 1
        assert 1 <= len(plans["proposals"]) <= 5
        assert all("_score" not in proposal for proposal in plans["proposals"])
        assert all(proposal["proposer_ability_id"] in {"agility", "camouflage", "propulsion"} for proposal in plans["proposals"])
        assert all("step_preview" in proposal for proposal in plans["proposals"])

    run(scenario())


def test_bot_plans_do_not_suggest_moving_before_current_compulsory_tile():
    async def scenario():
        service = GameRoomService()
        user = User(id="user_1", username="Player One")
        room = await service.create_room(user=user, mode="solo_with_bots", game_type="goldfish", human_ability_id="force")
        await service.enqueue_game_command(
            room_id=room["id"],
            user=user,
            command={
                "command_id": "cmd_start_forced_plan",
                "room_id": room["id"],
                "actor_user_id": user.id,
                "actor_seat_id": "goldfish",
                "expected_version": 0,
                "type": "start_goldfish_game",
                "payload": {},
            },
        )
        state = service._memory_states[room["id"]]
        state["phase"] = "night_action"
        state["active_capability_id"] = "agility"
        state["capabilities"]["agility"]["pa"] = 2
        state["capabilities"]["agility"]["initiates_event_ids"] = ["shark"]
        state["tile_catalog"] = {
            "categories": {"threat": {"id": "threat", "name": "Threat", "compulsory_on_same_node": True}},
            "events": {"shark": {"id": "shark", "name": "Shark", "category_id": "threat"}},
            "tiles": {"shark-tile": {"id": "shark-tile", "event_id": "shark", "priority": 9, "interaction_ids": []}},
            "interactions": {},
        }
        state["tiles"] = {"1A": [{"instance_id": "tile_shark", "tile_id": "shark-tile", "face_up": True}]}

        plans = await service.get_bot_plans(room_id=room["id"], user=user)
        plan_ids = [plan["plan_id"] for plan in plans["proposals"]]

        assert any(plan_id.startswith("forced_agility_tile_shark") for plan_id in plan_ids)
        assert not any(plan_id.startswith("move_inspect_") for plan_id in plan_ids)
        assert plans["proposals"][0]["risk_label"] == "forced"

    run(scenario())


def test_execute_bot_plan_runs_only_next_command_through_reducer():
    async def scenario():
        service = GameRoomService()
        user = User(id="user_1", username="Player One")
        room = await service.create_room(user=user, mode="solo_with_bots", game_type="goldfish", human_ability_id="force")
        await service.enqueue_game_command(
            room_id=room["id"],
            user=user,
            command={
                "command_id": "cmd_start_execute_plan",
                "room_id": room["id"],
                "actor_user_id": user.id,
                "actor_seat_id": "goldfish",
                "expected_version": 0,
                "type": "start_goldfish_game",
                "payload": {},
            },
        )

        result = await service.execute_bot_plan(room_id=room["id"], user=user, plan_id="take_control_collect_agility")

        assert result["ok"] is True
        assert result["status"] == "replan_required"
        assert [entry["type"] for entry in result["command_results"]] == ["take_control"]
        assert result["projection"]["active_capability_id"] == "agility"
        assert result["projection"]["version"] == 2
        assert result["projection"]["capabilities"]["agility"]["pa"] == 0

    run(scenario())


def test_bot_collect_plan_uses_configured_expected_ap_roll():
    async def scenario():
        service = GameRoomService()
        user = User(id="user_1", username="Player One")
        room = await service.create_room(user=user, mode="solo_with_bots", game_type="goldfish", human_ability_id="force")
        await service.enqueue_game_command(
            room_id=room["id"],
            user=user,
            command={
                "command_id": "cmd_start_expected_roll_plan",
                "room_id": room["id"],
                "actor_user_id": user.id,
                "actor_seat_id": "goldfish",
                "expected_version": 0,
                "type": "start_goldfish_game",
                "payload": {},
            },
        )
        state = service._memory_states[room["id"]]
        state["tile_catalog"]["bot_settings"] = {"expected_ap_roll": 5}

        plans = await service.get_bot_plans(room_id=room["id"], user=user)
        collect_plan = next(plan for plan in plans["proposals"] if plan["plan_id"] == "take_control_collect_agility")

        assert collect_plan["statistics"]["expected_ap_roll"] == 5
        assert collect_plan["expected_resources"]["expected_ap_gain_by_ability"] == {"agility": 5}
        assert "average AP roll of 5" in collect_plan["rationale"]
        assert len(collect_plan["plan_chain"]) > 2

    run(scenario())


def test_bot_plans_offer_surprise_resolution_without_public_card_ids():
    async def scenario():
        service = GameRoomService()
        user = User(id="user_1", username="Player One")
        room = await service.create_room(user=user, mode="solo_with_bots", game_type="goldfish", human_ability_id="force")
        await service.enqueue_game_command(
            room_id=room["id"],
            user=user,
            command={
                "command_id": "cmd_start_surprise_plans",
                "room_id": room["id"],
                "actor_user_id": user.id,
                "actor_seat_id": "goldfish",
                "expected_version": 0,
                "type": "start_goldfish_game",
                "payload": {},
            },
        )
        state = service._memory_states[room["id"]]
        state["pending_surprise"] = {
            "card": {
                "id": "surprise-1",
                "name": "Spark",
                "costs": [{"type": "play_cards", "interaction_ids": ["hide"]}],
                "effects": [{"type": "gain_neurons", "amount": 2}],
            }
        }
        state["capabilities"]["camouflage"]["hand"] = [
            {"card_id": "secret_card_hide", "interaction_id": "hide", "interaction_ids": ["hide"], "owner_capability_id": "camouflage"}
        ]

        public_plans = await service.get_bot_plans(room_id=room["id"], user=user)
        executed = await service.execute_bot_plan(room_id=room["id"], user=user, plan_id="surprise_accept_camouflage")

        assert [plan["plan_id"] for plan in public_plans["proposals"]] == ["surprise_accept_camouflage", "surprise_skip"]
        assert all("commands" not in plan for plan in public_plans["proposals"])
        assert "secret_card_hide" not in str(public_plans)
        assert executed["ok"] is True
        assert executed["projection"]["pending_surprise"] is None
        assert executed["projection"]["poulpita"]["neurons"] == 2
        assert executed["projection"]["capabilities"]["camouflage"]["hand"] == []

    run(scenario())


def test_bot_plans_after_surprise_can_take_control_for_camouflage_forced_tile():
    async def scenario():
        service = GameRoomService()
        user = User(id="user_1", username="Player One")
        room = await service.create_room(user=user, mode="solo_with_bots", game_type="goldfish", human_ability_id="force")
        await service.enqueue_game_command(
            room_id=room["id"],
            user=user,
            command={
                "command_id": "cmd_start_camouflage_forced_plan",
                "room_id": room["id"],
                "actor_user_id": user.id,
                "actor_seat_id": "goldfish",
                "expected_version": 0,
                "type": "start_goldfish_game",
                "payload": {},
            },
        )
        state = service._memory_states[room["id"]]
        state["phase"] = "night_action"
        state["active_capability_id"] = "force"
        state["capabilities"]["camouflage"]["pa"] = 2
        state["capabilities"]["camouflage"]["initiates_event_ids"] = ["moray"]
        state["tile_catalog"] = {
            "categories": {"threat": {"id": "threat", "name": "Threat", "compulsory_on_same_node": True}},
            "events": {"moray": {"id": "moray", "name": "Moray", "category_id": "threat"}},
            "tiles": {"moray-tile": {"id": "moray-tile", "event_id": "moray", "priority": 10, "interaction_ids": []}},
            "interactions": {},
        }
        state["tiles"] = {"1A": [{"instance_id": "tile_moray", "tile_id": "moray-tile", "face_up": True}]}

        plans = await service.get_bot_plans(room_id=room["id"], user=user)
        plan_ids = [plan["plan_id"] for plan in plans["proposals"]]

        assert "take_control_forced_camouflage_tile_moray" in plan_ids
        assert not any(plan_id.startswith("move_inspect_") for plan_id in plan_ids)
        assert plans["proposals"][0]["risk_label"] == "forced"

    run(scenario())


def test_bot_plans_keep_current_active_plan_and_show_take_control_alternatives():
    async def scenario():
        service = GameRoomService()
        user = User(id="user_1", username="Player One")
        room = await service.create_room(user=user, mode="solo_with_bots", game_type="goldfish", human_ability_id="force")
        await service.enqueue_game_command(
            room_id=room["id"],
            user=user,
            command={
                "command_id": "cmd_start_active_team_plan",
                "room_id": room["id"],
                "actor_user_id": user.id,
                "actor_seat_id": "goldfish",
                "expected_version": 0,
                "type": "start_goldfish_game",
                "payload": {},
            },
        )
        state = service._memory_states[room["id"]]
        state["phase"] = "night_action"
        state["active_capability_id"] = "force"
        state["capabilities"]["force"]["pa"] = 2
        state["capabilities"]["force"]["actions_taken_this_control"] = 0

        plans = await service.get_bot_plans(room_id=room["id"], user=user)
        plan_ids = [plan["plan_id"] for plan in plans["proposals"]]

        assert plans["status"] == "awaiting_selection"
        assert "collect_force" in plan_ids
        assert any(plan_id.startswith("take_control_collect_") for plan_id in plan_ids)
        active_plan = next(plan for plan in plans["proposals"] if plan["plan_id"] == "collect_force")
        alternative_plan = next(plan for plan in plans["proposals"] if plan["plan_id"].startswith("take_control_collect_"))
        assert active_plan["statistics"]["efficiency"] >= alternative_plan["statistics"]["efficiency"]

    run(scenario())


def test_forced_current_tile_reports_manual_blocker_instead_of_empty_plans():
    async def scenario():
        service = GameRoomService()
        user = User(id="user_1", username="Player One")
        room = await service.create_room(user=user, mode="solo_with_bots", game_type="goldfish", human_ability_id="force")
        await service.enqueue_game_command(
            room_id=room["id"],
            user=user,
            command={
                "command_id": "cmd_start_blocked_forced_plan",
                "room_id": room["id"],
                "actor_user_id": user.id,
                "actor_seat_id": "goldfish",
                "expected_version": 0,
                "type": "start_goldfish_game",
                "payload": {},
            },
        )
        state = service._memory_states[room["id"]]
        state["phase"] = "night_action"
        state["active_capability_id"] = "force"
        state["capabilities"]["force"]["initiates_event_ids"] = []
        for capability in state["capabilities"].values():
            capability["initiates_event_ids"] = []
            capability["control_takes_this_night"] = capability["max_control_takes_per_night"]
        state["tile_catalog"] = {
            "categories": {"threat": {"id": "threat", "name": "Threat", "compulsory_on_same_node": True}},
            "events": {"moray": {"id": "moray", "name": "Moray", "category_id": "threat"}},
            "tiles": {"moray-tile": {"id": "moray-tile", "event_id": "moray", "priority": 10, "interaction_ids": []}},
            "interactions": {},
        }
        state["tiles"] = {"1A": [{"instance_id": "tile_moray", "tile_id": "moray-tile", "face_up": True}]}

        plans = await service.get_bot_plans(room_id=room["id"], user=user)

        assert plans["status"] == "awaiting_selection"
        assert plans["proposals"][0]["plan_id"] == "forced_tile_needs_manual_resolution"
        assert plans["proposals"][0]["risk_label"] == "forced"

    run(scenario())


def test_bot_plans_support_open_interaction_with_public_statistics():
    async def scenario():
        service = GameRoomService()
        user = User(id="user_1", username="Player One")
        room = await service.create_room(user=user, mode="solo_with_bots", game_type="goldfish", human_ability_id="force")
        await service.enqueue_game_command(
            room_id=room["id"],
            user=user,
            command={
                "command_id": "cmd_start_open_support_plan",
                "room_id": room["id"],
                "actor_user_id": user.id,
                "actor_seat_id": "goldfish",
                "expected_version": 0,
                "type": "start_goldfish_game",
                "payload": {},
            },
        )
        state = service._memory_states[room["id"]]
        state["phase"] = "night_action"
        state["active_capability_id"] = "force"
        state["tile_catalog"] = {
            "categories": {"threat": {"id": "threat", "name": "Threat", "compulsory_on_same_node": True}},
            "events": {"moray": {"id": "moray", "name": "Moray", "category_id": "threat"}},
            "tiles": {"moray-tile": {"id": "moray-tile", "event_id": "moray", "priority": 10, "interaction_ids": ["hide"]}},
            "interactions": {"hide": {"id": "hide", "name": "Hide"}},
        }
        state["interaction"] = {
            "tile_instance_id": "tile_moray",
            "tile_id": "moray-tile",
            "node_id": "1A",
            "initiator_capability_id": "force",
            "played_cards": [],
        }
        state["capabilities"]["camouflage"]["hand"] = [
            {"card_id": "private_hide_card", "interaction_id": "hide", "interaction_ids": ["hide"], "owner_capability_id": "camouflage"}
        ]

        plans = await service.get_bot_plans(room_id=room["id"], user=user)
        proposal = next(plan for plan in plans["proposals"] if plan["plan_id"] == "support_interaction_camouflage_tile_moray")

        assert "commands" not in proposal
        assert "private_hide_card" not in str(plans)
        assert proposal["statistics"]["success_probability"] >= 0.9
        assert proposal["statistics"]["interaction_probabilities"][0]["tile_name"] == "Moray"
        assert proposal["plan_chain"]

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


def test_configured_move_action_costs_spend_ap_and_advance_time():
    async def scenario():
        service, user, room, _start = await create_started_room()
        await prepare_active_capability_with_ap(service, user, room)
        state = service._memory_states[room["id"]]
        state["capabilities"][DEFAULT_ACTIVE_CAPABILITY_ID]["pa"] = 3
        state["tile_catalog"]["action_costs"] = {"move": {"ap_cost": 2, "time_cost": 4}}

        result = await send_command(
            service,
            user,
            room,
            command_id="cmd_costed_move",
            expected_version=3,
            command_type="move_poulpita",
            payload={"capability_id": DEFAULT_ACTIVE_CAPABILITY_ID, "target_node_id": "1B"},
        )

        capability = result["projection"]["capabilities"][DEFAULT_ACTIVE_CAPABILITY_ID]
        assert result["ok"] is True
        assert capability["pa"] == 1
        assert result["projection"]["night_time_spent"] == 4

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


def test_successful_interaction_consumes_required_poulpita_shells():
    async def scenario():
        service, user, room, _start = await create_started_room()
        state = service._memory_states[room["id"]]
        state["poulpita"]["seashells"] = 3
        state["tile_catalog"] = {
            "tiles": {
                "shell-threat": {
                    "id": "shell-threat",
                    "event_id": "crab",
                    "interaction_ids": [],
                    "shell_requirement_count": 2,
                    "success_effects": [{"type": "gain_neurons", "amount": 1}],
                    "failure_effects": [],
                }
            },
            "events": {"crab": {"id": "crab", "category_id": "prey"}},
            "interactions": {},
        }
        state["tiles"] = {"1A": [{"instance_id": "tile_shell", "tile_id": "shell-threat", "face_up": True}]}
        state["interaction"] = {"tile_instance_id": "tile_shell", "tile_id": "shell-threat", "node_id": "1A", "played_cards": []}

        result = await send_command(
            service,
            user,
            room,
            command_id="cmd_shell_success",
            expected_version=1,
            command_type="resolve_interaction",
        )

        assert result["ok"] is True
        assert result["projection"]["poulpita"]["seashells"] == 1
        assert result["projection"]["poulpita"]["neurons"] == 1
        assert result["projection"]["tiles"]["1A"] == []

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
        state["capabilities"][DEFAULT_ACTIVE_CAPABILITY_ID]["pa"] = 3
        state["capabilities"][DEFAULT_ACTIVE_CAPABILITY_ID]["initiates_event_ids"] = ["shark", "crab"]
        state["tile_catalog"] = {
            "categories": {
                "threat": {"id": "threat", "name": "Threat", "compulsory_on_same_node": True},
                "prey": {"id": "prey", "name": "Prey", "compulsory_on_same_node": False},
            },
            "tiles": {
                "shark-high": {"id": "shark-high", "event_id": "shark", "priority": 9, "interaction_ids": ["hide"]},
                "shark-low": {"id": "shark-low", "event_id": "shark", "priority": 4, "interaction_ids": ["hide"]},
                "crab-tile": {"id": "crab-tile", "event_id": "crab", "priority": 3, "interaction_ids": ["hide"]},
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


def test_octopus_token_hydrates_tile_definition_and_enforces_initiators():
    async def scenario():
        service, user, room, _start = await create_started_room()
        state = service._memory_states[room["id"]]
        state["phase"] = "night_action"
        state["active_capability_id"] = "force"
        state["capabilities"]["force"]["pa"] = 1
        state["tile_catalog"] = {
            "categories": {},
            "tiles": {},
            "events": {},
            "interactions": {},
            "tokens": {
                "octopus": {
                    "id": "octopus",
                    "name": "Octopus token",
                    "image_url": "/api/admin/content/images/octopus.png",
                    "priority": 7,
                    "initiator_capability_ids": ["force"],
                    "interaction_ids": [],
                    "counter_attack_interaction_ids": [],
                    "success_effects": [],
                    "counter_attack_effects": [],
                    "failure_effects": [],
                }
            },
        }
        state["tiles"] = {
            "1A": [
                {
                    "instance_id": "octopus_1A",
                    "tile_id": "__octopus_token__",
                    "face_up": True,
                    "token_type": "octopus",
                }
            ]
        }

        accepted = await send_command(
            service,
            user,
            room,
            command_id="cmd_start_octopus_allowed",
            expected_version=1,
            command_type="start_interaction",
            payload={"capability_id": "force", "tile_instance_id": "octopus_1A"},
        )

        assert accepted["ok"] is True
        assert accepted["projection"]["interaction"]["tile_id"] == "__octopus_token__"
        assert accepted["projection"]["tile_catalog"]["tiles"]["__octopus_token__"]["image_url"].endswith("octopus.png")

        service, user, room, _start = await create_started_room()
        state = service._memory_states[room["id"]]
        state["phase"] = "night_action"
        state["active_capability_id"] = "agility"
        state["capabilities"]["agility"]["pa"] = 1
        state["tile_catalog"] = {
            "categories": {},
            "tiles": {},
            "events": {},
            "interactions": {},
            "tokens": {
                "octopus": {
                    "id": "octopus",
                    "name": "Octopus token",
                    "priority": 7,
                    "initiator_capability_ids": ["force"],
                    "interaction_ids": [],
                    "counter_attack_interaction_ids": [],
                    "success_effects": [],
                    "counter_attack_effects": [],
                    "failure_effects": [],
                }
            },
        }
        state["tiles"] = {"1A": [{"instance_id": "octopus_1A", "tile_id": "__octopus_token__", "face_up": True, "token_type": "octopus"}]}

        rejected = await send_command(
            service,
            user,
            room,
            command_id="cmd_start_octopus_rejected",
            expected_version=1,
            command_type="start_interaction",
            payload={"capability_id": "agility", "tile_instance_id": "octopus_1A"},
        )

        assert rejected["ok"] is False
        assert rejected["reason"] == "cannot_initiate_interaction"

    run(scenario())


def test_higher_priority_optional_interaction_can_precede_lower_compulsory_interaction():
    async def scenario():
        service, user, room, _start = await create_started_room()
        state = service._memory_states[room["id"]]
        state["phase"] = "night_action"
        state["active_capability_id"] = DEFAULT_ACTIVE_CAPABILITY_ID
        state["capabilities"][DEFAULT_ACTIVE_CAPABILITY_ID]["pa"] = 3
        state["capabilities"][DEFAULT_ACTIVE_CAPABILITY_ID]["initiates_event_ids"] = ["shark", "crab"]
        state["tile_catalog"] = {
            "categories": {
                "threat": {"id": "threat", "name": "Threat", "compulsory_on_same_node": True},
                "prey": {"id": "prey", "name": "Prey", "compulsory_on_same_node": False},
            },
            "tiles": {
                "shark-low": {"id": "shark-low", "event_id": "shark", "priority": 4, "interaction_ids": []},
                "crab-high": {"id": "crab-high", "event_id": "crab", "priority": 9, "interaction_ids": []},
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
                {"instance_id": "tile_crab_high", "tile_id": "crab-high", "face_up": True},
            ]
        }

        accepted_optional = await send_command(
            service,
            user,
            room,
            command_id="cmd_start_optional_high",
            expected_version=1,
            command_type="start_interaction",
            payload={"capability_id": DEFAULT_ACTIVE_CAPABILITY_ID, "tile_instance_id": "tile_crab_high"},
        )
        failed_optional = await send_command(
            service,
            user,
            room,
            command_id="cmd_fail_optional_high",
            expected_version=2,
            command_type="fail_interaction",
        )
        accepted_compulsory = await send_command(
            service,
            user,
            room,
            command_id="cmd_start_compulsory_low",
            expected_version=3,
            command_type="start_interaction",
            payload={"capability_id": DEFAULT_ACTIVE_CAPABILITY_ID, "tile_instance_id": "tile_shark_low"},
        )

        assert accepted_optional["ok"] is True
        assert accepted_optional["projection"]["interaction"]["tile_instance_id"] == "tile_crab_high"
        assert failed_optional["ok"] is True
        assert accepted_compulsory["ok"] is True
        assert accepted_compulsory["projection"]["interaction"]["tile_instance_id"] == "tile_shark_low"

    run(scenario())


def test_latest_tile_priority_metadata_allows_high_priority_optional_interaction(monkeypatch):
    async def scenario():
        service, user, room, _start = await create_started_room()
        state = service._memory_states[room["id"]]
        state["phase"] = "night_action"
        state["active_capability_id"] = DEFAULT_ACTIVE_CAPABILITY_ID
        state["capabilities"][DEFAULT_ACTIVE_CAPABILITY_ID]["pa"] = 1
        state["capabilities"][DEFAULT_ACTIVE_CAPABILITY_ID]["initiates_event_ids"] = ["shark", "surprise"]
        state["tile_catalog"] = {
            "categories": {
                "threat": {"id": "threat", "name": "Threat", "compulsory_on_same_node": True},
                "exploration": {"id": "exploration", "name": "Exploration", "compulsory_on_same_node": False},
            },
            "tiles": {
                "shark-low": {"id": "shark-low", "event_id": "shark", "priority": 4, "interaction_ids": []},
                "surprise-high": {"id": "surprise-high", "event_id": "surprise", "priority": 0, "interaction_ids": []},
            },
            "events": {
                "shark": {"id": "shark", "category_id": "threat"},
                "surprise": {"id": "surprise", "category_id": "exploration"},
            },
            "interactions": {},
        }
        state["tiles"] = {
            "1A": [
                {"instance_id": "tile_shark_low", "tile_id": "shark-low", "face_up": True},
                {"instance_id": "tile_surprise_high", "tile_id": "surprise-high", "face_up": True},
            ]
        }
        monkeypatch.setattr(
            "backend.app.game_room_service.get_game_content_catalog",
            lambda: {
                "categories": state["tile_catalog"]["categories"],
                "tiles": {
                    "shark-low": {"id": "shark-low", "event_id": "shark", "priority": 4, "interaction_ids": []},
                    "surprise-high": {"id": "surprise-high", "event_id": "surprise", "priority": 100, "interaction_ids": []},
                },
                "events": state["tile_catalog"]["events"],
                "interactions": {},
            },
        )

        accepted = await send_command(
            service,
            user,
            room,
            command_id="cmd_start_latest_optional_high",
            expected_version=1,
            command_type="start_interaction",
            payload={"capability_id": DEFAULT_ACTIVE_CAPABILITY_ID, "tile_instance_id": "tile_surprise_high"},
        )

        assert accepted["ok"] is True
        assert accepted["projection"]["interaction"]["tile_instance_id"] == "tile_surprise_high"

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
        assert resolved["projection"]["shelters"]["1A"]["count"] == 1
        assert ended["ok"] is True
        assert ended["projection"]["phase"] == "day"

    run(scenario())


def test_end_night_is_free_and_day_upgrades_stack_before_next_night():
    async def scenario():
        service, user, room, _start = await create_started_room()
        state = service._memory_states[room["id"]]
        state["phase"] = "night_action"
        state["active_capability_id"] = DEFAULT_ACTIVE_CAPABILITY_ID
        state["night_time_spent"] = 16
        state["shelters"] = {"1A": 1}
        state["poulpita"]["neurons"] = 3
        capability = state["capabilities"][DEFAULT_ACTIVE_CAPABILITY_ID]
        capability["pa"] = 0
        capability["control_takes_this_night"] = 2
        capability["actions_taken_this_control"] = int(capability["max_actions_per_control"])
        capability["current_max_cards_in_hand"] = 3
        capability["hand_size_upgrades"] = [
            {"cost_resource": "neurons", "cost": 2, "hand_size_bonus": 5},
            {"cost_resource": "neurons", "cost": 1, "hand_size_bonus": 1},
        ]
        capability["purchased_hand_size_upgrade_indices"] = []

        day = await send_command(
            service,
            user,
            room,
            command_id="cmd_free_end_night",
            expected_version=1,
            command_type="end_night",
            payload={"capability_id": DEFAULT_ACTIVE_CAPABILITY_ID},
        )
        bought = await send_command(
            service,
            user,
            room,
            command_id="cmd_buy_upgrade",
            expected_version=2,
            command_type="buy_hand_size_upgrade",
            payload={"capability_id": DEFAULT_ACTIVE_CAPABILITY_ID, "upgrade_index": 0},
        )
        duplicate = await send_command(
            service,
            user,
            room,
            command_id="cmd_buy_duplicate",
            expected_version=3,
            command_type="buy_hand_size_upgrade",
            payload={"capability_id": DEFAULT_ACTIVE_CAPABILITY_ID, "upgrade_index": 0},
        )
        night = await send_command(
            service,
            user,
            room,
            command_id="cmd_end_day",
            expected_version=3,
            command_type="end_day",
        )

        day_capability = day["projection"]["capabilities"][DEFAULT_ACTIVE_CAPABILITY_ID]
        bought_capability = bought["projection"]["capabilities"][DEFAULT_ACTIVE_CAPABILITY_ID]
        night_capability = night["projection"]["capabilities"][DEFAULT_ACTIVE_CAPABILITY_ID]
        assert day["ok"] is True
        assert day["projection"]["phase"] == "day"
        assert day["projection"]["night_time_spent"] == 0
        assert day_capability["pa"] == 0
        assert day_capability["control_takes_this_night"] == 0
        assert day_capability["actions_taken_this_control"] == 0
        assert bought["ok"] is True
        assert bought["projection"]["poulpita"]["neurons"] == 1
        assert bought_capability["current_max_cards_in_hand"] == 8
        assert bought_capability["purchased_hand_size_upgrade_indices"] == [0]
        assert duplicate["ok"] is False
        assert duplicate["reason"] == "upgrade_already_bought"
        assert night["ok"] is True
        assert night["projection"]["phase"] == "night_idle"
        assert night["projection"]["day_index"] == 2
        assert night_capability["current_max_cards_in_hand"] == 8
        assert night_capability["control_takes_this_night"] == 0

    run(scenario())


def test_day_can_buy_deck_exchange_upgrade():
    async def scenario():
        service, user, room, _start = await create_started_room()
        state = service._memory_states[room["id"]]
        state["phase"] = "day"
        state["poulpita"]["neurons"] = 3
        capability = state["capabilities"][DEFAULT_ACTIVE_CAPABILITY_ID]
        capability["hand_size_upgrades"] = [
            {
                "type": "deck_exchange",
                "cost_resource": "neurons",
                "cost": 2,
                "remove_cards": [{"interaction_id": "charge", "count": 1}],
                "add_cards": [{"interaction_ids": ["charge", "hide"], "count": 1}],
            }
        ]
        capability["purchased_hand_size_upgrade_indices"] = []
        capability["draw_pile"] = [{"card_id": "card_old", "interaction_id": "charge", "interaction_ids": ["charge"], "owner_capability_id": DEFAULT_ACTIVE_CAPABILITY_ID}]
        capability["hand"] = []
        capability["discard"] = []

        result = await send_command(
            service,
            user,
            room,
            command_id="cmd_buy_deck_exchange",
            expected_version=1,
            command_type="buy_hand_size_upgrade",
            payload={"capability_id": DEFAULT_ACTIVE_CAPABILITY_ID, "upgrade_index": 0},
        )

        next_capability = result["projection"]["capabilities"][DEFAULT_ACTIVE_CAPABILITY_ID]
        assert result["ok"] is True
        assert result["projection"]["poulpita"]["neurons"] == 1
        assert next_capability["purchased_hand_size_upgrade_indices"] == [0]
        assert len(next_capability["draw_pile"]) == 1
        assert next_capability["draw_pile"][0]["interaction_ids"] == ["charge", "hide"]
        assert next_capability["draw_pile"][0]["upgraded"] is True

    run(scenario())


def test_poulpita_size_can_increase_once_per_day_without_spending_to_zero():
    async def scenario():
        service, user, room, _start = await create_started_room()
        state = service._memory_states[room["id"]]
        state["phase"] = "day"
        state["poulpita"]["energy"] = 3
        state["poulpita"]["size_index"] = 0
        state["poulpita"]["size_upgraded_today"] = False
        state["tile_catalog"] = {
            "poulpita_panel": {
                "sizes": [
                    {"kg": 0.5, "energy_cost": 0},
                    {"kg": 1.0, "energy_cost": 3},
                    {"kg": 2.0, "energy_cost": 1},
                ]
            }
        }

        rejected_zero = await send_command(
            service,
            user,
            room,
            command_id="cmd_size_zero",
            expected_version=1,
            command_type="buy_poulpita_size",
        )
        state["poulpita"]["energy"] = 4
        accepted = await send_command(
            service,
            user,
            room,
            command_id="cmd_size_buy",
            expected_version=1,
            command_type="buy_poulpita_size",
        )
        duplicate = await send_command(
            service,
            user,
            room,
            command_id="cmd_size_duplicate",
            expected_version=2,
            command_type="buy_poulpita_size",
        )
        await send_command(
            service,
            user,
            room,
            command_id="cmd_size_end_day",
            expected_version=2,
            command_type="end_day",
        )
        next_state = service._memory_states[room["id"]]

        assert rejected_zero["ok"] is False
        assert rejected_zero["reason"] == "insufficient_energy"
        assert accepted["ok"] is True
        assert accepted["projection"]["poulpita"]["energy"] == 1
        assert accepted["projection"]["poulpita"]["size_index"] == 1
        assert accepted["projection"]["poulpita"]["size_upgraded_today"] is True
        assert duplicate["ok"] is False
        assert duplicate["reason"] == "size_already_upgraded_today"
        assert next_state["poulpita"]["size_upgraded_today"] is False

    run(scenario())


def test_goldfish_game_uses_level_starting_energy(monkeypatch):
    async def scenario():
        level = {**TEST_LEVEL, "starting_energy": 3, "starting_neurons": 5, "night_duration_steps": 18}
        monkeypatch.setattr("backend.app.game_room_service.get_level_config", lambda level_id=None: level)
        service, _user, _room, start = await create_started_room()

        assert start["projection"]["poulpita"]["energy"] == 3
        assert start["projection"]["poulpita"]["neurons"] == 5
        assert start["projection"]["night_time_total"] == 18
        assert service is not None

    run(scenario())


def test_goldfish_game_uses_level_starting_node_and_node_tokens(monkeypatch):
    level = {
        **TEST_LEVEL,
        "poulpita_starting_node_id": "1B",
        "node_tokens": {"1A": [{"type": "shelter"}], "1B": [{"type": "octopus"}]},
    }
    monkeypatch.setattr("backend.app.game_room_service.get_level_config", lambda level_id=None: level)
    monkeypatch.setattr(
        "backend.app.game_room_service.get_game_content_catalog",
        lambda: {
            "tiles": {},
            "events": {},
            "categories": {},
            "interactions": {"charge": {"id": "charge", "name": "Charge", "image_url": None}},
            "tokens": {
                "octopus": {
                    "id": "octopus",
                    "name": "Octopus token",
                    "image_url": "/api/content/images/octopus.png",
                    "priority": 12,
                    "interaction_ids": ["charge"],
                    "counter_attack_interaction_ids": [],
                    "success_effects": [{"type": "gain_neurons", "amount": 1}],
                    "counter_attack_effects": [],
                    "failure_effects": [{"type": "lose_energy", "amount": 1}],
                },
                "shelter": {"id": "shelter", "name": "Shelter token", "image_url": None},
            },
        },
    )

    state = _goldfish_state("room_tokens", level_id="test-level")
    octopus_instance = state["tiles"]["1B"][0]
    octopus_tile = state["tile_catalog"]["tiles"][octopus_instance["tile_id"]]

    assert state["poulpita"]["node_id"] == "1B"
    assert state["shelters"]["1A"]["count"] == 1
    assert octopus_instance["face_up"] is True
    assert octopus_tile["priority"] == 12
    assert octopus_tile["interaction_ids"] == ["charge"]
    assert state["tile_catalog"]["categories"]["__octopus_token_threat__"]["compulsory_on_same_node"] is True


def test_day_shell_transfer_secures_shelter_and_completes_objective():
    async def scenario():
        service, user, room, _start = await create_started_room()
        state = service._memory_states[room["id"]]
        state["phase"] = "day"
        state["poulpita"]["node_id"] = "1A"
        state["poulpita"]["seashells"] = 3
        state["shelters"] = {"1A": {"count": 1, "seashells": 0, "secure": False}}
        state["objectives"] = [{"id": "secure", "type": "secure_shelter"}]
        state["objective_progress"] = {"size_increases": 0, "found_shelter": True, "secured_shelter": False}

        first = await send_command(
            service,
            user,
            room,
            command_id="cmd_shell_1",
            expected_version=1,
            command_type="move_seashell_to_shelter",
        )
        second = await send_command(
            service,
            user,
            room,
            command_id="cmd_shell_2",
            expected_version=2,
            command_type="move_seashell_to_shelter",
        )
        third = await send_command(
            service,
            user,
            room,
            command_id="cmd_shell_3",
            expected_version=3,
            command_type="move_seashell_to_shelter",
        )

        assert first["ok"] is True
        assert first["projection"]["shelters"]["1A"]["seashells"] == 1
        assert second["projection"]["shelters"]["1A"]["secure"] is False
        assert third["ok"] is True
        assert third["projection"]["shelters"]["1A"]["seashells"] == 3
        assert third["projection"]["shelters"]["1A"]["secure"] is True
        assert third["projection"]["objectives"][0]["completed"] is True
        assert third["projection"]["phase"] == "game_over"
        assert service._memory_results[room["id"]]["outcome"] == "won"

    run(scenario())


def test_success_reward_draws_and_resolves_surprise_card_with_card_cost():
    async def scenario():
        service, user, room, _start = await create_started_room()
        state = service._memory_states[room["id"]]
        state["phase"] = "night_action"
        state["active_capability_id"] = DEFAULT_ACTIVE_CAPABILITY_ID
        state["tile_catalog"] = {
            "tiles": {
                "surprise-tile": {
                    "id": "surprise-tile",
                    "event_id": "crab",
                    "interaction_ids": ["charge"],
                    "success_effects": [{"type": "draw_surprise_card", "amount": None}],
                    "counter_attack_effects": [],
                    "failure_effects": [],
                }
            },
            "events": {"crab": {"id": "crab", "category_id": "prey"}},
            "interactions": {"charge": {"id": "charge", "name": "Charge"}},
            "surprise_cards": {
                "surprise-1": {
                    "id": "surprise-1",
                    "name": "Spark",
                    "costs": [{"type": "play_cards", "interaction_ids": ["charge"]}],
                    "effects": [{"type": "gain_neurons", "amount": 2}],
                }
            },
        }
        state["surprise_draw_pile"] = ["surprise-1"]
        state["tiles"] = {"1A": [{"instance_id": "tile_surprise", "tile_id": "surprise-tile", "face_up": True}]}
        state["interaction"] = {
            "tile_instance_id": "tile_surprise",
            "tile_id": "surprise-tile",
            "node_id": "1A",
            "played_cards": [{"card_id": "card_charge_played", "interaction_id": "charge", "capability_id": DEFAULT_ACTIVE_CAPABILITY_ID}],
        }
        state["capabilities"][DEFAULT_ACTIVE_CAPABILITY_ID]["hand"] = [
            {"card_id": "card_charge_cost", "interaction_id": "charge", "owner_capability_id": DEFAULT_ACTIVE_CAPABILITY_ID}
        ]

        resolved_interaction = await send_command(
            service,
            user,
            room,
            command_id="cmd_resolve_surprise_tile",
            expected_version=1,
            command_type="resolve_interaction",
        )
        resolved_surprise = await send_command(
            service,
            user,
            room,
            command_id="cmd_resolve_surprise_card",
            expected_version=2,
            command_type="resolve_surprise_card",
            payload={"accept": True, "capability_id": DEFAULT_ACTIVE_CAPABILITY_ID, "card_ids": ["card_charge_cost"]},
        )

        assert resolved_interaction["ok"] is True
        assert resolved_interaction["projection"]["pending_surprise"]["card"]["id"] == "surprise-1"
        assert resolved_surprise["ok"] is True
        assert resolved_surprise["projection"]["pending_surprise"] is None
        assert resolved_surprise["projection"]["poulpita"]["neurons"] == 2
        assert resolved_surprise["projection"]["capabilities"][DEFAULT_ACTIVE_CAPABILITY_ID]["hand"] == []

    run(scenario())


def test_free_surprise_tile_refreshes_stale_empty_deck_and_opens_pending_card(monkeypatch):
    async def scenario():
        service, user, room, _start = await create_started_room()
        level_with_surprises = {**TEST_LEVEL, "surprise_deck_id": "deck-1"}
        monkeypatch.setattr("backend.app.game_room_service.get_level_config", lambda level_id=None: level_with_surprises)
        monkeypatch.setattr("backend.app.game_room_service.random.shuffle", lambda cards: None)
        monkeypatch.setattr(
            "backend.app.game_room_service.get_game_content_catalog",
            lambda: {
                "tiles": {},
                "events": {},
                "interactions": {},
                "surprise_cards": {
                    "surprise-1": {
                        "id": "surprise-1",
                        "name": "Message in a Shell",
                        "costs": [],
                        "effects": [{"type": "gain_neurons", "amount": 1}],
                    }
                },
                "surprise_decks": {"deck-1": {"id": "deck-1", "name": "Deck", "card_ids": ["surprise-1"]}},
            },
        )
        state = service._memory_states[room["id"]]
        state["phase"] = "night_action"
        state["active_capability_id"] = DEFAULT_ACTIVE_CAPABILITY_ID
        state["level_id"] = "test-level"
        state["surprise_deck_id"] = "deck-1"
        state["surprise_draw_pile"] = []
        state["surprise_deck_initialized"] = True
        state["surprise_deck_exhausted"] = True
        state["surprise_deck_card_count"] = 0
        state["tile_catalog"] = {
            "tiles": {
                "surprise-tile": {
                    "id": "surprise-tile",
                    "event_id": "crab",
                    "interaction_ids": [],
                    "success_effects": [{"type": "draw_surprise_card", "amount": None}],
                    "counter_attack_effects": [],
                    "failure_effects": [],
                }
            },
            "events": {"crab": {"id": "crab", "category_id": "prey"}},
            "interactions": {},
            "surprise_cards": {},
            "surprise_decks": {},
        }
        state["tiles"] = {"1A": [{"instance_id": "tile_surprise", "tile_id": "surprise-tile", "face_up": True}]}
        state["interaction"] = {
            "tile_instance_id": "tile_surprise",
            "tile_id": "surprise-tile",
            "node_id": "1A",
            "played_cards": [],
        }

        result = await send_command(
            service,
            user,
            room,
            command_id="cmd_resolve_free_surprise_tile",
            expected_version=1,
            command_type="resolve_interaction",
        )

        assert result["ok"] is True
        assert result["projection"]["tiles"]["1A"] == []
        assert result["projection"]["pending_surprise"]["card"]["id"] == "surprise-1"

    run(scenario())


def test_tile_with_no_required_interactions_resolves_successfully():
    async def scenario():
        service, user, room, _start = await create_started_room()
        state = service._memory_states[room["id"]]
        state["phase"] = "night_action"
        state["active_capability_id"] = DEFAULT_ACTIVE_CAPABILITY_ID
        state["tile_catalog"] = {
            "tiles": {
                "free-tile": {
                    "id": "free-tile",
                    "event_id": "crab",
                    "interaction_ids": [],
                    "success_effects": [{"type": "gain_neurons", "amount": 1}],
                    "counter_attack_effects": [],
                    "failure_effects": [],
                }
            },
            "events": {"crab": {"id": "crab", "category_id": "prey"}},
            "interactions": {},
        }
        state["tiles"] = {"1A": [{"instance_id": "tile_free", "tile_id": "free-tile", "face_up": True}]}
        state["interaction"] = {
            "tile_instance_id": "tile_free",
            "tile_id": "free-tile",
            "node_id": "1A",
            "played_cards": [],
        }

        result = await send_command(
            service,
            user,
            room,
            command_id="cmd_resolve_free_tile",
            expected_version=1,
            command_type="resolve_interaction",
        )

        assert result["ok"] is True
        assert result["events"][0]["type"] == "interaction_resolved"
        assert result["projection"]["poulpita"]["neurons"] == 1
        assert result["projection"]["tiles"]["1A"] == []

    run(scenario())


def test_action_after_configured_night_duration_can_lose_game_when_energy_reaches_zero():
    async def scenario():
        service, user, room, _start = await create_started_room()
        state = service._memory_states[room["id"]]
        state["phase"] = "night_action"
        state["active_capability_id"] = DEFAULT_ACTIVE_CAPABILITY_ID
        state["night_time_total"] = 10
        state["night_time_spent"] = 10
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
        assert result["projection"]["night_time_spent"] == 11
        assert result["projection"]["poulpita"]["energy"] == 0
        assert result["projection"]["phase"] == "game_over"
        assert game_result["outcome"] == "lost"

    run(scenario())
