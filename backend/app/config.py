from pydantic_settings import BaseSettings
from pydantic_settings import SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_NAME: str = "Ma vie de poulpe"
    SECRET_KEY: str = "local-dev-only-change-me"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24
    DATABASE_URL: str = "sqlite:///./backend/data/app.db"
    AUTO_CREATE_SCHEMA: bool = True

    REDIS_URL: str = "redis://redis:6379/0"
    REDIS_PASSWORD: str = ""
    REDIS_ENABLED: bool = True
    PRESENCE_TTL_SECONDS: int = 120

    FIREBASE_ADMIN_CREDENTIALS: str = "secrets/firebase-admin.dev.json"
    FIREBASE_PROJECT_ID: str = ""
    FIREBASE_PRIMARY_ADMIN_EMAIL: str = ""

    CHAT_STREAM_PREFIX: str = "chat"
    CHAT_RETENTION_SECONDS: int = 86400
    CHAT_HISTORY_LIMIT: int = 80

    USE_DISTRIBUTED_GAME_RUNTIME: bool = False
    DISTRIBUTED_GAME_GATEWAY_RUN_WORKER: bool = False
    GAME_COMMAND_STREAM_KEY: str = "game:commands"
    GAME_COMMAND_CONSUMER_GROUP: str = "game-workers"
    GAME_COMMAND_CONSUMER_NAME: str = "worker-dev"
    GAME_COMMAND_RESULT_TTL_SECONDS: int = 60
    GAME_COMMAND_RESULT_TIMEOUT_SECONDS: float = 8.0
    GAME_COMMAND_RESULT_POLL_SECONDS: float = 0.05

    CORS_ALLOW_ORIGINS: str = "*"


settings = Settings()
