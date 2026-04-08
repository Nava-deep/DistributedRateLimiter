from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from redis.exceptions import RedisError

from app.api.router import api_router
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging, get_logger, log_event
from app.db.session import DatabaseSessionManager
from app.middleware.observability import ObservabilityMiddleware
from app.redis.client import close_redis_client, create_redis_client
from app.services.policy_cache import PolicySnapshotStore


async def run_startup_checks(app: FastAPI) -> dict[str, bool]:
    postgres_ok = False
    redis_ok = False

    try:
        await app.state.db.ping()
        postgres_ok = True
    except Exception as exc:
        log_event(
            app.state.logger,
            logging.ERROR,
            "startup_check_failed",
            dependency="postgres",
            error=str(exc),
        )

    try:
        await app.state.redis.ping()
        redis_ok = True
    except Exception as exc:
        log_event(
            app.state.logger,
            logging.ERROR,
            "startup_check_failed",
            dependency="redis",
            error=str(exc),
        )

    return {"postgres": postgres_ok, "redis": redis_ok}


async def policy_refresh_listener(app: FastAPI) -> None:
    pubsub = app.state.redis.pubsub()
    await pubsub.subscribe(app.state.settings.policy_refresh_channel)

    try:
        async for message in pubsub.listen():
            if message.get("type") != "message":
                continue
            await app.state.policy_snapshot.clear()
            log_event(
                app.state.logger,
                logging.INFO,
                "policy_refresh_received",
                payload=message.get("data"),
            )
    except asyncio.CancelledError:
        raise
    except (RedisError, TimeoutError):
        return
    finally:
        with suppress(Exception):
            await pubsub.unsubscribe(app.state.settings.policy_refresh_channel)
        close_method = getattr(pubsub, "aclose", None)
        with suppress(Exception):
            if close_method is not None:
                await close_method()
            else:
                await pubsub.close()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    logger = get_logger(settings.project_name)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = settings
        app.state.logger = logger
        app.state.db = DatabaseSessionManager(settings.database_url)
        app.state.redis = create_redis_client(settings)
        app.state.policy_snapshot = PolicySnapshotStore()
        listener_task: asyncio.Task[Any] | None = None

        startup_status = await run_startup_checks(app)
        app.state.startup_status = startup_status

        if settings.strict_startup_checks and not all(startup_status.values()):
            await close_redis_client(app.state.redis)
            await app.state.db.dispose()
            raise RuntimeError(f"Strict startup checks failed: {startup_status}")

        if settings.enable_policy_pubsub and startup_status["redis"]:
            listener_task = asyncio.create_task(policy_refresh_listener(app))

        log_event(
            logger,
            logging.INFO,
            "service_started",
            instance=settings.app_instance_name,
            environment=settings.environment,
            startup_status=startup_status,
        )

        try:
            yield
        finally:
            if listener_task is not None:
                listener_task.cancel()
                try:
                    await listener_task
                except (asyncio.CancelledError, RedisError, TimeoutError):
                    pass
            await close_redis_client(app.state.redis)
            await app.state.db.dispose()
            log_event(
                logger,
                logging.INFO,
                "service_stopped",
                instance=settings.app_instance_name,
            )

    application = FastAPI(
        title=settings.project_name,
        version="0.1.0",
        description="Distributed rate limiting service with Redis-backed atomic coordination.",
        lifespan=lifespan,
    )
    application.add_middleware(ObservabilityMiddleware)
    application.include_router(api_router)
    return application


app = create_app()
