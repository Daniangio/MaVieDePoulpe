from __future__ import annotations

import hashlib
import math
import random
from copy import deepcopy
from itertools import combinations
from typing import Any


BOT_PLAYER_ABILITIES = {"agility", "camouflage", "force", "propulsion"}
BOT_PLAN_TERMINAL_COMMANDS = {
    "buy_hand_size_upgrade",
    "buy_poulpita_size",
    "collect_action_points",
    "draw_action_card",
    "move_poulpita",
    "start_interaction",
    "resolve_interaction",
    "end_day",
}
DEFAULT_PLANNING_TAKE_CONTROL_DEPTH = 3


def _resource_estimate(*, ap: int = 0, time_steps: int = 0, control_takes: dict[str, int] | None = None) -> dict[str, Any]:
    return {
        "ap_by_ability": {"any": ap} if ap else {},
        "time_steps": time_steps,
        "control_takes_by_ability": control_takes or {},
        "energy_delta_expected": 0,
        "shells_delta_expected": 0,
        "neurons_delta_expected": 0,
    }


def _public_plan(
    *,
    plan_id: str,
    proposer_ability_id: str | None,
    title: str,
    rationale: str,
    risk_label: str,
    step_preview: list[str],
    expected_resources: dict[str, Any],
    score: float,
    warnings: list[str] | None = None,
    objective_effect: str | None = None,
    commands: list[dict[str, Any]] | None = None,
    statistics: dict[str, Any] | None = None,
    plan_chain: list[dict[str, Any]] | None = None,
    plan_group: str | None = None,
) -> dict[str, Any]:
    stats = statistics or {}
    success_probability = stats.get("success_probability")
    return {
        "plan_id": plan_id,
        "proposer_ability_id": proposer_ability_id,
        "title": title,
        "rationale": rationale,
        "risk_label": risk_label,
        "confidence": success_probability,
        "step_preview": step_preview,
        "plan_chain": plan_chain or _plan_chain(step_preview, commands or []),
        "expected_resources": expected_resources,
        "objective_effect": objective_effect,
        "statistics": stats,
        "warnings": warnings or [],
        "commands": commands or [],
        "_plan_group": plan_group or plan_id,
        "_score": score,
    }


def _safe_public_command(command: dict[str, Any]) -> dict[str, Any] | None:
    command_type = str(command.get("type") or "")
    payload = command.get("payload") or {}
    if not isinstance(payload, dict):
        payload = {}
    safe_payload_keys = {
        "take_control": {"capability_id"},
        "collect_action_points": {"capability_id"},
        "move_poulpita": {"capability_id", "target_node_id"},
        "draw_action_card": {"capability_id", "auto_discard_card"},
        "start_interaction": {"capability_id", "tile_instance_id", "auto_select_cards"},
        "resolve_interaction": {"capability_id", "auto_select_cards", "confirm_only"},
        "fail_interaction": {"target_node_id"},
        "end_day": set(),
        "end_night": {"capability_id"},
        "move_seashell_to_shelter": set(),
        "move_seashell_from_shelter": set(),
        "buy_hand_size_upgrade": {"capability_id", "upgrade_index"},
        "buy_poulpita_size": set(),
        "resolve_surprise_card": {"accept", "capability_id", "auto_select_cards"},
    }
    if command_type not in safe_payload_keys:
        return None
    if "discard_card_id" in payload:
        return None
    if "card_ids" in payload:
        if command_type not in {"resolve_interaction", "resolve_surprise_card"}:
            return None
        payload = {**payload, "auto_select_cards": True}
    public_payload = {key: payload[key] for key in safe_payload_keys[command_type] if key in payload}
    return {"type": command_type, "payload": public_payload}


def _plan_chain(step_preview: list[str], commands: list[dict[str, Any]]) -> list[dict[str, Any]]:
    length = max(len(step_preview), len(commands))
    chain = []
    for index in range(length):
        command_type = str((commands[index] if index < len(commands) else {}).get("type") or "")
        public_command = _safe_public_command(commands[index]) if index < len(commands) else None
        label = step_preview[index] if index < len(step_preview) else command_type.replace("_", " ").title()
        chain.append(
            {
                "index": index,
                "label": label,
                "command_type": command_type or None,
                "public_command": public_command,
                "auto_executable": bool(public_command),
                "decision_boundary": command_type in BOT_PLAN_TERMINAL_COMMANDS,
            }
        )
    return chain


def _action_cost(state: dict[str, Any], action_id: str) -> dict[str, int]:
    defaults = {
        "gain_ap": {"ap_cost": 0, "time_cost": 0, "neuron_cost": 0},
        "move": {"ap_cost": 1, "time_cost": 1, "neuron_cost": 0},
        "draw": {"ap_cost": 1, "time_cost": 1, "neuron_cost": 0},
        "interact": {"ap_cost": 2, "time_cost": 2, "neuron_cost": 0},
        "special_power": {"ap_cost": 2, "time_cost": 2, "neuron_cost": 1},
    }
    configured = (((state.get("tile_catalog") or {}).get("action_costs") or {}).get(action_id) or {})
    fallback = defaults.get(action_id) or {"ap_cost": 0, "time_cost": 0, "neuron_cost": 0}
    return {
        "ap_cost": max(0, int(configured.get("ap_cost") if configured.get("ap_cost") is not None else fallback["ap_cost"])),
        "time_cost": max(0, int(configured.get("time_cost") if configured.get("time_cost") is not None else fallback["time_cost"])),
        "neuron_cost": max(0, int(configured.get("neuron_cost") if configured.get("neuron_cost") is not None else fallback["neuron_cost"])),
    }


def _can_pay_action_cost(state: dict[str, Any], capability: dict[str, Any], cost: dict[str, int]) -> bool:
    return (
        int(capability.get("pa") or 0) >= int(cost.get("ap_cost") or 0)
        and int((state.get("poulpita") or {}).get("neurons") or 0) >= int(cost.get("neuron_cost") or 0)
    )


def _can_collect_toward_action_cost(state: dict[str, Any], capability: dict[str, Any], cost: dict[str, int]) -> bool:
    return (
        int(capability.get("pa") or 0) < int(cost.get("ap_cost") or 0)
        and int((state.get("poulpita") or {}).get("neurons") or 0) >= int(cost.get("neuron_cost") or 0)
        and _can_pay_action_cost(state, capability, _action_cost(state, "gain_ap"))
    )


def _simulate_spend_action(state: dict[str, Any], capability: dict[str, Any], cost: dict[str, int]) -> None:
    capability["pa"] = max(0, int(capability.get("pa") or 0) - int(cost.get("ap_cost") or 0))
    capability["actions_taken_this_control"] = int(capability.get("actions_taken_this_control") or 0) + 1
    poulpita = state.setdefault("poulpita", {})
    poulpita["neurons"] = max(0, int(poulpita.get("neurons") or 0) - int(cost.get("neuron_cost") or 0))
    _simulate_advance_time(state, int(cost.get("time_cost") or 0))


def _controller_ids(state: dict[str, Any], controller_type: str) -> list[str]:
    config = state.get("bot_config") or {}
    return [
        str(controller.get("ability_id"))
        for controller in config.get("controllers", []) or []
        if controller.get("controller_type") == controller_type and str(controller.get("ability_id")) in BOT_PLAYER_ABILITIES
    ]


def _capability(state: dict[str, Any], ability_id: str) -> dict[str, Any]:
    return (state.get("capabilities") or {}).get(ability_id) or {}


def _planner_capability_ids(state: dict[str, Any]) -> list[str]:
    ids = _controller_ids(state, "bot")
    if "intelligence" in (state.get("capabilities") or {}):
        ids.append("intelligence")
    return ids


def _all_capability_ids(state: dict[str, Any]) -> list[str]:
    preferred = ["agility", "camouflage", "force", "propulsion", "intelligence"]
    capabilities = state.get("capabilities") or {}
    ordered = [capability_id for capability_id in preferred if capability_id in capabilities]
    ordered.extend(capability_id for capability_id in capabilities if capability_id not in ordered)
    return ordered


def _has_control_take_left(capability: dict[str, Any]) -> bool:
    return int(capability.get("control_takes_this_night") or 0) < int(capability.get("max_control_takes_per_night") or 0)


def _action_slots_left(capability: dict[str, Any]) -> int:
    return int(capability.get("max_actions_per_control") or 0) - int(capability.get("actions_taken_this_control") or 0)


def _bot_settings(state: dict[str, Any]) -> dict[str, Any]:
    return (state.get("tile_catalog") or {}).get("bot_settings") or {}


def _expected_ap_roll(state: dict[str, Any]) -> int:
    return max(1, min(6, int(_bot_settings(state).get("expected_ap_roll") or 3)))


def _planning_depth_take_controls(state: dict[str, Any]) -> int:
    return max(1, min(8, int(_bot_settings(state).get("planning_depth_take_controls") or DEFAULT_PLANNING_TAKE_CONTROL_DEPTH)))


def _max_plans_per_proposer(state: dict[str, Any]) -> int:
    return max(1, min(16, int(_bot_settings(state).get("max_plans") or 3)))


def _max_public_plans(state: dict[str, Any]) -> int:
    proposer_count = max(1, len(_controller_ids(state, "bot")) + 1)
    return _max_plans_per_proposer(state) * proposer_count


def _playable_ability_ids(state: dict[str, Any]) -> list[str]:
    return [ability_id for ability_id in _all_capability_ids(state) if ability_id in (state.get("capabilities") or {})]


def _planner_weight(state: dict[str, Any], key: str, fallback: float) -> float:
    weights = _bot_settings(state).get("weights") or {}
    try:
        return max(0.0, float(weights.get(key) if weights.get(key) is not None else fallback))
    except (TypeError, ValueError):
        return fallback


def _resource_weight(state: dict[str, Any], key: str, fallback: float) -> float:
    weights = _bot_settings(state).get("resource_weights") or {}
    try:
        return float(weights.get(key) if weights.get(key) is not None else fallback)
    except (TypeError, ValueError):
        return fallback


def _weighted_expected_gain(state: dict[str, Any], delta: dict[str, Any]) -> float:
    defaults = {
        "energy": 8.0,
        "neurons": 5.0,
        "seashells": 4.0,
        "ap": 1.0,
        "shelters": 18.0,
        "surprise_cards": 6.0,
        "removed_tiles": 3.0,
    }
    score = 0.0
    for key, fallback in defaults.items():
        score += float(delta.get(key) or 0) * _resource_weight(state, key, fallback)
    return round(score, 2)


def _state_has_shelter(state: dict[str, Any], node_id: str) -> bool:
    raw = (state.get("shelters") or {}).get(str(node_id))
    if isinstance(raw, dict):
        return int(raw.get("count") or 0) > 0
    return int(raw or 0) > 0


def _current_size_value(state: dict[str, Any]) -> float:
    panel = (state.get("tile_catalog") or {}).get("poulpita_panel") or {}
    sizes = panel.get("sizes") or []
    size_index = max(0, int((state.get("poulpita") or {}).get("size_index") or 0))
    if size_index >= len(sizes):
        return float(size_index)
    size = sizes[size_index] or {}
    amount = float(size.get("amount") if size.get("amount") is not None else size.get("kg") or size_index)
    unit = str(size.get("unit") or "kg")
    multiplier = {"mg": 0.000001, "g": 0.001, "kg": 1.0}.get(unit, 1.0)
    return amount * multiplier


def _global_state_score_components(state: dict[str, Any]) -> dict[str, float]:
    poulpita = state.get("poulpita") or {}
    capabilities = state.get("capabilities") or {}
    current_node_id = str(poulpita.get("node_id") or "")
    hand_cards = sum(len(capability.get("hand") or []) for capability in capabilities.values())
    hand_capacity = sum(int(capability.get("current_max_cards_in_hand") or capability.get("default_max_cards_in_hand") or 0) for capability in capabilities.values())
    purchased_upgrades = sum(len(capability.get("purchased_hand_size_upgrade_indices") or []) for capability in capabilities.values())
    total_ap = sum(int(capability.get("pa") or 0) for capability in capabilities.values())
    shelter_entries = [raw for raw in (state.get("shelters") or {}).values()]
    shelter_count = 0
    secure_shelters = 0
    shelter_shells = 0
    for raw in shelter_entries:
        if isinstance(raw, dict):
            count = int(raw.get("count") or 0)
            shelter_count += count
            shelter_shells += int(raw.get("seashells") or 0)
            if count and bool(raw.get("secure")):
                secure_shelters += 1
        elif int(raw or 0) > 0:
            shelter_count += int(raw or 0)
    night_time_spent = int(state.get("night_time_spent") or 0)
    night_time_total = max(1, int(state.get("night_time_total") or 24))
    unsheltered_night_end_penalty = 1.0 if state.get("phase") in {"night_idle", "night_action"} and night_time_spent >= night_time_total and not _state_has_shelter(state, current_node_id) else 0.0
    return {
        "energy": float(poulpita.get("energy") or 0),
        "neurons": float(poulpita.get("neurons") or 0),
        "seashells": float(poulpita.get("seashells") or 0),
        "shelter_shells": float(shelter_shells),
        "cards_in_hand": float(hand_cards),
        "hand_capacity": float(hand_capacity),
        "purchased_upgrades": float(purchased_upgrades),
        "size_index": float(poulpita.get("size_index") or 0),
        "size_value": _current_size_value(state),
        "shelters": float(shelter_count),
        "secure_shelters": float(secure_shelters),
        "ap": float(total_ap),
        "night_time_remaining": float(max(0, night_time_total - night_time_spent)),
        "unsheltered_night_end_penalty": unsheltered_night_end_penalty,
        "tile_resolution": float(state.get("_simulated_resolved_tiles") or 0),
        "compulsory_tile_resolution": float(state.get("_simulated_resolved_compulsory_tiles") or 0),
    }


def _global_state_score(state: dict[str, Any]) -> float:
    if str(state.get("phase") or "") in {"game_over", "finished", "postgame"}:
        return 100000.0 if str(state.get("game_outcome") or "") == "won" else -100000.0
    defaults = {
        "energy": 10.0,
        "neurons": 5.0,
        "seashells": 4.0,
        "shelter_shells": 3.0,
        "cards_in_hand": 2.0,
        "hand_capacity": 1.0,
        "purchased_upgrades": 10.0,
        "size_index": 14.0,
        "size_value": 0.0,
        "shelters": 12.0,
        "secure_shelters": 18.0,
        "ap": 0.5,
        "night_time_remaining": 0.15,
        "unsheltered_night_end_penalty": -10.0,
        "tile_resolution": 14.0,
        "compulsory_tile_resolution": 35.0,
    }
    components = _global_state_score_components(state)
    score = 0.0
    for key, fallback in defaults.items():
        score += float(components.get(key) or 0) * _resource_weight(state, key, fallback)
    if state.get("phase") in {"night_idle", "night_action"}:
        current_node_id = str((state.get("poulpita") or {}).get("node_id") or "")
        shelter_distance = _distance_to_closest_shelter(state, current_node_id)
        if shelter_distance is None:
            shelter_distance = 6
        score -= _night_lateness_score(state) * max(0, shelter_distance)
    return round(score, 2)


def _tile_category(state: dict[str, Any], tile: dict[str, Any]) -> dict[str, Any]:
    catalog = state.get("tile_catalog") or {}
    event = (catalog.get("events") or {}).get(tile.get("event_id")) or {}
    return (catalog.get("categories") or {}).get(event.get("category_id")) or {}


def _visible_tiles_on_node(state: dict[str, Any], node_id: str) -> list[dict[str, Any]]:
    catalog_tiles = (state.get("tile_catalog") or {}).get("tiles") or {}
    visible = []
    for instance in (state.get("tiles") or {}).get(node_id, []) or []:
        if not instance.get("face_up"):
            continue
        tile = catalog_tiles.get(instance.get("tile_id")) or {}
        if tile:
            visible.append({"instance": instance, "tile": tile, "node_id": node_id})
    return visible


def _visible_current_tiles(state: dict[str, Any]) -> list[dict[str, Any]]:
    return _visible_tiles_on_node(state, str((state.get("poulpita") or {}).get("node_id") or ""))


def _compulsory_choices_on_node(state: dict[str, Any], node_id: str, *, highest_only: bool = True) -> list[dict[str, Any]]:
    choices = []
    for entry in _visible_tiles_on_node(state, node_id):
        if _tile_category(state, entry["tile"]).get("compulsory_on_same_node"):
            choices.append({**entry, "priority": int(entry["tile"].get("priority") or 0)})
    choices = sorted(choices, key=lambda choice: int(choice.get("priority") or 0), reverse=True)
    if not choices or not highest_only:
        return choices
    highest_priority = int(choices[0].get("priority") or 0)
    return [choice for choice in choices if int(choice.get("priority") or 0) == highest_priority]


def _compulsory_choices(state: dict[str, Any]) -> list[dict[str, Any]]:
    return _compulsory_choices_on_node(state, str((state.get("poulpita") or {}).get("node_id") or ""))


def _can_initiate(state: dict[str, Any], ability_id: str, tile: dict[str, Any]) -> bool:
    if tile.get("token_type") == "octopus":
        allowed_initiators = tile.get("initiator_capability_ids")
        if allowed_initiators is None:
            allowed_initiators = list((state.get("capabilities") or {}).keys())
        return ability_id in allowed_initiators
    return str(tile.get("event_id") or "") in (_capability(state, ability_id).get("initiates_event_ids") or [])


def _interaction_requirements(tile: dict[str, Any]) -> int:
    return len(tile.get("interaction_ids") or []) + max(0, int(tile.get("shell_requirement_count") or 0))


def _card_interaction_options(card: dict[str, Any]) -> list[str]:
    options = [str(interaction_id) for interaction_id in (card.get("interaction_ids") or []) if interaction_id]
    interaction_id = str(card.get("interaction_id") or "")
    if interaction_id and interaction_id not in options:
        options.insert(0, interaction_id)
    return options


def _tile_display_name(state: dict[str, Any], tile: dict[str, Any]) -> str:
    event = ((state.get("tile_catalog") or {}).get("events") or {}).get(tile.get("event_id")) or {}
    return str(event.get("name") or tile.get("name") or tile.get("id") or "tile")


def _interaction_display_name(state: dict[str, Any], interaction_id: str) -> str:
    interaction = ((state.get("tile_catalog") or {}).get("interactions") or {}).get(interaction_id) or {}
    return str(interaction.get("name") or interaction_id)


def _requirement_labels(state: dict[str, Any], tile: dict[str, Any]) -> list[str]:
    labels = [_interaction_display_name(state, str(interaction_id)) for interaction_id in (tile.get("interaction_ids") or []) if interaction_id]
    shell_count = max(0, int(tile.get("shell_requirement_count") or 0))
    if shell_count:
        labels.append(f"{shell_count} Poulpita shell{'s' if shell_count != 1 else ''}")
    return labels


def _effect_amount(effect: dict[str, Any]) -> int:
    return int(effect.get("amount") or 0)


def _effect_delta(effects: list[dict[str, Any]]) -> dict[str, float]:
    delta = {
        "energy": 0.0,
        "neurons": 0.0,
        "seashells": 0.0,
        "ap": 0.0,
        "shelters": 0.0,
        "surprise_cards": 0.0,
        "removed_tiles": 0.0,
    }
    for effect in effects or []:
        effect_type = str(effect.get("type") or "")
        amount = _effect_amount(effect)
        if effect_type == "gain_energy":
            delta["energy"] += amount
        elif effect_type == "lose_energy":
            delta["energy"] -= amount
        elif effect_type == "gain_neurons":
            delta["neurons"] += amount
        elif effect_type == "lose_neurons":
            delta["neurons"] -= amount
        elif effect_type == "gain_seashells":
            delta["seashells"] += amount
        elif effect_type == "gain_ap":
            delta["ap"] += amount
        elif effect_type == "advance_night":
            delta["ap"] -= amount * 0.25
        elif effect_type == "lose_seashells":
            delta["seashells"] -= amount
        elif effect_type == "lose_ap":
            delta["ap"] -= amount
        elif effect_type in {"lose_half_ap", "lose_all_ap"}:
            delta["ap"] -= 1
        elif effect_type == "place_shelter_token":
            delta["shelters"] += 1
        elif effect_type == "draw_surprise_card":
            delta["surprise_cards"] += 1
        elif effect_type in {"remove_tile", "remove_preys", "remove_tiles_category_here", "remove_tiles_category_adjacent"}:
            delta["removed_tiles"] += 1
    return delta


def _combine_expected_delta(success_probability: float, success_effects: list[dict[str, Any]], failure_effects: list[dict[str, Any]]) -> dict[str, float]:
    success_delta = _effect_delta(success_effects)
    failure_delta = _effect_delta(failure_effects)
    keys = sorted(set(success_delta) | set(failure_delta))
    return {
        key: round(success_probability * float(success_delta.get(key) or 0) + (1 - success_probability) * float(failure_delta.get(key) or 0), 2)
        for key in keys
        if round(success_probability * float(success_delta.get(key) or 0) + (1 - success_probability) * float(failure_delta.get(key) or 0), 2) != 0
    }


def _effect_labels(state: dict[str, Any], effects: list[dict[str, Any]]) -> list[str]:
    labels = []
    categories = (state.get("tile_catalog") or {}).get("categories") or {}
    for effect in effects or []:
        effect_type = str(effect.get("type") or "")
        amount = _effect_amount(effect)
        if effect_type == "gain_energy":
            labels.append(f"+{amount} energy")
        elif effect_type == "gain_neurons":
            labels.append(f"+{amount} neurons")
        elif effect_type == "gain_seashells":
            labels.append(f"+{amount} seashells")
        elif effect_type == "gain_ap":
            ability = _capability(state, str(effect.get("capability_id") or ""))
            labels.append(f"+{amount} AP to {ability.get('name') or effect.get('capability_id') or 'ability'}")
        elif effect_type == "advance_night":
            labels.append(f"+{amount} time step{'s' if amount != 1 else ''}")
        elif effect_type == "place_shelter_token":
            labels.append("place shelter")
        elif effect_type == "draw_surprise_card":
            labels.append("draw surprise")
        elif effect_type == "lose_energy":
            labels.append(f"-{amount} energy")
        elif effect_type == "lose_neurons":
            labels.append(f"-{amount} neurons")
        elif effect_type == "lose_seashells":
            labels.append(f"-{amount} seashells")
        elif effect_type == "lose_ap":
            labels.append(f"-{amount} AP from all")
        elif effect_type == "lose_half_ap":
            labels.append("half AP lost")
        elif effect_type == "lose_all_ap":
            labels.append("all AP lost")
        elif effect_type == "pulpita_move_previous":
            labels.append("Poulpita returns")
        elif effect_type == "pulpita_move_free":
            labels.append("free forced move")
        elif effect_type == "keep_tile":
            labels.append("tile remains")
        elif effect_type == "remove_tile":
            labels.append("tile removed")
        elif effect_type == "move_tile_previous":
            labels.append("tile moves back")
        elif effect_type == "remove_preys":
            category = categories.get(effect.get("category_id")) or {}
            labels.append(f"remove {category.get('name') or 'category'} here")
        elif effect_type in {"remove_tiles_category_here", "remove_tiles_category_adjacent"}:
            category = categories.get(effect.get("category_id")) or {}
            where = "nearby" if effect_type == "remove_tiles_category_adjacent" else "here"
            labels.append(f"remove {category.get('name') or 'category'} {where}")
    return labels


def _actor_candidates_for_entry(state: dict[str, Any], entry: dict[str, Any], preferred_ability_id: str | None = None) -> list[dict[str, Any]]:
    tile = entry.get("tile") or {}
    candidates = []
    ordered = []
    if preferred_ability_id:
        ordered.append(preferred_ability_id)
    ordered.extend(ability_id for ability_id in _all_capability_ids(state) if ability_id not in ordered)
    required = [str(interaction_id) for interaction_id in (tile.get("interaction_ids") or []) if interaction_id]
    for ability_id in ordered:
        capability = _capability(state, ability_id)
        if not capability or not _can_initiate(state, ability_id, tile):
            continue
        selected = _selected_cards_for_requirements(capability, required)
        candidates.append(
            {
                "ability_id": ability_id,
                "ability_name": capability.get("name") or ability_id,
                "can_initiate": True,
                "covers_required_cards_from_hand": selected is not None,
                "missing_card_count_after_hand": 0 if selected is not None else max(0, len(required) - _matched_requirement_count(capability.get("hand") or [], required)),
                "has_control_available": ability_id == state.get("active_capability_id") or _has_control_take_left(capability),
            }
        )
    return candidates


def _interaction_resolution_summary(state: dict[str, Any], entry: dict[str, Any], *, preferred_ability_id: str | None = None) -> dict[str, Any]:
    tile = entry.get("tile") or {}
    probability = _interaction_probability(state, entry)
    success_probability = float(probability.get("success_probability") or 0)
    success_effects = tile.get("success_effects") or []
    failure_effects = tile.get("failure_effects") or []
    return {
        **probability,
        "node_id": entry.get("node_id"),
        "priority": int(tile.get("priority") or 0),
        "compulsory": bool(_tile_category(state, tile).get("compulsory_on_same_node")),
        "requirements": _requirement_labels(state, tile) or ["automatic success"],
        "success_effects": _effect_labels(state, success_effects) or ["remove tile"],
        "counter_attack_effects": _effect_labels(state, tile.get("counter_attack_effects") or []),
        "failure_effects": _effect_labels(state, failure_effects) or ["no configured penalty"],
        "expected_delta": _combine_expected_delta(success_probability, success_effects, failure_effects),
        "actor_candidates": _actor_candidates_for_entry(state, entry, preferred_ability_id),
    }


