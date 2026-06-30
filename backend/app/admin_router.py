from __future__ import annotations

import json

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import get_db
from .db_models import AdminAuditLogRecord, UserProfileRecord
from .friend_service import list_friends_summary
from .game_content_service import (
    create_category,
    create_event,
    create_interaction,
    delete_category,
    delete_event,
    delete_interaction,
    delete_level,
    delete_surprise_card,
    delete_surprise_deck,
    delete_tile,
    export_admin_content_package,
    get_content_state,
    import_admin_content_package,
    save_level,
    save_surprise_card,
    save_surprise_deck,
    save_tile,
    save_player_board,
    update_token,
    update_poulpita_panel,
    update_category,
    update_event,
    update_interaction,
)
from .map_service import create_map, delete_map, export_maps_data, get_map, import_maps_data, list_maps, update_map
from .runtime_state import get_presence_service
from .schemas import (
    AdminAuditLogEntry,
    AdminMutationStatus,
    AdminUserAdminUpdate,
    AdminUserDetail,
    AdminUserSummary,
    UserPublic,
)
from .security import get_current_user
from .server_models import User
from .user_repository import get_registered_user_by_id, list_registered_users


router = APIRouter()


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if not current_user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return current_user


def _record_admin_audit(
    db: Session,
    *,
    admin: User,
    action: str,
    target_type: str,
    target_id: str,
    payload: dict | None = None,
) -> AdminAuditLogRecord:
    row = AdminAuditLogRecord(
        admin_user_id=admin.id,
        admin_username=admin.username,
        action=action,
        target_type=target_type,
        target_id=target_id,
        payload=jsonable_encoder(payload or {}),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _query_text(value, default: str = "") -> str:
    if isinstance(value, str):
        return value
    if hasattr(value, "default"):
        fallback = getattr(value, "default")
        return default if fallback is None else str(fallback)
    return default


def _query_int(value, default: int) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip():
        return int(value)
    if hasattr(value, "default"):
        fallback = getattr(value, "default")
        if fallback is not None:
            return int(fallback)
    return int(default)


async def _is_online(user_id: str) -> bool:
    presence_service = get_presence_service()
    if presence_service is None:
        return False
    presence = await presence_service.get_presence(user_id)
    return str((presence or {}).get("status") or "") == "online"


async def _admin_summary(user: User) -> AdminUserSummary:
    return AdminUserSummary(
        id=user.id,
        username=user.username,
        email=user.email,
        is_admin=bool(user.is_admin),
        online=await _is_online(user.id),
    )


async def _admin_detail_for_user(db: Session, user_id: str) -> AdminUserDetail:
    user = get_registered_user_by_id(db, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    friends_summary = list_friends_summary(db, user_id)
    return AdminUserDetail(
        user=UserPublic(
            id=user.id,
            username=user.username,
            email=user.email,
            is_admin=bool(user.is_admin),
            online=await _is_online(user.id),
        ),
        friends_count=len(friends_summary["friends"]),
        incoming_requests_count=len(friends_summary["incoming_requests"]),
        outgoing_requests_count=len(friends_summary["outgoing_requests"]),
    )


@router.get("/admin/users", response_model=list[AdminUserSummary])
async def admin_list_users(
    query: str = Query(default="", max_length=100),
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    normalized = _query_text(query).strip().casefold()
    users = list_registered_users(db)
    if normalized:
        users = [
            user
            for user in users
            if normalized in str(user.username or "").casefold()
            or normalized in str(user.email or "").casefold()
            or normalized in str(user.id or "").casefold()
        ]
    users.sort(key=lambda user: (str(user.username or "").casefold(), str(user.id)))
    return [await _admin_summary(user) for user in users]


@router.get("/admin/users/{user_id}", response_model=AdminUserDetail)
async def admin_get_user_detail(
    user_id: str,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return await _admin_detail_for_user(db, user_id)


@router.put("/admin/users/{user_id}/admin", response_model=AdminUserDetail)
async def admin_update_user_admin_flag(
    user_id: str,
    payload: AdminUserAdminUpdate,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if get_registered_user_by_id(db, user_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if user_id == _admin.id and not payload.is_admin:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot remove your own admin privileges.",
        )
    profile = db.get(UserProfileRecord, user_id)
    if profile is None:
        profile = UserProfileRecord(user_id=user_id, is_admin=bool(payload.is_admin))
    else:
        profile.is_admin = bool(payload.is_admin)
    db.add(profile)
    db.commit()
    _record_admin_audit(
        db,
        admin=_admin,
        action="update_user_admin_flag",
        target_type="user",
        target_id=user_id,
        payload={"is_admin": bool(payload.is_admin)},
    )
    return await _admin_detail_for_user(db, user_id)


@router.get("/admin/audit-logs", response_model=list[AdminAuditLogEntry])
async def admin_list_audit_logs(
    query: str = Query(default="", max_length=100),
    limit: int = Query(default=100, ge=1, le=500),
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    rows = db.execute(
        select(AdminAuditLogRecord)
        .order_by(AdminAuditLogRecord.created_at.desc())
        .limit(_query_int(limit, 100))
    ).scalars().all()
    normalized = _query_text(query).strip().casefold()
    if normalized:
        rows = [
            row
            for row in rows
            if normalized in row.action.casefold()
            or normalized in row.target_type.casefold()
            or normalized in row.target_id.casefold()
            or normalized in row.admin_username.casefold()
        ]
    return [
        AdminAuditLogEntry(
            id=row.id,
            admin_user_id=row.admin_user_id,
            admin_username=row.admin_username,
            action=row.action,
            target_type=row.target_type,
            target_id=row.target_id,
            payload=row.payload or {},
            created_at=row.created_at,
        )
        for row in rows
    ]


@router.get("/admin/health", response_model=AdminMutationStatus)
async def admin_health(_admin: User = Depends(require_admin)):
    return AdminMutationStatus(status="ok", message="Admin backoffice is available.")


def _json_form_object(value: str, label: str) -> dict:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"{label} must be valid JSON.") from exc
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=400, detail=f"{label} must be a JSON object.")
    return parsed


def _json_form_list(value: str, label: str) -> list:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"{label} must be valid JSON.") from exc
    if not isinstance(parsed, list):
        raise HTTPException(status_code=400, detail=f"{label} must be a JSON array.")
    return parsed


@router.get("/admin/maps")
async def admin_list_maps(_admin: User = Depends(require_admin)):
    return {"maps": list_maps()}


@router.get("/admin/maps/{map_id}")
async def admin_get_map(map_id: str, _admin: User = Depends(require_admin)):
    try:
        return get_map(map_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/admin/maps")
async def admin_create_map(
    name: str = Form(...),
    nodes_json: str = Form(...),
    adjacency_json: str = Form(...),
    image_width: int | None = Form(default=None),
    image_height: int | None = Form(default=None),
    starting_node_id: str | None = Form(default=None),
    image: UploadFile = File(...),
    _admin: User = Depends(require_admin),
):
    try:
        return await create_map(
            name=name,
            image=image,
            nodes=_json_form_object(nodes_json, "nodes_json"),
            adjacency=_json_form_object(adjacency_json, "adjacency_json"),
            image_width=image_width,
            image_height=image_height,
            starting_node_id=starting_node_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/admin/maps/{map_id}")
async def admin_update_map(
    map_id: str,
    name: str = Form(...),
    nodes_json: str = Form(...),
    adjacency_json: str = Form(...),
    image_width: int | None = Form(default=None),
    image_height: int | None = Form(default=None),
    starting_node_id: str | None = Form(default=None),
    image: UploadFile | None = File(default=None),
    _admin: User = Depends(require_admin),
):
    try:
        return await update_map(
            map_id=map_id,
            name=name,
            image=image,
            nodes=_json_form_object(nodes_json, "nodes_json"),
            adjacency=_json_form_object(adjacency_json, "adjacency_json"),
            image_width=image_width,
            image_height=image_height,
            starting_node_id=starting_node_id,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/admin/maps/{map_id}")
async def admin_delete_map(map_id: str, _admin: User = Depends(require_admin)):
    try:
        delete_map(map_id)
        return {"status": "deleted"}
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/admin/content")
async def admin_get_content(_admin: User = Depends(require_admin)):
    return get_content_state()


@router.get("/admin/content/package")
async def admin_export_content_package(_admin: User = Depends(require_admin)):
    payload = export_admin_content_package(maps=export_maps_data())
    return JSONResponse(
        content=payload,
        headers={"Content-Disposition": 'attachment; filename="maviedepoulpe-admin-content.json"'},
    )


@router.post("/admin/content/package/import")
async def admin_import_content_package(
    payload: dict = Body(...),
    _admin: User = Depends(require_admin),
):
    try:
        maps_summary = import_maps_data(payload.get("maps") or [])
        content_summary = import_admin_content_package(payload)
        return {"status": "imported", "maps": maps_summary, "content": content_summary}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/admin/content/categories")
async def admin_create_category(
    name: str = Form(...),
    compulsory_on_same_node: bool = Form(default=False),
    _admin: User = Depends(require_admin),
):
    try:
        return create_category(name=name, compulsory_on_same_node=compulsory_on_same_node)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/admin/content/categories/{category_id}")
async def admin_update_category(
    category_id: str,
    name: str = Form(...),
    compulsory_on_same_node: bool = Form(default=False),
    _admin: User = Depends(require_admin),
):
    try:
        return update_category(category_id=category_id, name=name, compulsory_on_same_node=compulsory_on_same_node)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/admin/content/categories/{category_id}")
async def admin_delete_category(category_id: str, _admin: User = Depends(require_admin)):
    try:
        delete_category(category_id)
        return {"status": "deleted"}
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/admin/content/interactions")
async def admin_create_interaction(
    name: str = Form(...),
    image: UploadFile = File(...),
    _admin: User = Depends(require_admin),
):
    try:
        return await create_interaction(name=name, image=image)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/admin/content/interactions/{interaction_id}")
async def admin_update_interaction(
    interaction_id: str,
    name: str = Form(...),
    image: UploadFile | None = File(default=None),
    _admin: User = Depends(require_admin),
):
    try:
        return await update_interaction(interaction_id=interaction_id, name=name, image=image)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/admin/content/interactions/{interaction_id}")
async def admin_delete_interaction(interaction_id: str, _admin: User = Depends(require_admin)):
    try:
        delete_interaction(interaction_id)
        return {"status": "deleted"}
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/admin/content/events")
async def admin_create_event(
    name: str = Form(...),
    category_id: str = Form(...),
    image: UploadFile = File(...),
    _admin: User = Depends(require_admin),
):
    try:
        return await create_event(name=name, category_id=category_id, image=image)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/admin/content/events/{event_id}")
async def admin_update_event(
    event_id: str,
    name: str = Form(...),
    category_id: str = Form(...),
    image: UploadFile | None = File(default=None),
    _admin: User = Depends(require_admin),
):
    try:
        return await update_event(event_id=event_id, name=name, category_id=category_id, image=image)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/admin/content/events/{event_id}")
async def admin_delete_event(event_id: str, _admin: User = Depends(require_admin)):
    try:
        delete_event(event_id)
        return {"status": "deleted"}
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/admin/content/tiles")
async def admin_create_tile(
    name: str = Form(...),
    event_id: str = Form(...),
    priority: int = Form(default=0),
    interaction_ids_json: str = Form(...),
    counter_attack_interaction_ids_json: str = Form(default="[]"),
    success_effects_json: str = Form(default="[]"),
    counter_attack_effects_json: str = Form(default="[]"),
    failure_effects_json: str = Form(default="[]"),
    _admin: User = Depends(require_admin),
):
    try:
        return save_tile(
            name=name,
            event_id=event_id,
            priority=priority,
            interaction_ids=[str(item) for item in _json_form_list(interaction_ids_json, "interaction_ids_json")],
            counter_attack_interaction_ids=[
                str(item)
                for item in _json_form_list(counter_attack_interaction_ids_json, "counter_attack_interaction_ids_json")
            ],
            success_effects=_json_form_list(success_effects_json, "success_effects_json"),
            counter_attack_effects=_json_form_list(counter_attack_effects_json, "counter_attack_effects_json"),
            failure_effects=_json_form_list(failure_effects_json, "failure_effects_json"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/admin/content/tiles/{tile_id}")
async def admin_update_tile(
    tile_id: str,
    name: str = Form(...),
    event_id: str = Form(...),
    priority: int = Form(default=0),
    interaction_ids_json: str = Form(...),
    counter_attack_interaction_ids_json: str = Form(default="[]"),
    success_effects_json: str = Form(default="[]"),
    counter_attack_effects_json: str = Form(default="[]"),
    failure_effects_json: str = Form(default="[]"),
    _admin: User = Depends(require_admin),
):
    try:
        return save_tile(
            tile_id=tile_id,
            name=name,
            event_id=event_id,
            priority=priority,
            interaction_ids=[str(item) for item in _json_form_list(interaction_ids_json, "interaction_ids_json")],
            counter_attack_interaction_ids=[
                str(item)
                for item in _json_form_list(counter_attack_interaction_ids_json, "counter_attack_interaction_ids_json")
            ],
            success_effects=_json_form_list(success_effects_json, "success_effects_json"),
            counter_attack_effects=_json_form_list(counter_attack_effects_json, "counter_attack_effects_json"),
            failure_effects=_json_form_list(failure_effects_json, "failure_effects_json"),
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/admin/content/tiles/{tile_id}")
async def admin_delete_tile(tile_id: str, _admin: User = Depends(require_admin)):
    try:
        delete_tile(tile_id)
        return {"status": "deleted"}
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/admin/content/surprise-cards")
async def admin_create_surprise_card(
    name: str = Form(...),
    costs_json: str = Form(default="[]"),
    effects_json: str = Form(default="[]"),
    image: UploadFile | None = File(default=None),
    _admin: User = Depends(require_admin),
):
    try:
        return await save_surprise_card(
            name=name,
            costs=_json_form_list(costs_json, "costs_json"),
            effects=_json_form_list(effects_json, "effects_json"),
            image=image,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/admin/content/surprise-cards/{card_id}")
async def admin_update_surprise_card(
    card_id: str,
    name: str = Form(...),
    costs_json: str = Form(default="[]"),
    effects_json: str = Form(default="[]"),
    image: UploadFile | None = File(default=None),
    _admin: User = Depends(require_admin),
):
    try:
        return await save_surprise_card(
            card_id=card_id,
            name=name,
            costs=_json_form_list(costs_json, "costs_json"),
            effects=_json_form_list(effects_json, "effects_json"),
            image=image,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/admin/content/surprise-cards/{card_id}")
async def admin_delete_surprise_card(card_id: str, _admin: User = Depends(require_admin)):
    try:
        delete_surprise_card(card_id)
        return {"status": "deleted"}
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/admin/content/surprise-decks")
async def admin_create_surprise_deck(
    name: str = Form(...),
    card_ids_json: str = Form(default="[]"),
    _admin: User = Depends(require_admin),
):
    try:
        return save_surprise_deck(name=name, card_ids=[str(item) for item in _json_form_list(card_ids_json, "card_ids_json")])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/admin/content/surprise-decks/{deck_id}")
async def admin_update_surprise_deck(
    deck_id: str,
    name: str = Form(...),
    card_ids_json: str = Form(default="[]"),
    _admin: User = Depends(require_admin),
):
    try:
        return save_surprise_deck(deck_id=deck_id, name=name, card_ids=[str(item) for item in _json_form_list(card_ids_json, "card_ids_json")])
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/admin/content/surprise-decks/{deck_id}")
async def admin_delete_surprise_deck(deck_id: str, _admin: User = Depends(require_admin)):
    try:
        delete_surprise_deck(deck_id)
        return {"status": "deleted"}
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/admin/content/levels")
async def admin_create_level(
    name: str = Form(...),
    map_id: str = Form(...),
    node_tile_counts_json: str = Form(...),
    node_group_ids_json: str = Form(...),
    groups_json: str = Form(...),
    objectives_json: str = Form(default="[]"),
    starting_energy: int = Form(default=3),
    surprise_deck_id: str = Form(default=""),
    _admin: User = Depends(require_admin),
):
    try:
        return save_level(
            name=name,
            map_id=map_id,
            node_tile_counts=_json_form_object(node_tile_counts_json, "node_tile_counts_json"),
            node_group_ids=_json_form_object(node_group_ids_json, "node_group_ids_json"),
            groups=_json_form_list(groups_json, "groups_json"),
            objectives=_json_form_list(objectives_json, "objectives_json"),
            starting_energy=starting_energy,
            surprise_deck_id=surprise_deck_id,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/admin/content/levels/{level_id}")
async def admin_update_level(
    level_id: str,
    name: str = Form(...),
    map_id: str = Form(...),
    node_tile_counts_json: str = Form(...),
    node_group_ids_json: str = Form(...),
    groups_json: str = Form(...),
    objectives_json: str = Form(default="[]"),
    starting_energy: int = Form(default=3),
    surprise_deck_id: str = Form(default=""),
    _admin: User = Depends(require_admin),
):
    try:
        return save_level(
            level_id=level_id,
            name=name,
            map_id=map_id,
            node_tile_counts=_json_form_object(node_tile_counts_json, "node_tile_counts_json"),
            node_group_ids=_json_form_object(node_group_ids_json, "node_group_ids_json"),
            groups=_json_form_list(groups_json, "groups_json"),
            objectives=_json_form_list(objectives_json, "objectives_json"),
            starting_energy=starting_energy,
            surprise_deck_id=surprise_deck_id,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/admin/content/levels/{level_id}")
async def admin_delete_level(level_id: str, _admin: User = Depends(require_admin)):
    try:
        delete_level(level_id)
        return {"status": "deleted"}
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/admin/content/tokens/{token_id}")
async def admin_update_token(
    token_id: str,
    image: UploadFile | None = File(default=None),
    _admin: User = Depends(require_admin),
):
    try:
        return await update_token(token_id=token_id, image=image)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/admin/content/poulpita-panel")
async def admin_update_poulpita_panel(
    zones_json: str = Form(...),
    sizes_json: str = Form(default="[]"),
    image_width: int | None = Form(default=None),
    image_height: int | None = Form(default=None),
    image: UploadFile | None = File(default=None),
    _admin: User = Depends(require_admin),
):
    try:
        return await update_poulpita_panel(
            zones=_json_form_object(zones_json, "zones_json"),
            sizes=_json_form_list(sizes_json, "sizes_json"),
            image=image,
            image_width=image_width,
            image_height=image_height,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/admin/content/player-boards/{board_id}")
async def admin_update_player_board(
    board_id: str,
    name: str = Form(...),
    initiates_event_ids_json: str = Form(default="[]"),
    deck_json: str = Form(default="[]"),
    default_max_cards_in_hand: int = Form(default=3),
    hand_size_upgrades_json: str = Form(default="[]"),
    actions_per_control: int = Form(default=3),
    control_takes_per_night: int = Form(default=3),
    _admin: User = Depends(require_admin),
):
    try:
        return save_player_board(
            board_id=board_id,
            name=name,
            initiates_event_ids=[
                str(item) for item in _json_form_list(initiates_event_ids_json, "initiates_event_ids_json")
            ],
            deck=_json_form_list(deck_json, "deck_json"),
            default_max_cards_in_hand=default_max_cards_in_hand,
            hand_size_upgrades=_json_form_list(hand_size_upgrades_json, "hand_size_upgrades_json"),
            actions_per_control=actions_per_control,
            control_takes_per_night=control_takes_per_night,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
