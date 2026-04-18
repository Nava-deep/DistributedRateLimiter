from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.models.policy import FailureMode, RateLimitAlgorithm
from app.schemas.policy import PolicyRead
from app.services.policy_cache import PolicySnapshotStore


def build_policy(name: str = "cache-policy") -> PolicyRead:
    return PolicyRead(
        id=uuid4(),
        name=name,
        description="cache test",
        algorithm=RateLimitAlgorithm.TOKEN_BUCKET,
        rate=10,
        window_seconds=60,
        burst_capacity=15,
        active=True,
        priority=0,
        version=1,
        route="/demo/protected",
        user_id=None,
        ip_address=None,
        tenant_id=None,
        api_key=None,
        failure_mode=FailureMode.FAIL_CLOSED,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_policy_snapshot_store_returns_none_when_empty() -> None:
    store = PolicySnapshotStore()

    assert await store.get_fresh(ttl_seconds=30) is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_policy_snapshot_store_returns_cached_policies_when_fresh(
    monkeypatch,
) -> None:
    store = PolicySnapshotStore()
    monkeypatch.setattr("app.services.policy_cache.monotonic", lambda: 100.0)
    await store.set([build_policy("fresh-policy")])

    monkeypatch.setattr("app.services.policy_cache.monotonic", lambda: 105.0)
    policies = await store.get_fresh(ttl_seconds=30)

    assert policies is not None
    assert [policy.name for policy in policies] == ["fresh-policy"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_policy_snapshot_store_returns_copy_of_cached_list(monkeypatch) -> None:
    store = PolicySnapshotStore()
    monkeypatch.setattr("app.services.policy_cache.monotonic", lambda: 200.0)
    await store.set([build_policy("copy-policy")])

    first = await store.get_fresh(ttl_seconds=30)
    second = await store.get_fresh(ttl_seconds=30)

    assert first is not None and second is not None
    assert first is not second
    first.clear()
    assert [policy.name for policy in second] == ["copy-policy"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_policy_snapshot_store_returns_none_when_snapshot_has_expired(
    monkeypatch,
) -> None:
    store = PolicySnapshotStore()
    monkeypatch.setattr("app.services.policy_cache.monotonic", lambda: 300.0)
    await store.set([build_policy("expired-policy")])

    monkeypatch.setattr("app.services.policy_cache.monotonic", lambda: 340.5)

    assert await store.get_fresh(ttl_seconds=30) is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_policy_snapshot_store_clear_removes_cached_snapshot(monkeypatch) -> None:
    store = PolicySnapshotStore()
    monkeypatch.setattr("app.services.policy_cache.monotonic", lambda: 400.0)
    await store.set([build_policy("clear-policy")])

    await store.clear()

    assert await store.get_fresh(ttl_seconds=30) is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_policy_snapshot_store_treats_boundary_age_as_fresh(monkeypatch) -> None:
    store = PolicySnapshotStore()
    monkeypatch.setattr("app.services.policy_cache.monotonic", lambda: 500.0)
    await store.set([build_policy("boundary-policy")])

    monkeypatch.setattr("app.services.policy_cache.monotonic", lambda: 530.0)
    policies = await store.get_fresh(ttl_seconds=30)

    assert policies is not None
    assert [policy.name for policy in policies] == ["boundary-policy"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_policy_snapshot_store_replaces_older_snapshot_when_set_again(monkeypatch) -> None:
    store = PolicySnapshotStore()
    monkeypatch.setattr("app.services.policy_cache.monotonic", lambda: 600.0)
    await store.set([build_policy("first-policy")])

    monkeypatch.setattr("app.services.policy_cache.monotonic", lambda: 605.0)
    await store.set([build_policy("second-policy")])

    monkeypatch.setattr("app.services.policy_cache.monotonic", lambda: 610.0)
    policies = await store.get_fresh(ttl_seconds=30)

    assert policies is not None
    assert [policy.name for policy in policies] == ["second-policy"]
