from __future__ import annotations

import asyncio
import json
import os
import random
import time
import uuid
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import WebSocket

from .bots.planner import (
    choose_bot_orchestrator_action,
    generate_bot_plan_status,
    has_executable_bot_orchestrator_action,
    public_bot_plan_status,
)
from .game_content_service import get_game_content_catalog, get_level_config, get_player_board_configs
from .map_service import get_map
from .server_models import User


ROOM_STATE_SETUP = "SETUP"
ROOM_STATE_IN_GAME = "IN_GAME"
ROOM_STATE_FINISHED = "FINISHED"
COMMAND_STREAM_KEY = "game:commands"
PHASE_SETUP = "setup"
PHASE_NIGHT_IDLE = "night_idle"
PHASE_NIGHT_ACTION = "night_action"
PHASE_DAY = "day"
PHASE_FINISHED = "game_over"
NIGHT_SHELTER_AVAILABLE_CHUNKS = 16
NIGHT_OVERRUN_CHUNKS = 24
DEFAULT_FOCUSED_CAPABILITY_ID = "agility"
DEFAULT_ACTIVE_CAPABILITY_ID = DEFAULT_FOCUSED_CAPABILITY_ID
CAPABILITY_ORDER = ["agility", "camouflage", "force", "propulsion", "intelligence"]
BOT_SEAT_CAPABILITY_IDS = ["agility", "camouflage", "force", "propulsion"]
CAPABILITY_NAMES = {
    "agility": "Agilite",
    "camouflage": "Camouflage",
    "force": "Force",
    "propulsion": "Propulsion",
    "intelligence": "Intelligence",
}
OCTOPUS_TOKEN_ID = "octopus"
OCTOPUS_TILE_ID = "__octopus_token__"
OCTOPUS_EVENT_ID = "__octopus_token_event__"
OCTOPUS_CATEGORY_ID = "__octopus_token_threat__"
COURTSHIP_TOKEN_ID = "courtship"
COURTSHIP_TILE_ID = "__courtship_token__"
COURTSHIP_EVENT_ID = "__courtship_token_event__"
COURTSHIP_CATEGORY_ID = "__courtship_token_category__"


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_str(name: str, default: str) -> str:
    return os.getenv(name, default).strip() or default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _history_key(user_id: str) -> str:
    return f"game:user:{user_id}:history"


def _room_key(room_id: str) -> str:
    return f"game:room:{room_id}"


def _state_key(room_id: str) -> str:
    return f"game:state:{room_id}"


def _result_key(room_id: str) -> str:
    return f"game:result:{room_id}"


def _command_result_key(command_id: str) -> str:
    return f"game:command_result:{command_id}"


def _projection_channel(room_id: str) -> str:
    return f"game:room:{room_id}:projection"


def _iso_to_epoch(value: Any) -> float:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return time.time()


def _public_room(room: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": room.get("id", ""),
        "owner_user_id": room.get("owner_user_id", ""),
        "mode": room.get("mode", "goldfish"),
        "game_type": room.get("game_type", "goldfish"),
        "state": room.get("state", ROOM_STATE_SETUP),
        "created_at": room.get("created_at", ""),
        "started_at": room.get("started_at") or "",
        "ended_at": room.get("ended_at") or None,
        "result_id": room.get("result_id") or None,
        "map_id": room.get("map_id") or "",
        "level_id": room.get("level_id") or "",
    }


def _bot_room_config(*, mode: str, human_ability_id: str | None = None) -> dict[str, Any] | None:
    normalized_mode = str(mode or "solo").strip() or "solo"
    if normalized_mode not in {"solo_with_bots", "bots_only"}:
        return None
    human_id = None
    if normalized_mode == "solo_with_bots":
        human_id = str(human_ability_id or "").strip() or DEFAULT_FOCUSED_CAPABILITY_ID
        if human_id not in BOT_SEAT_CAPABILITY_IDS:
            raise ValueError("human_ability_id must be one of agility, camouflage, force, or propulsion.")
    controllers = []
    for capability_id in BOT_SEAT_CAPABILITY_IDS:
        controller_type = "human" if human_id and capability_id == human_id else "bot"
        controllers.append(
            {
                "ability_id": capability_id,
                "controller_type": controller_type,
                "seat_id": "human" if controller_type == "human" else f"bot_{capability_id}",
            }
        )
    controllers.append({"ability_id": "intelligence", "controller_type": "shared", "seat_id": "shared_intelligence"})
    return {
        "mode": normalized_mode,
        "human_ability_id": human_id,
        "privacy_mode": "solo_faithful" if human_id else "all_bot",
        "controllers": controllers,
    }


