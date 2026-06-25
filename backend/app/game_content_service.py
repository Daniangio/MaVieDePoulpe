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
SUCCESS_EFFECT_TYPES = {"gain_energy", "gain_neurons", "gain_seashells"}
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
]
POULPITA_PANEL_ZONE_IDS = {"neurons", "seashells"}


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
        "player_boards": _default_player_boards(),
        "tokens": _default_tokens(),
        "poulpita_panel": _default_poulpita_panel(),
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


def _read_content() -> dict[str, Any]:
    _ensure_content()
    with CONTENT_JSON_PATH.open("r", encoding="utf-8") as handle:
        content = json.load(handle)
    content.setdefault("categories", [])
    content.setdefault("interactions", [])
    content.setdefault("events", [])
    content.setdefault("tiles", [])
    content.setdefault("levels", [])
    content["player_boards"] = _normalize_player_boards(content.get("player_boards") or [])
    content["tokens"] = _normalize_tokens(content.get("tokens") or [])
    content["poulpita_panel"] = _normalize_poulpita_panel(content.get("poulpita_panel") or {})
    for tile in content["tiles"]:
        tile.setdefault("interaction_ids", [])
        tile.setdefault("counter_attack_interaction_ids", [])
        tile.setdefault("success_effects", [])
        tile.setdefault("counter_attack_effects", [])
        tile.setdefault("failure_effects", [])
    return content


def _default_tokens() -> list[dict[str, Any]]:
    return [{**token, "image_filename": None} for token in TOKEN_TYPES]


def _normalize_tokens(raw_tokens: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {str(token.get("id")): dict(token) for token in raw_tokens if isinstance(token, dict)}
    tokens = []
    for default in _default_tokens():
        current = {**default, **by_id.get(default["id"], {})}
        current["id"] = default["id"]
        current["name"] = default["name"]
        current["image_filename"] = current.get("image_filename") or None
        tokens.append(current)
    return tokens


def _default_poulpita_panel() -> dict[str, Any]:
    return {
        "image_filename": None,
        "image_width": None,
        "image_height": None,
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
    return {
        "image_filename": raw_panel.get("image_filename") if isinstance(raw_panel, dict) else None,
        "image_width": int(raw_panel.get("image_width")) if isinstance(raw_panel, dict) and raw_panel.get("image_width") else None,
        "image_height": int(raw_panel.get("image_height")) if isinstance(raw_panel, dict) and raw_panel.get("image_height") else None,
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
        current["hand_size_upgrades"] = [
            {
                "cost_resource": str(entry.get("cost_resource") or "energy"),
                "cost": max(1, int(entry.get("cost") or 1)),
                "hand_size_bonus": max(1, int(entry.get("hand_size_bonus") or 1)),
            }
            for entry in current.get("hand_size_upgrades") or []
            if isinstance(entry, dict)
        ]
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


def get_content_state() -> dict[str, Any]:
    content = _read_content()
    return {
        "categories": [dict(category) for category in content.get("categories", [])],
        "card_categories": [dict(category) for category in content.get("categories", [])] + [dict(COUNTER_ATTACK_CATEGORY)],
        "interactions": [_with_urls(interaction) for interaction in content.get("interactions", [])],
        "events": [_with_urls(event) for event in content.get("events", [])],
        "tiles": [dict(tile) for tile in content.get("tiles", [])],
        "levels": [dict(level) for level in content.get("levels", [])],
        "player_boards": [dict(board) for board in content.get("player_boards", [])],
        "tokens": [_with_urls(token) for token in content.get("tokens", [])],
        "poulpita_panel": _poulpita_panel_with_urls(content.get("poulpita_panel") or _default_poulpita_panel()),
        "cards": _generated_cards(content),
    }


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


async def update_token(*, token_id: str, image: UploadFile | None) -> dict[str, Any]:
    content = _read_content()
    index = _find_index(content["tokens"], token_id)
    current = content["tokens"][index]
    image_filename = current.get("image_filename")
    next_image = await _save_uploaded_image(f"token-{token_id}", image)
    if next_image:
        _delete_image(image_filename)
        image_filename = next_image
    current["image_filename"] = image_filename
    content["tokens"][index] = current
    _write_content(content)
    return _with_urls(current)


async def update_poulpita_panel(
    *,
    zones: dict[str, Any],
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
        "events": {event["id"]: _with_urls(event) for event in content.get("events", [])},
        "interactions": {interaction["id"]: _with_urls(interaction) for interaction in content.get("interactions", [])},
        "cards": {card["id"]: card for card in _generated_cards(content)},
        "card_categories": [dict(category) for category in content.get("categories", [])] + [dict(COUNTER_ATTACK_CATEGORY)],
        "tokens": {token["id"]: _with_urls(token) for token in content.get("tokens", [])},
        "poulpita_panel": _poulpita_panel_with_urls(content.get("poulpita_panel") or _default_poulpita_panel()),
    }


def create_category(*, name: str) -> dict[str, Any]:
    content = _read_content()
    normalized_name = _normalize_name(name)
    category_id = f"{_slug(normalized_name)}-{uuid.uuid4().hex[:8]}"
    category = {"id": category_id, "name": normalized_name}
    content["categories"].append(category)
    _write_content(content)
    return category


def update_category(*, category_id: str, name: str) -> dict[str, Any]:
    content = _read_content()
    index = _find_index(content["categories"], category_id)
    content["categories"][index]["name"] = _normalize_name(name)
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
    if not normalized_interactions:
        raise ValueError("A tile needs at least one required interaction.")
    tile = {
        "id": tile_id or f"{_slug(name)}-{uuid.uuid4().hex[:8]}",
        "name": _normalize_name(name),
        "event_id": event_id,
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


def save_level(
    *,
    name: str,
    map_id: str,
    node_tile_counts: dict[str, Any],
    node_group_ids: dict[str, Any],
    groups: list[dict[str, Any]],
    level_id: str | None = None,
) -> dict[str, Any]:
    content = _read_content()
    map_config = get_map(map_id)
    node_ids = {str(node_id) for node_id in (map_config.get("nodes") or {})}
    if not node_ids:
        raise ValueError("Level map has no nodes.")
    tile_set = {str(tile.get("id")) for tile in content["tiles"]}
    normalized_groups = _normalize_level_groups(groups, tile_set)
    group_ids = {group["id"] for group in normalized_groups}
    normalized_counts = _normalize_node_tile_counts(node_tile_counts or {}, node_ids)
    normalized_node_groups = {}
    for node_id in node_ids:
        group_id = str((node_group_ids or {}).get(node_id) or "")
        if group_id not in group_ids:
            raise ValueError("Every map node must belong to a level group.")
        normalized_node_groups[node_id] = group_id
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
    normalized_upgrades = []
    for entry in hand_size_upgrades or []:
        if not isinstance(entry, dict):
            raise ValueError("Upgrade entries must be objects.")
        cost_resource = str(entry.get("cost_resource") or "")
        if cost_resource not in UPGRADE_COST_RESOURCES:
            raise ValueError("Upgrade cost resource must be energy or neurons.")
        cost = int(entry.get("cost") or 0)
        hand_size_bonus = int(entry.get("hand_size_bonus") or 1)
        if cost < 1 or hand_size_bonus < 1:
            raise ValueError("Upgrade cost and hand size bonus must be positive.")
        normalized_upgrades.append(
            {"cost_resource": cost_resource, "cost": cost, "hand_size_bonus": hand_size_bonus}
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