def _estimated_interaction_team_size(state: dict[str, Any], entry: dict[str, Any], initiator_id: str) -> int:
    required = [
        str(interaction_id)
        for interaction_id in (entry.get("tile") or {}).get("interaction_ids") or []
        if interaction_id
    ]
    if not required:
        return 1
    initiator_cards = list(_capability(state, initiator_id).get("hand") or [])
    if _matched_requirement_count(initiator_cards, required) >= len(required):
        return 1
    other_ids = [
        ability_id
        for ability_id in _all_capability_ids(state)
        if ability_id != initiator_id
        and (
            ability_id == state.get("active_capability_id")
            or _has_control_take_left(_capability(state, ability_id))
        )
    ]
    for supporter_count in range(1, len(other_ids) + 1):
        for supporter_ids in combinations(other_ids, supporter_count):
            cards = list(initiator_cards)
            for ability_id in supporter_ids:
                cards.extend(_capability(state, ability_id).get("hand") or [])
            if _matched_requirement_count(cards, required) >= len(required):
                return 1 + supporter_count
    return 3


def _interaction_team_penalty(state: dict[str, Any], entry: dict[str, Any], initiator_id: str) -> tuple[int, float]:
    team_size = _estimated_interaction_team_size(state, entry, initiator_id)
    penalty = max(0, team_size - 2) * _planner_weight(state, "third_ability_penalty", 45.0)
    return team_size, penalty


def _matched_requirement_count(cards: list[dict[str, Any]], required_interaction_ids: list[str]) -> int:
    remaining = [str(interaction_id) for interaction_id in required_interaction_ids if interaction_id]
    used_card_ids: set[str] = set()
    matched = 0
    for required_id in list(remaining):
        match = next(
            (
                card
                for card in cards
                if str(card.get("card_id") or id(card)) not in used_card_ids
                and required_id in _card_interaction_options(card)
            ),
            None,
        )
        if match:
            used_card_ids.add(str(match.get("card_id") or id(match)))
            matched += 1
    return matched


def _all_cards_in_zones(state: dict[str, Any], zones: list[str]) -> list[dict[str, Any]]:
    cards = []
    for capability in (state.get("capabilities") or {}).values():
        for zone in zones:
            cards.extend(capability.get(zone) or [])
    return cards


def _interaction_probability(state: dict[str, Any], entry: dict[str, Any]) -> dict[str, Any]:
    tile = entry.get("tile") or {}
    required = [str(interaction_id) for interaction_id in (tile.get("interaction_ids") or []) if interaction_id]
    counter_required = [str(interaction_id) for interaction_id in (tile.get("counter_attack_interaction_ids") or []) if interaction_id]
    shell_required = max(0, int(tile.get("shell_requirement_count") or 0))
    carried_shells = max(0, int((state.get("poulpita") or {}).get("seashells") or 0))
    hand_cards = _all_cards_in_zones(state, ["hand"])
    known_cards = _all_cards_in_zones(state, ["hand", "draw_pile", "discard"])
    hand_matches = _matched_requirement_count(hand_cards, required)
    known_matches = _matched_requirement_count(known_cards, required)
    shell_ready = carried_shells >= shell_required
    total_requirements = len(required) + shell_required
    covered_now = hand_matches + min(carried_shells, shell_required)
    covered_known = known_matches + min(carried_shells, shell_required)
    if total_requirements == 0:
        success_probability = 1.0
    elif not shell_ready:
        success_probability = min(0.25, covered_now / total_requirements if total_requirements else 0)
    elif hand_matches >= len(required):
        success_probability = 0.95
    elif known_matches >= len(required):
        success_probability = 0.65
    else:
        success_probability = max(0.05, 0.65 * (covered_known / total_requirements))
    counter_probability = 0.0
    if counter_required:
        counter_hand_matches = _matched_requirement_count(hand_cards, required + counter_required)
        counter_known_matches = _matched_requirement_count(known_cards, required + counter_required)
        counter_total = len(required) + len(counter_required) + shell_required
        if shell_ready and counter_hand_matches >= len(required) + len(counter_required):
            counter_probability = 0.9
        elif shell_ready and counter_known_matches >= len(required) + len(counter_required):
            counter_probability = 0.55
        else:
            counter_probability = max(0.03, success_probability * 0.35)
    return {
        "tile_instance_id": (entry.get("instance") or {}).get("instance_id"),
        "tile_name": _tile_display_name(state, tile),
        "success_probability": round(success_probability, 2),
        "counter_attack_probability": round(counter_probability, 2) if counter_required else None,
        "required_card_count": len(required),
        "required_shell_count": shell_required,
        "requirements_covered_from_hands": covered_now,
        "requirements_covered_from_known_decks": covered_known,
        "method": "omniscient_known_cards_v1",
    }


def _known_shelter_nodes(state: dict[str, Any]) -> set[str]:
    nodes = set()
    for node_id, raw in (state.get("shelters") or {}).items():
        count = int(raw.get("count") or 0) if isinstance(raw, dict) else int(raw or 0)
        if count > 0:
            nodes.add(str(node_id))
    return nodes


def _node_has_known_compulsory_blocker(state: dict[str, Any], node_id: str) -> bool:
    if _compulsory_choices_on_node(state, str(node_id), highest_only=False):
        return True
    catalog_tiles = ((state.get("tile_catalog") or {}).get("tiles") or {})
    return any(
        instance.get("face_up")
        and (
            str(instance.get("token_type") or "") == "octopus"
            or str(instance.get("tile_id") or "") in {"octopus", "__octopus_token__"}
            or str((catalog_tiles.get(instance.get("tile_id")) or {}).get("token_type") or "") == "octopus"
        )
        for instance in (state.get("tiles") or {}).get(str(node_id), []) or []
    )


def _safe_route_to_closest_shelter(state: dict[str, Any], start_node_id: str) -> dict[str, Any] | None:
    """Find the shortest known route that does not enter an unresolved compulsory node."""
    start_node_id = str(start_node_id or "")
    shelter_nodes = _known_shelter_nodes(state)
    if not start_node_id or not shelter_nodes:
        return None
    safe_shelters = {
        node_id for node_id in shelter_nodes if not _node_has_known_compulsory_blocker(state, node_id)
    }
    if start_node_id in safe_shelters:
        return {"shelter_node_id": start_node_id, "path": [start_node_id], "distance": 0}
    if not safe_shelters:
        return None

    adjacency = (state.get("map") or {}).get("adjacency") or {}
    frontier = [start_node_id]
    previous: dict[str, str | None] = {start_node_id: None}
    while frontier:
        node_id = frontier.pop(0)
        for raw_next_node_id in adjacency.get(node_id, []) or []:
            next_node_id = str(raw_next_node_id)
            if next_node_id in previous or _node_has_known_compulsory_blocker(state, next_node_id):
                continue
            previous[next_node_id] = node_id
            if next_node_id in safe_shelters:
                path = [next_node_id]
                while previous[path[-1]] is not None:
                    path.append(str(previous[path[-1]]))
                path.reverse()
                return {
                    "shelter_node_id": next_node_id,
                    "path": path,
                    "distance": len(path) - 1,
                }
            frontier.append(next_node_id)
    return None


def _distance_to_closest_shelter(state: dict[str, Any], start_node_id: str) -> int | None:
    route = _safe_route_to_closest_shelter(state, start_node_id)
    return int(route["distance"]) if route else None


def _shelter_return_context(state: dict[str, Any], start_node_id: str | None = None) -> dict[str, Any]:
    current_node_id = str(start_node_id or (state.get("poulpita") or {}).get("node_id") or "")
    route = _safe_route_to_closest_shelter(state, current_node_id)
    spent = int(state.get("night_time_spent") or 0)
    total = max(1, int(state.get("night_time_total") or 24))
    shelter_at = min(total, max(0, int(state.get("night_shelter_available_at") or 16)))
    move_time = max(1, int(_action_cost(state, "move").get("time_cost") or 0))
    distance = int(route.get("distance") or 0) if route else None
    travel_time = distance * move_time if distance is not None else total
    safety_margin = max(1, move_time)
    return_start = max(0, shelter_at - travel_time - safety_margin)
    per_step = _planner_weight(state, "late_shelter_urgency", 8.0)
    urgency = 0.0
    if route and spent >= return_start:
        urgency = (spent - return_start + 1) * per_step
        if spent >= shelter_at:
            urgency += (spent - shelter_at + 1) * per_step
        if spent >= total - max(2, travel_time):
            urgency += per_step * 4
    elif not route and spent >= shelter_at:
        urgency = (spent - shelter_at + 1) * per_step
        if spent >= total - 2:
            urgency += per_step * 4
    return {
        "route": route,
        "distance": distance,
        "travel_time": travel_time,
        "return_start": return_start,
        "urgency": min(240.0, urgency),
        "should_return": bool(route and distance and urgency > 0),
        "next_node_id": route["path"][1] if route and len(route.get("path") or []) > 1 else None,
    }


def _merge_deltas(deltas: list[dict[str, float]]) -> dict[str, float]:
    merged: dict[str, float] = {}
    for delta in deltas:
        for key, value in (delta or {}).items():
            merged[key] = round(float(merged.get(key) or 0) + float(value or 0), 2)
    return {key: value for key, value in merged.items() if value}


def _delta_score(delta: dict[str, float]) -> float:
    return (
        float(delta.get("energy") or 0) * 8
        + float(delta.get("neurons") or 0) * 5
        + float(delta.get("seashells") or 0) * 4
        + float(delta.get("shelters") or 0) * 18
        + float(delta.get("surprise_cards") or 0) * 6
        + float(delta.get("removed_tiles") or 0) * 3
        + float(delta.get("ap") or 0)
    )


def _format_delta(delta: dict[str, float]) -> str:
    if not delta:
        return "no expected resource change"
    labels = []
    names = {
        "energy": "energy",
        "neurons": "neurons",
        "seashells": "seashells",
        "ap": "AP",
        "shelters": "shelters",
        "surprise_cards": "surprise cards",
        "removed_tiles": "removed tiles",
    }
    for key in ["energy", "neurons", "seashells", "ap", "shelters", "surprise_cards", "removed_tiles"]:
        value = delta.get(key)
        if value:
            labels.append(f"{value:+g} {names.get(key, key)}")
    return ", ".join(labels)


def _interaction_step_labels(state: dict[str, Any], entries: list[dict[str, Any]], preferred_ability_id: str | None = None) -> list[str]:
    labels = []
    for entry in entries:
        summary = _interaction_resolution_summary(state, entry, preferred_ability_id=preferred_ability_id)
        actors = [candidate["ability_name"] for candidate in summary.get("actor_candidates") or [] if candidate.get("has_control_available")]
        actor_label = actors[0] if actors else "manual support"
        requirements = ", ".join(summary.get("requirements") or [])
        rewards = ", ".join(summary.get("success_effects") or [])
        expected_delta = _format_delta(summary.get("expected_delta") or {})
        labels.append(
            f"Resolve {summary['tile_name']} with {actor_label}: {round(float(summary.get('success_probability') or 0) * 100)}%, needs {requirements}, success {rewards}, EV {expected_delta}"
        )
    return labels


def _node_followup_score(state: dict[str, Any], node_id: str, ability_id: str) -> tuple[float, list[dict[str, Any]], int | None]:
    entries = _compulsory_choices_on_node(state, node_id, highest_only=False)
    summaries = [_interaction_resolution_summary(state, entry, preferred_ability_id=ability_id) for entry in entries]
    score = 0.0
    for summary in summaries:
        actor_candidates = summary.get("actor_candidates") or []
        preferred_can_act = any(candidate.get("ability_id") == ability_id for candidate in actor_candidates)
        any_actor = bool(actor_candidates)
        score += float(summary.get("success_probability") or 0) * 30
        score += _delta_score(summary.get("expected_delta") or {})
        if summary.get("compulsory"):
            score += 15
        if preferred_can_act:
            score += 18
        elif any_actor:
            score += 6
        else:
            score -= 30
    shelter_distance = _distance_to_closest_shelter(state, node_id)
    if shelter_distance is not None:
        score += max(0, 10 - shelter_distance * 2)
        score += _night_lateness_score(state) * max(0.0, (5.0 - min(5, shelter_distance)) / 5.0)
    return score, entries, shelter_distance


def _plan_statistics(
    state: dict[str, Any],
    *,
    commands: list[dict[str, Any]] | None = None,
    interactions: list[dict[str, Any]] | None = None,
    assumptions: list[str] | None = None,
) -> dict[str, Any]:
    commands = commands or []
    interactions = interactions or []
    interaction_probabilities = [_interaction_probability(state, entry) for entry in interactions]
    interaction_summaries = [_interaction_resolution_summary(state, entry) for entry in interactions]
    expected_resource_delta = _merge_deltas([summary.get("expected_delta") or {} for summary in interaction_summaries])
    success_probability = 1.0
    for probability in interaction_probabilities:
        success_probability *= float(probability.get("success_probability") or 0)
    estimated_time_steps = 0
    estimated_actions = 0
    estimated_take_controls = 0
    for command in commands:
        command_type = str(command.get("type") or "")
        if command_type == "take_control":
            estimated_take_controls += 1
        elif command_type == "move_poulpita":
            estimated_actions += 1
            estimated_time_steps += _action_cost(state, "move")["time_cost"]
        elif command_type == "start_interaction":
            estimated_actions += 1
            estimated_time_steps += _action_cost(state, "interact")["time_cost"]
        elif command_type == "collect_action_points":
            estimated_actions += 1
            estimated_time_steps += _action_cost(state, "gain_ap")["time_cost"]
        elif command_type == "draw_action_card":
            estimated_actions += 1
            estimated_time_steps += _action_cost(state, "draw")["time_cost"]
        elif command_type in {"buy_hand_size_upgrade", "buy_poulpita_size", "end_night", "end_day"}:
            pass
    if not interaction_probabilities:
        success_probability = 1.0
    return {
        "success_probability": round(success_probability, 2),
        "interaction_probabilities": interaction_probabilities,
        "estimated_take_controls": estimated_take_controls,
        "estimated_actions": estimated_actions,
        "estimated_time_steps": estimated_time_steps,
        "expected_ap_roll": _expected_ap_roll(state),
        "expected_resource_delta": expected_resource_delta,
        "interaction_summaries": interaction_summaries,
        "planning_depth_take_controls": _planning_depth_take_controls(state),
        "assumptions": assumptions or ["Surprise cards are modeled optimistically as no-op until one is actually drawn."],
    }


def _is_action_command(command_type: str) -> bool:
    return command_type in {
        "collect_action_points",
        "draw_action_card",
        "move_poulpita",
        "start_interaction",
    }


def _command_capability_id(command: dict[str, Any]) -> str:
    payload = command.get("payload") or {}
    return str(payload.get("capability_id") or "")


def _proposal_command_key(command: dict[str, Any]) -> str:
    command_type = str(command.get("type") or "")
    payload = command.get("payload") if isinstance(command.get("payload"), dict) else {}
    return f"{command_type}:{sorted((payload or {}).items())}"


def _proposal_efficiency_commands(proposal: dict[str, Any]) -> list[dict[str, Any]]:
    commands: list[dict[str, Any]] = []
    seen: set[str] = set()
    for command in proposal.get("commands") or []:
        if not isinstance(command, dict):
            continue
        key = _proposal_command_key(command)
        if key not in seen:
            commands.append(command)
            seen.add(key)
    for step in proposal.get("plan_chain") or []:
        public_command = (step or {}).get("public_command")
        if not isinstance(public_command, dict):
            continue
        key = _proposal_command_key(public_command)
        if key not in seen:
            commands.append(public_command)
            seen.add(key)
    return commands


def _efficiency_metrics(state: dict[str, Any], commands: list[dict[str, Any]]) -> dict[str, Any]:
    phase = str(state.get("phase") or "")
    active_id = str(state.get("active_capability_id") or "")
    current_active = _capability(state, active_id) if active_id else {}
    switched_to = ""
    wasted_current_actions = 0
    if phase == "night_action" and active_id and current_active:
        first_take_control = next((command for command in commands if str(command.get("type") or "") == "take_control"), None)
        if first_take_control:
            switched_to = _command_capability_id(first_take_control)
            if switched_to and switched_to != active_id:
                wasted_current_actions = max(0, _action_slots_left(current_active))

    action_capacity_by_ability: dict[str, int] = {}
    actions_used_by_ability: dict[str, int] = {}
    active_control_by_ability: dict[str, bool] = {}
    if phase == "night_action" and active_id:
        action_capacity_by_ability[active_id] = max(0, _action_slots_left(current_active))
        active_control_by_ability[active_id] = True
    for command in commands:
        command_type = str(command.get("type") or "")
        ability_id = _command_capability_id(command)
        if command_type == "take_control" and ability_id:
            capability = _capability(state, ability_id)
            action_capacity_by_ability[ability_id] = int(capability.get("max_actions_per_control") or 0)
            active_control_by_ability[ability_id] = True
        elif _is_action_command(command_type) and ability_id:
            capability = _capability(state, ability_id)
            action_capacity_by_ability.setdefault(
                ability_id,
                max(0, _action_slots_left(capability)) if ability_id == active_id else int(capability.get("max_actions_per_control") or 0),
            )
            actions_used_by_ability[ability_id] = actions_used_by_ability.get(ability_id, 0) + 1

    used_actions = sum(actions_used_by_ability.values())
    planned_capacity = sum(
        capacity
        for ability_id, capacity in action_capacity_by_ability.items()
        if active_control_by_ability.get(ability_id) and (actions_used_by_ability.get(ability_id, 0) > 0 or ability_id == switched_to or ability_id == active_id)
    )
    if used_actions <= 0:
        efficiency = 1.0
    else:
        utilization = min(1.0, used_actions / max(1, planned_capacity))
        switch_penalty = min(1.0, wasted_current_actions / max(1, int(current_active.get("max_actions_per_control") or 1))) if wasted_current_actions else 0.0
        efficiency = max(0.0, round(utilization - 0.35 * switch_penalty, 2))
    return {
        "efficiency": round(efficiency, 2),
        "planned_action_capacity": planned_capacity,
        "planned_actions_used": used_actions,
        "wasted_current_actions": wasted_current_actions,
        "initiative_switch_penalty": round(min(1.0, wasted_current_actions / max(1, int(current_active.get("max_actions_per_control") or 1))) if wasted_current_actions else 0.0, 2),
        "actions_used_by_ability": actions_used_by_ability,
    }


def _attach_plan_metrics(state: dict[str, Any], proposal: dict[str, Any]) -> dict[str, Any]:
    statistics = dict(proposal.get("statistics") or {})
    commands = _proposal_efficiency_commands(proposal)
    efficiency = _efficiency_metrics(state, commands)
    expected_delta = statistics.get("expected_resource_delta") or (proposal.get("expected_resources") or {}).get("expected_resource_delta") or {}
    base_global_score = _global_state_score(state)
    simulated = _clone_simulation_state(state)
    for command in commands:
        _simulate_public_command(simulated, command)
    expected_gain_score = _global_state_score(simulated)
    expected_delta_score = _weighted_expected_gain(state, expected_delta)
    objective_bonus = 25.0 if proposal.get("objective_effect") else 0.0
    confidence = max(0.0, min(1.0, float(statistics.get("success_probability") if statistics.get("success_probability") is not None else proposal.get("confidence") if proposal.get("confidence") is not None else 1.0)))
    efficiency_score = float(efficiency["efficiency"])
    aggregate_score = round(
        _planner_weight(state, "efficiency", 35.0) * efficiency_score
        + _planner_weight(state, "confidence", 35.0) * confidence
        + _planner_weight(state, "expected_gain", 30.0) * ((expected_gain_score - base_global_score + expected_delta_score + objective_bonus) / 20.0),
        2,
    )
    statistics.update(
        {
            **efficiency,
            "confidence_score": round(confidence, 2),
            "expected_gain_score": expected_gain_score,
            "base_global_score": base_global_score,
            "projected_global_score": expected_gain_score,
            "global_score_delta": round(expected_gain_score - base_global_score, 2),
            "global_score_components": _global_state_score_components(simulated),
            "planner_score": aggregate_score,
            "pareto_axes": {
                "efficiency": round(efficiency_score, 2),
                "confidence": round(confidence, 2),
                "expected_gain": round(expected_gain_score - base_global_score + expected_delta_score + objective_bonus, 2),
            },
        }
    )
    proposal["statistics"] = statistics
    proposal["plan_chain"] = _attach_step_metrics(state, proposal, confidence=confidence)
    proposal["_score"] = aggregate_score
    return proposal


def _attach_step_metrics(
    state: dict[str, Any],
    proposal: dict[str, Any],
    *,
    confidence: float,
) -> list[dict[str, Any]]:
    chain = [dict(step) for step in (proposal.get("plan_chain") or [])]
    active_id = str(state.get("active_capability_id") or "")
    active_capability = _capability(state, active_id) if active_id else {}
    active_capacity = int(active_capability.get("max_actions_per_control") or 0)
    prefix_commands: list[dict[str, Any]] = []
    for index, step in enumerate(chain):
        public_command = step.get("public_command")
        if isinstance(public_command, dict):
            prefix_commands.append(public_command)
        prefix_before = prefix_commands[:-1] if isinstance(public_command, dict) else prefix_commands
        prefix_metrics = _efficiency_metrics(state, prefix_commands)
        step_efficiency = float(prefix_metrics.get("efficiency") or 1)
        command_type = str((public_command or {}).get("type") or step.get("command_type") or "")
        command_ability_id = _command_capability_id(public_command or {})
        if command_type == "take_control" and active_id and command_ability_id and command_ability_id != active_id and active_capacity > 0:
            used_before_switch = sum(
                1
                for command in prefix_before
                if _is_action_command(str(command.get("type") or "")) and _command_capability_id(command) == active_id
            )
            step_efficiency = round(min(1.0, max(0.0, used_before_switch / max(1, active_capacity))), 2)
        elif _is_action_command(command_type) and command_ability_id == active_id:
            step_efficiency = 1.0
        simulated = _clone_simulation_state(state)
        for command in prefix_commands:
            _simulate_public_command(simulated, command)
        projected_global_score = _global_state_score(simulated)
        step["statistics"] = {
            **prefix_metrics,
            "efficiency": round(step_efficiency, 2),
            "confidence_score": round(confidence, 2),
            "risk_score": round(1.0 - confidence, 2),
            "expected_gain_score": projected_global_score,
            "projected_global_score": projected_global_score,
            "global_score_delta": round(projected_global_score - _global_state_score(state), 2),
            "global_score_components": _global_state_score_components(simulated),
            "step_index": index,
        }
    return chain


def _legal_active_actor(state: dict[str, Any]) -> str | None:
    active_id = str(state.get("active_capability_id") or "")
    if active_id not in (state.get("capabilities") or {}):
        return None
    return active_id if _action_slots_left(_capability(state, active_id)) > 0 else None


def _forced_actor_candidates(state: dict[str, Any], entries: list[dict[str, Any]]) -> list[tuple[str, bool]]:
    active_id = str(state.get("active_capability_id") or "")
    active_can_continue = (
        active_id in (state.get("capabilities") or {})
        and _action_slots_left(_capability(state, active_id)) > 0
        and any(_can_initiate(state, active_id, entry.get("tile") or {}) for entry in entries)
    )
    if active_can_continue:
        return [(active_id, False)]
    candidates: list[tuple[str, bool]] = []
    for ability_id in _all_capability_ids(state):
        if ability_id == active_id:
            continue
        capability = _capability(state, ability_id)
        if _has_control_take_left(capability) and any(
            _can_initiate(state, ability_id, entry.get("tile") or {}) for entry in entries
        ):
            candidates.append((ability_id, True))
    return candidates


def _interaction_commands(ability_id: str, entry: dict[str, Any]) -> list[dict[str, Any]]:
    tile = entry["tile"]
    commands = [
        {
            "type": "start_interaction",
            "payload": {
                "capability_id": ability_id,
                "tile_instance_id": entry["instance"].get("instance_id"),
                "auto_select_cards": True,
            },
        }
    ]
    commands.append({"type": "resolve_interaction", "payload": {"capability_id": ability_id, "auto_select_cards": True, "confirm_only": True}})
    if _interaction_requirements(tile) == 0:
        commands.append({"type": "resolve_interaction", "payload": {"capability_id": ability_id}})
    return commands


def _can_active_resolve_interaction(state: dict[str, Any], ability_id: str, entry: dict[str, Any]) -> bool:
    tile = entry.get("tile") or {}
    required = [str(interaction_id) for interaction_id in (tile.get("interaction_ids") or []) if interaction_id]
    shell_required = max(0, int(tile.get("shell_requirement_count") or 0))
    carried_shells = max(0, int((state.get("poulpita") or {}).get("seashells") or 0))
    return carried_shells >= shell_required and _selected_cards_for_requirements(_capability(state, ability_id), required) is not None


