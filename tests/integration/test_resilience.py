from __future__ import annotations

import asyncio

import pytest
from redis.exceptions import RedisError


def route_policy(*, name: str, route: str, failure_mode: str):
    return {
        "name": name,
        "algorithm": "token_bucket",
        "rate": 5,
        "window_seconds": 60,
        "burst_capacity": 5,
        "route": route,
        "failure_mode": failure_mode,
    }


@pytest.mark.integration
@pytest.mark.failure
@pytest.mark.asyncio
async def test_fail_open_when_redis_is_unavailable(client, app, admin_headers, monkeypatch) -> None:
    await client.post(
        "/admin/policies",
        json=route_policy(name="public-fail-open", route="/demo/public", failure_mode="fail_open"),
        headers=admin_headers,
    )

    async def raise_redis_error(*args, **kwargs):
        raise RedisError("redis unavailable")

    monkeypatch.setattr(app.state.redis, "eval", raise_redis_error)

    response = await client.get("/demo/public")

    assert response.status_code == 200
    assert response.headers["X-RateLimit-Limit"] == "5"


@pytest.mark.integration
@pytest.mark.failure
@pytest.mark.asyncio
async def test_fail_closed_when_redis_is_unavailable(
    client,
    app,
    admin_headers,
    monkeypatch,
) -> None:
    await client.post(
        "/admin/policies",
        json=route_policy(
            name="protected-fail-closed",
            route="/demo/protected",
            failure_mode="fail_closed",
        ),
        headers=admin_headers,
    )

    async def raise_redis_error(*args, **kwargs):
        raise RedisError("redis unavailable")

    monkeypatch.setattr(app.state.redis, "eval", raise_redis_error)

    response = await client.get("/demo/protected")

    assert response.status_code == 429
    assert response.json()["detail"] == "Rate limiter unavailable in fail-closed mode."


@pytest.mark.integration
@pytest.mark.concurrency
@pytest.mark.asyncio
async def test_concurrent_requests_do_not_bypass_limit(client, admin_headers) -> None:
    await client.post(
        "/admin/policies",
        json={
            "name": "concurrent-protected",
            "algorithm": "token_bucket",
            "rate": 25,
            "window_seconds": 60,
            "burst_capacity": 25,
            "route": "/demo/protected",
            "failure_mode": "fail_closed",
        },
        headers=admin_headers,
    )

    async def hit_endpoint() -> int:
        response = await client.get("/demo/protected")
        return response.status_code

    status_codes = await asyncio.gather(*[hit_endpoint() for _ in range(50)])

    assert status_codes.count(200) == 25
    assert status_codes.count(429) == 25
