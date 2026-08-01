from __future__ import annotations

import json
import os
import random
import threading
import time
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .bots.planner import choose_bot_orchestrator_action, choose_fast_bot_orchestrator_action
from .game_content_service import get_level_config
from .game_room_service import (
    PHASE_FINISHED,
    PHASE_NIGHT_ACTION,
    PHASE_NIGHT_IDLE,
    CommandRejection,
    GameRoomService,
    _bot_room_config,
    _goldfish_state,
    _mark_game_lost_if_needed,
    _project_state,
)
from .server_models import User


REPLAY_FORMAT_VERSION = 1
REPLAYS_ROOT = Path(
    os.getenv(
        "BOT_REPLAYS_ROOT",
        str(Path(__file__).resolve().parents[1] / "data" / "replays"),
    )
)
_simulation_lock = threading.Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _replay_path(replay_id: str) -> Path:
    normalized = str(replay_id or "").strip()
    if not normalized or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for character in normalized):
        raise LookupError("Replay not found.")
    return REPLAYS_ROOT / f"{normalized}.json"


def _write_replay(payload: dict[str, Any]) -> None:
    REPLAYS_ROOT.mkdir(parents=True, exist_ok=True)
    destination = _replay_path(str(payload["id"]))
    temporary = destination.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=True, separators=(",", ":")), encoding="utf-8")
    temporary.replace(destination)


def _read_replay(replay_id: str) -> dict[str, Any]:
    path = _replay_path(replay_id)
    if not path.exists():
        raise LookupError("Replay not found.")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LookupError("Replay file is invalid.") from exc
    if not isinstance(payload, dict):
        raise LookupError("Replay file is invalid.")
    return payload


def _compact_projection(projection: dict[str, Any]) -> dict[str, Any]:
    compact = deepcopy(projection)
    compact.pop("map", None)
    compact.pop("tile_catalog", None)
    compact.pop("player_boards", None)  # Duplicates the capability objects; the client already derives this list.
    return compact


def _replay_summary(payload: dict[str, Any]) -> dict[str, Any]:
    metadata = payload.get("metadata") or {}
    return {
        "id": str(payload.get("id") or ""),
        "created_at": str(payload.get("created_at") or ""),
        "level_id": str(payload.get("level_id") or ""),
        "level_name": str(payload.get("level_name") or payload.get("level_id") or ""),
        "seed": int(payload.get("seed") or 0),
        "simulation_mode": str(payload.get("simulation_mode") or "fast"),
        "outcome": str(metadata.get("outcome") or "incomplete"),
        "game_over_reason": str(metadata.get("game_over_reason") or ""),
        "steps": int(metadata.get("steps") or 0),
        "duration_ms": int(metadata.get("duration_ms") or 0),
        "final_day": int(metadata.get("final_day") or 1),
        "final_energy": int(metadata.get("final_energy") or 0),
        "frame_count": len(payload.get("frames") or []),
    }


def list_bot_replays() -> list[dict[str, Any]]:
    if not REPLAYS_ROOT.exists():
        return []
    summaries = []
    for path in REPLAYS_ROOT.glob("*.json"):
        try:
            summaries.append(_replay_summary(json.loads(path.read_text(encoding="utf-8"))))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            continue
    return sorted(summaries, key=lambda entry: entry["created_at"], reverse=True)


def get_bot_replay(replay_id: str) -> dict[str, Any]:
    return _read_replay(replay_id)


def delete_bot_replay(replay_id: str) -> None:
    path = _replay_path(replay_id)
    if not path.exists():
        raise LookupError("Replay not found.")
    path.unlink()


def _frame(
    *,
    index: int,
    projection: dict[str, Any],
    command: dict[str, Any] | None,
    events: list[dict[str, Any]] | None = None,
    decision: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "index": index,
        "command": deepcopy(command),
        "events": deepcopy(events or []),
        "decision": {
            "plan_id": decision.get("plan_id"),
            "plan_title": decision.get("plan_title"),
            "score": decision.get("score"),
        } if decision else None,
        "projection": _compact_projection(projection),
    }


def _fallback_night_command(state: dict[str, Any]) -> dict[str, Any]:
    capabilities = state.get("capabilities") or {}
    active_id = str(state.get("active_capability_id") or "")
    active = capabilities.get(active_id) or {}
    if active_id and int(active.get("actions_taken_this_control") or 0) < int(active.get("max_actions_per_control") or 3):
        return {"type": "collect_action_points", "payload": {"capability_id": active_id}}
    for ability_id, capability in capabilities.items():
        if ability_id == active_id:
            continue
        if int(capability.get("control_takes_this_night") or 0) < int(capability.get("max_control_takes_per_night") or 3):
            return {"type": "take_control", "payload": {"capability_id": ability_id}}
    return {"type": "bot_no_actions_available", "payload": {}}


