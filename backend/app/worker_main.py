from __future__ import annotations

import asyncio

from .account_bootstrap import bootstrap_all_registered_users
from .config import settings
from .database import SessionLocal, init_database
from .firebase_auth import initialize_firebase_admin
from .game_room_service import GameRoomService, GameWorker
from .redis_client import close_redis, init_redis


async def _wait_for_redis(*, attempts: int = 30, delay_seconds: float = 1.0):
    for _ in range(max(1, int(attempts))):
        redis_client = await init_redis()
        if redis_client is not None:
            return redis_client
        await asyncio.sleep(max(0.1, float(delay_seconds)))
    raise RuntimeError("Redis is required to run the game worker.")


async def _main() -> None:
    if not settings.USE_DISTRIBUTED_GAME_RUNTIME:
        print("[game-worker] USE_DISTRIBUTED_GAME_RUNTIME is false; worker exits.")
        return
    redis_client = await _wait_for_redis()
    initialize_firebase_admin()
    if settings.AUTO_CREATE_SCHEMA:
        init_database()
    db = SessionLocal()
    try:
        bootstrap_all_registered_users(db)
    finally:
        db.close()

    service = GameRoomService(redis_client=redis_client)
    worker = GameWorker(service, enabled=True)
    worker.start()
    print("[game-worker] command worker started.")
    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        await worker.stop()
        await service.close()
        await close_redis()


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()
