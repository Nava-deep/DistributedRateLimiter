from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient


def protected_policy(
    *,
    name: str,
    rate: int,
    burst_capacity: int | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": name,
        "algorithm": "token_bucket",
        "rate": rate,
        "window_seconds": 60,
        "route": "/demo/protected",
        "failure_mode": "fail_closed",
    }
    if burst_capacity is not None:
        payload["burst_capacity"] = burst_capacity
    return payload


@pytest.mark.integration
@pytest.mark.asyncio
async def test_shared_redis_state_is_enforced_across_two_app_instances(
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

        response = await client_a.post(
            "/admin/policies",
            json=protected_policy(name="shared-state", rate=3, burst_capacity=3),
            headers=admin_headers,
        )
        assert response.status_code == 201

        first = await client_a.get("/demo/protected")
        second = await client_b.get("/demo/protected")
        third = await client_a.get("/demo/protected")
        fourth = await client_b.get("/demo/protected")

        assert [first.status_code, second.status_code, third.status_code, fourth.status_code] == [
            200,
            200,
            200,
            429,
        ]
        assert first.json()["instance"] == "instance-a"
        assert second.json()["instance"] == "instance-b"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_concurrent_burst_traffic_across_instances_matches_expected_counts(
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

        response = await client_a.post(
            "/admin/policies",
            json=protected_policy(name="shared-burst", rate=8, burst_capacity=8),
            headers=admin_headers,
        )
        assert response.status_code == 201

        async def hit_endpoint(index: int) -> int:
            client = client_a if index % 2 == 0 else client_b
            response = await client.get("/demo/protected")
            return response.status_code

        status_codes = await asyncio.gather(*[hit_endpoint(index) for index in range(16)])

        assert status_codes.count(200) == 8
        assert status_codes.count(429) == 8
