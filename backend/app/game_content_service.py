from __future__ import annotations

import json
import re
import shutil
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any

from fastapi import UploadFile


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
FAILURE_EFFECT_TYPES = {"lose_energy", "lose_neurons", "lose_seashells", "lose_ap", "half_ap", "all_ap"}


def _slug(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(value or "").strip().lower()).strip("-")
    return normalized[:48] or "content"


def _empty_content() -> dict[str, Any]:
    return {
        "categories": deepcopy(DEFAULT_CATEGORIES),
        "interactions": [],
        "events": [],
        "tiles": [],
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
    for tile in content["tiles"]:
        tile.setdefault("interaction_ids", [])
        tile.setdefault("counter_attack_interaction_ids", [])
        tile.setdefault("success_effects", [])
        tile.setdefault("counter_attack_effects", [])
        tile.setdefault("failure_effects", [])
    return content


def _public_image_url(filename: str | None) -> str | None:
    if not filename:
        return None
    return f"/static/content/images/{filename}"


def _with_urls(entry: dict[str, Any]) -> dict[str, Any]:
    copy = dict(entry)
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
        "cards": _generated_cards(content),
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
    if any(tile.get("event_id") == event_id for tile in content["tiles"]):
        raise ValueError("Event is used by one or more tiles.")
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


def _normalize_effects(effects: list[dict[str, Any]], allowed_types: set[str], label: str) -> list[dict[str, Any]]:
    normalized = []
    for effect in effects or []:
        if not isinstance(effect, dict):
            raise ValueError(f"{label} effects must be objects.")
        effect_type = str(effect.get("type") or "")
        if effect_type not in allowed_types:
            raise ValueError(f"Unsupported {label} effect: {effect_type or '<missing>'}.")
        amount = int(effect.get("amount") or 0)
        if effect_type not in {"half_ap", "all_ap"} and amount < 1:
            raise ValueError(f"{label} effect amount must be at least 1.")
        normalized.append({"type": effect_type, "amount": None if effect_type in {"half_ap", "all_ap"} else amount})
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
        "failure_effects": _normalize_effects(failure_effects or [], FAILURE_EFFECT_TYPES, "failure"),
    }
    if tile_id:
        content["tiles"][_find_index(content["tiles"], tile_id)] = tile
    else:
        content["tiles"].append(tile)
    _write_content(content)
    return dict(tile)


def delete_tile(tile_id: str) -> None:
    content = _read_content()
    index = _find_index(content["tiles"], tile_id)
    del content["tiles"][index]
    _write_content(content)


def clear_content_images_for_tests() -> None:
    if CONTENT_IMAGES_ROOT.exists():
        shutil.rmtree(CONTENT_IMAGES_ROOT)
