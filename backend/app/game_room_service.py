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


def _setup_state(room_id: str, *, level_id: str | None = None) -> dict[str, Any]:
    level_config = get_level_config(level_id)
    map_config = get_map(level_config["map_id"])
    _validate_map_config(map_config)
    return {
        "room_id": room_id,
        "mode": "goldfish",
        "version": 0,
        "phase": PHASE_SETUP,
        "level_id": level_config["id"],
        "selected_level_id": level_config["id"],
        "day_index": 1,
        "night_time_spent": 0,
        "night_time_total": max(1, int(level_config.get("night_duration_steps") or NIGHT_OVERRUN_CHUNKS)),
        "selected_map_id": map_config["id"],
        "active_capability_id": None,
        "last_active_capability_id": None,
        "focused_capability_id": DEFAULT_FOCUSED_CAPABILITY_ID,
        "map": _map_projection(map_config),
        "poulpita": {"node_id": None, "previous_node_id": None, "energy": 0, "neurons": 0, "seashells": 0, "size_index": 0, "size_upgraded_today": False},
        "capabilities": _initial_capabilities(),
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
            cards.append(
                {
                    "card_id": f"card_{uuid.uuid4().hex}",
                    "interaction_id": interaction_id,
                    "interaction_ids": interaction_ids,
                    "owner_capability_id": capability_id,
                }
            )
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


def _remove_cards_from_capability(capability: dict[str, Any], interaction_id: str, count: int) -> list[dict[str, Any]] | None:
    available = sum(
        1
        for zone in ["draw_pile", "discard", "hand"]
        for card in capability.get(zone) or []
        if interaction_id in _card_interaction_options(card)
    )
    if available < count:
        return None
    removed: list[dict[str, Any]] = []
    zones = ["draw_pile", "discard", "hand"]
    for zone in zones:
        kept = []
        for card in capability.get(zone) or []:
            if len(removed) < count and interaction_id in _card_interaction_options(card):
                removed.append(card)
            else:
                kept.append(card)
        capability[zone] = kept
        if len(removed) >= count:
            return removed
    return None


def _apply_deck_exchange_upgrade(capability: dict[str, Any], upgrade: dict[str, Any]) -> None:
    removed_by_interaction: list[tuple[str, list[dict[str, Any]]]] = []
    for entry in upgrade.get("remove_cards") or []:
        interaction_id = str(entry.get("interaction_id") or "")
        count = max(0, int(entry.get("count") or 0))
        removed = _remove_cards_from_capability(capability, interaction_id, count)
        if removed is None:
            for restored_interaction_id, restored_cards in removed_by_interaction:
                capability.setdefault("draw_pile", []).extend(restored_cards)
            raise ValueError(f"Not enough {interaction_id} cards remain to exchange.")
        removed_by_interaction.append((interaction_id, removed))
    new_cards = []
    capability_id = str(capability.get("id") or "")
    for entry in upgrade.get("add_cards") or []:
        interaction_ids = [str(interaction_id) for interaction_id in (entry.get("interaction_ids") or []) if interaction_id]
        if not interaction_ids:
            continue
        for _index in range(max(0, int(entry.get("count") or 0))):
            new_cards.append(
                {
                    "card_id": f"card_{uuid.uuid4().hex}",
                    "interaction_id": interaction_ids[0],
                    "interaction_ids": interaction_ids,
                    "owner_capability_id": capability_id,
                    "upgraded": True,
                }
            )
    capability.setdefault("draw_pile", []).extend(new_cards)
    random.shuffle(capability["draw_pile"])


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
            "pa": 0,
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
        }
    return capabilities


def _tile_public(tile: dict[str, Any], catalog: dict[str, dict[str, Any]]) -> dict[str, Any]:
    event = catalog["events"].get(tile.get("event_id")) or {}
    return {
        **tile,
        "event": event,
        "image_url": event.get("image_url"),
    }


