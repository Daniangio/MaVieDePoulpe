from __future__ import annotations

from typing import Optional
from urllib.parse import quote, urlsplit, urlunsplit

from .config import settings

try:
    from redis.asyncio import Redis
    from redis.asyncio import from_url as redis_from_url
except ImportError:  # pragma: no cover
    Redis = object  # type: ignore[assignment]
    redis_from_url = None  # type: ignore[assignment]


_redis_client: Optional[Redis] = None


async def init_redis() -> Optional[Redis]:
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    if not settings.REDIS_ENABLED or redis_from_url is None:
        return None
    redis_url = _effective_redis_url()
    client = redis_from_url(redis_url, decode_responses=True)
    try:
        await client.ping()
    except Exception as exc:
        print(f"[redis] failed to connect using REDIS_URL={_redact_redis_url(redis_url)}: {exc}")
        await client.aclose()
        return None
    _redis_client = client
    return _redis_client


def get_redis() -> Optional[Redis]:
    return _redis_client


async def close_redis() -> None:
    global _redis_client
    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None


def _effective_redis_url() -> str:
    redis_url = str(settings.REDIS_URL or "").strip() or "redis://redis:6379/0"
    redis_password = str(getattr(settings, "REDIS_PASSWORD", "") or "").strip()
    if not redis_password:
        return redis_url
    parts = urlsplit(redis_url)
    if parts.password:
        return redis_url
    host = parts.hostname or ""
    if not host:
        return redis_url
    host_display = f"[{host}]" if ":" in host and not host.startswith("[") else host
    port = f":{parts.port}" if parts.port else ""
    username = parts.username or ""
    encoded_password = quote(redis_password, safe="")
    auth = f"{username}:{encoded_password}" if username else f":{encoded_password}"
    netloc = f"{auth}@{host_display}{port}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def _redact_redis_url(redis_url: str) -> str:
    parts = urlsplit(redis_url)
    if not parts.password:
        return redis_url
    host = parts.hostname or ""
    host_display = f"[{host}]" if ":" in host and not host.startswith("[") else host
    port = f":{parts.port}" if parts.port else ""
    username = parts.username or ""
    auth = f"{username}:***" if username else ":***"
    netloc = f"{auth}@{host_display}{port}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
