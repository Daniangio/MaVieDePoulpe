from __future__ import annotations

from typing import Any


BOT_PLAYER_ABILITIES = {"agility", "camouflage", "force", "propulsion"}
BOT_PLAN_TERMINAL_COMMANDS = {"collect_action_points", "draw_action_card", "move_poulpita", "start_interaction", "resolve_interaction", "end_day"}
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
        "draw_action_card": {"capability_id"},
        "start_interaction": {"capability_id", "tile_instance_id", "auto_select_cards"},
        "resolve_interaction": {"capability_id", "auto_select_cards"},
        "fail_interaction": {"target_node_id"},
        "end_day": set(),
        "end_night": {"capability_id"},
        "move_seashell_to_shelter": set(),
        "move_seashell_from_shelter": set(),
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
        "gain_ap": {"ap_cost": 0, "time_cost": 0},
        "move": {"ap_cost": 1, "time_cost": 1},
        "interact": {"ap_cost": 1, "time_cost": 2},
        "special_power": {"ap_cost": 1, "time_cost": 0},
    }
    configured = (((state.get("tile_catalog") or {}).get("action_costs") or {}).get(action_id) or {})
    fallback = defaults.get(action_id) or {"ap_cost": 0, "time_cost": 0}
    return {
        "ap_cost": max(0, int(configured.get("ap_cost") if configured.get("ap_cost") is not None else fallback["ap_cost"])),
        "time_cost": max(0, int(configured.get("time_cost") if configured.get("time_cost") is not None else fallback["time_cost"])),
    }


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
    }


def _global_state_score(state: dict[str, Any]) -> float:
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
    }
    components = _global_state_score_components(state)
    score = 0.0
    for key, fallback in defaults.items():
        score += float(components.get(key) or 0) * _resource_weight(state, key, fallback)
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
        elif effect_type in {"remove_tile", "remove_preys"}:
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
        if ability_id == "intelligence":
            continue
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
    for node_id, entries in (state.get("tiles") or {}).items():
        for entry in entries or []:
            if entry.get("face_up"):
                tile = ((state.get("tile_catalog") or {}).get("tiles") or {}).get(entry.get("tile_id")) or {}
                if any(str(effect.get("type") or "") == "place_shelter_token" for effect in tile.get("success_effects") or []):
                    nodes.add(str(node_id))
    return nodes


