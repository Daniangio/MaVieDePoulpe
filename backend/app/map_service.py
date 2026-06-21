from __future__ import annotations

import json
import re
import shutil
import uuid
from pathlib import Path
from typing import Any

from fastapi import UploadFile


MAPS_ROOT = Path(__file__).resolve().parents[1] / "data" / "maps"
DEFAULT_MAP_ID = "default-16"
ALLOWED_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


def _builtin_map_path() -> Path:
    return Path(__file__).resolve().parent / "content" / "map.json"


def _slug(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip().lower()).strip("-")
    return normalized[:48] or "map"


def _map_dir(map_id: str) -> Path:
    return MAPS_ROOT / map_id


def _map_json_path(map_id: str) -> Path:
    return _map_dir(map_id) / "map.json"


def _public_image_url(map_id: str, filename: str | None) -> str | None:
    if not filename:
        return None
    return f"/static/maps/{map_id}/{filename}"


def _validate_nodes_and_edges(nodes: dict[str, Any], adjacency: dict[str, Any]) -> None:
    if not nodes:
        raise ValueError("A map needs at least one node.")
    for node_id, node in nodes.items():
        if not isinstance(node_id, str) or not node_id.strip():
            raise ValueError("Node IDs must be non-empty strings.")
        x = float(node.get("x"))
        y = float(node.get("y"))
        if not (0 <= x <= 1 and 0 <= y <= 1):
            raise ValueError(f"Node {node_id} position must be relative coordinates between 0 and 1.")
        int(node.get("tier") or 1)
    for node_id, adjacent_ids in adjacency.items():
        if node_id not in nodes:
            raise ValueError(f"Adjacency references unknown node {node_id}.")
        if not isinstance(adjacent_ids, list):
            raise ValueError(f"Adjacency for node {node_id} must be a list.")
        for adjacent_id in adjacent_ids:
            if adjacent_id not in nodes:
                raise ValueError(f"Adjacency references unknown node {adjacent_id}.")
            if node_id not in (adjacency.get(adjacent_id) or []):
                raise ValueError(f"Adjacency must be symmetric between {node_id} and {adjacent_id}.")


def _normalize_nodes(nodes: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        node_id: {
            "id": node_id,
            "tier": int(node.get("tier") or 1),
            "x": float(node.get("x")),
            "y": float(node.get("y")),
        }
        for node_id, node in nodes.items()
    }


def _normalize_adjacency(nodes: dict[str, Any], adjacency: dict[str, Any]) -> dict[str, list[str]]:
    normalized = {node_id: [] for node_id in nodes}
    for node_id, adjacent_ids in adjacency.items():
        normalized[node_id] = sorted({str(adjacent_id) for adjacent_id in adjacent_ids})
    return normalized


def _with_runtime_urls(map_data: dict[str, Any]) -> dict[str, Any]:
    copy = dict(map_data)
    copy["image_url"] = _public_image_url(copy["id"], copy.get("image_filename"))
    return copy


def load_builtin_map() -> dict[str, Any]:
    with _builtin_map_path().open("r", encoding="utf-8") as handle:
        config = json.load(handle)
    max_x = max(float(node.get("x") or 0) for node in config["nodes"].values()) or 1
    max_y = max(float(node.get("y") or 0) for node in config["nodes"].values()) or 1
    nodes = {
        node_id: {
            "id": node_id,
            "tier": int(node["tier"]),
            "x": float(node.get("x") or 0) / max_x,
            "y": float(node.get("y") or 0) / max_y,
        }
        for node_id, node in config["nodes"].items()
    }
    adjacency = {node_id: list(node.get("adjacent") or []) for node_id, node in config["nodes"].items()}
    return {
        "id": DEFAULT_MAP_ID,
        "name": "Default 16-node map",
        "starting_node_id": config["starting_node_id"],
        "image_filename": None,
        "image_url": None,
        "image_width": None,
        "image_height": None,
        "nodes": nodes,
        "adjacency": adjacency,
    }


