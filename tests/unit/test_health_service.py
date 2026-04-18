from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.core.config import Settings
from app.services.health_service import HealthService


def build_service(
    *,
    db_manager: AsyncMock | None = None,
    redis_client: object | None = None,
) -> HealthService:
    return HealthService(
        settings=Settings(
            project_name="distributed-rate-limiter-test",
            environment="test",
            app_instance_name="test-instance",
        ),
        db_manager=db_manager or AsyncMock(),
        redis_client=redis_client or object(),
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_health_service_reports_healthy_dependencies(monkeypatch) -> None:
    service = build_service()

    async def ping_redis(redis_client: object) -> bool:
        return True

    monkeypatch.setattr("app.services.health_service.ping_redis", ping_redis)

    response = await service.get_health()

    assert response.service == "distributed-rate-limiter-test"
    assert response.environment == "test"
    assert response.instance == "test-instance"
    assert response.postgres.ok is True
    assert response.redis.ok is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_health_service_marks_postgres_unhealthy_when_ping_fails(monkeypatch) -> None:
    db_manager = AsyncMock()
    db_manager.ping.side_effect = RuntimeError("postgres down")
    service = build_service(db_manager=db_manager)

    async def ping_redis(redis_client: object) -> bool:
        return True

    monkeypatch.setattr("app.services.health_service.ping_redis", ping_redis)

    response = await service.get_health()

    assert response.postgres.ok is False
    assert response.postgres.details == "postgres down"
    assert response.redis.ok is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_health_service_marks_redis_unhealthy_when_ping_fails(monkeypatch) -> None:
    service = build_service()

    async def ping_redis(redis_client: object) -> bool:
        raise RuntimeError("redis down")

    monkeypatch.setattr("app.services.health_service.ping_redis", ping_redis)

    response = await service.get_health()

    assert response.postgres.ok is True
    assert response.redis.ok is False
    assert response.redis.details == "redis down"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_health_service_can_report_both_dependencies_unhealthy(monkeypatch) -> None:
    db_manager = AsyncMock()
    db_manager.ping.side_effect = RuntimeError("postgres unreachable")
    service = build_service(db_manager=db_manager)

    async def ping_redis(redis_client: object) -> bool:
        raise RuntimeError("redis unreachable")

    monkeypatch.setattr("app.services.health_service.ping_redis", ping_redis)

    response = await service.get_health()

    assert response.postgres.ok is False
    assert response.redis.ok is False
    assert response.postgres.details == "postgres unreachable"
    assert response.redis.details == "redis unreachable"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_health_service_reports_human_readable_success_messages(monkeypatch) -> None:
    service = build_service()

    async def ping_redis(redis_client: object) -> bool:
        return True

    monkeypatch.setattr("app.services.health_service.ping_redis", ping_redis)

    response = await service.get_health()

    assert response.postgres.details == "postgres reachable"
    assert response.redis.details == "redis reachable"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_health_service_calls_both_dependency_checks(monkeypatch) -> None:
    db_manager = AsyncMock()
    service = build_service(db_manager=db_manager)
    redis_calls = {"count": 0}

    async def ping_redis(redis_client: object) -> bool:
        redis_calls["count"] += 1
        return True

    monkeypatch.setattr("app.services.health_service.ping_redis", ping_redis)

    await service.get_health()

    db_manager.ping.assert_awaited_once()
    assert redis_calls["count"] == 1