def _interaction_rollout_commands(state: dict[str, Any], ability_id: str, entry: dict[str, Any]) -> list[dict[str, Any]]:
    commands = [
        {
            "type": "start_interaction",
            "payload": {
                "capability_id": ability_id,
                "tile_instance_id": entry["instance"].get("instance_id"),
                "auto_select_cards": True,
            },
        }
    ]
    if _interaction_requirements(entry.get("tile") or {}) == 0 or _can_active_resolve_interaction(state, ability_id, entry):
        commands.append({"type": "resolve_interaction", "payload": {"capability_id": ability_id, "auto_select_cards": True, "confirm_only": True}})
    if _interaction_requirements(entry.get("tile") or {}) == 0:
        commands.append({"type": "resolve_interaction", "payload": {"capability_id": ability_id}})
    return commands


def _simulated_tile_entry(state: dict[str, Any], tile_instance_id: str) -> dict[str, Any] | None:
    catalog_tiles = (state.get("tile_catalog") or {}).get("tiles") or {}
    for node_id, entries in (state.get("tiles") or {}).items():
        for instance in entries or []:
            if str(instance.get("instance_id") or "") == tile_instance_id:
                tile = catalog_tiles.get(instance.get("tile_id")) or {}
                if tile:
                    return {"instance": instance, "tile": tile, "node_id": str(node_id)}
    return None


def _clone_simulation_state(state: dict[str, Any]) -> dict[str, Any]:
    return deepcopy(state)


def _simulate_play_cards_for_requirements(state: dict[str, Any], ability_id: str, required_interaction_ids: list[str]) -> None:
    capability = _capability(state, ability_id)
    interaction = state.get("interaction") or {}
    if not capability or not interaction:
        return
    remaining = [str(interaction_id) for interaction_id in required_interaction_ids if interaction_id]
    played_cards = interaction.setdefault("played_cards", [])
    for card in list(capability.get("hand") or []):
        if not remaining:
            break
        match = next((interaction_id for interaction_id in remaining if interaction_id in _card_interaction_options(card)), None)
        if not match:
            continue
        remaining.remove(match)
        capability["hand"] = [entry for entry in capability.get("hand") or [] if str(entry.get("card_id") or "") != str(card.get("card_id") or "")]
        played_cards.append({**card, "interaction_id": match, "interaction_ids": _card_interaction_options(card), "capability_id": ability_id})


def _simulate_auto_discard_for_draw(state: dict[str, Any], capability: dict[str, Any]) -> None:
    hand = capability.get("hand") or []
    if not hand:
        return
    required = _missing_support_ids_for_open_interaction(state) if state.get("interaction") else []
    discard_index = 0
    if required:
        for index, card in enumerate(hand):
            if not any(interaction_id in required for interaction_id in _card_interaction_options(card)):
                discard_index = index
                break
    discarded = hand[discard_index]
    capability["hand"] = [card for index, card in enumerate(hand) if index != discard_index]
    capability.setdefault("discard", []).append(discarded)


def _simulate_remove_tiles_by_category(state: dict[str, Any], node_id: str, category_id: str) -> int:
    catalog_tiles = (state.get("tile_catalog") or {}).get("tiles") or {}
    catalog_events = (state.get("tile_catalog") or {}).get("events") or {}
    kept_tiles = []
    removed = 0
    for tile_instance in (state.get("tiles") or {}).get(node_id, []) or []:
        tile = catalog_tiles.get(tile_instance.get("tile_id")) or {}
        event = tile.get("event") or catalog_events.get(tile.get("event_id")) or {}
        if str(event.get("category_id") or "") == str(category_id or ""):
            removed += 1
        else:
            kept_tiles.append(tile_instance)
    state.setdefault("tiles", {})[node_id] = kept_tiles
    return removed


def _simulate_surprise_card_ids_for_costs(capability: dict[str, Any], costs: list[dict[str, Any]]) -> list[str]:
    selected: list[str] = []
    selected_ids: set[str] = set()
    for cost in costs or []:
        if str(cost.get("type") or "") != "play_cards":
            continue
        remaining = [str(interaction_id) for interaction_id in cost.get("interaction_ids") or [] if interaction_id]
        for card in capability.get("hand") or []:
            card_id = str(card.get("card_id") or "")
            if not remaining or not card_id or card_id in selected_ids:
                continue
            match = next((interaction_id for interaction_id in remaining if interaction_id in _card_interaction_options(card)), None)
            if match:
                remaining.remove(match)
                selected.append(card_id)
                selected_ids.add(card_id)
    return selected


def _simulate_pay_surprise_costs(state: dict[str, Any], payload: dict[str, Any], costs: list[dict[str, Any]]) -> None:
    ability_id = str(payload.get("capability_id") or "")
    selected_card_ids = {str(card_id) for card_id in (payload.get("card_ids") or []) if card_id}
    if payload.get("auto_select_cards") and ability_id:
        selected_card_ids = set(_simulate_surprise_card_ids_for_costs(_capability(state, ability_id), costs))
    for cost in costs or []:
        cost_type = str(cost.get("type") or "")
        if cost_type == "play_cards":
            capability = _capability(state, ability_id)
            if not capability:
                continue
            remaining = [str(interaction_id) for interaction_id in cost.get("interaction_ids") or [] if interaction_id]
            next_hand = []
            played = []
            for hand_card in capability.get("hand") or []:
                card_id = str(hand_card.get("card_id") or "")
                if card_id in selected_card_ids:
                    matching_interaction_id = next((interaction_id for interaction_id in _card_interaction_options(hand_card) if interaction_id in remaining), "")
                    if matching_interaction_id:
                        remaining.remove(matching_interaction_id)
                        played.append({**hand_card, "interaction_id": matching_interaction_id, "interaction_ids": _card_interaction_options(hand_card)})
                        continue
                next_hand.append(hand_card)
            capability["hand"] = next_hand
            capability.setdefault("discard", []).extend(played)
        elif cost_type == "pay_ap":
            payer_id = str(cost.get("capability_id") or ability_id)
            payer = _capability(state, payer_id)
            amount = max(1, int(cost.get("amount") or 1))
            if payer:
                payer["pa"] = max(0, int(payer.get("pa") or 0) - amount)


def _simulate_apply_surprise_effects(state: dict[str, Any], effects: list[dict[str, Any]]) -> None:
    poulpita = state.setdefault("poulpita", {})
    current_node_id = str(poulpita.get("node_id") or "")
    adjacency = (state.get("map") or {}).get("adjacency") or {}
    for effect in effects or []:
        effect_type = str(effect.get("type") or "")
        amount = max(0, int(effect.get("amount") or 0))
        if effect_type == "gain_ap":
            capability = _capability(state, str(effect.get("capability_id") or ""))
            if capability:
                capability["pa"] = int(capability.get("pa") or 0) + amount
        elif effect_type == "gain_neurons":
            poulpita["neurons"] = int(poulpita.get("neurons") or 0) + amount
        elif effect_type == "advance_night":
            _simulate_advance_time(state, amount)
        elif effect_type == "gain_energy":
            poulpita["energy"] = int(poulpita.get("energy") or 0) + amount
        elif effect_type == "lose_energy":
            poulpita["energy"] = max(0, int(poulpita.get("energy") or 0) - amount)
            if int(poulpita.get("energy") or 0) <= 0:
                state["phase"] = "postgame"
                state["outcome"] = "lost"
                state["loss_reason"] = "poulpita_no_energy"
        elif effect_type == "remove_tiles_category_here":
            _simulate_remove_tiles_by_category(state, current_node_id, str(effect.get("category_id") or ""))
        elif effect_type == "remove_tiles_category_adjacent":
            for node_id in adjacency.get(current_node_id, []) or []:
                _simulate_remove_tiles_by_category(state, str(node_id), str(effect.get("category_id") or ""))


def _apply_success_effects_to_simulation(state: dict[str, Any], entry: dict[str, Any]) -> None:
    state.setdefault("poulpita", {})
    node_id = str(entry.get("node_id") or "")
    tile = entry.get("tile") or {}
    for effect in tile.get("success_effects") or []:
        effect_type = str(effect.get("type") or "")
        amount = int(effect.get("amount") or 0)
        if effect_type == "gain_energy":
            state["poulpita"]["energy"] = int(state["poulpita"].get("energy") or 0) + amount
        elif effect_type == "gain_neurons":
            state["poulpita"]["neurons"] = int(state["poulpita"].get("neurons") or 0) + amount
        elif effect_type == "gain_seashells":
            state["poulpita"]["seashells"] = int(state["poulpita"].get("seashells") or 0) + amount
        elif effect_type == "place_shelter_token" and node_id:
            shelter = state.setdefault("shelters", {}).setdefault(node_id, {"count": 0, "seashells": 0, "secure": False})
            if isinstance(shelter, dict):
                shelter["count"] = int(shelter.get("count") or 0) + 1
        elif effect_type == "draw_surprise_card":
            draw_pile = state.get("surprise_draw_pile") or []
            if draw_pile:
                card_id = str(draw_pile.pop(0))
                card = ((state.get("tile_catalog") or {}).get("surprise_cards") or {}).get(card_id) or {}
                if card:
                    state["pending_surprise"] = {
                        "card_id": card_id,
                        "card": deepcopy(card),
                    }
            state["surprise_deck_exhausted"] = not bool(draw_pile)


def _simulate_tile_visibility(state: dict[str, Any]) -> None:
    current_node_id = str((state.get("poulpita") or {}).get("node_id") or "")
    if not current_node_id:
        return
    adjacency = (state.get("map") or {}).get("adjacency") or {}
    reveal_limits: dict[str, int | None] = {current_node_id: None}
    for adjacent_node_id in adjacency.get(current_node_id, []) or []:
        reveal_limits[str(adjacent_node_id)] = 2
    visited = {current_node_id, *[str(node_id) for node_id in adjacency.get(current_node_id, []) or []]}
    for adjacent_node_id in adjacency.get(current_node_id, []) or []:
        for step_two_node_id in adjacency.get(adjacent_node_id, []) or []:
            step_two_node_id = str(step_two_node_id)
            if step_two_node_id not in visited:
                reveal_limits[step_two_node_id] = 1
    for node_id, reveal_limit in reveal_limits.items():
        revealed = sum(1 for instance in (state.get("tiles") or {}).get(node_id, []) or [] if instance.get("face_up"))
        for instance in (state.get("tiles") or {}).get(node_id, []) or []:
            if instance.get("face_up"):
                continue
            if reveal_limit is None or revealed < reveal_limit:
                instance["face_up"] = True
                revealed += 1


def _simulate_advance_time(state: dict[str, Any], chunks: int) -> None:
    if state.get("phase") not in {"night_idle", "night_action"}:
        return
    previous_time = int(state.get("night_time_spent") or 0)
    next_time = previous_time + max(0, int(chunks or 0))
    state["night_time_spent"] = next_time
    night_time_total = max(1, int(state.get("night_time_total") or 24))
    if previous_time <= night_time_total < next_time:
        poulpita = state.setdefault("poulpita", {})
        poulpita["energy"] = max(0, int(poulpita.get("energy") or 0) - 1)


def _current_shelter_growth_discount(state: dict[str, Any]) -> int:
    current_node_id = str((state.get("poulpita") or {}).get("node_id") or "")
    raw = (state.get("shelters") or {}).get(current_node_id)
    if not isinstance(raw, dict):
        return 0
    return max(0, int(raw.get("seashells") or 0) - 2)


def _simulate_deck_exchange_upgrade(capability: dict[str, Any], upgrade: dict[str, Any]) -> None:
    for entry in upgrade.get("remove_cards") or []:
        interaction_id = str(entry.get("interaction_id") or "")
        remaining = max(0, int(entry.get("count") or 0))
        for zone in ["draw_pile", "discard", "hand"]:
            kept = []
            for card in capability.get(zone) or []:
                if remaining > 0 and interaction_id in _card_interaction_options(card):
                    remaining -= 1
                else:
                    kept.append(card)
            capability[zone] = kept
    capability_id = str(capability.get("id") or "")
    added = []
    for entry in upgrade.get("add_cards") or []:
        interaction_ids = [str(interaction_id) for interaction_id in (entry.get("interaction_ids") or []) if interaction_id]
        if not interaction_ids:
            continue
        for index in range(max(0, int(entry.get("count") or 0))):
            added.append(
                {
                    "card_id": f"planned_upgrade_{capability_id}_{len(added)}_{index}",
                    "interaction_id": interaction_ids[0],
                    "interaction_ids": interaction_ids,
                    "owner_capability_id": capability_id,
                    "upgraded": True,
                }
            )
    capability.setdefault("draw_pile", []).extend(added)


def _simulate_reshuffle_and_deal_starting_hand(capability: dict[str, Any]) -> None:
    cards = []
    for zone in ["hand", "draw_pile", "discard"]:
        cards.extend(deepcopy(capability.get(zone) or []))
    hand_limit = max(0, int(capability.get("current_max_cards_in_hand") or capability.get("default_max_cards_in_hand") or 3))
    capability["hand"] = cards[:hand_limit]
    capability["draw_pile"] = cards[hand_limit:]
    capability["discard"] = []


def _poulpita_size_upgrade_cost(state: dict[str, Any]) -> tuple[int | None, dict[str, Any] | None]:
    poulpita = state.get("poulpita") or {}
    sizes = ((state.get("tile_catalog") or {}).get("poulpita_panel") or {}).get("sizes") or []
    next_size_index = int(poulpita.get("size_index") or 0) + 1
    if next_size_index >= len(sizes):
        return None, None
    next_size = sizes[next_size_index] or {}
    base_cost = max(1, int(next_size.get("energy_cost") or 1))
    cost = max(0, base_cost - _current_shelter_growth_discount(state))
    return cost, next_size


def _can_end_night_now(state: dict[str, Any]) -> bool:
    if state.get("phase") != "night_action":
        return False
    current_node_id = str((state.get("poulpita") or {}).get("node_id") or "")
    shelter_at = int(state.get("night_shelter_available_at") or 16)
    catalog_tiles = ((state.get("tile_catalog") or {}).get("tiles") or {})
    has_blocker = any(
        str(instance.get("token_type") or "") == "octopus"
        or str(instance.get("tile_id") or "") in {"octopus", "__octopus_token__"}
        or str((catalog_tiles.get(instance.get("tile_id")) or {}).get("token_type") or "") == "octopus"
        or _tile_category(state, catalog_tiles.get(instance.get("tile_id")) or {}).get("compulsory_on_same_node")
        for instance in (state.get("tiles") or {}).get(current_node_id, []) or []
    )
    return (
        bool(state.get("active_capability_id"))
        and _state_has_shelter(state, current_node_id)
        and int(state.get("night_time_spent") or 0) >= shelter_at
        and not has_blocker
    )


def _night_lateness_score(state: dict[str, Any], start_node_id: str | None = None) -> float:
    return float(_shelter_return_context(state, start_node_id).get("urgency") or 0.0)


def _mark_simulated_loss_if_needed(state: dict[str, Any]) -> None:
    if state.get("phase") not in {"night_idle", "night_action"}:
        return
    if int((state.get("poulpita") or {}).get("energy") or 0) <= 0:
        state["phase"] = "game_over"
        state["game_outcome"] = "lost"
        state["game_over_reason"] = "poulpita_no_energy"
        return
    active_id = str(state.get("active_capability_id") or "")
    if not active_id or _action_slots_left(_capability(state, active_id)) > 0:
        return
    another_control_available = any(
        ability_id != active_id and _has_control_take_left(_capability(state, ability_id))
        for ability_id in _all_capability_ids(state)
    )
    if not another_control_available:
        state["phase"] = "game_over"
        state["game_outcome"] = "lost"
        state["game_over_reason"] = "no_controls_or_actions"


def _simulate_public_command(state: dict[str, Any], command: dict[str, Any]) -> None:
    command_type = str(command.get("type") or "")
    payload = command.get("payload") or {}
    ability_id = str(payload.get("capability_id") or state.get("active_capability_id") or "")
    capability = _capability(state, ability_id)
    if command_type == "take_control" and ability_id:
        state["active_capability_id"] = ability_id
        state["phase"] = "night_action"
        capability["control_takes_this_night"] = int(capability.get("control_takes_this_night") or 0) + 1
        capability["actions_taken_this_control"] = 0
    elif command_type == "collect_action_points" and ability_id:
        cost = _action_cost(state, "gain_ap")
        capability["pa"] = int(capability.get("pa") or 0) + _expected_ap_roll(state)
        _simulate_spend_action(state, capability, cost)
    elif command_type == "move_poulpita" and ability_id:
        cost = _action_cost(state, "move")
        _simulate_spend_action(state, capability, cost)
        target_node_id = str(payload.get("target_node_id") or "")
        state.setdefault("poulpita", {})["previous_node_id"] = state.get("poulpita", {}).get("node_id")
        state["poulpita"]["node_id"] = target_node_id
        if _state_has_shelter(state, target_node_id):
            state.setdefault("objective_progress", {})["found_shelter"] = True
        _simulate_tile_visibility(state)
    elif command_type == "draw_action_card" and ability_id:
        cost = _action_cost(state, "draw")
        _simulate_spend_action(state, capability, cost)
        hand_limit = int(capability.get("current_max_cards_in_hand") or 3)
        if len(capability.get("hand") or []) >= hand_limit and payload.get("auto_discard_card"):
            _simulate_auto_discard_for_draw(state, capability)
        missing = _missing_support_ids_for_open_interaction(state) if state.get("interaction") else []
        candidate_zones = ["draw_pile", "discard"]
        drawn_card = None
        drawn_zone = ""
        for zone in candidate_zones:
            cards = capability.get(zone) or []
            drawn_card = next((card for card in cards if any(required_id in _card_interaction_options(card) for required_id in missing)), None)
            if drawn_card:
                drawn_zone = zone
                break
        if drawn_card is None:
            for zone in candidate_zones:
                cards = capability.get(zone) or []
                if cards:
                    drawn_card = cards[0]
                    drawn_zone = zone
                    break
        if drawn_card is not None and drawn_zone:
            capability[drawn_zone] = [card for card in capability.get(drawn_zone) or [] if str(card.get("card_id") or "") != str(drawn_card.get("card_id") or "")]
            capability.setdefault("hand", []).append(drawn_card)
    elif command_type == "resolve_surprise_card":
        card = ((state.get("pending_surprise") or {}).get("card") or {})
        costs = card.get("costs") or []
        accept = bool(payload.get("accept"))
        paid = False
        if not costs:
            paid = True
        elif accept:
            paid = True
            _simulate_pay_surprise_costs(state, payload, costs)
        if paid:
            _simulate_apply_surprise_effects(state, card.get("effects") or [])
        state["pending_surprise"] = None
    elif command_type == "start_interaction" and ability_id:
        cost = _action_cost(state, "interact")
        _simulate_spend_action(state, capability, cost)
        entry = _simulated_tile_entry(state, str(payload.get("tile_instance_id") or ""))
        if entry:
            state["interaction"] = {
                "tile_instance_id": entry["instance"].get("instance_id"),
                "tile_id": entry["instance"].get("tile_id"),
                "node_id": entry.get("node_id"),
                "initiator_capability_id": ability_id,
                "initiator_confirmed": False,
                "played_cards": [],
            }
            if payload.get("auto_select_cards"):
                _simulate_play_cards_for_requirements(state, ability_id, list((entry.get("tile") or {}).get("interaction_ids") or []))
    elif command_type == "resolve_interaction":
        interaction = state.get("interaction") or {}
        initiator_id = str(interaction.get("initiator_capability_id") or "")
        if ability_id != initiator_id and not interaction.get("initiator_confirmed", True):
            return
        entry = _simulated_tile_entry(state, str(interaction.get("tile_instance_id") or ""))
        if payload.get("auto_select_cards") and entry:
            _simulate_play_cards_for_requirements(state, ability_id, _missing_support_ids_for_open_interaction(state))
        if entry:
            if ability_id == initiator_id:
                interaction["initiator_confirmed"] = True
            if payload.get("confirm_only"):
                return
            tile = entry.get("tile") or {}
            shell_ready = max(0, int((state.get("poulpita") or {}).get("seashells") or 0)) >= max(0, int(tile.get("shell_requirement_count") or 0))
            success = shell_ready and not _missing_interaction_ids_for_open_interaction(state)
            if success:
                _apply_success_effects_to_simulation(state, entry)
                node_id = str(entry.get("node_id") or "")
                state.setdefault("tiles", {})[node_id] = [
                    instance
                    for instance in state.get("tiles", {}).get(node_id, []) or []
                    if str(instance.get("instance_id") or "") != str(entry["instance"].get("instance_id") or "")
                ]
                state["_simulated_resolved_tiles"] = int(state.get("_simulated_resolved_tiles") or 0) + 1
                if _tile_category(state, tile).get("compulsory_on_same_node"):
                    state["_simulated_resolved_compulsory_tiles"] = int(state.get("_simulated_resolved_compulsory_tiles") or 0) + 1
                state["interaction"] = None
    elif command_type == "fail_interaction":
        interaction = state.get("interaction") or {}
        entry = _simulated_tile_entry(state, str(interaction.get("tile_instance_id") or ""))
        if entry:
            tile = entry.get("tile") or {}
            node_id = str(entry.get("node_id") or "")
            remove_tile = False
            keep_tile = False
            for effect in tile.get("failure_effects") or []:
                effect_type = str(effect.get("type") or "")
                amount = max(0, int(effect.get("amount") or 0))
                poulpita = state.setdefault("poulpita", {})
                if effect_type == "lose_energy":
                    poulpita["energy"] = max(0, int(poulpita.get("energy") or 0) - amount)
                elif effect_type == "lose_neurons":
                    poulpita["neurons"] = max(0, int(poulpita.get("neurons") or 0) - amount)
                elif effect_type == "lose_seashells":
                    poulpita["seashells"] = max(0, int(poulpita.get("seashells") or 0) - amount)
                elif effect_type == "lose_ap":
                    for next_capability in (state.get("capabilities") or {}).values():
                        next_capability["pa"] = max(0, int(next_capability.get("pa") or 0) - amount)
                elif effect_type == "lose_half_ap":
                    for next_capability in (state.get("capabilities") or {}).values():
                        next_capability["pa"] = int(next_capability.get("pa") or 0) // 2
                elif effect_type == "lose_all_ap":
                    for next_capability in (state.get("capabilities") or {}).values():
                        next_capability["pa"] = 0
                elif effect_type == "pulpita_move_previous" and poulpita.get("previous_node_id"):
                    poulpita["node_id"], poulpita["previous_node_id"] = poulpita.get("previous_node_id"), poulpita.get("node_id")
                elif effect_type == "pulpita_move_free" and payload.get("target_node_id"):
                    poulpita["previous_node_id"] = poulpita.get("node_id")
                    poulpita["node_id"] = str(payload.get("target_node_id"))
                elif effect_type == "remove_tile":
                    remove_tile = True
                elif effect_type == "keep_tile":
                    keep_tile = True
            if remove_tile and not keep_tile:
                state.setdefault("tiles", {})[node_id] = [
                    instance
                    for instance in state.get("tiles", {}).get(node_id, []) or []
                    if str(instance.get("instance_id") or "") != str(entry["instance"].get("instance_id") or "")
                ]
        state["interaction"] = None
    elif command_type == "move_seashell_to_shelter":
        current_node_id = str((state.get("poulpita") or {}).get("node_id") or "")
        poulpita = state.setdefault("poulpita", {})
        if int(poulpita.get("seashells") or 0) > 0 and _state_has_shelter(state, current_node_id):
            shelter = state.setdefault("shelters", {}).setdefault(current_node_id, {"count": 1, "seashells": 0, "secure": False})
            if isinstance(shelter, dict):
                poulpita["seashells"] = int(poulpita.get("seashells") or 0) - 1
                shelter["seashells"] = int(shelter.get("seashells") or 0) + 1
                shelter["secure"] = int(shelter.get("seashells") or 0) >= 3
    elif command_type == "move_seashell_from_shelter":
        current_node_id = str((state.get("poulpita") or {}).get("node_id") or "")
        shelter = (state.get("shelters") or {}).get(current_node_id)
        if isinstance(shelter, dict) and int(shelter.get("seashells") or 0) > 0:
            shelter["seashells"] = int(shelter.get("seashells") or 0) - 1
            shelter["secure"] = int(shelter.get("seashells") or 0) >= 3
            state.setdefault("poulpita", {})["seashells"] = int(state.setdefault("poulpita", {}).get("seashells") or 0) + 1
    elif command_type == "buy_hand_size_upgrade" and ability_id:
        upgrade_index = int(payload.get("upgrade_index") or 0)
        upgrades = capability.get("hand_size_upgrades") or []
        if 0 <= upgrade_index < len(upgrades):
            upgrade = upgrades[upgrade_index] or {}
            cost = max(0, int(upgrade.get("cost") or 0))
            state.setdefault("poulpita", {})["neurons"] = max(0, int(state.get("poulpita", {}).get("neurons") or 0) - cost)
            if str(upgrade.get("type") or "hand_size") == "hand_size":
                capability["current_max_cards_in_hand"] = int(capability.get("current_max_cards_in_hand") or capability.get("default_max_cards_in_hand") or 3) + max(1, int(upgrade.get("hand_size_bonus") or 1))
            elif str(upgrade.get("type") or "") == "deck_exchange":
                _simulate_deck_exchange_upgrade(capability, upgrade)
            capability.setdefault("purchased_hand_size_upgrade_indices", []).append(upgrade_index)
    elif command_type == "buy_poulpita_size":
        poulpita = state.setdefault("poulpita", {})
        sizes = ((state.get("tile_catalog") or {}).get("poulpita_panel") or {}).get("sizes") or []
        next_size_index = int(poulpita.get("size_index") or 0) + 1
        if next_size_index < len(sizes):
            base_cost = max(1, int((sizes[next_size_index] or {}).get("energy_cost") or 1))
            cost = max(0, base_cost - _current_shelter_growth_discount(state))
            poulpita["energy"] = max(0, int(poulpita.get("energy") or 0) - cost)
            poulpita["size_index"] = next_size_index
            poulpita["size_upgraded_today"] = True
            state.setdefault("objective_progress", {})["size_increases"] = int((state.get("objective_progress") or {}).get("size_increases") or 0) + 1
    elif command_type == "end_night":
        current_node_id = str((state.get("poulpita") or {}).get("node_id") or "")
        if not _state_has_shelter(state, current_node_id):
            state.setdefault("poulpita", {})["energy"] = max(0, int(state.get("poulpita", {}).get("energy") or 0) - 1)
        state["phase"] = "day"
        state["night_time_spent"] = 0
        state["active_capability_id"] = None
        for next_capability in (state.get("capabilities") or {}).values():
            next_capability["actions_taken_this_control"] = 0
            next_capability["control_takes_this_night"] = 0
        state.setdefault("poulpita", {})["size_upgraded_today"] = False
    elif command_type == "end_day":
        if int(state.get("day_index") or 1) >= int(state.get("max_nights") or 5):
            state["phase"] = "game_over"
            state["game_outcome"] = "lost"
            state["game_over_reason"] = "maximum_nights_reached"
            return
        state["phase"] = "night_idle"
        state["day_index"] = int(state.get("day_index") or 1) + 1
        state["night_time_spent"] = 0
        state["active_capability_id"] = None
        for next_capability in (state.get("capabilities") or {}).values():
            next_capability["actions_taken_this_control"] = 0
            next_capability["control_takes_this_night"] = 0
            _simulate_reshuffle_and_deal_starting_hand(next_capability)
        state.setdefault("poulpita", {})["size_upgraded_today"] = False
    _mark_simulated_loss_if_needed(state)


