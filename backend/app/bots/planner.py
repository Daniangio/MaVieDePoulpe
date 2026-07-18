from __future__ import annotations

from typing import Any


BOT_PLAYER_ABILITIES = {"agility", "camouflage", "force", "propulsion"}
BOT_PLAN_TERMINAL_COMMANDS = {"collect_action_points", "draw_action_card", "move_poulpita", "start_interaction", "resolve_interaction", "end_day"}


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
) -> dict[str, Any]:
    return {
        "plan_id": plan_id,
        "proposer_ability_id": proposer_ability_id,
        "title": title,
        "rationale": rationale,
        "risk_label": risk_label,
        "confidence": None,
        "step_preview": step_preview,
        "expected_resources": expected_resources,
        "objective_effect": objective_effect,
        "warnings": warnings or [],
        "commands": commands or [],
        "_score": score,
    }


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


def _has_control_take_left(capability: dict[str, Any]) -> bool:
    return int(capability.get("control_takes_this_night") or 0) < int(capability.get("max_control_takes_per_night") or 0)


def _action_slots_left(capability: dict[str, Any]) -> int:
    return int(capability.get("max_actions_per_control") or 0) - int(capability.get("actions_taken_this_control") or 0)


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


def _legal_active_bot(state: dict[str, Any]) -> str | None:
    active_id = str(state.get("active_capability_id") or "")
    if active_id not in _controller_ids(state, "bot"):
        return None
    return active_id if _action_slots_left(_capability(state, active_id)) > 0 else None


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
                commands=[{"type": "resolve_surprise_card", "payload": payload}],
            )
        )
    if costs:
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
                commands=[{"type": "resolve_surprise_card", "payload": {"accept": False}}],
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
        name = capability.get("name") or ability_id
        proposals.append(
            _public_plan(
                plan_id=f"take_control_collect_{ability_id}",
                proposer_ability_id=ability_id,
                title=f"{name} collects AP",
                rationale="This bot ability can legally take control and collect AP.",
                risk_label="low",
                step_preview=[f"{name} takes control", "Collect action points", "Recalculate after the die roll"],
                expected_resources=_resource_estimate(control_takes={ability_id: 1}),
                score=35,
                commands=[
                    {"type": "take_control", "payload": {"capability_id": ability_id}},
                    {"type": "collect_action_points", "payload": {"capability_id": ability_id}},
                ],
            )
        )
    return proposals


def _active_night_proposals(state: dict[str, Any]) -> list[dict[str, Any]]:
    proposals = []
    current_node_id = str((state.get("poulpita") or {}).get("node_id") or "")
    current_compulsory = _compulsory_choices_on_node(state, current_node_id)
    interact_cost = _action_cost(state, "interact")
    if current_compulsory and not state.get("interaction"):
        active_capability_id = str(state.get("active_capability_id") or "")
        for ability_id in _controller_ids(state, "bot"):
            capability = _capability(state, ability_id)
            if ability_id != active_capability_id and not _has_control_take_left(capability):
                continue
            for entry in current_compulsory:
                if _can_initiate(state, ability_id, entry["tile"]):
                    proposals.append(
                        _forced_interaction_plan(
                            state,
                            ability_id=ability_id,
                            entry=entry,
                            include_take_control=ability_id != active_capability_id,
                            score=105 if ability_id != active_capability_id else 110,
                        )
                    )
                    break
        if proposals:
            return proposals
    active_id = _legal_active_bot(state)
    if not active_id:
        return proposals
    capability = _capability(state, active_id)
    name = capability.get("name") or active_id
    if current_compulsory and int(capability.get("pa") or 0) >= interact_cost["ap_cost"] and not state.get("interaction"):
        for entry in current_compulsory:
            if _can_initiate(state, active_id, entry["tile"]):
                proposals.append(_forced_interaction_plan(state, ability_id=active_id, entry=entry, include_take_control=False, score=100))
                break
    collect_cost = _action_cost(state, "gain_ap")
    proposals.append(
        _public_plan(
            plan_id=f"collect_{active_id}",
            proposer_ability_id=active_id,
            title=f"{name} collects AP",
            rationale="Collecting AP is legal and may be needed for forced or future actions.",
            risk_label="low",
            step_preview=["Collect action points", "Recalculate after the die roll"],
            expected_resources=_resource_estimate(ap=collect_cost["ap_cost"], time_steps=collect_cost["time_cost"]),
            score=65 if current_compulsory else 30,
            commands=[{"type": "collect_action_points", "payload": {"capability_id": active_id}}],
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
                commands=[{"type": "draw_action_card", "payload": {"capability_id": active_id}}],
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
                )
            )
    if not current_compulsory and int(capability.get("pa") or 0) >= interact_cost["ap_cost"] and not state.get("interaction"):
        for entry in _visible_current_tiles(state):
            tile = entry["tile"]
            if not _can_initiate(state, active_id, tile):
                continue
            event = ((state.get("tile_catalog") or {}).get("events") or {}).get(tile.get("event_id")) or {}
            required_count = _interaction_requirements(tile)
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
                    commands=_interaction_commands(active_id, entry),
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
                commands=[{"type": "move_seashell_to_shelter", "payload": {}} for _ in range(shell_moves)],
            )
        )
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
            commands=[{"type": "end_day", "payload": {}}],
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
            proposals = _active_night_proposals(state)
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
