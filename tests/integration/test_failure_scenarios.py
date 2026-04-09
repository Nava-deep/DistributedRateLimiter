from __future__ import annotations

from contextlib import AsyncExitStack

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from redis.exceptions import RedisError, TimeoutError


def route_policy(
    *,
    name: str,
    route: str,
    algorithm: str = "token_bucket",
    rate: int = 2,
    burst_capacity: int | None = None,
    failure_mode: str = "fail_closed",
) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": name,
        "algorithm": algorithm,
        "rate": rate,
        "window_seconds": 60,
        "route": route,
        "failure_mode": failure_mode,
    }
    if burst_capacity is not None:
        payload["burst_capacity"] = burst_capacity
    return payload


@pytest.mark.integration
@pytest.mark.failure
@pytest.mark.asyncio
async def test_fail_open_when_redis_times_out(client, app, admin_headers, monkeypatch) -> None:
    await client.post(
        "/admin/policies",
        json=route_policy(
            name="public-timeout-fail-open",
            route="/demo/public",
            burst_capacity=2,
            failure_mode="fail_open",
        ),
        headers=admin_headers,
    )

    async def raise_timeout(*args, **kwargs):
        raise TimeoutError("redis timeout")

    monkeypatch.setattr(app.state.redis, "eval", raise_timeout)

    response = await client.get("/demo/public")

    assert response.status_code == 200
    assert response.headers["Retry-After"] == "0"


@pytest.mark.integration
@pytest.mark.failure
@pytest.mark.asyncio
async def test_local_policy_snapshot_allows_requests_when_policy_cache_get_fails(
    client,
    app,
    admin_headers,
    monkeypatch,
) -> None:
    await client.post(
        "/admin/policies",
        json=route_policy(
            name="snapshot-fallback",
            route="/demo/protected",
            algorithm="fixed_window",
            rate=2,
        ),
        headers=admin_headers,
    )

    warm = await client.get("/demo/protected")
    assert warm.status_code == 200
    assert await app.state.policy_snapshot.get_fresh(60) is not None

    async def raise_cache_error(*args, **kwargs):
        raise RedisError("policy cache unavailable")

    monkeypatch.setattr(app.state.redis, "get", raise_cache_error)

    second = await client.get("/demo/protected")
    third = await client.get("/demo/protected")

    assert second.status_code == 200
    assert third.status_code == 429


@pytest.mark.integration
@pytest.mark.failure
@pytest.mark.asyncio
async def test_shared_state_survives_instance_restart(app_factory, admin_headers) -> None:
    app_a = app_factory(app_instance_name="instance-a")
    app_b = app_factory(app_instance_name="instance-b")
    lifespan_a = LifespanManager(app_a)
    lifespan_b = LifespanManager(app_b)
    restarted_lifespan: LifespanManager | None = None
    app_a_stopped = False

    await lifespan_a.__aenter__()
    await lifespan_b.__aenter__()
    try:
        async with AsyncExitStack() as stack:
            client_a = await stack.enter_async_context(
                AsyncClient(transport=ASGITransport(app=app_a), base_url="http://instance-a")
            )
            client_b = await stack.enter_async_context(
                AsyncClient(transport=ASGITransport(app=app_b), base_url="http://instance-b")
            )

            created = await client_a.post(
                "/admin/policies",
                json=route_policy(
                    name="restart-survival",
                    route="/demo/protected",
                    rate=3,
                    burst_capacity=3,
                ),
                headers=admin_headers,
            )
            assert created.status_code == 201

            first = await client_a.get("/demo/protected")
            second = await client_b.get("/demo/protected")
            assert [first.status_code, second.status_code] == [200, 200]

            await lifespan_a.__aexit__(None, None, None)
            app_a_stopped = True

            restarted_app_a = app_factory(app_instance_name="instance-a-restarted")
            restarted_lifespan = LifespanManager(restarted_app_a)
            await restarted_lifespan.__aenter__()

            restarted_client_a = await stack.enter_async_context(
                AsyncClient(
                    transport=ASGITransport(app=restarted_app_a),
                    base_url="http://instance-a-restarted",
                )
            )

            third = await restarted_client_a.get("/demo/protected")
            fourth = await client_b.get("/demo/protected")

            assert [third.status_code, fourth.status_code] == [200, 429]
    finally:
        if restarted_lifespan is not None:
            await restarted_lifespan.__aexit__(None, None, None)
        if not app_a_stopped:
            await lifespan_a.__aexit__(None, None, None)
        await lifespan_b.__aexit__(None, None, None)
