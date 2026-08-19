from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
from typing import Any

from .bot_simulation_service import get_bot_replay, list_bot_replays


ABILITY_ORDER = ["agility", "camouflage", "force", "propulsion", "intelligence"]
ACTION_LABELS = {
    "collect_action_points": "Collect AP",
    "move_poulpita": "Move",
    "draw_action_card": "Draw card",
    "start_interaction": "Start interaction",
    "resolve_interaction": "Resolve interaction",
    "fail_interaction": "Fail interaction",
    "use_special_power": "Special power",
    "take_control": "Take control",
    "end_night": "End night",
    "move_seashell_to_shelter": "Store shell",
    "move_seashell_from_shelter": "Take shell",
    "buy_hand_size_upgrade": "Buy upgrade",
    "buy_poulpita_size": "Grow",
}
EVENT_ACTIONS = {
    "action_points_collected": "collect_action_points",
    "poulpita_moved": "move_poulpita",
    "action_card_drawn": "draw_action_card",
    "interaction_started": "start_interaction",
    "interaction_resolved": "resolve_interaction",
    "interaction_failed": "fail_interaction",
    "special_power_used": "use_special_power",
    "control_taken": "take_control",
    "day_started": "end_night",
    "night_started": "end_day",
    "seashell_moved_to_shelter": "move_seashell_to_shelter",
    "seashell_moved_to_poulpita": "move_seashell_from_shelter",
    "hand_size_upgrade_bought": "buy_hand_size_upgrade",
    "deck_exchange_upgrade_bought": "buy_hand_size_upgrade",
    "poulpita_size_increased": "buy_poulpita_size",
}


