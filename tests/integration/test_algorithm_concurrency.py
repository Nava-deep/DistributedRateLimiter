from __future__ import annotations

import asyncio

import pytest


def policy_payload(
    *,
    name: str,
    algorithm: str,
    route: str,
    rate: int,
    window_seconds: int = 60,
    burst_capacity: int | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": name,
        "algorithm": algorithm,
        "rate": rate,
        "window_seconds": window_seconds,
        "route": route,
        "failure_mode": "fail_closed",
    }
    if burst_capacity is not None:
        payload["burst_capacity"] = burst_capacity
    return payload


@pytest.mark.integration
@pytest.mark.concurrency
@pytest.mark.asyncio
async def test_token_bucket_parallel_requests_match_exact_capacity(client, admin_headers) -> None:
    await client.post(
        "/admin/policies",
        json=policy_payload(
            name="token-bucket-concurrency",
            algorithm="token_bucket",
            route="/demo/protected",
            rate=10,
            burst_capacity=10,
        ),
        headers=admin_headers,
    )

    responses = await asyncio.gather(*[client.get("/demo/protected") for _ in range(30)])

    assert [response.status_code for response in responses].count(200) == 10
    assert [response.status_code for response in responses].count(429) == 20


@pytest.mark.integration
@pytest.mark.concurrency
@pytest.mark.asyncio
async def test_fixed_window_parallel_requests_do_not_exceed_limit(client, admin_headers) -> None:
    await client.post(
        "/admin/policies",
        json=policy_payload(
            name="fixed-window-concurrency",
            algorithm="fixed_window",
            route="/demo/public",
            rate=8,
        ),
        headers=admin_headers,
    )

    responses = await asyncio.gather(*[client.get("/demo/public") for _ in range(24)])

    assert [response.status_code for response in responses].count(200) == 8
    assert [response.status_code for response in responses].count(429) == 16


@pytest.mark.integration
@pytest.mark.concurrency
@pytest.mark.asyncio
async def test_sliding_window_parallel_requests_do_not_exceed_limit(client, admin_headers) -> None:
    await client.post(
        "/admin/policies",
        json=policy_payload(
            name="sliding-window-concurrency",
            algorithm="sliding_window_log",
            route="/demo/user/{user_id}",
            rate=6,
        ),
        headers=admin_headers,
    )

    responses = await asyncio.gather(*[client.get("/demo/user/alice") for _ in range(18)])

    assert [response.status_code for response in responses].count(200) == 6
    assert [response.status_code for response in responses].count(429) == 12
