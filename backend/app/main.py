import asyncio

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware

from .connection_manager import ConnectionManager
from .chat_service import ChatService
from .routers import router as auth_router
from .player_router import router as player_router
from .admin_router import router as admin_router
from .game_router import router as game_router
from .database import init_database, SessionLocal
from .config import settings
from .firebase_auth import initialize_firebase_admin
from .redis_client import close_redis, init_redis
from .account_bootstrap import bootstrap_all_registered_users
from .game_room_service import GameRoomService, GameWorker
from .presence_service import PresenceService
from .websocket_session_router import WebSocketSessionRouter
from .websocket_gateway import WebSocketGateway
from .runtime_state import set_connection_manager, set_game_room_service, set_presence_service

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip()
        for origin in str(settings.CORS_ALLOW_ORIGINS or "*").split(",")
        if origin.strip()
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router, prefix="/api")
app.include_router(player_router, prefix="/api")
app.include_router(admin_router, prefix="/api")
app.include_router(game_router, prefix="/api")

connection_manager = ConnectionManager()
presence_service = PresenceService(ttl_seconds=settings.PRESENCE_TTL_SECONDS)
chat_service = ChatService(
    stream_prefix=settings.CHAT_STREAM_PREFIX,
    retention_seconds=settings.CHAT_RETENTION_SECONDS,
    history_limit=settings.CHAT_HISTORY_LIMIT,
)
game_room_service = GameRoomService()
game_worker = GameWorker(game_room_service)
websocket_session_router = WebSocketSessionRouter(
    connection_manager=connection_manager,
    presence_service=presence_service,
)
websocket_gateway = WebSocketGateway(
    connection_manager=connection_manager,
    presence_service=presence_service,
    chat_service=chat_service,
    session_router=websocket_session_router,
)
set_presence_service(presence_service)
set_connection_manager(connection_manager)
set_game_room_service(game_room_service)


async def _wait_for_redis(*, attempts: int = 20, delay_seconds: float = 0.5):
    redis_client = None
    for _ in range(max(1, int(attempts))):
        redis_client = await init_redis()
        if redis_client is not None:
            return redis_client
        await asyncio.sleep(max(0.1, float(delay_seconds)))
    return redis_client


@app.on_event("startup")
async def startup_event():
    redis_client = await _wait_for_redis()
    presence_service.configure_redis(redis_client)
    chat_service.configure_redis(redis_client)
    game_room_service.configure_redis(redis_client)
    game_worker.start()
    initialize_firebase_admin()
    if settings.AUTO_CREATE_SCHEMA:
        init_database()
    db = SessionLocal()
    try:
        bootstrap_all_registered_users(db)
    finally:
        db.close()


@app.on_event("shutdown")
async def shutdown_event():
    await game_worker.stop()
    await close_redis()


@app.get("/api/health")
def health_check():
    return {"status": "ok"}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket_gateway.handle_connection(websocket)
