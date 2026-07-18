from __future__ import annotations

import json
import re
import shutil
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any

from fastapi import UploadFile

from .map_service import get_map


CONTENT_ROOT = Path(__file__).resolve().parents[1] / "data" / "content"
CONTENT_IMAGES_ROOT = CONTENT_ROOT / "images"
CONTENT_JSON_PATH = CONTENT_ROOT / "content.json"
ALLOWED_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}

DEFAULT_CATEGORIES = [
    {"id": "prey", "name": "Prey"},
    {"id": "threat", "name": "Threat"},
    {"id": "exploration", "name": "Exploration"},
]
COUNTER_ATTACK_CATEGORY_ID = "__counter_attack__"
COUNTER_ATTACK_CATEGORY = {"id": COUNTER_ATTACK_CATEGORY_ID, "name": "Counter-attack", "special": True}
SUCCESS_EFFECT_TYPES = {"gain_energy", "gain_neurons", "gain_seashells", "place_shelter_token", "draw_surprise_card"}
SURPRISE_COST_TYPES = {"play_cards", "pay_ap"}
SURPRISE_EFFECT_TYPES = {
    "gain_ap",
    "gain_neurons",
    "advance_night",
    "gain_energy",
    "lose_energy",
    "remove_tiles_category_here",
    "remove_tiles_category_adjacent",
}
FAILURE_EFFECT_TYPES = {
    "lose_energy",
    "lose_neurons",
    "lose_seashells",
    "lose_ap",
    "lose_half_ap",
    "lose_all_ap",
    "pulpita_move_previous",
    "pulpita_move_free",
    "keep_tile",
    "remove_tile",
    "move_tile_previous",
    "remove_preys",
}
PLAYER_BOARD_ORDER = ["agility", "camouflage", "force", "propulsion", "intelligence"]
PLAYER_BOARD_DEFAULT_NAMES = {
    "agility": "Agility",
    "camouflage": "Camouflage",
    "force": "Force",
    "propulsion": "Propulsion",
    "intelligence": "Intelligence",
}
UPGRADE_COST_RESOURCES = {"energy", "neurons"}
TOKEN_TYPES = [
    {"id": "neuron", "name": "Neuron token"},
    {"id": "seashell", "name": "Seashell token"},
    {"id": "shelter", "name": "Shelter token"},
    {"id": "octopus", "name": "Octopus token"},
]
OCTOPUS_TOKEN_ID = "octopus"
PLACEABLE_LEVEL_TOKEN_IDS = {"shelter", OCTOPUS_TOKEN_ID}
POULPITA_PANEL_ZONE_IDS = {"neurons", "seashells"}
SIZE_UNITS = {"mg", "g", "kg"}
ADMIN_CONTENT_COLLECTION_KEYS = [
    "categories",
    "interactions",
    "events",
    "tiles",
    "levels",
    "surprise_cards",
    "surprise_decks",
    "player_boards",
    "tokens",
]
ACTION_COST_KEYS = ["gain_ap", "move", "interact", "special_power"]
DEFAULT_ACTION_COSTS = {
    "gain_ap": {"ap_cost": 0, "time_cost": 0},
    "move": {"ap_cost": 1, "time_cost": 1},
    "interact": {"ap_cost": 1, "time_cost": 2},
    "special_power": {"ap_cost": 1, "time_cost": 0},
}


def _slug(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(value or "").strip().lower()).strip("-")
    return normalized[:48] or "content"


def _empty_content() -> dict[str, Any]:
    return {
        "categories": deepcopy(DEFAULT_CATEGORIES),
        "interactions": [],
        "events": [],
        "tiles": [],
        "levels": [],
        "surprise_cards": [],
        "surprise_decks": [],
        "player_boards": _default_player_boards(),
        "tokens": _default_tokens(),
        "poulpita_panel": _default_poulpita_panel(),
        "action_costs": deepcopy(DEFAULT_ACTION_COSTS),
    }


def _ensure_content() -> None:
    CONTENT_IMAGES_ROOT.mkdir(parents=True, exist_ok=True)
    if CONTENT_JSON_PATH.exists():
        return
    CONTENT_ROOT.mkdir(parents=True, exist_ok=True)
    _write_content(_empty_content())


def _write_content(content: dict[str, Any]) -> None:
    CONTENT_ROOT.mkdir(parents=True, exist_ok=True)
    with CONTENT_JSON_PATH.open("w", encoding="utf-8") as handle:
        json.dump(content, handle, indent=2, sort_keys=True)


def _strip_image_fields(value: Any) -> Any:
    if isinstance(value, list):
        return [_strip_image_fields(item) for item in value]
    if isinstance(value, dict):
        stripped = {}
        for key, item in value.items():
            if key == "image_url":
                continue
            if key == "image_filename":
                stripped[key] = None
                continue
            stripped[key] = _strip_image_fields(item)
        return stripped
    return value


def _merge_items_by_id(current_items: list[dict[str, Any]], imported_items: list[dict[str, Any]], label: str) -> tuple[list[dict[str, Any]], int, int]:
    if not isinstance(imported_items, list):
        raise ValueError(f"{label} must be a JSON array.")
    merged = [dict(item) for item in current_items if isinstance(item, dict)]
    positions = {str(item.get("id")): index for index, item in enumerate(merged) if item.get("id")}
    created = 0
    updated = 0
    for raw_item in imported_items:
        if not isinstance(raw_item, dict):
            raise ValueError(f"Each {label} item must be an object.")
        item = _strip_image_fields(raw_item)
        item_id = str(item.get("id") or "").strip()
        if not item_id:
            raise ValueError(f"Each {label} item requires an id.")
        item["id"] = item_id
        if item_id in positions:
            merged[positions[item_id]] = item
            updated += 1
        else:
            positions[item_id] = len(merged)
            merged.append(item)
            created += 1
    return merged, created, updated


def _read_content() -> dict[str, Any]:
    _ensure_content()
    with CONTENT_JSON_PATH.open("r", encoding="utf-8") as handle:
        content = json.load(handle)
    content.setdefault("categories", [])
    content.setdefault("interactions", [])
    content.setdefault("events", [])
    content.setdefault("tiles", [])
    content.setdefault("levels", [])
    content.setdefault("surprise_cards", [])
    content.setdefault("surprise_decks", [])
    for category in content["categories"]:
        category["compulsory_on_same_node"] = bool(category.get("compulsory_on_same_node") or False)
    content["player_boards"] = _normalize_player_boards(content.get("player_boards") or [])
    content["tokens"] = _normalize_tokens(content.get("tokens") or [])
    content["poulpita_panel"] = _normalize_poulpita_panel(content.get("poulpita_panel") or {})
    for tile in content["tiles"]:
        tile["priority"] = int(tile.get("priority") or 0)
        tile.setdefault("interaction_ids", [])
        tile.setdefault("counter_attack_interaction_ids", [])
        tile.setdefault("success_effects", [])
        tile.setdefault("counter_attack_effects", [])
        tile.setdefault("failure_effects", [])
    for level in content["levels"]:
        level["objectives"] = _normalize_level_objectives(level.get("objectives") or [])
        level["starting_energy"] = max(0, min(32, int(level.get("starting_energy") or 3)))
        level["starting_neurons"] = max(0, int(level.get("starting_neurons") or 0))
        level["surprise_deck_id"] = level.get("surprise_deck_id") or ""
        level["poulpita_starting_node_id"] = str(level.get("poulpita_starting_node_id") or "")
        level["node_tokens"] = level.get("node_tokens") or {}
    return content


