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
_background_threads: set[threading.Thread] = set()
_background_threads_lock = threading.Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _replay_path(replay_id: str) -> Path:
    normalized = str(replay_id or "").strip()
    if not normalized or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for character in normalized):
        raise LookupError("Replay not found.")
    return REPLAYS_ROOT / f"{normalized}.json"


def _progress_path(replay_id: str) -> Path:
    return _replay_path(replay_id).with_suffix(".progress")


def _write_replay(payload: dict[str, Any]) -> None:
    REPLAYS_ROOT.mkdir(parents=True, exist_ok=True)
    destination = _replay_path(str(payload["id"]))
    temporary = destination.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=True, separators=(",", ":")), encoding="utf-8")
    temporary.replace(destination)


def _write_progress(replay_id: str, progress: dict[str, Any]) -> None:
    REPLAYS_ROOT.mkdir(parents=True, exist_ok=True)
    destination = _progress_path(replay_id)
    temporary = destination.with_suffix(".progress.tmp")
    temporary.write_text(json.dumps(progress, ensure_ascii=True, separators=(",", ":")), encoding="utf-8")
    temporary.replace(destination)


def _read_progress(replay_id: str) -> dict[str, Any] | None:
    path = _progress_path(replay_id)
    if not path.exists():
        return None
    try:
        progress = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return progress if isinstance(progress, dict) else None


def _payload_with_progress(payload: dict[str, Any]) -> dict[str, Any]:
    replay_id = str(payload.get("id") or "")
    progress = _read_progress(replay_id) if replay_id else None
    if not progress:
        return payload
    if str(progress.get("status") or "") == "running":
        try:
            updated_at = datetime.fromisoformat(str(progress.get("updated_at") or ""))
            if updated_at.tzinfo is None:
                updated_at = updated_at.replace(tzinfo=timezone.utc)
            heartbeat_age = (datetime.now(timezone.utc) - updated_at).total_seconds()
        except ValueError:
            heartbeat_age = 31
        if heartbeat_age > 30:
            _mark_simulation_failed(replay_id, "Simulation worker stopped before completing the replay.")
            payload = _read_replay(replay_id)
            progress = _read_progress(replay_id) or {}
    merged = deepcopy(payload)
    merged["status"] = str(progress.get("status") or merged.get("status") or "queued")
    merged["progress"] = progress
    return merged


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
    progress = deepcopy(payload.get("progress") or {})
    if "shelter_seashells" not in progress:
        frames = payload.get("frames") or []
        final_projection = (frames[-1].get("projection") or {}) if frames else {}
        progress["shelter_seashells"] = sum(
            max(0, int(shelter.get("seashells") or 0))
            for shelter in (final_projection.get("shelters") or {}).values()
            if isinstance(shelter, dict)
        )
    status = str(payload.get("status") or progress.get("status") or "completed")
    return {
        "id": str(payload.get("id") or ""),
        "created_at": str(payload.get("created_at") or ""),
        "level_id": str(payload.get("level_id") or ""),
        "level_name": str(payload.get("level_name") or payload.get("level_id") or ""),
        "seed": int(payload.get("seed") or 0),
        "simulation_mode": str(payload.get("simulation_mode") or "fast"),
        "status": status,
        "outcome": str(metadata.get("outcome") or ("pending" if status in {"queued", "running"} else "incomplete")),
        "game_over_reason": str(metadata.get("game_over_reason") or ""),
        "steps": int(metadata.get("steps") or 0),
        "duration_ms": int(metadata.get("duration_ms") or 0),
        "final_day": int(metadata.get("final_day") or 1),
        "final_energy": int(metadata.get("final_energy") or 0),
        "frame_count": len(payload.get("frames") or []),
        "progress": deepcopy(progress),
    }


