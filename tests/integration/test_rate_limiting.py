from __future__ import annotations

import pytest


def policy_payload(*, name: str, algorithm: str, route: str, rate: int, window_seconds: int = 60, **extra):
    payload = {
        "name": name,
        "algorithm": algorithm,
        "rate": rate,
        "window_seconds": window_seconds,
        "route": route,
        "failure_mode": "fail_closed",
    }
    payload.update(extra)
    return payload


@pytest.mark.integration
@pytest.mark.asyncio
async def test_token_bucket_blocks_after_limit(client, admin_headers) -> None:
    await client.post(
        "/admin/policies",
        json=policy_payload(
            name="protected-token",
            algorithm="token_bucket",
            route="/demo/protected",
            rate=2,
            burst_capacity=2,
        ),
        headers=admin_headers,
    )

    first = await client.get("/demo/protected")
    second = await client.get("/demo/protected")
    third = await client.get("/demo/protected")

    assert [first.status_code, second.status_code, third.status_code] == [200, 200, 429]
    assert third.headers["X-RateLimit-Limit"] == "2"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_fixed_window_blocks_after_limit(client, admin_headers) -> None:
    await client.post(
        "/admin/policies",
        json=policy_payload(
            name="public-fixed",
            algorithm="fixed_window",
            route="/demo/public",
            rate=1,
        ),
        headers=admin_headers,
    )

    first = await client.get("/demo/public")
    second = await client.get("/demo/public")

    assert first.status_code == 200
    assert second.status_code == 429


@pytest.mark.integration
@pytest.mark.asyncio
async def test_sliding_window_blocks_after_limit(client, admin_headers) -> None:
    await client.post(
        "/admin/policies",
        json=policy_payload(
            name="user-sliding",
            algorithm="sliding_window_log",
            route="/demo/user/{user_id}",
            rate=2,
        ),
        headers=admin_headers,
    )

    first = await client.get("/demo/user/alice")
    second = await client.get("/demo/user/alice")
    third = await client.get("/demo/user/alice")

    assert [first.status_code, second.status_code, third.status_code] == [200, 200, 429]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_route_fallback_applies_when_user_specific_policy_is_absent(client, admin_headers) -> None:
    await client.post(
        "/admin/policies",
        json=policy_payload(
            name="user-route-default",
            algorithm="fixed_window",
            route="/demo/user/{user_id}",
            rate=1,
        ),
        headers=admin_headers,
    )

    first = await client.get("/demo/user/bob")
    second = await client.get("/demo/user/bob")

    assert first.status_code == 200
    assert second.status_code == 429


@pytest.mark.integration
@pytest.mark.asyncio
async def test_user_specific_policy_overrides_route_default(client, admin_headers) -> None:
    await client.post(
        "/admin/policies",
        json=policy_payload(
            name="route-default",
            algorithm="fixed_window",
            route="/demo/user/{user_id}",
            rate=1,
        ),
        headers=admin_headers,
    )
    await client.post(
        "/admin/policies",
        json=policy_payload(
            name="alice-override",
            algorithm="fixed_window",
            route="/demo/user/{user_id}",
            user_id="alice",
            rate=2,
        ),
        headers=admin_headers,
    )

    alice_responses = [await client.get("/demo/user/alice") for _ in range(3)]
    bob_responses = [await client.get("/demo/user/bob") for _ in range(2)]

    assert [response.status_code for response in alice_responses] == [200, 200, 429]
    assert [response.status_code for response in bob_responses] == [200, 429]

