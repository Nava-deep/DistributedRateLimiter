from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from redis.exceptions import RedisError

from app.core.config import Settings
from app.models.policy import FailureMode, RateLimitAlgorithm, RateLimitPolicy
from app.schemas.policy import PolicyCreate, PolicyRead, PolicyUpdate
from app.services.key_builder import RequestIdentity
from app.services.policy_service import PolicyNotFoundError, PolicyService


def build_settings(**overrides) -> Settings:
    payload = {
        "database_url": "postgresql+asyncpg://test:test@localhost:5432/test",
        "redis_url": "redis://localhost:6379/0",
        "project_name": "distributed-rate-limiter-test",
        "policy_cache_ttl_seconds": 30,
        "local_policy_cache_ttl_seconds": 15,
        "enable_policy_pubsub": True,
    }
    payload.update(overrides)
    return Settings(**payload)


def build_policy_read(**overrides) -> PolicyRead:
    payload = {
        "id": uuid4(),
        "name": "policy-read",
        "description": "policy read",
        "algorithm": RateLimitAlgorithm.TOKEN_BUCKET,
        "rate": 10,
        "window_seconds": 60,
        "burst_capacity": 10,
        "active": True,
        "priority": 1,
        "version": 1,
        "route": "/demo/protected",
        "user_id": None,
        "ip_address": None,
        "tenant_id": None,
        "api_key": None,
        "failure_mode": FailureMode.FAIL_CLOSED,
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }
    payload.update(overrides)
    return PolicyRead(**payload)


def build_policy_model(**overrides) -> RateLimitPolicy:
    policy = RateLimitPolicy(
        name="policy-model",
        description="policy model",
        algorithm=RateLimitAlgorithm.TOKEN_BUCKET,
        rate=10,
        window_seconds=60,
        burst_capacity=10,
        active=True,
        priority=1,
        route="/demo/protected",
        user_id=None,
        ip_address=None,
        tenant_id=None,
        api_key=None,
        failure_mode=FailureMode.FAIL_CLOSED,
    )
    policy.id = uuid4()
    policy.version = 1
    policy.created_at = datetime.now(UTC)
    policy.updated_at = datetime.now(UTC)
    for field, value in overrides.items():
        setattr(policy, field, value)
    return policy