def _apply_controller_metadata(capabilities: dict[str, dict[str, Any]], bot_config: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    controller_by_ability = {
        str(controller.get("ability_id")): controller
        for controller in (bot_config or {}).get("controllers", []) or []
        if controller.get("ability_id")
    }
    for capability_id, capability in capabilities.items():
        controller = controller_by_ability.get(capability_id)
        controller_type = str((controller or {}).get("controller_type") or "human")
        capability["controller_type"] = controller_type
        capability["controller_seat_id"] = (controller or {}).get("seat_id") or capability_id
        capability["is_human_controlled"] = controller_type == "human"
        capability["is_bot_controlled"] = controller_type == "bot"
        capability["is_shared_controlled"] = controller_type == "shared"
    return capabilities


def _validate_map_config(config: dict[str, Any]) -> None:
    nodes = config.get("nodes") or {}
    starting_node_id = str(config.get("starting_node_id") or "")
    if starting_node_id not in nodes:
        raise ValueError("Map starting_node_id must reference an existing node.")
    adjacency = config.get("adjacency") or {}
    for node_id, node in nodes.items():
        tier = int(node.get("tier") or 0)
        if tier < 1:
            raise ValueError(f"Map node {node_id} has an invalid tier.")
        for adjacent_id in adjacency.get(node_id) or []:
            if adjacent_id not in nodes:
                raise ValueError(f"Map node {node_id} references unknown adjacent node {adjacent_id}.")
            if node_id not in (adjacency.get(adjacent_id) or []):
                raise ValueError(f"Map adjacency must be symmetric between {node_id} and {adjacent_id}.")


def _map_projection(map_config: dict[str, Any]) -> dict[str, Any]:
    nodes = {}
    adjacency = {}
    for node_id, node in map_config["nodes"].items():
        nodes[node_id] = {
            "id": node_id,
            "tier": int(node["tier"]),
            "x": float(node.get("x") or 0),
            "y": float(node.get("y") or 0),
        }
        adjacency[node_id] = list((map_config.get("adjacency") or {}).get(node_id) or [])
    return {
        "id": map_config["id"],
        "name": map_config["name"],
        "nodes": nodes,
        "adjacency": adjacency,
        "image_url": map_config.get("image_url"),
        "image_width": map_config.get("image_width"),
        "image_height": map_config.get("image_height"),
    }


@dataclass
class CommandRejection(Exception):
    command_id: str
    reason: str
    message: str
    current_version: int

    def payload(self, projection: dict[str, Any] | None = None) -> dict[str, Any]:
        data: dict[str, Any] = {
            "ok": False,
            "status": "rejected",
            "command_id": self.command_id,
            "revision": self.current_version,
            "reason": self.reason,
            "message": self.message,
            "current_version": self.current_version,
        }
        if projection is not None:
            data["projection"] = projection
        return data


def _setup_state(room_id: str, *, level_id: str | None = None, mode: str = "goldfish", bot_config: dict[str, Any] | None = None) -> dict[str, Any]:
    level_config = get_level_config(level_id)
    map_config = get_map(level_config["map_id"])
    _validate_map_config(map_config)
    return {
        "room_id": room_id,
        "mode": mode,
        "bot_config": deepcopy(bot_config),
        "version": 0,
        "phase": PHASE_SETUP,
        "level_id": level_config["id"],
        "selected_level_id": level_config["id"],
        "day_index": 1,
        "night_time_spent": 0,
        "night_time_total": max(1, int(level_config.get("night_duration_steps") or NIGHT_OVERRUN_CHUNKS)),
        "selected_map_id": map_config["id"],
        "poulpita_starting_node_id": str(level_config.get("poulpita_starting_node_id") or map_config["starting_node_id"]),
        "active_capability_id": None,
        "last_active_capability_id": None,
        "focused_capability_id": str((bot_config or {}).get("human_ability_id") or DEFAULT_FOCUSED_CAPABILITY_ID),
        "map": _map_projection(map_config),
        "poulpita": {"node_id": None, "previous_node_id": None, "energy": 0, "neurons": 0, "seashells": 0, "size_index": 0, "size_upgraded_today": False},
        "capabilities": _apply_controller_metadata(_initial_capabilities(), bot_config),
        "tiles": {},
        "shelters": {},
        "objectives": deepcopy(level_config.get("objectives") or []),
        "objective_progress": {"size_increases": 0, "found_shelter": False, "secured_shelter": False},
        "tile_catalog": {},
        "interaction": None,
        "event_log": [],
    }


def _expand_deck(deck_config: list[dict[str, Any]], capability_id: str) -> list[dict[str, Any]]:
    cards = []
    for entry in deck_config or []:
        interaction_ids = [str(interaction_id) for interaction_id in (entry.get("interaction_ids") or []) if interaction_id]
        interaction_id = str(entry.get("interaction_id") or (interaction_ids[0] if interaction_ids else ""))
        if not interaction_ids and interaction_id:
            interaction_ids = [interaction_id]
        for _index in range(max(0, int(entry.get("count") or 0))):
            card = {
                "card_id": f"card_{uuid.uuid4().hex}",
                "interaction_id": interaction_id,
                "interaction_ids": interaction_ids,
                "owner_capability_id": capability_id,
            }
            if entry.get("upgraded"):
                card["upgraded"] = True
            cards.append(card)
    random.shuffle(cards)
    return cards


def _refill_draw_pile_from_discard(capability: dict[str, Any]) -> bool:
    discard = capability.get("discard") or []
    if capability.get("draw_pile") or not discard:
        return False
    capability["draw_pile"] = deepcopy(discard)
    capability["discard"] = []
    random.shuffle(capability["draw_pile"])
    return True


def _reshuffle_and_deal_starting_hand(capability: dict[str, Any]) -> None:
    cards = _expand_deck(capability.get("deck") or [], str(capability.get("id") or ""))
    hand_limit = max(0, int(capability.get("current_max_cards_in_hand") or capability.get("default_max_cards_in_hand") or 3))
    capability["hand"] = cards[:hand_limit]
    capability["draw_pile"] = cards[hand_limit:]
    capability["discard"] = []


def _apply_deck_exchange_upgrade(capability: dict[str, Any], upgrade: dict[str, Any]) -> None:
    deck = deepcopy(capability.get("deck") or [])
    for entry in upgrade.get("remove_cards") or []:
        interaction_id = str(entry.get("interaction_id") or "")
        remaining = max(0, int(entry.get("count") or 0))
        for deck_entry in deck:
            options = [str(value) for value in (deck_entry.get("interaction_ids") or []) if value]
            primary = str(deck_entry.get("interaction_id") or "")
            if not options and primary:
                options = [primary]
            if interaction_id not in options:
                continue
            available = max(0, int(deck_entry.get("count") or 0))
            removed = min(available, remaining)
            deck_entry["count"] = available - removed
            remaining -= removed
            if remaining == 0:
                break
        if remaining:
            raise ValueError(f"Not enough {interaction_id} cards remain to exchange.")

    deck = [entry for entry in deck if int(entry.get("count") or 0) > 0]
    for entry in upgrade.get("add_cards") or []:
        interaction_ids = [str(interaction_id) for interaction_id in (entry.get("interaction_ids") or []) if interaction_id]
        if not interaction_ids:
            continue
        deck.append(
            {
                "interaction_id": interaction_ids[0],
                "interaction_ids": interaction_ids,
                "count": max(0, int(entry.get("count") or 0)),
                "upgraded": True,
            }
        )
    capability["deck"] = deck


def _apply_unmigrated_deck_exchange_upgrades(capability: dict[str, Any]) -> None:
    applied = {int(index) for index in (capability.get("applied_deck_exchange_upgrade_indices") or [])}
    purchased = {int(index) for index in (capability.get("purchased_hand_size_upgrade_indices") or [])}
    upgrades = capability.get("hand_size_upgrades") or []
    for upgrade_index in sorted(purchased - applied):
        if upgrade_index < 0 or upgrade_index >= len(upgrades):
            continue
        upgrade = upgrades[upgrade_index] or {}
        if str(upgrade.get("type") or "hand_size") != "deck_exchange":
            continue
        _apply_deck_exchange_upgrade(capability, upgrade)
        capability.setdefault("applied_deck_exchange_upgrade_indices", []).append(upgrade_index)


def _initial_capabilities(*, deal_hands: bool = False) -> dict[str, dict[str, Any]]:
    board_configs = {board["id"]: board for board in get_player_board_configs()}
    capabilities = {}
    for capability_id in CAPABILITY_ORDER:
        board = board_configs.get(capability_id, {})
        draw_pile = _expand_deck(board.get("deck") or [], capability_id)
        hand_limit = int(board.get("default_max_cards_in_hand") or 3)
        hand = draw_pile[:hand_limit] if deal_hands else []
        capabilities[capability_id] = {
            "id": capability_id,
            "name": board.get("name") or CAPABILITY_NAMES[capability_id],
            "pa": max(0, int(board.get("initial_ap") if board.get("initial_ap") is not None else 5)),
            "control_takes_this_night": 0,
            "actions_taken_this_control": 0,
            "max_actions_per_control": int(board.get("actions_per_control") or 3),
            "max_control_takes_per_night": int(board.get("control_takes_per_night") or 3),
            "default_max_cards_in_hand": int(board.get("default_max_cards_in_hand") or 3),
            "current_max_cards_in_hand": int(board.get("default_max_cards_in_hand") or 3),
            "initiates_event_ids": list(board.get("initiates_event_ids") or []),
            "deck": deepcopy(board.get("deck") or []),
            "draw_pile": draw_pile[hand_limit:] if deal_hands else draw_pile,
            "hand": hand,
            "discard": [],
            "hand_size_upgrades": deepcopy(board.get("hand_size_upgrades") or []),
            "purchased_hand_size_upgrade_indices": [],
            "initial_ap": max(0, int(board.get("initial_ap") if board.get("initial_ap") is not None else 5)),
        }
    return capabilities


def _tile_public(tile: dict[str, Any], catalog: dict[str, dict[str, Any]]) -> dict[str, Any]:
    event = catalog["events"].get(tile.get("event_id")) or {}
    return {
        **tile,
        "event": event,
        "image_url": event.get("image_url"),
    }


def _octopus_public_tile(octopus_token: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    octopus_event = {
        "id": OCTOPUS_EVENT_ID,
        "name": octopus_token.get("name") or "Octopus token",
        "category_id": OCTOPUS_CATEGORY_ID,
        "image_url": octopus_token.get("image_url"),
    }
    octopus_category = {
        "id": OCTOPUS_CATEGORY_ID,
        "name": "Threat",
        "compulsory_on_same_node": True,
    }
    octopus_tile = {
        "id": OCTOPUS_TILE_ID,
        "name": octopus_token.get("name") or "Octopus token",
        "event_id": OCTOPUS_EVENT_ID,
        "event": octopus_event,
        "image_url": octopus_token.get("image_url"),
        "priority": int(octopus_token.get("priority") or 0),
        "initiator_capability_ids": list(octopus_token.get("initiator_capability_ids") or []),
        "interaction_ids": list(octopus_token.get("interaction_ids") or []),
        "counter_attack_interaction_ids": list(octopus_token.get("counter_attack_interaction_ids") or []),
        "shell_requirement_count": int(octopus_token.get("shell_requirement_count") or 0),
        "success_effects": deepcopy(octopus_token.get("success_effects") or []),
        "counter_attack_effects": deepcopy(octopus_token.get("counter_attack_effects") or []),
        "failure_effects": deepcopy(octopus_token.get("failure_effects") or []),
        "token_type": OCTOPUS_TOKEN_ID,
    }
    return octopus_tile, octopus_event, octopus_category


def _ensure_octopus_tile_catalog(tile_catalog: dict[str, Any]) -> dict[str, Any]:
    token_catalog = tile_catalog.get("tokens") or {}
    octopus_token = token_catalog.get(OCTOPUS_TOKEN_ID) or {}
    if not octopus_token:
        latest_catalog = get_game_content_catalog()
        token_catalog = latest_catalog.get("tokens") or {}
        octopus_token = token_catalog.get(OCTOPUS_TOKEN_ID) or {}
        if token_catalog:
            tile_catalog["tokens"] = token_catalog
    if octopus_token:
        octopus_tile, octopus_event, octopus_category = _octopus_public_tile(octopus_token)
        tile_catalog.setdefault("tiles", {})[OCTOPUS_TILE_ID] = octopus_tile
        tile_catalog.setdefault("events", {})[OCTOPUS_EVENT_ID] = octopus_event
        tile_catalog.setdefault("categories", {})[OCTOPUS_CATEGORY_ID] = octopus_category
    return tile_catalog


def _is_octopus_tile_instance(tile_instance: dict[str, Any]) -> bool:
    return (
        str(tile_instance.get("token_type") or "") == OCTOPUS_TOKEN_ID
        or str(tile_instance.get("tile_id") or "") in {OCTOPUS_TILE_ID, OCTOPUS_TOKEN_ID}
    )


def _build_tile_catalog() -> dict[str, Any]:
    catalog = get_game_content_catalog()
    public_tiles = {}
    for tile_id, tile in catalog["tiles"].items():
        public_tiles[tile_id] = _tile_public(tile, catalog)
    token_catalog = catalog.get("tokens") or {}
    octopus_token = token_catalog.get(OCTOPUS_TOKEN_ID) or {}
    if octopus_token:
        octopus_tile, octopus_event, octopus_category = _octopus_public_tile(octopus_token)
        catalog.setdefault("events", {})[OCTOPUS_EVENT_ID] = octopus_event
        catalog.setdefault("categories", {})[OCTOPUS_CATEGORY_ID] = octopus_category
        public_tiles[OCTOPUS_TILE_ID] = octopus_tile
    courtship_token = token_catalog.get(COURTSHIP_TOKEN_ID) or {}
    if courtship_token:
        courtship_event = {
            "id": COURTSHIP_EVENT_ID,
            "name": courtship_token.get("name") or "Courtship token",
            "category_id": COURTSHIP_CATEGORY_ID,
            "image_url": courtship_token.get("image_url"),
        }
        catalog.setdefault("events", {})[COURTSHIP_EVENT_ID] = courtship_event
        catalog.setdefault("categories", {})[COURTSHIP_CATEGORY_ID] = {
            "id": COURTSHIP_CATEGORY_ID,
            "name": "Courtship",
            "compulsory_on_same_node": False,
        }
        public_tiles[COURTSHIP_TILE_ID] = {
            "id": COURTSHIP_TILE_ID,
            "name": courtship_event["name"],
            "event_id": COURTSHIP_EVENT_ID,
            "event": courtship_event,
            "image_url": courtship_event["image_url"],
            "interaction_ids": [],
            "counter_attack_interaction_ids": [],
            "success_effects": [],
            "failure_effects": [],
            "token_type": COURTSHIP_TOKEN_ID,
        }
    cards = catalog.get("cards") or {}
    if isinstance(cards, list):
        cards = {card["id"]: card for card in cards if card.get("id")}
    return {
        "tiles": public_tiles,
        "categories": catalog.get("categories") or {},
        "events": catalog["events"],
        "interactions": catalog["interactions"],
        "cards": cards,
        "surprise_cards": catalog.get("surprise_cards") or {},
        "surprise_decks": catalog.get("surprise_decks") or {},
        "courtship_cards": catalog.get("courtship_cards") or {},
        "card_categories": catalog.get("card_categories") or [],
        "tokens": token_catalog,
        "poulpita_panel": catalog.get("poulpita_panel") or {},
        "action_costs": catalog.get("action_costs") or {},
        "bot_settings": catalog.get("bot_settings") or {},
    }


def _level_tiles(
    level_config: dict[str, Any],
    catalog: dict[str, Any],
    *,
    groups: list[dict[str, Any]] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    node_tiles = {node_id: [] for node_id in level_config.get("node_tile_counts") or {}}
    for group in (groups if groups is not None else level_config.get("groups") or []):
        expanded = []
        for tile_id, count in (group.get("tile_counts") or {}).items():
            for _index in range(max(0, int(count or 0))):
                tile = catalog["tiles"].get(tile_id)
                if tile:
                    is_courtship = str(tile_id) == COURTSHIP_TILE_ID
                    expanded.append(
                        {
                            "instance_id": f"courtship_{uuid.uuid4().hex}" if is_courtship else f"tile_{uuid.uuid4().hex}",
                            "tile_id": tile_id,
                            "face_up": is_courtship,
                            **({"token_type": COURTSHIP_TOKEN_ID} if is_courtship else {}),
                        }
                    )
        random.shuffle(expanded)
        group_node_ids = [node_id for node_id, group_id in (level_config.get("node_group_ids") or {}).items() if group_id == group["id"]]
        for node_id in group_node_ids:
            count = int((level_config.get("node_tile_counts") or {}).get(node_id) or 0)
            node_tiles.setdefault(node_id, []).extend(expanded[:count])
            expanded = expanded[count:]
    for node_id, tokens in (level_config.get("node_tokens") or {}).items():
        for token in tokens or []:
            if str(token.get("type") if isinstance(token, dict) else token) == OCTOPUS_TOKEN_ID:
                _ensure_octopus_tile_catalog(catalog)
                node_tiles.setdefault(str(node_id), []).append(
                    {
                        "instance_id": f"octopus_{node_id}_{uuid.uuid4().hex}",
                        "tile_id": OCTOPUS_TILE_ID,
                        "face_up": True,
                        "token_type": OCTOPUS_TOKEN_ID,
                    }
                )
            elif str(token.get("type") if isinstance(token, dict) else token) == COURTSHIP_TOKEN_ID:
                node_tiles.setdefault(str(node_id), []).append(
                    {
                        "instance_id": f"courtship_{node_id}_{uuid.uuid4().hex}",
                        "tile_id": COURTSHIP_TILE_ID,
                        "face_up": True,
                        "token_type": COURTSHIP_TOKEN_ID,
                    }
                )
    return node_tiles


def _replace_tiles_for_size(next_state: dict[str, Any], size_index: int) -> bool:
    tile_sets = list(next_state.get("level_tile_sets") or [])
    eligible = [entry for entry in tile_sets if int(entry.get("size_index") or 0) <= size_index]
    if not eligible:
        return False
    selected = max(eligible, key=lambda entry: int(entry.get("size_index") or 0))
    selected_id = str(selected.get("id") or selected.get("size_index") or "")
    if selected_id == str(next_state.get("active_tile_set_id") or ""):
        return False
    level_layout = next_state.get("level_layout") or {}
    replacement = _level_tiles(level_layout, next_state.get("tile_catalog") or {}, groups=selected.get("groups") or [])
    next_state["tiles"] = replacement
    next_state["active_tile_set_id"] = selected_id
    _apply_tile_visibility(next_state)
    return True


def _level_shelters(level_config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    shelters: dict[str, dict[str, Any]] = {}
    for node_id, tokens in (level_config.get("node_tokens") or {}).items():
        count = sum(1 for token in tokens or [] if str(token.get("type") if isinstance(token, dict) else token) == "shelter")
        if count:
            shelters[str(node_id)] = {"count": count, "seashells": 0, "secure": False}
    return shelters


def _apply_tile_visibility(state: dict[str, Any]) -> None:
    current_node_id = state.get("poulpita", {}).get("node_id")
    if not current_node_id:
        return
    adjacency = (state.get("map") or {}).get("adjacency") or {}
    reveal_limits = {str(current_node_id): None}
    for adjacent_node_id in adjacency.get(current_node_id, []) or []:
        reveal_limits[str(adjacent_node_id)] = 2
    visited = {str(current_node_id), *[str(node_id) for node_id in adjacency.get(current_node_id, []) or []]}
    for adjacent_node_id in adjacency.get(current_node_id, []) or []:
        for step_two_node_id in adjacency.get(adjacent_node_id, []) or []:
            step_two_node_id = str(step_two_node_id)
            if step_two_node_id not in visited:
                reveal_limits[step_two_node_id] = max(1, reveal_limits.get(step_two_node_id) or 0)
    for node_id, reveal_limit in reveal_limits.items():
        if reveal_limit is None:
            for tile_instance in (state.get("tiles") or {}).get(node_id, []) or []:
                tile_instance["face_up"] = True
            continue
        revealed = 0
        for tile_instance in (state.get("tiles") or {}).get(node_id, []) or []:
            if tile_instance.get("face_up"):
                revealed += 1
                continue
            if revealed < reveal_limit:
                tile_instance["face_up"] = True
                revealed += 1


def _goldfish_state(room_id: str, *, level_id: str | None = None, mode: str = "goldfish", bot_config: dict[str, Any] | None = None) -> dict[str, Any]:
    level_config = get_level_config(level_id)
    map_config = get_map(level_config["map_id"])
    _validate_map_config(map_config)
    tile_catalog = _build_tile_catalog()
    max_energy = max(1, min(32, int(level_config.get("max_energy") or 32)))
    starting_energy = max(0, min(max_energy, int(level_config.get("starting_energy") if level_config.get("starting_energy") is not None else 8)))
    starting_neurons = max(0, int(level_config.get("starting_neurons") or 0))
    surprise_deck_id = str(level_config.get("surprise_deck_id") or "")
    surprise_draw_pile = list(((tile_catalog.get("surprise_decks") or {}).get(surprise_deck_id) or {}).get("card_ids") or [])
    random.shuffle(surprise_draw_pile)
    state = {
        "room_id": room_id,
        "mode": mode,
        "bot_config": deepcopy(bot_config),
        "version": 1,
        "phase": PHASE_NIGHT_IDLE,
        "level_id": level_config["id"],
        "selected_level_id": level_config["id"],
        "day_index": 1,
        "night_time_spent": 0,
        "night_time_total": max(1, int(level_config.get("night_duration_steps") or NIGHT_OVERRUN_CHUNKS)),
        "max_nights": max(1, int(level_config.get("max_nights") or 5)),
        "counter_attack_min_size_index": max(1, int(level_config.get("counter_attack_min_size_index") or 1)),
        "courtship_min_size_index": max(0, int(level_config.get("courtship_min_size_index") if level_config.get("courtship_min_size_index") is not None else 3)),
        "courtship_min_energy": max(1, int(level_config.get("courtship_min_energy") or 8)),
        "win_min_energy": max(1, int(level_config.get("win_min_energy") or 5)),
        "size_deadline_night": max(1, int(level_config.get("size_deadline_night") or 4)),
        "level_tile_sets": deepcopy(level_config.get("tile_sets") or []),
        "active_tile_set_id": "base",
        "level_layout": {
            "node_tile_counts": deepcopy(level_config.get("node_tile_counts") or {}),
            "node_group_ids": deepcopy(level_config.get("node_group_ids") or {}),
            "groups": deepcopy(level_config.get("groups") or []),
            "node_tokens": deepcopy(level_config.get("node_tokens") or {}),
        },
        "selected_map_id": map_config["id"],
        "active_capability_id": None,
        "last_active_capability_id": None,
        "focused_capability_id": str((bot_config or {}).get("human_ability_id") or DEFAULT_FOCUSED_CAPABILITY_ID),
        "map": _map_projection(map_config),
        "poulpita": {
            "node_id": str(level_config.get("poulpita_starting_node_id") or map_config["starting_node_id"]),
            "previous_node_id": None,
            "energy": starting_energy,
            "max_energy": max_energy,
            "neurons": starting_neurons,
            "seashells": 0,
            "size_index": 0,
            "size_upgraded_today": False,
        },
        "capabilities": _apply_controller_metadata(_initial_capabilities(deal_hands=True), bot_config),
        "tiles": _level_tiles(level_config, tile_catalog),
        "shelters": _level_shelters(level_config),
        "surprise_deck_id": surprise_deck_id,
        "surprise_draw_pile": surprise_draw_pile,
        "surprise_deck_initialized": True,
        "surprise_deck_card_count": len(surprise_draw_pile),
        "surprise_deck_exhausted": not bool(surprise_draw_pile),
        "pending_surprise": None,
        "courtship_completed": False,
        "courtship_blocked_node_id": None,
        "courtship_required": any(
            str(token.get("type") if isinstance(token, dict) else token) == COURTSHIP_TOKEN_ID
            for tokens in (level_config.get("node_tokens") or {}).values()
            for token in tokens or []
        ) or any(
            int((group.get("tile_counts") or {}).get(COURTSHIP_TILE_ID) or 0) > 0
            for group in (level_config.get("groups") or [])
        ),
        "objectives": deepcopy(level_config.get("objectives") or []),
        "objective_progress": {"size_increases": 0, "found_shelter": False, "secured_shelter": False},
        "tile_catalog": tile_catalog,
        "interaction": None,
        "event_log": [
            {
                "event_id": f"evt_{uuid.uuid4().hex}",
                "type": "goldfish_game_started",
                "version": 1,
                "created_at": _now_iso(),
            }
        ],
    }
    _apply_tile_visibility(state)
    return state


def _project_state(state: dict[str, Any]) -> dict[str, Any]:
    bot_config = deepcopy(state.get("bot_config"))
    capabilities = _apply_controller_metadata(deepcopy(state.get("capabilities") or {}), bot_config)
    capability_order = list(CAPABILITY_ORDER)
    player_boards = [capabilities[capability_id] for capability_id in capability_order if capability_id in capabilities]
    tile_catalog = deepcopy(state.get("tile_catalog") or {})
    try:
        latest_catalog = get_game_content_catalog()
        latest_tiles = latest_catalog.get("tiles") or {}
        latest_events = latest_catalog.get("events") or {}
        preserved_special_tiles = {
            tile_id: tile
            for tile_id, tile in (tile_catalog.get("tiles") or {}).items()
            if str(tile_id).startswith("__")
        }
        preserved_special_events = {
            event_id: event
            for event_id, event in (tile_catalog.get("events") or {}).items()
            if str(event_id).startswith("__")
        }
        preserved_special_categories = {
            category_id: category
            for category_id, category in (tile_catalog.get("categories") or {}).items()
            if str(category_id).startswith("__")
        }
        latest_tokens = latest_catalog.get("tokens") or {}
        latest_octopus_token = latest_tokens.get(OCTOPUS_TOKEN_ID) or {}
        if latest_octopus_token:
            octopus_tile, octopus_event, octopus_category = _octopus_public_tile(latest_octopus_token)
            preserved_special_events[OCTOPUS_EVENT_ID] = octopus_event
            preserved_special_categories[OCTOPUS_CATEGORY_ID] = octopus_category
            preserved_special_tiles[OCTOPUS_TILE_ID] = octopus_tile
        tile_catalog["tiles"] = {
            tile_id: _tile_public(tile, {"events": latest_events})
            for tile_id, tile in latest_tiles.items()
        } or {}
        tile_catalog["tiles"].update(preserved_special_tiles)
        tile_catalog["categories"] = {**(latest_catalog.get("categories") or {}), **preserved_special_categories}
        tile_catalog["events"] = {**(latest_events or {}), **preserved_special_events}
        tile_catalog["interactions"] = latest_catalog.get("interactions") or tile_catalog.get("interactions") or {}
        tile_catalog["cards"] = latest_catalog.get("cards") or tile_catalog.get("cards") or {}
        tile_catalog["tokens"] = latest_tokens or tile_catalog.get("tokens") or {}
        tile_catalog["poulpita_panel"] = latest_catalog.get("poulpita_panel") or tile_catalog.get("poulpita_panel") or {}
        tile_catalog["surprise_cards"] = latest_catalog.get("surprise_cards") or tile_catalog.get("surprise_cards") or {}
        tile_catalog["surprise_decks"] = latest_catalog.get("surprise_decks") or tile_catalog.get("surprise_decks") or {}
        tile_catalog["courtship_cards"] = latest_catalog.get("courtship_cards") or tile_catalog.get("courtship_cards") or {}
        tile_catalog["action_costs"] = latest_catalog.get("action_costs") or tile_catalog.get("action_costs") or {}
        tile_catalog["bot_settings"] = latest_catalog.get("bot_settings") or tile_catalog.get("bot_settings") or {}
    except Exception:
        pass
    projected_tiles = {}
    for node_id, node_tiles in (state.get("tiles") or {}).items():
        projected_tiles[node_id] = [
            deepcopy(tile_instance)
            if tile_instance.get("face_up")
            else {"instance_id": tile_instance.get("instance_id"), "face_up": False}
            for tile_instance in node_tiles or []
        ]
    return {
        "room_id": state["room_id"],
        "projection_mode": "goldfish",
        "privacy_enforced": False,
        "mode": state["mode"],
        "bot_config": bot_config,
        "version": int(state["version"]),
        "phase": state["phase"],
        "game_outcome": state.get("game_outcome"),
        "game_over_reason": state.get("game_over_reason"),
        "level_id": state["level_id"],
        "selected_level_id": state.get("selected_level_id") or state.get("level_id"),
        "day_index": int(state.get("day_index") or 1),
        "night_time_spent": int(state.get("night_time_spent") or 0),
        "night_time_total": max(1, int(state.get("night_time_total") or NIGHT_OVERRUN_CHUNKS)),
        "max_nights": max(1, int(state.get("max_nights") or 5)),
        "night_shelter_available_at": NIGHT_SHELTER_AVAILABLE_CHUNKS,
        "selected_map_id": state.get("selected_map_id") or "",
        "poulpita_starting_node_id": state.get("poulpita_starting_node_id") or "",
        "active_capability_id": state.get("active_capability_id"),
        "last_active_capability_id": state.get("last_active_capability_id"),
        "focused_capability_id": state.get("focused_capability_id") or DEFAULT_FOCUSED_CAPABILITY_ID,
        "capability_order": capability_order,
        "capabilities": capabilities,
        "players": [
            {
                "id": capability_id,
                "seat_id": capability_id,
                "display_name": capabilities.get(capability_id, {}).get("name", CAPABILITY_NAMES.get(capability_id, capability_id)),
                "controller_type": capabilities.get(capability_id, {}).get("controller_type", "human"),
                "controller_seat_id": capabilities.get(capability_id, {}).get("controller_seat_id", capability_id),
            }
            for capability_id in capability_order
            if capability_id in capabilities
        ],
        "player_boards": player_boards,
        "map": deepcopy(state["map"]),
        "poulpita": deepcopy(state["poulpita"]),
        "tiles": projected_tiles,
        "shelters": _projected_shelters(state),
        "pending_surprise": deepcopy(state.get("pending_surprise")),
        "courtship_completed": bool(state.get("courtship_completed")),
        "courtship_blocked_node_id": state.get("courtship_blocked_node_id"),
        "courtship_min_size_index": int(state.get("courtship_min_size_index") or 0),
        "counter_attack_min_size_index": int(state.get("counter_attack_min_size_index") or 1),
        "counter_attack_unlocked": _counter_attack_unlocked(state),
        "objectives": _objective_status(state),
        "objective_progress": deepcopy(state.get("objective_progress") or {}),
        "tile_catalog": tile_catalog,
        "interaction": deepcopy(state.get("interaction")),
        "events": list(state.get("event_log") or [])[-20:],
    }


def _configured_action_cost(state: dict[str, Any], action_id: str) -> dict[str, int]:
    defaults = {
        "gain_ap": {"ap_cost": 0, "time_cost": 0, "neuron_cost": 0},
        "move": {"ap_cost": 1, "time_cost": 1, "neuron_cost": 0},
        "draw": {"ap_cost": 1, "time_cost": 1, "neuron_cost": 0},
        "interact": {"ap_cost": 2, "time_cost": 2, "neuron_cost": 0},
        "special_power": {"ap_cost": 2, "time_cost": 2, "neuron_cost": 1},
    }
    raw = ((state.get("tile_catalog") or {}).get("action_costs") or {}).get(action_id) or {}
    fallback = defaults.get(action_id) or {"ap_cost": 0, "time_cost": 0, "neuron_cost": 0}
    return {
        "ap_cost": max(0, int(raw.get("ap_cost") if raw.get("ap_cost") is not None else fallback["ap_cost"])),
        "time_cost": max(0, int(raw.get("time_cost") if raw.get("time_cost") is not None else fallback["time_cost"])),
        "neuron_cost": max(0, int(raw.get("neuron_cost") if raw.get("neuron_cost") is not None else fallback["neuron_cost"])),
    }


def _configured_ap_die_sides(state: dict[str, Any]) -> list[int]:
    raw_sides = ((state.get("tile_catalog") or {}).get("poulpita_panel") or {}).get("ap_die_sides")
    if not isinstance(raw_sides, list):
        return [1, 2, 3, 4, 5, 6]
    sides = [max(0, min(99, int(value))) for value in raw_sides[:32]]
    return sides or [1, 2, 3, 4, 5, 6]


def _require_active_action(service: "GameRoomService", state: dict[str, Any], command_id: str, capability_id: str, *, ap_cost: int = 0, neuron_cost: int = 0) -> dict[str, Any]:
    capability = _require_active_control(service, state, command_id, capability_id)
    if int(capability.get("pa") or 0) < ap_cost:
        service._reject(state, command_id, "insufficient_pa", f"This action costs {ap_cost} AP.")
    if int((state.get("poulpita") or {}).get("neurons") or 0) < neuron_cost:
        service._reject(state, command_id, "insufficient_neurons", f"This action costs {neuron_cost} neurons.")
    if int(capability.get("actions_taken_this_control") or 0) >= int(capability.get("max_actions_per_control") or 3):
        service._reject(state, command_id, "action_limit_reached", "This capability has already taken all actions during this control.")
    return capability


def _require_active_control(service: "GameRoomService", state: dict[str, Any], command_id: str, capability_id: str) -> dict[str, Any]:
    if state["phase"] != PHASE_NIGHT_ACTION:
        service._reject(state, command_id, "phase_not_actionable", "Take control before taking actions.")
    if capability_id != state.get("active_capability_id"):
        service._reject(state, command_id, "not_active_capability", "Only the active capability can take this action.")
    capability = (state.get("capabilities") or {}).get(capability_id)
    if capability is None:
        service._reject(state, command_id, "unknown_capability", "Unknown capability.")
    return capability


def _reset_night_runtime(next_state: dict[str, Any]) -> None:
    next_state["night_time_spent"] = 0
    next_state["active_capability_id"] = None
    next_state.setdefault("poulpita", {})["size_upgraded_today"] = False
    for capability in (next_state.get("capabilities") or {}).values():
        capability["control_takes_this_night"] = 0
        capability["actions_taken_this_control"] = 0


def _spend_action(next_state: dict[str, Any], capability_id: str, *, ap_cost: int = 0, time_cost: int = 0, neuron_cost: int = 0) -> None:
    capability = next_state["capabilities"][capability_id]
    capability["pa"] = int(capability.get("pa") or 0) - ap_cost
    next_state.setdefault("poulpita", {})["neurons"] = max(0, int(next_state.setdefault("poulpita", {}).get("neurons") or 0) - neuron_cost)
    capability["actions_taken_this_control"] = int(capability.get("actions_taken_this_control") or 0) + 1
    if time_cost > 0:
        _advance_night_clock(next_state, chunks=time_cost)


def _advance_night_clock(next_state: dict[str, Any], *, chunks: int = 1) -> None:
    if next_state.get("phase") not in {PHASE_NIGHT_IDLE, PHASE_NIGHT_ACTION}:
        return
    previous_time = int(next_state.get("night_time_spent") or 0)
    next_time = previous_time + max(0, int(chunks or 0))
    next_state["night_time_spent"] = next_time
    night_time_total = max(1, int(next_state.get("night_time_total") or NIGHT_OVERRUN_CHUNKS))
    if previous_time <= night_time_total < next_time:
        _damage_poulpita(next_state, amount=1, reason="night_overrun")
        if int((next_state.get("poulpita") or {}).get("energy") or 0) <= 0:
            _mark_game_lost_if_needed(next_state, reason="poulpita_no_energy")


def _damage_poulpita(next_state: dict[str, Any], *, amount: int = 1, reason: str = "damage") -> None:
    poulpita = next_state.setdefault("poulpita", {})
    poulpita["energy"] = max(0, int(poulpita.get("energy") or 0) - max(0, int(amount or 0)))
    next_state.setdefault("event_log", []).append(
        {
            "event_id": f"evt_{uuid.uuid4().hex}",
            "type": "poulpita_damaged",
            "reason": reason,
            "amount": max(0, int(amount or 0)),
            "energy": int(poulpita.get("energy") or 0),
            "created_at": _now_iso(),
        }
    )


def _active_capability_is_out_of_actions(state: dict[str, Any]) -> bool:
    active_id = state.get("active_capability_id")
    if not active_id:
        return True
    capability = (state.get("capabilities") or {}).get(active_id) or {}
    remaining_actions = int(capability.get("max_actions_per_control") or 0) - int(capability.get("actions_taken_this_control") or 0)
    return remaining_actions <= 0


def _no_other_control_takes_available(state: dict[str, Any]) -> bool:
    active_id = str(state.get("active_capability_id") or "")
    for capability_id, capability in (state.get("capabilities") or {}).items():
        if str(capability_id) == active_id:
            continue
        if int(capability.get("control_takes_this_night") or 0) < int(capability.get("max_control_takes_per_night") or 0):
            return False
    return True


def _mark_game_lost_if_needed(next_state: dict[str, Any], *, reason: str | None = None) -> bool:
    if next_state.get("phase") == PHASE_FINISHED:
        return True
    loss_reason = reason
    if not loss_reason and _no_other_control_takes_available(next_state) and _active_capability_is_out_of_actions(next_state):
        loss_reason = loss_reason or "no_controls_or_actions"
    if not loss_reason:
        return False
    next_state["phase"] = PHASE_FINISHED
    next_state["game_outcome"] = "lost"
    next_state["game_over_reason"] = loss_reason
    next_state.setdefault("event_log", []).append(
        {
            "event_id": f"evt_{uuid.uuid4().hex}",
            "type": "game_lost",
            "reason": loss_reason,
            "version": int(next_state.get("version") or 0),
            "created_at": _now_iso(),
        }
    )
    return True


def _normalize_shelter_entry(entry: Any) -> dict[str, int]:
    if isinstance(entry, dict):
        count = max(0, int(entry.get("count") or entry.get("tokens") or 0))
        seashells = max(0, int(entry.get("seashells") or entry.get("shells") or 0))
    else:
        count = max(0, int(entry or 0))
        seashells = 0
    return {"count": count, "seashells": seashells, "secure": seashells >= 3}


def _shelter_entry(state: dict[str, Any], node_id: str | None) -> dict[str, int]:
    if not node_id:
        return {"count": 0, "seashells": 0, "secure": False}
    return _normalize_shelter_entry((state.get("shelters") or {}).get(str(node_id)))


def _ensure_shelter_entry(next_state: dict[str, Any], node_id: str) -> dict[str, int]:
    shelters = next_state.setdefault("shelters", {})
    normalized = _normalize_shelter_entry(shelters.get(node_id))
    shelters[node_id] = normalized
    return normalized


def _has_shelter(state: dict[str, Any], node_id: str | None) -> bool:
    return _shelter_entry(state, node_id).get("count", 0) > 0


def _current_shelter_secure(state: dict[str, Any]) -> bool:
    current_node_id = str((state.get("poulpita") or {}).get("node_id") or "")
    return bool(_shelter_entry(state, current_node_id).get("secure"))


def _projected_shelters(state: dict[str, Any]) -> dict[str, Any]:
    return {
        str(node_id): _normalize_shelter_entry(entry)
        for node_id, entry in (state.get("shelters") or {}).items()
        if _normalize_shelter_entry(entry).get("count", 0) > 0
    }


def _counter_attack_unlocked(state: dict[str, Any]) -> bool:
    current_size = max(0, int((state.get("poulpita") or {}).get("size_index") or 0))
    required_size = max(1, int(state.get("counter_attack_min_size_index") or 1))
    return current_size >= required_size


def _counter_attack_requirements(state: dict[str, Any], tile: dict[str, Any]) -> list[str]:
    if not _counter_attack_unlocked(state):
        return []
    return [str(interaction_id) for interaction_id in (tile.get("counter_attack_interaction_ids") or []) if interaction_id]


def _objective_status(state: dict[str, Any]) -> list[dict[str, Any]]:
    progress = state.get("objective_progress") or {}
    statuses = []
    for objective in state.get("objectives") or []:
        objective_type = str(objective.get("type") or "")
        target = max(1, int(objective.get("target") or 1))
        current = 0
        completed = False
        label = objective_type
        if objective_type == "increase_size":
            current = max(0, int(progress.get("size_increases") or 0))
            completed = current >= target
            label = f"Increase size {target} time{'s' if target != 1 else ''}"
        elif objective_type == "find_shelter":
            completed = bool(progress.get("found_shelter"))
            label = "Find a shelter"
        elif objective_type == "secure_shelter":
            completed = bool(progress.get("secured_shelter"))
            label = "Secure a shelter"
        elif objective_type == "resolve_courtship":
            completed = bool(state.get("courtship_completed"))
            label = "Resolve courtship"
        elif objective_type == "return_secured_shelter_after_courtship":
            current = max(0, int(progress.get("secured_shelter_return_energy_after_courtship") or 0))
            completed = current >= target
            label = f"Return to a secured shelter with {target} energy after courtship"
        statuses.append({
            **objective,
            "label": label,
            "current": current,
            "target": target if objective_type in {"increase_size", "return_secured_shelter_after_courtship"} else None,
            "completed": completed,
        })
    return statuses


def _mark_game_won_if_needed(next_state: dict[str, Any]) -> bool:
    objectives = next_state.get("objectives") or []
    if next_state.get("phase") == PHASE_FINISHED:
        return False
    if objectives and not all(objective.get("completed") for objective in _objective_status(next_state)):
        return False
    if not objectives:
        return False
    next_state["phase"] = PHASE_FINISHED
    next_state["game_outcome"] = "won"
    next_state["game_over_reason"] = "objectives_completed"
    next_state.setdefault("event_log", []).append(
        {
            "event_id": f"evt_{uuid.uuid4().hex}",
            "type": "game_won",
            "reason": "objectives_completed",
            "version": int(next_state.get("version") or 0),
            "created_at": _now_iso(),
        }
    )
    return True


def _find_tile_instance(state: dict[str, Any], tile_instance_id: str) -> tuple[str, dict[str, Any]] | tuple[None, None]:
    for node_id, tiles in (state.get("tiles") or {}).items():
        for tile_instance in tiles or []:
            if tile_instance.get("instance_id") == tile_instance_id:
                return node_id, tile_instance
    return None, None


def _maybe_start_courtship_interaction(next_state: dict[str, Any]) -> bool:
    if next_state.get("interaction") or next_state.get("pending_surprise") or next_state.get("courtship_completed"):
        return False
    current_node_id = str((next_state.get("poulpita") or {}).get("node_id") or "")
    if not current_node_id or str(next_state.get("courtship_blocked_node_id") or "") == current_node_id:
        return False
    courtship_instance = next(
        (
            instance
            for instance in (next_state.get("tiles") or {}).get(current_node_id, []) or []
            if str(instance.get("token_type") or "") == COURTSHIP_TOKEN_ID
        ),
        None,
    )
    if not courtship_instance or _compulsory_tile_choices(next_state, current_node_id):
        return False
    if int((next_state.get("poulpita") or {}).get("size_index") or 0) < int(next_state.get("courtship_min_size_index") if next_state.get("courtship_min_size_index") is not None else 3):
        return False
    if int((next_state.get("poulpita") or {}).get("energy") or 0) < int(next_state.get("courtship_min_energy") or 8):
        return False
    courtship_cards = list(((next_state.get("tile_catalog") or {}).get("courtship_cards") or {}).values())
    if not courtship_cards:
        return False
    next_state["interaction"] = {
        "tile_instance_id": courtship_instance.get("instance_id"),
        "tile_id": COURTSHIP_TILE_ID,
        "node_id": current_node_id,
        "initiator_capability_id": next_state.get("active_capability_id"),
        "initiator_confirmed": False,
        "played_cards": [],
        "requirement_reduction": 1 if next_state.get("force_reduces_next_interaction") else 0,
        "courtship_card": deepcopy(random.choice(courtship_cards)),
    }
    next_state["force_reduces_next_interaction"] = False
    next_state.setdefault("event_log", []).append(
        {
            "event_id": f"evt_{uuid.uuid4().hex}",
            "type": "courtship_started",
            "created_at": _now_iso(),
        }
    )
    return True


def _compulsory_tile_choices(state: dict[str, Any], node_id: str) -> list[dict[str, Any]]:
    catalog = state.get("tile_catalog") or {}
    catalog_tiles = catalog.get("tiles") or {}
    catalog_events = catalog.get("events") or {}
    catalog_categories = catalog.get("categories") or {}
    choices = []
    for tile_instance in (state.get("tiles") or {}).get(node_id, []) or []:
        if not tile_instance.get("face_up"):
            continue
        tile = catalog_tiles.get(tile_instance.get("tile_id")) or {}
        category = _tile_category(state, tile)
        if not category.get("compulsory_on_same_node"):
            continue
        choices.append(
            {
                "instance_id": tile_instance.get("instance_id"),
                "tile_id": tile_instance.get("tile_id"),
                "priority": int(tile.get("priority") or 0),
            }
        )
    if not choices:
        return []
    highest_priority = max(choice["priority"] for choice in choices)
    return [choice for choice in choices if choice["priority"] == highest_priority]


def _tile_category(state: dict[str, Any], tile: dict[str, Any]) -> dict[str, Any]:
    catalog = state.get("tile_catalog") or {}
    event = tile.get("event") or (catalog.get("events") or {}).get(tile.get("event_id")) or {}
    return (catalog.get("categories") or {}).get(event.get("category_id")) or {}


def _night_end_blockers(state: dict[str, Any], node_id: str) -> list[dict[str, Any]]:
    catalog_tiles = ((state.get("tile_catalog") or {}).get("tiles") or {})
    blockers = []
    for instance in (state.get("tiles") or {}).get(node_id, []) or []:
        tile = catalog_tiles.get(instance.get("tile_id")) or {}
        if _is_octopus_tile_instance(instance) or tile.get("token_type") == OCTOPUS_TOKEN_ID:
            blockers.append(instance)
            continue
        if _tile_category(state, tile).get("compulsory_on_same_node"):
            blockers.append(instance)
    return blockers


def _played_interactions(state: dict[str, Any]) -> list[str]:
    interactions = []
    for card in ((state.get("interaction") or {}).get("played_cards") or []):
        interactions.append(str(card.get("interaction_id") or ""))
    return interactions


def _card_interaction_options(card: dict[str, Any]) -> list[str]:
    options = [str(interaction_id) for interaction_id in (card.get("interaction_ids") or []) if interaction_id]
    interaction_id = str(card.get("interaction_id") or "")
    if interaction_id and interaction_id not in options:
        options.insert(0, interaction_id)
    return options


def _choose_card_interaction(next_state: dict[str, Any], played_cards: list[dict[str, Any]], card: dict[str, Any]) -> str:
    options = _card_interaction_options(card)
    if not options:
        return str(card.get("interaction_id") or "")
    interaction = next_state.get("interaction") or {}
    tile = (next_state.get("tile_catalog") or {}).get("tiles", {}).get(interaction.get("tile_id")) or {}
    played = [str(played_card.get("interaction_id") or "") for played_card in played_cards]
    for required_ids in [tile.get("interaction_ids") or [], _counter_attack_requirements(next_state, tile)]:
        remaining = list(required_ids)
        for played_interaction_id in played:
            if played_interaction_id in remaining:
                remaining.remove(played_interaction_id)
        for option in options:
            if option in remaining:
                return option
    return options[0]


def _sync_interaction_cards(next_state: dict[str, Any], capability_id: str, selected_card_ids: list[str]) -> None:
    interaction = next_state.get("interaction") or {}
    capability = next_state.get("capabilities", {}).get(capability_id)
    if capability is None:
        raise ValueError("Unknown capability.")
    selected = {str(card_id) for card_id in selected_card_ids}
    kept_played = []
    for card in interaction.get("played_cards") or []:
        if card.get("capability_id") == capability_id:
            capability.setdefault("hand", []).append(
                {
                    "card_id": card["card_id"],
                    "interaction_id": card["interaction_id"],
                    "interaction_ids": _card_interaction_options(card),
                    "owner_capability_id": capability_id,
                }
            )
        else:
            kept_played.append(card)
    next_played = kept_played
    interaction_tile = (next_state.get("tile_catalog") or {}).get("tiles", {}).get(interaction.get("tile_id")) or {}
    required_ids = list(
        ((interaction.get("courtship_card") or {}).get("interaction_ids"))
        or interaction_tile.get("interaction_ids")
        or []
    ) + _counter_attack_requirements(next_state, interaction_tile)
    hand = []
    for card in capability.get("hand") or []:
        if str(card.get("card_id")) in selected:
            remaining = list(required_ids)
            for played_card in next_played:
                played_interaction_id = str(played_card.get("interaction_id") or "")
                if played_interaction_id in remaining:
                    remaining.remove(played_interaction_id)
            chosen_interaction_id = _choose_card_interaction(next_state, next_played, card)
            if chosen_interaction_id not in remaining:
                raise ValueError("Cards can only be played for requirements that are still missing.")
            next_played.append({**card, "interaction_id": chosen_interaction_id, "interaction_ids": _card_interaction_options(card), "capability_id": capability_id})
        else:
            hand.append(card)
    missing = selected - {str(card.get("card_id")) for card in next_played if card.get("capability_id") == capability_id}
    if missing:
        raise ValueError("Selected cards must be in this ability hand or already played by it.")
    capability["hand"] = hand
    interaction["played_cards"] = next_played


def _auto_selected_interaction_card_ids(next_state: dict[str, Any], capability_id: str, required_interaction_ids: list[str]) -> list[str]:
    interaction = next_state.get("interaction") or {}
    capability = next_state.get("capabilities", {}).get(capability_id)
    if capability is None:
        return []
    remaining = [str(interaction_id) for interaction_id in required_interaction_ids if interaction_id]
    selected: list[str] = []
    for card in interaction.get("played_cards") or []:
        if str(card.get("capability_id") or "") == capability_id and card.get("card_id"):
            selected.append(str(card.get("card_id")))
        played_interaction_id = str(card.get("interaction_id") or "")
        if played_interaction_id in remaining:
            remaining.remove(played_interaction_id)
    for card in capability.get("hand") or []:
        if not remaining:
            break
        match = next((interaction_id for interaction_id in remaining if interaction_id in _card_interaction_options(card)), None)
        if match:
            remaining.remove(match)
            selected.append(str(card.get("card_id")))
    return selected


def _auto_discard_card_id_for_draw(state: dict[str, Any], capability: dict[str, Any]) -> str:
    interaction = state.get("interaction") or {}
    tile = (state.get("tile_catalog") or {}).get("tiles", {}).get(interaction.get("tile_id")) or {}
    required = [
        str(interaction_id)
        for interaction_id in list(tile.get("interaction_ids") or []) + _counter_attack_requirements(state, tile)
        if interaction_id
    ]
    hand = capability.get("hand") or []
    if required:
        for card in hand:
            if not any(interaction_id in required for interaction_id in _card_interaction_options(card)):
                return str(card.get("card_id") or "")
    return str((hand[0] if hand else {}).get("card_id") or "")


def _auto_selected_surprise_card_ids(capability: dict[str, Any], costs: list[dict[str, Any]]) -> list[str]:
    selected: list[str] = []
    selected_ids: set[str] = set()
    for cost in costs or []:
        if str(cost.get("type") or "") != "play_cards":
            continue
        remaining = [str(interaction_id) for interaction_id in (cost.get("interaction_ids") or []) if interaction_id]
        for card in capability.get("hand") or []:
            card_id = str(card.get("card_id") or "")
            if not remaining or card_id in selected_ids:
                continue
            match = next((interaction_id for interaction_id in remaining if interaction_id in _card_interaction_options(card)), None)
            if match:
                remaining.remove(match)
                selected.append(card_id)
                selected_ids.add(card_id)
    return selected


def _criteria_met(required: list[str], played: list[str]) -> bool:
    remaining = list(required or [])
    for interaction_id in played:
        if interaction_id in remaining:
            remaining.remove(interaction_id)
    return not remaining


def _criteria_met_with_reduction(required: list[str], played: list[str], reduction: int = 0) -> bool:
    if reduction <= 0:
        return _criteria_met(required, played)
    if len(required) <= reduction:
        return True
    return any(
        _criteria_met(required[:index] + required[index + 1 :], played)
        for index in range(len(required))
    )


def _shell_requirement_count(tile: dict[str, Any]) -> int:
    return max(0, int(tile.get("shell_requirement_count") or 0))


def _shell_requirement_met(state: dict[str, Any], tile: dict[str, Any]) -> bool:
    required = _shell_requirement_count(tile)
    if required <= 0:
        return True
    return int((state.get("poulpita") or {}).get("seashells") or 0) >= required


def _spend_required_shells(next_state: dict[str, Any], tile: dict[str, Any]) -> None:
    required = _shell_requirement_count(tile)
    if required <= 0:
        return
    poulpita = next_state.setdefault("poulpita", {})
    poulpita["seashells"] = max(0, int(poulpita.get("seashells") or 0) - required)


def _apply_effects(next_state: dict[str, Any], effects: list[dict[str, Any]], *, node_id: str | None = None) -> None:
    for effect in effects or []:
        effect_type = str(effect.get("type") or "")
        amount = int(effect.get("amount") or 0)
        if effect_type == "gain_energy":
            max_energy = max(1, int(next_state["poulpita"].get("max_energy") or 32))
            next_state["poulpita"]["energy"] = min(max_energy, int(next_state["poulpita"].get("energy") or 0) + amount)
        elif effect_type == "gain_neurons":
            next_state["poulpita"]["neurons"] = int(next_state["poulpita"].get("neurons") or 0) + amount
        elif effect_type == "gain_seashells":
            next_state["poulpita"]["seashells"] = int(next_state["poulpita"].get("seashells") or 0) + amount
        elif effect_type == "place_shelter_token":
            target_node_id = str(node_id or next_state.get("poulpita", {}).get("node_id") or "")
            if target_node_id:
                shelter = _ensure_shelter_entry(next_state, target_node_id)
                shelter["count"] = int(shelter.get("count") or 0) + 1
                shelter["secure"] = int(shelter.get("seashells") or 0) >= 3
        elif effect_type == "draw_surprise_card":
            _draw_surprise_card(next_state)


def _move_poulpita_without_ap(next_state: dict[str, Any], target_node_id: str) -> None:
    current_node_id = str(next_state.get("poulpita", {}).get("node_id") or "")
    next_state["poulpita"]["previous_node_id"] = current_node_id or None
    next_state["poulpita"]["node_id"] = target_node_id
    _record_shelter_arrival(next_state, target_node_id)


def _record_shelter_arrival(next_state: dict[str, Any], node_id: str) -> None:
    if not _has_shelter(next_state, node_id):
        return
    progress = next_state.setdefault("objective_progress", {})
    progress["found_shelter"] = True
    if next_state.get("courtship_completed") and _shelter_entry(next_state, node_id).get("secure"):
        energy = max(0, int((next_state.get("poulpita") or {}).get("energy") or 0))
        progress["secured_shelter_return_energy_after_courtship"] = max(
            energy,
            int(progress.get("secured_shelter_return_energy_after_courtship") or 0),
        )


def _move_interaction_tile(next_state: dict[str, Any], interaction: dict[str, Any], target_node_id: str) -> None:
    source_node_id = interaction.get("node_id")
    tile_instance_id = interaction.get("tile_instance_id")
    source_tiles = next_state.get("tiles", {}).get(source_node_id) or []
    tile_instance = next((entry for entry in source_tiles if entry.get("instance_id") == tile_instance_id), None)
    if tile_instance is None:
        return
    next_state["tiles"][source_node_id] = [entry for entry in source_tiles if entry.get("instance_id") != tile_instance_id]
    next_state.setdefault("tiles", {}).setdefault(target_node_id, []).append(tile_instance)
    interaction["node_id"] = target_node_id


def _remove_tiles_by_category(next_state: dict[str, Any], node_id: str, category_id: str) -> None:
    catalog_tiles = (next_state.get("tile_catalog") or {}).get("tiles") or {}
    catalog_events = (next_state.get("tile_catalog") or {}).get("events") or {}
    kept_tiles = []
    for tile_instance in (next_state.get("tiles", {}).get(node_id) or []):
        tile = catalog_tiles.get(tile_instance.get("tile_id")) or {}
        event = tile.get("event") or catalog_events.get(tile.get("event_id")) or {}
        if event.get("category_id") != category_id:
            kept_tiles.append(tile_instance)
    next_state["tiles"][node_id] = kept_tiles


def _draw_surprise_card(next_state: dict[str, Any]) -> dict[str, Any] | None:
    if next_state.get("pending_surprise"):
        return None

    def refresh_draw_pile() -> None:
        try:
            level_config = get_level_config(str(next_state.get("level_id") or ""))
            surprise_deck_id = str(level_config.get("surprise_deck_id") or next_state.get("surprise_deck_id") or "")
            latest_catalog = get_game_content_catalog()
            draw_pile = list(((latest_catalog.get("surprise_decks") or {}).get(surprise_deck_id) or {}).get("card_ids") or [])
            random.shuffle(draw_pile)
            next_state["surprise_deck_id"] = surprise_deck_id
            next_state["surprise_draw_pile"] = draw_pile
            next_state["surprise_deck_initialized"] = True
            next_state["surprise_deck_card_count"] = len(draw_pile)
            next_state["surprise_deck_exhausted"] = not bool(draw_pile)
            next_state.setdefault("tile_catalog", {})["surprise_cards"] = latest_catalog.get("surprise_cards") or next_state.get("tile_catalog", {}).get("surprise_cards") or {}
            next_state.setdefault("tile_catalog", {})["surprise_decks"] = latest_catalog.get("surprise_decks") or next_state.get("tile_catalog", {}).get("surprise_decks") or {}
        except Exception:
            next_state["surprise_deck_initialized"] = True

    if not next_state.get("surprise_deck_initialized"):
        refresh_draw_pile()
    draw_pile = next_state.setdefault("surprise_draw_pile", [])
    deck_was_never_populated = int(next_state.get("surprise_deck_card_count") or 0) == 0
    if not draw_pile and (not next_state.get("surprise_deck_exhausted") or deck_was_never_populated):
        refresh_draw_pile()
        draw_pile = next_state.setdefault("surprise_draw_pile", [])
    if not draw_pile:
        return None
    card_id = str(draw_pile.pop(0))
    if not draw_pile:
        next_state["surprise_deck_exhausted"] = True
    card = ((next_state.get("tile_catalog") or {}).get("surprise_cards") or {}).get(card_id)
    if not card:
        return None
    pending = {"card": deepcopy(card), "selected_cards": [], "created_at": _now_iso()}
    next_state["pending_surprise"] = pending
    return pending


def _apply_surprise_effects(next_state: dict[str, Any], effects: list[dict[str, Any]]) -> None:
    current_node_id = str((next_state.get("poulpita") or {}).get("node_id") or "")
    adjacency = (next_state.get("map") or {}).get("adjacency") or {}
    for effect in effects or []:
        effect_type = str(effect.get("type") or "")
        amount = max(0, int(effect.get("amount") or 0))
        if effect_type == "gain_ap":
            capability_id = str(effect.get("capability_id") or "")
            capability = (next_state.get("capabilities") or {}).get(capability_id)
            if capability is not None:
                capability["pa"] = int(capability.get("pa") or 0) + amount
        elif effect_type == "gain_neurons":
            next_state["poulpita"]["neurons"] = int(next_state["poulpita"].get("neurons") or 0) + amount
        elif effect_type == "advance_night":
            _advance_night_clock(next_state, chunks=amount)
        elif effect_type == "gain_energy":
            max_energy = max(1, int(next_state["poulpita"].get("max_energy") or 32))
            next_state["poulpita"]["energy"] = min(max_energy, int(next_state["poulpita"].get("energy") or 0) + amount)
        elif effect_type == "lose_energy":
            _damage_poulpita(next_state, amount=amount, reason="surprise_card")
            if int((next_state.get("poulpita") or {}).get("energy") or 0) <= 0:
                _mark_game_lost_if_needed(next_state, reason="poulpita_no_energy")
        elif effect_type == "remove_tiles_category_here":
            _remove_tiles_by_category(next_state, current_node_id, str(effect.get("category_id") or ""))
        elif effect_type == "remove_tiles_category_adjacent":
            for node_id in adjacency.get(current_node_id, []) or []:
                _remove_tiles_by_category(next_state, str(node_id), str(effect.get("category_id") or ""))
    _apply_tile_visibility(next_state)


def _apply_failure_effects(
    next_state: dict[str, Any],
    effects: list[dict[str, Any]],
    interaction: dict[str, Any],
    *,
    free_move_target_node_id: str | None = None,
) -> None:
    original_previous_node_id = next_state.get("poulpita", {}).get("previous_node_id")
    for effect in effects or []:
        effect_type = str(effect.get("type") or "")
        amount = int(effect.get("amount") or 0)
        if effect_type == "lose_energy":
            next_state["poulpita"]["energy"] = max(0, int(next_state["poulpita"].get("energy") or 0) - amount)
        elif effect_type == "lose_neurons":
            next_state["poulpita"]["neurons"] = max(0, int(next_state["poulpita"].get("neurons") or 0) - amount)
        elif effect_type == "lose_seashells":
            next_state["poulpita"]["seashells"] = max(0, int(next_state["poulpita"].get("seashells") or 0) - amount)
        elif effect_type == "lose_ap":
            for capability in (next_state.get("capabilities") or {}).values():
                capability["pa"] = max(0, int(capability.get("pa") or 0) - amount)
        elif effect_type == "lose_half_ap":
            for capability in (next_state.get("capabilities") or {}).values():
                capability["pa"] = max(0, int(capability.get("pa") or 0) // 2)
        elif effect_type == "lose_all_ap":
            for capability in (next_state.get("capabilities") or {}).values():
                capability["pa"] = 0
        elif effect_type == "pulpita_move_previous":
            if original_previous_node_id:
                _move_poulpita_without_ap(next_state, str(original_previous_node_id))
        elif effect_type == "pulpita_move_free":
            if free_move_target_node_id:
                _move_poulpita_without_ap(next_state, free_move_target_node_id)
        elif effect_type == "remove_tile":
            node_id = interaction.get("node_id")
            node_tiles = next_state.get("tiles", {}).get(node_id) or []
            next_state["tiles"][node_id] = [entry for entry in node_tiles if entry.get("instance_id") != interaction.get("tile_instance_id")]
        elif effect_type == "move_tile_previous":
            if original_previous_node_id:
                _move_interaction_tile(next_state, interaction, str(original_previous_node_id))
        elif effect_type == "remove_preys":
            category_id = str(effect.get("category_id") or "")
            if category_id:
                _remove_tiles_by_category(next_state, str(interaction.get("node_id") or ""), category_id)


class GameRoomService:
    def __init__(self, redis_client=None) -> None:
        self.redis = redis_client
        self.node_id = f"game-service-{uuid.uuid4().hex}"
        self._memory_rooms: dict[str, dict[str, Any]] = {}
        self._memory_states: dict[str, dict[str, Any]] = {}
        self._memory_results: dict[str, dict[str, Any]] = {}
        self._memory_history: dict[str, list[str]] = {}
        self._room_locks: dict[str, asyncio.Lock] = {}
        self._room_sockets: dict[str, set[WebSocket]] = {}
        self._room_pubsub_tasks: dict[str, asyncio.Task] = {}

    def configure_redis(self, redis_client) -> None:
        self.redis = redis_client

    async def close(self) -> None:
        tasks = list(self._room_pubsub_tasks.values())
        self._room_pubsub_tasks.clear()
        for task in tasks:
            task.cancel()
        for task in tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def _redis_get_json(self, key: str) -> dict[str, Any] | None:
        if self.redis is None:
            return None
        raw = await self.redis.get(key)
        if not raw:
            return None
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8", errors="ignore")
        try:
            parsed = json.loads(str(raw))
        except (TypeError, json.JSONDecodeError):
            return None
        return parsed if isinstance(parsed, dict) else None

    async def _redis_set_json(self, key: str, payload: dict[str, Any], *, ex: int | None = None) -> None:
        if self.redis is None:
            return
        encoded = json.dumps(payload, default=str, separators=(",", ":"))
        if ex is None:
            await self.redis.set(key, encoded)
        else:
            await self.redis.set(key, encoded, ex=ex)

    async def _save_room(self, room: dict[str, Any]) -> None:
        room_id = str(room.get("id") or "")
        if not room_id:
            return
        self._memory_rooms[room_id] = deepcopy(room)
        await self._redis_set_json(_room_key(room_id), room)

    async def _load_room(self, room_id: str) -> dict[str, Any] | None:
        if self.redis is not None:
            room = await self._redis_get_json(_room_key(room_id))
            if room is not None:
                self._memory_rooms[room_id] = room
                return room
        room = self._memory_rooms.get(room_id)
        if room is not None:
            return room
        return None

    async def _save_state(self, room_id: str, state: dict[str, Any]) -> None:
        self._memory_states[room_id] = deepcopy(state)
        await self._redis_set_json(_state_key(room_id), state)

    async def _load_state(self, room_id: str) -> dict[str, Any] | None:
        if self.redis is not None:
            state = await self._redis_get_json(_state_key(room_id))
            if state is not None:
                self._memory_states[room_id] = state
                return state
        state = self._memory_states.get(room_id)
        if state is not None:
            return state
        return None

    async def _save_result(self, result: dict[str, Any]) -> None:
        room_id = str(result.get("room_id") or result.get("id") or "")
        if not room_id:
            return
        self._memory_results[room_id] = deepcopy(result)
        await self._redis_set_json(_result_key(room_id), result)

    async def create_room(
        self,
        *,
        user: User,
        mode: str = "goldfish",
        game_type: str = "goldfish",
        map_id: str | None = None,
        level_id: str | None = None,
        human_ability_id: str | None = None,
    ) -> dict[str, Any]:
        normalized_game_type = str(game_type or "goldfish").strip() or "goldfish"
        bot_config = _bot_room_config(mode=mode, human_ability_id=human_ability_id)
        normalized_mode = str((bot_config or {}).get("mode") or "goldfish")
        selected_level = get_level_config(level_id)
        selected_map = get_map(selected_level["map_id"])
        room_id = f"room_{uuid.uuid4().hex[:16]}"
        now = _now_iso()
        room = {
            "id": room_id,
            "owner_user_id": user.id,
            "owner_username": user.username or user.email or user.id,
            "mode": normalized_mode,
            "game_type": normalized_game_type,
            "state": ROOM_STATE_SETUP,
            "created_at": now,
            "started_at": "",
            "ended_at": "",
            "result_id": "",
            "map_id": selected_map["id"],
            "level_id": selected_level["id"],
            "bot_config": deepcopy(bot_config),
        }
        await self._save_room(room)
        await self._save_state(room_id, _setup_state(room_id, level_id=selected_level["id"], mode=normalized_mode, bot_config=bot_config))
        self._room_locks[room_id] = asyncio.Lock()
        return _public_room(room)

    async def get_room(self, *, room_id: str, user: User) -> dict[str, Any] | None:
        room = await self._load_room(room_id)
        if not room or room.get("owner_user_id") != user.id:
            return None
        return _public_room(room)

    async def join_room(self, *, room_id: str, user: User) -> dict[str, str] | None:
        room = await self._load_room(room_id)
        if not room or room.get("owner_user_id") != user.id:
            return None
        return {"room_id": room_id, "seat_id": "goldfish"}

    async def get_projection(self, *, room_id: str, user: User) -> dict[str, Any] | None:
        room = await self._load_room(room_id)
        if not room or room.get("owner_user_id") != user.id:
            return None
        state = await self._load_state(room_id)
        if state is None:
            return None
        return _project_state(state)

    async def get_game_state(self, *, room_id: str, user: User, selected_tile: str | None = None) -> dict[str, Any] | None:
        return await self.get_projection(room_id=room_id, user=user)

    async def get_bot_plans(self, *, room_id: str, user: User) -> dict[str, Any] | None:
        room = await self._load_room(room_id)
        if not room or room.get("owner_user_id") != user.id:
            return None
        state = await self._load_state(room_id)
        if state is None:
            return None
        state = self._state_with_latest_content_metadata(state)
        plans = await asyncio.to_thread(generate_bot_plan_status, state)
        return public_bot_plan_status(plans)

    async def execute_bot_plan(self, *, room_id: str, user: User, plan_id: str) -> dict[str, Any] | None:
        room = await self._load_room(room_id)
        if not room or room.get("owner_user_id") != user.id:
            return None
        state = await self._load_state(room_id)
        if state is None:
            return None
        state = self._state_with_latest_content_metadata(state)
        plans = await asyncio.to_thread(generate_bot_plan_status, state)
        proposal = next((entry for entry in plans.get("proposals") or [] if str(entry.get("plan_id")) == str(plan_id)), None)
        if proposal is None:
            return {
                "ok": False,
                "status": "invalidated",
                "plan_id": plan_id,
                "reason": "plan_not_available",
                "message": "This plan is no longer available for the current state.",
                "projection": _project_state(state),
                "command_results": [],
            }
        all_command_templates = list(proposal.get("commands") or [])
        command_templates = all_command_templates[:1]
        if not command_templates:
            return {
                "ok": False,
                "status": "human_input_required",
                "plan_id": plan_id,
                "reason": "no_executable_commands",
                "message": "This plan needs a human decision before it can execute.",
                "projection": _project_state(state),
                "command_results": [],
            }
        command_results = []
        projection = _project_state(state)
        status = "completed"
        reason = "plan_completed"
        message = "Plan completed."
        for index, template in enumerate(command_templates):
            latest_state = await self._load_state(room_id)
            if latest_state is None:
                raise LookupError("Game state not found.")
            command_type = str(template.get("type") or "")
            command = {
                "command_id": f"bot_{uuid.uuid4().hex}",
                "room_id": room_id,
                "actor_user_id": user.id,
                "actor_seat_id": "bot_plan",
                "expected_version": int(latest_state.get("version") or 0),
                "type": command_type,
                "payload": deepcopy(template.get("payload") or {}),
            }
            result = await self.enqueue_game_command(room_id=room_id, user=user, command=command)
            command_results.append(
                {
                    "command_id": result.get("command_id"),
                    "type": command_type,
                    "ok": bool(result.get("ok")),
                    "status": result.get("status"),
                    "reason": result.get("reason"),
                    "message": result.get("message"),
                    "version": result.get("version") or result.get("revision"),
                }
            )
            projection = result.get("projection") or projection
            if not result.get("ok"):
                status = "command_rejected"
                reason = str(result.get("reason") or "command_rejected")
                message = str(result.get("message") or "A bot plan command was rejected.")
                break
            if (projection or {}).get("phase") == PHASE_FINISHED:
                status = "game_finished"
                reason = "game_finished"
                message = "The game finished during plan execution."
                break
            if (projection or {}).get("pending_surprise"):
                status = "human_input_required"
                reason = "surprise_resolution_required"
                message = "A surprise card was drawn. Resolve it before continuing the plan."
                break
            if command_type == "move_poulpita" and index < len(command_templates) - 1:
                status = "replan_required"
                reason = "movement_changed_visibility"
                message = "Movement can reveal new information; choose a new plan before continuing."
                break
        if status == "completed" and command_results:
            last_type = command_results[-1].get("type")
            if last_type == "start_interaction":
                status = "human_input_required"
                reason = "interaction_needs_resolution"
                message = "The interaction is open. Add required support or confirm the result."
            elif last_type in {"collect_action_points", "draw_action_card", "move_poulpita"}:
                status = "replan_required"
                reason = f"{last_type}_changed_state"
                message = "The plan reached a decision boundary. Recalculate plans."
            elif len(command_results) < len(all_command_templates):
                status = "replan_required"
                reason = "planned_step_completed"
                message = "One planned step was executed. Recalculate or execute the next selected step."
        return {
            "ok": status not in {"command_rejected", "invalidated"},
            "status": status,
            "plan_id": plan_id,
            "proposal_set_id": plans.get("proposal_set_id"),
            "generated_from_version": plans.get("generated_from_version"),
            "reason": reason,
            "message": message,
            "command_results": command_results,
            "projection": projection,
        }

    async def execute_bot_orchestrator_step(self, *, room_id: str, user: User) -> dict[str, Any] | None:
        room = await self._load_room(room_id)
        if not room or room.get("owner_user_id") != user.id:
            return None
        state = await self._load_state(room_id)
        if state is None:
            return None
        state = self._state_with_latest_content_metadata(state)
        decision = await asyncio.to_thread(choose_bot_orchestrator_action, state)
        public_decision = deepcopy(decision)
        for evaluated in public_decision.get("evaluated_plans") or []:
            for rollout in evaluated.get("rollouts") or []:
                rollout.pop("path", None)
        command_template = decision.get("command")
        if not isinstance(command_template, dict):
            if (
                room.get("mode") == "bots_only"
                and state.get("phase") in {PHASE_NIGHT_IDLE, PHASE_NIGHT_ACTION}
                and _active_capability_is_out_of_actions(state)
                and _no_other_control_takes_available(state)
            ):
                command_template = {"type": "bot_no_actions_available", "payload": {}}
            else:
                return {
                    "ok": False,
                    "status": decision.get("status") or "idle",
                    "message": decision.get("message") or "No orchestrator action is available.",
                    "decision": public_decision,
                    "projection": _project_state(state),
                }
        command = {
            "command_id": f"orchestrator_{uuid.uuid4().hex}",
            "room_id": room_id,
            "actor_user_id": user.id,
            "actor_seat_id": "bot_orchestrator",
            "expected_version": int(state.get("version") or 0),
            "type": str(command_template.get("type") or ""),
            "payload": deepcopy(command_template.get("payload") or {}),
        }
        result = await self.enqueue_game_command(room_id=room_id, user=user, command=command)
        success_message = (
            "No legal bot actions or control takes remain. The game is lost."
            if command["type"] == "bot_no_actions_available"
            else decision.get("message")
        )
        return {
            **result,
            "status": "action_executed" if result.get("ok") else result.get("status"),
            "message": success_message if result.get("ok") else result.get("message"),
            "decision": public_decision,
        }

    async def enqueue_game_command(
        self,
        *,
        room_id: str,
        user: User,
        command: dict[str, Any],
    ) -> dict[str, Any]:
        if self.redis is not None and _env_bool("USE_DISTRIBUTED_GAME_RUNTIME", False):
            return await self._enqueue_distributed_command(room_id=room_id, user=user, command=command)
        return await self.apply_command(room_id=room_id, user=user, command=command)

    async def _enqueue_distributed_command(
        self,
        *,
        room_id: str,
        user: User,
        command: dict[str, Any],
    ) -> dict[str, Any]:
        command_id = str(command.get("command_id") or "").strip() or f"cmd_{uuid.uuid4().hex}"
        command = {**command, "command_id": command_id}
        result_key = _command_result_key(command_id)
        await self.redis.delete(result_key)
        await self.redis.xadd(
            _env_str("GAME_COMMAND_STREAM_KEY", COMMAND_STREAM_KEY),
            {
                "command_id": command_id,
                "room_id": room_id,
                "user": json.dumps(user.model_dump(), default=str, separators=(",", ":")),
                "command": json.dumps(command, default=str, separators=(",", ":")),
                "queued_at": _now_iso(),
            },
        )
        deadline = time.monotonic() + max(0.1, _env_float("GAME_COMMAND_RESULT_TIMEOUT_SECONDS", 8.0))
        poll_seconds = max(0.01, _env_float("GAME_COMMAND_RESULT_POLL_SECONDS", 0.05))
        while time.monotonic() < deadline:
            raw = await self.redis.get(result_key)
            if raw:
                if isinstance(raw, (bytes, bytearray)):
                    raw = raw.decode("utf-8", errors="ignore")
                try:
                    parsed = json.loads(str(raw))
                except (TypeError, json.JSONDecodeError):
                    parsed = None
                if isinstance(parsed, dict):
                    return parsed
            await asyncio.sleep(poll_seconds)
        projection = await self.get_projection(room_id=room_id, user=user)
        return {
            "ok": False,
            "status": "rejected",
            "command_id": command_id,
            "revision": int((projection or {}).get("version") or 0),
            "reason": "command_timeout",
            "message": "The game worker did not process the command in time.",
            "current_version": int((projection or {}).get("version") or 0),
            "projection": projection,
        }

    async def apply_command(self, *, room_id: str, user: User, command: dict[str, Any]) -> dict[str, Any]:
        room = await self._load_room(room_id)
        if not room or room.get("owner_user_id") != user.id:
            raise LookupError("Game room not found.")
        lock = self._room_locks.setdefault(room_id, asyncio.Lock())
        async with lock:
            state = await self._load_state(room_id)
            if state is None:
                raise LookupError("Game state not found.")
            state = self._state_with_latest_content_metadata(state)
            actor_seat_id = str(command.get("actor_seat_id") or "")
            if (
                room.get("mode") == "bots_only"
                and state.get("phase") != PHASE_SETUP
                and actor_seat_id != "bot_orchestrator"
            ):
                rejection = CommandRejection(
                    command_id=str(command.get("command_id") or ""),
                    reason="bots_only_room",
                    message="Only the bot orchestrator can perform game actions in this room.",
                    current_version=int(state.get("version") or 0),
                )
                return rejection.payload(_project_state(state))
            try:
                next_state, events = self._reduce(state, command, user=user, room_id=room_id, room=room)
            except CommandRejection as rejection:
                return rejection.payload(_project_state(state))
            if (
                next_state.get("phase") in {PHASE_NIGHT_IDLE, PHASE_NIGHT_ACTION}
                and _mark_game_lost_if_needed(next_state)
            ):
                loss_event = next_state.get("event_log", [])[-1]
                if not any(event.get("event_id") == loss_event.get("event_id") for event in events):
                    events = [*events, loss_event]
            if next_state["phase"] != PHASE_SETUP:
                room.update({"state": ROOM_STATE_IN_GAME, "started_at": room.get("started_at") or _now_iso()})
            if next_state.get("phase") == PHASE_FINISHED:
                result = self._result_from_state(room=room, state=next_state, user_id=user.id)
                room.update({"state": ROOM_STATE_FINISHED, "ended_at": result["created_at"], "result_id": room_id})
                await self._save_result(result)
            await self._save_room(room)
            await self._save_state(room_id, next_state)
            projection = _project_state(next_state)
        await self.broadcast_projection(room_id)
        return {
            "ok": True,
            "status": "accepted",
            "command_id": str(command.get("command_id") or ""),
            "revision": int(next_state["version"]),
            "version": int(next_state["version"]),
            "events": events,
            "projection": projection,
        }

    def _state_with_latest_content_metadata(self, state: dict[str, Any]) -> dict[str, Any]:
        if not state.get("tile_catalog"):
            return state
        next_state = deepcopy(state)
        try:
            latest_catalog = get_game_content_catalog()
            latest_tiles = latest_catalog.get("tiles") or {}
            latest_events = latest_catalog.get("events") or {}
            next_state.setdefault("tile_catalog", {})["tiles"] = {
                tile_id: _tile_public(tile, {"events": latest_events})
                for tile_id, tile in latest_tiles.items()
            } or next_state["tile_catalog"].get("tiles") or {}
            next_state.setdefault("tile_catalog", {})["categories"] = latest_catalog.get("categories") or next_state["tile_catalog"].get("categories") or {}
            next_state.setdefault("tile_catalog", {})["events"] = latest_events or next_state["tile_catalog"].get("events") or {}
            next_state.setdefault("tile_catalog", {})["interactions"] = latest_catalog.get("interactions") or next_state["tile_catalog"].get("interactions") or {}
            next_state.setdefault("tile_catalog", {})["cards"] = latest_catalog.get("cards") or next_state["tile_catalog"].get("cards") or {}
            next_state.setdefault("tile_catalog", {})["tokens"] = latest_catalog.get("tokens") or next_state["tile_catalog"].get("tokens") or {}
            next_state.setdefault("tile_catalog", {})["poulpita_panel"] = latest_catalog.get("poulpita_panel") or next_state["tile_catalog"].get("poulpita_panel") or {}
            next_state.setdefault("tile_catalog", {})["surprise_cards"] = latest_catalog.get("surprise_cards") or next_state["tile_catalog"].get("surprise_cards") or {}
            next_state.setdefault("tile_catalog", {})["surprise_decks"] = latest_catalog.get("surprise_decks") or next_state["tile_catalog"].get("surprise_decks") or {}
            next_state.setdefault("tile_catalog", {})["action_costs"] = latest_catalog.get("action_costs") or next_state["tile_catalog"].get("action_costs") or {}
            next_state.setdefault("tile_catalog", {})["bot_settings"] = latest_catalog.get("bot_settings") or next_state["tile_catalog"].get("bot_settings") or {}
            _ensure_octopus_tile_catalog(next_state["tile_catalog"])
        except Exception:
            return state
        return next_state

    def _result_from_state(self, *, room: dict[str, Any], state: dict[str, Any], user_id: str) -> dict[str, Any]:
        now = _now_iso()
        outcome = str(state.get("game_outcome") or "completed")
        reason = str(state.get("game_over_reason") or "")
        summary = "Goldfish prototype room ended."
        if outcome == "lost":
            summary = "Poulpita lost the night."
            if reason == "poulpita_no_energy":
                summary = "Poulpita lost all energy."
            elif reason == "no_controls_or_actions":
                summary = "No controls or actions remained."
        elif outcome == "won":
            summary = "Poulpita completed all level objectives."
        return {
            "id": room.get("id", state.get("room_id", "")),
            "room_id": room.get("id", state.get("room_id", "")),
            "user_id": user_id,
            "mode": room.get("mode", "goldfish"),
            "game_type": room.get("game_type", "goldfish"),
            "outcome": outcome,
            "score": "0",
            "turns": str(max(0, int(state.get("version") or 0) - 1)),
            "duration_seconds": str(max(1, int(time.time() - _iso_to_epoch(room.get("started_at") or room.get("created_at"))))),
            "summary": summary,
            "created_at": now,
        }

    def _reject(self, state: dict[str, Any], command_id: str, reason: str, message: str) -> None:
        raise CommandRejection(
            command_id=command_id,
            reason=reason,
            message=message,
            current_version=int(state.get("version") or 0),
        )

    def _reduce(
        self,
        state: dict[str, Any],
        command: dict[str, Any],
        *,
        user: User,
        room_id: str,
        room: dict[str, Any],
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        command_id = str(command.get("command_id") or "").strip() or f"cmd_{uuid.uuid4().hex}"
        command_type = str(command.get("type") or "").strip()
        expected_version = command.get("expected_version")
        if expected_version is None:
            expected_version = command.get("expected_revision")
        if expected_version is not None:
            try:
                normalized_expected_version = int(expected_version)
            except (TypeError, ValueError):
                self._reject(state, command_id, "invalid_expected_version", "expected_version must be an integer.")
            if normalized_expected_version != int(state["version"]):
                self._reject(
                    state,
                    command_id,
                    "state_version_conflict",
                    "The room has already advanced. Refresh the board and try again.",
                )
        if command.get("room_id") and str(command.get("room_id")) != room_id:
            self._reject(state, command_id, "room_mismatch", "Command room_id does not match the URL room.")
        if command.get("actor_user_id") and str(command.get("actor_user_id")) != user.id:
            self._reject(state, command_id, "actor_mismatch", "Command actor does not match the authenticated user.")

        if command_type == "start_goldfish_game":
            if state["phase"] != PHASE_SETUP:
                self._reject(state, command_id, "game_already_started", "This goldfish game has already started.")
            next_state = _goldfish_state(
                room_id,
                level_id=room.get("level_id") or state.get("selected_level_id"),
                mode=str(room.get("mode") or state.get("mode") or "goldfish"),
                bot_config=deepcopy(room.get("bot_config") or state.get("bot_config")),
            )
            event = next_state["event_log"][0]
            return next_state, [event]

        if command_type == "select_level":
            if state["phase"] != PHASE_SETUP:
                self._reject(state, command_id, "game_already_started", "Level can be changed only before the game starts.")
            payload = command.get("payload") or {}
            if not isinstance(payload, dict):
                self._reject(state, command_id, "invalid_payload", "Command payload must be an object.")
            level_id = str(payload.get("level_id") or "")
            try:
                level_config = get_level_config(level_id)
                map_config = get_map(level_config["map_id"])
                _validate_map_config(map_config)
            except (LookupError, ValueError):
                self._reject(state, command_id, "unknown_level", "Selected level does not exist or is invalid.")
            next_state = deepcopy(state)
            next_state["version"] = int(state["version"]) + 1
            next_state["level_id"] = level_config["id"]
            next_state["selected_level_id"] = level_config["id"]
            next_state["selected_map_id"] = map_config["id"]
            next_state["night_time_total"] = max(1, int(level_config.get("night_duration_steps") or NIGHT_OVERRUN_CHUNKS))
            next_state["map"] = _map_projection(map_config)
            room["map_id"] = map_config["id"]
            room["level_id"] = level_config["id"]
            event = {
                "event_id": f"evt_{uuid.uuid4().hex}",
                "type": "level_selected",
                "command_id": command_id,
                "level_id": level_config["id"],
                "map_id": map_config["id"],
                "version": int(next_state["version"]),
                "created_at": _now_iso(),
            }
            next_state.setdefault("event_log", []).append(event)
            return next_state, [event]

        if command_type == "bot_no_actions_available":
            if room.get("mode") != "bots_only" or str(command.get("actor_seat_id") or "") != "bot_orchestrator":
                self._reject(
                    state,
                    command_id,
                    "invalid_orchestrator_command",
                    "Only the bot orchestrator can finish a bots-only game with no available actions.",
                )
            if state.get("phase") not in {PHASE_NIGHT_IDLE, PHASE_NIGHT_ACTION}:
                self._reject(state, command_id, "phase_not_night", "This dead-end check applies only during the night.")
            # Planner viability is advisory. An unscored board position must not
            # become an authoritative loss while another control take remains.
            if not _no_other_control_takes_available(state) or (
                not _active_capability_is_out_of_actions(state)
                and has_executable_bot_orchestrator_action(state)
            ):
                self._reject(
                    state,
                    command_id,
                    "bot_actions_still_available",
                    "At least one ability can still act or take control.",
                )
            next_state = deepcopy(state)
            next_state["version"] = int(state["version"]) + 1
            _mark_game_lost_if_needed(next_state, reason="no_controls_or_actions")
            event = next_state["event_log"][-1]
            event["command_id"] = command_id
            event["version"] = int(next_state["version"])
            return next_state, [event]

        if command_type == "move_poulpita":
            if state["phase"] != PHASE_NIGHT_ACTION:
                self._reject(state, command_id, "phase_not_movable", "Take control before moving Poulpita.")
            payload = command.get("payload") or {}
            if not isinstance(payload, dict):
                self._reject(state, command_id, "invalid_payload", "Command payload must be an object.")
            capability_id = str(payload.get("capability_id") or "")
            target_node_id = str(payload.get("target_node_id") or "")
            action_cost = _configured_action_cost(state, "move")
            _require_active_action(self, state, command_id, capability_id, ap_cost=action_cost["ap_cost"], neuron_cost=action_cost["neuron_cost"])
            nodes = state["map"]["nodes"]
            if target_node_id not in nodes:
                self._reject(state, command_id, "unknown_target_node", "Target node does not exist.")
            current_node_id = str(state["poulpita"]["node_id"])
            active_interaction = state.get("interaction") or {}
            if active_interaction and not active_interaction.get("courtship_card"):
                self._reject(state, command_id, "interaction_in_progress", "Resolve the active interaction before moving.")
            if _compulsory_tile_choices(state, current_node_id):
                self._reject(state, command_id, "compulsory_interaction_blocks_move", "Resolve compulsory interactions before moving.")
            if target_node_id not in (state["map"]["adjacency"].get(current_node_id) or []):
                self._reject(state, command_id, "non_adjacent_node", "Poulpita can move only to an adjacent node.")
            next_state = deepcopy(state)
            if (next_state.get("interaction") or {}).get("courtship_card"):
                for played_card in next_state["interaction"].get("played_cards") or []:
                    owner = (next_state.get("capabilities") or {}).get(played_card.get("capability_id"))
                    if owner is not None:
                        owner.setdefault("discard", []).append(deepcopy(played_card))
                next_state["interaction"] = None
            next_state["version"] = int(state["version"]) + 1
            next_state["poulpita"]["previous_node_id"] = current_node_id
            next_state["poulpita"]["node_id"] = target_node_id
            next_state["courtship_blocked_node_id"] = None
            _spend_action(next_state, capability_id, ap_cost=action_cost["ap_cost"], time_cost=action_cost["time_cost"], neuron_cost=action_cost["neuron_cost"])
            _apply_tile_visibility(next_state)
            _maybe_start_courtship_interaction(next_state)
            if _has_shelter(next_state, target_node_id):
                _record_shelter_arrival(next_state, target_node_id)
                _mark_game_won_if_needed(next_state)
            _mark_game_lost_if_needed(next_state)
            event = {
                "event_id": f"evt_{uuid.uuid4().hex}",
                "type": "poulpita_moved",
                "command_id": command_id,
                "from_node_id": current_node_id,
                "to_node_id": target_node_id,
                "version": int(next_state["version"]),
                "created_at": _now_iso(),
            }
            next_state.setdefault("event_log", []).append(event)
            return next_state, [event]

        if command_type == "take_control":
            if state["phase"] not in {PHASE_NIGHT_IDLE, PHASE_NIGHT_ACTION}:
                self._reject(state, command_id, "phase_not_controllable", "Control can be taken only during the night.")
            payload = command.get("payload") or {}
            if not isinstance(payload, dict):
                self._reject(state, command_id, "invalid_payload", "Command payload must be an object.")
            capability_id = str(payload.get("capability_id") or "")
            capabilities = state.get("capabilities") or {}
            capability = capabilities.get(capability_id)
            if capability is None:
                self._reject(state, command_id, "unknown_capability", "Unknown capability.")
            if capability_id == state.get("active_capability_id"):
                self._reject(state, command_id, "already_active_capability", "This capability already controls Poulpita.")
            if int(capability.get("control_takes_this_night") or 0) >= int(capability.get("max_control_takes_per_night") or 3):
                self._reject(state, command_id, "control_limit_reached", "This capability has already taken control 3 times tonight.")
            next_state = deepcopy(state)
            previous_active = next_state.get("active_capability_id")
            if previous_active:
                next_state["last_active_capability_id"] = previous_active
            next_state["active_capability_id"] = capability_id
            next_state["focused_capability_id"] = capability_id
            next_state["phase"] = PHASE_NIGHT_ACTION
            next_state["version"] = int(state["version"]) + 1
            next_capability = next_state["capabilities"][capability_id]
            next_capability["control_takes_this_night"] = int(next_capability.get("control_takes_this_night") or 0) + 1
            next_capability["actions_taken_this_control"] = 0
            if int(next_state.get("night_time_spent") or 0) >= max(1, int(next_state.get("night_time_total") or NIGHT_OVERRUN_CHUNKS)):
                _damage_poulpita(next_state, amount=1, reason="late_control_taken")
                if int((next_state.get("poulpita") or {}).get("energy") or 0) <= 0:
                    _mark_game_lost_if_needed(next_state, reason="poulpita_no_energy")
            event = {
                "event_id": f"evt_{uuid.uuid4().hex}",
                "type": "control_taken",
                "command_id": command_id,
                "capability_id": capability_id,
                "previous_active_capability_id": previous_active,
                "version": int(next_state["version"]),
                "created_at": _now_iso(),
            }
            next_state.setdefault("event_log", []).append(event)
            events = [event]
            if _maybe_start_courtship_interaction(next_state):
                events.append(next_state["event_log"][-1])
            return next_state, events

        if command_type == "end_night":
            if state["phase"] != PHASE_NIGHT_ACTION:
                self._reject(state, command_id, "phase_not_night", "Night can be ended only while a player has control.")
            payload = command.get("payload") or {}
            if not isinstance(payload, dict):
                self._reject(state, command_id, "invalid_payload", "Command payload must be an object.")
            capability_id = str(payload.get("capability_id") or "")
            _require_active_control(self, state, command_id, capability_id)
            current_node_id = str(state.get("poulpita", {}).get("node_id") or "")
            if not _has_shelter(state, current_node_id):
                self._reject(state, command_id, "no_shelter_here", "Poulpita must be on a shelter token to end the night.")
            if int(state.get("night_time_spent") or 0) < NIGHT_SHELTER_AVAILABLE_CHUNKS:
                self._reject(state, command_id, "too_early_to_end_night", "At least 4 hours must pass before ending the night.")
            if _night_end_blockers(state, current_node_id):
                self._reject(
                    state,
                    command_id,
                    "night_end_blocked",
                    "Resolve every compulsory tile and octopus token on this node before ending the night.",
                )
            next_state = deepcopy(state)
            next_state["phase"] = PHASE_DAY
            next_state["last_active_capability_id"] = capability_id
            _reset_night_runtime(next_state)
            next_state["version"] = int(state["version"]) + 1
            event = {
                "event_id": f"evt_{uuid.uuid4().hex}",
                "type": "day_started",
                "command_id": command_id,
                "capability_id": capability_id,
                "version": int(next_state["version"]),
                "created_at": _now_iso(),
            }
            next_state.setdefault("event_log", []).append(event)
            return next_state, [event]

        if command_type in {"move_seashell_to_shelter", "move_seashell_from_shelter"}:
            if state["phase"] != PHASE_DAY:
                self._reject(state, command_id, "phase_not_day", "Shells can be moved to shelters only during the day.")
            current_node_id = str((state.get("poulpita") or {}).get("node_id") or "")
            if not _has_shelter(state, current_node_id):
                self._reject(state, command_id, "no_shelter_here", "Poulpita must be on a shelter.")
            next_state = deepcopy(state)
            shelter = _ensure_shelter_entry(next_state, current_node_id)
            poulpita = next_state.setdefault("poulpita", {})
            if command_type == "move_seashell_to_shelter":
                if int(poulpita.get("seashells") or 0) <= 0:
                    self._reject(state, command_id, "no_poulpita_shells", "Poulpita has no seashells to store.")
                previous_shells = int(shelter.get("seashells") or 0)
                poulpita["seashells"] = int(poulpita.get("seashells") or 0) - 1
                shelter["seashells"] = previous_shells + 1
                if previous_shells < 3 <= int(shelter.get("seashells") or 0):
                    next_state.setdefault("objective_progress", {})["secured_shelter"] = True
                event_type = "seashell_moved_to_shelter"
            else:
                if int(shelter.get("seashells") or 0) <= 0:
                    self._reject(state, command_id, "no_shelter_shells", "This shelter has no seashells.")
                shelter["seashells"] = int(shelter.get("seashells") or 0) - 1
                poulpita["seashells"] = int(poulpita.get("seashells") or 0) + 1
                event_type = "seashell_moved_to_poulpita"
            shelter["secure"] = int(shelter.get("seashells") or 0) >= 3
            next_state["version"] = int(state["version"]) + 1
            _mark_game_won_if_needed(next_state)
            event = {
                "event_id": f"evt_{uuid.uuid4().hex}",
                "type": event_type,
                "command_id": command_id,
                "node_id": current_node_id,
                "shelter_seashells": int(shelter.get("seashells") or 0),
                "version": int(next_state["version"]),
                "created_at": _now_iso(),
            }
            next_state.setdefault("event_log", []).append(event)
            return next_state, [event]

        if command_type == "buy_hand_size_upgrade":
            if state["phase"] != PHASE_DAY:
                self._reject(state, command_id, "phase_not_day", "Upgrades can be bought only during the day.")
            payload = command.get("payload") or {}
            if not isinstance(payload, dict):
                self._reject(state, command_id, "invalid_payload", "Command payload must be an object.")
            capability_id = str(payload.get("capability_id") or "")
            upgrade_index = int(payload.get("upgrade_index") or 0)
            capability = (state.get("capabilities") or {}).get(capability_id)
            if capability is None:
                self._reject(state, command_id, "unknown_capability", "Unknown capability.")
            upgrades = capability.get("hand_size_upgrades") or []
            if upgrade_index < 0 or upgrade_index >= len(upgrades):
                self._reject(state, command_id, "unknown_upgrade", "Unknown hand size upgrade.")
            purchased = {int(index) for index in (capability.get("purchased_hand_size_upgrade_indices") or [])}
            if upgrade_index in purchased:
                self._reject(state, command_id, "upgrade_already_bought", "This upgrade was already bought.")
            upgrade = upgrades[upgrade_index] or {}
            upgrade_type = str(upgrade.get("type") or "hand_size")
            if str(upgrade.get("cost_resource") or "neurons") != "neurons":
                self._reject(state, command_id, "unsupported_upgrade_cost", "Only neuron upgrades can be bought during the day.")
            cost = max(0, int(upgrade.get("cost") or 0))
            if int((state.get("poulpita") or {}).get("neurons") or 0) < cost:
                self._reject(state, command_id, "insufficient_neurons", "Poulpita does not have enough neurons.")
            next_state = deepcopy(state)
            next_capability = next_state["capabilities"][capability_id]
            bonus = 0
            try:
                if upgrade_type == "deck_exchange":
                    _apply_deck_exchange_upgrade(next_capability, upgrade)
                    next_capability.setdefault("applied_deck_exchange_upgrade_indices", []).append(upgrade_index)
                else:
                    bonus = max(1, int(upgrade.get("hand_size_bonus") or 1))
                    next_capability["current_max_cards_in_hand"] = int(next_capability.get("current_max_cards_in_hand") or next_capability.get("default_max_cards_in_hand") or 3) + bonus
            except ValueError as exc:
                self._reject(state, command_id, "upgrade_requirements_not_met", str(exc))
            next_state["poulpita"]["neurons"] = int(next_state["poulpita"].get("neurons") or 0) - cost
            next_capability.setdefault("purchased_hand_size_upgrade_indices", []).append(upgrade_index)
            next_state["focused_capability_id"] = capability_id
            next_state["version"] = int(state["version"]) + 1
            event = {
                "event_id": f"evt_{uuid.uuid4().hex}",
                "type": "deck_exchange_upgrade_bought" if upgrade_type == "deck_exchange" else "hand_size_upgrade_bought",
                "command_id": command_id,
                "capability_id": capability_id,
                "upgrade_index": upgrade_index,
                "cost": cost,
                "hand_size_bonus": bonus,
                "version": int(next_state["version"]),
                "created_at": _now_iso(),
            }
            next_state.setdefault("event_log", []).append(event)
            return next_state, [event]

        if command_type == "buy_poulpita_size":
            if state["phase"] != PHASE_DAY:
                self._reject(state, command_id, "phase_not_day", "Poulpita can grow only during the day.")
            poulpita = state.get("poulpita") or {}
            if poulpita.get("size_upgraded_today"):
                self._reject(state, command_id, "size_already_upgraded_today", "Poulpita can grow only once per day.")
            sizes = ((state.get("tile_catalog") or {}).get("poulpita_panel") or {}).get("sizes") or [{"kg": 1.0, "energy_cost": 0}]
            current_size_index = max(0, int(poulpita.get("size_index") or 0))
            next_size_index = current_size_index + 1
            if next_size_index >= len(sizes):
                self._reject(state, command_id, "max_size_reached", "Poulpita is already at the maximum configured size.")
            next_size = sizes[next_size_index] or {}
            base_cost = max(1, int(next_size.get("energy_cost") or 1))
            shelter_shells = int(_shelter_entry(state, (state.get("poulpita") or {}).get("node_id")).get("seashells") or 0)
            cost = max(0, base_cost - max(0, shelter_shells - 2))
            current_energy = int(poulpita.get("energy") or 0)
            if cost > 0 and current_energy - cost <= 0:
                self._reject(state, command_id, "insufficient_energy", "Poulpita must have enough energy and cannot spend down to 0.")
            next_state = deepcopy(state)
            next_state["poulpita"]["energy"] = current_energy - cost
            next_state["poulpita"]["size_index"] = next_size_index
            next_state["poulpita"]["size_upgraded_today"] = True
            next_state["version"] = int(state["version"]) + 1
            next_state.setdefault("objective_progress", {})["size_increases"] = int((next_state.get("objective_progress") or {}).get("size_increases") or 0) + 1
            _replace_tiles_for_size(next_state, next_size_index)
            _mark_game_won_if_needed(next_state)
            event = {
                "event_id": f"evt_{uuid.uuid4().hex}",
                "type": "poulpita_size_increased",
                "command_id": command_id,
                "size_index": next_size_index,
                "amount": float(next_size.get("amount") or next_size.get("kg") or 0),
                "unit": str(next_size.get("unit") or "kg"),
                "energy_cost": cost,
                "version": int(next_state["version"]),
                "created_at": _now_iso(),
            }
            next_state.setdefault("event_log", []).append(event)
            return next_state, [event]

        if command_type == "resolve_surprise_card":
            pending_surprise = state.get("pending_surprise")
            if not pending_surprise:
                self._reject(state, command_id, "no_pending_surprise", "No surprise card is waiting to be resolved.")
            payload = command.get("payload") or {}
            if payload and not isinstance(payload, dict):
                self._reject(state, command_id, "invalid_payload", "Command payload must be an object.")
            accept = bool(payload.get("accept"))
            capability_id = str(payload.get("capability_id") or "")
            selected_card_ids = [str(card_id) for card_id in (payload.get("card_ids") or [])]
            card = pending_surprise.get("card") or {}
            costs = card.get("costs") or []
            if payload.get("auto_select_cards") and capability_id:
                capability = (state.get("capabilities") or {}).get(capability_id) or {}
                selected_card_ids = _auto_selected_surprise_card_ids(capability, costs)
            next_state = deepcopy(state)
            paid = False
            if not costs:
                paid = True
            elif accept:
                paid = True
                for cost in costs:
                    cost_type = str(cost.get("type") or "")
                    if cost_type == "play_cards":
                        capability = (next_state.get("capabilities") or {}).get(capability_id)
                        if capability is None:
                            self._reject(state, command_id, "unknown_capability", "Choose an ability to play cards.")
                        remaining = list(cost.get("interaction_ids") or [])
                        selected = set(selected_card_ids)
                        next_hand = []
                        played = []
                        for hand_card in capability.get("hand") or []:
                            if hand_card.get("card_id") in selected:
                                matching_interaction_id = next((interaction_id for interaction_id in _card_interaction_options(hand_card) if interaction_id in remaining), "")
                                if matching_interaction_id:
                                    remaining.remove(matching_interaction_id)
                                    played.append({**hand_card, "interaction_id": matching_interaction_id, "interaction_ids": _card_interaction_options(hand_card)})
                                else:
                                    next_hand.append(hand_card)
                            else:
                                next_hand.append(hand_card)
                        if remaining:
                            self._reject(state, command_id, "surprise_cost_not_paid", "Selected cards do not satisfy the surprise cost.")
                        capability["hand"] = next_hand
                        capability.setdefault("discard", []).extend(played)
                    elif cost_type == "pay_ap":
                        payer_id = str(cost.get("capability_id") or capability_id)
                        capability = (next_state.get("capabilities") or {}).get(payer_id)
                        amount = max(1, int(cost.get("amount") or 1))
                        if capability is None:
                            self._reject(state, command_id, "unknown_capability", "Unknown AP payer.")
                        if int(capability.get("pa") or 0) < amount:
                            self._reject(state, command_id, "insufficient_pa", "This surprise cost needs more AP.")
                        capability["pa"] = int(capability.get("pa") or 0) - amount
            if paid:
                _apply_surprise_effects(next_state, card.get("effects") or [])
            next_state["pending_surprise"] = None
            next_state["version"] = int(state["version"]) + 1
            _mark_game_won_if_needed(next_state)
            event = {
                "event_id": f"evt_{uuid.uuid4().hex}",
                "type": "surprise_card_resolved" if paid else "surprise_card_skipped",
                "command_id": command_id,
                "surprise_card_id": card.get("id"),
                "paid": paid,
                "version": int(next_state["version"]),
                "created_at": _now_iso(),
            }
            next_state.setdefault("event_log", []).append(event)
            return next_state, [event]

        if command_type == "end_day":
            if state["phase"] != PHASE_DAY:
                self._reject(state, command_id, "phase_not_day", "Day can be ended only during the day.")
            next_state = deepcopy(state)
            if int(state.get("day_index") or 1) >= int(state.get("max_nights") or 5):
                next_state["version"] = int(state["version"]) + 1
                _mark_game_lost_if_needed(next_state, reason="maximum_nights_reached")
                event = next_state["event_log"][-1]
                event["command_id"] = command_id
                event["version"] = int(next_state["version"])
                return next_state, [event]
            next_state["phase"] = PHASE_NIGHT_IDLE
            next_state["day_index"] = int(state.get("day_index") or 1) + 1
            next_state["night_time_spent"] = 0
            next_state["active_capability_id"] = None
            next_state["last_active_capability_id"] = None
            next_state.setdefault("poulpita", {})["size_upgraded_today"] = False
            for capability in (next_state.get("capabilities") or {}).values():
                capability["control_takes_this_night"] = 0
                capability["actions_taken_this_control"] = 0
                initial_ap = capability.get("initial_ap")
                capability["pa"] = max(0, int(initial_ap if initial_ap is not None else 5))
                _apply_unmigrated_deck_exchange_upgrades(capability)
                _reshuffle_and_deal_starting_hand(capability)
            next_state["version"] = int(state["version"]) + 1
            event = {
                "event_id": f"evt_{uuid.uuid4().hex}",
                "type": "night_started",
                "command_id": command_id,
                "day_index": int(next_state["day_index"]),
                "version": int(next_state["version"]),
                "created_at": _now_iso(),
            }
            next_state.setdefault("event_log", []).append(event)
            return next_state, [event]

        if command_type == "use_special_power":
            payload = command.get("payload") or {}
            if not isinstance(payload, dict):
                self._reject(state, command_id, "invalid_payload", "Command payload must be an object.")
            capability_id = str(payload.get("capability_id") or "")
            action_cost = _configured_action_cost(state, "special_power")
            _require_active_action(
                self,
                state,
                command_id,
                capability_id,
                ap_cost=action_cost["ap_cost"],
                neuron_cost=action_cost["neuron_cost"],
            )
            next_state = deepcopy(state)
            current_node_id = str((state.get("poulpita") or {}).get("node_id") or "")
            adjacency = (state.get("map") or {}).get("adjacency") or {}
            details: dict[str, Any] = {}
            if capability_id == "intelligence":
                tile_instance_id = str(payload.get("tile_instance_id") or "")
                node_id, tile_instance = _find_tile_instance(next_state, tile_instance_id)
                if not tile_instance or str(node_id) not in [str(value) for value in adjacency.get(current_node_id, []) or []]:
                    self._reject(state, command_id, "invalid_reveal_target", "Choose a hidden tile on an adjacent node.")
                if tile_instance.get("face_up"):
                    self._reject(state, command_id, "tile_already_revealed", "This tile is already revealed.")
                tile_instance["face_up"] = True
                details = {"tile_instance_id": tile_instance_id, "node_id": node_id}
            elif capability_id == "agility":
                drawn_by: list[str] = []
                for target_id, target in (next_state.get("capabilities") or {}).items():
                    _refill_draw_pile_from_discard(target)
                    if target.get("draw_pile"):
                        target.setdefault("hand", []).append(target["draw_pile"].pop(0))
                        drawn_by.append(str(target_id))
                details = {"drawn_by": drawn_by}
            elif capability_id == "propulsion":
                path = [str(node_id) for node_id in (payload.get("path") or [])]
                if len(path) != 2 or path[0] not in (adjacency.get(current_node_id) or []) or path[1] not in (adjacency.get(path[0]) or []):
                    self._reject(state, command_id, "invalid_propulsion_path", "Propulsion must follow exactly two connected edges.")
                if path[1] == str(state.get("poulpita_starting_node_id") or ""):
                    self._reject(state, command_id, "propulsion_starting_node_forbidden", "Propulsion cannot return Poulpita to the level starting node.")
                next_state["poulpita"]["previous_node_id"] = current_node_id
                next_state["poulpita"]["node_id"] = path[0]
                _apply_tile_visibility(next_state)
                next_state["poulpita"]["node_id"] = path[1]
                next_state["courtship_blocked_node_id"] = None
                _apply_tile_visibility(next_state)
                details = {"path": path}
            elif capability_id == "force":
                next_state["force_reduces_next_interaction"] = True
            elif capability_id == "camouflage":
                target_node_id = str(payload.get("target_node_id") or "")
                if target_node_id not in (adjacency.get(current_node_id) or []):
                    self._reject(state, command_id, "non_adjacent_node", "Camouflage must move to an adjacent node.")
                next_state["poulpita"]["previous_node_id"] = current_node_id
                next_state["poulpita"]["node_id"] = target_node_id
                next_state["courtship_blocked_node_id"] = None
                _apply_tile_visibility(next_state)
                details = {"target_node_id": target_node_id}
            else:
                self._reject(state, command_id, "unknown_special_power", "This ability has no special power.")
            _spend_action(
                next_state,
                capability_id,
                ap_cost=action_cost["ap_cost"],
                time_cost=action_cost["time_cost"],
                neuron_cost=action_cost["neuron_cost"],
            )
            next_state["version"] = int(state["version"]) + 1
            _maybe_start_courtship_interaction(next_state)
            destination_node_id = str((next_state.get("poulpita") or {}).get("node_id") or "")
            if _has_shelter(next_state, destination_node_id):
                _record_shelter_arrival(next_state, destination_node_id)
                _mark_game_won_if_needed(next_state)
            _mark_game_lost_if_needed(next_state)
            event = {
                "event_id": f"evt_{uuid.uuid4().hex}",
                "type": "special_power_used",
                "command_id": command_id,
                "capability_id": capability_id,
                **details,
                "version": int(next_state["version"]),
                "created_at": _now_iso(),
            }
            next_state.setdefault("event_log", []).append(event)
            if (
                int(next_state.get("day_index") or 1) >= int(next_state.get("size_deadline_night") or 4)
                and int((next_state.get("poulpita") or {}).get("size_index") or 0) < int(next_state.get("courtship_min_size_index") if next_state.get("courtship_min_size_index") is not None else 3)
            ):
                _mark_game_lost_if_needed(next_state, reason="size_deadline_missed")
                loss_event = next_state["event_log"][-1]
                loss_event["command_id"] = command_id
                loss_event["version"] = int(next_state["version"])
                return next_state, [event, loss_event]
            return next_state, [event]

        if command_type == "collect_action_points":
            payload = command.get("payload") or {}
            if not isinstance(payload, dict):
                self._reject(state, command_id, "invalid_payload", "Command payload must be an object.")
            capability_id = str(payload.get("capability_id") or "")
            action_cost = _configured_action_cost(state, "gain_ap")
            _require_active_action(self, state, command_id, capability_id, ap_cost=action_cost["ap_cost"], neuron_cost=action_cost["neuron_cost"])
            die_sides = _configured_ap_die_sides(state)
            amount = random.choice(die_sides)
            next_state = deepcopy(state)
            next_state["version"] = int(state["version"]) + 1
            next_capability = next_state["capabilities"][capability_id]
            next_capability["pa"] = int(next_capability.get("pa") or 0) + amount
            _spend_action(next_state, capability_id, ap_cost=action_cost["ap_cost"], time_cost=action_cost["time_cost"], neuron_cost=action_cost["neuron_cost"])
            _mark_game_lost_if_needed(next_state)
            event = {
                "event_id": f"evt_{uuid.uuid4().hex}",
                "type": "action_points_collected",
                "command_id": command_id,
                "capability_id": capability_id,
                "amount": amount,
                "die_sides": die_sides,
                "version": int(next_state["version"]),
                "created_at": _now_iso(),
            }
            next_state.setdefault("event_log", []).append(event)
            return next_state, [event]

        if command_type == "draw_action_card":
            payload = command.get("payload") or {}
            if not isinstance(payload, dict):
                self._reject(state, command_id, "invalid_payload", "Command payload must be an object.")
            capability_id = str(payload.get("capability_id") or "")
            action_cost = _configured_action_cost(state, "draw")
            capability = _require_active_action(self, state, command_id, capability_id, ap_cost=action_cost["ap_cost"], neuron_cost=action_cost["neuron_cost"])
            discard_card_id = str(payload.get("discard_card_id") or "").strip()
            hand = capability.get("hand") or []
            hand_limit = int(capability.get("current_max_cards_in_hand") or 3)
            if len(hand) >= hand_limit and not discard_card_id and payload.get("auto_discard_card"):
                discard_card_id = _auto_discard_card_id_for_draw(state, capability)
            if len(hand) >= hand_limit and not discard_card_id:
                self._reject(state, command_id, "discard_required", "Choose a card to discard before drawing.")
            if discard_card_id and not any(card.get("card_id") == discard_card_id for card in hand):
                self._reject(state, command_id, "unknown_discard_card", "Discarded card must be in this ability hand.")
            if not (capability.get("draw_pile") or capability.get("discard") or discard_card_id):
                self._reject(state, command_id, "empty_deck", "This ability has no cards left to draw.")
            next_state = deepcopy(state)
            next_capability = next_state["capabilities"][capability_id]
            discarded_card = None
            if discard_card_id:
                next_hand = []
                for hand_card in next_capability.get("hand") or []:
                    if hand_card.get("card_id") == discard_card_id:
                        discarded_card = hand_card
                    else:
                        next_hand.append(hand_card)
                next_capability["hand"] = next_hand
                if discarded_card:
                    next_capability.setdefault("discard", []).append(discarded_card)
            _refill_draw_pile_from_discard(next_capability)
            if not (next_capability.get("draw_pile") or []):
                self._reject(state, command_id, "empty_deck", "This ability has no cards left to draw.")
            card = next_capability["draw_pile"].pop(0)
            next_capability.setdefault("hand", []).append(card)
            _refill_draw_pile_from_discard(next_capability)
            _spend_action(next_state, capability_id, ap_cost=action_cost["ap_cost"], time_cost=action_cost["time_cost"], neuron_cost=action_cost["neuron_cost"])
            next_state["version"] = int(state["version"]) + 1
            _mark_game_lost_if_needed(next_state)
            event = {
                "event_id": f"evt_{uuid.uuid4().hex}",
                "type": "action_card_drawn",
                "command_id": command_id,
                "capability_id": capability_id,
                "interaction_id": card.get("interaction_id"),
                "discarded_card_id": discard_card_id or None,
                "version": int(next_state["version"]),
                "created_at": _now_iso(),
            }
            next_state.setdefault("event_log", []).append(event)
            return next_state, [event]

        if command_type == "start_interaction":
            payload = command.get("payload") or {}
            if not isinstance(payload, dict):
                self._reject(state, command_id, "invalid_payload", "Command payload must be an object.")
            capability_id = str(payload.get("capability_id") or "")
            tile_instance_id = str(payload.get("tile_instance_id") or "")
            selected_card_ids = [str(card_id) for card_id in (payload.get("card_ids") or [])]
            action_cost = _configured_action_cost(state, "interact")
            if state.get("interaction"):
                self._reject(state, command_id, "interaction_already_active", "Resolve or fail the current interaction first.")
            node_id, tile_instance = _find_tile_instance(state, tile_instance_id)
            if not tile_instance:
                self._reject(state, command_id, "unknown_tile", "Tile not found.")
            if node_id != state.get("poulpita", {}).get("node_id"):
                self._reject(state, command_id, "tile_not_on_poulpita_node", "Poulpita must be on the tile node.")
            if not tile_instance.get("face_up"):
                self._reject(state, command_id, "tile_face_down", "This tile is not revealed yet.")
            tile_catalog = state.get("tile_catalog") if isinstance(state.get("tile_catalog"), dict) else {}
            is_octopus_instance = _is_octopus_tile_instance(tile_instance)
            if is_octopus_instance:
                _ensure_octopus_tile_catalog(tile_catalog)
            lookup_tile_id = OCTOPUS_TILE_ID if is_octopus_instance else tile_instance.get("tile_id")
            tile = (tile_catalog.get("tiles") or {}).get(lookup_tile_id)
            if not tile:
                self._reject(state, command_id, "unknown_tile", "Tile definition not found.")
            is_courtship_instance = str(tile_instance.get("token_type") or "") == COURTSHIP_TOKEN_ID
            courtship_card = None
            if is_courtship_instance:
                _require_active_control(self, state, command_id, capability_id)
                if _compulsory_tile_choices(state, str(node_id)):
                    self._reject(state, command_id, "courtship_blocked_by_threat", "Resolve compulsory threats before courtship.")
                if int((state.get("poulpita") or {}).get("size_index") or 0) < int(state.get("courtship_min_size_index") if state.get("courtship_min_size_index") is not None else 3):
                    self._reject(state, command_id, "courtship_size_too_small", "Poulpita has not reached the required courtship size.")
                if int((state.get("poulpita") or {}).get("energy") or 0) < int(state.get("courtship_min_energy") or 8):
                    self._reject(state, command_id, "courtship_energy_too_low", "Poulpita does not have enough energy for courtship.")
                if str(state.get("courtship_blocked_node_id") or "") == str(node_id):
                    self._reject(state, command_id, "courtship_requires_movement", "Move away before attempting courtship again.")
                courtship_cards = list(((state.get("tile_catalog") or {}).get("courtship_cards") or {}).values())
                if not courtship_cards:
                    self._reject(state, command_id, "courtship_deck_empty", "No courtship cards are configured.")
                courtship_card = deepcopy(random.choice(courtship_cards))
            else:
                _require_active_action(self, state, command_id, capability_id, ap_cost=action_cost["ap_cost"], neuron_cost=action_cost["neuron_cost"])
            compulsory_choices = _compulsory_tile_choices(state, str(node_id))
            if compulsory_choices and tile_instance_id not in {str(choice.get("instance_id")) for choice in compulsory_choices}:
                highest_priority = max(int(choice.get("priority") or 0) for choice in compulsory_choices)
                selected_category = _tile_category(state, tile)
                selected_is_compulsory = bool(selected_category.get("compulsory_on_same_node"))
                selected_priority = int(tile.get("priority") or 0)
                if selected_is_compulsory or selected_priority <= highest_priority:
                    self._reject(
                        state,
                        command_id,
                        "compulsory_interaction_first",
                        f"A compulsory interaction with priority {highest_priority} must be resolved first.",
                    )
            capability = (state.get("capabilities") or {}).get(capability_id) or {}
            if is_courtship_instance:
                pass
            elif tile.get("token_type") == OCTOPUS_TOKEN_ID:
                allowed_initiators = tile.get("initiator_capability_ids")
                if allowed_initiators is None:
                    allowed_initiators = list((state.get("capabilities") or {}).keys())
                if capability_id not in allowed_initiators:
                    self._reject(state, command_id, "cannot_initiate_interaction", "This ability cannot initiate interaction with the octopus token.")
            elif tile.get("event_id") not in (capability.get("initiates_event_ids") or []):
                self._reject(state, command_id, "cannot_initiate_interaction", "This ability cannot initiate interaction with this event.")
            next_state = deepcopy(state)
            if is_octopus_instance:
                next_state["tile_catalog"] = tile_catalog
                next_node_id, next_tile_instance = _find_tile_instance(next_state, tile_instance_id)
                if next_tile_instance:
                    next_tile_instance["tile_id"] = OCTOPUS_TILE_ID
                    next_tile_instance["token_type"] = OCTOPUS_TOKEN_ID
            next_state["interaction"] = {
                "tile_instance_id": tile_instance_id,
                "tile_id": lookup_tile_id,
                "node_id": node_id,
                "initiator_capability_id": capability_id,
                "initiator_confirmed": False,
                "played_cards": [],
                "requirement_reduction": 1 if next_state.get("force_reduces_next_interaction") else 0,
                "courtship_card": courtship_card,
            }
            next_state["force_reduces_next_interaction"] = False
            if payload.get("auto_select_cards"):
                selected_card_ids = _auto_selected_interaction_card_ids(
                    next_state,
                    capability_id,
                    list((courtship_card or {}).get("interaction_ids") or tile.get("interaction_ids") or []),
                )
            try:
                _sync_interaction_cards(next_state, capability_id, selected_card_ids)
            except ValueError as exc:
                self._reject(state, command_id, "invalid_selected_cards", str(exc))
            if not is_courtship_instance:
                _spend_action(next_state, capability_id, ap_cost=action_cost["ap_cost"], time_cost=action_cost["time_cost"], neuron_cost=action_cost["neuron_cost"])
            next_state["version"] = int(state["version"]) + 1
            _mark_game_lost_if_needed(next_state)
            event = {
                "event_id": f"evt_{uuid.uuid4().hex}",
                "type": "interaction_started",
                "command_id": command_id,
                "capability_id": capability_id,
                "tile_instance_id": tile_instance_id,
                "version": int(next_state["version"]),
                "created_at": _now_iso(),
            }
            next_state.setdefault("event_log", []).append(event)
            return next_state, [event]

        if command_type in {"play_interaction_card", "withdraw_interaction_card"}:
            payload = command.get("payload") or {}
            if not isinstance(payload, dict):
                self._reject(state, command_id, "invalid_payload", "Command payload must be an object.")
            capability_id = str(payload.get("capability_id") or "")
            card_id = str(payload.get("card_id") or "")
            if not state.get("interaction"):
                self._reject(state, command_id, "no_active_interaction", "No interaction is active.")
            interaction = state["interaction"]
            if (
                capability_id != str(interaction.get("initiator_capability_id") or "")
                and not interaction.get("initiator_confirmed", True)
            ):
                self._reject(
                    state,
                    command_id,
                    "initiator_confirmation_required",
                    "The initiating ability must confirm its cards before support cards can be committed.",
                )
            next_state = deepcopy(state)
            next_interaction = next_state["interaction"]
            capability = next_state["capabilities"].get(capability_id)
            if capability is None:
                self._reject(state, command_id, "unknown_capability", "Unknown capability.")
            if command_type == "play_interaction_card":
                card = next((entry for entry in capability.get("hand") or [] if entry.get("card_id") == card_id), None)
                if card is None:
                    self._reject(state, command_id, "unknown_card", "Card is not in this ability hand.")
                chosen_interaction_id = _choose_card_interaction(next_state, next_interaction.get("played_cards") or [], card)
                interaction_tile = (next_state.get("tile_catalog") or {}).get("tiles", {}).get(next_interaction.get("tile_id")) or {}
                remaining = list(
                    ((next_interaction.get("courtship_card") or {}).get("interaction_ids"))
                    or interaction_tile.get("interaction_ids")
                    or []
                ) + _counter_attack_requirements(next_state, interaction_tile)
                for played_card in next_interaction.get("played_cards") or []:
                    played_interaction_id = str(played_card.get("interaction_id") or "")
                    if played_interaction_id in remaining:
                        remaining.remove(played_interaction_id)
                if chosen_interaction_id not in remaining:
                    self._reject(state, command_id, "card_not_required", "Cards can only be played for requirements that are still missing.")
                capability["hand"] = [entry for entry in capability.get("hand") or [] if entry.get("card_id") != card_id]
                next_interaction.setdefault("played_cards", []).append({**card, "interaction_id": chosen_interaction_id, "interaction_ids": _card_interaction_options(card), "capability_id": capability_id})
                event_type = "interaction_card_played"
            else:
                card = next((entry for entry in next_interaction.get("played_cards") or [] if entry.get("card_id") == card_id and entry.get("capability_id") == capability_id), None)
                if card is None:
                    self._reject(state, command_id, "unknown_played_card", "This played card cannot be withdrawn by the active ability.")
                next_interaction["played_cards"] = [entry for entry in next_interaction.get("played_cards") or [] if entry.get("card_id") != card_id]
                capability.setdefault("hand", []).append({"card_id": card["card_id"], "interaction_id": card["interaction_id"], "interaction_ids": _card_interaction_options(card), "owner_capability_id": capability_id, "upgraded": bool(card.get("upgraded"))})
                event_type = "interaction_card_withdrawn"
            next_state["version"] = int(state["version"]) + 1
            event = {
                "event_id": f"evt_{uuid.uuid4().hex}",
                "type": event_type,
                "command_id": command_id,
                "capability_id": capability_id,
                "card_id": card_id,
                "version": int(next_state["version"]),
                "created_at": _now_iso(),
            }
            next_state.setdefault("event_log", []).append(event)
            return next_state, [event]

        if command_type in {"resolve_interaction", "fail_interaction"}:
            if not state.get("interaction"):
                self._reject(state, command_id, "no_active_interaction", "No interaction is active.")
            interaction = state["interaction"]
            tile = (state.get("tile_catalog") or {}).get("tiles", {}).get(interaction.get("tile_id")) or {}
            required_interaction_ids = list(
                ((interaction.get("courtship_card") or {}).get("interaction_ids"))
                or tile.get("interaction_ids")
                or []
            )
            if (
                command_type == "fail_interaction"
                and not required_interaction_ids
                and max(0, int(tile.get("shell_requirement_count") or 0)) == 0
            ):
                self._reject(
                    state,
                    command_id,
                    "automatic_interaction_cannot_fail",
                    "This interaction succeeds automatically and cannot be failed.",
                )
            next_state = deepcopy(state)
            success = False
            counter_success = False
            if command_type == "resolve_interaction":
                payload = command.get("payload") or {}
                if payload and not isinstance(payload, dict):
                    self._reject(state, command_id, "invalid_payload", "Command payload must be an object.")
                submitted_capability_id = str((payload or {}).get("capability_id") or "")
                capability_id = str(
                    submitted_capability_id
                    or interaction.get("initiator_capability_id")
                    or state.get("active_capability_id")
                    or ""
                )
                if capability_id and capability_id not in (state.get("capabilities") or {}):
                    self._reject(state, command_id, "unknown_capability", "Unknown capability.")
                initiator_id = str(interaction.get("initiator_capability_id") or "")
                if capability_id != initiator_id and not interaction.get("initiator_confirmed", True):
                    self._reject(
                        state,
                        command_id,
                        "initiator_confirmation_required",
                        "The initiating ability must confirm its cards before another ability can support.",
                    )
                selected_card_ids = [str(card_id) for card_id in ((payload or {}).get("card_ids") or [])]
                should_sync_cards = bool(
                    (payload or {}).get("auto_select_cards")
                    or "card_ids" in (payload or {})
                )
                if capability_id and should_sync_cards:
                    if (payload or {}).get("auto_select_cards"):
                        selected_card_ids = _auto_selected_interaction_card_ids(
                            next_state,
                            capability_id,
                            required_interaction_ids + _counter_attack_requirements(next_state, tile),
                        )
                    try:
                        _sync_interaction_cards(next_state, capability_id, selected_card_ids)
                    except ValueError as exc:
                        self._reject(state, command_id, "invalid_selected_cards", str(exc))
                if capability_id == initiator_id:
                    next_state["interaction"]["initiator_confirmed"] = True
                played = _played_interactions(next_state)
                success = _criteria_met_with_reduction(
                    required_interaction_ids,
                    played,
                    int(interaction.get("requirement_reduction") or 0),
                ) and _shell_requirement_met(next_state, tile)
                counter_required = _counter_attack_requirements(next_state, tile)
                counter_success = success and bool(counter_required) and _criteria_met(counter_required, played)
                if bool((payload or {}).get("confirm_only")):
                    next_state["version"] = int(state["version"]) + 1
                    event = {
                        "event_id": f"evt_{uuid.uuid4().hex}",
                        "type": "interaction_cards_confirmed",
                        "command_id": command_id,
                        "capability_id": capability_id,
                        "tile_instance_id": interaction.get("tile_instance_id"),
                        "success_ready": success,
                        "counter_success_ready": counter_success,
                        "version": int(next_state["version"]),
                        "created_at": _now_iso(),
                    }
                    next_state.setdefault("event_log", []).append(event)
                    return next_state, [event]
                if not success:
                    next_state["version"] = int(state["version"]) + 1
                    event = {
                        "event_id": f"evt_{uuid.uuid4().hex}",
                        "type": "interaction_cards_confirmed",
                        "command_id": command_id,
                        "tile_instance_id": interaction.get("tile_instance_id"),
                        "success": False,
                        "counter_success": False,
                        "version": int(next_state["version"]),
                        "created_at": _now_iso(),
                    }
                    next_state.setdefault("event_log", []).append(event)
                    return next_state, [event]
                if interaction.get("courtship_card"):
                    next_state["courtship_completed"] = True
                    next_state["courtship_blocked_node_id"] = None
                _spend_required_shells(next_state, tile)
                _apply_effects(next_state, tile.get("success_effects") or [], node_id=str(interaction.get("node_id") or ""))
                if counter_success:
                    _apply_effects(next_state, tile.get("counter_attack_effects") or [], node_id=str(interaction.get("node_id") or ""))
                node_tiles = next_state.get("tiles", {}).get(interaction.get("node_id")) or []
                next_state["tiles"][interaction.get("node_id")] = [entry for entry in node_tiles if entry.get("instance_id") != interaction.get("tile_instance_id")]
                _apply_tile_visibility(next_state)
                _mark_game_won_if_needed(next_state)
                event_type = "interaction_resolved"
            else:
                payload = command.get("payload") or {}
                if payload and not isinstance(payload, dict):
                    self._reject(state, command_id, "invalid_payload", "Command payload must be an object.")
                if interaction.get("courtship_card"):
                    retry = bool((payload or {}).get("spend_energy_to_retry"))
                    if retry:
                        if int((next_state.get("poulpita") or {}).get("energy") or 0) <= 1:
                            self._reject(state, command_id, "courtship_retry_energy_too_low", "Poulpita cannot spend its last energy.")
                        _damage_poulpita(next_state, amount=1, reason="courtship_retry")
                        courtship_cards = list(((next_state.get("tile_catalog") or {}).get("courtship_cards") or {}).values())
                        if not courtship_cards:
                            self._reject(state, command_id, "courtship_deck_empty", "No courtship cards are configured.")
                        for card in interaction.get("played_cards") or []:
                            owner = (next_state.get("capabilities") or {}).get(card.get("capability_id"))
                            if owner is not None:
                                owner.setdefault("discard", []).append(deepcopy(card))
                        next_state["interaction"]["played_cards"] = []
                        next_state["interaction"]["courtship_card"] = deepcopy(random.choice(courtship_cards))
                        next_state["interaction"]["initiator_confirmed"] = False
                        next_state["version"] = int(state["version"]) + 1
                        event = {
                            "event_id": f"evt_{uuid.uuid4().hex}",
                            "type": "courtship_retried",
                            "command_id": command_id,
                            "version": int(next_state["version"]),
                            "created_at": _now_iso(),
                        }
                        next_state.setdefault("event_log", []).append(event)
                        return next_state, [event]
                    next_state["courtship_blocked_node_id"] = str(interaction.get("node_id") or "")
                    failure_effects = []
                else:
                    failure_effects = tile.get("failure_effects") or []
                free_move_target_node_id = str((payload or {}).get("target_node_id") or "")
                if any(effect.get("type") == "pulpita_move_free" for effect in failure_effects):
                    current_node_id = str(state.get("poulpita", {}).get("node_id") or "")
                    adjacency = (state.get("map") or {}).get("adjacency") or {}
                    if not free_move_target_node_id:
                        self._reject(state, command_id, "free_move_target_required", "Choose where Poulpita moves after this failed interaction.")
                    if free_move_target_node_id not in (state.get("map", {}).get("nodes") or {}):
                        self._reject(state, command_id, "unknown_target_node", "Target node does not exist.")
                    if free_move_target_node_id not in adjacency.get(current_node_id, []):
                        self._reject(state, command_id, "non_adjacent_node", "Poulpita can move only to an adjacent node.")
                _apply_failure_effects(
                    next_state,
                    failure_effects,
                    interaction,
                    free_move_target_node_id=free_move_target_node_id or None,
                )
                _apply_tile_visibility(next_state)
                if int((next_state.get("poulpita") or {}).get("energy") or 0) <= 0 and any(effect.get("type") == "lose_energy" for effect in failure_effects):
                    _mark_game_lost_if_needed(next_state, reason="poulpita_no_energy")
                if next_state.get("phase") != PHASE_FINISHED:
                    _mark_game_won_if_needed(next_state)
                event_type = "interaction_failed"
            for card in interaction.get("played_cards") or []:
                capability = next_state["capabilities"].get(card.get("capability_id"))
                if capability is not None:
                    capability.setdefault("discard", []).append(
                        {
                            "card_id": card["card_id"],
                            "interaction_id": card["interaction_id"],
                            "interaction_ids": _card_interaction_options(card),
                            "owner_capability_id": card.get("capability_id"),
                            "upgraded": bool(card.get("upgraded")),
                        }
                    )
            next_state["interaction"] = None
            _maybe_start_courtship_interaction(next_state)
            next_state["version"] = int(state["version"]) + 1
            event = {
                "event_id": f"evt_{uuid.uuid4().hex}",
                "type": event_type,
                "command_id": command_id,
                "tile_instance_id": interaction.get("tile_instance_id"),
                "success": success,
                "counter_success": counter_success,
                "version": int(next_state["version"]),
                "created_at": _now_iso(),
            }
            next_state.setdefault("event_log", []).append(event)
            return next_state, [event]

        self._reject(state, command_id, "unknown_command", f"Unknown command type: {command_type or '<missing>'}.")

    async def connect_room_socket(self, *, room_id: str, user: User, websocket: WebSocket) -> bool:
        room = await self._load_room(room_id)
        if not room or room.get("owner_user_id") != user.id:
            return False
        state = await self._load_state(room_id)
        if state is None:
            return False
        await websocket.accept()
        self._room_sockets.setdefault(room_id, set()).add(websocket)
        await self._ensure_room_subscription(room_id)
        await websocket.send_json({"type": "state_projection", "payload": _project_state(state)})
        return True

    def disconnect_room_socket(self, *, room_id: str, websocket: WebSocket) -> None:
        sockets = self._room_sockets.get(room_id)
        if sockets is None:
            return
        sockets.discard(websocket)
        if not sockets:
            self._room_sockets.pop(room_id, None)
            task = self._room_pubsub_tasks.pop(room_id, None)
            if task is not None:
                task.cancel()

    async def broadcast_projection(self, room_id: str) -> None:
        state = await self._load_state(room_id)
        if state is None:
            return
        message = {"type": "state_projection", "payload": _project_state(state)}
        await self._send_local_projection(room_id, message)
        if self.redis is not None:
            await self.redis.publish(
                _projection_channel(room_id),
                json.dumps({"origin": self.node_id, "message": message}, default=str, separators=(",", ":")),
            )

    async def _send_local_projection(self, room_id: str, message: dict[str, Any]) -> None:
        sockets = list(self._room_sockets.get(room_id) or [])
        if not sockets:
            return
        stale: list[WebSocket] = []
        for websocket in sockets:
            try:
                await websocket.send_json(message)
            except Exception:
                stale.append(websocket)
        for websocket in stale:
            self.disconnect_room_socket(room_id=room_id, websocket=websocket)

    async def _ensure_room_subscription(self, room_id: str) -> None:
        if self.redis is None or room_id in self._room_pubsub_tasks:
            return
        self._room_pubsub_tasks[room_id] = asyncio.create_task(
            self._run_room_subscription(room_id),
            name=f"game-room-pubsub-{room_id}",
        )

    async def _run_room_subscription(self, room_id: str) -> None:
        pubsub = self.redis.pubsub()
        try:
            await pubsub.subscribe(_projection_channel(room_id))
            while room_id in self._room_pubsub_tasks:
                raw = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if not raw:
                    await asyncio.sleep(0)
                    continue
                data = raw.get("data")
                if isinstance(data, (bytes, bytearray)):
                    data = data.decode("utf-8", errors="ignore")
                try:
                    payload = json.loads(str(data))
                except (TypeError, json.JSONDecodeError):
                    continue
                if not isinstance(payload, dict) or payload.get("origin") == self.node_id:
                    continue
                message = payload.get("message")
                if isinstance(message, dict):
                    await self._send_local_projection(room_id, message)
        except asyncio.CancelledError:
            raise
        finally:
            try:
                await pubsub.unsubscribe(_projection_channel(room_id))
                await pubsub.aclose()
            except Exception:
                pass

    async def enqueue_end_room(self, *, room_id: str, user: User) -> dict[str, Any]:
        room = await self._load_room(room_id)
        if not room or room.get("owner_user_id") != user.id:
            raise LookupError("Game room not found.")
        if room.get("state") == ROOM_STATE_FINISHED:
            return _public_room(room)
        await self.finish_room(room_id=room_id, user_id=user.id)
        await self.broadcast_projection(room_id)
        updated_room = await self._load_room(room_id)
        return _public_room(updated_room or room)

    async def finish_room(self, *, room_id: str, user_id: str) -> dict[str, Any] | None:
        room = await self._load_room(room_id)
        if not room or room.get("owner_user_id") != user_id:
            return None
        if room.get("state") == ROOM_STATE_FINISHED:
            return await self.get_result(room_id=room_id, user_id=user_id)
        now = _now_iso()
        state = await self._load_state(room_id) or _setup_state(room_id, level_id=room.get("level_id"))
        result = {
            "id": room_id,
            "room_id": room_id,
            "user_id": user_id,
            "mode": room.get("mode", "goldfish"),
            "game_type": room.get("game_type", "goldfish"),
            "outcome": "completed",
            "score": "0",
            "turns": str(max(0, int(state.get("version") or 0) - 1)),
            "duration_seconds": str(max(1, int(time.time() - _iso_to_epoch(room.get("started_at") or room.get("created_at"))))),
            "summary": "Goldfish prototype room ended.",
            "created_at": now,
        }
        next_state = deepcopy(state)
        next_state["phase"] = PHASE_FINISHED
        next_state["version"] = int(next_state.get("version") or 0) + 1
        room.update({"state": ROOM_STATE_FINISHED, "ended_at": now, "result_id": room_id})
        await self._save_room(room)
        await self._save_state(room_id, next_state)
        await self._save_result(result)
        self._memory_history.setdefault(user_id, [])
        if room_id not in self._memory_history[user_id]:
            self._memory_history[user_id].append(room_id)
        if self.redis is not None:
            await self.redis.zadd(_history_key(user_id), {room_id: time.time()})
        return self._public_result(result)

    async def get_result(self, *, room_id: str, user_id: str) -> dict[str, Any] | None:
        result = self._memory_results.get(room_id)
        if self.redis is not None:
            redis_result = await self._redis_get_json(_result_key(room_id))
            if redis_result is not None:
                result = redis_result
                self._memory_results[room_id] = redis_result
        if not result or result.get("user_id") != user_id:
            return None
        return self._public_result(result)

    async def list_history(self, *, user_id: str, limit: int = 25) -> list[dict[str, Any]]:
        normalized_limit = max(1, min(100, int(limit or 25)))
        room_ids = list(reversed(self._memory_history.get(user_id, [])))[:normalized_limit]
        if self.redis is not None:
            redis_room_ids = await self.redis.zrevrange(_history_key(user_id), 0, normalized_limit - 1)
            room_ids = [str(room_id) for room_id in redis_room_ids]
        results: list[dict[str, Any]] = []
        for room_id in room_ids:
            result = await self.get_result(room_id=str(room_id), user_id=user_id)
            if result is not None:
                results.append(result)
        return results

    def _public_result(self, result: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": result.get("id", ""),
            "room_id": result.get("room_id", ""),
            "mode": result.get("mode", "goldfish"),
            "game_type": result.get("game_type", "goldfish"),
            "outcome": result.get("outcome", "completed"),
            "score": int(result.get("score") or 0),
            "turns": int(result.get("turns") or 0),
            "duration_seconds": int(result.get("duration_seconds") or 0),
            "summary": result.get("summary", ""),
            "created_at": result.get("created_at", ""),
        }


class GameWorker:
    def __init__(
        self,
        service: GameRoomService,
        *,
        stream_key: str | None = None,
        consumer_group: str | None = None,
        consumer_name: str | None = None,
        enabled: bool = True,
    ) -> None:
        self.service = service
        self.stream_key = stream_key or _env_str("GAME_COMMAND_STREAM_KEY", COMMAND_STREAM_KEY)
        self.consumer_group = consumer_group or _env_str("GAME_COMMAND_CONSUMER_GROUP", "game-workers")
        self.consumer_name = consumer_name or _env_str("GAME_COMMAND_CONSUMER_NAME", "worker-dev")
        self.enabled = enabled
        self._task: Optional[asyncio.Task] = None
        self._stopped = asyncio.Event()
        self._group_ready = False

    def start(self) -> None:
        if not self.enabled or self.service.redis is None:
            return
        if self._task is not None and not self._task.done():
            return
        self._stopped.clear()
        self._task = asyncio.create_task(self._run(), name=f"game-worker-{self.consumer_name}")

    async def stop(self) -> None:
        self._stopped.set()
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    async def _run(self) -> None:
        while not self._stopped.is_set():
            try:
                await self._ensure_group()
                messages = await self.service.redis.xreadgroup(
                    groupname=self.consumer_group,
                    consumername=self.consumer_name,
                    streams={self.stream_key: ">"},
                    count=16,
                    block=1000,
                )
                if not messages:
                    continue
                for _stream, entries in messages:
                    for entry_id, fields in entries:
                        await self._process_entry(str(entry_id), fields or {})
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                print(f"[game-worker] loop error: {exc}")
                await asyncio.sleep(0.5)

    async def _ensure_group(self) -> None:
        if self._group_ready:
            return
        try:
            await self.service.redis.xgroup_create(
                name=self.stream_key,
                groupname=self.consumer_group,
                id="0",
                mkstream=True,
            )
        except Exception:
            pass
        self._group_ready = True

    async def _process_entry(self, entry_id: str, fields: dict[str, Any]) -> None:
        command_id = self._field(fields, "command_id") or f"cmd_{uuid.uuid4().hex}"
        result: dict[str, Any]
        try:
            room_id = self._field(fields, "room_id")
            user_payload = json.loads(self._field(fields, "user") or "{}")
            command = json.loads(self._field(fields, "command") or "{}")
            user = User(**user_payload)
            result = await self.service.apply_command(room_id=room_id, user=user, command=command)
        except Exception as exc:
            result = {
                "ok": False,
                "status": "rejected",
                "command_id": command_id,
                "revision": 0,
                "reason": "worker_error",
                "message": str(exc),
                "current_version": 0,
            }
        await self.service._redis_set_json(
            _command_result_key(command_id),
            result,
            ex=max(1, _env_int("GAME_COMMAND_RESULT_TTL_SECONDS", 60)),
        )
        try:
            await self.service.redis.xack(self.stream_key, self.consumer_group, entry_id)
        except Exception:
            pass

    @staticmethod
    def _field(fields: dict[str, Any], key: str) -> str:
        value = fields.get(key)
        if isinstance(value, (bytes, bytearray)):
            return value.decode("utf-8", errors="ignore")
        return str(value or "")
