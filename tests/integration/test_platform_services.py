from __future__ import annotations

import pytest


def policy_payload(
    *,
    name: str,
    algorithm: str,
    route: str,
    rate: int,
    window_seconds: int = 60,
    **extra,
) -> dict[str, object]:
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
async def test_auth_service_route_is_rate_limited(client, admin_headers) -> None:
    await client.post(
        "/admin/policies",
        json=policy_payload(
            name="auth-service-limit",
            algorithm="token_bucket",
            route="/services/auth/session",
            rate=2,
            burst_capacity=2,
        ),
        headers=admin_headers,
    )

    first = await client.post("/services/auth/session")
    second = await client.post("/services/auth/session")
    third = await client.post("/services/auth/session")

    assert [first.status_code, second.status_code, third.status_code] == [200, 200, 429]
    assert first.json()["service"] == "auth"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_payments_service_route_is_rate_limited(client, admin_headers) -> None:
    await client.post(
        "/admin/policies",
        json=policy_payload(
            name="payments-service-limit",
            algorithm="sliding_window_log",
            route="/services/payments/authorize",
            rate=1,
        ),
        headers=admin_headers,
    )

    first = await client.post("/services/payments/authorize")
    second = await client.post("/services/payments/authorize")

    assert first.status_code == 200
    assert second.status_code == 429
    assert first.json()["service"] == "payments"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_search_service_route_is_rate_limited(client, admin_headers) -> None:
    await client.post(
        "/admin/policies",
        json=policy_payload(
            name="search-service-limit",
            algorithm="fixed_window",
            route="/services/search/query",
            rate=1,
        ),
        headers=admin_headers,
    )

    first = await client.get("/services/search/query")
    second = await client.get("/services/search/query")

    assert first.status_code == 200
    assert second.status_code == 429
    assert first.json()["service"] == "search"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_service_route_response_includes_policy_and_decision_headers(
    client,
    admin_headers,
) -> None:
    await client.post(
        "/admin/policies",
        json=policy_payload(
            name="auth-service-response-shape",
            algorithm="token_bucket",
            route="/services/auth/session",
            rate=3,
            burst_capacity=3,
        ),
        headers=admin_headers,
    )

    response = await client.post("/services/auth/session")
    body = response.json()

    assert response.status_code == 200
    assert body["policy"]["name"] == "auth-service-response-shape"
    assert body["decision"]["X-RateLimit-Limit"] == "3"
    assert response.headers["X-RateLimit-Limit"] == "3"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_user_specific_service_policy_override_beats_route_default(
    client,
    admin_headers,
) -> None:
    await client.post(
        "/admin/policies",
        json=policy_payload(
            name="auth-route-default",
            algorithm="fixed_window",
            route="/services/auth/session",
            rate=1,
        ),
        headers=admin_headers,
    )
    await client.post(
        "/admin/policies",
        json=policy_payload(
            name="auth-user-override",
            algorithm="fixed_window",
            route="/services/auth/session",
            rate=2,
            user_id="vip-user",
            priority=5,
        ),
        headers=admin_headers,
    )

    vip_headers = {"X-User-Id": "vip-user"}
    default_headers = {"X-User-Id": "other-user"}
    vip_responses = [
        await client.post("/services/auth/session", headers=vip_headers) for _ in range(3)
    ]
    other_responses = [
        await client.post("/services/auth/session", headers=default_headers) for _ in range(2)
    ]

    assert [response.status_code for response in vip_responses] == [200, 200, 429]
    assert [response.status_code for response in other_responses] == [200, 429]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_service_route_without_policy_is_not_limited(client) -> None:
    response = await client.get("/services/search/query")

    assert response.status_code == 200
    assert "X-RateLimit-Limit" not in response.headers