def run_bot_simulation(*, level_id: str, seed: int, max_steps: int = 2000, simulation_mode: str = "fast") -> dict[str, Any]:
    level = get_level_config(level_id)
    replay_id = f"replay_{uuid.uuid4().hex}"
    room_id = f"simulation_{uuid.uuid4().hex}"
    bot_config = _bot_room_config(mode="bots_only")
    user = User(id="backend_bot_simulator", username="Backend bot simulator", is_admin=True)
    room = {
        "id": room_id,
        "owner_user_id": user.id,
        "mode": "bots_only",
        "game_type": "goldfish",
        "level_id": level["id"],
        "bot_config": bot_config,
    }
    reducer = GameRoomService()
    started = time.perf_counter()
    random.seed(seed)
    state = _goldfish_state(room_id, level_id=level["id"], mode="bots_only", bot_config=bot_config)
    initial_projection = _project_state(state)
    frames = [_frame(index=0, projection=initial_projection, command=None, events=initial_projection.get("events") or [])]
    stop_reason = "game_finished"

    for step in range(1, max_steps + 1):
        if state.get("phase") == PHASE_FINISHED:
            break
        decision = (
            choose_bot_orchestrator_action(state)
            if simulation_mode == "full"
            else choose_fast_bot_orchestrator_action(state)
        )
        command_template = decision.get("command")
        if not isinstance(command_template, dict):
            if state.get("phase") in {PHASE_NIGHT_IDLE, PHASE_NIGHT_ACTION}:
                command_template = _fallback_night_command(state)
            else:
                stop_reason = str(decision.get("status") or "orchestrator_idle")
                break
        command = {
            "command_id": f"simulation_{step}_{uuid.uuid4().hex}",
            "room_id": room_id,
            "actor_user_id": user.id,
            "actor_seat_id": "bot_orchestrator",
            "expected_version": int(state.get("version") or 0),
            "type": str(command_template.get("type") or ""),
            "payload": deepcopy(command_template.get("payload") or {}),
        }
        try:
            next_state, events = reducer._reduce(state, command, user=user, room_id=room_id, room=room)
        except CommandRejection as exc:
            stop_reason = f"command_rejected:{type(exc).__name__}:{exc}"
            break
        if next_state.get("phase") in {PHASE_NIGHT_IDLE, PHASE_NIGHT_ACTION}:
            _mark_game_lost_if_needed(next_state)
        state = next_state
        frames.append(
            _frame(
                index=step,
                projection=_project_state(state),
                command={"type": command["type"], "payload": command["payload"]},
                events=events,
                decision=decision,
            )
        )
    else:
        stop_reason = "step_limit_reached"

    elapsed_ms = max(1, round((time.perf_counter() - started) * 1000))
    poulpita = state.get("poulpita") or {}
    payload = {
        "format_version": REPLAY_FORMAT_VERSION,
        "id": replay_id,
        "created_at": _now_iso(),
        "level_id": level["id"],
        "level_name": level.get("name") or level["id"],
        "seed": seed,
        "simulation_mode": simulation_mode,
        "map": deepcopy(initial_projection.get("map") or {}),
        "tile_catalog": deepcopy(initial_projection.get("tile_catalog") or {}),
        "metadata": {
            "outcome": state.get("game_outcome") or ("incomplete" if state.get("phase") != PHASE_FINISHED else "completed"),
            "game_over_reason": state.get("game_over_reason") or stop_reason,
            "stop_reason": stop_reason,
            "steps": len(frames) - 1,
            "duration_ms": elapsed_ms,
            "final_day": int(state.get("day_index") or 1),
            "final_energy": int(poulpita.get("energy") or 0),
        },
        "frames": frames,
    }
    _write_replay(payload)
    return _replay_summary(payload)


def run_bot_simulation_batch(
    *,
    level_id: str,
    game_count: int,
    max_steps: int = 2000,
    seed: int | None = None,
    simulation_mode: str = "fast",
) -> list[dict[str, Any]]:
    normalized_count = max(1, min(100, int(game_count)))
    normalized_steps = max(10, min(10000, int(max_steps)))
    normalized_mode = "full" if str(simulation_mode or "fast").lower() == "full" else "fast"
    base_seed = int(seed) if seed is not None else random.SystemRandom().randrange(1, 2**31)
    with _simulation_lock:
        previous_random_state = random.getstate()
        try:
            return [
                run_bot_simulation(
                    level_id=level_id,
                    seed=base_seed + index,
                    max_steps=normalized_steps,
                    simulation_mode=normalized_mode,
                )
                for index in range(normalized_count)
            ]
        finally:
            random.setstate(previous_random_state)
