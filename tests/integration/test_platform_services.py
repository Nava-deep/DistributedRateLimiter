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