def list_bot_replays() -> list[dict[str, Any]]:
    if not REPLAYS_ROOT.exists():
        return []
    summaries = []
    for path in REPLAYS_ROOT.glob("*.json"):
        try:
            summaries.append(_replay_summary(_payload_with_progress(json.loads(path.read_text(encoding="utf-8")))))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            continue
    return sorted(summaries, key=lambda entry: entry["created_at"], reverse=True)


def get_bot_replay(replay_id: str) -> dict[str, Any]:
    return _payload_with_progress(_read_replay(replay_id))


def delete_bot_replay(replay_id: str) -> None:
    path = _replay_path(replay_id)
    if not path.exists():
        raise LookupError("Replay not found.")
    progress = _read_progress(replay_id) or {}
    if str(progress.get("status") or "") in {"queued", "running"}:
        raise RuntimeError("A running simulation cannot be deleted.")
    path.unlink()
    _progress_path(replay_id).unlink(missing_ok=True)


def _simulation_progress(
    *,
    state: dict[str, Any],
    status: str,
    step: int,
    max_steps: int,
    last_action: str = "",
) -> dict[str, Any]:
    poulpita = state.get("poulpita") or {}
    shelters = state.get("shelters") or {}
    shelter_tokens = sum(
        max(0, int(entry.get("count") or 0)) if isinstance(entry, dict) else max(0, int(entry or 0))
        for entry in shelters.values()
    )
    secured_shelters = sum(
        1
        for entry in shelters.values()
        if isinstance(entry, dict) and (entry.get("secure") or int(entry.get("seashells") or 0) >= 3)
    )
    shelter_seashells = sum(
        max(0, int(entry.get("seashells") or 0))
        for entry in shelters.values()
        if isinstance(entry, dict)
    )
    phase = str(state.get("phase") or "setup")
    day_index = max(1, int(state.get("day_index") or 1))
    capabilities = state.get("capabilities") or {}
    total_initiatives = sum(
        max(0, int(capability.get("max_control_takes_per_night") or 0))
        for capability in capabilities.values()
    )
    remaining_initiatives = sum(
        max(
            0,
            int(capability.get("max_control_takes_per_night") or 0)
            - int(capability.get("control_takes_this_night") or 0),
        )
        for capability in capabilities.values()
    )
    size_index = max(0, int(poulpita.get("size_index") or 0))
    sizes = ((state.get("tile_catalog") or {}).get("poulpita_panel") or {}).get("sizes") or []
    current_size = sizes[size_index] if size_index < len(sizes) else {}
    size_amount = current_size.get("amount")
    size_unit = str(current_size.get("unit") or "")
    size_label = f"{size_amount:g} {size_unit}" if isinstance(size_amount, (int, float)) else f"Size {size_index + 1}"
    return {
        "status": status,
        "updated_at": _now_iso(),
        "step": max(0, int(step)),
        "max_steps": max(1, int(max_steps)),
        "percent": round(min(100, max(0, int(step)) * 100 / max(1, int(max_steps))), 1),
        "phase": phase,
        "phase_label": "Day" if phase == "day" else (f"Night {day_index}" if phase in {PHASE_NIGHT_IDLE, PHASE_NIGHT_ACTION} else phase.replace("_", " ").title()),
        "day_index": day_index,
        "night_time_spent": max(0, int(state.get("night_time_spent") or 0)),
        "night_time_total": max(1, int(state.get("night_time_total") or 24)),
        "energy": max(0, int(poulpita.get("energy") or 0)),
        "max_energy": max(1, int(poulpita.get("max_energy") or 32)),
        "neurons": max(0, int(poulpita.get("neurons") or 0)),
        "seashells": max(0, int(poulpita.get("seashells") or 0)),
        "shelter_seashells": shelter_seashells,
        "size_index": size_index,
        "size_label": size_label.strip(),
        "remaining_initiatives": remaining_initiatives,
        "total_initiatives": total_initiatives,
        "node_id": str(poulpita.get("node_id") or ""),
        "shelter_tokens": shelter_tokens,
        "secured_shelters": secured_shelters,
        "last_action": str(last_action or ""),
    }


