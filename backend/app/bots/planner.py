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
        "_score": score,
    }


def _plan_chain(step_preview: list[str], commands: list[dict[str, Any]]) -> list[dict[str, Any]]:
    length = max(len(step_preview), len(commands))
    chain = []
    for index in range(length):
        command_type = str((commands[index] if index < len(commands) else {}).get("type") or "")
        label = step_preview[index] if index < len(step_preview) else command_type.replace("_", " ").title()
        chain.append(
            {
                "index": index,
                "label": label,
                "command_type": command_type or None,
                "auto_executable": bool(command_type),
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
        return True
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
        "planning_depth_take_controls": int(((state.get("bot_config") or {}).get("planning_depth_take_controls") or DEFAULT_PLANNING_TAKE_CONTROL_DEPTH)),
        "assumptions": assumptions or ["Surprise cards are modeled optimistically as no-op until one is actually drawn."],
    }


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
    commands = [{"type": "start_interaction", "payload": {"capability_id": ability_id, "tile_instance_id": entry["instance"].get("instance_id")}}]
    if _interaction_requirements(tile) == 0:
        commands.append({"type": "resolve_interaction", "payload": {"capability_id": ability_id}})
    return commands


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
        commands = [{"type": "resolve_surprise_card", "payload": payload}]
        proposals.append(
            _public_plan(
                plan_id=f"surprise_accept_{capability_id or 'free'}",
                proposer_ability_id=str(capability_id) if capability_id else None,
                title=f"Resolve surprise: {card.get('name') or 'Surprise'}",
                rationale="A surprise card is pending. This plan resolves it before returning to board planning.",
                risk_label="low" if not costs else "moderate",
                step_preview=[
                    "Acknowledge automatic effect" if not costs else f"{capability_name} pays the optional cost",
                    "Apply surprise effects",
                    "Recalculate board plans",
                ],
                expected_resources=_resource_estimate(),
                score=90 if not costs else 75,
                warnings=[] if not costs else ["Private card identities are hidden from the public proposal."],
                commands=commands,
                statistics=_plan_statistics(state, commands=commands, assumptions=["This proposal resolves the real drawn surprise card; no further hidden draw is assumed."]),
            )
        )
    if costs:
        commands = [{"type": "resolve_surprise_card", "payload": {"accept": False}}]
        proposals.append(
            _public_plan(
                plan_id="surprise_skip",
                proposer_ability_id=None,
                title=f"Do not pay: {card.get('name') or 'Surprise'}",
                rationale="Surprise costs are optional. The team can skip the cost and return to board planning.",
                risk_label="low",
                step_preview=["Decline the optional surprise cost", "Discard the pending surprise decision", "Recalculate board plans"],
                expected_resources=_resource_estimate(),
                score=40,
                commands=commands,
                statistics=_plan_statistics(state, commands=commands, assumptions=["Optional surprise costs can be declined with no reward."]),
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
    statistics = _plan_statistics(state, commands=commands, interactions=[entry])
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
        expected_resources=_resource_estimate(
            ap=interact_cost["ap_cost"] if has_ap else 0,
            time_steps=interact_cost["time_cost"] if has_ap else 0,
            control_takes={ability_id: 1} if include_take_control else {},
        ),
        score=score if has_ap else score - 20,
        warnings=[] if has_ap else ["This bot needs AP before starting the forced interaction."],
        commands=commands,
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
                    statistics=_plan_statistics(state, commands=commands, interactions=[entry]),
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
                warnings=["Private card identities are hidden from the public proposal."],
                statistics=_plan_statistics(state, commands=commands, interactions=[entry]),
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
    capability = simulated["capabilities"].setdefault(ability_id, {})
    expected_roll = _expected_ap_roll(state)
    capability["pa"] = int(capability.get("pa") or 0) + expected_roll
    capability["actions_taken_this_control"] = int(capability.get("actions_taken_this_control") or 0) + 1
    if include_take_control:
        capability["control_takes_this_night"] = int(capability.get("control_takes_this_night") or 0) + 1
    current_node_id = str((state.get("poulpita") or {}).get("node_id") or "")
    interact_cost = _action_cost(state, "interact")
    move_cost = _action_cost(state, "move")
    draw_cost = _action_cost(state, "special_power")
    followup_steps: list[str] = []
    followup_interactions: list[dict[str, Any]] = []
    followup_label = "future actions"
    score_bonus = 0

    if _action_slots_left(capability) <= 0:
        return {
            "steps": [f"Expected roll gives {expected_roll} AP, then control is exhausted"],
            "interactions": [],
            "label": "control setup",
            "score_bonus": 0,
        }

    current_compulsory = _compulsory_choices_on_node(simulated, current_node_id)
    if int(capability.get("pa") or 0) >= interact_cost["ap_cost"]:
        for entry in current_compulsory:
            if _can_initiate(simulated, ability_id, entry["tile"]):
                tile_name = _tile_display_name(simulated, entry["tile"])
                return {
                    "steps": [
                        f"Expected roll gives {expected_roll} AP",
                        f"Use expected AP to start forced {tile_name}",
                        "Resolve immediately if no support is missing; otherwise replan support",
                    ],
                    "interactions": [entry],
                    "label": f"forced {tile_name}",
                    "score_bonus": 35,
                }
    if not current_compulsory and int(capability.get("pa") or 0) >= interact_cost["ap_cost"]:
        for entry in _visible_current_tiles(simulated):
            if _can_initiate(simulated, ability_id, entry["tile"]):
                tile_name = _tile_display_name(simulated, entry["tile"])
                followup_steps = [
                    f"Expected roll gives {expected_roll} AP",
                    f"Use expected AP to start {tile_name}",
                    "Resolve immediately if no support is missing; otherwise replan support",
                ]
                followup_interactions = [entry]
                followup_label = tile_name
                score_bonus = 22
                break
    if not followup_steps and not current_compulsory and int(capability.get("pa") or 0) >= move_cost["ap_cost"]:
        adjacent = list(((state.get("map") or {}).get("adjacency") or {}).get(current_node_id) or [])
        if adjacent:
            target_node_id = str(adjacent[0])
            target_compulsory = _compulsory_choices_on_node(simulated, target_node_id, highest_only=False)
            followup_steps = [f"Expected roll gives {expected_roll} AP", f"Use expected AP to move to {target_node_id}"]
            if target_compulsory:
                followup_steps.append(f"Then account for {len(target_compulsory)} known compulsory tile{'s' if len(target_compulsory) != 1 else ''}")
            else:
                followup_steps.append("Reveal nearby tiles and replan")
            followup_interactions = target_compulsory
            followup_label = f"node {target_node_id}"
            score_bonus = 14 + len(target_compulsory) * 6
    if not followup_steps and not current_compulsory and int(capability.get("pa") or 0) >= draw_cost["ap_cost"]:
        hand_count = len(capability.get("hand") or [])
        hand_limit = int(capability.get("current_max_cards_in_hand") or 3)
        if hand_count < hand_limit and (capability.get("draw_pile") or capability.get("discard")):
            followup_steps = [f"Expected roll gives {expected_roll} AP", "Use expected AP to draw a card", "Replan with the new card"]
            followup_label = "card draw"
            score_bonus = 8
    if not followup_steps:
        followup_steps = [f"Expected roll gives {expected_roll} AP", "Recalculate with the real dice result"]
    return {
        "steps": followup_steps,
        "interactions": followup_interactions,
        "label": followup_label,
        "score_bonus": score_bonus,
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
    step_preview = ([f"{name} takes control"] if include_take_control else []) + ["Collect action points"] + followup["steps"][1:]
    expected_resources = _resource_estimate(
        ap=collect_cost["ap_cost"],
        time_steps=collect_cost["time_cost"],
        control_takes={ability_id: 1} if include_take_control else {},
    )
    expected_resources["expected_ap_gain_by_ability"] = {ability_id: _expected_ap_roll(state)}
    plan_chain = _plan_chain(step_preview, commands)
    for index in range(len(commands), len(plan_chain)):
        plan_chain[index]["auto_executable"] = False
        plan_chain[index]["decision_boundary"] = True
        plan_chain[index]["command_type"] = None
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
        statistics=_plan_statistics(
            state,
            commands=commands,
            interactions=followup.get("interactions") or [],
            assumptions=[
                f"Collect AP is simulated with expected roll {_expected_ap_roll(state)} for follow-up planning.",
                "Only the collect command is auto-executed; the real dice result triggers replanning before follow-up actions.",
                "Surprise cards are modeled optimistically as no-op until one is actually drawn.",
            ],
        ),
    )


def _night_idle_proposals(state: dict[str, Any]) -> list[dict[str, Any]]:
    proposals = []
    current_node_id = str((state.get("poulpita") or {}).get("node_id") or "")
    compulsory = _compulsory_choices_on_node(state, current_node_id)
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
            return sorted(proposals, key=lambda proposal: float(proposal.get("_score") or 0), reverse=True)[:3]
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
                statistics=_plan_statistics(state, commands=draw_commands),
            )
        )
    move_cost = _action_cost(state, "move")
    adjacent = list(((state.get("map") or {}).get("adjacency") or {}).get(current_node_id) or [])
    if not current_compulsory and adjacent and int(capability.get("pa") or 0) >= move_cost["ap_cost"]:
        for target_node_id in adjacent[:3]:
            target_compulsory = _compulsory_choices_on_node(state, str(target_node_id), highest_only=False)
            warnings = []
            steps = [f"Move Poulpita to {target_node_id}", "Reveal nearby tiles"]
            score = 24
            risk = "moderate"
            if target_compulsory:
                known_count = len(target_compulsory)
                initiable_count = sum(1 for entry in target_compulsory if _can_initiate(state, active_id, entry["tile"]))
                steps.append(f"Account for {known_count} known compulsory tile{'s' if known_count != 1 else ''} on arrival")
                warnings.append("Destination has known compulsory tiles; optional actions wait until those are handled.")
                if initiable_count < known_count:
                    warnings.append("This bot may need another ability to finish all compulsory interactions there.")
                score = 34
                risk = "forced"
            else:
                steps.append("Recalculate after movement")
            proposals.append(
                # Movement can reveal or expose forced tiles, so execute only the move and let the next plan handle them.
                _public_plan(
                    plan_id=f"move_inspect_{active_id}_{target_node_id}",
                    proposer_ability_id=active_id,
                    title=f"{name} moves to {target_node_id}" if target_compulsory else f"{name} inspects {target_node_id}",
                    rationale="A one-step move is legal. Known compulsory tiles on the destination are included before optional follow-up actions.",
                    risk_label=risk,
                    step_preview=steps,
                    expected_resources=_resource_estimate(ap=move_cost["ap_cost"], time_steps=move_cost["time_cost"]),
                    score=score,
                    warnings=warnings,
                    commands=[{"type": "move_poulpita", "payload": {"capability_id": active_id, "target_node_id": target_node_id}}],
                    statistics=_plan_statistics(
                        state,
                        commands=[{"type": "move_poulpita", "payload": {"capability_id": active_id, "target_node_id": target_node_id}}],
                        interactions=target_compulsory,
                    ),
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
            proposals.append(
                _public_plan(
                    plan_id=f"interact_{active_id}_{entry['instance'].get('instance_id')}",
                    proposer_ability_id=active_id,
                    title=f"Interact with {event.get('name') or tile.get('name') or 'tile'}",
                    rationale="This visible optional tile can be initiated by the active bot ability.",
                    risk_label="moderate",
                    step_preview=["Start interaction", "Resolve immediately" if required_count == 0 else "Pause if cards or shells are required"],
                    expected_resources=_resource_estimate(ap=interact_cost["ap_cost"], time_steps=interact_cost["time_cost"]),
                    score=26 - required_count,
                    warnings=[] if required_count == 0 else ["May require support cards."],
                    commands=commands,
                    statistics=_plan_statistics(state, commands=commands, interactions=[entry]),
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
    proposals = sorted(proposals, key=lambda proposal: float(proposal.pop("_score", 0)), reverse=True)[:5]
    return {
        "status": "awaiting_selection" if proposals else "idle",
        "proposal_set_id": f"plans_{state.get('room_id')}_{int(state.get('version') or 0)}",
        "generated_from_version": int(state.get("version") or 0),
        "proposals": proposals,
        "message": "" if proposals else "No bot proposals are available for the current state.",
    }


def public_bot_plan_status(status: dict[str, Any]) -> dict[str, Any]:
    public_status = dict(status)
    public_status["proposals"] = [
        {key: value for key, value in dict(proposal).items() if key not in {"commands", "_score", "private_basis"}}
        for proposal in status.get("proposals") or []
    ]
    return public_status