def build_service(**overrides) -> PolicyService:
    session = overrides.pop(
        "session",
        SimpleNamespace(
            add=Mock(),
            commit=AsyncMock(),
            refresh=AsyncMock(),
            get=AsyncMock(),
            delete=AsyncMock(),
            execute=AsyncMock(),
        ),
    )
    redis_client = overrides.pop("redis_client", AsyncMock())
    snapshot_store = overrides.pop("snapshot_store", AsyncMock())
    return PolicyService(
        session=session,
        redis_client=redis_client,
        settings=overrides.pop("settings", build_settings()),
        snapshot_store=snapshot_store,
        logger=logging.getLogger("policy-service-test"),
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_policy_returns_policy_read_when_found() -> None:
    service = build_service()
    model = build_policy_model()
    service.session.get.return_value = model

    result = await service.get_policy(model.id)

    assert result.id == model.id
    assert result.name == model.name


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_policy_raises_when_missing() -> None:
    service = build_service()
    service.session.get.return_value = None

    with pytest.raises(PolicyNotFoundError):
        await service.get_policy(uuid4())


@pytest.mark.unit
@pytest.mark.asyncio
async def test_update_policy_increments_version_and_invalidates_cache(monkeypatch) -> None:
    service = build_service()
    model = build_policy_model(name="before-update", version=3)
    service.session.get.return_value = model
    invalidate = AsyncMock()
    monkeypatch.setattr(service, "invalidate_policy_cache", invalidate)

    result = await service.update_policy(
        model.id,
        PolicyUpdate(name="after-update", rate=25, burst_capacity=30),
    )

    assert result.name == "after-update"
    assert result.rate == 25
    assert result.version == 4
    service.session.commit.assert_awaited_once()
    invalidate.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_update_policy_with_empty_payload_skips_commit(monkeypatch) -> None:
    service = build_service()
    model = build_policy_model(name="unchanged", version=2)
    service.session.get.return_value = model
    invalidate = AsyncMock()
    monkeypatch.setattr(service, "invalidate_policy_cache", invalidate)

    result = await service.update_policy(model.id, PolicyUpdate())

    assert result.name == "unchanged"
    assert result.version == 2
    service.session.commit.assert_not_awaited()
    invalidate.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_update_policy_raises_when_missing() -> None:
    service = build_service()
    service.session.get.return_value = None

    with pytest.raises(PolicyNotFoundError):
        await service.update_policy(uuid4(), PolicyUpdate(name="missing"))


@pytest.mark.unit
@pytest.mark.asyncio
async def test_delete_policy_removes_record_and_invalidates_cache(monkeypatch) -> None:
    service = build_service()
    model = build_policy_model()
    service.session.get.return_value = model
    invalidate = AsyncMock()
    monkeypatch.setattr(service, "invalidate_policy_cache", invalidate)

    await service.delete_policy(model.id)

    service.session.delete.assert_awaited_once_with(model)
    service.session.commit.assert_awaited_once()
    invalidate.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_delete_policy_raises_when_missing() -> None:
    service = build_service()
    service.session.get.return_value = None

    with pytest.raises(PolicyNotFoundError):
        await service.delete_policy(uuid4())


@pytest.mark.unit
@pytest.mark.asyncio
async def test_resolve_policy_returns_best_match(monkeypatch) -> None:
    service = build_service()
    route_default = build_policy_read(name="route-default")
    user_override = build_policy_read(name="user-override", user_id="alice", priority=10)
    monkeypatch.setattr(
        service,
        "list_active_policies_cached",
        AsyncMock(return_value=[route_default, user_override]),
    )

    identity = RequestIdentity(
        route="/demo/protected",
        user_id="alice",
        ip_address="203.0.113.10",
        tenant_id=None,
        api_key=None,
    )
    result = await service.resolve_policy(identity)

    assert result is not None
    assert result.name == "user-override"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_active_policies_cached_uses_redis_payload() -> None:
    policy = build_policy_read(name="redis-policy")
    service = build_service()
    service.redis_client.get.return_value = json.dumps([policy.model_dump(mode="json")])

    result = await service.list_active_policies_cached()

    assert [item.name for item in result] == ["redis-policy"]
    service.snapshot_store.set.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_active_policies_cached_returns_local_snapshot_after_redis_error() -> None:
    service = build_service()
    service.redis_client.get.side_effect = RedisError("cache read failed")
    cached_policies = [build_policy_read(name="local-policy")]
    service.snapshot_store.get_fresh.return_value = cached_policies

    result = await service.list_active_policies_cached()

    assert result == cached_policies
    service.snapshot_store.set.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_active_policies_cached_queries_database_when_snapshot_missing(
    monkeypatch,
) -> None:
    service = build_service()
    service.redis_client.get.side_effect = RedisError("cache read failed")
    service.snapshot_store.get_fresh.return_value = None
    db_policies = [build_policy_read(name="db-policy")]
    monkeypatch.setattr(service, "list_policies", AsyncMock(return_value=db_policies))

    result = await service.list_active_policies_cached()

    assert [item.name for item in result] == ["db-policy"]
    service.snapshot_store.set.assert_awaited_once_with(db_policies)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_active_policies_cached_sets_redis_when_cache_misses(monkeypatch) -> None:
    service = build_service()
    service.redis_client.get.return_value = None
    policies = [build_policy_read(name="postgres-policy")]
    monkeypatch.setattr(service, "list_policies", AsyncMock(return_value=policies))

    result = await service.list_active_policies_cached()

    assert [item.name for item in result] == ["postgres-policy"]
    service.redis_client.setex.assert_awaited_once()
    service.snapshot_store.set.assert_awaited_once_with(policies)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_active_policies_cached_tolerates_setex_errors(monkeypatch) -> None:
    service = build_service()
    service.redis_client.get.return_value = None
    service.redis_client.setex.side_effect = RedisError("setex failed")
    policies = [build_policy_read(name="postgres-policy")]
    monkeypatch.setattr(service, "list_policies", AsyncMock(return_value=policies))

    result = await service.list_active_policies_cached()

    assert [item.name for item in result] == ["postgres-policy"]
    service.snapshot_store.set.assert_awaited_once_with(policies)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_invalidate_policy_cache_deletes_and_publishes_when_enabled() -> None:
    service = build_service(settings=build_settings(enable_policy_pubsub=True))

    await service.invalidate_policy_cache(reason="update", policy_id="policy-1")

    service.snapshot_store.clear.assert_awaited_once()
    service.redis_client.delete.assert_awaited_once_with(service.settings.policy_cache_key)
    service.redis_client.publish.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_invalidate_policy_cache_skips_publish_when_disabled() -> None:
    service = build_service(settings=build_settings(enable_policy_pubsub=False))

    await service.invalidate_policy_cache(reason="delete", policy_id="policy-1")

    service.redis_client.delete.assert_awaited_once_with(service.settings.policy_cache_key)
    service.redis_client.publish.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_invalidate_policy_cache_tolerates_redis_errors() -> None:
    service = build_service()
    service.redis_client.delete.side_effect = RedisError("delete failed")

    await service.invalidate_policy_cache(reason="update", policy_id="policy-1")

    service.snapshot_store.clear.assert_awaited_once()


@pytest.mark.unit
def test_to_policy_payload_includes_all_selectors() -> None:
    policy = build_policy_model(
        route="/services/auth/session",
        user_id="alice",
        ip_address="203.0.113.10",
        tenant_id="tenant-a",
        api_key="key-123",
    )

    payload = PolicyService._to_policy_payload(policy)

    assert payload["route"] == "/services/auth/session"
    assert payload["user_id"] == "alice"
    assert payload["ip_address"] == "203.0.113.10"
    assert payload["tenant_id"] == "tenant-a"
    assert payload["api_key"] == "key-123"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_create_policy_persists_model_and_invalidates_cache(monkeypatch) -> None:
    service = build_service()
    added: list[RateLimitPolicy] = []

    def add_instance(model: RateLimitPolicy) -> None:
        model.id = uuid4()
        model.version = 1
        model.created_at = datetime.now(UTC)
        model.updated_at = datetime.now(UTC)
        added.append(model)

    service.session.add.side_effect = add_instance
    invalidate = AsyncMock()
    monkeypatch.setattr(service, "invalidate_policy_cache", invalidate)

    result = await service.create_policy(
        PolicyCreate(
            name="created-policy",
            algorithm=RateLimitAlgorithm.TOKEN_BUCKET,
            rate=5,
            window_seconds=60,
            burst_capacity=5,
            route="/demo/public",
        )
    )

    assert added[0].name == "created-policy"
    assert result.name == "created-policy"
    service.session.commit.assert_awaited_once()
    service.session.refresh.assert_awaited_once()
    invalidate.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_upsert_policy_by_name_creates_missing_policy(monkeypatch) -> None:
    service = build_service()
    created_policy = build_policy_read(name="sync-created")
    create_policy = AsyncMock(return_value=created_policy)
    monkeypatch.setattr(service, "create_policy", create_policy)
    execute_result = SimpleNamespace(scalar_one_or_none=lambda: None)
    service.session.execute.return_value = execute_result

    result, action = await service.upsert_policy_by_name(
        PolicyCreate(
            name="sync-created",
            algorithm=RateLimitAlgorithm.TOKEN_BUCKET,
            rate=5,
            window_seconds=60,
            burst_capacity=5,
            route="/api/submissions/submit/",
        )
    )

    assert action == "created"
    assert result.name == "sync-created"
    create_policy.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_upsert_policy_by_name_updates_existing_policy(monkeypatch) -> None:
    service = build_service()
    model = build_policy_model(name="sync-updated", rate=10, burst_capacity=10, version=2)
    execute_result = SimpleNamespace(scalar_one_or_none=lambda: model)
    service.session.execute.return_value = execute_result
    invalidate = AsyncMock()
    monkeypatch.setattr(service, "invalidate_policy_cache", invalidate)

    result, action = await service.upsert_policy_by_name(
        PolicyCreate(
            name="sync-updated",
            algorithm=RateLimitAlgorithm.TOKEN_BUCKET,
            rate=25,
            window_seconds=60,
            burst_capacity=30,
            route="/api/submissions/submit/",
        )
    )

    assert action == "updated"
    assert result.rate == 25
    assert result.version == 3
    service.session.commit.assert_awaited_once()
    invalidate.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_upsert_policy_by_name_skips_write_when_payload_is_unchanged(monkeypatch) -> None:
    service = build_service()
    model = build_policy_model(name="sync-unchanged", route="/api/submissions/submit/")
    execute_result = SimpleNamespace(scalar_one_or_none=lambda: model)
    service.session.execute.return_value = execute_result
    invalidate = AsyncMock()
    monkeypatch.setattr(service, "invalidate_policy_cache", invalidate)

    result, action = await service.upsert_policy_by_name(
        PolicyCreate(
            name="sync-unchanged",
            description="policy model",
            algorithm=RateLimitAlgorithm.TOKEN_BUCKET,
            rate=10,
            window_seconds=60,
            burst_capacity=10,
            active=True,
            priority=1,
            route="/api/submissions/submit/",
            failure_mode=FailureMode.FAIL_CLOSED,
        )
    )

    assert action == "unchanged"
    assert result.version == 1
    service.session.commit.assert_not_awaited()
    invalidate.assert_not_awaited()