def list_maps() -> list[dict[str, Any]]:
    MAPS_ROOT.mkdir(parents=True, exist_ok=True)
    maps = [load_builtin_map()]
    for path in sorted(MAPS_ROOT.glob("*/map.json")):
        with path.open("r", encoding="utf-8") as handle:
            maps.append(_with_runtime_urls(json.load(handle)))
    return maps


def get_map(map_id: str | None) -> dict[str, Any]:
    normalized_id = str(map_id or DEFAULT_MAP_ID)
    if normalized_id == DEFAULT_MAP_ID:
        return load_builtin_map()
    path = _map_json_path(normalized_id)
    if not path.exists():
        raise LookupError("Map not found.")
    with path.open("r", encoding="utf-8") as handle:
        return _with_runtime_urls(json.load(handle))


async def _save_uploaded_image(map_id: str, image: UploadFile) -> str:
    suffix = Path(image.filename or "").suffix.lower()
    if suffix not in ALLOWED_IMAGE_SUFFIXES:
        raise ValueError("Map image must be a jpg, png, or webp file.")
    filename = f"board{suffix}"
    target = _map_dir(map_id) / filename
    with target.open("wb") as handle:
        while chunk := await image.read(1024 * 1024):
            handle.write(chunk)
    return filename


def save_map_data(
    *,
    map_id: str,
    name: str,
    nodes: dict[str, Any],
    adjacency: dict[str, Any],
    image_filename: str | None,
    image_width: int | None,
    image_height: int | None,
    starting_node_id: str | None = None,
) -> dict[str, Any]:
    _validate_nodes_and_edges(nodes, adjacency)
    normalized_nodes = _normalize_nodes(nodes)
    normalized_adjacency = _normalize_adjacency(normalized_nodes, adjacency)
    normalized_start = starting_node_id if starting_node_id in normalized_nodes else next(iter(normalized_nodes))
    map_data = {
        "id": map_id,
        "name": name.strip() or "Untitled map",
        "starting_node_id": normalized_start,
        "image_filename": image_filename,
        "image_width": int(image_width) if image_width else None,
        "image_height": int(image_height) if image_height else None,
        "nodes": normalized_nodes,
        "adjacency": normalized_adjacency,
    }
    _map_dir(map_id).mkdir(parents=True, exist_ok=True)
    with _map_json_path(map_id).open("w", encoding="utf-8") as handle:
        json.dump(map_data, handle, indent=2, sort_keys=True)
    return _with_runtime_urls(map_data)


async def create_map(
    *,
    name: str,
    image: UploadFile,
    nodes: dict[str, Any],
    adjacency: dict[str, Any],
    image_width: int | None,
    image_height: int | None,
    starting_node_id: str | None = None,
) -> dict[str, Any]:
    map_id = f"{_slug(name)}-{uuid.uuid4().hex[:8]}"
    _map_dir(map_id).mkdir(parents=True, exist_ok=False)
    image_filename = await _save_uploaded_image(map_id, image)
    return save_map_data(
        map_id=map_id,
        name=name,
        nodes=nodes,
        adjacency=adjacency,
        image_filename=image_filename,
        image_width=image_width,
        image_height=image_height,
        starting_node_id=starting_node_id,
    )


async def update_map(
    *,
    map_id: str,
    name: str,
    nodes: dict[str, Any],
    adjacency: dict[str, Any],
    image: UploadFile | None,
    image_width: int | None,
    image_height: int | None,
    starting_node_id: str | None = None,
) -> dict[str, Any]:
    if map_id == DEFAULT_MAP_ID:
        raise ValueError("The built-in map cannot be edited.")
    current = get_map(map_id)
    image_filename = current.get("image_filename")
    if image is not None and image.filename:
        image_filename = await _save_uploaded_image(map_id, image)
    return save_map_data(
        map_id=map_id,
        name=name,
        nodes=nodes,
        adjacency=adjacency,
        image_filename=image_filename,
        image_width=image_width,
        image_height=image_height,
        starting_node_id=starting_node_id,
    )


def delete_map(map_id: str) -> None:
    if map_id == DEFAULT_MAP_ID:
        raise ValueError("The built-in map cannot be deleted.")
    path = _map_dir(map_id)
    if not path.exists():
        raise LookupError("Map not found.")
    shutil.rmtree(path)
