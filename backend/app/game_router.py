from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from .runtime_state import get_game_room_service
from .schemas import (
    GameCommandQueuedResponse,
    GameCommandRequest,
    GameHistoryResponse,
    GameResultResponse,
    GameRoomCreateRequest,
    GameRoomResponse,
    GameStateResponse,
)
from .security import get_current_user
from .server_models import User


router = APIRouter()


def _service():
    service = get_game_room_service()
    if service is None:
        raise HTTPException(status_code=503, detail="Game room service is unavailable.")
    return service


@router.post("/game/rooms", response_model=GameRoomResponse)
async def create_game_room(
    payload: GameRoomCreateRequest,
    current_user: User = Depends(get_current_user),
):
    return await _service().create_room(user=current_user, game_type=payload.game_type)


@router.get("/game/rooms/{room_id}", response_model=GameRoomResponse)
async def get_game_room(room_id: str, current_user: User = Depends(get_current_user)):
    room = await _service().get_room(room_id=room_id, user=current_user)
    if room is None:
        raise HTTPException(status_code=404, detail="Game room not found.")
    return room


@router.post("/game/rooms/{room_id}/end", response_model=GameRoomResponse)
async def end_game_room(room_id: str, current_user: User = Depends(get_current_user)):
    try:
        return await _service().enqueue_end_room(room_id=room_id, user=current_user)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/game/rooms/{room_id}/state", response_model=GameStateResponse)
async def get_game_state(
    room_id: str,
    current_user: User = Depends(get_current_user),
):
    state = await _service().get_game_state(room_id=room_id, user=current_user)
    if state is None:
        raise HTTPException(status_code=404, detail="Game state not found.")
    return state


@router.post("/game/rooms/{room_id}/commands", response_model=GameCommandQueuedResponse)
async def enqueue_game_command(
    room_id: str,
    payload: GameCommandRequest,
    current_user: User = Depends(get_current_user),
):
    try:
        return await _service().enqueue_game_command(
            room_id=room_id,
            user=current_user,
            command=payload.model_dump(),
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/game/results/{room_id}", response_model=GameResultResponse)
async def get_game_result(room_id: str, current_user: User = Depends(get_current_user)):
    result = await _service().get_result(room_id=room_id, user_id=current_user.id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Game result not found.")
    return result


@router.get("/game/history", response_model=GameHistoryResponse)
async def get_game_history(current_user: User = Depends(get_current_user)):
    return GameHistoryResponse(results=await _service().list_history(user_id=current_user.id))
