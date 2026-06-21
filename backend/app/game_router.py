from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, status

from .database import SessionLocal
from .map_service import list_maps
from .runtime_state import get_game_room_service
from .schemas import (
    GameCommandQueuedResponse,
    GameCommandRequest,
    GameHistoryResponse,
    GameRoomJoinResponse,
    GameResultResponse,
    GameRoomCreateRequest,
    GameRoomResponse,
    GameStateResponse,
)
from .security import get_current_user, get_current_user_with_db
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
    try:
        return await _service().create_room(user=current_user, game_type=payload.game_type, map_id=payload.map_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/game/maps")
async def list_game_maps(current_user: User = Depends(get_current_user)):
    return {"maps": list_maps()}


@router.get("/game/rooms/{room_id}", response_model=GameRoomResponse)
async def get_game_room(room_id: str, current_user: User = Depends(get_current_user)):
    room = await _service().get_room(room_id=room_id, user=current_user)
    if room is None:
        raise HTTPException(status_code=404, detail="Game room not found.")
    return room


@router.post("/game/rooms/{room_id}/join", response_model=GameRoomJoinResponse)
async def join_game_room(room_id: str, current_user: User = Depends(get_current_user)):
    joined = await _service().join_room(room_id=room_id, user=current_user)
    if joined is None:
        raise HTTPException(status_code=404, detail="Game room not found.")
    return joined


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
        result = await _service().enqueue_game_command(
            room_id=room_id,
            user=current_user,
            command=payload.model_dump(),
        )
        return result
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


@router.websocket("/game/rooms/{room_id}/ws")
async def game_room_websocket(websocket: WebSocket, room_id: str):
    token = str(websocket.query_params.get("token") or "")
    if not token:
        await websocket.close(code=4401)
        return
    db = SessionLocal()
    try:
        try:
            user = get_current_user_with_db(token, db)
        except Exception:
            await websocket.close(code=4401)
            return
    finally:
        db.close()

    service = get_game_room_service()
    if service is None:
        await websocket.close(code=1011)
        return
    connected = await service.connect_room_socket(room_id=room_id, user=user, websocket=websocket)
    if not connected:
        await websocket.close(code=4404)
        return
    try:
        while True:
            message = await websocket.receive_json()
            if message.get("type") == "request_projection":
                projection = await service.get_projection(room_id=room_id, user=user)
                if projection is not None:
                    await websocket.send_json({"type": "state_projection", "payload": projection})
    except WebSocketDisconnect:
        service.disconnect_room_socket(room_id=room_id, websocket=websocket)