def _default_tokens() -> list[dict[str, Any]]:
    tokens = []
    for token in TOKEN_TYPES:
        entry = {**token, "image_filename": None}
        if token["id"] == OCTOPUS_TOKEN_ID:
            entry.update(
                {
                    "priority": 0,
                    "interaction_ids": [],
                    "counter_attack_interaction_ids": [],
                    "success_effects": [],
                    "counter_attack_effects": [],
                    "failure_effects": [],
                }
            )
        tokens.append(entry)
    return tokens


def _normalize_tokens(raw_tokens: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {str(token.get("id")): dict(token) for token in raw_tokens if isinstance(token, dict)}
    tokens = []
    for default in _default_tokens():
        current = {**default, **by_id.get(default["id"], {})}
        current["id"] = default["id"]
        current["name"] = default["name"]
        current["image_filename"] = current.get("image_filename") or None
        if current["id"] == OCTOPUS_TOKEN_ID:
            current["priority"] = int(current.get("priority") or 0)
            current["interaction_ids"] = list(current.get("interaction_ids") or [])
            current["counter_attack_interaction_ids"] = list(current.get("counter_attack_interaction_ids") or [])
            current["success_effects"] = list(current.get("success_effects") or [])
            current["counter_attack_effects"] = list(current.get("counter_attack_effects") or [])
            current["failure_effects"] = list(current.get("failure_effects") or [])
        tokens.append(current)
    return tokens


def _default_poulpita_panel() -> dict[str, Any]:
    return {
        "image_filename": None,
        "image_width": None,
        "image_height": None,
        "sizes": [{"amount": 1.0, "unit": "kg", "energy_cost": 0}],
        "zones": {
            "neurons": {"x": 0.08, "y": 0.12, "width": 0.38, "height": 0.76},
            "seashells": {"x": 0.54, "y": 0.12, "width": 0.38, "height": 0.76},
        },
    }


def _normalize_zone(zone: dict[str, Any] | None, fallback: dict[str, float]) -> dict[str, float]:
    normalized = {}
    for key in ["x", "y", "width", "height"]:
        value = fallback[key]
        if isinstance(zone, dict) and zone.get(key) is not None:
            value = float(zone.get(key) or 0)
        normalized[key] = min(1.0, max(0.0, value))
    normalized["width"] = max(0.01, min(normalized["width"], 1.0 - normalized["x"]))
    normalized["height"] = max(0.01, min(normalized["height"], 1.0 - normalized["y"]))
    return normalized


def _normalize_poulpita_panel(raw_panel: dict[str, Any]) -> dict[str, Any]:
    default = _default_poulpita_panel()
    zones = raw_panel.get("zones") if isinstance(raw_panel, dict) else {}
    raw_sizes = raw_panel.get("sizes") if isinstance(raw_panel, dict) else None
    sizes = []
    for index, entry in enumerate(raw_sizes or default["sizes"]):
        if not isinstance(entry, dict):
            continue
        amount = max(0.01, float(entry.get("amount") or entry.get("kg") or entry.get("size_kg") or 1))
        unit = str(entry.get("unit") or "kg").lower()
        if unit not in SIZE_UNITS:
            unit = "kg"
        energy_cost = 0 if index == 0 else max(1, int(entry.get("energy_cost") or entry.get("cost") or 1))
        sizes.append({"amount": amount, "unit": unit, "energy_cost": energy_cost})
    if not sizes:
        sizes = deepcopy(default["sizes"])
    sizes[0]["energy_cost"] = 0
    return {
        "image_filename": raw_panel.get("image_filename") if isinstance(raw_panel, dict) else None,
        "image_width": int(raw_panel.get("image_width")) if isinstance(raw_panel, dict) and raw_panel.get("image_width") else None,
        "image_height": int(raw_panel.get("image_height")) if isinstance(raw_panel, dict) and raw_panel.get("image_height") else None,
        "sizes": sizes,
        "zones": {
            zone_id: _normalize_zone((zones or {}).get(zone_id), default["zones"][zone_id])
            for zone_id in POULPITA_PANEL_ZONE_IDS
        },
    }


def _default_player_boards() -> list[dict[str, Any]]:
    return [
        {
            "id": board_id,
            "name": PLAYER_BOARD_DEFAULT_NAMES[board_id],
            "initiates_event_ids": [],
            "deck": [],
            "default_max_cards_in_hand": 3,
            "hand_size_upgrades": [],
            "actions_per_control": 3,
            "control_takes_per_night": 3,
        }
        for board_id in PLAYER_BOARD_ORDER
    ]


def _normalize_player_boards(raw_boards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {str(board.get("id")): dict(board) for board in raw_boards if isinstance(board, dict)}
    boards = []
    for default in _default_player_boards():
        current = {**default, **by_id.get(default["id"], {})}
        current["id"] = default["id"]
        current["name"] = _normalize_name(current.get("name") or default["name"])
        current["initiates_event_ids"] = [str(item) for item in current.get("initiates_event_ids") or []]
        current.pop("initiates_interaction_ids", None)
        current["deck"] = [
            {"interaction_id": str(entry.get("interaction_id") or ""), "count": max(0, int(entry.get("count") or 0))}
            for entry in current.get("deck") or []
            if isinstance(entry, dict) and str(entry.get("interaction_id") or "")
        ]
        current["default_max_cards_in_hand"] = max(1, int(current.get("default_max_cards_in_hand") or 3))
        upgrades = []
        for entry in current.get("hand_size_upgrades") or []:
            if not isinstance(entry, dict):
                continue
            upgrade_type = str(entry.get("type") or "hand_size")
            if upgrade_type == "deck_exchange":
                upgrades.append(
                    {
                        "type": "deck_exchange",
                        "cost_resource": "neurons",
                        "cost": max(1, int(entry.get("cost") or 1)),
                        "remove_cards": [
                            {"interaction_id": str(card.get("interaction_id") or ""), "count": max(0, int(card.get("count") or 0))}
                            for card in entry.get("remove_cards") or []
                            if isinstance(card, dict) and str(card.get("interaction_id") or "")
                        ],
                        "add_cards": [
                            {
                                "interaction_ids": [str(interaction_id) for interaction_id in (card.get("interaction_ids") or [])][:2],
                                "count": max(0, int(card.get("count") or 0)),
                            }
                            for card in entry.get("add_cards") or []
                            if isinstance(card, dict)
                        ],
                    }
                )
            else:
                upgrades.append(
                    {
                        "type": "hand_size",
                        "cost_resource": str(entry.get("cost_resource") or "energy"),
                        "cost": max(1, int(entry.get("cost") or 1)),
                        "hand_size_bonus": max(1, int(entry.get("hand_size_bonus") or 1)),
                    }
                )
        current["hand_size_upgrades"] = upgrades
        current["actions_per_control"] = max(1, int(current.get("actions_per_control") or 3))
        current["control_takes_per_night"] = max(1, int(current.get("control_takes_per_night") or 3))
        boards.append(current)
    return boards


def _public_image_url(filename: str | None) -> str | None:
    if not filename:
        return None
    return f"/static/content/images/{filename}"


def _with_urls(entry: dict[str, Any]) -> dict[str, Any]:
    copy = dict(entry)
    copy["image_url"] = _public_image_url(copy.get("image_filename"))
    return copy


def _poulpita_panel_with_urls(panel: dict[str, Any]) -> dict[str, Any]:
    copy = deepcopy(panel)
    copy["image_url"] = _public_image_url(copy.get("image_filename"))
    return copy


async def _save_uploaded_image(prefix: str, image: UploadFile | None) -> str | None:
    if image is None or not image.filename:
        return None
    suffix = Path(image.filename).suffix.lower()
    if suffix not in ALLOWED_IMAGE_SUFFIXES:
        raise ValueError("Image must be a jpg, png, or webp file.")
    CONTENT_IMAGES_ROOT.mkdir(parents=True, exist_ok=True)
    filename = f"{_slug(prefix)}-{uuid.uuid4().hex[:10]}{suffix}"
    target = CONTENT_IMAGES_ROOT / filename
    with target.open("wb") as handle:
        while chunk := await image.read(1024 * 1024):
            handle.write(chunk)
    return filename


def _delete_image(filename: str | None) -> None:
    if not filename:
        return
    path = CONTENT_IMAGES_ROOT / filename
    if path.exists() and path.is_file():
        path.unlink()


def _find_index(items: list[dict[str, Any]], item_id: str) -> int:
    for index, item in enumerate(items):
        if item.get("id") == item_id:
            return index
    raise LookupError("Content item not found.")


def _normalize_name(name: str) -> str:
    normalized = str(name or "").strip()
    if not normalized:
        raise ValueError("Name is required.")
    return normalized


def _generated_cards(content: dict[str, Any]) -> list[dict[str, Any]]:
    categories = {category["id"]: category for category in content.get("categories", [])}
    events = {event["id"]: event for event in content.get("events", [])}
    cards = []
    for interaction in content.get("interactions", []):
        resolved_by_category = {category_id: [] for category_id in categories}
        resolved_by_category[COUNTER_ATTACK_CATEGORY_ID] = []
        for tile in content.get("tiles", []):
            required_ids = [str(item) for item in tile.get("interaction_ids") or []]
            event = events.get(tile.get("event_id"))
            if event is None:
                continue
            if interaction["id"] in required_ids:
                category_id = event.get("category_id")
                if category_id not in resolved_by_category:
                    resolved_by_category[category_id] = []
                resolved_by_category[category_id].append(
                    {
                        "tile_id": tile["id"],
                        "event_id": event["id"],
                        "event_name": event["name"],
                        "event_image_url": _public_image_url(event.get("image_filename")),
                        "requirement_type": "success",
                    }
                )
            counter_ids = [str(item) for item in tile.get("counter_attack_interaction_ids") or []]
            if interaction["id"] in counter_ids:
                resolved_by_category[COUNTER_ATTACK_CATEGORY_ID].append(
                    {
                        "tile_id": tile["id"],
                        "event_id": event["id"],
                        "event_name": event["name"],
                        "event_image_url": _public_image_url(event.get("image_filename")),
                        "requirement_type": "counter_attack",
                    }
                )
        cards.append(
            {
                "id": interaction["id"],
                "name": interaction["name"],
                "image_url": _public_image_url(interaction.get("image_filename")),
                "resolves": resolved_by_category,
            }
        )
    return cards


def _normalize_surprise_costs(costs: list[dict[str, Any]], interaction_set: set[str], capability_ids: set[str]) -> list[dict[str, Any]]:
    normalized = []
    for cost in costs or []:
        if not isinstance(cost, dict):
            raise ValueError("Surprise costs must be objects.")
        cost_type = str(cost.get("type") or "")
        if cost_type not in SURPRISE_COST_TYPES:
            raise ValueError(f"Unsupported surprise cost: {cost_type or '<missing>'}.")
        if cost_type == "play_cards":
            interaction_ids = []
            for interaction_id in cost.get("interaction_ids") or []:
                interaction_id = str(interaction_id)
                if interaction_id not in interaction_set:
                    raise ValueError("Surprise card cost references an unknown interaction.")
                interaction_ids.append(interaction_id)
            if not interaction_ids:
                raise ValueError("Play-cards surprise cost needs at least one interaction.")
            normalized.append({"type": cost_type, "interaction_ids": interaction_ids})
        elif cost_type == "pay_ap":
            amount = max(1, int(cost.get("amount") or 1))
            capability_id = str(cost.get("capability_id") or "")
            if capability_id and capability_id not in capability_ids:
                raise ValueError("Surprise AP cost references an unknown ability.")
            normalized.append({"type": cost_type, "amount": amount, "capability_id": capability_id})
    return normalized


def _normalize_surprise_effects(effects: list[dict[str, Any]], category_ids: set[str], capability_ids: set[str]) -> list[dict[str, Any]]:
    normalized = []
    for effect in effects or []:
        if not isinstance(effect, dict):
            raise ValueError("Surprise effects must be objects.")
        effect_type = str(effect.get("type") or "")
        if effect_type not in SURPRISE_EFFECT_TYPES:
            raise ValueError(f"Unsupported surprise effect: {effect_type or '<missing>'}.")
        entry: dict[str, Any] = {"type": effect_type}
        if effect_type in {"gain_ap", "gain_neurons", "advance_night", "gain_energy", "lose_energy"}:
            entry["amount"] = max(1, int(effect.get("amount") or 1))
        if effect_type == "gain_ap":
            capability_id = str(effect.get("capability_id") or "")
            if capability_id not in capability_ids:
                raise ValueError("Gain AP surprise effect requires an ability.")
            entry["capability_id"] = capability_id
        if effect_type in {"remove_tiles_category_here", "remove_tiles_category_adjacent"}:
            category_id = str(effect.get("category_id") or "")
            if category_id not in category_ids:
                raise ValueError("Remove-tile surprise effect requires an existing category.")
            entry["category_id"] = category_id
        normalized.append(entry)
    return normalized


def _surprise_card_with_urls(card: dict[str, Any]) -> dict[str, Any]:
    return _with_urls(card)


def get_content_state() -> dict[str, Any]:
    content = _read_content()
    return {
        "categories": [dict(category) for category in content.get("categories", [])],
        "card_categories": [dict(category) for category in content.get("categories", [])] + [dict(COUNTER_ATTACK_CATEGORY)],
        "interactions": [_with_urls(interaction) for interaction in content.get("interactions", [])],
        "events": [_with_urls(event) for event in content.get("events", [])],
        "tiles": [dict(tile) for tile in content.get("tiles", [])],
        "levels": [dict(level) for level in content.get("levels", [])],
        "surprise_cards": [_surprise_card_with_urls(card) for card in content.get("surprise_cards", [])],
        "surprise_decks": [dict(deck) for deck in content.get("surprise_decks", [])],
        "player_boards": [dict(board) for board in content.get("player_boards", [])],
        "tokens": [_with_urls(token) for token in content.get("tokens", [])],
        "poulpita_panel": _poulpita_panel_with_urls(content.get("poulpita_panel") or _default_poulpita_panel()),
        "action_costs": deepcopy(content.get("action_costs") or DEFAULT_ACTION_COSTS),
        "cards": _generated_cards(content),
    }


def export_admin_content_package(*, maps: list[dict[str, Any]]) -> dict[str, Any]:
    content = _read_content()
    return {
        "schema": "maviedepoulpe.admin-content.v1",
        "maps": maps,
        "content": _strip_image_fields(
            {
                **{key: content.get(key, []) for key in ADMIN_CONTENT_COLLECTION_KEYS},
                "poulpita_panel": content.get("poulpita_panel") or _default_poulpita_panel(),
                "action_costs": content.get("action_costs") or DEFAULT_ACTION_COSTS,
            }
        ),
    }


def import_admin_content_package(package: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(package, dict):
        raise ValueError("Import file must contain a JSON object.")
    imported_content = package.get("content")
    if imported_content is None:
        imported_content = {
            key: package.get(key)
            for key in [*ADMIN_CONTENT_COLLECTION_KEYS, "poulpita_panel", "action_costs"]
            if key in package
        }
    if not isinstance(imported_content, dict):
        raise ValueError("content must be a JSON object.")

    content = _read_content()
    summary = {"created": {}, "updated": {}}
    for key in ADMIN_CONTENT_COLLECTION_KEYS:
        if key not in imported_content:
            continue
        merged, created, updated = _merge_items_by_id(content.get(key) or [], imported_content.get(key) or [], key)
        content[key] = merged
        summary["created"][key] = created
        summary["updated"][key] = updated
    if "poulpita_panel" in imported_content:
        panel = _strip_image_fields(imported_content.get("poulpita_panel") or {})
        if not isinstance(panel, dict):
            raise ValueError("poulpita_panel must be a JSON object.")
        content["poulpita_panel"] = _normalize_poulpita_panel(panel)
        summary["updated"]["poulpita_panel"] = 1
    if "action_costs" in imported_content:
        action_costs = imported_content.get("action_costs") or {}
        if not isinstance(action_costs, dict):
            raise ValueError("action_costs must be a JSON object.")
        content["action_costs"] = _normalize_action_costs(action_costs)
        summary["updated"]["action_costs"] = 1
    _write_content(_read_content_from_value(content))
    return summary


def _read_content_from_value(content: dict[str, Any]) -> dict[str, Any]:
    content = dict(content)
    content.setdefault("categories", [])
    content.setdefault("interactions", [])
    content.setdefault("events", [])
    content.setdefault("tiles", [])
    content.setdefault("levels", [])
    content.setdefault("surprise_cards", [])
    content.setdefault("surprise_decks", [])
    content["action_costs"] = _normalize_action_costs(content.get("action_costs") or {})
    content["player_boards"] = _normalize_player_boards(content.get("player_boards") or [])
    content["tokens"] = _normalize_tokens(content.get("tokens") or [])
    content["poulpita_panel"] = _normalize_poulpita_panel(content.get("poulpita_panel") or {})
    for category in content["categories"]:
        category["compulsory_on_same_node"] = bool(category.get("compulsory_on_same_node") or False)
    for tile in content["tiles"]:
        tile["priority"] = int(tile.get("priority") or 0)
        tile.setdefault("interaction_ids", [])
        tile["shell_requirement_count"] = max(0, int(tile.get("shell_requirement_count") or 0))
        tile.setdefault("counter_attack_interaction_ids", [])
        tile.setdefault("success_effects", [])
        tile.setdefault("counter_attack_effects", [])
        tile.setdefault("failure_effects", [])
    for level in content["levels"]:
        level["objectives"] = _normalize_level_objectives(level.get("objectives") or [])
        level["starting_energy"] = max(0, min(32, int(level.get("starting_energy") or 3)))
    return content


def _normalize_action_costs(raw_costs: dict[str, Any]) -> dict[str, dict[str, int]]:
    normalized = deepcopy(DEFAULT_ACTION_COSTS)
    if not isinstance(raw_costs, dict):
        return normalized
    for action_id in ACTION_COST_KEYS:
        raw = raw_costs.get(action_id) or {}
        if not isinstance(raw, dict):
            continue
        normalized[action_id] = {
            "ap_cost": max(0, int(raw.get("ap_cost") if raw.get("ap_cost") is not None else normalized[action_id]["ap_cost"])),
            "time_cost": max(0, int(raw.get("time_cost") if raw.get("time_cost") is not None else normalized[action_id]["time_cost"])),
        }
    return normalized


def get_player_board_configs() -> list[dict[str, Any]]:
    return [dict(board) for board in _read_content().get("player_boards", [])]


def get_level_configs() -> list[dict[str, Any]]:
    return [dict(level) for level in _read_content().get("levels", [])]


def get_level_config(level_id: str | None = None) -> dict[str, Any]:
    levels = get_level_configs()
    if not levels:
        raise LookupError("No levels available. Create a level in the admin console first.")
    if not level_id:
        return dict(levels[0])
    for level in levels:
        if level.get("id") == level_id:
            return dict(level)
    raise LookupError("Level not found.")


async def update_token(
    *,
    token_id: str,
    image: UploadFile | None,
    priority: int | None = None,
    interaction_ids: list[str] | None = None,
    counter_attack_interaction_ids: list[str] | None = None,
    success_effects: list[dict[str, Any]] | None = None,
    counter_attack_effects: list[dict[str, Any]] | None = None,
    failure_effects: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    content = _read_content()
    index = _find_index(content["tokens"], token_id)
    current = content["tokens"][index]
    image_filename = current.get("image_filename")
    next_image = await _save_uploaded_image(f"token-{token_id}", image)
    if next_image:
        _delete_image(image_filename)
        image_filename = next_image
    current["image_filename"] = image_filename
    if token_id == OCTOPUS_TOKEN_ID:
        interaction_set = {interaction.get("id") for interaction in content["interactions"]}
        category_ids = {category.get("id") for category in content["categories"]}
        current["priority"] = int(priority if priority is not None else current.get("priority") or 0)
        current["interaction_ids"] = _normalize_interaction_ids(
            interaction_ids if interaction_ids is not None else current.get("interaction_ids") or [],
            interaction_set,
        )
        current["counter_attack_interaction_ids"] = _normalize_interaction_ids(
            counter_attack_interaction_ids
            if counter_attack_interaction_ids is not None
            else current.get("counter_attack_interaction_ids") or [],
            interaction_set,
        )
        current["success_effects"] = _normalize_effects(
            success_effects if success_effects is not None else current.get("success_effects") or [],
            SUCCESS_EFFECT_TYPES,
            "octopus success",
        )
        current["counter_attack_effects"] = _normalize_effects(
            counter_attack_effects if counter_attack_effects is not None else current.get("counter_attack_effects") or [],
            SUCCESS_EFFECT_TYPES,
            "octopus counter-attack",
        )
        current["failure_effects"] = _normalize_effects(
            failure_effects if failure_effects is not None else current.get("failure_effects") or [],
            FAILURE_EFFECT_TYPES,
            "octopus failure",
            category_ids=category_ids,
        )
    content["tokens"][index] = current
    _write_content(content)
    return _with_urls(current)


async def update_poulpita_panel(
    *,
    zones: dict[str, Any],
    sizes: list[dict[str, Any]] | None = None,
    image: UploadFile | None,
    image_width: int | None = None,
    image_height: int | None = None,
) -> dict[str, Any]:
    content = _read_content()
    current = content.get("poulpita_panel") or _default_poulpita_panel()
    image_filename = current.get("image_filename")
    next_image = await _save_uploaded_image("poulpita-panel", image)
    if next_image:
        _delete_image(image_filename)
        image_filename = next_image
    next_panel = _normalize_poulpita_panel(
        {
            "image_filename": image_filename,
            "image_width": image_width or current.get("image_width"),
            "image_height": image_height or current.get("image_height"),
            "sizes": sizes if sizes is not None else current.get("sizes"),
            "zones": zones,
        }
    )
    content["poulpita_panel"] = next_panel
    _write_content(content)
    return _poulpita_panel_with_urls(next_panel)


def get_game_content_catalog() -> dict[str, dict[str, Any]]:
    content = _read_content()
    return {
        "tiles": {tile["id"]: dict(tile) for tile in content.get("tiles", [])},
        "categories": {category["id"]: dict(category) for category in content.get("categories", [])},
        "events": {event["id"]: _with_urls(event) for event in content.get("events", [])},
        "interactions": {interaction["id"]: _with_urls(interaction) for interaction in content.get("interactions", [])},
        "cards": {card["id"]: card for card in _generated_cards(content)},
        "surprise_cards": {card["id"]: _surprise_card_with_urls(card) for card in content.get("surprise_cards", [])},
        "surprise_decks": {deck["id"]: dict(deck) for deck in content.get("surprise_decks", [])},
        "card_categories": [dict(category) for category in content.get("categories", [])] + [dict(COUNTER_ATTACK_CATEGORY)],
        "tokens": {token["id"]: _with_urls(token) for token in content.get("tokens", [])},
        "poulpita_panel": _poulpita_panel_with_urls(content.get("poulpita_panel") or _default_poulpita_panel()),
        "action_costs": deepcopy(content.get("action_costs") or DEFAULT_ACTION_COSTS),
    }


def update_action_costs(action_costs: dict[str, Any]) -> dict[str, dict[str, int]]:
    content = _read_content()
    content["action_costs"] = _normalize_action_costs(action_costs)
    _write_content(content)
    return deepcopy(content["action_costs"])


def create_category(*, name: str, compulsory_on_same_node: bool = False) -> dict[str, Any]:
    content = _read_content()
    normalized_name = _normalize_name(name)
    category_id = f"{_slug(normalized_name)}-{uuid.uuid4().hex[:8]}"
    category = {"id": category_id, "name": normalized_name, "compulsory_on_same_node": bool(compulsory_on_same_node)}
    content["categories"].append(category)
    _write_content(content)
    return category


def update_category(*, category_id: str, name: str, compulsory_on_same_node: bool = False) -> dict[str, Any]:
    content = _read_content()
    index = _find_index(content["categories"], category_id)
    content["categories"][index]["name"] = _normalize_name(name)
    content["categories"][index]["compulsory_on_same_node"] = bool(compulsory_on_same_node)
    _write_content(content)
    return dict(content["categories"][index])


def delete_category(category_id: str) -> None:
    content = _read_content()
    if any(event.get("category_id") == category_id for event in content["events"]):
        raise ValueError("Category is used by one or more events.")
    if any(
        effect.get("type") == "remove_preys" and effect.get("category_id") == category_id
        for tile in content["tiles"]
        for effect in (tile.get("failure_effects") or [])
    ):
        raise ValueError("Category is used by one or more tile effects.")
    index = _find_index(content["categories"], category_id)
    del content["categories"][index]
    _write_content(content)


async def create_interaction(*, name: str, image: UploadFile) -> dict[str, Any]:
    content = _read_content()
    normalized_name = _normalize_name(name)
    interaction_id = f"{_slug(normalized_name)}-{uuid.uuid4().hex[:8]}"
    image_filename = await _save_uploaded_image(interaction_id, image)
    if not image_filename:
        raise ValueError("Interaction image is required.")
    interaction = {"id": interaction_id, "name": normalized_name, "image_filename": image_filename}
    content["interactions"].append(interaction)
    _write_content(content)
    return _with_urls(interaction)


async def update_interaction(*, interaction_id: str, name: str, image: UploadFile | None) -> dict[str, Any]:
    content = _read_content()
    index = _find_index(content["interactions"], interaction_id)
    current = content["interactions"][index]
    image_filename = current.get("image_filename")
    next_image = await _save_uploaded_image(interaction_id, image)
    if next_image:
        _delete_image(image_filename)
        image_filename = next_image
    current.update({"name": _normalize_name(name), "image_filename": image_filename})
    _write_content(content)
    return _with_urls(current)


def delete_interaction(interaction_id: str) -> None:
    content = _read_content()
    if any(
        interaction_id in (tile.get("interaction_ids") or [])
        or interaction_id in (tile.get("counter_attack_interaction_ids") or [])
        for tile in content["tiles"]
    ) or any(
        any(entry.get("interaction_id") == interaction_id for entry in board.get("deck") or [])
        for board in content["player_boards"]
    ):
        raise ValueError("Interaction is used by one or more tiles.")
    index = _find_index(content["interactions"], interaction_id)
    _delete_image(content["interactions"][index].get("image_filename"))
    del content["interactions"][index]
    _write_content(content)


async def create_event(*, name: str, category_id: str, image: UploadFile) -> dict[str, Any]:
    content = _read_content()
    if not any(category.get("id") == category_id for category in content["categories"]):
        raise ValueError("Event category does not exist.")
    normalized_name = _normalize_name(name)
    event_id = f"{_slug(normalized_name)}-{uuid.uuid4().hex[:8]}"
    image_filename = await _save_uploaded_image(event_id, image)
    if not image_filename:
        raise ValueError("Event image is required.")
    event = {"id": event_id, "name": normalized_name, "category_id": category_id, "image_filename": image_filename}
    content["events"].append(event)
    _write_content(content)
    return _with_urls(event)


async def update_event(*, event_id: str, name: str, category_id: str, image: UploadFile | None) -> dict[str, Any]:
    content = _read_content()
    if not any(category.get("id") == category_id for category in content["categories"]):
        raise ValueError("Event category does not exist.")
    index = _find_index(content["events"], event_id)
    current = content["events"][index]
    image_filename = current.get("image_filename")
    next_image = await _save_uploaded_image(event_id, image)
    if next_image:
        _delete_image(image_filename)
        image_filename = next_image
    current.update({"name": _normalize_name(name), "category_id": category_id, "image_filename": image_filename})
    _write_content(content)
    return _with_urls(current)


def delete_event(event_id: str) -> None:
    content = _read_content()
    if any(tile.get("event_id") == event_id for tile in content["tiles"]) or any(
        event_id in (board.get("initiates_event_ids") or [])
        for board in content["player_boards"]
    ):
        raise ValueError("Event is used by one or more tiles or player boards.")
    index = _find_index(content["events"], event_id)
    _delete_image(content["events"][index].get("image_filename"))
    del content["events"][index]
    _write_content(content)


async def save_surprise_card(
    *,
    name: str,
    costs: list[dict[str, Any]] | None = None,
    effects: list[dict[str, Any]] | None = None,
    image: UploadFile | None = None,
    card_id: str | None = None,
) -> dict[str, Any]:
    content = _read_content()
    interaction_set = {interaction.get("id") for interaction in content["interactions"]}
    category_ids = {category.get("id") for category in content["categories"]}
    capability_ids = set(PLAYER_BOARD_ORDER)
    image_filename = None
    if card_id:
        current = content["surprise_cards"][_find_index(content["surprise_cards"], card_id)]
        image_filename = current.get("image_filename")
    next_image = await _save_uploaded_image(f"surprise-{name}", image)
    if next_image:
        _delete_image(image_filename)
        image_filename = next_image
    card = {
        "id": card_id or f"{_slug(name)}-{uuid.uuid4().hex[:8]}",
        "name": _normalize_name(name),
        "image_filename": image_filename,
        "costs": _normalize_surprise_costs(costs or [], interaction_set, capability_ids),
        "effects": _normalize_surprise_effects(effects or [], category_ids, capability_ids),
    }
    if card_id:
        content["surprise_cards"][_find_index(content["surprise_cards"], card_id)] = card
    else:
        content["surprise_cards"].append(card)
    _write_content(content)
    return _surprise_card_with_urls(card)


def delete_surprise_card(card_id: str) -> None:
    content = _read_content()
    if any(card_id in (deck.get("card_ids") or []) for deck in content.get("surprise_decks", [])):
        raise ValueError("Surprise card is used by one or more decks.")
    index = _find_index(content["surprise_cards"], card_id)
    _delete_image(content["surprise_cards"][index].get("image_filename"))
    del content["surprise_cards"][index]
    _write_content(content)


def save_surprise_deck(*, name: str, card_ids: list[str], deck_id: str | None = None) -> dict[str, Any]:
    content = _read_content()
    card_set = {card.get("id") for card in content.get("surprise_cards", [])}
    normalized_card_ids = []
    for card_id in card_ids or []:
        card_id = str(card_id)
        if card_id not in card_set:
            raise ValueError("Surprise deck references an unknown card.")
        normalized_card_ids.append(card_id)
    deck = {
        "id": deck_id or f"{_slug(name)}-{uuid.uuid4().hex[:8]}",
        "name": _normalize_name(name),
        "card_ids": normalized_card_ids,
    }
    if deck_id:
        content["surprise_decks"][_find_index(content["surprise_decks"], deck_id)] = deck
    else:
        content["surprise_decks"].append(deck)
    _write_content(content)
    return dict(deck)


def delete_surprise_deck(deck_id: str) -> None:
    content = _read_content()
    if any(level.get("surprise_deck_id") == deck_id for level in content.get("levels", [])):
        raise ValueError("Surprise deck is used by one or more levels.")
    index = _find_index(content["surprise_decks"], deck_id)
    del content["surprise_decks"][index]
    _write_content(content)


def _normalize_interaction_ids(interaction_ids: list[str], interaction_set: set[str]) -> list[str]:
    normalized = []
    for interaction_id in interaction_ids:
        if interaction_id not in interaction_set:
            raise ValueError("Tile references an unknown interaction.")
        if interaction_id not in normalized:
            normalized.append(interaction_id)
    return normalized


def _normalize_event_ids(event_ids: list[str], event_set: set[str]) -> list[str]:
    normalized = []
    for event_id in event_ids:
        if event_id not in event_set:
            raise ValueError("Player board references an unknown event.")
        if event_id not in normalized:
            normalized.append(event_id)
    return normalized


def _normalize_effects(
    effects: list[dict[str, Any]],
    allowed_types: set[str],
    label: str,
    *,
    category_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    normalized = []
    for effect in effects or []:
        if not isinstance(effect, dict):
            raise ValueError(f"{label} effects must be objects.")
        effect_type = str(effect.get("type") or "")
        if effect_type not in allowed_types:
            raise ValueError(f"Unsupported {label} effect: {effect_type or '<missing>'}.")
        if effect_type == "remove_preys":
            category_id = str(effect.get("category_id") or "")
            if not category_id or category_id not in (category_ids or set()):
                raise ValueError("remove_preys requires an existing category.")
            normalized.append({"type": effect_type, "amount": None, "category_id": category_id})
            continue
        amount = int(effect.get("amount") or 0)
        no_amount_types = {
            "place_shelter_token",
            "draw_surprise_card",
            "lose_half_ap",
            "lose_all_ap",
            "pulpita_move_previous",
            "pulpita_move_free",
            "keep_tile",
            "remove_tile",
            "move_tile_previous",
        }
        if effect_type not in no_amount_types and amount < 1:
            raise ValueError(f"{label} effect amount must be at least 1.")
        normalized.append({"type": effect_type, "amount": None if effect_type in no_amount_types else amount})
    return normalized


def save_tile(
    *,
    name: str,
    event_id: str,
    priority: int = 0,
    shell_requirement_count: int = 0,
    interaction_ids: list[str],
    counter_attack_interaction_ids: list[str] | None = None,
    success_effects: list[dict[str, Any]] | None = None,
    counter_attack_effects: list[dict[str, Any]] | None = None,
    failure_effects: list[dict[str, Any]] | None = None,
    tile_id: str | None = None,
) -> dict[str, Any]:
    content = _read_content()
    if not any(event.get("id") == event_id for event in content["events"]):
        raise ValueError("Tile event does not exist.")
    interaction_set = {interaction.get("id") for interaction in content["interactions"]}
    category_ids = {category.get("id") for category in content["categories"]}
    normalized_interactions = _normalize_interaction_ids(interaction_ids, interaction_set)
    tile = {
        "id": tile_id or f"{_slug(name)}-{uuid.uuid4().hex[:8]}",
        "name": _normalize_name(name),
        "event_id": event_id,
        "priority": int(priority or 0),
        "shell_requirement_count": max(0, int(shell_requirement_count or 0)),
        "interaction_ids": normalized_interactions,
        "counter_attack_interaction_ids": _normalize_interaction_ids(counter_attack_interaction_ids or [], interaction_set),
        "success_effects": _normalize_effects(success_effects or [], SUCCESS_EFFECT_TYPES, "success"),
        "counter_attack_effects": _normalize_effects(counter_attack_effects or [], SUCCESS_EFFECT_TYPES, "counter-attack"),
        "failure_effects": _normalize_effects(failure_effects or [], FAILURE_EFFECT_TYPES, "failure", category_ids=category_ids),
    }
    if tile_id:
        content["tiles"][_find_index(content["tiles"], tile_id)] = tile
    else:
        content["tiles"].append(tile)
    _write_content(content)
    return dict(tile)


def delete_tile(tile_id: str) -> None:
    content = _read_content()
    if any(
        int((group.get("tile_counts") or {}).get(tile_id) or 0) > 0
        for level in content.get("levels", [])
        for group in level.get("groups", [])
    ):
        raise ValueError("Tile is used by one or more levels.")
    index = _find_index(content["tiles"], tile_id)
    del content["tiles"][index]
    _write_content(content)


def _normalize_node_tile_counts(node_tile_counts: dict[str, Any], node_ids: set[str]) -> dict[str, int]:
    normalized = {}
    for node_id in node_ids:
        count = int(node_tile_counts.get(node_id, 3))
        if count < 0:
            raise ValueError("Node tile counts cannot be negative.")
        normalized[node_id] = count
    return normalized


def _normalize_level_node_tokens(node_tokens: dict[str, Any], node_ids: set[str]) -> dict[str, list[dict[str, str]]]:
    normalized: dict[str, list[dict[str, str]]] = {}
    for node_id, raw_tokens in (node_tokens or {}).items():
        node_id = str(node_id)
        if node_id not in node_ids:
            raise ValueError("Level token placement references an unknown node.")
        tokens = []
        seen_types = set()
        if not isinstance(raw_tokens, list):
            raise ValueError("Level node tokens must be JSON arrays.")
        for raw_token in raw_tokens:
            token_type = str(raw_token.get("type") if isinstance(raw_token, dict) else raw_token or "")
            if token_type not in PLACEABLE_LEVEL_TOKEN_IDS:
                raise ValueError("Level token placement references an unknown token type.")
            if token_type in seen_types:
                continue
            seen_types.add(token_type)
            tokens.append({"type": token_type})
        if tokens:
            normalized[node_id] = tokens
    return normalized


def _normalize_level_groups(groups: list[dict[str, Any]], tile_set: set[str]) -> list[dict[str, Any]]:
    normalized = []
    seen_ids = set()
    for index, group in enumerate(groups or []):
        if not isinstance(group, dict):
            raise ValueError("Level groups must be objects.")
        group_id = _slug(str(group.get("id") or group.get("name") or f"group-{index + 1}"))
        if not group_id:
            raise ValueError("Level group ID is required.")
        if group_id in seen_ids:
            raise ValueError("Level group IDs must be unique.")
        seen_ids.add(group_id)
        tile_counts = {}
        for tile_id, raw_count in (group.get("tile_counts") or {}).items():
            tile_id = str(tile_id)
            if tile_id not in tile_set:
                raise ValueError("Level group references an unknown tile.")
            count = int(raw_count or 0)
            if count < 0:
                raise ValueError("Level tile counts cannot be negative.")
            if count:
                tile_counts[tile_id] = count
        normalized.append({"id": group_id, "name": _normalize_name(group.get("name") or group_id), "tile_counts": tile_counts})
    if not normalized:
        raise ValueError("A level needs at least one group.")
    return normalized


def _normalize_level_objectives(objectives: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = []
    for index, objective in enumerate(objectives or []):
        if not isinstance(objective, dict):
            raise ValueError("Level objectives must be objects.")
        objective_type = str(objective.get("type") or "").strip()
        objective_id = str(objective.get("id") or f"objective-{index + 1}")
        if objective_type == "increase_size":
            target = max(1, int(objective.get("target") or objective.get("count") or 1))
            normalized.append({"id": objective_id, "type": objective_type, "target": target})
        elif objective_type in {"find_shelter", "secure_shelter"}:
            normalized.append({"id": objective_id, "type": objective_type})
        elif objective_type:
            raise ValueError(f"Unsupported objective type: {objective_type}.")
    return normalized


def save_level(
    *,
    name: str,
    map_id: str,
    node_tile_counts: dict[str, Any],
    node_group_ids: dict[str, Any],
    groups: list[dict[str, Any]],
    objectives: list[dict[str, Any]] | None = None,
    starting_energy: int | None = None,
    starting_neurons: int | None = None,
    surprise_deck_id: str | None = None,
    poulpita_starting_node_id: str | None = None,
    node_tokens: dict[str, Any] | None = None,
    level_id: str | None = None,
) -> dict[str, Any]:
    content = _read_content()
    map_config = get_map(map_id)
    node_ids = {str(node_id) for node_id in (map_config.get("nodes") or {})}
    if not node_ids:
        raise ValueError("Level map has no nodes.")
    tile_set = {str(tile.get("id")) for tile in content["tiles"]}
    normalized_groups = _normalize_level_groups(groups, tile_set)
    normalized_surprise_deck_id = str(surprise_deck_id or "")
    if normalized_surprise_deck_id and not any(deck.get("id") == normalized_surprise_deck_id for deck in content.get("surprise_decks", [])):
        raise ValueError("Level surprise deck does not exist.")
    group_ids = {group["id"] for group in normalized_groups}
    normalized_counts = _normalize_node_tile_counts(node_tile_counts or {}, node_ids)
    normalized_node_groups = {}
    for node_id in node_ids:
        group_id = str((node_group_ids or {}).get(node_id) or "")
        if group_id not in group_ids:
            raise ValueError("Every map node must belong to a level group.")
        normalized_node_groups[node_id] = group_id
    normalized_starting_node_id = str(poulpita_starting_node_id or map_config.get("starting_node_id") or sorted(node_ids)[0])
    if normalized_starting_node_id not in node_ids:
        raise ValueError("Poulpita starting node must be one of the map nodes.")
    for group in normalized_groups:
        capacity = sum(count for node_id, count in normalized_counts.items() if normalized_node_groups[node_id] == group["id"])
        assigned = sum(int(count or 0) for count in (group.get("tile_counts") or {}).values())
        if assigned != capacity:
            raise ValueError(f"Group {group['name']} has {assigned} assigned tiles but needs {capacity}.")
    level = {
        "id": level_id or f"{_slug(name)}-{uuid.uuid4().hex[:8]}",
        "name": _normalize_name(name),
        "map_id": str(map_id),
        "node_tile_counts": normalized_counts,
        "node_group_ids": normalized_node_groups,
        "groups": normalized_groups,
        "objectives": _normalize_level_objectives(objectives or []),
        "starting_energy": max(0, min(32, int(starting_energy if starting_energy is not None else 3))),
        "starting_neurons": max(0, int(starting_neurons if starting_neurons is not None else 0)),
        "surprise_deck_id": normalized_surprise_deck_id,
        "poulpita_starting_node_id": normalized_starting_node_id,
        "node_tokens": _normalize_level_node_tokens(node_tokens or {}, node_ids),
    }
    if level_id:
        content["levels"][_find_index(content["levels"], level_id)] = level
    else:
        content["levels"].append(level)
    _write_content(content)
    return dict(level)


def delete_level(level_id: str) -> None:
    content = _read_content()
    index = _find_index(content["levels"], level_id)
    del content["levels"][index]
    _write_content(content)


def save_player_board(
    *,
    board_id: str,
    name: str,
    initiates_event_ids: list[str],
    deck: list[dict[str, Any]],
    default_max_cards_in_hand: int,
    hand_size_upgrades: list[dict[str, Any]],
    actions_per_control: int,
    control_takes_per_night: int,
) -> dict[str, Any]:
    content = _read_content()
    if board_id not in PLAYER_BOARD_ORDER:
        raise ValueError("Unknown player board.")
    interaction_set = {interaction.get("id") for interaction in content["interactions"]}
    event_set = {event.get("id") for event in content["events"]}
    normalized_initiates = _normalize_event_ids(initiates_event_ids, event_set)
    normalized_deck = []
    for entry in deck or []:
        if not isinstance(entry, dict):
            raise ValueError("Deck entries must be objects.")
        interaction_id = str(entry.get("interaction_id") or "")
        if interaction_id not in interaction_set:
            raise ValueError("Deck references an unknown interaction.")
        count = int(entry.get("count") or 0)
        if count < 0:
            raise ValueError("Deck counts cannot be negative.")
        if count:
            normalized_deck.append({"interaction_id": interaction_id, "count": count})
    deck_counts = {entry["interaction_id"]: int(entry.get("count") or 0) for entry in normalized_deck}
    normalized_upgrades = []
    for entry in hand_size_upgrades or []:
        if not isinstance(entry, dict):
            raise ValueError("Upgrade entries must be objects.")
        upgrade_type = str(entry.get("type") or "hand_size")
        cost_resource = str(entry.get("cost_resource") or "neurons")
        if upgrade_type != "deck_exchange" and cost_resource not in UPGRADE_COST_RESOURCES:
            raise ValueError("Upgrade cost resource must be energy or neurons.")
        cost = int(entry.get("cost") or 0)
        if cost < 1:
            raise ValueError("Upgrade cost must be positive.")
        if upgrade_type == "deck_exchange":
            remove_cards = []
            add_cards = []
            for card_entry in entry.get("remove_cards") or []:
                interaction_id = str(card_entry.get("interaction_id") or "")
                if interaction_id not in interaction_set:
                    raise ValueError("Deck exchange upgrade removes an unknown interaction.")
                count = int(card_entry.get("count") or 0)
                if count < 0:
                    raise ValueError("Deck exchange remove counts cannot be negative.")
                if count > deck_counts.get(interaction_id, 0):
                    raise ValueError("Deck exchange cannot remove more cards than the board deck contains.")
                if count:
                    remove_cards.append({"interaction_id": interaction_id, "count": count})
            for card_entry in entry.get("add_cards") or []:
                interaction_ids = [str(interaction_id) for interaction_id in (card_entry.get("interaction_ids") or [])]
                if len(interaction_ids) != 2 or any(interaction_id not in interaction_set for interaction_id in interaction_ids):
                    raise ValueError("Powerful cards must reference exactly two known interactions.")
                count = int(card_entry.get("count") or 0)
                if count < 0:
                    raise ValueError("Powerful card counts cannot be negative.")
                if count:
                    add_cards.append({"interaction_ids": interaction_ids, "count": count})
            if not remove_cards or not add_cards:
                raise ValueError("Deck exchange upgrades need cards to remove and powerful cards to add.")
            normalized_upgrades.append(
                {
                    "type": "deck_exchange",
                    "cost_resource": "neurons",
                    "cost": cost,
                    "remove_cards": remove_cards,
                    "add_cards": add_cards,
                }
            )
        else:
            hand_size_bonus = int(entry.get("hand_size_bonus") or 1)
            if hand_size_bonus < 1:
                raise ValueError("Hand size bonus must be positive.")
            normalized_upgrades.append(
                {"type": "hand_size", "cost_resource": cost_resource, "cost": cost, "hand_size_bonus": hand_size_bonus}
            )
    next_board = {
        "id": board_id,
        "name": _normalize_name(name),
        "initiates_event_ids": normalized_initiates,
        "deck": normalized_deck,
        "default_max_cards_in_hand": max(1, int(default_max_cards_in_hand or 3)),
        "hand_size_upgrades": normalized_upgrades,
        "actions_per_control": max(1, int(actions_per_control or 3)),
        "control_takes_per_night": max(1, int(control_takes_per_night or 3)),
    }
    content["player_boards"] = [
        next_board if board.get("id") == board_id else board
        for board in _normalize_player_boards(content.get("player_boards") or [])
    ]
    _write_content(content)
    return dict(next_board)


def clear_content_images_for_tests() -> None:
    if CONTENT_IMAGES_ROOT.exists():
        shutil.rmtree(CONTENT_IMAGES_ROOT)
