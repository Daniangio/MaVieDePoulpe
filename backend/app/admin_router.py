from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import get_db
from .db_models import AdminAuditLogRecord, UserProfileRecord
from .friend_service import list_friends_summary
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