def _queued_replay_payload(
    *,
    replay_id: str,
    created_at: str,
    level: dict[str, Any],
    seed: int,
    max_steps: int,
    simulation_mode: str,
) -> dict[str, Any]:
    return {
        "format_version": REPLAY_FORMAT_VERSION,
        "id": replay_id,
        "created_at": created_at,
        "level_id": str(level["id"]),
        "level_name": str(level.get("name") or level["id"]),
        "seed": int(seed),
        "simulation_mode": simulation_mode,
        "status": "queued",
        "metadata": {
            "outcome": "pending",
            "game_over_reason": "",
            "stop_reason": "queued",
            "steps": 0,
            "duration_ms": 0,
            "final_day": 1,
            "final_energy": max(0, int(level.get("starting_energy") or 3)),
            "max_steps": int(max_steps),
        },
        "frames": [],
    }


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


def _playable_initial_state(
    *,
    room_id: str,
    level_id: str,
    bot_config: dict[str, Any],
    max_attempts: int = 50,
) -> tuple[dict[str, Any], int]:
    for attempt in range(1, max_attempts + 1):
        state = _goldfish_state(room_id, level_id=level_id, mode="bots_only", bot_config=bot_config)
        first_decision = choose_fast_bot_orchestrator_action(state)
        first_command_type = str(((first_decision.get("command") or {}).get("type") or ""))
        if first_command_type != "bot_no_actions_available":
            return state, attempt
    raise RuntimeError(
        "Could not create a playable initial layout after "
        f"{max_attempts} shuffles. Check compulsory tile initiator configuration."
    )


def run_bot_simulation(
    *,
    level_id: str,
    seed: int,
    max_steps: int = 2000,
    simulation_mode: str = "fast",
    replay_id: str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    level = get_level_config(level_id)
    replay_id = replay_id or f"replay_{uuid.uuid4().hex}"
    created_at = created_at or _now_iso()
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
    state, setup_attempts = _playable_initial_state(
        room_id=room_id,
        level_id=level["id"],
        bot_config=bot_config,
    )
    initial_projection = _project_state(state)
    frames = [_frame(index=0, projection=initial_projection, command=None, events=initial_projection.get("events") or [])]
    stop_reason = "game_finished"
    last_progress_write = 0.0
    previous_phase = ""
    _write_progress(
        replay_id,
        _simulation_progress(state=state, status="running", step=0, max_steps=max_steps),
    )

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
            stop_reason = f"command_rejected:{exc.reason}:{exc.message}"
            break
        if next_state.get("phase") in {PHASE_NIGHT_IDLE, PHASE_NIGHT_ACTION}:
            _mark_game_lost_if_needed(next_state)
        state = next_state
        command_label = str(command["type"] or "").replace("_", " ")
        frames.append(
            _frame(
                index=step,
                projection=_project_state(state),
                command={"type": command["type"], "payload": command["payload"]},
                events=events,
                decision=decision,
            )
        )
        now = time.perf_counter()
        phase = str(state.get("phase") or "")
        if phase != previous_phase or step % 10 == 0 or now - last_progress_write >= 0.2:
            _write_progress(
                replay_id,
                _simulation_progress(
                    state=state,
                    status="running",
                    step=step,
                    max_steps=max_steps,
                    last_action=command_label,
                ),
            )
            previous_phase = phase
            last_progress_write = now
    else:
        stop_reason = "step_limit_reached"

    elapsed_ms = max(1, round((time.perf_counter() - started) * 1000))
    poulpita = state.get("poulpita") or {}
    final_progress = _simulation_progress(
        state=state,
        status="completed",
        step=len(frames) - 1,
        max_steps=max_steps,
        last_action=str(((frames[-1].get("command") or {}).get("type") or "")).replace("_", " "),
    )
    final_progress["percent"] = 100
    payload = {
        "format_version": REPLAY_FORMAT_VERSION,
        "id": replay_id,
        "created_at": created_at,
        "level_id": level["id"],
        "level_name": level.get("name") or level["id"],
        "seed": seed,
        "simulation_mode": simulation_mode,
        "status": "completed",
        "progress": final_progress,
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
            "setup_rerolls": max(0, setup_attempts - 1),
        },
        "frames": frames,
    }
    _write_replay(payload)
    _progress_path(replay_id).unlink(missing_ok=True)
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