def _integer(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _histogram(values: list[int]) -> list[dict[str, int]]:
    return [
        {"value": value, "count": count}
        for value, count in sorted(Counter(values).items())
    ]


def _safe_map(payload: dict[str, Any]) -> dict[str, Any]:
    board = payload.get("map") or {}
    return {
        "id": str(board.get("id") or ""),
        "name": str(board.get("name") or ""),
        "image_url": board.get("image_url"),
        "image_width": board.get("image_width"),
        "image_height": board.get("image_height"),
        "nodes": deepcopy(board.get("nodes") or {}),
    }


def _point_from_projection(
    projection: dict[str, Any],
    *,
    command: dict[str, Any] | None,
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    poulpita = projection.get("poulpita") or {}
    payload = (command or {}).get("payload") if isinstance((command or {}).get("payload"), dict) else {}
    capability_id = str(payload.get("capability_id") or "")
    if not capability_id:
        capability_id = str(next((event.get("capability_id") for event in events if event.get("capability_id")), "") or "")
    return {
        "day_index": max(1, _integer(projection.get("day_index"), 1)),
        "phase": str(projection.get("phase") or ""),
        "command_type": str((command or {}).get("type") or ""),
        "capability_id": capability_id,
        "node_id": str(poulpita.get("node_id") or ""),
        "energy": max(0, _integer(poulpita.get("energy"))),
        "neurons": max(0, _integer(poulpita.get("neurons"))),
        "seashells": max(0, _integer(poulpita.get("seashells"))),
        "size_index": max(0, _integer(poulpita.get("size_index"))),
        "event_types": [str(event.get("type") or "") for event in events if event.get("type")],
        "event_capabilities": [str(event.get("capability_id") or "") for event in events if event.get("capability_id")],
    }


def _simulation_game(replay: dict[str, Any]) -> dict[str, Any]:
    frames = replay.get("frames") or []
    points = [
        _point_from_projection(
            frame.get("projection") or {},
            command=frame.get("command") or {},
            events=frame.get("events") or [],
        )
        for frame in frames
        if isinstance(frame, dict) and isinstance(frame.get("projection"), dict)
    ]
    metadata = replay.get("metadata") or {}
    return {
        "id": str(replay.get("id") or ""),
        "source": "bot_simulation",
        "created_at": str(replay.get("created_at") or ""),
        "level_id": str(replay.get("level_id") or ""),
        "mode": "bots_only",
        "outcome": str(metadata.get("outcome") or "incomplete"),
        "game_over_reason": str(metadata.get("game_over_reason") or ""),
        "map": _safe_map(replay),
        "points": points,
    }


def _saved_game(record: dict[str, Any]) -> dict[str, Any]:
    state = record.get("state") or {}
    timeline = list(state.get("analytics_timeline") or [])
    detail_level = "complete" if timeline else "event_log"
    if not timeline:
        current_day = 1
        current_node_id = ""
        final_poulpita = state.get("poulpita") or {}
        timeline = []
        for event in state.get("event_log") or []:
            if not isinstance(event, dict):
                continue
            if event.get("day_index") is not None:
                current_day = max(1, _integer(event.get("day_index"), current_day))
            event_type = str(event.get("type") or "")
            current_node_id = str(
                event.get("to_node_id")
                or event.get("node_id")
                or current_node_id
                or final_poulpita.get("node_id")
                or ""
            )
            timeline.append(
                {
                    "day_index": current_day,
                    "phase": str(state.get("phase") or ""),
                    "command_type": EVENT_ACTIONS.get(event_type, ""),
                    "capability_id": str(event.get("capability_id") or ""),
                    "node_id": current_node_id,
                    # Old states do not store resource checkpoints, so do not infer false deltas.
                    "energy": None,
                    "neurons": None,
                    "seashells": None,
                    "size_index": None,
                    "event_types": [event_type] if event_type else [],
                    "event_capabilities": [str(event.get("capability_id") or "")] if event.get("capability_id") else [],
                }
            )
        timeline.append(
            {
                "day_index": max(1, _integer(state.get("day_index"), current_day)),
                "phase": str(state.get("phase") or ""),
                "command_type": "",
                "capability_id": "",
                "node_id": str(final_poulpita.get("node_id") or current_node_id),
                "energy": max(0, _integer(final_poulpita.get("energy"))),
                "neurons": max(0, _integer(final_poulpita.get("neurons"))),
                "seashells": max(0, _integer(final_poulpita.get("seashells"))),
                "size_index": max(0, _integer(final_poulpita.get("size_index"))),
                "event_types": [],
                "event_capabilities": [],
            }
        )
    return {
        "id": str(record.get("id") or ""),
        "source": "saved_game",
        "created_at": str(record.get("created_at") or ""),
        "level_id": str(record.get("level_id") or state.get("level_id") or ""),
        "mode": str(record.get("mode") or state.get("mode") or "goldfish"),
        "outcome": str(record.get("outcome") or state.get("game_outcome") or "completed"),
        "game_over_reason": str(record.get("game_over_reason") or state.get("game_over_reason") or ""),
        "map": _safe_map(state),
        "points": timeline,
        "detail_level": detail_level,
    }


def list_games_for_level(*, level_id: str, saved_games: list[dict[str, Any]]) -> list[dict[str, Any]]:
    games = [_saved_game(record) for record in saved_games if str(record.get("level_id") or "") == str(level_id)]
    for summary in list_bot_replays():
        if str(summary.get("level_id") or "") != str(level_id):
            continue
        try:
            games.append(_simulation_game(get_bot_replay(str(summary.get("id") or ""))))
        except (LookupError, OSError, ValueError):
            continue
    return sorted(games, key=lambda game: game["created_at"], reverse=True)


def _game_summary(game: dict[str, Any]) -> dict[str, Any]:
    points = game.get("points") or []
    final = points[-1] if points else {}
    return {
        "id": game["id"],
        "source": game["source"],
        "created_at": game["created_at"],
        "mode": game["mode"],
        "outcome": game["outcome"],
        "game_over_reason": game["game_over_reason"],
        "detail_level": str(game.get("detail_level") or "complete"),
        "final_day": max(1, _integer(final.get("day_index"), 1)),
        "final_energy": max(0, _integer(final.get("energy"))),
        "steps": max(0, len(points) - 1),
    }


def build_level_analytics(
    *,
    level_id: str,
    games: list[dict[str, Any]],
    selected_nights: set[int] | None = None,
) -> dict[str, Any]:
    outcomes: Counter[str] = Counter()
    reasons: Counter[str] = Counter()
    action_counts: dict[str, Counter[str]] = defaultdict(Counter)
    special_counts: Counter[str] = Counter()
    upgrades_by_day: Counter[int] = Counter()
    node_visits: Counter[str] = Counter()
    resource_per_night: dict[str, list[int]] = {
        "energy_gained_per_night": [],
        "energy_lost_per_night": [],
        "neurons_gained_per_night": [],
        "neurons_spent_per_night": [],
    }
    interaction_counts: Counter[str] = Counter()
    final_energy: list[int] = []
    final_day: list[int] = []
    step_counts: list[int] = []
    map_data: dict[str, Any] = {}
    available_nights: set[int] = set()

    for game in games:
        if not map_data and (game.get("map") or {}).get("nodes"):
            map_data = game["map"]
        outcomes[str(game.get("outcome") or "incomplete")] += 1
        if game.get("game_over_reason"):
            reasons[str(game["game_over_reason"])] += 1
        points = game.get("points") or []
        if not points:
            continue
        previous = None
        previous_node = None
        per_day: dict[int, dict[str, int]] = defaultdict(lambda: {
            "energy_gained_per_night": 0,
            "energy_lost_per_night": 0,
            "neurons_gained_per_night": 0,
            "neurons_spent_per_night": 0,
        })
        for point in points:
            day = max(1, _integer(point.get("day_index"), 1))
            available_nights.add(day)
            action = str(point.get("command_type") or "")
            ability_id = str(point.get("capability_id") or "")
            if action:
                action_counts[ability_id or "team"][action] += 1
            if action == "use_special_power" and ability_id:
                special_counts[ability_id] += 1
            if action in {"buy_hand_size_upgrade", "buy_poulpita_size"}:
                upgrades_by_day[day] += 1
            for event_type in point.get("event_types") or []:
                if event_type == "interaction_resolved":
                    interaction_counts["resolved"] += 1
                elif event_type == "interaction_failed":
                    interaction_counts["failed"] += 1
                elif (
                    not action.startswith("buy_")
                    and event_type in {"hand_size_upgrade_bought", "deck_exchange_upgrade_bought", "poulpita_size_increased"}
                ):
                    upgrades_by_day[day] += 1
            node_id = str(point.get("node_id") or "")
            if node_id and node_id != previous_node:
                node_visits[node_id] += 1
                previous_node = node_id
            if previous is not None and point.get("energy") is not None and previous.get("energy") is not None:
                energy_delta = _integer(point.get("energy")) - _integer(previous.get("energy"))
                neuron_delta = _integer(point.get("neurons")) - _integer(previous.get("neurons"))
                if energy_delta > 0:
                    per_day[day]["energy_gained_per_night"] += energy_delta
                elif energy_delta < 0:
                    per_day[day]["energy_lost_per_night"] += -energy_delta
                if neuron_delta > 0:
                    per_day[day]["neurons_gained_per_night"] += neuron_delta
                elif neuron_delta < 0:
                    per_day[day]["neurons_spent_per_night"] += -neuron_delta
            previous = point
        for day, values in per_day.items():
            if selected_nights is not None and day not in selected_nights:
                continue
            for metric in resource_per_night:
                resource_per_night[metric].append(values[metric])
        final_energy.append(max(0, _integer(points[-1].get("energy"))))
        final_day.append(max(1, _integer(points[-1].get("day_index"), 1)))
        step_counts.append(max(0, len(points) - 1))

    total = len(games)
    resource_totals = {metric: sum(values) for metric, values in resource_per_night.items()}
    action_rows = []
    for ability_id in [*ABILITY_ORDER, "team"]:
        counts = action_counts.get(ability_id)
        if not counts:
            continue
        action_rows.append({
            "ability_id": ability_id,
            "total": sum(counts.values()),
            "actions": [
                {"id": action_id, "label": ACTION_LABELS.get(action_id, action_id.replace("_", " ")), "count": count}
                for action_id, count in counts.most_common()
            ],
        })

    return {
        "level_id": str(level_id),
        "games": [_game_summary(game) for game in games],
        "analytics": {
            "overview": {
                "games": total,
                "wins": outcomes.get("won", 0),
                "win_rate": round((outcomes.get("won", 0) / total * 100) if total else 0, 1),
                "average_final_day": round(sum(final_day) / len(final_day), 2) if final_day else 0,
                "average_final_energy": round(sum(final_energy) / len(final_energy), 2) if final_energy else 0,
                "average_steps": round(sum(step_counts) / len(step_counts), 1) if step_counts else 0,
            },
            "outcomes": [{"id": key, "count": value} for key, value in outcomes.most_common()],
            "loss_reasons": [{"id": key, "count": value} for key, value in reasons.most_common()],
            "resource_distributions": {metric: _histogram(values) for metric, values in resource_per_night.items()},
            "resource_filter": {
                "available_nights": sorted(available_nights),
                "selected_nights": sorted(selected_nights) if selected_nights is not None else sorted(available_nights),
                "samples": len(resource_per_night["energy_gained_per_night"]),
                "totals": resource_totals,
            },
            "upgrades_by_day": [{"day": day, "count": count} for day, count in sorted(upgrades_by_day.items())],
            "special_abilities": [{"ability_id": ability_id, "count": count} for ability_id, count in special_counts.most_common()],
            "actions_by_ability": action_rows,
            "node_visits": [{"node_id": node_id, "count": count} for node_id, count in node_visits.most_common()],
            "interaction_outcomes": {
                "resolved": interaction_counts.get("resolved", 0),
                "failed": interaction_counts.get("failed", 0),
                "success_rate": round(
                    interaction_counts.get("resolved", 0) / sum(interaction_counts.values()) * 100,
                    1,
                ) if interaction_counts else 0,
            },
            "map": map_data,
        },
    }
