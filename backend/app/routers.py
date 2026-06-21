from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from . import schemas, server_models
from .database import get_db
from .runtime_registry import compat_runtime_users
from .security import get_current_user
from .user_repository import get_registered_user_by_id

router = APIRouter()

# Runtime compatibility stores used by tests and transitional in-memory runtime.
fake_users_db: dict[str, server_models.User] = compat_runtime_users


@router.get("/auth/me", response_model=schemas.AuthMeResponse)
def auth_me(
    current_user: server_models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    player = get_registered_user_by_id(db, current_user.id)
    return schemas.AuthMeResponse(
        uid=current_user.id,
        email=current_user.email,
        username=current_user.username,
        auth_provider=current_user.auth_provider,
        player_exists=player is not None,
        is_admin=bool(current_user.is_admin),
    )