def _mark_simulation_failed(replay_id: str, message: str) -> None:
    try:
        payload = _read_replay(replay_id)
    except LookupError:
        return
    payload["status"] = "failed"
    metadata = payload.setdefault("metadata", {})
    metadata["outcome"] = "incomplete"
    metadata["stop_reason"] = "simulation_failed"
    metadata["game_over_reason"] = str(message or "Simulation failed.")
    _write_replay(payload)
    progress = _read_progress(replay_id) or {}
    progress.update(
        {
            "status": "failed",
            "updated_at": _now_iso(),
            "phase": "failed",
            "phase_label": "Failed",
            "error": str(message or "Simulation failed."),
        }
    )
    _write_progress(replay_id, progress)


def _run_background_batch(instances: list[dict[str, Any]]) -> None:
    with _simulation_lock:
        previous_random_state = random.getstate()
        try:
            for instance in instances:
                try:
                    run_bot_simulation(
                        level_id=instance["level_id"],
                        seed=instance["seed"],
                        max_steps=instance["max_steps"],
                        simulation_mode=instance["simulation_mode"],
                        replay_id=instance["id"],
                        created_at=instance["created_at"],
                    )
                except Exception as exc:  # Persist worker failures so polling never remains stuck on running.
                    _mark_simulation_failed(instance["id"], f"{type(exc).__name__}: {exc}")
        finally:
            random.setstate(previous_random_state)


def start_bot_simulation_batch(
    *,
    level_id: str,
    game_count: int,
    max_steps: int = 2000,
    seed: int | None = None,
    simulation_mode: str = "fast",
) -> list[dict[str, Any]]:
    level = get_level_config(level_id)
    normalized_count = max(1, min(100, int(game_count)))
    normalized_steps = max(10, min(10000, int(max_steps)))
    normalized_mode = "full" if str(simulation_mode or "fast").lower() == "full" else "fast"
    base_seed = int(seed) if seed is not None else random.SystemRandom().randrange(1, 2**31)
    instances = []
    for index in range(normalized_count):
        replay_id = f"replay_{uuid.uuid4().hex}"
        created_at = _now_iso()
        instance = {
            "id": replay_id,
            "created_at": created_at,
            "level_id": str(level["id"]),
            "seed": base_seed + index,
            "max_steps": normalized_steps,
            "simulation_mode": normalized_mode,
        }
        payload = _queued_replay_payload(
            replay_id=replay_id,
            created_at=created_at,
            level=level,
            seed=instance["seed"],
            max_steps=normalized_steps,
            simulation_mode=normalized_mode,
        )
        _write_replay(payload)
        _write_progress(
            replay_id,
            {
                "status": "queued",
                "updated_at": created_at,
                "step": 0,
                "max_steps": normalized_steps,
                "percent": 0,
                "phase": "queued",
                "phase_label": "Queued",
            },
        )
        instances.append(instance)

    thread = threading.Thread(
        target=_run_background_batch,
        args=(instances,),
        name=f"bot-simulation-{instances[0]['id']}",
        daemon=True,
    )
    with _background_threads_lock:
        _background_threads.add(thread)

    def release_thread() -> None:
        try:
            thread.join()
        finally:
            with _background_threads_lock:
                _background_threads.discard(thread)

    thread.start()
    cleanup = threading.Thread(target=release_thread, name=f"cleanup-{thread.name}", daemon=True)
    cleanup.start()
    return [_replay_summary(_payload_with_progress(_read_replay(instance["id"]))) for instance in instances]
