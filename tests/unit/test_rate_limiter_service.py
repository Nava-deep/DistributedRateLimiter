from __future__ import annotations

import logging
from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from redis.exceptions import RedisError

from app.core.config import Settings
from app.models.policy import FailureMode, RateLimitAlgorithm
from app.schemas.policy import PolicyRead
from app.services.key_builder import RequestIdentity
from app.services.local_fallback_limiter import LocalFallbackLimiter
from app.services.rate_limiter import RateLimitDecision, RateLimiterService


def build_policy(**overrides) -> PolicyRead:
    payload = {
        "id": uuid4(),
        "name": "limiter-policy",
        "description": "limiter test",
        "algorithm": RateLimitAlgorithm.TOKEN_BUCKET,
        "rate": 10,
        "window_seconds": 60,
        "burst_capacity": 15,
        "active": True,
        "priority": 0,
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


def build_identity() -> RequestIdentity:
    return RequestIdentity(
        route="/demo/protected",
        user_id="alice",
        ip_address="203.0.113.10",
        tenant_id=None,
        api_key=None,
    )


def build_service(
    policy_service: AsyncMock | None = None,
    *,
    settings_overrides: dict[str, object] | None = None,
) -> RateLimiterService:
    settings_payload = {
        "database_url": "postgresql+asyncpg://test:test@localhost:5432/test",
        "redis_url": "redis://localhost:6379/0",
        "enable_local_fallback_limiter": False,
        "redis_retry_attempts": 1,
        "redis_retry_backoff_ms": 0,
    }
    if settings_overrides:
        settings_payload.update(settings_overrides)

    return RateLimiterService(
        policy_service=policy_service or AsyncMock(),
        redis_client=AsyncMock(),
        logger=logging.getLogger("rate-limiter-test"),
        settings=Settings(**settings_payload),
        local_fallback_limiter=LocalFallbackLimiter(),
    )


@pytest.mark.unit
def test_rate_limit_decision_headers_clamp_negative_values() -> None:
    decision = RateLimitDecision(
        allowed=False,
        limit=10,
        remaining=-5,
        reset_at_epoch_seconds=123,
        retry_after_seconds=-9,
    )

    assert decision.headers == {
        "X-RateLimit-Limit": "10",
        "X-RateLimit-Remaining": "0",
        "X-RateLimit-Reset": "123",
        "Retry-After": "0",
    }


@pytest.mark.unit
def test_parse_common_decision_for_allowed_response() -> None:
    decision = RateLimiterService._parse_common_decision([1, 15, 9, 61_000, 0])

    assert decision.allowed is True
    assert decision.limit == 15
    assert decision.remaining == 9
    assert decision.reset_at_epoch_seconds == 61
    assert decision.retry_after_seconds == 0


@pytest.mark.unit
def test_parse_common_decision_for_blocked_response() -> None:
    decision = RateLimiterService._parse_common_decision([0, 15, 0, 61_000, 2_500])

    assert decision.allowed is False
    assert decision.limit == 15
    assert decision.remaining == 0
    assert decision.reset_at_epoch_seconds == 61
    assert decision.retry_after_seconds == 3


@pytest.mark.unit
def test_build_degraded_decision_fail_open_allows_request() -> None:
    service = build_service()
    policy = build_policy(failure_mode=FailureMode.FAIL_OPEN)

    decision = service._build_degraded_decision(policy)

    assert decision.allowed is True
    assert decision.degraded is True
    assert decision.remaining == policy.header_limit


@pytest.mark.unit
def test_build_degraded_decision_fail_closed_blocks_request() -> None:
    service = build_service()
    policy = build_policy(failure_mode=FailureMode.FAIL_CLOSED)

    decision = service._build_degraded_decision(policy)

    assert decision.allowed is False
    assert decision.degraded is True
    assert decision.remaining == 0
    assert decision.retry_after_seconds == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_evaluate_returns_none_when_no_policy_matches() -> None:
    policy_service = AsyncMock()
    policy_service.resolve_policy.return_value = None
    service = build_service(policy_service)

    decision, policy = await service.evaluate(build_identity())

    assert decision is None
    assert policy is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_evaluate_returns_decision_from_algorithm_path(monkeypatch) -> None:
    policy_service = AsyncMock()
    policy = build_policy()
    expected_decision = RateLimitDecision(
        allowed=True,
        limit=15,
        remaining=14,
        reset_at_epoch_seconds=123,
        retry_after_seconds=0,
    )
    policy_service.resolve_policy.return_value = policy
    service = build_service(policy_service)

    async def run_policy(
        selected_policy: PolicyRead,
        identity: RequestIdentity,
    ) -> RateLimitDecision:
        return expected_decision

    monkeypatch.setattr(service, "_run_policy", run_policy)

    decision, returned_policy = await service.evaluate(build_identity())

    assert decision == expected_decision
    assert returned_policy == policy


@pytest.mark.unit
@pytest.mark.asyncio
async def test_evaluate_uses_degraded_decision_when_redis_error_occurs(monkeypatch) -> None:
    policy_service = AsyncMock()
    policy = build_policy(failure_mode=FailureMode.FAIL_OPEN)
    policy_service.resolve_policy.return_value = policy
    service = build_service(policy_service)

    async def run_policy(
        selected_policy: PolicyRead,
        identity: RequestIdentity,
    ) -> RateLimitDecision:
        raise RedisError("redis unavailable")

    monkeypatch.setattr(service, "_run_policy", run_policy)

    decision, returned_policy = await service.evaluate(build_identity())

    assert decision is not None
    assert decision.allowed is True
    assert decision.degraded is True
    assert returned_policy == policy


@pytest.mark.unit
@pytest.mark.asyncio
async def test_evaluate_retries_redis_before_succeeding(monkeypatch) -> None:
    policy_service = AsyncMock()
    policy_service.resolve_policy.return_value = build_policy()
    service = build_service(policy_service, settings_overrides={"redis_retry_attempts": 1})

    attempts = {"count": 0}
    successful_decision = RateLimitDecision(
        allowed=True,
        limit=15,
        remaining=14,
        reset_at_epoch_seconds=123,
        retry_after_seconds=0,
    )

    async def run_policy(
        selected_policy: PolicyRead,
        identity: RequestIdentity,
    ) -> RateLimitDecision:
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RedisError("temporary redis hiccup")
        return successful_decision

    monkeypatch.setattr(service, "_run_policy", run_policy)

    decision, _ = await service.evaluate(build_identity())

    assert attempts["count"] == 2
    assert decision == successful_decision


@pytest.mark.unit
@pytest.mark.asyncio
async def test_evaluate_uses_local_fallback_when_enabled(monkeypatch) -> None:
    policy_service = AsyncMock()
    policy = build_policy(rate=1, burst_capacity=1)
    policy_service.resolve_policy.return_value = policy
    service = build_service(
        policy_service,
        settings_overrides={"enable_local_fallback_limiter": True, "redis_retry_attempts": 0},
    )

    async def run_policy(
        selected_policy: PolicyRead,
        identity: RequestIdentity,
    ) -> RateLimitDecision:
        raise RedisError("redis unavailable")

    monkeypatch.setattr(service, "_run_policy", run_policy)

    first, _ = await service.evaluate(build_identity())
    second, _ = await service.evaluate(build_identity())

    assert first is not None
    assert first.allowed is True
    assert first.local_fallback is True
    assert second is not None
    assert second.allowed is False
    assert second.local_fallback is True