def _best_rollout_interaction(state: dict[str, Any], ability_id: str, entries: list[dict[str, Any]]) -> dict[str, Any] | None:
    candidates = [entry for entry in entries if _can_initiate(state, ability_id, entry.get("tile") or {})]
    if not candidates:
        return None
    return sorted(
        candidates,
        key=lambda entry: (
            _delta_score(_interaction_resolution_summary(state, entry, preferred_ability_id=ability_id).get("expected_delta") or {}),
            float(_interaction_probability(state, entry).get("success_probability") or 0),
            int((entry.get("tile") or {}).get("priority") or 0),
        ),
        reverse=True,
    )[0]


def _rollout_next_commands(state: dict[str, Any], ability_id: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
    capability = _capability(state, ability_id)
    current_node_id = str((state.get("poulpita") or {}).get("node_id") or "")
    interact_cost = _action_cost(state, "interact")
    move_cost = _action_cost(state, "move")
    draw_cost = _action_cost(state, "draw")
    collect_cost = _action_cost(state, "gain_ap")
    if _can_end_night_now(state):
        return [{"type": "end_night", "payload": {"capability_id": ability_id}}], [], "end night at shelter"
    if _action_slots_left(capability) <= 0:
        return [], [], "control exhausted"
    if state.get("interaction"):
        return _next_interaction_support_command(state, ability_id)
    current_compulsory = _compulsory_choices_on_node(state, current_node_id)
    shelter_return = _shelter_return_context(state, current_node_id)
    if _can_pay_action_cost(state, capability, interact_cost):
        forced_entry = _best_rollout_interaction(state, ability_id, current_compulsory)
        if forced_entry:
            return _interaction_rollout_commands(state, ability_id, forced_entry), [forced_entry], f"forced {_tile_display_name(state, forced_entry['tile'])}"
        if not shelter_return["should_return"]:
            optional_entry = _best_rollout_interaction(state, ability_id, _visible_current_tiles(state))
            if optional_entry:
                return _interaction_rollout_commands(state, ability_id, optional_entry), [optional_entry], _tile_display_name(state, optional_entry["tile"])
    elif (
        current_compulsory
        and any(_can_initiate(state, ability_id, entry.get("tile") or {}) for entry in current_compulsory)
        and int(capability.get("pa") or 0) < interact_cost["ap_cost"]
        and int((state.get("poulpita") or {}).get("neurons") or 0) >= interact_cost["neuron_cost"]
        and _can_pay_action_cost(state, capability, collect_cost)
    ):
        return [{"type": "collect_action_points", "payload": {"capability_id": ability_id}}], current_compulsory, "AP for forced interaction"
    if not current_compulsory and shelter_return["should_return"]:
        if _can_pay_action_cost(state, capability, move_cost):
            target_node_id = str(shelter_return["next_node_id"])
            return [
                {"type": "move_poulpita", "payload": {"capability_id": ability_id, "target_node_id": target_node_id}}
            ], [], f"safe shelter route via {target_node_id}"
        positive_move_ap = int(move_cost.get("ap_cost") or 0) > int(capability.get("pa") or 0)
        neurons_ready = int((state.get("poulpita") or {}).get("neurons") or 0) >= int(move_cost.get("neuron_cost") or 0)
        if positive_move_ap and neurons_ready and _can_pay_action_cost(state, capability, collect_cost):
            return [{"type": "collect_action_points", "payload": {"capability_id": ability_id}}], [], "AP for shelter return"
        return [], [], "safe shelter route currently unaffordable"
    if not current_compulsory and _can_pay_action_cost(state, capability, move_cost):
        adjacent = list(((state.get("map") or {}).get("adjacency") or {}).get(current_node_id) or [])
        if adjacent:
            scored_nodes = []
            for adjacent_node_id in adjacent:
                node_score, node_entries, shelter_distance = _node_followup_score(state, str(adjacent_node_id), ability_id)
                scored_nodes.append((node_score, str(adjacent_node_id), node_entries, shelter_distance))
            scored_nodes.sort(key=lambda item: item[0], reverse=True)
            _node_score, target_node_id, target_entries, _shelter_distance = scored_nodes[0]
            return [{"type": "move_poulpita", "payload": {"capability_id": ability_id, "target_node_id": target_node_id}}], target_entries, f"node {target_node_id}"
    if not current_compulsory and _can_pay_action_cost(state, capability, draw_cost):
        hand_count = len(capability.get("hand") or [])
        hand_limit = int(capability.get("current_max_cards_in_hand") or 3)
        if hand_count < hand_limit and (capability.get("draw_pile") or capability.get("discard")):
            return [{"type": "draw_action_card", "payload": {"capability_id": ability_id}}], [], "card draw"
    positive_action_costs = [cost["ap_cost"] for cost in [move_cost, interact_cost, draw_cost] if cost["ap_cost"] > 0]
    if not current_compulsory and positive_action_costs and int(capability.get("pa") or 0) < min(positive_action_costs) and _can_pay_action_cost(state, capability, collect_cost):
        return [{"type": "collect_action_points", "payload": {"capability_id": ability_id}}], [], "AP setup"
    return [], [], "replan"


def _rollout_command_label(state: dict[str, Any], command: dict[str, Any]) -> str:
    command_type = str(command.get("type") or "")
    payload = command.get("payload") or {}
    if command_type == "take_control":
        ability_id = str(payload.get("capability_id") or "")
        return f"{(_capability(state, ability_id).get('name') or ability_id)} takes control"
    if command_type == "collect_action_points":
        return "Collect AP"
    if command_type == "move_poulpita":
        return f"Move {payload.get('target_node_id') or '?'}"
    if command_type == "start_interaction":
        entry = _simulated_tile_entry(state, str(payload.get("tile_instance_id") or ""))
        return f"Interact {_tile_display_name(state, entry['tile']) if entry else 'tile'}"
    if command_type == "resolve_interaction":
        return "Confirm interaction"
    if command_type == "draw_action_card":
        return "Draw action card"
    if command_type == "resolve_surprise_card":
        return "Resolve surprise"
    return command_type.replace("_", " ").title()


def _choose_next_rollout_control(simulated: dict[str, Any], current_ability_id: str) -> str | None:
    choices = []
    for candidate_id in _all_capability_ids(simulated):
        if candidate_id == "intelligence" or candidate_id == current_ability_id:
            continue
        candidate = _capability(simulated, candidate_id)
        if not _has_control_take_left(candidate):
            continue
        candidate_state = _clone_simulation_state(simulated)
        candidate_state["phase"] = "night_action"
        candidate_state["active_capability_id"] = candidate_id
        candidate_capability = _capability(candidate_state, candidate_id)
        candidate_capability["control_takes_this_night"] = int(candidate_capability.get("control_takes_this_night") or 0) + 1
        candidate_capability["actions_taken_this_control"] = 0
        commands, interactions, _label = _rollout_next_commands(candidate_state, candidate_id)
        if not commands:
            continue
        interaction_gain = sum(
            _delta_score(_interaction_resolution_summary(candidate_state, entry, preferred_ability_id=candidate_id).get("expected_delta") or {})
            for entry in interactions
        )
        support_gain = _interaction_support_score(candidate_state, candidate_id) if candidate_state.get("interaction") else 0
        choices.append((interaction_gain + support_gain + len(commands), candidate_id))
    if not choices:
        return None
    choices.sort(key=lambda item: item[0], reverse=True)
    return choices[0][1]


def _optimistic_followup_from_state(
    state: dict[str, Any],
    *,
    start_ability_id: str | None = None,
    max_steps: int = 7,
) -> dict[str, Any]:
    simulated = _clone_simulation_state(state)
    simulated["pending_surprise"] = None
    ability_id = str(start_ability_id or simulated.get("active_capability_id") or "")
    steps: list[str] = []
    commands_out: list[dict[str, Any]] = []
    interactions: list[dict[str, Any]] = []
    controls_used = 0
    max_controls = _planning_depth_take_controls(state)
    stop_reason = "max steps reached"
    while len(commands_out) < max_steps:
        if not ability_id or _action_slots_left(_capability(simulated, ability_id)) <= 0:
            if controls_used >= max_controls:
                stop_reason = "planning depth controls exhausted"
                break
            next_ability_id = _choose_next_rollout_control(simulated, ability_id)
            if not next_ability_id:
                stop_reason = "no eligible next control after action slots exhausted"
                break
            command = {"type": "take_control", "payload": {"capability_id": next_ability_id}}
            steps.append(_rollout_command_label(simulated, command))
            commands_out.append(command)
            _simulate_public_command(simulated, command)
            ability_id = next_ability_id
            controls_used += 1
            continue
        next_commands, next_interactions, _label = _rollout_next_commands(simulated, ability_id)
        if not next_commands:
            if controls_used >= max_controls:
                stop_reason = "planning depth controls exhausted"
                break
            next_ability_id = _choose_next_rollout_control(simulated, ability_id)
            if not next_ability_id:
                stop_reason = _rollout_next_commands(simulated, ability_id)[2] or "no rollout command available"
                break
            command = {"type": "take_control", "payload": {"capability_id": next_ability_id}}
            steps.append(_rollout_command_label(simulated, command))
            commands_out.append(command)
            _simulate_public_command(simulated, command)
            ability_id = next_ability_id
            controls_used += 1
            continue
        for command in next_commands:
            if len(commands_out) >= max_steps:
                break
            steps.append(_rollout_command_label(simulated, command))
            commands_out.append(command)
            _simulate_public_command(simulated, command)
        interactions.extend(next_interactions)
    unique_interactions = []
    seen_interaction_ids: set[str] = set()
    for entry in interactions:
        instance_id = str((entry.get("instance") or {}).get("instance_id") or "")
        if instance_id and instance_id in seen_interaction_ids:
            continue
        if instance_id:
            seen_interaction_ids.add(instance_id)
        unique_interactions.append(entry)
    return {
        "steps": steps,
        "public_commands": commands_out,
        "interactions": unique_interactions,
        "debug": {
            "stop_reason": stop_reason,
            "controls_used": controls_used,
            "followup_action_count": len(commands_out),
        },
    }


def _selected_cards_matching_requirements(capability: dict[str, Any], required_interaction_ids: list[str]) -> list[str]:
    remaining = [str(interaction_id) for interaction_id in required_interaction_ids if interaction_id]
    selected: list[str] = []
    for card in capability.get("hand") or []:
        if not remaining:
            break
        match = next((interaction_id for interaction_id in remaining if interaction_id in _card_interaction_options(card)), None)
        if match:
            remaining.remove(match)
            selected.append(str(card.get("card_id")))
    return selected


def _selected_cards_for_requirements(capability: dict[str, Any], required_interaction_ids: list[str]) -> list[str] | None:
    required = [str(interaction_id) for interaction_id in required_interaction_ids if interaction_id]
    selected = _selected_cards_matching_requirements(capability, required)
    return selected if len(selected) == len(required) else None


def _surprise_accept_payloads(state: dict[str, Any], card: dict[str, Any]) -> list[dict[str, Any]]:
    costs = card.get("costs") or []
    if not costs:
        return [{"accept": True}]
    payloads = []
    for capability_id in _planner_capability_ids(state):
        capability = _capability(state, capability_id)
        selected_card_ids: list[str] = []
        payable = True
        for cost in costs:
            cost_type = str(cost.get("type") or "")
            if cost_type == "play_cards":
                selected = _selected_cards_for_requirements(capability, [str(interaction_id) for interaction_id in cost.get("interaction_ids") or []])
                if selected is None:
                    payable = False
                    break
                selected_card_ids.extend(selected)
            elif cost_type == "pay_ap":
                payer_id = str(cost.get("capability_id") or capability_id)
                payer = _capability(state, payer_id)
                if int(payer.get("pa") or 0) < max(1, int(cost.get("amount") or 1)):
                    payable = False
                    break
            else:
                payable = False
                break
        if payable:
            payloads.append({"accept": True, "capability_id": capability_id, "card_ids": selected_card_ids})
    return payloads


def _surprise_cost_labels(state: dict[str, Any], payload: dict[str, Any], costs: list[dict[str, Any]]) -> list[str]:
    labels = []
    ability_id = str(payload.get("capability_id") or "")
    for cost in costs or []:
        cost_type = str(cost.get("type") or "")
        if cost_type == "play_cards":
            names = [_interaction_display_name(state, str(interaction_id)) for interaction_id in cost.get("interaction_ids") or [] if interaction_id]
            payer = _capability(state, ability_id)
            labels.append(f"{payer.get('name') or ability_id or 'ability'} plays {', '.join(names) if names else 'cards'}")
        elif cost_type == "pay_ap":
            payer_id = str(cost.get("capability_id") or ability_id)
            payer = _capability(state, payer_id)
            labels.append(f"{payer.get('name') or payer_id or 'ability'} pays {max(1, int(cost.get('amount') or 1))} AP")
    return labels


def _surprise_proposals(state: dict[str, Any]) -> list[dict[str, Any]]:
    card = ((state.get("pending_surprise") or {}).get("card") or {})
    if not card:
        return []
    costs = card.get("costs") or []
    effect_labels = _effect_labels(state, card.get("effects") or [])
    proposals = []
    for payload in _surprise_accept_payloads(state, card):
        capability_id = payload.get("capability_id")
        capability_name = (_capability(state, str(capability_id)).get("name") if capability_id else "") or "Team"
        resolve_command = {"type": "resolve_surprise_card", "payload": payload}
        simulated_after_surprise = _clone_simulation_state(state)
        pre_surprise_components = _global_state_score_components(simulated_after_surprise)
        _simulate_public_command(simulated_after_surprise, resolve_command)
        post_surprise_components = _global_state_score_components(simulated_after_surprise)
        surprise_delta = {
            key: round(float(post_surprise_components.get(key) or 0) - float(pre_surprise_components.get(key) or 0), 2)
            for key in sorted(set(pre_surprise_components) | set(post_surprise_components))
            if round(float(post_surprise_components.get(key) or 0) - float(pre_surprise_components.get(key) or 0), 2) != 0
        }
        followup = _optimistic_followup_from_state(
            simulated_after_surprise,
            start_ability_id=str(simulated_after_surprise.get("active_capability_id") or ""),
            max_steps=7,
        )
        commands = [resolve_command] + list(followup.get("public_commands") or [])
        step_labels = ["Resolve surprise"] + list(followup.get("steps") or [])
        statistics = _plan_statistics(
            state,
            commands=commands,
            interactions=followup.get("interactions") or [],
            assumptions=["Surprise costs and effects are simulated for follow-up planning; every later step is rechecked by the authoritative reducer."],
        )
        statistics["surprise_resolution"] = "pay" if costs else "automatic"
        statistics["surprise_card"] = {"id": card.get("id"), "name": card.get("name")}
        statistics["surprise_costs"] = _surprise_cost_labels(state, payload, costs)
        statistics["surprise_effects"] = effect_labels
        statistics["surprise_delta"] = surprise_delta
        statistics["expected_resource_delta"] = _merge_deltas([statistics.get("expected_resource_delta") or {}, _effect_delta(card.get("effects") or [])])
        proposals.append(
            _public_plan(
                plan_id=f"surprise_accept_{capability_id or 'free'}",
                proposer_ability_id=str(capability_id) if capability_id else None,
                title=f"Resolve surprise: {card.get('name') or 'Surprise'}",
                rationale="A surprise card is pending. The planner resolves it and then continues optimistically into the next public actions.",
                risk_label="low" if not costs else "moderate",
                step_preview=[
                    "Acknowledge automatic effect" if not costs else f"{capability_name} pays the optional cost",
                    f"Apply: {', '.join(effect_labels[:3])}" if effect_labels else "Apply surprise effects",
                    *(followup.get("steps") or ["Recalculate board plans"]),
                ],
                expected_resources=_resource_estimate(),
                score=90 if not costs else 75,
                warnings=[] if not costs else ["Private card identities are hidden from the public proposal."],
                commands=commands,
                plan_chain=_plan_chain(step_labels, commands),
                statistics=statistics,
            )
        )
    if costs:
        skip_command = {"type": "resolve_surprise_card", "payload": {"accept": False}}
        simulated_after_skip = _clone_simulation_state(state)
        _simulate_public_command(simulated_after_skip, skip_command)
        followup = _optimistic_followup_from_state(
            simulated_after_skip,
            start_ability_id=str(simulated_after_skip.get("active_capability_id") or ""),
            max_steps=7,
        )
        commands = [skip_command] + list(followup.get("public_commands") or [])
        step_labels = ["Skip surprise"] + list(followup.get("steps") or [])
        statistics = _plan_statistics(
            state,
            commands=commands,
            interactions=followup.get("interactions") or [],
            assumptions=["Optional surprise costs can be declined. Follow-up steps are optimistic and rechecked before execution."],
        )
        statistics["surprise_resolution"] = "skip"
        statistics["surprise_card"] = {"id": card.get("id"), "name": card.get("name")}
        statistics["surprise_costs"] = _surprise_cost_labels(state, {"accept": False}, costs)
        statistics["surprise_effects"] = []
        statistics["surprise_delta"] = {}
        proposals.append(
            _public_plan(
                plan_id="surprise_skip",
                proposer_ability_id=None,
                title=f"Do not pay: {card.get('name') or 'Surprise'}",
                rationale="Surprise costs are optional. The team can skip the cost and continue with the next public actions.",
                risk_label="low",
                step_preview=["Decline the optional surprise cost", "Discard the pending surprise decision", *(followup.get("steps") or ["Recalculate board plans"])],
                expected_resources=_resource_estimate(),
                score=40,
                commands=commands,
                plan_chain=_plan_chain(step_labels, commands),
                statistics=statistics,
            )
        )
    return proposals


def _forced_interaction_plan(
    state: dict[str, Any],
    *,
    ability_id: str,
    entry: dict[str, Any],
    include_take_control: bool,
    score: float,
) -> dict[str, Any]:
    capability = _capability(state, ability_id)
    name = capability.get("name") or ability_id
    tile = entry["tile"]
    is_compulsory = bool(_tile_category(state, tile).get("compulsory_on_same_node"))
    interaction_kind = "compulsory" if is_compulsory else "optional"
    plan_kind = "forced" if is_compulsory else "optional"
    event = ((state.get("tile_catalog") or {}).get("events") or {}).get(tile.get("event_id")) or {}
    interact_cost = _action_cost(state, "interact")
    has_ap = _can_pay_action_cost(state, capability, interact_cost)
    commands = []
    if include_take_control:
        commands.append({"type": "take_control", "payload": {"capability_id": ability_id}})
    if has_ap:
        commands.extend(_interaction_commands(ability_id, entry))
    else:
        commands.append({"type": "collect_action_points", "payload": {"capability_id": ability_id}})
    interaction_summary = _interaction_resolution_summary(state, entry, preferred_ability_id=ability_id)
    expected_delta = interaction_summary.get("expected_delta") or {}
    team_size, team_penalty = _interaction_team_penalty(state, entry, ability_id)
    statistics = _plan_statistics(state, commands=commands, interactions=[entry])
    statistics["interaction_summaries"] = [interaction_summary]
    statistics["expected_resource_delta"] = expected_delta
    statistics["interaction_team_size"] = team_size
    statistics["initiative_change_penalty"] = team_penalty
    expected_resources = _resource_estimate(
        ap=interact_cost["ap_cost"] if has_ap else 0,
        time_steps=interact_cost["time_cost"] if has_ap else 0,
        control_takes={ability_id: 1} if include_take_control else {},
    )
    expected_resources["expected_resource_delta"] = expected_delta
    expected_resources["energy_delta_expected"] = expected_delta.get("energy", 0)
    expected_resources["shells_delta_expected"] = expected_delta.get("seashells", 0)
    expected_resources["neurons_delta_expected"] = expected_delta.get("neurons", 0)
    chain_labels = []
    if include_take_control:
        chain_labels.append(f"{name} takes control")
    if has_ap:
        chain_labels.append(f"Start {event.get('name') or tile.get('name') or 'interaction'}")
        if _interaction_requirements(tile) == 0:
            chain_labels.append("Confirm interaction")
    else:
        chain_labels.append("Collect action points")
    return _public_plan(
        plan_id=f"{'take_control_' if include_take_control else ''}{plan_kind}_{ability_id}_{entry['instance'].get('instance_id')}",
        proposer_ability_id=ability_id,
        title=f"{name} addresses {interaction_kind} {event.get('name') or tile.get('name') or 'tile'}",
        rationale=(
            "A compulsory tile is revealed on Poulpita's node, so movement is not proposed until it is addressed."
            if is_compulsory
            else "This visible tile has an efficient initiator and resolving it advances the team's resources and objectives."
        ),
        risk_label="forced" if is_compulsory else "moderate",
        step_preview=[
            f"{name} takes control" if include_take_control else "Use current initiative",
            f"Start the {interaction_kind} interaction" if has_ap else f"Collect AP first, then replan for the {interaction_kind} interaction",
            "Resolve immediately" if has_ap and _interaction_requirements(tile) == 0 else "Pause if cards or shells are required",
        ],
        expected_resources=expected_resources,
        score=(score if has_ap else score - 20) + _delta_score(expected_delta) - team_penalty,
        warnings=[] if has_ap else ["This bot needs AP before starting the forced interaction."],
        commands=commands,
        plan_chain=_plan_chain(chain_labels, commands),
        statistics=statistics,
    )


def _forced_blocker_plan(state: dict[str, Any], compulsory: list[dict[str, Any]]) -> dict[str, Any]:
    names = []
    catalog_events = (state.get("tile_catalog") or {}).get("events") or {}
    for entry in compulsory:
        tile = entry.get("tile") or {}
        event = catalog_events.get(tile.get("event_id")) or {}
        names.append(str(event.get("name") or tile.get("name") or tile.get("id") or "forced tile"))
    return _public_plan(
        plan_id="forced_tile_needs_manual_resolution",
        proposer_ability_id=None,
        title="Forced tile needs manual resolution",
        rationale="A compulsory tile is revealed on Poulpita's node, but the planner could not find an ability with both legal initiation and available control/action capacity.",
        risk_label="forced",
        step_preview=[
            f"Resolve: {', '.join(names[:3])}",
            "Check that the correct ability can initiate this event",
            "Take control, collect AP, or adjust the content configuration if needed",
        ],
        expected_resources=_resource_estimate(),
        score=60,
        warnings=["No movement plans are shown because the current compulsory tile blocks optional planning."],
        statistics=_plan_statistics(state, interactions=compulsory),
    )


def _open_interaction_entry(state: dict[str, Any]) -> dict[str, Any] | None:
    interaction = state.get("interaction") or {}
    if not interaction:
        return None
    tile = ((state.get("tile_catalog") or {}).get("tiles") or {}).get(interaction.get("tile_id")) or {}
    if not tile:
        return None
    return {
        "instance": {"instance_id": interaction.get("tile_instance_id"), "tile_id": interaction.get("tile_id"), "face_up": True},
        "tile": tile,
        "node_id": interaction.get("node_id"),
    }


def _played_interactions(state: dict[str, Any]) -> list[str]:
    return [str(card.get("interaction_id") or "") for card in ((state.get("interaction") or {}).get("played_cards") or []) if card.get("interaction_id")]


def _missing_interaction_ids_for_open_interaction(state: dict[str, Any], *, include_counter_attack: bool = False) -> list[str]:
    entry = _open_interaction_entry(state)
    if not entry:
        return []
    tile = entry["tile"]
    missing = []
    played = list(_played_interactions(state))
    required_ids = [
        str(interaction_id)
        for interaction_id in (
            ((state.get("interaction") or {}).get("courtship_card") or {}).get("interaction_ids")
            or tile.get("interaction_ids")
            or []
        )
        if interaction_id
    ]
    if include_counter_attack:
        required_ids.extend(str(interaction_id) for interaction_id in (tile.get("counter_attack_interaction_ids") or []) if interaction_id)
    for required_id in required_ids:
        if required_id in played:
            played.remove(required_id)
        else:
            missing.append(required_id)
    return missing


def _missing_support_ids_for_open_interaction(state: dict[str, Any]) -> list[str]:
    full_missing = _missing_interaction_ids_for_open_interaction(state, include_counter_attack=True)
    normal_missing = _missing_interaction_ids_for_open_interaction(state)
    if full_missing == normal_missing:
        return normal_missing
    full_coverage_score = max(
        (
            _matched_requirement_count((_capability(state, ability_id).get("hand") or []) + (_capability(state, ability_id).get("draw_pile") or []) + (_capability(state, ability_id).get("discard") or []), full_missing)
            for ability_id in _playable_ability_ids(state)
        ),
        default=0,
    )
    return full_missing if full_coverage_score > 0 else normal_missing


def _interaction_support_score(state: dict[str, Any], ability_id: str) -> float:
    entry = _open_interaction_entry(state)
    if not entry:
        return 0.0
    missing = _missing_support_ids_for_open_interaction(state)
    tile = entry.get("tile") or {}
    capability = _capability(state, ability_id)
    shell_ready = max(0, int((state.get("poulpita") or {}).get("seashells") or 0)) >= max(0, int(tile.get("shell_requirement_count") or 0))
    if shell_ready and (not missing or _selected_cards_for_requirements(capability, missing) is not None):
        return 100.0
    hand_matches = _matched_requirement_count(capability.get("hand") or [], missing)
    deck_matches = _matched_requirement_count((capability.get("draw_pile") or []) + (capability.get("discard") or []), missing)
    if not shell_ready:
        return 0.0
    return hand_matches * 20.0 + deck_matches * 6.0 + min(3, int(capability.get("pa") or 0))


def _support_candidate_estimate(state: dict[str, Any], ability_id: str, missing: list[str], entry: dict[str, Any]) -> dict[str, Any]:
    capability = _capability(state, ability_id)
    tile = entry.get("tile") or {}
    shell_ready = max(0, int((state.get("poulpita") or {}).get("seashells") or 0)) >= max(0, int(tile.get("shell_requirement_count") or 0))
    hand_matches = _matched_requirement_count(capability.get("hand") or [], missing)
    known_future_matches = _matched_requirement_count((capability.get("draw_pile") or []) + (capability.get("discard") or []), missing)
    total_missing = max(1, len(missing))
    has_required_in_hand = shell_ready and hand_matches >= len(missing)
    can_improve_by_drawing = shell_ready and known_future_matches > 0
    is_human = bool(capability.get("is_human_controlled") or str(capability.get("controller_type") or "") == "human")
    if has_required_in_hand:
        probability = 0.95
    elif can_improve_by_drawing:
        probability = min(0.75, 0.35 + 0.3 * (known_future_matches / total_missing))
    elif is_human:
        probability = max(0.2, 0.45 * (hand_matches / total_missing))
    else:
        probability = max(0.05, 0.25 * ((hand_matches + known_future_matches) / total_missing))
    return {
        "shell_ready": shell_ready,
        "hand_matches": hand_matches,
        "known_future_matches": known_future_matches,
        "has_required_in_hand": has_required_in_hand,
        "can_improve_by_drawing": can_improve_by_drawing,
        "is_human": is_human,
        "probability": round(probability, 2),
    }


def _next_interaction_support_command(state: dict[str, Any], ability_id: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
    entry = _open_interaction_entry(state)
    if not entry:
        return [], [], "interaction pending"
    interaction = state.get("interaction") or {}
    initiator_id = str(interaction.get("initiator_capability_id") or "")
    if not interaction.get("initiator_confirmed", True):
        if ability_id != initiator_id:
            return [], [entry], "waiting for initiator confirmation"
        return [
            {
                "type": "resolve_interaction",
                "payload": {"capability_id": ability_id, "auto_select_cards": True, "confirm_only": True},
            }
        ], [entry], f"confirm initiator cards for {_tile_display_name(state, entry.get('tile') or {})}"
    capability = _capability(state, ability_id)
    missing = _missing_support_ids_for_open_interaction(state)
    tile = entry.get("tile") or {}
    shell_ready = max(0, int((state.get("poulpita") or {}).get("seashells") or 0)) >= max(0, int(tile.get("shell_requirement_count") or 0))
    if shell_ready and not missing:
        return [{"type": "resolve_interaction", "payload": {"capability_id": ability_id}}], [entry], f"complete {_tile_display_name(state, tile)}"
    if shell_ready and _selected_cards_for_requirements(capability, missing) is not None:
        return [{"type": "resolve_interaction", "payload": {"capability_id": ability_id, "auto_select_cards": True, "confirm_only": True}}], [entry], f"confirm cards for {_tile_display_name(state, tile)}"
    if shell_ready and _selected_cards_matching_requirements(capability, missing):
        return [{"type": "resolve_interaction", "payload": {"capability_id": ability_id, "auto_select_cards": True, "confirm_only": True}}], [entry], f"commit cards to {_tile_display_name(state, tile)}"
    draw_cost = _action_cost(state, "draw")
    has_action_slot = _action_slots_left(capability) > 0
    hand_count = len(capability.get("hand") or [])
    hand_limit = int(capability.get("current_max_cards_in_hand") or 3)
    known_support_cards = (capability.get("draw_pile") or []) + (capability.get("discard") or [])
    if (
        missing
        and shell_ready
        and _matched_requirement_count(known_support_cards, missing) > 0
    ):
        if has_action_slot and _can_pay_action_cost(state, capability, draw_cost):
            payload = {"capability_id": ability_id}
            if hand_count >= hand_limit:
                payload["auto_discard_card"] = True
            return [{"type": "draw_action_card", "payload": payload}], [entry], f"draw for {_tile_display_name(state, tile)}"
        if has_action_slot and _can_collect_toward_action_cost(state, capability, draw_cost):
            return [{"type": "collect_action_points", "payload": {"capability_id": ability_id}}], [entry], f"AP for {_tile_display_name(state, tile)}"
    return [], [], "interaction pending"


def _support_candidate_plan(
    state: dict[str, Any],
    *,
    ability_id: str,
    include_take_control: bool,
    entry: dict[str, Any],
    estimate: dict[str, Any],
) -> dict[str, Any] | None:
    capability = _capability(state, ability_id)
    if not capability:
        return None
    missing = _missing_support_ids_for_open_interaction(state)
    selected = _selected_cards_for_requirements(capability, missing)
    partial_selected = _selected_cards_matching_requirements(capability, missing)
    title_name = _tile_display_name(state, entry.get("tile") or {})
    name = capability.get("name") or ability_id
    commands: list[dict[str, Any]] = []
    labels: list[str] = []
    if include_take_control:
        commands.append({"type": "take_control", "payload": {"capability_id": ability_id}})
        labels.append(f"{name} takes control")
    draw_cost = _action_cost(state, "draw")
    has_action_slot = include_take_control or _action_slots_left(capability) > 0
    if selected is not None:
        commands.append({"type": "resolve_interaction", "payload": {"capability_id": ability_id, "card_ids": selected, "confirm_only": True}})
        labels.append(f"{name} plays support cards")
    elif partial_selected:
        commands.append({"type": "resolve_interaction", "payload": {"capability_id": ability_id, "card_ids": partial_selected, "confirm_only": True}})
        labels.append(f"{name} commits available support cards")
    elif estimate.get("can_improve_by_drawing") and has_action_slot:
        if _can_pay_action_cost(state, capability, draw_cost):
            draw_payload = {"capability_id": ability_id}
            if len(capability.get("hand") or []) >= int(capability.get("current_max_cards_in_hand") or 3):
                draw_payload["auto_discard_card"] = True
                labels.append(f"{name} swaps a card for {title_name}")
            else:
                labels.append(f"{name} draws for {title_name}")
            commands.append({"type": "draw_action_card", "payload": draw_payload})
        elif _can_collect_toward_action_cost(state, capability, draw_cost):
            commands.append({"type": "collect_action_points", "payload": {"capability_id": ability_id}})
            labels.append(f"{name} collects AP to draw")
    elif estimate.get("is_human"):
        commands.append({"type": "resolve_interaction", "payload": {"capability_id": ability_id, "auto_select_cards": True, "confirm_only": True}})
        labels.append(f"{name} tries support")
    if not commands or (include_take_control and len(commands) == 1):
        return None
    interaction_summary = _interaction_resolution_summary(state, entry, preferred_ability_id=ability_id)
    statistics = _plan_statistics(state, commands=commands, interactions=[entry])
    statistics["interaction_summaries"] = [interaction_summary]
    statistics["expected_resource_delta"] = interaction_summary.get("expected_delta") or {}
    statistics["support_estimate"] = {
        "ability_id": ability_id,
        "ability_name": name,
        "missing_requirements": [_interaction_display_name(state, requirement_id) for requirement_id in missing],
        **estimate,
    }
    statistics["success_probability"] = min(
        float(statistics.get("success_probability") or 1),
        float(estimate.get("probability") or 0.05),
    )
    score = 70 + float(estimate.get("probability") or 0) * 35 + int(estimate.get("hand_matches") or 0) * 5 + int(estimate.get("known_future_matches") or 0) * 2
    if not include_take_control:
        score += 8
    if estimate.get("is_human") and selected is None:
        score -= 18
    rationale = "The interaction is open. This branch keeps the game moving by choosing the best available support action for this ability."
    if selected is None and estimate.get("is_human"):
        rationale = "The interaction is open. This human-controlled ability might be able to support from private knowledge; the reducer will reject the step if it is not actually payable."
    return _public_plan(
        plan_id=f"support_option_{ability_id}_{(entry['instance'] or {}).get('instance_id')}_{str(commands[-1].get('type') or 'act')}",
        proposer_ability_id=ability_id,
        title=f"{name} supports {title_name}",
        rationale=rationale,
        risk_label="forced" if _tile_category(state, entry.get("tile") or {}).get("compulsory_on_same_node") else "moderate",
        step_preview=labels,
        expected_resources=_resource_estimate(control_takes={ability_id: 1} if include_take_control else {}),
        score=score,
        commands=commands,
        plan_chain=_plan_chain(labels, commands),
        warnings=[] if selected is not None else ["This is a probabilistic support branch and may need replanning after the next action."],
        statistics=statistics,
    )


def _proposal_advisor_support_score(state: dict[str, Any], advisor_id: str, proposal: dict[str, Any]) -> float:
    capability = _capability(state, advisor_id)
    hand = capability.get("hand") or []
    future_cards = (capability.get("draw_pile") or []) + (capability.get("discard") or [])
    entries: list[dict[str, Any]] = []
    seen_instances: set[str] = set()
    for command in proposal.get("commands") or []:
        command_type = str(command.get("type") or "")
        payload = command.get("payload") or {}
        if command_type == "move_poulpita":
            node_id = str(payload.get("target_node_id") or "")
            candidate_entries = _visible_tiles_on_node(state, node_id)
        elif command_type == "start_interaction":
            entry = _simulated_tile_entry(state, str(payload.get("tile_instance_id") or ""))
            candidate_entries = [entry] if entry else []
        else:
            candidate_entries = []
        for entry in candidate_entries:
            instance_id = str((entry.get("instance") or {}).get("instance_id") or "")
            if instance_id and instance_id not in seen_instances:
                seen_instances.add(instance_id)
                entries.append(entry)
    score = 0.0
    for entry in entries:
        tile = entry.get("tile") or {}
        required = [
            str(interaction_id)
            for interaction_id in (tile.get("interaction_ids") or []) + (tile.get("counter_attack_interaction_ids") or [])
            if interaction_id
        ]
        score += _matched_requirement_count(hand, required) * 12.0
        score += _matched_requirement_count(future_cards, required) * 4.0
    return score + min(3, int(capability.get("pa") or 0)) * 0.25


def _advised_active_proposals(
    state: dict[str, Any],
    proposals: list[dict[str, Any]],
    active_id: str,
) -> list[dict[str, Any]]:
    advisors = [ability_id for ability_id in _planner_capability_ids(state) if ability_id in (state.get("capabilities") or {})]
    if not proposals or not advisors:
        return proposals

    advised: list[dict[str, Any]] = []
    represented: set[str] = set()
    advisor_rankings: dict[str, list[tuple[float, dict[str, Any]]]] = {ability_id: [] for ability_id in advisors}
    for proposal in proposals:
        ranked = sorted(
            (
                (_proposal_advisor_support_score(state, advisor_id, proposal), advisor_id)
                for advisor_id in advisors
            ),
            key=lambda item: (item[0], item[1]),
            reverse=True,
        )
        support_score, advisor_id = ranked[0]
        clone = deepcopy(proposal)
        clone["proposer_ability_id"] = advisor_id
        clone["rationale"] = (
            f"{_capability(state, advisor_id).get('name') or advisor_id} recommends keeping "
            f"{_capability(state, active_id).get('name') or active_id} in control. {clone.get('rationale') or ''}"
        )
        clone["statistics"] = {
            **(clone.get("statistics") or {}),
            "advisor_ability_id": advisor_id,
            "advisor_support_score": round(support_score, 2),
            "recommended_active_ability_id": active_id,
        }
        advised.append(clone)
        represented.add(advisor_id)
        for advisor_score, ranked_advisor_id in ranked:
            advisor_rankings[ranked_advisor_id].append(
                (float(proposal.get("_score") or 0) + advisor_score, proposal)
            )

    for advisor_id in advisors:
        if advisor_id in represented or not advisor_rankings[advisor_id]:
            continue
        _ranking, proposal = max(advisor_rankings[advisor_id], key=lambda item: item[0])
        clone = deepcopy(proposal)
        clone["plan_id"] = f"{proposal.get('plan_id')}__advisor_{advisor_id}"
        clone["_plan_group"] = f"{proposal.get('_plan_group') or proposal.get('plan_id')}__advisor_{advisor_id}"
        clone["proposer_ability_id"] = advisor_id
        support_score = _proposal_advisor_support_score(state, advisor_id, proposal)
        clone["rationale"] = (
            f"{_capability(state, advisor_id).get('name') or advisor_id} recommends keeping "
            f"{_capability(state, active_id).get('name') or active_id} in control. {clone.get('rationale') or ''}"
        )
        clone["statistics"] = {
            **(clone.get("statistics") or {}),
            "advisor_ability_id": advisor_id,
            "advisor_support_score": round(support_score, 2),
            "recommended_active_ability_id": active_id,
        }
        advised.append(clone)
    return advised


def _interaction_support_proposals(state: dict[str, Any]) -> list[dict[str, Any]]:
    entry = _open_interaction_entry(state)
    if not entry:
        return []
    interaction = state.get("interaction") or {}
    if not interaction.get("initiator_confirmed", True):
        initiator_id = str(interaction.get("initiator_capability_id") or "")
        if initiator_id not in (state.get("capabilities") or {}):
            return []
        command = {
            "type": "resolve_interaction",
            "payload": {"capability_id": initiator_id, "auto_select_cards": True, "confirm_only": True},
        }
        title_name = _tile_display_name(state, entry.get("tile") or {})
        statistics = _plan_statistics(state, commands=[command], interactions=[entry])
        proposal = _public_plan(
            plan_id=f"confirm_initiator_{initiator_id}_{(entry.get('instance') or {}).get('instance_id')}",
            proposer_ability_id=initiator_id,
            title=f"Confirm {title_name} cards",
            rationale="The initiating ability confirms its contribution before support abilities can commit cards.",
            risk_label="low",
            step_preview=[f"{_capability(state, initiator_id).get('name') or initiator_id} confirms cards"],
            expected_resources=_resource_estimate(),
            score=140,
            commands=[command],
            plan_chain=_plan_chain(["Confirm initiator cards"], [command]),
            statistics=statistics,
        )
        return _advised_active_proposals(state, [proposal], initiator_id)
    missing = _missing_support_ids_for_open_interaction(state)
    tile = entry["tile"]
    title_name = _tile_display_name(state, tile)
    proposals = []
    if not missing:
        active_id = _legal_active_actor(state) or str(state.get("active_capability_id") or "")
        if active_id:
            commands = [{"type": "resolve_interaction", "payload": {"capability_id": active_id}}]
            interaction_summary = _interaction_resolution_summary(state, entry, preferred_ability_id=active_id)
            statistics = _plan_statistics(state, commands=commands, interactions=[entry])
            statistics["interaction_summaries"] = [interaction_summary]
            statistics["expected_resource_delta"] = interaction_summary.get("expected_delta") or {}
            proposals.append(
                _public_plan(
                    plan_id=f"confirm_interaction_{active_id}_{(entry['instance'] or {}).get('instance_id')}",
                    proposer_ability_id=active_id,
                    title=f"Confirm {title_name}",
                    rationale="All visible normal success requirements are currently covered. Confirming resolves the interaction.",
                    risk_label="low",
                    step_preview=["Confirm the played cards", "Apply success effects", "Recalculate after any surprise draw"],
                    expected_resources=_resource_estimate(),
                    score=115,
                    commands=commands,
                    plan_chain=_plan_chain(["Confirm interaction"], commands),
                    statistics=statistics,
                )
            )
        return _advised_active_proposals(state, proposals, active_id)
    active_id = str(state.get("active_capability_id") or "")
    active_plan = None
    active_support_command_type = ""
    if active_id in (state.get("capabilities") or {}):
        active_commands, _active_entries, _active_label = _next_interaction_support_command(state, active_id)
        if active_commands:
            active_support_command_type = str(active_commands[0].get("type") or "")
            active_estimate = _support_candidate_estimate(state, active_id, missing, entry)
            active_plan = _support_candidate_plan(
                state,
                ability_id=active_id,
                include_take_control=False,
                entry=entry,
                estimate=active_estimate,
            )
    candidates: list[tuple[str, bool]] = [(active_id, False)] if active_plan else []
    for ability_id in _all_capability_ids(state):
        if ability_id == active_id:
            continue
        capability = _capability(state, ability_id)
        has_direct_support = bool(_selected_cards_matching_requirements(capability, missing))
        estimate = _support_candidate_estimate(state, ability_id, missing, entry)
        if not has_direct_support and not estimate.get("can_improve_by_drawing") and not estimate.get("is_human"):
            continue
        include_take_control = not has_direct_support
        if include_take_control and not _has_control_take_left(capability):
            continue
        candidates.append((ability_id, include_take_control))
    for ability_id, include_take_control in candidates:
        capability = _capability(state, ability_id)
        selected = _selected_cards_for_requirements(capability, missing)
        estimate = _support_candidate_estimate(state, ability_id, missing, entry)
        plan = active_plan if ability_id == active_id and not include_take_control else _support_candidate_plan(
            state,
            ability_id=ability_id,
            include_take_control=include_take_control,
            entry=entry,
            estimate=estimate,
        )
        if plan:
            if selected is not None:
                plan["plan_id"] = f"support_interaction_{ability_id}_{(entry['instance'] or {}).get('instance_id')}"
            proposals.append(plan)
    if active_plan and active_support_command_type == "resolve_interaction" and proposals:
        return _advised_active_proposals(state, proposals, active_id)
    has_direct_support_plan = any(
        str(((plan.get("commands") or [{}])[0]).get("type") or "") == "resolve_interaction"
        for plan in proposals
    )
    if not has_direct_support_plan:
        fail_payload: dict[str, Any] = {}
        if any(str(effect.get("type") or "") == "pulpita_move_free" for effect in (tile or {}).get("failure_effects") or []):
            current_node_id = str((state.get("poulpita") or {}).get("node_id") or "")
            adjacent = sorted(str(node_id) for node_id in ((state.get("map") or {}).get("adjacency") or {}).get(current_node_id, []) or [])
            if adjacent:
                fail_payload["target_node_id"] = adjacent[0]
        fail_commands = [{"type": "fail_interaction", "payload": fail_payload}]
        fail_statistics = _plan_statistics(
            state,
            commands=fail_commands,
            interactions=[entry],
            assumptions=["Failure is available when no support path can be planned."],
        )
        interaction_summary = _interaction_resolution_summary(state, entry)
        fail_statistics["interaction_summaries"] = [interaction_summary]
        fail_statistics["expected_resource_delta"] = _effect_delta((tile or {}).get("failure_effects") or [])
        proposals.append(
            _public_plan(
                plan_id=f"fail_interaction_{(entry['instance'] or {}).get('instance_id')}",
                proposer_ability_id=None,
                title=f"Fail {title_name}",
                rationale="No ability has a planned path to provide the missing support. Accepting failure keeps the game moving and applies the configured penalties.",
                risk_label="high",
                step_preview=["Accept the failed interaction"],
                expected_resources=_resource_estimate(),
                score=35,
                warnings=[] if fail_payload or not any(str(effect.get("type") or "") == "pulpita_move_free" for effect in (tile or {}).get("failure_effects") or []) else ["No legal free-move target is available."],
                commands=fail_commands,
                plan_chain=_plan_chain(["Fail interaction"], fail_commands),
                statistics=fail_statistics,
            )
        )
    return proposals


def _collect_simulation_after_expected_roll(state: dict[str, Any], ability_id: str, *, include_take_control: bool) -> dict[str, Any]:
    simulated = _clone_simulation_state(state)
    simulated["phase"] = "night_action"
    simulated["active_capability_id"] = ability_id
    capability = simulated["capabilities"].setdefault(ability_id, {})
    expected_roll = _expected_ap_roll(state)
    capability["pa"] = int(capability.get("pa") or 0) + expected_roll
    capability["actions_taken_this_control"] = int(capability.get("actions_taken_this_control") or 0) + 1
    if include_take_control:
        capability["control_takes_this_night"] = int(capability.get("control_takes_this_night") or 0) + 1
    return simulated


def _optimistic_collect_followup(
    state: dict[str, Any],
    ability_id: str,
    *,
    include_take_control: bool,
    forced_first_commands: list[dict[str, Any]] | None = None,
    variant_label: str | None = None,
) -> dict[str, Any]:
    simulated = _collect_simulation_after_expected_roll(state, ability_id, include_take_control=include_take_control)
    capability = simulated["capabilities"].setdefault(ability_id, {})
    expected_roll = _expected_ap_roll(state)
    current_node_id = str((state.get("poulpita") or {}).get("node_id") or "")
    max_followup_actions = max(1, _planning_depth_take_controls(state) * max(1, int(capability.get("max_actions_per_control") or 3)) - 1)
    followup_steps: list[str] = [f"Expected roll gives {expected_roll} AP"]
    followup_public_commands: list[dict[str, Any]] = []
    followup_interactions: list[dict[str, Any]] = []
    followup_label = "future actions"
    score_bonus = 0
    shelter_distance = _distance_to_closest_shelter(simulated, current_node_id)
    controls_used = 1
    max_controls = _planning_depth_take_controls(state)
    stop_reason = "max follow-up actions reached"

    for command in forced_first_commands or []:
        if len(followup_public_commands) >= max_followup_actions:
            break
        followup_steps.append(_rollout_command_label(simulated, command))
        followup_public_commands.append(command)
        if str(command.get("type") or "") == "start_interaction":
            entry = _simulated_tile_entry(simulated, str((command.get("payload") or {}).get("tile_instance_id") or ""))
            if entry:
                followup_interactions.append(entry)
        _simulate_public_command(simulated, command)
        followup_label = variant_label or _rollout_command_label(simulated, command)

    def choose_next_control(current_ability_id: str) -> str | None:
        choices = []
        for candidate_id in _all_capability_ids(simulated):
            if candidate_id == "intelligence" or candidate_id == current_ability_id:
                continue
            candidate = _capability(simulated, candidate_id)
            if not _has_control_take_left(candidate):
                continue
            candidate_state = {
                **simulated,
                "phase": "night_action",
                "active_capability_id": candidate_id,
                "capabilities": {
                    capability_id: dict(capability_entry)
                    for capability_id, capability_entry in (simulated.get("capabilities") or {}).items()
                },
            }
            candidate_capability = _capability(candidate_state, candidate_id)
            candidate_capability["control_takes_this_night"] = int(candidate_capability.get("control_takes_this_night") or 0) + 1
            candidate_capability["actions_taken_this_control"] = 0
            commands, interactions, _label = _rollout_next_commands(candidate_state, candidate_id)
            if not commands:
                continue
            interaction_gain = sum(_delta_score(_interaction_resolution_summary(candidate_state, entry, preferred_ability_id=candidate_id).get("expected_delta") or {}) for entry in interactions)
            support_gain = _interaction_support_score(candidate_state, candidate_id) if candidate_state.get("interaction") else 0
            choices.append((interaction_gain + support_gain + len(commands), candidate_id))
        if not choices:
            return None
        choices.sort(key=lambda item: item[0], reverse=True)
        return choices[0][1]

    for _index in range(max_followup_actions):
        if _action_slots_left(_capability(simulated, ability_id)) <= 0:
            if controls_used >= max_controls:
                stop_reason = "planning depth controls exhausted"
                break
            next_ability_id = choose_next_control(ability_id)
            if not next_ability_id:
                stop_reason = "no eligible next control after action slots exhausted"
                break
            take_control_command = {"type": "take_control", "payload": {"capability_id": next_ability_id}}
            followup_steps.append(f"{(_capability(simulated, next_ability_id).get('name') or next_ability_id)} takes control")
            followup_public_commands.append(take_control_command)
            _simulate_public_command(simulated, take_control_command)
            ability_id = next_ability_id
            capability = _capability(simulated, ability_id)
            controls_used += 1
        commands, interactions, label = _rollout_next_commands(simulated, ability_id)
        if not commands:
            if controls_used < max_controls:
                next_ability_id = choose_next_control(ability_id)
                if next_ability_id:
                    take_control_command = {"type": "take_control", "payload": {"capability_id": next_ability_id}}
                    followup_steps.append(f"{(_capability(simulated, next_ability_id).get('name') or next_ability_id)} takes control")
                    followup_public_commands.append(take_control_command)
                    _simulate_public_command(simulated, take_control_command)
                    ability_id = next_ability_id
                    capability = _capability(simulated, ability_id)
                    controls_used += 1
                    continue
            if len(followup_steps) == 1:
                followup_steps.append("Recalculate with the real dice result")
            stop_reason = label or "no rollout command available"
            break
        for command in commands:
            command_type = str(command.get("type") or "")
            payload = command.get("payload") or {}
            if command_type == "move_poulpita":
                followup_steps.append(f"Move {payload.get('target_node_id') or '?'}")
            elif command_type == "start_interaction":
                entry = _simulated_tile_entry(simulated, str(payload.get("tile_instance_id") or ""))
                followup_steps.append(f"Interact {_tile_display_name(simulated, entry['tile']) if entry else 'tile'}")
            elif command_type == "resolve_interaction":
                followup_steps.append("Confirm interaction")
            elif command_type == "draw_action_card":
                followup_steps.append("Draw action card")
            else:
                followup_steps.append(command_type.replace("_", " ").title())
            followup_public_commands.append(command)
            _simulate_public_command(simulated, command)
        followup_interactions.extend(interactions)
        followup_label = label
        if interactions:
            score_bonus += 22 + sum(_delta_score(_interaction_resolution_summary(state, entry, preferred_ability_id=ability_id).get("expected_delta") or {}) for entry in interactions)
        elif commands and str(commands[0].get("type") or "") == "move_poulpita":
            score_bonus += 12
        elif commands and str(commands[0].get("type") or "") == "draw_action_card":
            score_bonus += 8
        shelter_distance = _distance_to_closest_shelter(simulated, str((simulated.get("poulpita") or {}).get("node_id") or ""))
    unique_interactions = []
    seen_interaction_ids: set[str] = set()
    for entry in followup_interactions:
        instance_id = str((entry.get("instance") or {}).get("instance_id") or "")
        if instance_id and instance_id in seen_interaction_ids:
            continue
        if instance_id:
            seen_interaction_ids.add(instance_id)
        unique_interactions.append(entry)
    return {
        "steps": followup_steps,
        "public_commands": followup_public_commands,
        "interactions": unique_interactions,
        "summaries": [_interaction_resolution_summary(simulated, entry, preferred_ability_id=ability_id) for entry in unique_interactions],
        "label": followup_label,
        "score_bonus": score_bonus,
        "shelter_distance": shelter_distance,
        "stop_reason": stop_reason,
        "controls_used": controls_used,
        "followup_action_count": len(followup_public_commands),
    }


def _collect_followup_variants(state: dict[str, Any], ability_id: str, *, include_take_control: bool) -> list[tuple[str, dict[str, Any]]]:
    variants: list[tuple[str, dict[str, Any]]] = [("best", _optimistic_collect_followup(state, ability_id, include_take_control=include_take_control))]
    simulated = _collect_simulation_after_expected_roll(state, ability_id, include_take_control=include_take_control)
    capability = _capability(simulated, ability_id)
    current_node_id = str((simulated.get("poulpita") or {}).get("node_id") or "")
    move_cost = _action_cost(simulated, "move")
    interact_cost = _action_cost(simulated, "interact")
    seen_first_keys = {
        _proposal_command_key((variants[0][1].get("public_commands") or [{}])[0])
        if variants[0][1].get("public_commands")
        else ""
    }
    max_variants = max(1, _max_plans_per_proposer(state))

    def add_variant(variant_id: str, command: dict[str, Any], label: str) -> None:
        if len(variants) >= max_variants:
            return
        key = _proposal_command_key(command)
        if not key or key in seen_first_keys:
            return
        seen_first_keys.add(key)
        variants.append(
            (
                variant_id,
                _optimistic_collect_followup(
                    state,
                    ability_id,
                    include_take_control=include_take_control,
                    forced_first_commands=[command],
                    variant_label=label,
                ),
            )
        )

    current_compulsory = _compulsory_choices_on_node(simulated, current_node_id)
    if _can_pay_action_cost(simulated, capability, interact_cost):
        for entry in current_compulsory + _visible_current_tiles(simulated):
            if _can_initiate(simulated, ability_id, entry.get("tile") or {}):
                add_variant(
                    f"interact_{(entry.get('instance') or {}).get('instance_id')}",
                    {
                        "type": "start_interaction",
                        "payload": {
                            "capability_id": ability_id,
                            "tile_instance_id": (entry.get("instance") or {}).get("instance_id"),
                            "auto_select_cards": True,
                        },
                    },
                    f"forced {_tile_display_name(simulated, entry.get('tile') or {})}",
                )
    if not current_compulsory and _can_pay_action_cost(simulated, capability, move_cost):
        scored_nodes = []
        for adjacent_node_id in ((simulated.get("map") or {}).get("adjacency") or {}).get(current_node_id, []) or []:
            node_score, _node_entries, _shelter_distance = _node_followup_score(simulated, str(adjacent_node_id), ability_id)
            scored_nodes.append((node_score, str(adjacent_node_id)))
        scored_nodes.sort(key=lambda item: item[0], reverse=True)
        for _score, target_node_id in scored_nodes:
            add_variant(
                f"move_{target_node_id}",
                {"type": "move_poulpita", "payload": {"capability_id": ability_id, "target_node_id": target_node_id}},
                f"node {target_node_id}",
            )
    draw_cost = _action_cost(simulated, "draw")
    if (
        _can_pay_action_cost(simulated, capability, draw_cost)
        and len(capability.get("hand") or []) < int(capability.get("current_max_cards_in_hand") or 3)
        and (capability.get("draw_pile") or capability.get("discard"))
    ):
        add_variant(
            "draw",
            {"type": "draw_action_card", "payload": {"capability_id": ability_id}},
            "card draw",
        )
    return variants


def _collect_plan(
    state: dict[str, Any],
    *,
    ability_id: str,
    include_take_control: bool,
    base_score: float,
    rationale: str,
    variant_id: str = "best",
    followup: dict[str, Any] | None = None,
) -> dict[str, Any]:
    capability = _capability(state, ability_id)
    name = capability.get("name") or ability_id
    collect_cost = _action_cost(state, "gain_ap")
    commands = []
    if include_take_control:
        commands.append({"type": "take_control", "payload": {"capability_id": ability_id}})
    commands.append({"type": "collect_action_points", "payload": {"capability_id": ability_id}})
    followup = followup or _optimistic_collect_followup(state, ability_id, include_take_control=include_take_control)
    followup_public_commands = followup.get("public_commands") or []
    followup_action_labels = (followup.get("steps") or [])[1 : 1 + len(followup_public_commands)]
    step_preview = ([f"{name} takes control"] if include_take_control else []) + ["Collect action points"] + followup_action_labels
    expected_resources = _resource_estimate(
        ap=collect_cost["ap_cost"],
        time_steps=collect_cost["time_cost"],
        control_takes={ability_id: 1} if include_take_control else {},
    )
    expected_resources["expected_ap_gain_by_ability"] = {ability_id: _expected_ap_roll(state)}
    expected_delta = _merge_deltas([summary.get("expected_delta") or {} for summary in followup.get("summaries") or []])
    expected_resources["energy_delta_expected"] = expected_delta.get("energy", 0)
    expected_resources["shells_delta_expected"] = expected_delta.get("seashells", 0)
    expected_resources["neurons_delta_expected"] = expected_delta.get("neurons", 0)
    expected_resources["expected_resource_delta"] = expected_delta
    plan_chain = _plan_chain(step_preview, commands)
    for public_index, public_command in enumerate(followup_public_commands):
        chain_index = len(commands) + public_index
        if chain_index < len(plan_chain):
            plan_chain[chain_index]["public_command"] = _safe_public_command(public_command)
            plan_chain[chain_index]["auto_executable"] = bool(plan_chain[chain_index]["public_command"])
            plan_chain[chain_index]["command_type"] = public_command.get("type")
    for index in range(len(commands) + len(followup_public_commands), len(plan_chain)):
        plan_chain[index]["auto_executable"] = False
        plan_chain[index]["decision_boundary"] = True
        plan_chain[index]["command_type"] = None
    statistics = _plan_statistics(
        state,
        commands=commands + followup_public_commands,
        interactions=followup.get("interactions") or [],
        assumptions=[
            f"Collect AP is simulated with expected roll {_expected_ap_roll(state)} for follow-up planning.",
            "Later steps are optimistic public actions and are rechecked by the authoritative reducer when executed.",
            "Surprise cards are modeled optimistically as no-op until one is actually drawn.",
        ],
    )
    if followup.get("summaries"):
        statistics["interaction_summaries"] = followup["summaries"]
        statistics["expected_resource_delta"] = expected_delta
    if followup.get("shelter_distance") is not None:
        statistics["distance_to_closest_known_shelter"] = followup["shelter_distance"]
    statistics["rollout_debug"] = {
        "stop_reason": followup.get("stop_reason"),
        "controls_used": followup.get("controls_used"),
        "followup_action_count": followup.get("followup_action_count"),
        "followup_label": followup.get("label"),
    }
    plan_id = f"{'take_control_' if include_take_control else ''}collect_{ability_id}"
    if variant_id != "best":
        plan_id = f"{plan_id}_{variant_id}"
    return _public_plan(
        plan_id=plan_id,
        proposer_ability_id=ability_id,
        title=f"{name} collects AP toward {followup['label']}",
        rationale=f"{rationale} The planner assumes an average AP roll of {_expected_ap_roll(state)} for deeper evaluation.",
        risk_label="low",
        step_preview=step_preview,
        expected_resources=expected_resources,
        score=base_score + float(followup.get("score_bonus") or 0),
        commands=commands,
        plan_chain=plan_chain,
        statistics=statistics,
        plan_group=f"collect:{ability_id}:{followup['label']}",
    )


def _collect_plan_variants(
    state: dict[str, Any],
    *,
    ability_id: str,
    include_take_control: bool,
    base_score: float,
    rationale: str,
) -> list[dict[str, Any]]:
    if not _can_pay_action_cost(state, _capability(state, ability_id), _action_cost(state, "gain_ap")):
        return []
    return [
        _collect_plan(
            state,
            ability_id=ability_id,
            include_take_control=include_take_control,
            base_score=base_score,
            rationale=rationale,
            variant_id=variant_id,
            followup=followup,
        )
        for variant_id, followup in _collect_followup_variants(state, ability_id, include_take_control=include_take_control)
    ]


def _move_plan(
    state: dict[str, Any],
    *,
    ability_id: str,
    target_node_id: str,
    include_take_control: bool,
    base_score: float,
    rationale: str,
) -> dict[str, Any]:
    capability = _capability(state, ability_id)
    name = capability.get("name") or ability_id
    move_cost = _action_cost(state, "move")
    commands = []
    simulated = _clone_simulation_state(state)
    if include_take_control:
        take_control_command = {"type": "take_control", "payload": {"capability_id": ability_id}}
        commands.append(take_control_command)
        _simulate_public_command(simulated, take_control_command)
    move_command = {"type": "move_poulpita", "payload": {"capability_id": ability_id, "target_node_id": target_node_id}}
    commands.append(move_command)
    _simulate_public_command(simulated, move_command)
    followup = _optimistic_followup_from_state(simulated, start_ability_id=ability_id, max_steps=max(0, 8 - len(commands)))
    followup_commands = list(followup.get("public_commands") or [])
    followup_interactions = list(followup.get("interactions") or [])
    target_compulsory = _compulsory_choices_on_node(state, str(target_node_id), highest_only=False)
    warnings = []
    if target_compulsory:
        warnings.append("Destination has known compulsory tiles; the optimistic branch tries to clear them before leaving the node.")
        initiable_count = sum(1 for entry in target_compulsory if _can_initiate(state, ability_id, entry["tile"]))
        if initiable_count < len(target_compulsory):
            warnings.append("Another ability may need to take initiative to cover all compulsory interactions there.")
    step_labels = ([f"{name} takes control"] if include_take_control else []) + [f"Move Poulpita to {target_node_id}"] + list(followup.get("steps") or [])
    if len(step_labels) == (2 if include_take_control else 1):
        step_labels.append("Reveal nearby tiles")
    statistics = _plan_statistics(
        state,
        commands=commands + followup_commands,
        interactions=followup_interactions or target_compulsory,
        assumptions=["Movement follow-up is planned optimistically; revealed information and every later command are rechecked by the authoritative reducer."],
    )
    if followup_interactions:
        statistics["interaction_summaries"] = [
            _interaction_resolution_summary(state, entry, preferred_ability_id=ability_id)
            for entry in followup_interactions
        ]
    elif target_compulsory:
        statistics["interaction_summaries"] = [
            _interaction_resolution_summary(state, entry, preferred_ability_id=ability_id)
            for entry in target_compulsory
        ]
    statistics["distance_to_closest_known_shelter"] = _distance_to_closest_shelter(state, str(target_node_id))
    expected_delta = _merge_deltas([summary.get("expected_delta") or {} for summary in statistics.get("interaction_summaries") or []])
    expected_resources = _resource_estimate(
        ap=move_cost["ap_cost"],
        time_steps=move_cost["time_cost"],
        control_takes={ability_id: 1} if include_take_control else {},
    )
    expected_resources["expected_resource_delta"] = expected_delta
    expected_resources["energy_delta_expected"] = expected_delta.get("energy", 0)
    expected_resources["shells_delta_expected"] = expected_delta.get("seashells", 0)
    expected_resources["neurons_delta_expected"] = expected_delta.get("neurons", 0)
    return _public_plan(
        plan_id=f"{'take_control_' if include_take_control else ''}move_{ability_id}_{target_node_id}",
        proposer_ability_id=ability_id,
        title=f"{name} moves to {target_node_id}" if target_compulsory else f"{name} inspects {target_node_id}",
        rationale=rationale,
        risk_label="forced" if target_compulsory else "moderate",
        step_preview=step_labels,
        expected_resources=expected_resources,
        score=base_score + len(followup_commands) + _delta_score(expected_delta),
        warnings=warnings,
        commands=commands + followup_commands,
        plan_chain=_plan_chain(step_labels, commands + followup_commands),
        statistics=statistics,
        plan_group=f"move:{target_node_id}",
    )


def _end_night_plan(state: dict[str, Any]) -> dict[str, Any] | None:
    if not _can_end_night_now(state):
        return None
    ability_id = str(state.get("active_capability_id") or "")
    capability = _capability(state, ability_id)
    commands = [{"type": "end_night", "payload": {"capability_id": ability_id}}]
    lateness = _night_lateness_score(state)
    statistics = _plan_statistics(
        state,
        commands=commands,
        assumptions=["Ending the night is free and is prioritized when Poulpita is on a shelter late in the night."],
    )
    expected_resources = _resource_estimate()
    expected_resources["expected_resource_delta"] = {"energy": 1 if int(state.get("night_time_spent") or 0) >= int(state.get("night_time_total") or 24) else 0}
    return _public_plan(
        plan_id=f"end_night_{ability_id}",
        proposer_ability_id=ability_id or None,
        title="End the night at shelter",
        rationale="Poulpita is on a shelter and enough night time has passed. Ending now avoids late-night energy loss and opens day upgrades.",
        risk_label="low",
        step_preview=[f"{capability.get('name') or ability_id} ends the night"],
        expected_resources=expected_resources,
        score=95 + lateness,
        commands=commands,
        plan_chain=_plan_chain(["End night"], commands),
        statistics=statistics,
    )


def _night_idle_proposals(state: dict[str, Any]) -> list[dict[str, Any]]:
    proposals = []
    current_node_id = str((state.get("poulpita") or {}).get("node_id") or "")
    compulsory = _compulsory_choices_on_node(state, current_node_id)
    shelter_return = _shelter_return_context(state, current_node_id)
    visible_entries = _visible_current_tiles(state)
    visible_initiators = {
        ability_id
        for ability_id in _playable_ability_ids(state)
        if any(_can_initiate(state, ability_id, entry.get("tile") or {}) for entry in visible_entries)
    }
    move_cost = _action_cost(state, "move")
    adjacent = list(((state.get("map") or {}).get("adjacency") or {}).get(current_node_id) or [])
    if not compulsory and shelter_return["should_return"]:
        target_node_id = str(shelter_return["next_node_id"])
        for ability_id in _playable_ability_ids(state):
            capability = _capability(state, ability_id)
            if not _has_control_take_left(capability):
                continue
            if _can_pay_action_cost(state, capability, move_cost):
                proposals.append(
                    _move_plan(
                        state,
                        ability_id=ability_id,
                        target_node_id=target_node_id,
                        include_take_control=True,
                        base_score=90 + float(shelter_return["urgency"]),
                        rationale="Night is approaching its safe return window. This is the next step on the shortest known route to a shelter without compulsory blockers.",
                    )
                )
            else:
                proposals.extend(
                    _collect_plan_variants(
                        state,
                        ability_id=ability_id,
                        include_take_control=True,
                        base_score=75 + float(shelter_return["urgency"]),
                        rationale="Night is approaching its safe return window. This ability needs AP before following the safe shelter route.",
                    )
                )
        if proposals:
            return proposals
    for ability_id in _playable_ability_ids(state):
        capability = _capability(state, ability_id)
        if not _has_control_take_left(capability):
            continue
        if compulsory:
            for entry in compulsory:
                if _can_initiate(state, ability_id, entry["tile"]):
                    proposals.append(_forced_interaction_plan(state, ability_id=ability_id, entry=entry, include_take_control=True, score=100))
                    break
            continue
        if visible_initiators:
            if ability_id not in visible_initiators:
                continue
            for entry in visible_entries:
                if _can_initiate(state, ability_id, entry.get("tile") or {}):
                    proposals.append(
                        _forced_interaction_plan(
                            state,
                            ability_id=ability_id,
                            entry=entry,
                            include_take_control=True,
                            score=75,
                        )
                    )
            continue
        proposals.extend(_collect_plan_variants(state, ability_id=ability_id, include_take_control=True, base_score=35, rationale="This bot ability can legally take control and collect AP."))
        if _can_pay_action_cost(state, capability, move_cost):
            scored_nodes = []
            for adjacent_node_id in adjacent:
                node_score, _node_entries, _shelter_distance = _node_followup_score(state, str(adjacent_node_id), ability_id)
                scored_nodes.append((node_score, str(adjacent_node_id)))
            scored_nodes.sort(key=lambda item: item[0], reverse=True)
            for _score, target_node_id in scored_nodes[:2]:
                proposals.append(
                    _move_plan(
                        state,
                        ability_id=ability_id,
                        target_node_id=target_node_id,
                        include_take_control=True,
                        base_score=28,
                        rationale="This bot can take initiative and move as an alternative branch; later known interactions are planned optimistically.",
                    )
                )
    return proposals


def _active_night_proposals(state: dict[str, Any]) -> list[dict[str, Any]]:
    proposals = []
    current_node_id = str((state.get("poulpita") or {}).get("node_id") or "")
    current_compulsory = _compulsory_choices_on_node(state, current_node_id)
    visible_entries = _visible_current_tiles(state)
    interact_cost = _action_cost(state, "interact")
    end_night = _end_night_plan(state)
    if end_night:
        return _advised_active_proposals(state, [end_night], str(state.get("active_capability_id") or ""))
    if current_compulsory and not state.get("interaction"):
        forced_proposals = []
        actor_candidates = _forced_actor_candidates(state, current_compulsory)
        for ability_id, include_take_control in actor_candidates:
            capability = _capability(state, ability_id)
            if not _can_pay_action_cost(state, capability, interact_cost):
                collect_cost = _action_cost(state, "gain_ap")
                can_reach_interaction_with_ap = (
                    int(capability.get("pa") or 0) < interact_cost["ap_cost"]
                    and int((state.get("poulpita") or {}).get("neurons") or 0) >= interact_cost["neuron_cost"]
                )
                if can_reach_interaction_with_ap and _can_pay_action_cost(state, capability, collect_cost):
                    forced_proposals.extend(
                        _collect_plan_variants(
                            state,
                            ability_id=ability_id,
                            include_take_control=include_take_control,
                            base_score=110 if not include_take_control else 100,
                            rationale=(
                                "The current ability can initiate the compulsory interaction but first needs AP."
                                if not include_take_control
                                else "The current ability cannot initiate the compulsory interaction; this ability can take control and collect the AP needed for it."
                            ),
                        )
                    )
                continue
            for entry in current_compulsory:
                if _can_initiate(state, ability_id, entry["tile"]):
                    forced_proposals.append(
                        _forced_interaction_plan(
                            state,
                            ability_id=ability_id,
                            entry=entry,
                            include_take_control=include_take_control,
                            score=105 if include_take_control else 115,
                        )
                    )
                    break
        if forced_proposals:
            proposals.extend(forced_proposals)
            if actor_candidates and not actor_candidates[0][1]:
                return _advised_active_proposals(state, proposals, actor_candidates[0][0])
            return proposals
        if proposals:
            return proposals
        return [_forced_blocker_plan(state, current_compulsory)]
    active_id = _legal_active_actor(state)
    if not active_id:
        if not current_compulsory and not state.get("interaction"):
            move_cost = _action_cost(state, "move")
            adjacent = list(((state.get("map") or {}).get("adjacency") or {}).get(current_node_id) or [])
            shelter_return = _shelter_return_context(state, current_node_id)
            if shelter_return["should_return"]:
                target_node_id = str(shelter_return["next_node_id"])
                for ability_id in _playable_ability_ids(state):
                    capability = _capability(state, ability_id)
                    if ability_id == str(state.get("active_capability_id") or "") or not _has_control_take_left(capability):
                        continue
                    if _can_pay_action_cost(state, capability, move_cost):
                        proposals.append(
                            _move_plan(
                                state,
                                ability_id=ability_id,
                                target_node_id=target_node_id,
                                include_take_control=True,
                                base_score=90 + float(shelter_return["urgency"]),
                                rationale="The previous control is exhausted. This ability can continue along the shortest safe route to shelter.",
                            )
                        )
                    else:
                        proposals.extend(
                            _collect_plan_variants(
                                state,
                                ability_id=ability_id,
                                include_take_control=True,
                                base_score=75 + float(shelter_return["urgency"]),
                                rationale="The previous control is exhausted. This ability needs AP to continue toward shelter.",
                            )
                        )
                if proposals:
                    return proposals
            eligible_visible_initiators = {
                ability_id
                for ability_id in _playable_ability_ids(state)
                if ability_id != str(state.get("active_capability_id") or "")
                and _has_control_take_left(_capability(state, ability_id))
                and any(_can_initiate(state, ability_id, entry.get("tile") or {}) for entry in visible_entries)
            }
            for ability_id in _playable_ability_ids(state):
                capability = _capability(state, ability_id)
                if ability_id == str(state.get("active_capability_id") or "") or not _has_control_take_left(capability):
                    continue
                if eligible_visible_initiators:
                    if ability_id not in eligible_visible_initiators:
                        continue
                    for entry in visible_entries:
                        if _can_initiate(state, ability_id, entry.get("tile") or {}):
                            proposals.append(
                                _forced_interaction_plan(
                                    state,
                                    ability_id=ability_id,
                                    entry=entry,
                                    include_take_control=True,
                                    score=75,
                                )
                            )
                    continue
                proposals.extend(
                    _collect_plan_variants(
                        state,
                        ability_id=ability_id,
                        include_take_control=True,
                        base_score=32,
                        rationale="The current initiative has no actions left. This bot can take initiative and continue the team plan.",
                    )
                )
                if _can_pay_action_cost(state, capability, move_cost):
                    scored_nodes = []
                    for adjacent_node_id in adjacent:
                        node_score, _node_entries, _shelter_distance = _node_followup_score(state, str(adjacent_node_id), ability_id)
                        scored_nodes.append((node_score, str(adjacent_node_id)))
                    scored_nodes.sort(key=lambda item: item[0], reverse=True)
                    for _score, target_node_id in scored_nodes[:3]:
                        proposals.append(
                            _move_plan(
                                state,
                                ability_id=ability_id,
                                target_node_id=target_node_id,
                                include_take_control=True,
                                base_score=26,
                                rationale="The current initiative has no actions left. This bot can take initiative and move as an alternative branch.",
                            )
                        )
        return proposals
    capability = _capability(state, active_id)
    name = capability.get("name") or active_id
    if current_compulsory and _can_pay_action_cost(state, capability, interact_cost) and not state.get("interaction"):
        for entry in current_compulsory:
            if _can_initiate(state, active_id, entry["tile"]):
                proposals.append(_forced_interaction_plan(state, ability_id=active_id, entry=entry, include_take_control=False, score=100))
                break
    shelter_return = _shelter_return_context(state, current_node_id)
    if not current_compulsory and shelter_return["should_return"]:
        move_cost = _action_cost(state, "move")
        if _can_pay_action_cost(state, capability, move_cost):
            route_plan = _move_plan(
                state,
                ability_id=active_id,
                target_node_id=str(shelter_return["next_node_id"]),
                include_take_control=False,
                base_score=95 + float(shelter_return["urgency"]),
                rationale="Night is approaching its safe return window. This move follows the shortest known path to shelter without compulsory blockers.",
            )
            route_plan["statistics"]["safe_shelter_route"] = shelter_return["route"]
            route_plan["statistics"]["shelter_return_start"] = shelter_return["return_start"]
            return _advised_active_proposals(state, [route_plan], active_id)
        collect_plans = _collect_plan_variants(
            state,
            ability_id=active_id,
            include_take_control=False,
            base_score=80 + float(shelter_return["urgency"]),
            rationale="Night is approaching its safe return window. Collect AP now to pay for the next shelter-route move.",
        )
        if collect_plans:
            return _advised_active_proposals(state, collect_plans, active_id)
    visible_interaction_path = any(
        _can_initiate(state, ability_id, entry.get("tile") or {})
        for ability_id in _playable_ability_ids(state)
        for entry in visible_entries
    )
    active_visible_interactions = [
        entry
        for entry in visible_entries
        if _can_initiate(state, active_id, entry.get("tile") or {})
        and _can_pay_action_cost(state, capability, interact_cost)
    ]
    if not active_visible_interactions:
        proposals.extend(
            _collect_plan_variants(
                state,
                ability_id=active_id,
                include_take_control=False,
                base_score=65 if current_compulsory else 30,
                rationale="Collecting AP is legal and may be needed for forced or future actions.",
            )
        )
    draw_cost = _action_cost(state, "draw")
    hand_count = len(capability.get("hand") or [])
    hand_limit = int(capability.get("current_max_cards_in_hand") or 3)
    if (
        not current_compulsory
        and not active_visible_interactions
        and _can_pay_action_cost(state, capability, draw_cost)
        and hand_count < hand_limit
        and (capability.get("draw_pile") or capability.get("discard"))
    ):
        draw_commands = [{"type": "draw_action_card", "payload": {"capability_id": active_id}}]
        proposals.append(
            _public_plan(
                plan_id=f"draw_{active_id}",
                proposer_ability_id=active_id,
                title=f"{name} draws a card",
                rationale="Drawing is legal and may improve interaction coverage.",
                risk_label="low",
                step_preview=["Draw one action card", "Recalculate after the draw"],
                expected_resources=_resource_estimate(ap=draw_cost["ap_cost"], time_steps=draw_cost["time_cost"]),
                score=28,
                commands=draw_commands,
                plan_chain=_plan_chain(["Draw one action card"], draw_commands),
                statistics=_plan_statistics(state, commands=draw_commands),
            )
        )
    move_cost = _action_cost(state, "move")
    adjacent = list(((state.get("map") or {}).get("adjacency") or {}).get(current_node_id) or [])
    if not current_compulsory and not visible_interaction_path and adjacent and _can_pay_action_cost(state, capability, move_cost):
        for target_node_id in adjacent[:3]:
            proposals.append(
                _move_plan(
                    state,
                    ability_id=active_id,
                    target_node_id=str(target_node_id),
                    include_take_control=False,
                    base_score=34 if _compulsory_choices_on_node(state, str(target_node_id), highest_only=False) else 24,
                    rationale="A one-step move is legal. Known compulsory tiles on the destination are planned optimistically before optional follow-up actions.",
                )
            )
    if not current_compulsory and _can_pay_action_cost(state, capability, interact_cost) and not state.get("interaction"):
        for entry in active_visible_interactions:
            tile = entry["tile"]
            event = ((state.get("tile_catalog") or {}).get("events") or {}).get(tile.get("event_id")) or {}
            required_count = _interaction_requirements(tile)
            commands = _interaction_commands(active_id, entry)
            interaction_summary = _interaction_resolution_summary(state, entry, preferred_ability_id=active_id)
            expected_delta = interaction_summary.get("expected_delta") or {}
            expected_resources = _resource_estimate(ap=interact_cost["ap_cost"], time_steps=interact_cost["time_cost"])
            expected_resources["expected_resource_delta"] = expected_delta
            expected_resources["energy_delta_expected"] = expected_delta.get("energy", 0)
            expected_resources["shells_delta_expected"] = expected_delta.get("seashells", 0)
            expected_resources["neurons_delta_expected"] = expected_delta.get("neurons", 0)
            statistics = _plan_statistics(state, commands=commands, interactions=[entry])
            statistics["interaction_summaries"] = [interaction_summary]
            statistics["expected_resource_delta"] = expected_delta
            team_size, team_penalty = _interaction_team_penalty(state, entry, active_id)
            statistics["interaction_team_size"] = team_size
            statistics["initiative_change_penalty"] = team_penalty
            proposals.append(
                _public_plan(
                    plan_id=f"interact_{active_id}_{entry['instance'].get('instance_id')}",
                    proposer_ability_id=active_id,
                    title=f"Interact with {event.get('name') or tile.get('name') or 'tile'}",
                    rationale="This visible optional tile can be initiated by the active bot ability.",
                    risk_label="moderate",
                    step_preview=["Start interaction", "Resolve immediately" if required_count == 0 else "Pause if cards or shells are required"],
                    expected_resources=expected_resources,
                    score=55
                    + int(tile.get("priority") or 0)
                    + _planner_weight(state, "tile_resolution", 14.0)
                    + _delta_score(expected_delta)
                    - team_penalty,
                    warnings=[] if required_count == 0 else ["May require support cards."],
                    commands=commands,
                    plan_chain=_plan_chain(["Start interaction", "Resolve interaction"] if required_count == 0 else ["Start interaction"], commands),
                    statistics=statistics,
                )
            )
    return _advised_active_proposals(state, proposals, active_id)


def _day_proposals(state: dict[str, Any]) -> list[dict[str, Any]]:
    proposals = []
    current_node_id = str((state.get("poulpita") or {}).get("node_id") or "")
    raw_shelter = (state.get("shelters") or {}).get(current_node_id)
    shelter_count = int(raw_shelter.get("count") or 0) if isinstance(raw_shelter, dict) else int(raw_shelter or 0)
    shelter_shells = int(raw_shelter.get("seashells") or 0) if isinstance(raw_shelter, dict) else 0
    carried_shells = int((state.get("poulpita") or {}).get("seashells") or 0)
    if carried_shells > 1 and shelter_count > 0 and shelter_shells < 3:
        shell_moves = min(carried_shells - 1, 3 - shelter_shells)
        commands = [{"type": "move_seashell_to_shelter", "payload": {}} for _ in range(shell_moves)]
        proposals.append(
            _public_plan(
                plan_id="day_store_shells",
                proposer_ability_id=None,
                title=f"Store {shell_moves} seashell{'s' if shell_moves != 1 else ''} in the shelter",
                rationale="During day, shells carried by Poulpita can be moved into the current shelter. This can secure the shelter.",
                risk_label="low",
                step_preview=["Move shells to the current shelter", "Recalculate shelter security"],
                expected_resources=_resource_estimate(),
                score=140,
                objective_effect="Can progress secure-shelter objectives.",
                commands=commands,
                plan_chain=_plan_chain(["Move shell to shelter"] * len(commands), commands),
                statistics=_plan_statistics(state, commands=commands),
            )
        )
    cost, next_size = _poulpita_size_upgrade_cost(state)
    min_energy_after_growth = max(1, int(_bot_settings(state).get("min_energy_after_size_upgrade") or 4))
    current_energy = int((state.get("poulpita") or {}).get("energy") or 0)
    needs_size = any(
        str(objective.get("type") or "") == "increase_size"
        and int((state.get("objective_progress") or {}).get("size_increases") or 0) < max(1, int(objective.get("count") or 1))
        for objective in state.get("objectives") or []
    )
    if cost is not None and next_size and not (state.get("poulpita") or {}).get("size_upgraded_today") and current_energy - int(cost or 0) >= min_energy_after_growth:
        commands = [{"type": "buy_poulpita_size", "payload": {}}]
        statistics = _plan_statistics(
            state,
            commands=commands,
            assumptions=[f"Bot growth plans keep at least {min_energy_after_growth} energy after paying the size cost."],
        )
        statistics["expected_resource_delta"] = {"energy": -int(cost or 0), "size_index": 1}
        proposals.append(
            _public_plan(
                plan_id="day_buy_poulpita_size",
                proposer_ability_id=None,
                title="Grow Poulpita",
                rationale="Growing advances size objectives and is worth more than holding spare energy when enough energy remains afterward.",
                risk_label="low",
                step_preview=[f"Spend {int(cost or 0)} energy to grow"],
                expected_resources={"expected_resource_delta": {"energy": -int(cost or 0), "size_index": 1}, **_resource_estimate()},
                score=90 if needs_size else 55,
                objective_effect="Progresses size objectives." if needs_size else None,
                commands=commands,
                plan_chain=_plan_chain(["Grow Poulpita"], commands),
                statistics=statistics,
            )
        )
    shared_neurons = int((state.get("poulpita") or {}).get("neurons") or 0)
    for ability_id in _playable_ability_ids(state):
        capability = _capability(state, ability_id)
        purchased = {int(index) for index in capability.get("purchased_hand_size_upgrade_indices") or []}
        for index, upgrade in enumerate(capability.get("hand_size_upgrades") or []):
            if index in purchased:
                continue
            cost_neurons = max(0, int((upgrade or {}).get("cost") or 0))
            if shared_neurons < cost_neurons or str((upgrade or {}).get("cost_resource") or "neurons") != "neurons":
                continue
            upgrade_type = str((upgrade or {}).get("type") or "hand_size")
            commands = [{"type": "buy_hand_size_upgrade", "payload": {"capability_id": ability_id, "upgrade_index": index}}]
            gain_delta = {"neurons": -cost_neurons, "purchased_upgrades": 1}
            if upgrade_type == "hand_size":
                gain_delta["hand_capacity"] = max(1, int((upgrade or {}).get("hand_size_bonus") or 1))
            elif upgrade_type == "deck_exchange":
                gain_delta["cards_in_hand"] = 1
            statistics = _plan_statistics(state, commands=commands, assumptions=["Day upgrades are valued higher than holding neurons because they improve all future nights."])
            statistics["expected_resource_delta"] = gain_delta
            name = capability.get("name") or ability_id
            proposals.append(
                _public_plan(
                    plan_id=f"day_buy_upgrade_{ability_id}_{index}",
                    proposer_ability_id=ability_id,
                    title=f"Buy {name} upgrade",
                    rationale="Buying configured day upgrades converts shared neurons into persistent capability strength.",
                    risk_label="low",
                    step_preview=[f"Spend {cost_neurons} neurons on {name}"],
                    expected_resources={"expected_resource_delta": gain_delta, **_resource_estimate()},
                    score=80 + (20 if upgrade_type == "deck_exchange" else 10) - cost_neurons,
                    commands=commands,
                    plan_chain=_plan_chain([f"Buy {name} upgrade"], commands),
                    statistics=statistics,
                )
            )
    commands = [{"type": "end_day", "payload": {}}]
    proposals.append(
        _public_plan(
            plan_id="day_end_day",
            proposer_ability_id=None,
            title="Begin the next night",
            rationale="Ending day is legal at any time during the day. Use this if no upgrade or shell allocation is better.",
            risk_label="moderate",
            step_preview=["End day", "Reset controls and start the next night"],
            expected_resources=_resource_estimate(),
            score=10,
            commands=commands,
            plan_chain=_plan_chain(["End day"], commands),
            statistics=_plan_statistics(state, commands=commands),
        )
    )
    return proposals


def generate_bot_plan_status(state: dict[str, Any]) -> dict[str, Any]:
    bot_config = state.get("bot_config")
    if not bot_config or state.get("mode") not in {"solo_with_bots", "bots_only"}:
        return {
            "status": "disabled",
            "proposal_set_id": None,
            "generated_from_version": int(state.get("version") or 0),
            "proposals": [],
            "message": "Bot planning is disabled for this room.",
        }
    if state.get("pending_surprise"):
        proposals = _surprise_proposals(state)
    else:
        phase = str(state.get("phase") or "")
        if phase == "night_idle":
            proposals = _night_idle_proposals(state)
        elif phase == "night_action":
            proposals = _interaction_support_proposals(state) if state.get("interaction") else _active_night_proposals(state)
        elif phase == "day":
            proposals = _day_proposals(state)
        else:
            proposals = []
    generated_count = len(proposals)
    proposals, debug = _select_pareto_proposals(state, proposals, limit=_max_public_plans(state))
    debug["raw_generated_count"] = generated_count
    return {
        "status": "awaiting_selection" if proposals else "idle",
        "proposal_set_id": f"plans_{state.get('room_id')}_{int(state.get('version') or 0)}",
        "generated_from_version": int(state.get("version") or 0),
        "proposals": proposals,
        "message": "" if proposals else "No bot proposals are available for the current state.",
        "debug": debug,
    }


def _orchestrator_int_setting(state: dict[str, Any], key: str, fallback: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(_bot_settings(state).get(key) if _bot_settings(state).get(key) is not None else fallback)
    except (TypeError, ValueError):
        value = fallback
    return max(minimum, min(maximum, value))


def _orchestrator_float_setting(state: dict[str, Any], key: str, fallback: float, *, minimum: float, maximum: float) -> float:
    try:
        value = float(_bot_settings(state).get(key) if _bot_settings(state).get(key) is not None else fallback)
    except (TypeError, ValueError):
        value = fallback
    return max(minimum, min(maximum, value))


def _orchestrator_command(proposal: dict[str, Any]) -> dict[str, Any] | None:
    commands = _orchestrator_commands(proposal)
    return commands[0] if commands else None


def _orchestrator_commands(proposal: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        public_command
        for command in proposal.get("commands") or []
        if (public_command := _safe_public_command(command))
    ]


def _orchestrator_plan_score(proposal: dict[str, Any]) -> float:
    statistics = proposal.get("statistics") or {}
    try:
        return float(statistics.get("planner_score") or 0)
    except (TypeError, ValueError):
        return 0.0


def _weighted_rollout_plan(
    proposals: list[dict[str, Any]],
    *,
    generator: random.Random,
    temperature: float,
) -> dict[str, Any] | None:
    executable = [proposal for proposal in proposals if _orchestrator_command(proposal)]
    if not executable:
        return None
    scores = [_orchestrator_plan_score(proposal) for proposal in executable]
    maximum = max(scores)
    scale = max(1.0, 20.0 * temperature)
    weights = [math.exp(max(-30.0, min(0.0, (score - maximum) / scale))) for score in scores]
    threshold = generator.random() * sum(weights)
    cumulative = 0.0
    for proposal, weight in zip(executable, weights):
        cumulative += weight
        if cumulative >= threshold:
            return proposal
    return executable[-1]


def _orchestrator_plan_quality(proposal: dict[str, Any]) -> float:
    statistics = proposal.get("statistics") or {}
    axes = statistics.get("pareto_axes") or {}
    raw_confidence = statistics.get("confidence_score")
    if raw_confidence is None:
        raw_confidence = proposal.get("confidence")
    confidence = max(0.0, min(1.0, float(raw_confidence if raw_confidence is not None else 1.0)))
    return float(axes.get("expected_gain") or 0) * confidence * 0.1


def _local_orchestrator_candidate(
    state: dict[str, Any],
    *,
    plan_id: str,
    title: str,
    command: dict[str, Any],
    base_score: float,
    confidence: float = 1.0,
    expected_gain: float = 0.0,
) -> dict[str, Any]:
    simulated = _clone_simulation_state(state)
    before_score = _global_state_score(simulated)
    _simulate_public_command(simulated, command)
    state_delta = _global_state_score(simulated) - before_score
    planner_score = round(base_score + state_delta + expected_gain * confidence, 2)
    return {
        "plan_id": plan_id,
        "title": title,
        "commands": [command],
        "confidence": confidence,
        "statistics": {
            "planner_score": planner_score,
            "confidence_score": confidence,
            "pareto_axes": {
                "efficiency": 1.0,
                "confidence": confidence,
                "expected_gain": round(state_delta + expected_gain, 2),
            },
        },
    }


def _local_orchestrator_fail_command(state: dict[str, Any], entry: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    tile = entry.get("tile") or {}
    if any(str(effect.get("type") or "") == "pulpita_move_free" for effect in tile.get("failure_effects") or []):
        current_node_id = str((state.get("poulpita") or {}).get("node_id") or "")
        adjacent = sorted(str(node_id) for node_id in ((state.get("map") or {}).get("adjacency") or {}).get(current_node_id, []) or [])
        if adjacent:
            payload["target_node_id"] = adjacent[0]
    return {"type": "fail_interaction", "payload": payload}


def _local_orchestrator_surprise_candidates(state: dict[str, Any]) -> list[dict[str, Any]]:
    card = ((state.get("pending_surprise") or {}).get("card") or {})
    if not card:
        return []
    costs = card.get("costs") or []
    candidates = []
    for index, payload in enumerate(_surprise_accept_payloads(state, card)):
        public_payload = {
            "accept": True,
            **({"capability_id": payload.get("capability_id")} if payload.get("capability_id") else {}),
            **({"auto_select_cards": True} if payload.get("card_ids") else {}),
        }
        candidates.append(
            _local_orchestrator_candidate(
                state,
                plan_id=f"local_surprise_accept_{index}",
                title=f"Resolve {card.get('name') or 'surprise'}",
                command={"type": "resolve_surprise_card", "payload": public_payload},
                base_score=90 if not costs else 65,
                expected_gain=_weighted_expected_gain(state, _effect_delta(card.get("effects") or [])),
            )
        )
    if costs:
        candidates.append(
            _local_orchestrator_candidate(
                state,
                plan_id="local_surprise_skip",
                title=f"Skip {card.get('name') or 'surprise'}",
                command={"type": "resolve_surprise_card", "payload": {"accept": False}},
                base_score=35,
            )
        )
    return candidates


def _local_orchestrator_day_candidates(state: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = []
    current_node_id = str((state.get("poulpita") or {}).get("node_id") or "")
    shelter = (state.get("shelters") or {}).get(current_node_id)
    shelter_count = int(shelter.get("count") or 0) if isinstance(shelter, dict) else int(shelter or 0)
    shelter_shells = int(shelter.get("seashells") or 0) if isinstance(shelter, dict) else 0
    carried_shells = int((state.get("poulpita") or {}).get("seashells") or 0)
    if shelter_count and shelter_shells < 3 and carried_shells > 1:
        return [
            _local_orchestrator_candidate(
                state,
                plan_id="local_day_store_shell",
                title="Store a shell",
                command={"type": "move_seashell_to_shelter", "payload": {}},
                base_score=140,
            )
        ]
    cost, next_size = _poulpita_size_upgrade_cost(state)
    poulpita = state.get("poulpita") or {}
    min_energy = max(1, int(_bot_settings(state).get("min_energy_after_size_upgrade") or 4))
    if (
        cost is not None
        and next_size
        and not poulpita.get("size_upgraded_today")
        and int(poulpita.get("energy") or 0) - int(cost) >= min_energy
    ):
        candidates.append(
            _local_orchestrator_candidate(
                state,
                plan_id="local_day_grow",
                title="Grow Poulpita",
                command={"type": "buy_poulpita_size", "payload": {}},
                base_score=85,
                expected_gain=14,
            )
        )
    shared_neurons = int(poulpita.get("neurons") or 0)
    for ability_id in _playable_ability_ids(state):
        capability = _capability(state, ability_id)
        purchased = {int(index) for index in capability.get("purchased_hand_size_upgrade_indices") or []}
        for index, upgrade in enumerate(capability.get("hand_size_upgrades") or []):
            cost_neurons = max(0, int((upgrade or {}).get("cost") or 0))
            if (
                index in purchased
                or shared_neurons < cost_neurons
                or str((upgrade or {}).get("cost_resource") or "neurons") != "neurons"
            ):
                continue
            candidates.append(
                _local_orchestrator_candidate(
                    state,
                    plan_id=f"local_day_upgrade_{ability_id}_{index}",
                    title=f"Upgrade {capability.get('name') or ability_id}",
                    command={"type": "buy_hand_size_upgrade", "payload": {"capability_id": ability_id, "upgrade_index": index}},
                    base_score=80 + (15 if str((upgrade or {}).get("type") or "") == "deck_exchange" else 5),
                    expected_gain=10,
                )
            )
    candidates.append(
        _local_orchestrator_candidate(
            state,
            plan_id="local_day_end",
            title="Begin next night",
            command={"type": "end_day", "payload": {}},
            base_score=20,
        )
    )
    return candidates


def _local_orchestrator_interaction_candidates(state: dict[str, Any]) -> list[dict[str, Any]]:
    entry = _open_interaction_entry(state)
    if not entry:
        return []
    interaction = state.get("interaction") or {}
    tile = entry.get("tile") or {}
    active_id = str(state.get("active_capability_id") or "")
    initiator_id = str(interaction.get("initiator_capability_id") or "")
    if not interaction.get("initiator_confirmed", True):
        if initiator_id not in (state.get("capabilities") or {}):
            return []
        return [
            _local_orchestrator_candidate(
                state,
                plan_id=f"local_confirm_initiator_{initiator_id}",
                title=f"{_capability(state, initiator_id).get('name') or initiator_id} confirms cards",
                command={"type": "resolve_interaction", "payload": {"capability_id": initiator_id, "auto_select_cards": True, "confirm_only": True}},
                base_score=155,
            )
        ]

    missing = _missing_support_ids_for_open_interaction(state)
    shell_ready = int((state.get("poulpita") or {}).get("seashells") or 0) >= max(0, int(tile.get("shell_requirement_count") or 0))
    if shell_ready and not missing:
        resolver_id = active_id or initiator_id
        if resolver_id not in (state.get("capabilities") or {}):
            return []
        return [
            _local_orchestrator_candidate(
                state,
                plan_id=f"local_complete_interaction_{resolver_id}",
                title=f"Complete {_tile_display_name(state, tile)}",
                command={"type": "resolve_interaction", "payload": {"capability_id": resolver_id}},
                base_score=155,
            )
        ]

    direct_candidates = []
    if shell_ready:
        for ability_id in _all_capability_ids(state):
            capability = _capability(state, ability_id)
            selected_cards = _selected_cards_matching_requirements(capability, missing)
            if not selected_cards:
                continue
            estimate = _support_candidate_estimate(state, ability_id, missing, entry)
            direct_candidates.append(
                _local_orchestrator_candidate(
                    state,
                    plan_id=f"local_direct_support_{ability_id}",
                    title=f"{capability.get('name') or ability_id} plays support",
                    command={"type": "resolve_interaction", "payload": {"capability_id": ability_id, "card_ids": selected_cards, "confirm_only": True}},
                    base_score=145 + len(selected_cards) * 5,
                    confidence=float(estimate.get("probability") or 0.05),
                )
            )
    if direct_candidates:
        return direct_candidates

    existing_participants = {initiator_id} | {
        str(card.get("capability_id") or "")
        for card in interaction.get("played_cards") or []
    }
    existing_participants.discard("")
    search_candidates = []
    best_search_probability = 0.0
    active_capability = _capability(state, active_id)
    active_estimate = _support_candidate_estimate(state, active_id, missing, entry) if active_capability else {}
    active_commands, _entries, active_label = _next_interaction_support_command(state, active_id)
    if active_commands and int(active_estimate.get("known_future_matches") or 0) > 0:
        command = active_commands[0]
        command_type = str(command.get("type") or "")
        if command_type in {"draw_action_card", "collect_action_points"}:
            probability = float(active_estimate.get("probability") or 0.05)
            best_search_probability = max(best_search_probability, probability)
            search_candidates.append(
                _local_orchestrator_candidate(
                    state,
                    plan_id=f"local_continue_support_search_{active_id}_{command_type}",
                    title=f"{active_capability.get('name') or active_id}: {active_label}",
                    command=command,
                    base_score=145 if command_type == "draw_action_card" else 125,
                    confidence=probability,
                )
            )

    if not search_candidates and shell_ready:
        for ability_id in _all_capability_ids(state):
            if ability_id == active_id:
                continue
            capability = _capability(state, ability_id)
            estimate = _support_candidate_estimate(state, ability_id, missing, entry)
            if int(estimate.get("known_future_matches") or 0) <= 0 or not _has_control_take_left(capability):
                continue
            simulated = _clone_simulation_state(state)
            take_command = {"type": "take_control", "payload": {"capability_id": ability_id}}
            _simulate_public_command(simulated, take_command)
            support_commands, _entries, label = _next_interaction_support_command(simulated, ability_id)
            if not support_commands or str(support_commands[0].get("type") or "") not in {"draw_action_card", "collect_action_points"}:
                continue
            participant_count = len(existing_participants | {ability_id})
            participant_penalty = max(0, participant_count - 2) * _planner_weight(state, "third_ability_penalty", 45.0)
            probability = float(estimate.get("probability") or 0.05)
            best_search_probability = max(best_search_probability, probability)
            candidate = _local_orchestrator_candidate(
                state,
                plan_id=f"local_support_search_take_{ability_id}",
                title=f"{capability.get('name') or ability_id}: {label}",
                command=take_command,
                base_score=95 + probability * 25 - participant_penalty,
                confidence=probability,
            )
            candidate["statistics"]["interaction_team_size"] = participant_count
            candidate["statistics"]["initiative_change_penalty"] = participant_penalty
            search_candidates.append(candidate)

    failure_gain = _weighted_expected_gain(state, _effect_delta(tile.get("failure_effects") or []))
    fail_candidate = _local_orchestrator_candidate(
        state,
        plan_id=f"local_fail_{(entry.get('instance') or {}).get('instance_id')}",
        title=f"Fail {_tile_display_name(state, tile)}",
        command=_local_orchestrator_fail_command(state, entry),
        base_score=75 - best_search_probability * 35,
        confidence=1.0,
        expected_gain=failure_gain,
    )
    fail_candidate["statistics"]["failure_effect_score"] = failure_gain
    fail_candidate["statistics"]["best_support_search_probability"] = round(best_search_probability, 2)
    return [*search_candidates, fail_candidate]


def _local_orchestrator_night_candidates(state: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = []
    phase = str(state.get("phase") or "")
    active_id = str(state.get("active_capability_id") or "")
    current_node_id = str((state.get("poulpita") or {}).get("node_id") or "")
    compulsory = _compulsory_choices_on_node(state, current_node_id)
    shelter_return = _shelter_return_context(state, current_node_id)
    returning_to_shelter = bool(shelter_return["should_return"] and not compulsory)
    if phase == "night_idle":
        active_id = ""
    if not active_id:
        visible = _visible_current_tiles(state)
        visible_initiators = {
            ability_id
            for ability_id in _all_capability_ids(state)
            if _has_control_take_left(_capability(state, ability_id))
            and any(_can_initiate(state, ability_id, entry.get("tile") or {}) for entry in visible)
        }
        for ability_id in _all_capability_ids(state):
            capability = _capability(state, ability_id)
            if not _has_control_take_left(capability):
                continue
            if visible_initiators and ability_id not in visible_initiators and not returning_to_shelter:
                continue
            initiable_entries = [
                entry for entry in visible if _can_initiate(state, ability_id, entry.get("tile") or {})
            ]
            tile_bonus = max(
                (
                    _planner_weight(state, "tile_resolution", 14.0)
                    + (
                        _planner_weight(state, "compulsory_tile_resolution", 35.0)
                        if _tile_category(state, entry.get("tile") or {}).get("compulsory_on_same_node")
                        else 0.0
                    )
                    - _interaction_team_penalty(state, entry, ability_id)[1]
                    for entry in initiable_entries
                ),
                default=0.0,
            )
            return_bonus = 0.0
            if returning_to_shelter:
                move_cost = _action_cost(state, "move")
                return_bonus = float(shelter_return["urgency"])
                if _can_pay_action_cost(state, capability, move_cost):
                    return_bonus += 65
            candidates.append(
                _local_orchestrator_candidate(
                    state,
                    plan_id=f"local_take_{ability_id}",
                    title=f"{capability.get('name') or ability_id} takes control",
                    command={"type": "take_control", "payload": {"capability_id": ability_id}},
                    base_score=40 + min(10, int(capability.get("pa") or 0)) + tile_bonus + return_bonus,
                )
            )
        return candidates
    if state.get("interaction"):
        return _local_orchestrator_interaction_candidates(state)

    capability = _capability(state, active_id)
    action_slot = _action_slots_left(capability) > 0
    if _can_end_night_now(state):
        return [
            _local_orchestrator_candidate(
                state,
                plan_id="local_end_night",
                title="End night",
                command={"type": "end_night", "payload": {"capability_id": active_id}},
                base_score=140 + _night_lateness_score(state),
            )
        ]
    visible = _visible_current_tiles(state)
    visible_initiators = {
        ability_id
        for entry in visible
        for ability_id in _all_capability_ids(state)
        if _can_initiate(state, ability_id, entry.get("tile") or {})
    }
    highest_compulsory_priority = max((int(entry.get("priority") or 0) for entry in compulsory), default=None)
    active_can_initiate_compulsory = any(
        _can_initiate(state, active_id, entry.get("tile") or {})
        for entry in compulsory
    )
    interact_cost = _action_cost(state, "interact")
    active_interaction_candidate_count = 0
    if action_slot and _can_pay_action_cost(state, capability, interact_cost):
        for entry in visible:
            tile = entry.get("tile") or {}
            priority = int(tile.get("priority") or 0)
            is_compulsory = bool(_tile_category(state, tile).get("compulsory_on_same_node"))
            if returning_to_shelter and not is_compulsory:
                continue
            if highest_compulsory_priority is not None and not is_compulsory and priority <= highest_compulsory_priority:
                continue
            if highest_compulsory_priority is not None and is_compulsory and priority < highest_compulsory_priority:
                continue
            if not _can_initiate(state, active_id, tile):
                continue
            summary = _interaction_resolution_summary(state, entry, preferred_ability_id=active_id)
            expected_delta = summary.get("expected_delta") or {}
            tile_progress_gain = _planner_weight(state, "tile_resolution", 14.0)
            if is_compulsory:
                tile_progress_gain += _planner_weight(state, "compulsory_tile_resolution", 35.0)
            team_size, team_penalty = _interaction_team_penalty(state, entry, active_id)
            candidate = _local_orchestrator_candidate(
                state,
                plan_id=f"local_interact_{active_id}_{(entry.get('instance') or {}).get('instance_id')}",
                title=f"Interact {_tile_display_name(state, tile)}",
                command={
                    "type": "start_interaction",
                    "payload": {
                        "capability_id": active_id,
                        "tile_instance_id": (entry.get("instance") or {}).get("instance_id"),
                        "auto_select_cards": True,
                    },
                },
                base_score=(115 if is_compulsory else 55) + priority - team_penalty,
                confidence=float(summary.get("success_probability") or 0.05),
                expected_gain=_weighted_expected_gain(state, expected_delta) + tile_progress_gain,
            )
            candidate["statistics"]["interaction_team_size"] = team_size
            candidate["statistics"]["initiative_change_penalty"] = team_penalty
            candidates.append(candidate)
            active_interaction_candidate_count += 1

    active_can_address_compulsory = not compulsory or active_can_initiate_compulsory
    if action_slot and active_can_address_compulsory:
        collect_cost = _action_cost(state, "gain_ap")
        move_cost = _action_cost(state, "move")
        needs_shelter_ap = returning_to_shelter and not _can_pay_action_cost(state, capability, move_cost)
        if active_interaction_candidate_count == 0 and _can_pay_action_cost(state, capability, collect_cost) and (not returning_to_shelter or needs_shelter_ap):
            compulsory_ap_setup = bool(compulsory) and int(capability.get("pa") or 0) < interact_cost["ap_cost"]
            candidates.append(
                _local_orchestrator_candidate(
                    state,
                    plan_id=f"local_collect_{active_id}",
                    title=f"{capability.get('name') or active_id} collects AP",
                    command={"type": "collect_action_points", "payload": {"capability_id": active_id}},
                    base_score=(110 if compulsory_ap_setup else 30) + _expected_ap_roll(state) * 3 + (float(shelter_return["urgency"]) if needs_shelter_ap else 0),
                )
            )
        draw_cost = _action_cost(state, "draw")
        if (
            active_interaction_candidate_count == 0
            and not returning_to_shelter
            and _can_pay_action_cost(state, capability, draw_cost)
            and (capability.get("draw_pile") or capability.get("discard"))
        ):
            draw_payload = {"capability_id": active_id}
            if len(capability.get("hand") or []) >= int(capability.get("current_max_cards_in_hand") or 3):
                draw_payload["auto_discard_card"] = True
            candidates.append(
                _local_orchestrator_candidate(
                    state,
                    plan_id=f"local_draw_{active_id}",
                    title=f"{capability.get('name') or active_id} draws",
                    command={"type": "draw_action_card", "payload": draw_payload},
                    base_score=32,
                )
            )
        if (
            not compulsory
            and (not visible_initiators or returning_to_shelter)
            and active_interaction_candidate_count == 0
            and _can_pay_action_cost(state, capability, move_cost)
        ):
            target_nodes = (
                [shelter_return["next_node_id"]]
                if returning_to_shelter
                else ((state.get("map") or {}).get("adjacency") or {}).get(current_node_id, []) or []
            )
            for target_node_id in target_nodes:
                node_score, _entries, _distance = _node_followup_score(state, str(target_node_id), active_id)
                candidate = _local_orchestrator_candidate(
                    state,
                    plan_id=f"local_move_{active_id}_{target_node_id}",
                    title=f"Move to {target_node_id}",
                    command={"type": "move_poulpita", "payload": {"capability_id": active_id, "target_node_id": str(target_node_id)}},
                    base_score=38 + node_score + (90 + float(shelter_return["urgency"]) if returning_to_shelter else 0),
                )
                if returning_to_shelter:
                    candidate["statistics"]["safe_shelter_route"] = shelter_return["route"]
                    candidate["statistics"]["shelter_return_start"] = shelter_return["return_start"]
                candidates.append(
                    candidate
                )
    active_action_candidates = [
        candidate
        for candidate in candidates
        if str((_orchestrator_command(candidate) or {}).get("type") or "") != "take_control"
    ]
    if not active_action_candidates:
        available_visible_initiators = {
            ability_id
            for ability_id in visible_initiators
            if ability_id != active_id and _has_control_take_left(_capability(state, ability_id))
        }
        for ability_id in _all_capability_ids(state):
            if ability_id == active_id:
                continue
            next_capability = _capability(state, ability_id)
            if not _has_control_take_left(next_capability):
                continue
            if available_visible_initiators and ability_id not in available_visible_initiators:
                continue
            initiable_entries = [
                entry for entry in visible if _can_initiate(state, ability_id, entry.get("tile") or {})
            ]
            tile_bonus = max(
                (
                    _planner_weight(state, "tile_resolution", 14.0)
                    + (
                        _planner_weight(state, "compulsory_tile_resolution", 35.0)
                        if _tile_category(state, entry.get("tile") or {}).get("compulsory_on_same_node")
                        else 0.0
                    )
                    - _interaction_team_penalty(state, entry, ability_id)[1]
                    for entry in initiable_entries
                ),
                default=0.0,
            )
            return_bonus = 0.0
            if returning_to_shelter:
                return_bonus = float(shelter_return["urgency"])
                if _can_pay_action_cost(state, next_capability, _action_cost(state, "move")):
                    return_bonus += 65
            candidates.append(
                _local_orchestrator_candidate(
                    state,
                    plan_id=f"local_switch_{ability_id}",
                    title=f"{next_capability.get('name') or ability_id} takes control",
                    command={"type": "take_control", "payload": {"capability_id": ability_id}},
                    base_score=34 + min(8, int(next_capability.get("pa") or 0)) + tile_bonus + return_bonus,
                )
            )
    return candidates


def _local_orchestrator_candidates(state: dict[str, Any]) -> list[dict[str, Any]]:
    if state.get("pending_surprise"):
        candidates = _local_orchestrator_surprise_candidates(state)
    elif str(state.get("phase") or "") == "day":
        candidates = _local_orchestrator_day_candidates(state)
    elif str(state.get("phase") or "") in {"night_idle", "night_action"}:
        candidates = _local_orchestrator_night_candidates(state)
    else:
        candidates = []
    deduplicated: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        command = _orchestrator_command(candidate) or {}
        key = repr((command.get("type"), sorted((command.get("payload") or {}).items())))
        current = deduplicated.get(key)
        if current is None or _orchestrator_plan_score(candidate) > _orchestrator_plan_score(current):
            deduplicated[key] = candidate
    limit = _orchestrator_int_setting(state, "orchestrator_max_candidates", 8, minimum=2, maximum=20)
    return sorted(deduplicated.values(), key=_orchestrator_plan_score, reverse=True)[:limit]


def _orchestrator_unexpected_boundary(state: dict[str, Any], next_command: dict[str, Any] | None) -> str | None:
    next_type = str((next_command or {}).get("type") or "")
    if state.get("pending_surprise") and next_type != "resolve_surprise_card":
        return "surprise card requires a new decision"
    if state.get("interaction"):
        support_types = {
            "take_control",
            "collect_action_points",
            "draw_action_card",
            "resolve_interaction",
            "fail_interaction",
        }
        if next_type not in support_types:
            return "open interaction requires a support decision"
    elif next_type in {"resolve_interaction", "fail_interaction"}:
        return "planned interaction is no longer open"
    phase = str(state.get("phase") or "")
    if phase == "day" and next_type in {
        "take_control",
        "collect_action_points",
        "draw_action_card",
        "move_poulpita",
        "start_interaction",
        "resolve_interaction",
    }:
        return "night plan reached the day phase"
    if phase in {"night_idle", "night_action"} and next_type in {
        "buy_hand_size_upgrade",
        "buy_poulpita_size",
        "end_day",
        "move_seashell_to_shelter",
        "move_seashell_from_shelter",
    }:
        return "day plan reached the night phase"
    if next_type == "move_poulpita":
        current_node_id = str((state.get("poulpita") or {}).get("node_id") or "")
        if _compulsory_choices_on_node(state, current_node_id):
            return "new compulsory interaction blocks movement"
    return None


def _simulate_orchestrator_rollout(
    state: dict[str, Any],
    *,
    root_proposal: dict[str, Any],
    horizon: int,
    temperature: float,
    seed: str,
) -> dict[str, Any]:
    simulated = _clone_simulation_state(state)
    generator = random.Random(int(hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16], 16))
    selected = root_proposal
    command_queue = _orchestrator_commands(selected)
    controls_started = 0
    path_quality = _orchestrator_plan_quality(selected)
    path: list[dict[str, Any]] = []
    replans = 0
    unexpected_boundaries = 0
    stop_reason = "step limit reached"
    max_steps = max(8, min(64, horizon * 12))

    for _index in range(max_steps):
        if not command_queue:
            next_proposals = _local_orchestrator_candidates(simulated)
            if not next_proposals:
                stop_reason = "no local follow-up actions"
                break
            selected = _weighted_rollout_plan(next_proposals, generator=generator, temperature=temperature)
            if selected is None:
                stop_reason = "no executable follow-up plan"
                break
            command_queue = _orchestrator_commands(selected)
            path_quality += _orchestrator_plan_quality(selected)
            replans += 1

        command = command_queue[0]
        command_type = str(command.get("type") or "")
        if command_type == "take_control" and controls_started >= horizon:
            stop_reason = "initiative horizon reached"
            break
        command_queue.pop(0)

        path.append(
            {
                "plan_id": selected.get("plan_id"),
                "title": selected.get("title"),
                "command": deepcopy(command),
                "planner_score": round(_orchestrator_plan_score(selected), 2),
            }
        )
        _simulate_public_command(simulated, command)
        if command_type == "take_control":
            controls_started += 1

        if str(simulated.get("phase") or "") in {"game_over", "finished", "postgame"}:
            stop_reason = "game finished"
            break

        boundary_reason = _orchestrator_unexpected_boundary(
            simulated,
            command_queue[0] if command_queue else None,
        )
        if boundary_reason:
            command_queue = []
            unexpected_boundaries += 1
            stop_reason = boundary_reason
    else:
        stop_reason = "step limit reached"

    terminal_score = _global_state_score(simulated)
    return {
        "return": round(terminal_score + path_quality, 2),
        "terminal_global_score": terminal_score,
        "controls_started": controls_started,
        "steps": len(path),
        "replans": replans,
        "unexpected_boundaries": unexpected_boundaries,
        "stop_reason": stop_reason,
        "path": path,
    }


def choose_fast_bot_orchestrator_action(state: dict[str, Any]) -> dict[str, Any]:
    """Select the best immediate legal bot action without nested rollout simulation."""
    if state.get("mode") != "bots_only":
        return {
            "status": "disabled",
            "message": "The bot orchestrator is enabled only in bots-only rooms.",
            "command": None,
        }
    proposals = _local_orchestrator_candidates(state)
    if not proposals:
        return {
            "status": "idle",
            "message": "No executable local bot actions are available.",
            "command": None,
            "planner_debug": {"processor": "local_fast", "root_candidate_count": 0},
        }
    proposal = max(
        proposals,
        key=lambda candidate: (_orchestrator_plan_score(candidate), str(candidate.get("plan_id") or "")),
    )
    score = round(_orchestrator_plan_score(proposal), 2)
    return {
        "status": "selected",
        "message": f"Selected {proposal.get('title') or proposal.get('plan_id')}.",
        "plan_id": proposal.get("plan_id"),
        "plan_title": proposal.get("title"),
        "command": _orchestrator_command(proposal),
        "score": score,
        "expected_return": score,
        "settings": {"mode": "fast_immediate"},
        "evaluated_plans": [],
        "planner_debug": {
            "processor": "local_fast",
            "root_candidate_count": len(proposals),
            "rollout_count": 0,
        },
    }


def choose_bot_orchestrator_action(state: dict[str, Any]) -> dict[str, Any]:
    """Evaluate bounded, local bot rollouts and return one authoritative command."""
    if state.get("mode") != "bots_only":
        return {
            "status": "disabled",
            "message": "The bot orchestrator is enabled only in bots-only rooms.",
            "command": None,
        }
    root_proposals = _local_orchestrator_candidates(state)
    if not root_proposals:
        return {
            "status": "idle",
            "message": "No executable local bot actions are available.",
            "command": None,
            "planner_debug": {"processor": "local", "root_candidate_count": 0},
        }

    horizon = _orchestrator_int_setting(
        state,
        "orchestrator_rollout_take_controls",
        3,
        minimum=1,
        maximum=8,
    )
    rollout_count = _orchestrator_int_setting(
        state,
        "orchestrator_rollouts_per_plan",
        3,
        minimum=1,
        maximum=12,
    )
    temperature = _orchestrator_float_setting(
        state,
        "orchestrator_sampling_temperature",
        1.0,
        minimum=0.1,
        maximum=5.0,
    )
    version = int(state.get("version") or 0)
    room_id = str(state.get("room_id") or "")
    evaluated = []
    for root in root_proposals:
        rollouts = [
            _simulate_orchestrator_rollout(
                state,
                root_proposal=root,
                horizon=horizon,
                temperature=temperature,
                seed=f"{room_id}:{version}:{root.get('plan_id')}:{rollout_index}",
            )
            for rollout_index in range(rollout_count)
        ]
        mean_return = sum(float(rollout["return"]) for rollout in rollouts) / len(rollouts)
        evaluated.append(
            {
                "proposal": root,
                "mean_return": round(mean_return, 2),
                "minimum_return": min(float(rollout["return"]) for rollout in rollouts),
                "maximum_return": max(float(rollout["return"]) for rollout in rollouts),
                "rollouts": rollouts,
            }
        )

    best_return = max(float(entry["mean_return"]) for entry in evaluated)
    tied = [entry for entry in evaluated if best_return - float(entry["mean_return"]) <= 0.5]
    tied.sort(
        key=lambda entry: (
            float(entry["mean_return"]),
            _orchestrator_plan_score(entry["proposal"]),
            str(entry["proposal"].get("plan_id") or ""),
        ),
        reverse=True,
    )
    chosen = tied[0]
    proposal = chosen["proposal"]
    return {
        "status": "selected",
        "message": f"Selected {proposal.get('title') or proposal.get('plan_id')}.",
        "plan_id": proposal.get("plan_id"),
        "plan_title": proposal.get("title"),
        "command": _orchestrator_command(proposal),
        "expected_return": chosen["mean_return"],
        "settings": {
            "rollout_take_controls": horizon,
            "rollouts_per_plan": rollout_count,
            "sampling_temperature": temperature,
            "max_candidates": _orchestrator_int_setting(state, "orchestrator_max_candidates", 8, minimum=2, maximum=20),
        },
        "evaluated_plans": [
            {
                "plan_id": entry["proposal"].get("plan_id"),
                "title": entry["proposal"].get("title"),
                "mean_return": entry["mean_return"],
                "minimum_return": entry["minimum_return"],
                "maximum_return": entry["maximum_return"],
                "rollouts": entry["rollouts"],
            }
            for entry in evaluated
        ],
        "planner_debug": {
            "processor": "local",
            "root_candidate_count": len(root_proposals),
            "rollout_count": len(root_proposals) * rollout_count,
        },
    }


def public_bot_plan_status(status: dict[str, Any]) -> dict[str, Any]:
    public_status = dict(status)
    public_status["proposals"] = [
        {key: value for key, value in dict(proposal).items() if key not in {"commands", "_score", "_plan_group", "private_basis"}}
        for proposal in status.get("proposals") or []
    ]
    return public_status


def _pareto_axes(proposal: dict[str, Any]) -> dict[str, float]:
    axes = ((proposal.get("statistics") or {}).get("pareto_axes") or {})
    return {
        "efficiency": float(axes.get("efficiency") or 0),
        "confidence": float(axes.get("confidence") or 0),
        "expected_gain": float(axes.get("expected_gain") or 0),
    }


def _dominates(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_axes = _pareto_axes(left)
    right_axes = _pareto_axes(right)
    at_least_equal = all(left_axes[key] >= right_axes[key] - 0.0001 for key in left_axes)
    strictly_better = any(left_axes[key] > right_axes[key] + 0.0001 for key in left_axes)
    return at_least_equal and strictly_better


def _proposal_count_by_key(proposals: list[dict[str, Any]], key: str, fallback: str = "team") -> dict[str, int]:
    counts: dict[str, int] = {}
    for proposal in proposals:
        value = str(proposal.get(key) or fallback)
        counts[value] = counts.get(value, 0) + 1
    return counts


def _proposal_depth_buckets(proposals: list[dict[str, Any]]) -> dict[str, int]:
    buckets: dict[str, int] = {}
    for proposal in proposals:
        depth = len(proposal.get("plan_chain") or [])
        label = str(depth)
        buckets[label] = buckets.get(label, 0) + 1
    return buckets


def _proposal_debug_summary(proposal: dict[str, Any]) -> dict[str, Any]:
    statistics = proposal.get("statistics") or {}
    rollout_debug = statistics.get("rollout_debug") or {}
    chain = proposal.get("plan_chain") or []
    return {
        "plan_id": proposal.get("plan_id"),
        "proposer_ability_id": proposal.get("proposer_ability_id") or "team",
        "title": proposal.get("title"),
        "depth": len(chain),
        "last_step": (chain[-1] or {}).get("label") if chain else None,
        "rollout_stop_reason": rollout_debug.get("stop_reason"),
        "score": round(float(proposal.get("_score") or 0), 2),
        "pareto_axes": statistics.get("pareto_axes") or {},
    }


def _select_pareto_proposals(state: dict[str, Any], proposals: list[dict[str, Any]], *, limit: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    measured = [_attach_plan_metrics(state, proposal) for proposal in proposals]
    frontier = [
        proposal
        for index, proposal in enumerate(measured)
        if not any(other_index != index and _dominates(other, proposal) for other_index, other in enumerate(measured))
    ]
    per_proposer_limit = _max_plans_per_proposer(state)
    selected: list[dict[str, Any]] = []
    selected_ids = {proposal.get("plan_id") for proposal in selected}
    minimum_options = min(limit, max(5, min(len(measured), _planning_depth_take_controls(state) + 2)))
    proposer_counts: dict[str, int] = {}

    def try_select(proposal: dict[str, Any]) -> bool:
        proposal_id = proposal.get("plan_id")
        if proposal_id in selected_ids:
            return False
        proposer_id = str(proposal.get("proposer_ability_id") or "team")
        if proposer_counts.get(proposer_id, 0) >= per_proposer_limit:
            return False
        selected.append(proposal)
        selected_ids.add(proposal_id)
        proposer_counts[proposer_id] = proposer_counts.get(proposer_id, 0) + 1
        return True

    for proposal in sorted(frontier, key=lambda item: float(item.get("_score") or 0), reverse=True):
        try_select(proposal)
        if len(selected) >= limit:
            break
    if len(selected) < minimum_options:
        for proposal in sorted(measured, key=lambda item: float(item.get("_score") or 0), reverse=True):
            if proposal.get("plan_id") in selected_ids:
                continue
            try_select(proposal)
            if len(selected) >= minimum_options:
                break
    selected = selected[:limit]
    selected_plan_ids = {proposal.get("plan_id") for proposal in selected}
    debug = {
        "phase": state.get("phase"),
        "active_capability_id": state.get("active_capability_id"),
        "planning_depth_take_controls": _planning_depth_take_controls(state),
        "max_plans_per_proposer": _max_plans_per_proposer(state),
        "max_public_plans": limit,
        "generated_count": len(proposals),
        "measured_count": len(measured),
        "frontier_count": len(frontier),
        "selected_count": len(selected),
        "generated_by_proposer": _proposal_count_by_key(measured, "proposer_ability_id"),
        "selected_by_proposer": _proposal_count_by_key(selected, "proposer_ability_id"),
        "generated_depths": _proposal_depth_buckets(measured),
        "selected_depths": _proposal_depth_buckets(selected),
        "selected": [_proposal_debug_summary(proposal) for proposal in selected],
        "pruned": [_proposal_debug_summary(proposal) for proposal in measured if proposal.get("plan_id") not in selected_plan_ids][:12],
    }
    for proposal in selected:
        proposal.pop("_score", None)
        proposal.pop("_plan_group", None)
    return selected, debug