def _distance_to_closest_shelter(state: dict[str, Any], start_node_id: str) -> int | None:
    shelter_nodes = _known_shelter_nodes(state)
    if not start_node_id or not shelter_nodes:
        return None
    if start_node_id in shelter_nodes:
        return 0
    adjacency = (state.get("map") or {}).get("adjacency") or {}
    frontier = [(start_node_id, 0)]
    visited = {start_node_id}
    while frontier:
        node_id, distance = frontier.pop(0)
        for next_node_id in adjacency.get(node_id, []) or []:
            next_node_id = str(next_node_id)
            if next_node_id in visited:
                continue
            if next_node_id in shelter_nodes:
                return distance + 1
            visited.add(next_node_id)
            frontier.append((next_node_id, distance + 1))
    return None


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
            estimated_time_steps += _action_cost(state, "special_power")["time_cost"]
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
    confidence = max(0.0, min(1.0, float(statistics.get("success_probability") if statistics.get("success_probability") is not None else proposal.get("confidence") if proposal.get("confidence") is not None else 1.0)))
    efficiency_score = float(efficiency["efficiency"])
    aggregate_score = round(
        _planner_weight(state, "efficiency", 35.0) * efficiency_score
        + _planner_weight(state, "confidence", 35.0) * confidence
        + _planner_weight(state, "expected_gain", 30.0) * ((expected_gain_score - base_global_score + expected_delta_score) / 20.0),
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
                "expected_gain": round(expected_gain_score - base_global_score + expected_delta_score, 2),
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


def _forced_actor_candidates(state: dict[str, Any]) -> list[tuple[str, bool]]:
    active_id = str(state.get("active_capability_id") or "")
    candidates: list[tuple[str, bool]] = []
    if active_id in (state.get("capabilities") or {}) and _action_slots_left(_capability(state, active_id)) > 0:
        candidates.append((active_id, False))
    for ability_id in _all_capability_ids(state):
        if ability_id == active_id:
            continue
        capability = _capability(state, ability_id)
        if ability_id == "intelligence":
            continue
        if _has_control_take_left(capability):
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
        commands.append({"type": "resolve_interaction", "payload": {"capability_id": ability_id, "auto_select_cards": True}})
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
    simulated = {**state}
    simulated["capabilities"] = {
        capability_id: dict(capability)
        for capability_id, capability in (state.get("capabilities") or {}).items()
    }
    simulated["poulpita"] = dict(state.get("poulpita") or {})
    simulated["tiles"] = {
        node_id: [dict(instance) for instance in entries or []]
        for node_id, entries in (state.get("tiles") or {}).items()
    }
    simulated["shelters"] = {
        node_id: dict(value) if isinstance(value, dict) else value
        for node_id, value in (state.get("shelters") or {}).items()
    }
    if state.get("interaction"):
        simulated["interaction"] = {
            **(state.get("interaction") or {}),
            "played_cards": [dict(card) for card in ((state.get("interaction") or {}).get("played_cards") or [])],
        }
    return simulated


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


def _current_shelter_secure_for_simulation(state: dict[str, Any]) -> bool:
    current_node_id = str((state.get("poulpita") or {}).get("node_id") or "")
    raw = (state.get("shelters") or {}).get(current_node_id)
    return bool(raw.get("secure")) if isinstance(raw, dict) else False


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
        capability["actions_taken_this_control"] = int(capability.get("actions_taken_this_control") or 0) + 1
        _simulate_advance_time(state, cost["time_cost"])
    elif command_type == "move_poulpita" and ability_id:
        cost = _action_cost(state, "move")
        capability["pa"] = max(0, int(capability.get("pa") or 0) - cost["ap_cost"])
        capability["actions_taken_this_control"] = int(capability.get("actions_taken_this_control") or 0) + 1
        _simulate_advance_time(state, cost["time_cost"])
        target_node_id = str(payload.get("target_node_id") or "")
        state.setdefault("poulpita", {})["previous_node_id"] = state.get("poulpita", {}).get("node_id")
        state["poulpita"]["node_id"] = target_node_id
    elif command_type == "draw_action_card" and ability_id:
        cost = _action_cost(state, "special_power")
        capability["pa"] = max(0, int(capability.get("pa") or 0) - cost["ap_cost"])
        capability["actions_taken_this_control"] = int(capability.get("actions_taken_this_control") or 0) + 1
        _simulate_advance_time(state, cost["time_cost"])
        missing = _missing_interaction_ids_for_open_interaction(state) if state.get("interaction") else []
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
        state["pending_surprise"] = None
    elif command_type == "start_interaction" and ability_id:
        cost = _action_cost(state, "interact")
        capability["pa"] = max(0, int(capability.get("pa") or 0) - cost["ap_cost"])
        capability["actions_taken_this_control"] = int(capability.get("actions_taken_this_control") or 0) + 1
        _simulate_advance_time(state, cost["time_cost"])
        entry = _simulated_tile_entry(state, str(payload.get("tile_instance_id") or ""))
        if entry:
            state["interaction"] = {
                "tile_instance_id": entry["instance"].get("instance_id"),
                "tile_id": entry["instance"].get("tile_id"),
                "node_id": entry.get("node_id"),
                "initiator_capability_id": ability_id,
                "played_cards": [],
            }
            if payload.get("auto_select_cards"):
                _simulate_play_cards_for_requirements(state, ability_id, list((entry.get("tile") or {}).get("interaction_ids") or []))
    elif command_type == "resolve_interaction":
        interaction = state.get("interaction") or {}
        entry = _simulated_tile_entry(state, str(interaction.get("tile_instance_id") or ""))
        if payload.get("auto_select_cards") and entry:
            _simulate_play_cards_for_requirements(state, ability_id, _missing_interaction_ids_for_open_interaction(state))
        if entry:
            _apply_success_effects_to_simulation(state, entry)
            node_id = str(entry.get("node_id") or "")
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
            capability.setdefault("purchased_hand_size_upgrade_indices", []).append(upgrade_index)
    elif command_type == "buy_poulpita_size":
        poulpita = state.setdefault("poulpita", {})
        sizes = ((state.get("tile_catalog") or {}).get("poulpita_panel") or {}).get("sizes") or []
        next_size_index = int(poulpita.get("size_index") or 0) + 1
        if next_size_index < len(sizes):
            base_cost = max(1, int((sizes[next_size_index] or {}).get("energy_cost") or 1))
            cost = max(0, base_cost - (1 if _current_shelter_secure_for_simulation(state) else 0))
            poulpita["energy"] = max(0, int(poulpita.get("energy") or 0) - cost)
            poulpita["size_index"] = next_size_index
            poulpita["size_upgraded_today"] = True
    elif command_type == "end_night":
        current_node_id = str((state.get("poulpita") or {}).get("node_id") or "")
        if not _state_has_shelter(state, current_node_id):
            state.setdefault("poulpita", {})["energy"] = max(0, int(state.get("poulpita", {}).get("energy") or 0) - 1)
        state["phase"] = "day"
        state["night_time_spent"] = 0
        state["active_capability_id"] = None
        for next_capability in (state.get("capabilities") or {}).values():
            next_capability["pa"] = 0
            next_capability["actions_taken_this_control"] = 0
            next_capability["control_takes_this_night"] = 0
        state.setdefault("poulpita", {})["size_upgraded_today"] = False
    elif command_type == "end_day":
        state["phase"] = "night_idle"
        state["night_time_spent"] = 0
        state["active_capability_id"] = None
        for next_capability in (state.get("capabilities") or {}).values():
            next_capability["pa"] = 0
            next_capability["actions_taken_this_control"] = 0
            next_capability["control_takes_this_night"] = 0
        state.setdefault("poulpita", {})["size_upgraded_today"] = False


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
    draw_cost = _action_cost(state, "special_power")
    collect_cost = _action_cost(state, "gain_ap")
    if _action_slots_left(capability) <= 0:
        return [], [], "control exhausted"
    if state.get("interaction"):
        return _next_interaction_support_command(state, ability_id)
    current_compulsory = _compulsory_choices_on_node(state, current_node_id)
    if int(capability.get("pa") or 0) >= interact_cost["ap_cost"]:
        forced_entry = _best_rollout_interaction(state, ability_id, current_compulsory)
        if forced_entry:
            return _interaction_rollout_commands(state, ability_id, forced_entry), [forced_entry], f"forced {_tile_display_name(state, forced_entry['tile'])}"
        optional_entry = _best_rollout_interaction(state, ability_id, _visible_current_tiles(state))
        if optional_entry:
            return _interaction_rollout_commands(state, ability_id, optional_entry), [optional_entry], _tile_display_name(state, optional_entry["tile"])
    elif current_compulsory and any(_can_initiate(state, ability_id, entry.get("tile") or {}) for entry in current_compulsory) and int(capability.get("pa") or 0) >= collect_cost["ap_cost"]:
        return [{"type": "collect_action_points", "payload": {"capability_id": ability_id}}], current_compulsory, "AP for forced interaction"
    if not current_compulsory and int(capability.get("pa") or 0) >= move_cost["ap_cost"]:
        adjacent = list(((state.get("map") or {}).get("adjacency") or {}).get(current_node_id) or [])
        if adjacent:
            scored_nodes = []
            for adjacent_node_id in adjacent:
                node_score, node_entries, shelter_distance = _node_followup_score(state, str(adjacent_node_id), ability_id)
                scored_nodes.append((node_score, str(adjacent_node_id), node_entries, shelter_distance))
            scored_nodes.sort(key=lambda item: item[0], reverse=True)
            _node_score, target_node_id, target_entries, _shelter_distance = scored_nodes[0]
            return [{"type": "move_poulpita", "payload": {"capability_id": ability_id, "target_node_id": target_node_id}}], target_entries, f"node {target_node_id}"
    if not current_compulsory and int(capability.get("pa") or 0) >= draw_cost["ap_cost"]:
        hand_count = len(capability.get("hand") or [])
        hand_limit = int(capability.get("current_max_cards_in_hand") or 3)
        if hand_count < hand_limit and (capability.get("draw_pile") or capability.get("discard")):
            return [{"type": "draw_action_card", "payload": {"capability_id": ability_id}}], [], "card draw"
    positive_action_costs = [cost["ap_cost"] for cost in [move_cost, interact_cost, draw_cost] if cost["ap_cost"] > 0]
    if not current_compulsory and positive_action_costs and int(capability.get("pa") or 0) < min(positive_action_costs) and int(capability.get("pa") or 0) >= collect_cost["ap_cost"]:
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


def _selected_cards_for_requirements(capability: dict[str, Any], required_interaction_ids: list[str]) -> list[str] | None:
    remaining = [str(interaction_id) for interaction_id in required_interaction_ids if interaction_id]
    selected: list[str] = []
    for card in capability.get("hand") or []:
        if not remaining:
            break
        match = next((interaction_id for interaction_id in remaining if interaction_id in _card_interaction_options(card)), None)
        if match:
            remaining.remove(match)
            selected.append(str(card.get("card_id")))
    return selected if not remaining else None


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


def _surprise_proposals(state: dict[str, Any]) -> list[dict[str, Any]]:
    card = ((state.get("pending_surprise") or {}).get("card") or {})
    if not card:
        return []
    costs = card.get("costs") or []
    proposals = []
    for payload in _surprise_accept_payloads(state, card):
        capability_id = payload.get("capability_id")
        capability_name = (_capability(state, str(capability_id)).get("name") if capability_id else "") or "Team"
        resolve_command = {"type": "resolve_surprise_card", "payload": payload}
        simulated_after_surprise = _clone_simulation_state(state)
        _simulate_public_command(simulated_after_surprise, resolve_command)
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
            assumptions=["Surprise effects are modeled optimistically for follow-up planning; every later step is rechecked by the authoritative reducer."],
        )
        proposals.append(
            _public_plan(
                plan_id=f"surprise_accept_{capability_id or 'free'}",
                proposer_ability_id=str(capability_id) if capability_id else None,
                title=f"Resolve surprise: {card.get('name') or 'Surprise'}",
                rationale="A surprise card is pending. The planner resolves it and then continues optimistically into the next public actions.",
                risk_label="low" if not costs else "moderate",
                step_preview=[
                    "Acknowledge automatic effect" if not costs else f"{capability_name} pays the optional cost",
                    "Apply surprise effects",
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
                statistics=_plan_statistics(
                    state,
                    commands=commands,
                    interactions=followup.get("interactions") or [],
                    assumptions=["Optional surprise costs can be declined. Follow-up steps are optimistic and rechecked before execution."],
                ),
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
    event = ((state.get("tile_catalog") or {}).get("events") or {}).get(tile.get("event_id")) or {}
    interact_cost = _action_cost(state, "interact")
    has_ap = int(capability.get("pa") or 0) >= interact_cost["ap_cost"]
    commands = []
    if include_take_control:
        commands.append({"type": "take_control", "payload": {"capability_id": ability_id}})
    if has_ap:
        commands.extend(_interaction_commands(ability_id, entry))
    else:
        commands.append({"type": "collect_action_points", "payload": {"capability_id": ability_id}})
    interaction_summary = _interaction_resolution_summary(state, entry, preferred_ability_id=ability_id)
    expected_delta = interaction_summary.get("expected_delta") or {}
    statistics = _plan_statistics(state, commands=commands, interactions=[entry])
    statistics["interaction_summaries"] = [interaction_summary]
    statistics["expected_resource_delta"] = expected_delta
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
        plan_id=f"{'take_control_' if include_take_control else ''}forced_{ability_id}_{entry['instance'].get('instance_id')}",
        proposer_ability_id=ability_id,
        title=f"{name} addresses forced {event.get('name') or tile.get('name') or 'tile'}",
        rationale="A compulsory tile is revealed on Poulpita's node, so movement is not proposed until a forced interaction is addressed.",
        risk_label="forced",
        step_preview=[
            f"{name} takes control" if include_take_control else "Use current initiative",
            "Start the compulsory interaction" if has_ap else "Collect AP first, then replan for the compulsory interaction",
            "Resolve immediately" if has_ap and _interaction_requirements(tile) == 0 else "Pause if cards or shells are required",
        ],
        expected_resources=expected_resources,
        score=(score if has_ap else score - 20) + _delta_score(expected_delta),
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


def _missing_interaction_ids_for_open_interaction(state: dict[str, Any]) -> list[str]:
    entry = _open_interaction_entry(state)
    if not entry:
        return []
    tile = entry["tile"]
    missing = []
    played = list(_played_interactions(state))
    for required_id in [str(interaction_id) for interaction_id in (tile.get("interaction_ids") or []) if interaction_id]:
        if required_id in played:
            played.remove(required_id)
        else:
            missing.append(required_id)
    return missing


def _interaction_support_score(state: dict[str, Any], ability_id: str) -> float:
    entry = _open_interaction_entry(state)
    if not entry:
        return 0.0
    missing = _missing_interaction_ids_for_open_interaction(state)
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


def _next_interaction_support_command(state: dict[str, Any], ability_id: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
    entry = _open_interaction_entry(state)
    if not entry:
        return [], [], "interaction pending"
    capability = _capability(state, ability_id)
    missing = _missing_interaction_ids_for_open_interaction(state)
    tile = entry.get("tile") or {}
    shell_ready = max(0, int((state.get("poulpita") or {}).get("seashells") or 0)) >= max(0, int(tile.get("shell_requirement_count") or 0))
    if shell_ready and (not missing or _selected_cards_for_requirements(capability, missing) is not None):
        return [{"type": "resolve_interaction", "payload": {"capability_id": ability_id, "auto_select_cards": True}}], [entry], f"complete {_tile_display_name(state, tile)}"
    draw_cost = _action_cost(state, "special_power")
    collect_cost = _action_cost(state, "gain_ap")
    hand_count = len(capability.get("hand") or [])
    hand_limit = int(capability.get("current_max_cards_in_hand") or 3)
    known_support_cards = (capability.get("draw_pile") or []) + (capability.get("discard") or [])
    if (
        missing
        and shell_ready
        and hand_count < hand_limit
        and _matched_requirement_count(known_support_cards, missing) > 0
    ):
        if int(capability.get("pa") or 0) >= draw_cost["ap_cost"]:
            return [{"type": "draw_action_card", "payload": {"capability_id": ability_id}}], [entry], f"draw for {_tile_display_name(state, tile)}"
        if int(capability.get("pa") or 0) >= collect_cost["ap_cost"]:
            return [{"type": "collect_action_points", "payload": {"capability_id": ability_id}}], [entry], f"AP for {_tile_display_name(state, tile)}"
    return [], [], "interaction pending"


def _interaction_support_proposals(state: dict[str, Any]) -> list[dict[str, Any]]:
    entry = _open_interaction_entry(state)
    if not entry:
        return []
    missing = _missing_interaction_ids_for_open_interaction(state)
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
        return proposals
    active_id = str(state.get("active_capability_id") or "")
    candidates: list[tuple[str, bool]] = []
    if active_id in (state.get("capabilities") or {}):
        candidates.append((active_id, False))
    for ability_id in _all_capability_ids(state):
        if ability_id == active_id or ability_id == "intelligence":
            continue
        if _has_control_take_left(_capability(state, ability_id)):
            candidates.append((ability_id, True))
    for ability_id, include_take_control in candidates:
        capability = _capability(state, ability_id)
        selected = _selected_cards_for_requirements(capability, missing)
        if selected is None:
            continue
        commands = []
        if include_take_control:
            commands.append({"type": "take_control", "payload": {"capability_id": ability_id}})
        commands.append({"type": "resolve_interaction", "payload": {"capability_id": ability_id, "card_ids": selected}})
        name = capability.get("name") or ability_id
        interaction_summary = _interaction_resolution_summary(state, entry, preferred_ability_id=ability_id)
        statistics = _plan_statistics(state, commands=commands, interactions=[entry])
        statistics["interaction_summaries"] = [interaction_summary]
        statistics["expected_resource_delta"] = interaction_summary.get("expected_delta") or {}
        proposals.append(
            _public_plan(
                plan_id=f"support_interaction_{ability_id}_{(entry['instance'] or {}).get('instance_id')}",
                proposer_ability_id=ability_id,
                title=f"{name} completes {title_name}",
                rationale="The interaction is already open. This ability can provide the missing cards and confirm the result.",
                risk_label="forced" if _tile_category(state, tile).get("compulsory_on_same_node") else "moderate",
                step_preview=[
                    f"{name} takes control" if include_take_control else "Use current initiative",
                    f"{name} plays the missing support cards",
                    "Confirm the interaction",
                    "Recalculate after any surprise draw",
                ],
                expected_resources=_resource_estimate(control_takes={ability_id: 1} if include_take_control else {}),
                score=110 if include_take_control else 120,
                commands=commands,
                plan_chain=_plan_chain(
                    ([f"{name} takes control"] if include_take_control else []) + [f"{name} plays support cards"],
                    commands,
                ),
                warnings=["Private card identities are hidden from the public proposal."],
                statistics=statistics,
            )
        )
    if not proposals:
        proposals.append(
            _public_plan(
                plan_id=f"open_interaction_needs_manual_resolution_{(entry['instance'] or {}).get('instance_id')}",
                proposer_ability_id=None,
                title=f"{title_name} needs manual support",
                rationale="The interaction is open, but no planner-controlled ability can cover all currently missing requirements.",
                risk_label="high",
                step_preview=["Inspect missing symbols", "Choose support manually, draw cards, or fail the interaction"],
                expected_resources=_resource_estimate(),
                score=55,
                warnings=["No executable support plan is available for the current hands."],
                statistics=_plan_statistics(state, interactions=[entry]),
            )
        )
    return proposals


def _optimistic_collect_followup(state: dict[str, Any], ability_id: str, *, include_take_control: bool) -> dict[str, Any]:
    simulated = {**state, "phase": "night_action", "active_capability_id": ability_id}
    simulated["capabilities"] = {
        capability_id: dict(capability)
        for capability_id, capability in (state.get("capabilities") or {}).items()
    }
    simulated["poulpita"] = dict(state.get("poulpita") or {})
    simulated["tiles"] = {
        node_id: [dict(instance) for instance in entries or []]
        for node_id, entries in (state.get("tiles") or {}).items()
    }
    simulated["shelters"] = {
        node_id: dict(value) if isinstance(value, dict) else value
        for node_id, value in (state.get("shelters") or {}).items()
    }
    capability = simulated["capabilities"].setdefault(ability_id, {})
    expected_roll = _expected_ap_roll(state)
    capability["pa"] = int(capability.get("pa") or 0) + expected_roll
    capability["actions_taken_this_control"] = int(capability.get("actions_taken_this_control") or 0) + 1
    if include_take_control:
        capability["control_takes_this_night"] = int(capability.get("control_takes_this_night") or 0) + 1
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


def _collect_plan(
    state: dict[str, Any],
    *,
    ability_id: str,
    include_take_control: bool,
    base_score: float,
    rationale: str,
) -> dict[str, Any]:
    capability = _capability(state, ability_id)
    name = capability.get("name") or ability_id
    collect_cost = _action_cost(state, "gain_ap")
    commands = []
    if include_take_control:
        commands.append({"type": "take_control", "payload": {"capability_id": ability_id}})
    commands.append({"type": "collect_action_points", "payload": {"capability_id": ability_id}})
    followup = _optimistic_collect_followup(state, ability_id, include_take_control=include_take_control)
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
    return _public_plan(
        plan_id=f"{'take_control_' if include_take_control else ''}collect_{ability_id}",
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
        plan_group=f"collect:{followup['label']}",
    )


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


def _night_idle_proposals(state: dict[str, Any]) -> list[dict[str, Any]]:
    proposals = []
    current_node_id = str((state.get("poulpita") or {}).get("node_id") or "")
    compulsory = _compulsory_choices_on_node(state, current_node_id)
    move_cost = _action_cost(state, "move")
    adjacent = list(((state.get("map") or {}).get("adjacency") or {}).get(current_node_id) or [])
    for ability_id in _controller_ids(state, "bot"):
        capability = _capability(state, ability_id)
        if not _has_control_take_left(capability):
            continue
        if compulsory:
            for entry in compulsory:
                if _can_initiate(state, ability_id, entry["tile"]):
                    proposals.append(_forced_interaction_plan(state, ability_id=ability_id, entry=entry, include_take_control=True, score=100))
                    break
            continue
        proposals.append(_collect_plan(state, ability_id=ability_id, include_take_control=True, base_score=35, rationale="This bot ability can legally take control and collect AP."))
        if int(capability.get("pa") or 0) >= move_cost["ap_cost"]:
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
    interact_cost = _action_cost(state, "interact")
    if current_compulsory and not state.get("interaction"):
        for ability_id, include_take_control in _forced_actor_candidates(state):
            for entry in current_compulsory:
                if _can_initiate(state, ability_id, entry["tile"]):
                    proposals.append(
                        _forced_interaction_plan(
                            state,
                            ability_id=ability_id,
                            entry=entry,
                            include_take_control=include_take_control,
                            score=105 if include_take_control else 115,
                        )
                    )
                    break
        if proposals:
            return proposals
        return [_forced_blocker_plan(state, current_compulsory)]
    active_id = _legal_active_actor(state)
    if not active_id:
        return proposals
    capability = _capability(state, active_id)
    name = capability.get("name") or active_id
    if current_compulsory and int(capability.get("pa") or 0) >= interact_cost["ap_cost"] and not state.get("interaction"):
        for entry in current_compulsory:
            if _can_initiate(state, active_id, entry["tile"]):
                proposals.append(_forced_interaction_plan(state, ability_id=active_id, entry=entry, include_take_control=False, score=100))
                break
    proposals.append(
        _collect_plan(
            state,
            ability_id=active_id,
            include_take_control=False,
            base_score=65 if current_compulsory else 30,
            rationale="Collecting AP is legal and may be needed for forced or future actions.",
        )
    )
    draw_cost = _action_cost(state, "special_power")
    hand_count = len(capability.get("hand") or [])
    hand_limit = int(capability.get("current_max_cards_in_hand") or 3)
    if (
        not current_compulsory
        and int(capability.get("pa") or 0) >= draw_cost["ap_cost"]
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
    if not current_compulsory and adjacent and int(capability.get("pa") or 0) >= move_cost["ap_cost"]:
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
    if not current_compulsory and int(capability.get("pa") or 0) >= interact_cost["ap_cost"] and not state.get("interaction"):
        for entry in _visible_current_tiles(state):
            tile = entry["tile"]
            if not _can_initiate(state, active_id, tile):
                continue
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
            proposals.append(
                _public_plan(
                    plan_id=f"interact_{active_id}_{entry['instance'].get('instance_id')}",
                    proposer_ability_id=active_id,
                    title=f"Interact with {event.get('name') or tile.get('name') or 'tile'}",
                    rationale="This visible optional tile can be initiated by the active bot ability.",
                    risk_label="moderate",
                    step_preview=["Start interaction", "Resolve immediately" if required_count == 0 else "Pause if cards or shells are required"],
                    expected_resources=expected_resources,
                    score=26 - required_count + _delta_score(expected_delta),
                    warnings=[] if required_count == 0 else ["May require support cards."],
                    commands=commands,
                    plan_chain=_plan_chain(["Start interaction", "Resolve interaction"] if required_count == 0 else ["Start interaction"], commands),
                    statistics=statistics,
                )
            )
    if not current_compulsory and not state.get("interaction"):
        for ability_id in _controller_ids(state, "bot"):
            if ability_id == active_id:
                continue
            bot_capability = _capability(state, ability_id)
            if not _has_control_take_left(bot_capability):
                continue
            proposals.append(
                _collect_plan(
                    state,
                    ability_id=ability_id,
                    include_take_control=True,
                    base_score=18,
                    rationale="This bot can take initiative as an alternative branch and collect AP for a deeper team plan.",
                )
            )
            if int(bot_capability.get("pa") or 0) >= move_cost["ap_cost"]:
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
                            target_node_id=str(target_node_id),
                            include_take_control=True,
                            base_score=18,
                            rationale="This bot can take initiative and move Poulpita as an alternative branch; later compulsory tiles are planned optimistically.",
                        )
                    )
    return proposals


def _day_proposals(state: dict[str, Any]) -> list[dict[str, Any]]:
    proposals = []
    current_node_id = str((state.get("poulpita") or {}).get("node_id") or "")
    raw_shelter = (state.get("shelters") or {}).get(current_node_id)
    shelter_count = int(raw_shelter.get("count") or 0) if isinstance(raw_shelter, dict) else int(raw_shelter or 0)
    shelter_shells = int(raw_shelter.get("seashells") or 0) if isinstance(raw_shelter, dict) else 0
    carried_shells = int((state.get("poulpita") or {}).get("seashells") or 0)
    if carried_shells > 0 and shelter_count > 0:
        shell_moves = max(1, min(carried_shells, max(1, 3 - shelter_shells)))
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
                score=45,
                objective_effect="Can progress secure-shelter objectives.",
                commands=commands,
                plan_chain=_plan_chain(["Move shell to shelter"] * len(commands), commands),
                statistics=_plan_statistics(state, commands=commands),
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
    if not bot_config or state.get("mode") != "solo_with_bots":
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
