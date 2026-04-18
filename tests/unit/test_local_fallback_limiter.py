from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.models.policy import FailureMode, RateLimitAlgorithm
from app.schemas.policy import PolicyRead
from app.services.key_builder import RequestIdentity
from app.services.local_fallback_limiter import LocalFallbackLimiter


def build_policy(**overrides) -> PolicyRead:
    payload = {
        "id": uuid4(),
        "name": "fallback-policy",
        "description": "fallback test",
        "algorithm": RateLimitAlgorithm.TOKEN_BUCKET,
        "rate": 2,
        "window_seconds": 60,
        "burst_capacity": 2,
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


def build_identity(route: str = "/demo/protected") -> RequestIdentity:
    return RequestIdentity(
        route=route,
        user_id="alice",
        ip_address="203.0.113.10",
        tenant_id=None,
        api_key=None,
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_local_fallback_token_bucket_enforces_capacity() -> None:
    limiter = LocalFallbackLimiter()
    policy = build_policy()
    identity = build_identity()

    first = await limiter.apply(policy, identity, now_ms=0)
    second = await limiter.apply(policy, identity, now_ms=1)
    third = await limiter.apply(policy, identity, now_ms=2)

    assert [first.allowed, second.allowed, third.allowed] == [True, True, False]
    assert third.retry_after_seconds >= 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_local_fallback_fixed_window_resets_after_window_boundary() -> None:
    limiter = LocalFallbackLimiter()
    policy = build_policy(
        algorithm=RateLimitAlgorithm.FIXED_WINDOW,
        burst_capacity=None,
        route="/demo/public",
        rate=1,
        window_seconds=10,
    )
    identity = build_identity(route="/demo/public")

    first = await limiter.apply(policy, identity, now_ms=1_000)
    second = await limiter.apply(policy, identity, now_ms=2_000)
    third = await limiter.apply(policy, identity, now_ms=11_000)

    assert first.allowed is True
    assert second.allowed is False
    assert third.allowed is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_local_fallback_sliding_window_drops_expired_events() -> None:
    limiter = LocalFallbackLimiter()
    policy = build_policy(
        algorithm=RateLimitAlgorithm.SLIDING_WINDOW_LOG,
        burst_capacity=None,
        route="/demo/user/{user_id}",
        rate=2,
        window_seconds=5,
        user_id="alice",
    )
    identity = build_identity(route="/demo/user/{user_id}")

    first = await limiter.apply(policy, identity, now_ms=0)
    second = await limiter.apply(policy, identity, now_ms=1_000)
    third = await limiter.apply(policy, identity, now_ms=2_000)
    fourth = await limiter.apply(policy, identity, now_ms=6_100)

    assert [first.allowed, second.allowed, third.allowed, fourth.allowed] == [
        True,
        True,
        False,
        True,
    ]