def _build_tile_catalog() -> dict[str, Any]:
    catalog = get_game_content_catalog()
    public_tiles = {}
    for tile_id, tile in catalog["tiles"].items():
        public_tiles[tile_id] = _tile_public(tile, catalog)
    token_catalog = catalog.get("tokens") or {}
    octopus_token = token_catalog.get(OCTOPUS_TOKEN_ID) or {}
    if octopus_token:
        octopus_event = {
            "id": OCTOPUS_EVENT_ID,
            "name": octopus_token.get("name") or "Octopus token",
            "category_id": OCTOPUS_CATEGORY_ID,
            "image_url": octopus_token.get("image_url"),
        }
        catalog.setdefault("events", {})[OCTOPUS_EVENT_ID] = octopus_event
        catalog.setdefault("categories", {})[OCTOPUS_CATEGORY_ID] = {
            "id": OCTOPUS_CATEGORY_ID,
            "name": "Threat",
            "compulsory_on_same_node": True,
        }
        public_tiles[OCTOPUS_TILE_ID] = {
            "id": OCTOPUS_TILE_ID,
            "name": octopus_token.get("name") or "Octopus token",
            "event_id": OCTOPUS_EVENT_ID,
            "event": octopus_event,
            "image_url": octopus_token.get("image_url"),
            "priority": int(octopus_token.get("priority") or 0),
            "interaction_ids": list(octopus_token.get("interaction_ids") or []),
            "counter_attack_interaction_ids": list(octopus_token.get("counter_attack_interaction_ids") or []),
            "success_effects": deepcopy(octopus_token.get("success_effects") or []),
            "counter_attack_effects": deepcopy(octopus_token.get("counter_attack_effects") or []),
            "failure_effects": deepcopy(octopus_token.get("failure_effects") or []),
            "token_type": OCTOPUS_TOKEN_ID,
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
        "card_categories": catalog.get("card_categories") or [],
        "tokens": token_catalog,
        "poulpita_panel": catalog.get("poulpita_panel") or {},
        "action_costs": catalog.get("action_costs") or {},
    }


