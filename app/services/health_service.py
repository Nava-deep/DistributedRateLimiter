from __future__ import annotations

from redis.asyncio import Redis

from app.core.config import Settings
from app.db.session import DatabaseSessionManager
from app.redis.client import ping_redis
from app.schemas.health import DependencyHealth, HealthResponse


class HealthService:
    def __init__(
        self,
        *,
        settings: Settings,
        db_manager: DatabaseSessionManager,
        redis_client: Redis,
    ) -> None:
        self.settings = settings
        self.db_manager = db_manager
        self.redis_client = redis_client

    async def get_health(self) -> HealthResponse:
        postgres_health = await self._check_postgres()
        redis_health = await self._check_redis()
        return HealthResponse(
            service=self.settings.project_name,
            environment=self.settings.environment,
            instance=self.settings.app_instance_name,
            postgres=postgres_health,
            redis=redis_health,
        )

    async def _check_postgres(self) -> DependencyHealth:
        try:
            await self.db_manager.ping()
        except Exception as exc:
            return DependencyHealth(ok=False, details=str(exc))
        return DependencyHealth(ok=True, details="postgres reachable")

    async def _check_redis(self) -> DependencyHealth:
        try:
            await ping_redis(self.redis_client)
        except Exception as exc:
            return DependencyHealth(ok=False, details=str(exc))
        return DependencyHealth(ok=True, details="redis reachable")

