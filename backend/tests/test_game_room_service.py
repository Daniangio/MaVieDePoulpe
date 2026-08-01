import asyncio
from copy import deepcopy
import pytest

import backend.app.bots.planner as bot_planner
import backend.app.bot_simulation_service as bot_simulation_service
from backend.app.bots.planner import choose_bot_orchestrator_action
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


def test_bots_only_assigns_all_player_abilities_to_bots():
    async def scenario():
        service = GameRoomService()
        user = User(id="user_1", username="Player One")

        room = await service.create_room(user=user, mode="bots_only", game_type="goldfish")
        projection = await service.get_projection(room_id=room["id"], user=user)

        assert room["mode"] == "bots_only"
        assert projection["mode"] == "bots_only"
        assert projection["bot_config"]["human_ability_id"] is None
        assert {
            capability_id
            for capability_id, capability in projection["capabilities"].items()
            if capability.get("controller_type") == "bot"
        } == {"agility", "camouflage", "force", "propulsion"}
        assert projection["capabilities"]["intelligence"]["controller_type"] == "shared"

    run(scenario())


def test_bots_only_orchestrator_simulates_and_executes_one_real_action():
    async def scenario():
        service = GameRoomService()
        user = User(id="user_1", username="Player One")
        room = await service.create_room(user=user, mode="bots_only", game_type="goldfish")
        await service.enqueue_game_command(
            room_id=room["id"],
            user=user,
            command={
                "command_id": "cmd_start_bots_only",
                "room_id": room["id"],
                "actor_user_id": user.id,
                "actor_seat_id": "goldfish",
                "expected_version": 0,
                "type": "start_goldfish_game",
                "payload": {},
            },
        )
        state = service._memory_states[room["id"]]
        state["tile_catalog"]["bot_settings"] = {
            "planning_depth_take_controls": 1,
            "orchestrator_rollout_take_controls": 1,
            "orchestrator_rollouts_per_plan": 1,
            "orchestrator_sampling_temperature": 0.5,
            "max_plans": 1,
        }

        result = await service.execute_bot_orchestrator_step(room_id=room["id"], user=user)

        assert result["ok"] is True
        assert result["status"] == "action_executed"
        assert result["decision"]["settings"]["rollout_take_controls"] == 1
        assert result["decision"]["command"]["type"] == "take_control"
        assert result["projection"]["version"] == 2
        assert result["projection"]["active_capability_id"] in {"agility", "camouflage", "force", "propulsion", "intelligence"}
        assert len(result["decision"]["evaluated_plans"]) >= 1

    run(scenario())


def test_backend_only_bot_simulation_persists_compact_replay(tmp_path, monkeypatch):
    monkeypatch.setattr(bot_simulation_service, "REPLAYS_ROOT", tmp_path)
    monkeypatch.setattr(bot_simulation_service, "get_level_config", lambda level_id: TEST_LEVEL)

    summaries = bot_simulation_service.run_bot_simulation_batch(
        level_id="test-level",
        game_count=1,
        max_steps=10,
        seed=123,
    )

    assert len(summaries) == 1
    replay = bot_simulation_service.get_bot_replay(summaries[0]["id"])
    assert summaries[0]["status"] == "completed"
    assert replay["seed"] == 123
    assert replay["frames"][0]["command"] is None
    assert replay["map"]["id"] == "test-map"
    assert "map" not in replay["frames"][0]["projection"]
    assert "tile_catalog" not in replay["frames"][0]["projection"]
    assert replay["metadata"]["steps"] == len(replay["frames"]) - 1
    assert replay["progress"]["status"] == "completed"
    assert replay["progress"]["percent"] == 100
    assert replay["progress"]["phase_label"]
    assert "neurons" in replay["progress"]
    assert "seashells" in replay["progress"]

    bot_simulation_service.delete_bot_replay(replay["id"])
    assert bot_simulation_service.list_bot_replays() == []


def test_background_bot_simulations_are_listed_immediately_as_queued(tmp_path, monkeypatch):
    monkeypatch.setattr(bot_simulation_service, "REPLAYS_ROOT", tmp_path)
    monkeypatch.setattr(bot_simulation_service, "get_level_config", lambda level_id: TEST_LEVEL)
    worker_started = bot_simulation_service.threading.Event()
    release_worker = bot_simulation_service.threading.Event()

    def paused_worker(_instances):
        worker_started.set()
        release_worker.wait(timeout=2)

    monkeypatch.setattr(bot_simulation_service, "_run_background_batch", paused_worker)

    summaries = bot_simulation_service.start_bot_simulation_batch(
        level_id="test-level",
        game_count=2,
        max_steps=50,
        seed=500,
    )
    assert worker_started.wait(timeout=1)
    listed = bot_simulation_service.list_bot_replays()

    assert len(summaries) == 2
    assert {summary["status"] for summary in summaries} == {"queued"}
    assert {summary["status"] for summary in listed} == {"queued"}
    assert {summary["seed"] for summary in listed} == {500, 501}
    assert all(summary["progress"]["phase_label"] == "Queued" for summary in listed)
    release_worker.set()


def test_backend_simulation_reshuffles_an_initial_no_action_layout(tmp_path, monkeypatch):
    monkeypatch.setattr(bot_simulation_service, "REPLAYS_ROOT", tmp_path)
    monkeypatch.setattr(bot_simulation_service, "get_level_config", lambda level_id: TEST_LEVEL)
    playable_state = _goldfish_state("simulation_template", level_id="test-level", mode="bots_only")
    dead_state = deepcopy(playable_state)
    for capability in dead_state["capabilities"].values():
        capability["max_control_takes_per_night"] = 0
    generated_states = [dead_state, playable_state]

    def generate_state(*_args, **_kwargs):
        return deepcopy(generated_states.pop(0) if generated_states else playable_state)

    monkeypatch.setattr(bot_simulation_service, "_goldfish_state", generate_state)

    summary = bot_simulation_service.run_bot_simulation(
        level_id="test-level",
        seed=700,
        max_steps=10,
    )
    replay = bot_simulation_service.get_bot_replay(summary["id"])

    assert replay["metadata"]["setup_rerolls"] == 1
    assert replay["frames"][1]["command"]["type"] != "bot_no_actions_available"
    assert not (summary["outcome"] == "lost" and summary["steps"] == 1)