def _level_tiles(level_config: dict[str, Any], catalog: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    node_tiles = {node_id: [] for node_id in level_config.get("node_tile_counts") or {}}
    for group in level_config.get("groups") or []:
        expanded = []
        for tile_id, count in (group.get("tile_counts") or {}).items():
            for _index in range(max(0, int(count or 0))):
                tile = catalog["tiles"].get(tile_id)
                if tile:
                    expanded.append({"instance_id": f"tile_{uuid.uuid4().hex}", "tile_id": tile_id, "face_up": False})
        random.shuffle(expanded)
        group_node_ids = [node_id for node_id, group_id in (level_config.get("node_group_ids") or {}).items() if group_id == group["id"]]
        for node_id in group_node_ids:
            count = int((level_config.get("node_tile_counts") or {}).get(node_id) or 0)
            node_tiles.setdefault(node_id, []).extend(expanded[:count])
            expanded = expanded[count:]
    for node_id, tokens in (level_config.get("node_tokens") or {}).items():
        for token in tokens or []:
            if str(token.get("type") if isinstance(token, dict) else token) == OCTOPUS_TOKEN_ID and OCTOPUS_TILE_ID in (catalog.get("tiles") or {}):
                node_tiles.setdefault(str(node_id), []).append(
                    {
                        "instance_id": f"octopus_{node_id}_{uuid.uuid4().hex}",
                        "tile_id": OCTOPUS_TILE_ID,
                        "face_up": True,
                        "token_type": OCTOPUS_TOKEN_ID,
                    }
                )
    return node_tiles


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


def _goldfish_state(room_id: str, *, level_id: str | None = None) -> dict[str, Any]:
    level_config = get_level_config(level_id)
    map_config = get_map(level_config["map_id"])
    _validate_map_config(map_config)
    tile_catalog = _build_tile_catalog()
    starting_energy = max(0, min(32, int(level_config.get("starting_energy") or 3)))
    starting_neurons = max(0, int(level_config.get("starting_neurons") or 0))
    surprise_deck_id = str(level_config.get("surprise_deck_id") or "")
    surprise_draw_pile = list(((tile_catalog.get("surprise_decks") or {}).get(surprise_deck_id) or {}).get("card_ids") or [])
    random.shuffle(surprise_draw_pile)
    state = {
        "room_id": room_id,
        "mode": "goldfish",
        "version": 1,
        "phase": PHASE_NIGHT_IDLE,
        "level_id": level_config["id"],
        "selected_level_id": level_config["id"],
        "day_index": 1,
        "night_time_spent": 0,
        "night_time_total": max(1, int(level_config.get("night_duration_steps") or NIGHT_OVERRUN_CHUNKS)),
        "selected_map_id": map_config["id"],
        "active_capability_id": None,
        "last_active_capability_id": None,
        "focused_capability_id": DEFAULT_FOCUSED_CAPABILITY_ID,
        "map": _map_projection(map_config),
        "poulpita": {
            "node_id": str(level_config.get("poulpita_starting_node_id") or map_config["starting_node_id"]),
            "previous_node_id": None,
            "energy": starting_energy,
            "neurons": starting_neurons,
            "seashells": 0,
            "size_index": 0,
            "size_upgraded_today": False,
        },
        "capabilities": _initial_capabilities(deal_hands=True),
        "tiles": _level_tiles(level_config, tile_catalog),
        "shelters": _level_shelters(level_config),
        "surprise_deck_id": surprise_deck_id,
        "surprise_draw_pile": surprise_draw_pile,
        "surprise_deck_initialized": True,
        "surprise_deck_card_count": len(surprise_draw_pile),
        "surprise_deck_exhausted": not bool(surprise_draw_pile),
        "pending_surprise": None,
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
    capabilities = deepcopy(state.get("capabilities") or {})
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
        tile_catalog["tiles"] = {
            tile_id: _tile_public(tile, {"events": latest_events})
            for tile_id, tile in latest_tiles.items()
        } or {}
        tile_catalog["tiles"].update(preserved_special_tiles)
        tile_catalog["categories"] = {**(latest_catalog.get("categories") or {}), **preserved_special_categories}
        tile_catalog["events"] = {**(latest_events or {}), **preserved_special_events}
        tile_catalog["interactions"] = latest_catalog.get("interactions") or tile_catalog.get("interactions") or {}
        tile_catalog["cards"] = latest_catalog.get("cards") or tile_catalog.get("cards") or {}
        tile_catalog["tokens"] = latest_catalog.get("tokens") or tile_catalog.get("tokens") or {}
        tile_catalog["poulpita_panel"] = latest_catalog.get("poulpita_panel") or tile_catalog.get("poulpita_panel") or {}
        tile_catalog["surprise_cards"] = latest_catalog.get("surprise_cards") or tile_catalog.get("surprise_cards") or {}
        tile_catalog["surprise_decks"] = latest_catalog.get("surprise_decks") or tile_catalog.get("surprise_decks") or {}
        tile_catalog["action_costs"] = latest_catalog.get("action_costs") or tile_catalog.get("action_costs") or {}
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
        "version": int(state["version"]),
        "phase": state["phase"],
        "level_id": state["level_id"],
        "selected_level_id": state.get("selected_level_id") or state.get("level_id"),
        "day_index": int(state.get("day_index") or 1),
        "night_time_spent": int(state.get("night_time_spent") or 0),
        "night_time_total": max(1, int(state.get("night_time_total") or NIGHT_OVERRUN_CHUNKS)),
        "night_shelter_available_at": NIGHT_SHELTER_AVAILABLE_CHUNKS,
        "selected_map_id": state.get("selected_map_id") or "",
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
        "objectives": _objective_status(state),
        "objective_progress": deepcopy(state.get("objective_progress") or {}),
        "tile_catalog": tile_catalog,
        "interaction": deepcopy(state.get("interaction")),
        "events": list(state.get("event_log") or [])[-20:],
    }


def _configured_action_cost(state: dict[str, Any], action_id: str) -> dict[str, int]:
    defaults = {
        "gain_ap": {"ap_cost": 0, "time_cost": 0},
        "move": {"ap_cost": 1, "time_cost": 1},
        "interact": {"ap_cost": 1, "time_cost": 2},
        "special_power": {"ap_cost": 1, "time_cost": 0},
    }
    raw = ((state.get("tile_catalog") or {}).get("action_costs") or {}).get(action_id) or {}
    fallback = defaults.get(action_id) or {"ap_cost": 0, "time_cost": 0}
    return {
        "ap_cost": max(0, int(raw.get("ap_cost") if raw.get("ap_cost") is not None else fallback["ap_cost"])),
        "time_cost": max(0, int(raw.get("time_cost") if raw.get("time_cost") is not None else fallback["time_cost"])),
    }


def _require_active_action(service: "GameRoomService", state: dict[str, Any], command_id: str, capability_id: str, *, ap_cost: int = 0) -> dict[str, Any]:
    capability = _require_active_control(service, state, command_id, capability_id)
    if int(capability.get("pa") or 0) < ap_cost:
        service._reject(state, command_id, "insufficient_pa", f"This action costs {ap_cost} AP.")
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
        capability["pa"] = 0
        capability["control_takes_this_night"] = 0
        capability["actions_taken_this_control"] = 0


def _spend_action(next_state: dict[str, Any], capability_id: str, *, ap_cost: int = 0, time_cost: int = 0) -> None:
    capability = next_state["capabilities"][capability_id]
    capability["pa"] = int(capability.get("pa") or 0) - ap_cost
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
        return False
    capability = (state.get("capabilities") or {}).get(active_id) or {}
    remaining_actions = int(capability.get("max_actions_per_control") or 0) - int(capability.get("actions_taken_this_control") or 0)
    return remaining_actions <= 0


def _no_control_takes_available(state: dict[str, Any]) -> bool:
    for capability in (state.get("capabilities") or {}).values():
        if int(capability.get("control_takes_this_night") or 0) < int(capability.get("max_control_takes_per_night") or 0):
            return False
    return True


def _mark_game_lost_if_needed(next_state: dict[str, Any], *, reason: str | None = None) -> bool:
    if next_state.get("phase") == PHASE_FINISHED:
        return True
    loss_reason = reason
    if not loss_reason and _no_control_takes_available(next_state) and _active_capability_is_out_of_actions(next_state):
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
        statuses.append({**objective, "label": label, "current": current, "target": target if objective_type == "increase_size" else None, "completed": completed})
    return statuses


def _mark_game_won_if_needed(next_state: dict[str, Any]) -> bool:
    objectives = next_state.get("objectives") or []
    if not objectives or next_state.get("phase") == PHASE_FINISHED:
        return False
    if not all(objective.get("completed") for objective in _objective_status(next_state)):
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
    for required_ids in [tile.get("interaction_ids") or [], tile.get("counter_attack_interaction_ids") or []]:
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
    hand = []
    for card in capability.get("hand") or []:
        if str(card.get("card_id")) in selected:
            chosen_interaction_id = _choose_card_interaction(next_state, next_played, card)
            next_played.append({**card, "interaction_id": chosen_interaction_id, "interaction_ids": _card_interaction_options(card), "capability_id": capability_id})
        else:
            hand.append(card)
    missing = selected - {str(card.get("card_id")) for card in next_played if card.get("capability_id") == capability_id}
    if missing:
        raise ValueError("Selected cards must be in this ability hand or already played by it.")
    capability["hand"] = hand
    interaction["played_cards"] = next_played


def _criteria_met(required: list[str], played: list[str]) -> bool:
    remaining = list(required or [])
    for interaction_id in played:
        if interaction_id in remaining:
            remaining.remove(interaction_id)
    return not remaining


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
            next_state["poulpita"]["energy"] = int(next_state["poulpita"].get("energy") or 0) + amount
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
                next_state.setdefault("objective_progress", {})["found_shelter"] = True
        elif effect_type == "draw_surprise_card":
            _draw_surprise_card(next_state)


def _move_poulpita_without_ap(next_state: dict[str, Any], target_node_id: str) -> None:
    current_node_id = str(next_state.get("poulpita", {}).get("node_id") or "")
    next_state["poulpita"]["previous_node_id"] = current_node_id or None
    next_state["poulpita"]["node_id"] = target_node_id


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
            next_state["poulpita"]["energy"] = int(next_state["poulpita"].get("energy") or 0) + amount
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

    async def create_room(self, *, user: User, game_type: str = "goldfish", map_id: str | None = None, level_id: str | None = None) -> dict[str, Any]:
        normalized_game_type = str(game_type or "goldfish").strip() or "goldfish"
        selected_level = get_level_config(level_id)
        selected_map = get_map(selected_level["map_id"])
        room_id = f"room_{uuid.uuid4().hex[:16]}"
        now = _now_iso()
        room = {
            "id": room_id,
            "owner_user_id": user.id,
            "owner_username": user.username or user.email or user.id,
            "mode": "goldfish",
            "game_type": normalized_game_type,
            "state": ROOM_STATE_SETUP,
            "created_at": now,
            "started_at": "",
            "ended_at": "",
            "result_id": "",
            "map_id": selected_map["id"],
            "level_id": selected_level["id"],
        }
        await self._save_room(room)
        await self._save_state(room_id, _setup_state(room_id, level_id=selected_level["id"]))
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
            try:
                next_state, events = self._reduce(state, command, user=user, room_id=room_id, room=room)
            except CommandRejection as rejection:
                return rejection.payload(_project_state(state))
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
            next_state = _goldfish_state(room_id, level_id=room.get("level_id") or state.get("selected_level_id"))
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

        if command_type == "move_poulpita":
            if state["phase"] != PHASE_NIGHT_ACTION:
                self._reject(state, command_id, "phase_not_movable", "Take control before moving Poulpita.")
            payload = command.get("payload") or {}
            if not isinstance(payload, dict):
                self._reject(state, command_id, "invalid_payload", "Command payload must be an object.")
            capability_id = str(payload.get("capability_id") or "")
            target_node_id = str(payload.get("target_node_id") or "")
            action_cost = _configured_action_cost(state, "move")
            _require_active_action(self, state, command_id, capability_id, ap_cost=action_cost["ap_cost"])
            nodes = state["map"]["nodes"]
            if target_node_id not in nodes:
                self._reject(state, command_id, "unknown_target_node", "Target node does not exist.")
            current_node_id = str(state["poulpita"]["node_id"])
            if target_node_id not in (state["map"]["adjacency"].get(current_node_id) or []):
                self._reject(state, command_id, "non_adjacent_node", "Poulpita can move only to an adjacent node.")
            next_state = deepcopy(state)
            next_state["version"] = int(state["version"]) + 1
            next_state["poulpita"]["previous_node_id"] = current_node_id
            next_state["poulpita"]["node_id"] = target_node_id
            _spend_action(next_state, capability_id, ap_cost=action_cost["ap_cost"], time_cost=action_cost["time_cost"])
            _apply_tile_visibility(next_state)
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
            return next_state, [event]

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
            next_state.setdefault("objective_progress", {})["found_shelter"] = True
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
            cost = max(0, base_cost - (1 if _current_shelter_secure(state) else 0))
            current_energy = int(poulpita.get("energy") or 0)
            if cost > 0 and current_energy - cost <= 0:
                self._reject(state, command_id, "insufficient_energy", "Poulpita must have enough energy and cannot spend down to 0.")
            next_state = deepcopy(state)
            next_state["poulpita"]["energy"] = current_energy - cost
            next_state["poulpita"]["size_index"] = next_size_index
            next_state["poulpita"]["size_upgraded_today"] = True
            next_state["version"] = int(state["version"]) + 1
            next_state.setdefault("objective_progress", {})["size_increases"] = int((next_state.get("objective_progress") or {}).get("size_increases") or 0) + 1
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
            next_state["phase"] = PHASE_NIGHT_IDLE
            next_state["day_index"] = int(state.get("day_index") or 1) + 1
            next_state["night_time_spent"] = 0
            next_state["active_capability_id"] = None
            next_state["last_active_capability_id"] = None
            next_state.setdefault("poulpita", {})["size_upgraded_today"] = False
            for capability in (next_state.get("capabilities") or {}).values():
                capability["pa"] = 0
                capability["control_takes_this_night"] = 0
                capability["actions_taken_this_control"] = 0
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

        if command_type == "collect_action_points":
            payload = command.get("payload") or {}
            if not isinstance(payload, dict):
                self._reject(state, command_id, "invalid_payload", "Command payload must be an object.")
            capability_id = str(payload.get("capability_id") or "")
            action_cost = _configured_action_cost(state, "gain_ap")
            _require_active_action(self, state, command_id, capability_id, ap_cost=action_cost["ap_cost"])
            amount = random.randint(1, 6)
            next_state = deepcopy(state)
            next_state["version"] = int(state["version"]) + 1
            next_capability = next_state["capabilities"][capability_id]
            next_capability["pa"] = int(next_capability.get("pa") or 0) + amount
            _spend_action(next_state, capability_id, ap_cost=action_cost["ap_cost"], time_cost=action_cost["time_cost"])
            _mark_game_lost_if_needed(next_state)
            event = {
                "event_id": f"evt_{uuid.uuid4().hex}",
                "type": "action_points_collected",
                "command_id": command_id,
                "capability_id": capability_id,
                "amount": amount,
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
            action_cost = _configured_action_cost(state, "special_power")
            capability = _require_active_action(self, state, command_id, capability_id, ap_cost=action_cost["ap_cost"])
            discard_card_id = str(payload.get("discard_card_id") or "").strip()
            hand = capability.get("hand") or []
            hand_limit = int(capability.get("current_max_cards_in_hand") or 3)
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
            _spend_action(next_state, capability_id, ap_cost=action_cost["ap_cost"], time_cost=action_cost["time_cost"])
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
            _require_active_action(self, state, command_id, capability_id, ap_cost=action_cost["ap_cost"])
            if state.get("interaction"):
                self._reject(state, command_id, "interaction_already_active", "Resolve or fail the current interaction first.")
            node_id, tile_instance = _find_tile_instance(state, tile_instance_id)
            if not tile_instance:
                self._reject(state, command_id, "unknown_tile", "Tile not found.")
            if node_id != state.get("poulpita", {}).get("node_id"):
                self._reject(state, command_id, "tile_not_on_poulpita_node", "Poulpita must be on the tile node.")
            if not tile_instance.get("face_up"):
                self._reject(state, command_id, "tile_face_down", "This tile is not revealed yet.")
            tile = (state.get("tile_catalog") or {}).get("tiles", {}).get(tile_instance.get("tile_id"))
            if not tile:
                self._reject(state, command_id, "unknown_tile", "Tile definition not found.")
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
            if tile.get("token_type") != OCTOPUS_TOKEN_ID and tile.get("event_id") not in (capability.get("initiates_event_ids") or []):
                self._reject(state, command_id, "cannot_initiate_interaction", "This ability cannot initiate interaction with this event.")
            next_state = deepcopy(state)
            next_state["interaction"] = {
                "tile_instance_id": tile_instance_id,
                "tile_id": tile_instance.get("tile_id"),
                "node_id": node_id,
                "initiator_capability_id": capability_id,
                "played_cards": [],
            }
            try:
                _sync_interaction_cards(next_state, capability_id, selected_card_ids)
            except ValueError as exc:
                self._reject(state, command_id, "invalid_selected_cards", str(exc))
            _spend_action(next_state, capability_id, ap_cost=action_cost["ap_cost"], time_cost=action_cost["time_cost"])
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
            if capability_id != state.get("active_capability_id"):
                self._reject(state, command_id, "not_active_capability", "Only the active capability can play or withdraw cards.")
            if not state.get("interaction"):
                self._reject(state, command_id, "no_active_interaction", "No interaction is active.")
            next_state = deepcopy(state)
            next_interaction = next_state["interaction"]
            capability = next_state["capabilities"].get(capability_id)
            if capability is None:
                self._reject(state, command_id, "unknown_capability", "Unknown capability.")
            if command_type == "play_interaction_card":
                card = next((entry for entry in capability.get("hand") or [] if entry.get("card_id") == card_id), None)
                if card is None:
                    self._reject(state, command_id, "unknown_card", "Card is not in this ability hand.")
                capability["hand"] = [entry for entry in capability.get("hand") or [] if entry.get("card_id") != card_id]
                chosen_interaction_id = _choose_card_interaction(next_state, next_interaction.get("played_cards") or [], card)
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
            next_state = deepcopy(state)
            success = False
            counter_success = False
            if command_type == "resolve_interaction":
                payload = command.get("payload") or {}
                if payload and not isinstance(payload, dict):
                    self._reject(state, command_id, "invalid_payload", "Command payload must be an object.")
                capability_id = str((payload or {}).get("capability_id") or "")
                selected_card_ids = [str(card_id) for card_id in ((payload or {}).get("card_ids") or [])]
                if capability_id:
                    if capability_id != state.get("active_capability_id"):
                        self._reject(state, command_id, "not_active_capability", "Only the active capability can confirm cards.")
                    try:
                        _sync_interaction_cards(next_state, capability_id, selected_card_ids)
                    except ValueError as exc:
                        self._reject(state, command_id, "invalid_selected_cards", str(exc))
                played = _played_interactions(next_state)
                success = _criteria_met(tile.get("interaction_ids") or [], played) and _shell_requirement_met(next_state, tile)
                counter_required = tile.get("counter_attack_interaction_ids") or []
                counter_success = success and bool(counter_required) and _criteria_met(counter_required, played)
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
