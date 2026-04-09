from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient


def route_policy(*, name: str, route: str, rate: int) -> dict[str, object]:
    return {
        "name": name,
        "algorithm": "fixed_window",
        "rate": rate,
        "window_seconds": 60,
        "route": route,
        "failure_mode": "fail_closed",
    }


@pytest.mark.integration
@pytest.mark.asyncio
async def test_policy_cache_miss_then_hit(client, app, admin_headers, monkeypatch) -> None:
    await client.post(
        "/admin/policies",
        json=route_policy(name="cache-protected", route="/demo/protected", rate=3),
        headers=admin_headers,
    )

    calls = {"hit": 0, "miss": 0}

    def mark_hit() -> None:
        calls["hit"] += 1

    def mark_miss() -> None:
        calls["miss"] += 1

    monkeypatch.setattr("app.services.policy_service.mark_policy_cache_hit", mark_hit)
    monkeypatch.setattr("app.services.policy_service.mark_policy_cache_miss", mark_miss)

    first = await client.get("/demo/protected")
    second = await client.get("/demo/protected")
    cache_payload = await app.state.redis.get(app.state.settings.policy_cache_key)

    assert first.status_code == 200
    assert second.status_code == 200
    assert calls == {"hit": 1, "miss": 1}
    assert cache_payload is not None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_policy_refresh_pubsub_invalidates_other_instance_snapshot(
    app_factory,
    admin_headers,
) -> None:
    app_a = app_factory(app_instance_name="instance-a")
    app_b = app_factory(app_instance_name="instance-b")

    async with AsyncExitStack() as stack:
        await stack.enter_async_context(LifespanManager(app_a))
        await stack.enter_async_context(LifespanManager(app_b))

        client_a = await stack.enter_async_context(
            AsyncClient(transport=ASGITransport(app=app_a), base_url="http://instance-a")
        )
        client_b = await stack.enter_async_context(
            AsyncClient(transport=ASGITransport(app=app_b), base_url="http://instance-b")
        )

        created = await client_a.post(
            "/admin/policies",
            json=route_policy(name="pubsub-protected", route="/demo/protected", rate=1),
            headers=admin_headers,
        )
        policy_id = created.json()["id"]

        warm = await client_b.get("/demo/protected")
        assert warm.status_code == 200
        assert await app_b.state.policy_snapshot.get_fresh(60) is not None

        updated = await client_a.put(
            f"/admin/policies/{policy_id}",
            json={"rate": 2},
            headers=admin_headers,
        )
        assert updated.status_code == 200

        for _ in range(40):
            if await app_b.state.policy_snapshot.get_fresh(60) is None:
                break
            await asyncio.sleep(0.05)

        assert await app_b.state.policy_snapshot.get_fresh(60) is None

        second = await client_b.get("/demo/protected")
        third = await client_b.get("/demo/protected")

        assert [second.status_code, third.status_code] == [200, 200]