def test_bots_only_orchestrator_marks_an_early_shelter_dead_end_as_lost():
    async def scenario():
        service = GameRoomService()
        user = User(id="user_1", username="Player One")
        room = await service.create_room(user=user, mode="bots_only", game_type="goldfish")
        await service.enqueue_game_command(
            room_id=room["id"],
            user=user,
            command={
                "command_id": "cmd_start_bots_only_dead_end",
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
        state["active_capability_id"] = DEFAULT_ACTIVE_CAPABILITY_ID
        state["night_time_spent"] = 0
        current_node_id = state["poulpita"]["node_id"]
        state["shelters"][current_node_id] = {"count": 1, "seashells": 0, "secure": False}
        for capability in state["capabilities"].values():
            capability["control_takes_this_night"] = capability["max_control_takes_per_night"]
        active = state["capabilities"][DEFAULT_ACTIVE_CAPABILITY_ID]
        active["actions_taken_this_control"] = active["max_actions_per_control"]

        result = await service.execute_bot_orchestrator_step(room_id=room["id"], user=user)
        game_result = await service.get_result(room_id=room["id"], user_id=user.id)

        assert result["ok"] is True
        assert result["projection"]["phase"] == "game_over"
        assert service._memory_states[room["id"]]["game_over_reason"] == "no_controls_or_actions"
        assert game_result["outcome"] == "lost"

    run(scenario())


def test_bots_only_orchestrator_marks_unaffordable_action_dead_end_as_lost():
    async def scenario():
        service = GameRoomService()
        user = User(id="user_1", username="Player One")
        room = await service.create_room(user=user, mode="bots_only", game_type="goldfish")
        await service.enqueue_game_command(
            room_id=room["id"],
            user=user,
            command={
                "command_id": "cmd_start_unaffordable_dead_end",
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
        current_node_id = state["poulpita"]["node_id"]
        state["map"]["adjacency"][current_node_id] = []
        state["poulpita"]["neurons"] = 0
        state["tile_catalog"]["action_costs"] = {
            "gain_ap": {"ap_cost": 0, "time_cost": 0, "neuron_cost": 1},
        }
        for ability_id, capability in state["capabilities"].items():
            capability["hand"] = []
            capability["draw_pile"] = []
            capability["discard"] = []
            if ability_id != "force":
                capability["control_takes_this_night"] = capability["max_control_takes_per_night"]

        result = await service.execute_bot_orchestrator_step(room_id=room["id"], user=user)

        assert result["ok"] is True
        assert result["decision"]["command"]["type"] == "bot_no_actions_available"
        assert result["projection"]["phase"] == "game_over"
        assert service._memory_states[room["id"]]["game_over_reason"] == "no_controls_or_actions"

    run(scenario())


def test_bot_no_actions_command_is_rejected_while_another_control_take_remains():
    async def scenario():
        service = GameRoomService()
        user = User(id="user_1", username="Player One")
        room = await service.create_room(user=user, mode="bots_only", game_type="goldfish")
        await service.enqueue_game_command(
            room_id=room["id"],
            user=user,
            command={
                "command_id": "cmd_start_false_dead_end",
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
        state["active_capability_id"] = "intelligence"
        active = state["capabilities"]["intelligence"]
        active["actions_taken_this_control"] = active["max_actions_per_control"]
        state["capabilities"]["force"]["control_takes_this_night"] = 0

        result = await service.enqueue_game_command(
            room_id=room["id"],
            user=user,
            command={
                "command_id": "cmd_false_dead_end",
                "room_id": room["id"],
                "actor_user_id": user.id,
                "actor_seat_id": "bot_orchestrator",
                "expected_version": state["version"],
                "type": "bot_no_actions_available",
                "payload": {},
            },
        )

        assert result["ok"] is False
        assert result["reason"] == "bot_actions_still_available"
        assert service._memory_states[room["id"]]["phase"] == "night_action"

    run(scenario())


def test_bot_orchestrator_rollouts_do_not_mutate_authoritative_state():
    state = _goldfish_state(
        "room_bot_rollout_copy",
        level_id="test-level",
        mode="bots_only",
        bot_config={
            "mode": "bots_only",
            "human_ability_id": None,
            "controllers": [
                {"ability_id": capability_id, "controller_type": "bot", "seat_id": f"bot_{capability_id}"}
                for capability_id in ["agility", "camouflage", "force", "propulsion"]
            ]
            + [{"ability_id": "intelligence", "controller_type": "shared", "seat_id": "shared_intelligence"}],
        },
    )
    state["tile_catalog"]["bot_settings"] = {
        "planning_depth_take_controls": 1,
        "orchestrator_rollout_take_controls": 1,
        "orchestrator_rollouts_per_plan": 1,
        "max_plans": 1,
    }
    authoritative_snapshot = deepcopy(state)

    decision = choose_bot_orchestrator_action(state)

    assert decision["status"] == "selected"
    assert decision["command"]["type"] == "take_control"
    assert state == authoritative_snapshot


def test_bot_orchestrator_does_not_generate_the_detailed_plan_tree(monkeypatch):
    state = _goldfish_state(
        "room_bot_local_processor",
        level_id="test-level",
        mode="bots_only",
        bot_config={
            "mode": "bots_only",
            "human_ability_id": None,
            "controllers": [
                {"ability_id": capability_id, "controller_type": "bot", "seat_id": f"bot_{capability_id}"}
                for capability_id in ["agility", "camouflage", "force", "propulsion"]
            ]
            + [{"ability_id": "intelligence", "controller_type": "shared", "seat_id": "shared_intelligence"}],
        },
    )
    state["tile_catalog"]["bot_settings"] = {
        "orchestrator_rollout_take_controls": 1,
        "orchestrator_rollouts_per_plan": 1,
        "orchestrator_max_candidates": 5,
    }

    monkeypatch.setattr(
        bot_planner,
        "generate_bot_plan_status",
        lambda _state: (_ for _ in ()).throw(AssertionError("Detailed planner must not run in local bot simulation.")),
    )

    decision = choose_bot_orchestrator_action(state)

    assert decision["status"] == "selected"
    assert decision["planner_debug"]["processor"] == "local"


def test_bot_orchestrator_follows_plan_commands_before_replanning(monkeypatch):
    state = _goldfish_state(
        "room_bot_precise_rollout",
        level_id="test-level",
        mode="bots_only",
        bot_config={
            "mode": "bots_only",
            "human_ability_id": None,
            "controllers": [
                {"ability_id": capability_id, "controller_type": "bot", "seat_id": f"bot_{capability_id}"}
                for capability_id in ["agility", "camouflage", "force", "propulsion"]
            ]
            + [{"ability_id": "intelligence", "controller_type": "shared", "seat_id": "shared_intelligence"}],
        },
    )
    root = {
        "plan_id": "precise_root",
        "title": "Precise root",
        "commands": [
            {"type": "take_control", "payload": {"capability_id": "agility"}},
            {"type": "collect_action_points", "payload": {"capability_id": "agility"}},
        ],
        "statistics": {"planner_score": 10, "pareto_axes": {"expected_gain": 1}},
    }
    continuation = {
        "plan_id": "next_control",
        "title": "Next control",
        "commands": [{"type": "take_control", "payload": {"capability_id": "force"}}],
        "statistics": {"planner_score": 10, "pareto_axes": {"expected_gain": 1}},
    }
    planner_calls = 0

    def generated_status(_state):
        nonlocal planner_calls
        planner_calls += 1
        return {"proposals": [continuation], "message": ""}

    monkeypatch.setattr(bot_planner, "_local_orchestrator_candidates", lambda next_state: generated_status(next_state)["proposals"])

    rollout = bot_planner._simulate_orchestrator_rollout(
        state,
        root_proposal=root,
        horizon=1,
        temperature=1,
        seed="precise",
    )

    assert [step["command"]["type"] for step in rollout["path"]] == [
        "take_control",
        "collect_action_points",
    ]
    assert planner_calls == 1
    assert rollout["replans"] == 1
    assert rollout["stop_reason"] == "initiative horizon reached"


def test_bots_only_rejects_manual_game_commands_after_start():
    async def scenario():
        service = GameRoomService()
        user = User(id="user_1", username="Player One")
        room = await service.create_room(user=user, mode="bots_only", game_type="goldfish")
        await service.enqueue_game_command(
            room_id=room["id"],
            user=user,
            command={
                "command_id": "cmd_start_bots_only_manual_rejection",
                "room_id": room["id"],
                "actor_user_id": user.id,
                "actor_seat_id": "goldfish",
                "expected_version": 0,
                "type": "start_goldfish_game",
                "payload": {},
            },
        )

        rejected = await send_command(
            service,
            user,
            room,
            command_id="cmd_manual_take_control",
            expected_version=1,
            command_type="take_control",
            payload={"capability_id": "agility"},
        )

        assert rejected["ok"] is False
        assert rejected["reason"] == "bots_only_room"
        assert rejected["current_version"] == 1

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
        assert all(proposal["proposer_ability_id"] in {"agility", "camouflage", "force", "propulsion", "intelligence"} for proposal in plans["proposals"])
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
        assert result["projection"]["capabilities"]["agility"]["pa"] == 5

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
        accept_plan = next(plan for plan in public_plans["proposals"] if plan["plan_id"] == "surprise_accept_camouflage")

        assert [plan["plan_id"] for plan in public_plans["proposals"]] == ["surprise_accept_camouflage", "surprise_skip"]
        assert all("commands" not in plan for plan in public_plans["proposals"])
        assert "secret_card_hide" not in str(public_plans)
        assert accept_plan["statistics"]["surprise_resolution"] == "pay"
        assert accept_plan["statistics"]["surprise_delta"]["neurons"] == 2
        assert accept_plan["statistics"]["surprise_delta"]["cards_in_hand"] == -1
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


def test_bot_plans_keep_current_active_control_until_actions_are_exhausted():
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
        assert not any(
            (plan.get("plan_chain") or [{}])[0].get("public_command", {}).get("type") == "take_control"
            for plan in plans["proposals"]
        )
        active_plan = next(plan for plan in plans["proposals"] if plan["plan_id"] == "collect_force")
        assert active_plan["statistics"]["recommended_active_ability_id"] == "force"
        assert active_plan["proposer_ability_id"] != "force"

        state["capabilities"]["force"]["actions_taken_this_control"] = state["capabilities"]["force"]["max_actions_per_control"]
        exhausted = bot_planner.generate_bot_plan_status(state)

        assert any(
            (plan.get("commands") or [{}])[0].get("type") == "take_control"
            for plan in exhausted["proposals"]
        )

    run(scenario())


def test_local_orchestrator_switches_control_only_without_active_actions():
    state = _goldfish_state("room_local_active", level_id="test-level", mode="bots_only")
    state["phase"] = "night_action"
    state["active_capability_id"] = "force"
    state["capabilities"]["force"]["pa"] = 2
    state["capabilities"]["force"]["actions_taken_this_control"] = 0

    active_candidates = bot_planner._local_orchestrator_night_candidates(state)

    assert active_candidates
    assert all(
        (candidate.get("commands") or [{}])[0].get("type") != "take_control"
        for candidate in active_candidates
    )

    state["capabilities"]["force"]["actions_taken_this_control"] = state["capabilities"]["force"]["max_actions_per_control"]
    exhausted_candidates = bot_planner._local_orchestrator_night_candidates(state)

    assert exhausted_candidates
    assert all(
        (candidate.get("commands") or [{}])[0].get("type") == "take_control"
        for candidate in exhausted_candidates
    )


def test_local_orchestrator_switches_to_compulsory_initiator_with_immediate_followup():
    state = _goldfish_state("room_required_initiator", level_id="test-level", mode="bots_only")
    state["phase"] = "night_action"
    state["active_capability_id"] = "force"
    current_node_id = state["poulpita"]["node_id"]
    for ability_id, capability in state["capabilities"].items():
        capability["initiates_event_ids"] = ["threat-event"] if ability_id == "camouflage" else []
    state["tile_catalog"] = {
        **state["tile_catalog"],
        "categories": {"threat": {"id": "threat", "name": "Threat", "compulsory_on_same_node": True}},
        "events": {"threat-event": {"id": "threat-event", "name": "Big fish", "category_id": "threat"}},
        "tiles": {
            "threat-tile": {
                "id": "threat-tile",
                "event_id": "threat-event",
                "priority": 5,
                "interaction_ids": [],
            }
        },
    }
    state["tiles"] = {
        current_node_id: [{"instance_id": "threat-instance", "tile_id": "threat-tile", "face_up": True}]
    }

    candidates = bot_planner._local_orchestrator_night_candidates(state)

    assert [candidate["commands"][0] for candidate in candidates] == [
        {"type": "take_control", "payload": {"capability_id": "camouflage"}}
    ]
    simulated = deepcopy(state)
    bot_planner._simulate_public_command(simulated, candidates[0]["commands"][0])
    followups = bot_planner._local_orchestrator_night_candidates(simulated)
    assert followups
    assert followups[0]["commands"][0]["type"] == "start_interaction"


def test_local_orchestrator_uses_active_fallback_before_switching_control():
    state = _goldfish_state("room_active_fallback", level_id="test-level", mode="bots_only")
    state["phase"] = "night_action"
    state["active_capability_id"] = "force"
    current_node_id = state["poulpita"]["node_id"]
    state["map"]["adjacency"][current_node_id] = []
    for capability in state["capabilities"].values():
        capability["hand"] = []
        capability["draw_pile"] = []
        capability["discard"] = []

    candidates = bot_planner._local_orchestrator_night_candidates(state)

    assert [candidate["commands"][0] for candidate in candidates] == [
        {"type": "collect_action_points", "payload": {"capability_id": "force"}}
    ]


def test_local_orchestrator_does_not_lose_when_unassigned_compulsory_tile_blocks_scoring():
    state = _goldfish_state("room_unassigned_compulsory", level_id="test-level", mode="bots_only")
    state["phase"] = "night_action"
    state["active_capability_id"] = "intelligence"
    active = state["capabilities"]["intelligence"]
    active["actions_taken_this_control"] = active["max_actions_per_control"]
    current_node_id = state["poulpita"]["node_id"]
    for capability in state["capabilities"].values():
        capability["initiates_event_ids"] = []
    state["tile_catalog"] = {
        **state["tile_catalog"],
        "categories": {"threat": {"id": "threat", "name": "Threat", "compulsory_on_same_node": True}},
        "events": {"moray": {"id": "moray", "name": "Moray", "category_id": "threat"}},
        "tiles": {"moray-tile": {"id": "moray-tile", "event_id": "moray", "priority": 6, "interaction_ids": []}},
    }
    state["tiles"] = {
        current_node_id: [{"instance_id": "moray-instance", "tile_id": "moray-tile", "face_up": True}]
    }

    candidates = bot_planner._local_orchestrator_night_candidates(state)
    commands = [candidate["commands"][0] for candidate in candidates]

    assert commands
    assert all(command["type"] == "take_control" for command in commands)
    assert all(command["type"] != "bot_no_actions_available" for command in commands)


def test_local_orchestrator_ignores_gain_only_control_when_productive_control_exists():
    state = _goldfish_state("room_productive_control", level_id="test-level", mode="bots_only")
    state["phase"] = "night_idle"
    state["active_capability_id"] = None
    for ability_id, capability in state["capabilities"].items():
        capability["pa"] = 0 if ability_id == "force" else 2
        if ability_id not in {"force", "camouflage"}:
            capability["control_takes_this_night"] = capability["max_control_takes_per_night"]

    candidates = bot_planner._local_orchestrator_night_candidates(state)
    commands = [candidate["commands"][0] for candidate in candidates]

    assert {"type": "take_control", "payload": {"capability_id": "camouflage"}} in commands
    assert {"type": "take_control", "payload": {"capability_id": "force"}} not in commands


def test_local_orchestrator_finishes_when_no_control_can_start_the_night():
    state = _goldfish_state("room_no_controls", level_id="test-level", mode="bots_only")
    state["phase"] = "night_idle"
    state["active_capability_id"] = None
    for capability in state["capabilities"].values():
        capability["control_takes_this_night"] = capability["max_control_takes_per_night"]

    candidates = bot_planner._local_orchestrator_night_candidates(state)

    assert [candidate["commands"][0] for candidate in candidates] == [
        {"type": "bot_no_actions_available", "payload": {}}
    ]


def test_local_orchestrator_finishes_instead_of_idling_when_no_action_is_affordable():
    state = _goldfish_state("room_no_affordable_action", level_id="test-level", mode="bots_only")
    state["phase"] = "night_action"
    state["active_capability_id"] = "force"
    current_node_id = state["poulpita"]["node_id"]
    state["map"]["adjacency"][current_node_id] = []
    state["poulpita"]["neurons"] = 0
    state["tile_catalog"]["action_costs"] = {
        "gain_ap": {"ap_cost": 0, "time_cost": 0, "neuron_cost": 1},
    }
    for ability_id, capability in state["capabilities"].items():
        capability["hand"] = []
        capability["draw_pile"] = []
        capability["discard"] = []
        if ability_id != "force":
            capability["control_takes_this_night"] = capability["max_control_takes_per_night"]

    candidates = bot_planner._local_orchestrator_night_candidates(state)

    assert [candidate["commands"][0] for candidate in candidates] == [
        {"type": "bot_no_actions_available", "payload": {}}
    ]
    assert bot_planner.has_executable_bot_orchestrator_action(state) is False


def test_local_orchestrator_collects_ap_instead_of_switching_for_free_surprise_tile():
    state = _goldfish_state("room_local_surprise", level_id="test-level", mode="bots_only")
    state["phase"] = "night_action"
    state["active_capability_id"] = "force"
    state["capabilities"]["force"]["pa"] = 0
    state["capabilities"]["force"]["actions_taken_this_control"] = 1
    current_node_id = state["poulpita"]["node_id"]
    surprise_event_id = "surprise-event"
    for capability in state["capabilities"].values():
        capability["initiates_event_ids"] = [surprise_event_id]
    state["tile_catalog"] = {
        **state["tile_catalog"],
        "categories": {
            "surprise-category": {
                "id": "surprise-category",
                "name": "Surprise",
                "compulsory_on_same_node": True,
            }
        },
        "events": {
            surprise_event_id: {
                "id": surprise_event_id,
                "name": "Surprise",
                "category_id": "surprise-category",
            }
        },
        "tiles": {
            "surprise-tile": {
                "id": "surprise-tile",
                "event_id": surprise_event_id,
                "priority": 100,
                "interaction_ids": [],
                "success_effects": [{"type": "draw_surprise_card"}],
            }
        },
    }
    state["tiles"] = {
        current_node_id: [
            {
                "instance_id": "surprise-instance",
                "tile_id": "surprise-tile",
                "face_up": True,
            }
        ]
    }

    candidates = bot_planner._local_orchestrator_night_candidates(state)

    assert candidates
    assert candidates[0]["commands"][0]["type"] == "collect_action_points"
    assert all(candidate["commands"][0]["type"] != "take_control" for candidate in candidates)

    state["capabilities"]["force"]["pa"] = 1
    state["interaction"] = {
        "tile_instance_id": "surprise-instance",
        "tile_id": "surprise-tile",
        "node_id": current_node_id,
        "initiator_capability_id": "force",
        "played_cards": [],
    }
    interaction_candidates = bot_planner._local_orchestrator_interaction_candidates(state)
    assert [candidate["commands"][0]["type"] for candidate in interaction_candidates] == ["resolve_interaction"]


def test_local_orchestrator_switches_to_bot_with_partial_interaction_support():
    state = _goldfish_state("room_local_support", level_id="test-level", mode="bots_only")
    state["phase"] = "night_action"
    state["active_capability_id"] = "force"
    current_node_id = state["poulpita"]["node_id"]
    for capability in state["capabilities"].values():
        capability["hand"] = []
        capability["draw_pile"] = []
        capability["discard"] = []
    state["capabilities"]["camouflage"]["hand"] = [
        {
            "card_id": "hide-card",
            "interaction_id": "hide",
            "interaction_ids": ["hide"],
            "owner_capability_id": "camouflage",
        }
    ]
    state["capabilities"]["intelligence"]["hand"] = [
        {
            "card_id": "analyse-card",
            "interaction_id": "analyse",
            "interaction_ids": ["analyse"],
            "owner_capability_id": "intelligence",
        }
    ]
    state["tile_catalog"] = {
        **state["tile_catalog"],
        "categories": {"threat": {"id": "threat", "name": "Threat", "compulsory_on_same_node": True}},
        "events": {"fish": {"id": "fish", "name": "Big fish", "category_id": "threat"}},
        "interactions": {
            "charge": {"id": "charge", "name": "Charge"},
            "hide": {"id": "hide", "name": "Hide"},
            "analyse": {"id": "analyse", "name": "Analyse"},
        },
        "tiles": {
            "fish-tile": {
                "id": "fish-tile",
                "event_id": "fish",
                "interaction_ids": ["charge", "hide", "analyse"],
            }
        },
    }
    state["tiles"] = {
        current_node_id: [{"instance_id": "fish-instance", "tile_id": "fish-tile", "face_up": True}]
    }
    state["interaction"] = {
        "tile_instance_id": "fish-instance",
        "tile_id": "fish-tile",
        "node_id": current_node_id,
        "initiator_capability_id": "force",
        "played_cards": [
            {
                "card_id": "charge-card",
                "interaction_id": "charge",
                "interaction_ids": ["charge"],
                "capability_id": "force",
            }
        ],
    }

    candidates = bot_planner._local_orchestrator_interaction_candidates(state)
    camouflage = next(
        candidate
        for candidate in candidates
        if candidate["commands"][0] == {"type": "resolve_interaction", "payload": {"capability_id": "camouflage", "card_ids": ["hide-card"], "confirm_only": True}}
    )
    simulated = deepcopy(state)
    bot_planner._simulate_public_command(simulated, camouflage["commands"][0])
    support_commands, _entries, _label = bot_planner._next_interaction_support_command(simulated, "intelligence")

    assert support_commands[0]["type"] == "resolve_interaction"
    assert support_commands[0]["payload"]["auto_select_cards"] is True
    assert all(candidate["commands"][0]["type"] == "resolve_interaction" for candidate in candidates)
    state["tile_catalog"]["bot_settings"] = {
        "orchestrator_rollout_take_controls": 2,
        "orchestrator_rollouts_per_plan": 1,
        "orchestrator_sampling_temperature": 0.1,
    }
    decision = choose_bot_orchestrator_action(state)
    assert decision["command"]["type"] == "resolve_interaction"
    assert decision["command"]["payload"]["capability_id"] in {"camouflage", "intelligence"}


def test_local_orchestrator_keeps_useful_support_search_and_fails_when_no_path_remains():
    state = _goldfish_state("room_local_support_search", level_id="test-level", mode="bots_only")
    state["phase"] = "night_action"
    state["active_capability_id"] = "force"
    current_node_id = state["poulpita"]["node_id"]
    for capability in state["capabilities"].values():
        capability["hand"] = []
        capability["draw_pile"] = []
        capability["discard"] = []
        capability["pa"] = 3
        capability["actions_taken_this_control"] = 0
    state["tile_catalog"] = {
        **state["tile_catalog"],
        "categories": {"threat": {"id": "threat", "name": "Threat", "compulsory_on_same_node": True}},
        "events": {"fish": {"id": "fish", "name": "Big fish", "category_id": "threat"}},
        "interactions": {"hide": {"id": "hide", "name": "Hide"}},
        "tiles": {
            "fish-tile": {
                "id": "fish-tile",
                "event_id": "fish",
                "interaction_ids": ["hide"],
                "failure_effects": [{"type": "lose_energy", "amount": 1}],
            }
        },
    }
    state["tiles"] = {current_node_id: [{"instance_id": "fish-instance", "tile_id": "fish-tile", "face_up": True}]}
    state["interaction"] = {
        "tile_instance_id": "fish-instance",
        "tile_id": "fish-tile",
        "node_id": current_node_id,
        "initiator_capability_id": "force",
        "initiator_confirmed": True,
        "played_cards": [],
    }
    state["capabilities"]["force"]["draw_pile"] = [
        {"card_id": "force-hide", "interaction_id": "hide", "interaction_ids": ["hide"], "owner_capability_id": "force"}
    ]
    state["capabilities"]["camouflage"]["draw_pile"] = [
        {"card_id": "camouflage-hide", "interaction_id": "hide", "interaction_ids": ["hide"], "owner_capability_id": "camouflage"}
    ]

    active_search = bot_planner._local_orchestrator_interaction_candidates(state)
    assert [candidate["commands"][0]["type"] for candidate in active_search] == ["draw_action_card", "fail_interaction"]
    assert active_search[0]["commands"][0]["payload"]["capability_id"] == "force"
    assert all(candidate["commands"][0]["type"] != "take_control" for candidate in active_search)
    state["tile_catalog"]["bot_settings"] = {
        "orchestrator_rollout_take_controls": 1,
        "orchestrator_rollouts_per_plan": 1,
        "orchestrator_sampling_temperature": 0.1,
    }
    assert choose_bot_orchestrator_action(state)["command"] == {
        "type": "draw_action_card",
        "payload": {"capability_id": "force"},
    }

    state["capabilities"]["force"]["actions_taken_this_control"] = state["capabilities"]["force"]["max_actions_per_control"]
    targeted_switch = bot_planner._local_orchestrator_interaction_candidates(state)
    take_commands = [candidate["commands"][0] for candidate in targeted_switch if candidate["commands"][0]["type"] == "take_control"]
    assert take_commands == [{"type": "take_control", "payload": {"capability_id": "camouflage"}}]

    state["capabilities"]["camouflage"]["draw_pile"] = []
    no_path = bot_planner._local_orchestrator_interaction_candidates(state)
    assert [candidate["commands"][0]["type"] for candidate in no_path] == ["fail_interaction"]


def test_local_orchestrator_does_not_draw_for_exhausted_interaction_initiator():
    state = _goldfish_state("room_exhausted_support", level_id="test-level", mode="bots_only")
    state["phase"] = "night_action"
    state["active_capability_id"] = "force"
    current_node_id = state["poulpita"]["node_id"]
    for capability in state["capabilities"].values():
        capability["hand"] = []
        capability["draw_pile"] = []
        capability["discard"] = []
    force = state["capabilities"]["force"]
    force["actions_taken_this_control"] = force["max_actions_per_control"]
    force["pa"] = 3
    force["draw_pile"] = [
        {
            "card_id": "force-hide",
            "interaction_id": "hide",
            "interaction_ids": ["hide"],
            "owner_capability_id": "force",
        }
    ]
    state["capabilities"]["camouflage"]["hand"] = [
        {
            "card_id": "camouflage-hide",
            "interaction_id": "hide",
            "interaction_ids": ["hide"],
            "owner_capability_id": "camouflage",
        }
    ]
    state["tile_catalog"] = {
        **state["tile_catalog"],
        "categories": {"threat": {"id": "threat", "name": "Threat", "compulsory_on_same_node": True}},
        "events": {"fish": {"id": "fish", "name": "Big fish", "category_id": "threat"}},
        "interactions": {"hide": {"id": "hide", "name": "Hide"}},
        "tiles": {
            "fish-tile": {
                "id": "fish-tile",
                "event_id": "fish",
                "interaction_ids": ["hide"],
            }
        },
    }
    state["tiles"] = {
        current_node_id: [{"instance_id": "fish-instance", "tile_id": "fish-tile", "face_up": True}]
    }
    state["interaction"] = {
        "tile_instance_id": "fish-instance",
        "tile_id": "fish-tile",
        "node_id": current_node_id,
        "initiator_capability_id": "force",
        "played_cards": [],
    }

    candidates = bot_planner._local_orchestrator_interaction_candidates(state)
    commands = [candidate["commands"][0] for candidate in candidates]

    assert {"type": "draw_action_card", "payload": {"capability_id": "force"}} not in commands
    assert {"type": "collect_action_points", "payload": {"capability_id": "force"}} not in commands
    assert {"type": "resolve_interaction", "payload": {"capability_id": "camouflage", "card_ids": ["camouflage-hide"], "confirm_only": True}} in commands


def test_local_orchestrator_interacts_instead_of_farming_ap_when_tile_is_available():
    state = _goldfish_state("room_local_tile_reward", level_id="test-level", mode="bots_only")
    state["phase"] = "night_action"
    state["active_capability_id"] = "force"
    state["capabilities"]["force"]["pa"] = 2
    state["capabilities"]["force"]["actions_taken_this_control"] = 0
    state["capabilities"]["force"]["initiates_event_ids"] = ["prey-event"]
    current_node_id = state["poulpita"]["node_id"]
    state["tile_catalog"] = {
        **state["tile_catalog"],
        "categories": {"prey": {"id": "prey", "name": "Prey", "compulsory_on_same_node": False}},
        "events": {"prey-event": {"id": "prey-event", "name": "Crab", "category_id": "prey"}},
        "tiles": {
            "prey-tile": {
                "id": "prey-tile",
                "event_id": "prey-event",
                "priority": 1,
                "interaction_ids": [],
                "success_effects": [{"type": "gain_energy", "amount": 1}],
            }
        },
    }
    state["tiles"] = {
        current_node_id: [{"instance_id": "prey-instance", "tile_id": "prey-tile", "face_up": True}]
    }

    candidates = bot_planner._local_orchestrator_night_candidates(state)
    command_types = [candidate["commands"][0]["type"] for candidate in candidates]

    assert "start_interaction" in command_types
    assert "collect_action_points" not in command_types
    interaction_candidate = next(
        candidate for candidate in candidates if candidate["commands"][0]["type"] == "start_interaction"
    )
    assert interaction_candidate["statistics"]["planner_score"] > 55
    state["tile_catalog"]["bot_settings"] = {
        "orchestrator_rollout_take_controls": 1,
        "orchestrator_rollouts_per_plan": 1,
        "orchestrator_sampling_temperature": 0.1,
    }
    decision = choose_bot_orchestrator_action(state)
    assert decision["command"]["type"] == "start_interaction"


def test_local_orchestrator_switches_to_an_optional_tile_initiator_before_moving():
    state = _goldfish_state("room_local_optional_switch", level_id="test-level", mode="bots_only")
    state["phase"] = "night_action"
    state["active_capability_id"] = "force"
    state["capabilities"]["force"]["actions_taken_this_control"] = state["capabilities"]["force"]["max_actions_per_control"]
    state["capabilities"]["camouflage"]["initiates_event_ids"] = ["prey-event"]
    current_node_id = state["poulpita"]["node_id"]
    state["tile_catalog"] = {
        **state["tile_catalog"],
        "categories": {"prey": {"id": "prey", "name": "Prey", "compulsory_on_same_node": False}},
        "events": {"prey-event": {"id": "prey-event", "name": "Crab", "category_id": "prey"}},
        "tiles": {
            "prey-tile": {
                "id": "prey-tile",
                "event_id": "prey-event",
                "priority": 1,
                "interaction_ids": [],
                "success_effects": [{"type": "gain_energy", "amount": 1}],
            }
        },
    }
    state["tiles"] = {
        current_node_id: [{"instance_id": "prey-instance", "tile_id": "prey-tile", "face_up": True}]
    }

    candidates = bot_planner._local_orchestrator_night_candidates(state)
    commands = [candidate["commands"][0] for candidate in candidates]

    assert commands == [{"type": "take_control", "payload": {"capability_id": "camouflage"}}]


def test_interaction_requiring_three_abilities_receives_configured_penalty():
    state = _goldfish_state("room_team_penalty", level_id="test-level", mode="bots_only")
    state["active_capability_id"] = "force"
    state["tile_catalog"]["bot_settings"] = {"weights": {"third_ability_penalty": 60}}
    for capability in state["capabilities"].values():
        capability["hand"] = []
    state["capabilities"]["force"]["hand"] = [
        {"card_id": "charge-card", "interaction_id": "charge", "interaction_ids": ["charge"]}
    ]
    state["capabilities"]["camouflage"]["hand"] = [
        {"card_id": "hide-card", "interaction_id": "hide", "interaction_ids": ["hide"]}
    ]
    state["capabilities"]["intelligence"]["hand"] = [
        {"card_id": "analyse-card", "interaction_id": "analyse", "interaction_ids": ["analyse"]}
    ]
    entry = {
        "tile": {"id": "complex-threat", "interaction_ids": ["charge", "hide", "analyse"]},
        "instance": {"instance_id": "complex-threat-instance", "tile_id": "complex-threat"},
        "node_id": state["poulpita"]["node_id"],
    }

    team_size, penalty = bot_planner._interaction_team_penalty(state, entry, "force")

    assert team_size == 3
    assert penalty == 60


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


def test_bot_plans_suggest_drawing_when_open_interaction_support_is_missing_from_hand():
    async def scenario():
        service = GameRoomService()
        user = User(id="user_1", username="Player One")
        room = await service.create_room(user=user, mode="solo_with_bots", game_type="goldfish", human_ability_id="force")
        await service.enqueue_game_command(
            room_id=room["id"],
            user=user,
            command={
                "command_id": "cmd_start_draw_support_plan",
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
        state["capabilities"]["force"]["actions_taken_this_control"] = state["capabilities"]["force"]["max_actions_per_control"]
        state["capabilities"]["camouflage"]["pa"] = 1
        state["capabilities"]["camouflage"]["hand"] = []
        state["capabilities"]["camouflage"]["draw_pile"] = [
            {"card_id": "future_hide_card", "interaction_id": "hide", "interaction_ids": ["hide"], "owner_capability_id": "camouflage"}
        ]
        state["tile_catalog"] = {
            "categories": {"threat": {"id": "threat", "name": "Threat", "compulsory_on_same_node": True}},
            "events": {"crab": {"id": "crab", "name": "Crab", "category_id": "threat"}},
            "tiles": {"crab-tile": {"id": "crab-tile", "event_id": "crab", "priority": 10, "interaction_ids": ["hide"]}},
            "interactions": {"hide": {"id": "hide", "name": "Hide"}},
        }
        state["interaction"] = {
            "tile_instance_id": "tile_crab",
            "tile_id": "crab-tile",
            "node_id": "1A",
            "initiator_capability_id": "force",
            "played_cards": [],
        }

        plans = await service.get_bot_plans(room_id=room["id"], user=user)
        plan_ids = [plan["plan_id"] for plan in plans["proposals"]]
        draw_plan = next(plan for plan in plans["proposals"] if plan["proposer_ability_id"] == "camouflage")

        assert not any(plan_id.startswith("open_interaction_needs_manual_resolution") for plan_id in plan_ids)
        assert draw_plan["plan_chain"][0]["public_command"]["type"] == "take_control"
        assert draw_plan["plan_chain"][1]["public_command"]["type"] == "draw_action_card"
        assert draw_plan["statistics"]["support_estimate"]["known_future_matches"] == 1

    run(scenario())


def test_bot_plans_use_shared_intelligence_cards_for_open_interaction_support():
    async def scenario():
        service = GameRoomService()
        user = User(id="user_1", username="Player One")
        room = await service.create_room(user=user, mode="solo_with_bots", game_type="goldfish", human_ability_id="force")
        await service.enqueue_game_command(
            room_id=room["id"],
            user=user,
            command={
                "command_id": "cmd_start_intelligence_support_plan",
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
        state["capabilities"]["force"]["actions_taken_this_control"] = state["capabilities"]["force"]["max_actions_per_control"]
        state["capabilities"]["intelligence"]["hand"] = [
            {"card_id": "analyse_card", "interaction_id": "analyse", "interaction_ids": ["analyse"], "owner_capability_id": "intelligence"}
        ]
        state["tile_catalog"] = {
            "categories": {"threat": {"id": "threat", "name": "Threat", "compulsory_on_same_node": True}},
            "events": {"fish": {"id": "fish", "name": "Big fish", "category_id": "threat"}},
            "tiles": {"fish-tile": {"id": "fish-tile", "event_id": "fish", "priority": 10, "interaction_ids": ["analyse"]}},
            "interactions": {"analyse": {"id": "analyse", "name": "Analyse"}},
        }
        state["interaction"] = {
            "tile_instance_id": "tile_fish",
            "tile_id": "fish-tile",
            "node_id": "1A",
            "initiator_capability_id": "camouflage",
            "played_cards": [],
        }

        plans = await service.get_bot_plans(room_id=room["id"], user=user)
        plan = next(plan for plan in plans["proposals"] if plan["plan_id"] == "support_interaction_intelligence_tile_fish")

        assert plan["proposer_ability_id"] == "intelligence"
        assert plan["plan_chain"][0]["public_command"]["type"] == "resolve_interaction"
        assert plan["statistics"]["support_estimate"]["hand_matches"] == 1
        assert "analyse_card" not in str(plans)

    run(scenario())


def test_auto_resolve_interaction_selects_counter_attack_cards():
    async def scenario():
        service, user, room, _start = await create_started_room()
        state = service._memory_states[room["id"]]
        state["phase"] = "night_action"
        state["active_capability_id"] = "camouflage"
        state["poulpita"]["energy"] = 3
        state["tile_catalog"] = {
            "categories": {"threat": {"id": "threat", "name": "Threat", "compulsory_on_same_node": True}},
            "events": {"fish": {"id": "fish", "name": "Big fish", "category_id": "threat"}},
            "tiles": {
                "fish-tile": {
                    "id": "fish-tile",
                    "event_id": "fish",
                    "interaction_ids": ["charge"],
                    "counter_attack_interaction_ids": ["hide"],
                    "success_effects": [{"type": "gain_neurons", "amount": 1}],
                    "counter_attack_effects": [{"type": "gain_energy", "amount": 2}],
                    "failure_effects": [],
                }
            },
            "interactions": {"charge": {"id": "charge", "name": "Charge"}, "hide": {"id": "hide", "name": "Hide"}},
        }
        state["tiles"] = {"1A": [{"instance_id": "tile_fish", "tile_id": "fish-tile", "face_up": True}]}
        state["interaction"] = {
            "tile_instance_id": "tile_fish",
            "tile_id": "fish-tile",
            "node_id": "1A",
            "initiator_capability_id": "force",
            "played_cards": [{"card_id": "charge_card", "interaction_id": "charge", "interaction_ids": ["charge"], "capability_id": "force"}],
        }
        state["capabilities"]["camouflage"]["hand"] = [
            {"card_id": "hide_card", "interaction_id": "hide", "interaction_ids": ["hide"], "owner_capability_id": "camouflage"}
        ]

        result = await send_command(
            service,
            user,
            room,
            command_id="cmd_counter_auto",
            expected_version=1,
            command_type="resolve_interaction",
            payload={"capability_id": "camouflage", "auto_select_cards": True},
        )

        assert result["ok"] is True
        assert result["events"][0]["counter_success"] is True
        assert result["projection"]["poulpita"]["neurons"] == 1
        assert result["projection"]["poulpita"]["energy"] == 5
        assert result["projection"]["capabilities"]["camouflage"]["hand"] == []

    run(scenario())


def test_bot_support_plan_draws_with_auto_discard_for_counter_attack_when_hand_is_full():
    async def scenario():
        service = GameRoomService()
        user = User(id="user_1", username="Player One")
        room = await service.create_room(user=user, mode="solo_with_bots", game_type="goldfish", human_ability_id="force")
        await service.enqueue_game_command(
            room_id=room["id"],
            user=user,
            command={
                "command_id": "cmd_start_counter_draw_plan",
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
        state["capabilities"]["force"]["actions_taken_this_control"] = state["capabilities"]["force"]["max_actions_per_control"]
        state["capabilities"]["camouflage"]["pa"] = 1
        state["capabilities"]["camouflage"]["current_max_cards_in_hand"] = 2
        state["capabilities"]["camouflage"]["hand"] = [
            {"card_id": "junk_1", "interaction_id": "ink", "interaction_ids": ["ink"], "owner_capability_id": "camouflage"},
            {"card_id": "junk_2", "interaction_id": "analyse", "interaction_ids": ["analyse"], "owner_capability_id": "camouflage"},
        ]
        state["capabilities"]["camouflage"]["draw_pile"] = [
            {"card_id": "future_hide", "interaction_id": "hide", "interaction_ids": ["hide"], "owner_capability_id": "camouflage"}
        ]
        state["tile_catalog"] = {
            "categories": {"threat": {"id": "threat", "name": "Threat", "compulsory_on_same_node": True}},
            "events": {"fish": {"id": "fish", "name": "Big fish", "category_id": "threat"}},
            "tiles": {"fish-tile": {"id": "fish-tile", "event_id": "fish", "interaction_ids": ["charge"], "counter_attack_interaction_ids": ["hide"]}},
            "interactions": {"charge": {"id": "charge", "name": "Charge"}, "hide": {"id": "hide", "name": "Hide"}},
        }
        state["interaction"] = {
            "tile_instance_id": "tile_fish",
            "tile_id": "fish-tile",
            "node_id": "1A",
            "initiator_capability_id": "force",
            "played_cards": [{"card_id": "charge_card", "interaction_id": "charge", "interaction_ids": ["charge"], "capability_id": "force"}],
        }

        plans = await service.get_bot_plans(room_id=room["id"], user=user)
        plan = next(plan for plan in plans["proposals"] if plan["proposer_ability_id"] == "camouflage")
        draw_step = next(step for step in plan["plan_chain"] if step.get("public_command", {}).get("type") == "draw_action_card")

        assert draw_step["public_command"]["payload"]["auto_discard_card"] is True
        assert "future_hide" not in str(plans)

    run(scenario())


def test_bot_plans_continue_when_only_intelligence_has_control_left():
    async def scenario():
        service = GameRoomService()
        user = User(id="user_1", username="Player One")
        room = await service.create_room(user=user, mode="solo_with_bots", game_type="goldfish", human_ability_id="force")
        await service.enqueue_game_command(
            room_id=room["id"],
            user=user,
            command={
                "command_id": "cmd_start_only_intelligence_left",
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
        state["capabilities"]["force"]["actions_taken_this_control"] = state["capabilities"]["force"]["max_actions_per_control"]
        for ability_id, capability in state["capabilities"].items():
            if ability_id not in {"force", "intelligence"}:
                capability["control_takes_this_night"] = capability["max_control_takes_per_night"]
        state["capabilities"]["intelligence"]["control_takes_this_night"] = 0

        plans = await service.get_bot_plans(room_id=room["id"], user=user)

        assert plans["status"] == "awaiting_selection"
        assert any(
            step.get("public_command", {}).get("type") == "take_control"
            and step.get("public_command", {}).get("payload", {}).get("capability_id") == "intelligence"
            for plan in plans["proposals"]
            for step in plan["plan_chain"]
        )

    run(scenario())


def test_bot_plans_prioritize_ending_night_at_shelter_when_late():
    async def scenario():
        service = GameRoomService()
        user = User(id="user_1", username="Player One")
        room = await service.create_room(user=user, mode="solo_with_bots", game_type="goldfish", human_ability_id="force")
        await service.enqueue_game_command(
            room_id=room["id"],
            user=user,
            command={
                "command_id": "cmd_start_late_shelter_plan",
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
        state["night_time_spent"] = 23
        state["poulpita"]["node_id"] = "1A"
        state["shelters"] = {"1A": {"count": 1, "seashells": 0, "secure": False}}

        plans = await service.get_bot_plans(room_id=room["id"], user=user)

        assert plans["proposals"][0]["plan_id"] == "end_night_force"
        assert plans["proposals"][0]["plan_chain"][0]["public_command"]["type"] == "end_night"

    run(scenario())


def test_shelter_proximity_becomes_more_valuable_as_night_gets_later():
    state = _goldfish_state("room_late_shelter_value", level_id="test-level", mode="bots_only")
    state["phase"] = "night_action"
    state["active_capability_id"] = "force"
    state["shelters"] = {"1D": {"count": 1, "seashells": 0, "secure": False}}
    state["night_time_spent"] = int(state.get("night_shelter_available_at") or 16) - 1
    early_near, _entries, _distance = bot_planner._node_followup_score(state, "1C", "force")
    early_far, _entries, _distance = bot_planner._node_followup_score(state, "1B", "force")

    state["night_time_spent"] = int(state["night_time_total"]) - 2
    late_near, _entries, _distance = bot_planner._node_followup_score(state, "1C", "force")
    late_far, _entries, _distance = bot_planner._node_followup_score(state, "1B", "force")

    assert late_near - late_far > early_near - early_far


def test_safe_shelter_route_avoids_known_compulsory_nodes():
    state = _goldfish_state("room_safe_shelter_route", level_id="test-level", mode="bots_only")
    state["map"]["adjacency"] = {
        "start": ["shortcut", "safe-a"],
        "shortcut": ["start", "shelter"],
        "safe-a": ["start", "safe-b"],
        "safe-b": ["safe-a", "shelter"],
        "shelter": ["shortcut", "safe-b"],
    }
    state["poulpita"]["node_id"] = "start"
    state["shelters"] = {"shelter": {"count": 1, "seashells": 0, "secure": False}}
    state["tile_catalog"]["categories"] = {
        "threat": {"id": "threat", "name": "Threat", "compulsory_on_same_node": True}
    }
    state["tile_catalog"]["events"] = {
        "danger": {"id": "danger", "name": "Danger", "category_id": "threat"}
    }
    state["tile_catalog"]["tiles"] = {
        "blocker": {"id": "blocker", "name": "Blocker", "event_id": "danger"}
    }
    state["tiles"] = {
        "shortcut": [{"instance_id": "known_blocker", "tile_id": "blocker", "face_up": True}]
    }

    route = bot_planner._safe_route_to_closest_shelter(state, "start")

    assert route == {
        "shelter_node_id": "shelter",
        "path": ["start", "safe-a", "safe-b", "shelter"],
        "distance": 3,
    }


def test_late_shelter_return_uses_blocked_route_instead_of_optional_interaction():
    state = _goldfish_state("room_blocked_shelter_return", level_id="test-level", mode="bots_only")
    state["phase"] = "night_action"
    state["active_capability_id"] = "force"
    state["map"]["adjacency"] = {
        "start": ["blocked"],
        "blocked": ["start", "shelter"],
        "shelter": ["blocked"],
    }
    state["poulpita"]["node_id"] = "start"
    state["shelters"] = {"shelter": {"count": 1, "seashells": 0, "secure": False}}
    state["night_time_spent"] = 12
    state["night_shelter_available_at"] = 16
    state["capabilities"]["force"]["pa"] = 5
    state["capabilities"]["force"]["initiates_event_ids"] = ["optional-event"]
    state["tile_catalog"] = {
        **state["tile_catalog"],
        "categories": {
            "prey": {"id": "prey", "name": "Prey", "compulsory_on_same_node": False},
            "threat": {"id": "threat", "name": "Threat", "compulsory_on_same_node": True},
        },
        "events": {
            "optional-event": {"id": "optional-event", "name": "Crab", "category_id": "prey"},
            "blocker-event": {"id": "blocker-event", "name": "Shark", "category_id": "threat"},
        },
        "tiles": {
            "optional-tile": {"id": "optional-tile", "event_id": "optional-event", "interaction_ids": []},
            "blocker-tile": {"id": "blocker-tile", "event_id": "blocker-event", "interaction_ids": []},
        },
    }
    state["tiles"] = {
        "start": [{"instance_id": "optional-instance", "tile_id": "optional-tile", "face_up": True}],
        "blocked": [{"instance_id": "blocker-instance", "tile_id": "blocker-tile", "face_up": True}],
    }

    context = bot_planner._shelter_return_context(state)
    candidates = bot_planner._local_orchestrator_night_candidates(state)
    commands = [bot_planner._orchestrator_command(candidate) for candidate in candidates]

    assert context["route_is_safe"] is False
    assert context["route"]["path"] == ["start", "blocked", "shelter"]
    assert commands == [
        {"type": "move_poulpita", "payload": {"capability_id": "force", "target_node_id": "blocked"}}
    ]


def test_local_orchestrator_returns_toward_safe_shelter_before_end_night_threshold():
    state = _goldfish_state("room_shelter_return_window", level_id="test-level", mode="bots_only")
    state["phase"] = "night_action"
    state["active_capability_id"] = "force"
    state["poulpita"]["node_id"] = "1A"
    state["shelters"] = {"1D": {"count": 1, "seashells": 0, "secure": False}}
    state["tiles"] = {}
    state["night_time_spent"] = 12
    state["night_shelter_available_at"] = 16
    state["capabilities"]["force"]["pa"] = 5
    state["capabilities"]["force"]["actions_taken_this_control"] = 0

    context = bot_planner._shelter_return_context(state)
    candidates = bot_planner._local_orchestrator_night_candidates(state)
    commands = [bot_planner._orchestrator_command(candidate) for candidate in candidates]

    assert context["should_return"] is True
    assert context["next_node_id"] == "1B"
    assert commands == [
        {"type": "move_poulpita", "payload": {"capability_id": "force", "target_node_id": "1B"}}
    ]


def test_local_orchestrator_does_not_start_optional_interaction_inside_return_margin():
    state = _goldfish_state("room_optional_at_return_margin", level_id="test-level", mode="bots_only")
    state["phase"] = "night_action"
    state["active_capability_id"] = "force"
    state["poulpita"]["node_id"] = "1C"
    state["shelters"] = {"1D": {"count": 1, "seashells": 0, "secure": False}}
    state["night_time_spent"] = 13
    state["night_shelter_available_at"] = 16
    state["capabilities"]["force"]["pa"] = 5
    state["capabilities"]["force"]["initiates_event_ids"] = ["optional-event"]
    state["tile_catalog"] = {
        **state["tile_catalog"],
        "categories": {"prey": {"id": "prey", "name": "Prey", "compulsory_on_same_node": False}},
        "events": {"optional-event": {"id": "optional-event", "name": "Crab", "category_id": "prey"}},
        "tiles": {
            "optional-tile": {
                "id": "optional-tile",
                "event_id": "optional-event",
                "interaction_ids": [],
            }
        },
    }
    state["tiles"] = {
        "1C": [{"instance_id": "optional-instance", "tile_id": "optional-tile", "face_up": True}]
    }

    context = bot_planner._shelter_return_context(state)
    candidates = bot_planner._local_orchestrator_night_candidates(state)
    commands = [bot_planner._orchestrator_command(candidate) for candidate in candidates]

    assert context["return_start"] == 13
    assert context["safety_margin"] == 2
    assert commands == [
        {"type": "move_poulpita", "payload": {"capability_id": "force", "target_node_id": "1D"}}
    ]


def test_optimistic_rollout_does_not_stop_for_optional_tile_during_shelter_return():
    state = _goldfish_state("room_rollout_shelter_return", level_id="test-level", mode="bots_only")
    state["phase"] = "night_action"
    state["active_capability_id"] = "force"
    state["poulpita"]["node_id"] = "1A"
    state["shelters"] = {"1D": {"count": 1, "seashells": 0, "secure": False}}
    state["night_time_spent"] = 12
    state["night_shelter_available_at"] = 16
    state["capabilities"]["force"]["pa"] = 5
    state["capabilities"]["force"]["initiates_event_ids"] = ["optional-event"]
    state["tile_catalog"]["categories"] = {
        "prey": {"id": "prey", "name": "Prey", "compulsory_on_same_node": False}
    }
    state["tile_catalog"]["events"] = {
        "optional-event": {"id": "optional-event", "name": "Optional", "category_id": "prey"}
    }
    state["tile_catalog"]["tiles"] = {
        "optional-tile": {"id": "optional-tile", "name": "Optional", "event_id": "optional-event"}
    }
    state["tiles"] = {
        "1A": [{"instance_id": "optional-1", "tile_id": "optional-tile", "face_up": True}]
    }

    commands, interactions, label = bot_planner._rollout_next_commands(state, "force")

    assert commands == [
        {"type": "move_poulpita", "payload": {"capability_id": "force", "target_node_id": "1B"}}
    ]
    assert interactions == []
    assert label == "safe shelter route via 1B"


def test_simulated_no_actions_loss_has_extreme_negative_value():
    state = _goldfish_state("room_simulated_loss_value", level_id="test-level", mode="bots_only")
    state["phase"] = "night_action"
    state["active_capability_id"] = "force"
    for capability in state["capabilities"].values():
        capability["control_takes_this_night"] = capability["max_control_takes_per_night"]
    active = state["capabilities"]["force"]
    active["actions_taken_this_control"] = active["max_actions_per_control"] - 1

    bot_planner._simulate_public_command(
        state,
        {"type": "collect_action_points", "payload": {"capability_id": "force"}},
    )

    assert state["phase"] == "game_over"
    assert state["game_outcome"] == "lost"
    assert bot_planner._global_state_score(state) == -100000


def test_bot_day_plans_include_size_growth_and_ability_upgrades():
    async def scenario():
        service = GameRoomService()
        user = User(id="user_1", username="Player One")
        room = await service.create_room(user=user, mode="solo_with_bots", game_type="goldfish", human_ability_id="force")
        await service.enqueue_game_command(
            room_id=room["id"],
            user=user,
            command={
                "command_id": "cmd_start_day_upgrade_plans",
                "room_id": room["id"],
                "actor_user_id": user.id,
                "actor_seat_id": "goldfish",
                "expected_version": 0,
                "type": "start_goldfish_game",
                "payload": {},
            },
        )
        state = service._memory_states[room["id"]]
        state["phase"] = "day"
        state["poulpita"]["energy"] = 7
        state["poulpita"]["neurons"] = 4
        state["objectives"] = [{"type": "increase_size", "count": 1}]
        state["tile_catalog"]["poulpita_panel"] = {"sizes": [{"amount": 1, "unit": "kg", "energy_cost": 0}, {"amount": 2, "unit": "kg", "energy_cost": 2}]}
        state["tile_catalog"]["bot_settings"] = {"min_energy_after_size_upgrade": 4}
        for capability in state["capabilities"].values():
            capability["hand_size_upgrades"] = []
        state["capabilities"]["force"]["hand_size_upgrades"] = [{"cost_resource": "neurons", "cost": 2, "hand_size_bonus": 1}]

        plans = await service.get_bot_plans(room_id=room["id"], user=user)
        plan_ids = {plan["plan_id"] for plan in plans["proposals"]}

        assert "day_buy_poulpita_size" in plan_ids
        assert "day_buy_upgrade_force_0" in plan_ids

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
        assert projection["capabilities"][DEFAULT_ACTIVE_CAPABILITY_ID]["pa"] == 5
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
                        "interaction_ids": ["charge"],
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
                        "interaction_ids": ["charge"],
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
                "crab-tile": {"id": "crab-tile", "event_id": "crab", "interaction_ids": ["charge"], "failure_effects": [{"type": "remove_preys", "amount": None, "category_id": "prey"}]},
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


def test_octopus_token_hydrates_tile_definition_and_enforces_initiators(monkeypatch):
    async def scenario():
        monkeypatch.setattr(
            "backend.app.game_room_service.get_game_content_catalog",
            lambda: {
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
            },
        )
        service, user, room, _start = await create_started_room()
        state = service._memory_states[room["id"]]
        state["phase"] = "night_action"
        state["active_capability_id"] = "force"
        state["capabilities"]["force"]["pa"] = 2
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
        state["active_capability_id"] = "force"
        state["capabilities"]["force"]["pa"] = 2
        state["tile_catalog"] = {"categories": {}, "tiles": {}, "events": {}, "interactions": {}}
        state["tiles"] = {"1A": [{"instance_id": "octopus_legacy", "tile_id": "octopus", "face_up": True, "token_type": "octopus"}]}

        accepted_legacy = await send_command(
            service,
            user,
            room,
            command_id="cmd_start_octopus_legacy",
            expected_version=1,
            command_type="start_interaction",
            payload={"capability_id": "force", "tile_instance_id": "octopus_legacy"},
        )

        assert accepted_legacy["ok"] is True
        assert accepted_legacy["projection"]["interaction"]["tile_id"] == "__octopus_token__"
        assert accepted_legacy["projection"]["tiles"]["1A"][0]["tile_id"] == "__octopus_token__"

        service, user, room, _start = await create_started_room()
        state = service._memory_states[room["id"]]
        state["phase"] = "night_action"
        state["active_capability_id"] = "agility"
        state["capabilities"]["agility"]["pa"] = 2
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
        state["capabilities"][DEFAULT_ACTIVE_CAPABILITY_ID]["pa"] = 4
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
        resolved_optional = await send_command(
            service,
            user,
            room,
            command_id="cmd_resolve_optional_high",
            expected_version=2,
            command_type="resolve_interaction",
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
        assert resolved_optional["ok"] is True
        assert accepted_compulsory["ok"] is True
        assert accepted_compulsory["projection"]["interaction"]["tile_instance_id"] == "tile_shark_low"

    run(scenario())


def test_latest_tile_priority_metadata_allows_high_priority_optional_interaction(monkeypatch):
    async def scenario():
        service, user, room, _start = await create_started_room()
        state = service._memory_states[room["id"]]
        state["phase"] = "night_action"
        state["active_capability_id"] = DEFAULT_ACTIVE_CAPABILITY_ID
        state["capabilities"][DEFAULT_ACTIVE_CAPABILITY_ID]["pa"] = 2
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
        assert resolved["projection"]["objective_progress"]["found_shelter"] is False
        assert ended["ok"] is True
        assert ended["projection"]["phase"] == "day"

    run(scenario())


def test_find_shelter_objective_completes_only_when_poulpita_moves_onto_it():
    async def scenario():
        service, user, room, _start = await create_started_room()
        state = service._memory_states[room["id"]]
        state["phase"] = "night_action"
        state["active_capability_id"] = DEFAULT_ACTIVE_CAPABILITY_ID
        state["capabilities"][DEFAULT_ACTIVE_CAPABILITY_ID]["pa"] = 1
        state["shelters"] = {"1B": {"count": 1, "seashells": 0, "secure": False}}
        state["objectives"] = [{"id": "find", "type": "find_shelter"}]
        state["objective_progress"]["found_shelter"] = False

        moved = await send_command(
            service,
            user,
            room,
            command_id="cmd_find_shelter_by_moving",
            expected_version=1,
            command_type="move_poulpita",
            payload={"capability_id": DEFAULT_ACTIVE_CAPABILITY_ID, "target_node_id": "1B"},
        )

        assert moved["ok"] is True
        assert moved["projection"]["objective_progress"]["found_shelter"] is True
        assert moved["projection"]["phase"] == "game_over"

    run(scenario())


def test_end_night_is_blocked_by_compulsory_tiles_and_octopus_tokens():
    async def scenario():
        service, user, room, _start = await create_started_room()
        state = service._memory_states[room["id"]]
        state["phase"] = "night_action"
        state["active_capability_id"] = DEFAULT_ACTIVE_CAPABILITY_ID
        state["night_time_spent"] = 16
        state["shelters"] = {"1A": {"count": 1, "seashells": 0, "secure": False}}
        state["tile_catalog"] = {
            "tiles": {"threat-tile": {"id": "threat-tile", "event_id": "threat-event"}},
            "events": {"threat-event": {"id": "threat-event", "category_id": "threat"}},
            "categories": {"threat": {"id": "threat", "compulsory_on_same_node": True}},
        }
        state["tiles"] = {"1A": [{"instance_id": "threat-instance", "tile_id": "threat-tile", "face_up": True}]}

        compulsory_blocked = await send_command(
            service,
            user,
            room,
            command_id="cmd_end_night_compulsory_blocked",
            expected_version=1,
            command_type="end_night",
            payload={"capability_id": DEFAULT_ACTIVE_CAPABILITY_ID},
        )

        state["tiles"] = {
            "1A": [
                {
                    "instance_id": "octopus-instance",
                    "tile_id": "__octopus_token__",
                    "token_type": "octopus",
                    "face_up": True,
                }
            ]
        }
        octopus_blocked = await send_command(
            service,
            user,
            room,
            command_id="cmd_end_night_octopus_blocked",
            expected_version=1,
            command_type="end_night",
            payload={"capability_id": DEFAULT_ACTIVE_CAPABILITY_ID},
        )

        assert compulsory_blocked["ok"] is False
        assert compulsory_blocked["reason"] == "night_end_blocked"
        assert octopus_blocked["ok"] is False
        assert octopus_blocked["reason"] == "night_end_blocked"

    run(scenario())


def test_bot_stores_shells_until_shelter_is_secure_but_keeps_one_carried():
    state = _goldfish_state("room_bot_secure_shelter", level_id="test-level", mode="bots_only")
    state["phase"] = "day"
    current_node_id = state["poulpita"]["node_id"]
    state["poulpita"]["seashells"] = 4
    state["shelters"] = {current_node_id: {"count": 1, "seashells": 0, "secure": False}}

    for _index in range(3):
        candidates = bot_planner._local_orchestrator_day_candidates(state)
        assert candidates[0]["commands"][0]["type"] == "move_seashell_to_shelter"
        bot_planner._simulate_public_command(state, candidates[0]["commands"][0])

    assert state["poulpita"]["seashells"] == 1
    assert state["shelters"][current_node_id]["seashells"] == 3
    assert state["shelters"][current_node_id]["secure"] is True
    assert all(
        candidate["commands"][0]["type"] != "move_seashell_to_shelter"
        for candidate in bot_planner._local_orchestrator_day_candidates(state)
    )


def test_end_night_is_free_and_day_upgrades_stack_before_next_night():
    async def scenario():
        service, user, room, _start = await create_started_room()
        state = service._memory_states[room["id"]]
        state["phase"] = "night_action"
        state["active_capability_id"] = DEFAULT_ACTIVE_CAPABILITY_ID
        state["night_time_spent"] = 16
        state["shelters"] = {"1A": 1}
        state["poulpita"]["neurons"] = 3
        expected_initial_ap = {}
        for index, (capability_id, configured_capability) in enumerate(state["capabilities"].items()):
            configured_capability["initial_ap"] = index
            configured_capability["pa"] = 99
            expected_initial_ap[capability_id] = index
        capability = state["capabilities"][DEFAULT_ACTIVE_CAPABILITY_ID]
        capability["pa"] = 0
        capability["initial_ap"] = 7
        expected_initial_ap[DEFAULT_ACTIVE_CAPABILITY_ID] = 7
        capability["control_takes_this_night"] = 2
        capability["actions_taken_this_control"] = int(capability["max_actions_per_control"])
        capability["current_max_cards_in_hand"] = 3
        capability["hand"] = capability["hand"][:1]
        capability["discard"] = capability["draw_pile"][:4]
        capability["draw_pile"] = capability["draw_pile"][4:]
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
        assert night_capability["pa"] == 7
        assert {
            capability_id: projected_capability["pa"]
            for capability_id, projected_capability in night["projection"]["capabilities"].items()
        } == expected_initial_ap
        assert night_capability["control_takes_this_night"] == 0
        assert len(night_capability["hand"]) == min(8, len(night_capability["hand"]) + len(night_capability["draw_pile"]))
        assert night_capability["discard"] == []

    run(scenario())


def test_planner_simulation_resets_ap_to_initial_value_when_day_ends():
    state = _goldfish_state("room_simulated_night_reset", level_id="test-level", mode="bots_only")
    state["phase"] = "day"
    state["day_index"] = 1
    state["max_nights"] = 5
    for index, capability in enumerate(state["capabilities"].values()):
        capability["initial_ap"] = index
        capability["pa"] = 99

    bot_planner._simulate_public_command(state, {"type": "end_day", "payload": {}})

    assert state["phase"] == "night_idle"
    assert [capability["pa"] for capability in state["capabilities"].values()] == list(
        range(len(state["capabilities"]))
    )


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
        capability["applied_deck_exchange_upgrade_indices"] = []
        capability["deck"] = [{"interaction_id": "charge", "count": 1}]
        capability["draw_pile"] = []
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
        duplicate = await send_command(
            service,
            user,
            room,
            command_id="cmd_buy_deck_exchange_again",
            expected_version=2,
            command_type="buy_hand_size_upgrade",
            payload={"capability_id": DEFAULT_ACTIVE_CAPABILITY_ID, "upgrade_index": 0},
        )
        night = await send_command(
            service,
            user,
            room,
            command_id="cmd_end_day_after_deck_exchange",
            expected_version=2,
            command_type="end_day",
        )

        next_capability = result["projection"]["capabilities"][DEFAULT_ACTIVE_CAPABILITY_ID]
        night_capability = night["projection"]["capabilities"][DEFAULT_ACTIVE_CAPABILITY_ID]
        assert result["ok"] is True
        assert result["projection"]["poulpita"]["neurons"] == 1
        assert next_capability["purchased_hand_size_upgrade_indices"] == [0]
        assert next_capability["applied_deck_exchange_upgrade_indices"] == [0]
        assert duplicate["ok"] is False
        assert duplicate["reason"] == "upgrade_already_bought"
        assert night["ok"] is True
        night_cards = night_capability["hand"] + night_capability["draw_pile"]
        assert len(night_cards) == 1
        assert night_cards[0]["interaction_ids"] == ["charge", "hide"]
        assert night_cards[0]["upgraded"] is True

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


def test_ap_persists_and_final_day_ends_in_loss():
    async def scenario():
        service, user, room, _start = await create_started_room()
        state = service._memory_states[room["id"]]
        state["phase"] = "night_action"
        state["active_capability_id"] = DEFAULT_ACTIVE_CAPABILITY_ID
        state["day_index"] = 2
        state["max_nights"] = 2
        state["size_deadline_night"] = 99
        state["night_time_spent"] = 16
        state["shelters"] = {"1A": {"count": 1, "seashells": 0, "secure": False}}
        state["capabilities"][DEFAULT_ACTIVE_CAPABILITY_ID]["pa"] = 7

        day = await send_command(
            service,
            user,
            room,
            command_id="cmd_final_day",
            expected_version=1,
            command_type="end_night",
            payload={"capability_id": DEFAULT_ACTIVE_CAPABILITY_ID},
        )
        lost = await send_command(
            service,
            user,
            room,
            command_id="cmd_final_day_end",
            expected_version=2,
            command_type="end_day",
        )

        assert day["ok"] is True
        assert day["projection"]["phase"] == "day"
        assert day["projection"]["capabilities"][DEFAULT_ACTIVE_CAPABILITY_ID]["pa"] == 7
        assert lost["ok"] is True
        assert lost["projection"]["phase"] == "game_over"
        assert lost["projection"]["game_outcome"] == "lost"
        assert lost["events"][0]["reason"] == "maximum_nights_reached"

    run(scenario())


def test_interaction_support_requires_initiator_confirmation_and_not_initiative():
    async def scenario():
        service, user, room, _start = await create_started_room()
        state = service._memory_states[room["id"]]
        state["phase"] = "night_action"
        state["active_capability_id"] = "force"
        state["capabilities"]["force"]["initiates_event_ids"] = ["fish"]
        state["tile_catalog"] = {
            "categories": {"threat": {"id": "threat", "compulsory_on_same_node": True}},
            "events": {"fish": {"id": "fish", "name": "Fish", "category_id": "threat"}},
            "interactions": {
                "charge": {"id": "charge", "name": "Charge"},
                "hide": {"id": "hide", "name": "Hide"},
                "analyse": {"id": "analyse", "name": "Analyse"},
            },
            "tiles": {
                "fish-tile": {
                    "id": "fish-tile",
                    "event_id": "fish",
                    "interaction_ids": ["charge", "hide", "analyse"],
                    "success_effects": [{"type": "gain_neurons", "amount": 1}],
                }
            },
        }
        state["tiles"] = {"1A": [{"instance_id": "fish-instance", "tile_id": "fish-tile", "face_up": True}]}
        state["capabilities"]["force"]["hand"] = [
            {"card_id": "charge-card", "interaction_id": "charge", "interaction_ids": ["charge"], "owner_capability_id": "force"},
            {"card_id": "ink-card", "interaction_id": "ink", "interaction_ids": ["ink"], "owner_capability_id": "force"},
        ]
        state["capabilities"]["camouflage"]["hand"] = [{"card_id": "hide-card", "interaction_id": "hide", "interaction_ids": ["hide"], "owner_capability_id": "camouflage"}]
        state["capabilities"]["intelligence"]["hand"] = [{"card_id": "analyse-card", "interaction_id": "analyse", "interaction_ids": ["analyse"], "owner_capability_id": "intelligence"}]

        started = await send_command(
            service, user, room, command_id="cmd_support_start", expected_version=1,
            command_type="start_interaction", payload={"capability_id": "force", "tile_instance_id": "fish-instance"},
        )
        early_support = await send_command(
            service, user, room, command_id="cmd_support_early", expected_version=2,
            command_type="resolve_interaction", payload={"capability_id": "camouflage", "card_ids": ["hide-card"]},
        )
        confirmed = await send_command(
            service, user, room, command_id="cmd_support_confirm", expected_version=2,
            command_type="resolve_interaction", payload={"capability_id": "force", "card_ids": ["charge-card"], "confirm_only": True},
        )
        first_support = await send_command(
            service, user, room, command_id="cmd_support_first", expected_version=3,
            command_type="resolve_interaction", payload={"capability_id": "camouflage", "card_ids": ["hide-card"], "confirm_only": True},
        )
        stale_support = await send_command(
            service, user, room, command_id="cmd_support_stale", expected_version=3,
            command_type="resolve_interaction", payload={"capability_id": "intelligence", "card_ids": ["analyse-card"]},
        )
        completed = await send_command(
            service, user, room, command_id="cmd_support_complete", expected_version=4,
            command_type="resolve_interaction", payload={"capability_id": "intelligence", "card_ids": ["analyse-card"], "confirm_only": True},
        )
        extra_card = await send_command(
            service, user, room, command_id="cmd_support_extra", expected_version=5,
            command_type="resolve_interaction", payload={"capability_id": "force", "card_ids": ["ink-card"], "confirm_only": True},
        )
        resolved = await send_command(
            service, user, room, command_id="cmd_support_resolve", expected_version=5,
            command_type="resolve_interaction", payload={"capability_id": "force"},
        )

        assert started["projection"]["interaction"]["initiator_confirmed"] is False
        assert early_support["reason"] == "initiator_confirmation_required"
        assert confirmed["projection"]["interaction"]["initiator_confirmed"] is True
        assert first_support["ok"] is True
        assert stale_support["reason"] == "state_version_conflict"
        assert any(card["card_id"] == "analyse-card" for card in stale_support["projection"]["capabilities"]["intelligence"]["hand"])
        assert completed["ok"] is True
        assert completed["projection"]["interaction"] is not None
        assert completed["events"][0]["type"] == "interaction_cards_confirmed"
        assert extra_card["reason"] == "invalid_selected_cards"
        assert resolved["projection"]["interaction"] is None
        assert resolved["projection"]["poulpita"]["neurons"] == 1
        assert resolved["projection"]["active_capability_id"] == "force"

    run(scenario())


def test_special_power_spends_configured_resources_and_propulsion_cannot_return_to_start():
    async def scenario():
        service, user, room, _start = await create_started_room()
        state = service._memory_states[room["id"]]
        state["phase"] = "night_action"
        state["active_capability_id"] = "force"
        state["poulpita"]["neurons"] = 2
        state["tile_catalog"]["action_costs"] = {
            "special_power": {"ap_cost": 2, "time_cost": 2, "neuron_cost": 1}
        }

        force = await send_command(
            service, user, room, command_id="cmd_force_special", expected_version=1,
            command_type="use_special_power", payload={"capability_id": "force"},
        )
        next_state = service._memory_states[room["id"]]
        next_state["active_capability_id"] = "propulsion"
        next_state["poulpita"]["node_id"] = "1C"
        next_state["poulpita_starting_node_id"] = "1A"
        next_state["capabilities"]["propulsion"]["pa"] = 5
        rejected = await send_command(
            service, user, room, command_id="cmd_propulsion_home", expected_version=2,
            command_type="use_special_power", payload={"capability_id": "propulsion", "path": ["1B", "1A"]},
        )

        assert force["ok"] is True
        assert force["projection"]["capabilities"]["force"]["pa"] == 3
        assert force["projection"]["poulpita"]["neurons"] == 1
        assert force["projection"]["night_time_spent"] == 2
        assert next_state["force_reduces_next_interaction"] is True
        assert rejected["reason"] == "propulsion_starting_node_forbidden"
        assert rejected["projection"]["poulpita"]["neurons"] == 1

    run(scenario())


def test_courtship_retry_draws_again_and_declining_blocks_until_movement():
    async def scenario():
        service, user, room, _start = await create_started_room()
        state = service._memory_states[room["id"]]
        state["phase"] = "night_action"
        state["active_capability_id"] = "force"
        state["poulpita"]["size_index"] = 3
        state["poulpita"]["energy"] = 8
        state["courtship_min_size_index"] = 3
        state["courtship_min_energy"] = 8
        state["tile_catalog"] = {
            **state["tile_catalog"],
            "categories": {"__courtship_category__": {"id": "__courtship_category__", "compulsory_on_same_node": False}},
            "events": {"__courtship_event__": {"id": "__courtship_event__", "category_id": "__courtship_category__"}},
            "interactions": {"dance": {"id": "dance", "name": "Dance"}},
            "tiles": {"__courtship_token__": {"id": "__courtship_token__", "event_id": "__courtship_event__", "token_type": "courtship", "interaction_ids": []}},
            "courtship_cards": {"dance-card": {"id": "dance-card", "name": "Dance", "interaction_ids": ["dance"]}},
        }
        state["tiles"] = {
            "1A": [],
            "1B": [{"instance_id": "courtship-1", "tile_id": "__courtship_token__", "token_type": "courtship", "face_up": True}],
        }

        moved = await send_command(
            service, user, room, command_id="cmd_move_to_courtship", expected_version=1,
            command_type="move_poulpita", payload={"capability_id": "force", "target_node_id": "1B"},
        )
        confirmed = await send_command(
            service, user, room, command_id="cmd_confirm_empty_courtship", expected_version=2,
            command_type="resolve_interaction", payload={"capability_id": "force", "card_ids": []},
        )
        retried = await send_command(
            service, user, room, command_id="cmd_retry_courtship", expected_version=3,
            command_type="fail_interaction", payload={"spend_energy_to_retry": True},
        )
        blocked = await send_command(
            service, user, room, command_id="cmd_block_courtship", expected_version=4,
            command_type="fail_interaction", payload={"spend_energy_to_retry": False},
        )
        left = await send_command(
            service, user, room, command_id="cmd_leave_courtship", expected_version=5,
            command_type="move_poulpita", payload={"capability_id": "force", "target_node_id": "1A"},
        )

        assert moved["projection"]["interaction"]["courtship_card"]["id"] == "dance-card"
        assert confirmed["projection"]["interaction"]["initiator_confirmed"] is True
        assert retried["projection"]["poulpita"]["energy"] == 7
        assert retried["projection"]["interaction"]["initiator_confirmed"] is False
        assert blocked["projection"]["interaction"] is None
        assert blocked["projection"]["courtship_blocked_node_id"] == "1B"
        assert left["projection"]["courtship_blocked_node_id"] is None

    run(scenario())


def test_size_upgrade_uses_all_shelter_shell_discount_and_replaces_tiles():
    async def scenario():
        service, user, room, _start = await create_started_room()
        state = service._memory_states[room["id"]]
        state["phase"] = "day"
        state["poulpita"]["energy"] = 10
        state["poulpita"]["size_index"] = 0
        state["shelters"] = {"1A": {"count": 1, "seashells": 4, "secure": True}}
        state["tile_catalog"] = {
            **state["tile_catalog"],
            "poulpita_panel": {"sizes": [{"amount": 1, "unit": "kg", "energy_cost": 0}, {"amount": 2, "unit": "kg", "energy_cost": 3}]},
            "tiles": {"adult-tile": {"id": "adult-tile", "event_id": "adult", "interaction_ids": []}},
            "events": {"adult": {"id": "adult", "category_id": "prey"}},
        }
        state["level_layout"] = {
            "node_tile_counts": {node_id: (1 if node_id == "1A" else 0) for node_id in TEST_MAP["nodes"]},
            "node_group_ids": {node_id: "main" for node_id in TEST_MAP["nodes"]},
            "groups": [{"id": "main", "name": "Main", "tile_counts": {}}],
            "node_tokens": {},
        }
        state["level_tile_sets"] = [{"id": "adult", "size_index": 1, "groups": [{"id": "main", "name": "Main", "tile_counts": {"adult-tile": 1}}]}]
        state["tiles"] = {node_id: [] for node_id in TEST_MAP["nodes"]}

        result = await send_command(
            service, user, room, command_id="cmd_size_replace", expected_version=1,
            command_type="buy_poulpita_size",
        )

        assert result["ok"] is True
        assert result["projection"]["poulpita"]["energy"] == 9
        assert result["events"][0]["energy_cost"] == 1
        assert result["projection"]["tiles"]["1A"][0]["tile_id"] == "adult-tile"

    run(scenario())


def test_automatic_success_interaction_cannot_be_failed():
    async def scenario():
        service, user, room, _start = await create_started_room()
        state = service._memory_states[room["id"]]
        state["phase"] = "night_action"
        state["active_capability_id"] = DEFAULT_ACTIVE_CAPABILITY_ID
        state["tile_catalog"] = {
            "tiles": {
                "surprise-tile": {
                    "id": "surprise-tile",
                    "event_id": "surprise",
                    "interaction_ids": [],
                    "success_effects": [{"type": "draw_surprise_card"}],
                    "failure_effects": [],
                }
            },
            "events": {"surprise": {"id": "surprise", "category_id": "exploration"}},
            "interactions": {},
        }
        state["tiles"] = {
            "1A": [{"instance_id": "tile_surprise", "tile_id": "surprise-tile", "face_up": True}]
        }
        state["interaction"] = {
            "tile_instance_id": "tile_surprise",
            "tile_id": "surprise-tile",
            "node_id": "1A",
            "played_cards": [],
        }

        rejected = await send_command(
            service,
            user,
            room,
            command_id="cmd_fail_automatic_surprise",
            expected_version=1,
            command_type="fail_interaction",
        )

        assert rejected["ok"] is False
        assert rejected["reason"] == "automatic_interaction_cannot_fail"
        assert service._memory_states[room["id"]]["interaction"] is not None

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


def test_game_is_lost_when_active_ability_ends_actions_and_no_other_ability_can_take_control():
    async def scenario():
        service, user, room, _start = await create_started_room()
        state = service._memory_states[room["id"]]
        state["phase"] = "night_action"
        state["active_capability_id"] = DEFAULT_ACTIVE_CAPABILITY_ID
        active = state["capabilities"][DEFAULT_ACTIVE_CAPABILITY_ID]
        active["actions_taken_this_control"] = int(active["max_actions_per_control"]) - 1
        active["control_takes_this_night"] = 0
        for capability_id, capability in state["capabilities"].items():
            if capability_id != DEFAULT_ACTIVE_CAPABILITY_ID:
                capability["control_takes_this_night"] = capability["max_control_takes_per_night"]

        result = await send_command(
            service,
            user,
            room,
            command_id="cmd_last_available_action",
            expected_version=1,
            command_type="collect_action_points",
            payload={"capability_id": DEFAULT_ACTIVE_CAPABILITY_ID},
        )

        assert result["ok"] is True
        assert result["projection"]["phase"] == "game_over"
        finished_state = service._memory_states[room["id"]]
        assert finished_state["game_outcome"] == "lost"
        assert finished_state["game_over_reason"] == "no_controls_or_actions"

    run(scenario())


def test_game_continues_when_active_ability_ends_actions_and_another_can_take_control():
    async def scenario():
        service, user, room, _start = await create_started_room()
        state = service._memory_states[room["id"]]
        state["phase"] = "night_action"
        state["active_capability_id"] = DEFAULT_ACTIVE_CAPABILITY_ID
        active = state["capabilities"][DEFAULT_ACTIVE_CAPABILITY_ID]
        active["actions_taken_this_control"] = int(active["max_actions_per_control"]) - 1
        next_ability_id = next(capability_id for capability_id in state["capabilities"] if capability_id != DEFAULT_ACTIVE_CAPABILITY_ID)
        for capability_id, capability in state["capabilities"].items():
            capability["control_takes_this_night"] = (
                0 if capability_id == next_ability_id else capability["max_control_takes_per_night"]
            )

        result = await send_command(
            service,
            user,
            room,
            command_id="cmd_last_action_with_successor",
            expected_version=1,
            command_type="collect_action_points",
            payload={"capability_id": DEFAULT_ACTIVE_CAPABILITY_ID},
        )

        assert result["ok"] is True
        assert result["projection"]["phase"] == "night_action"
        assert service._memory_states[room["id"]].get("game_outcome") is None

    run(scenario())
