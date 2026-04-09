from __future__ import annotations

import pytest


def scoped_policy(
    *,
    name: str,
    route: str | None = None,
    user_id: str | None = None,
    ip_address: str | None = None,
    algorithm: str = "fixed_window",
    rate: int = 1,
    window_seconds: int = 60,
    burst_capacity: int | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": name,
        "algorithm": algorithm,
        "rate": rate,
        "window_seconds": window_seconds,
        "failure_mode": "fail_closed",
    }
    if route is not None:
        payload["route"] = route
    if user_id is not None:
        payload["user_id"] = user_id
    if ip_address is not None:
        payload["ip_address"] = ip_address
    if burst_capacity is not None:
        payload["burst_capacity"] = burst_capacity
    return payload


@pytest.mark.integration
@pytest.mark.asyncio
async def test_per_ip_policy_enforces_limit_for_same_forwarded_ip(client, admin_headers) -> None:
    await client.post(
        "/admin/policies",
        json=scoped_policy(
            name="protected-ip-limit",
            route="/demo/protected",
            ip_address="203.0.113.10",
            rate=1,
        ),
        headers=admin_headers,
    )

    first = await client.get("/demo/protected", headers={"X-Forwarded-For": "203.0.113.10"})
    second = await client.get("/demo/protected", headers={"X-Forwarded-For": "203.0.113.10"})
    different_ip = await client.get("/demo/protected", headers={"X-Forwarded-For": "203.0.113.99"})

    assert first.status_code == 200
    assert second.status_code == 429
    assert different_ip.status_code == 200


@pytest.mark.integration
@pytest.mark.asyncio
async def test_per_route_policy_only_applies_to_matching_route(client, admin_headers) -> None:
    await client.post(
        "/admin/policies",
        json=scoped_policy(name="protected-only", route="/demo/protected", rate=1),
        headers=admin_headers,
    )

    first = await client.get("/demo/protected")
    second = await client.get("/demo/protected")
    public = await client.get("/demo/public")

    assert first.status_code == 200
    assert second.status_code == 429
    assert public.status_code == 200


@pytest.mark.integration
@pytest.mark.asyncio
async def test_composite_user_and_route_policy_only_limits_matching_user(
    client,
    admin_headers,
) -> None:
    await client.post(
        "/admin/policies",
        json=scoped_policy(
            name="alice-user-route",
            route="/demo/user/{user_id}",
            user_id="alice",
            rate=1,
        ),
        headers=admin_headers,
    )

    alice_first = await client.get("/demo/user/alice")
    alice_second = await client.get("/demo/user/alice")
    bob_first = await client.get("/demo/user/bob")
    bob_second = await client.get("/demo/user/bob")

    assert [alice_first.status_code, alice_second.status_code] == [200, 429]
    assert [bob_first.status_code, bob_second.status_code] == [200, 200]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_rate_limit_headers_are_returned_on_allow_and_block(client, admin_headers) -> None:
    await client.post(
        "/admin/policies",
        json=scoped_policy(
            name="protected-headers",
            route="/demo/protected",
            algorithm="token_bucket",
            rate=2,
            window_seconds=60,
            burst_capacity=2,
        ),
        headers=admin_headers,
    )

    first = await client.get("/demo/protected")
    second = await client.get("/demo/protected")
    third = await client.get("/demo/protected")

    for response in (first, third):
        assert "X-RateLimit-Limit" in response.headers
        assert "X-RateLimit-Remaining" in response.headers
        assert "X-RateLimit-Reset" in response.headers
        assert "Retry-After" in response.headers

    assert first.status_code == 200
    assert first.headers["X-RateLimit-Limit"] == "2"
    assert first.headers["X-RateLimit-Remaining"] == "1"
    assert second.status_code == 200
    assert second.headers["X-RateLimit-Remaining"] == "0"
    assert third.status_code == 429
    assert third.json()["detail"] == "Rate limit exceeded."
    assert third.headers["X-RateLimit-Remaining"] == "0"
    assert int(third.headers["Retry-After"]) >= 1
