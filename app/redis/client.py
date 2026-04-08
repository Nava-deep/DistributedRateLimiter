from __future__ import annotations

from redis.asyncio import Redis

from app.core.config import Settings


def create_redis_client(settings: Settings) -> Redis:
    return Redis.from_url(
        settings.redis_url,
        encoding="utf-8",
        decode_responses=True,
        socket_timeout=settings.redis_socket_timeout_seconds,
        socket_connect_timeout=settings.redis_socket_timeout_seconds,
        health_check_interval=30,
    )


async def ping_redis(redis_client: Redis) -> bool:
    await redis_client.ping()
    return True


async def close_redis_client(redis_client: Redis) -> None:
    close_method = getattr(redis_client, "aclose", None)
    if close_method is not None:
        await close_method()
        return
    await redis_client.close()
