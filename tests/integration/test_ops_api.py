from __future__ import annotations

import pytest
from redis.exceptions import RedisError


def protected_policy(name: str = "ops-protected", rate: int = 1) -> dict[str, object]:
    return {
        "name": name,
        "algorithm": "token_bucket",
        "rate": rate,
        "window_seconds": 60,
        "burst_capacity": rate,
        "route": "/demo/protected",
        "failure_mode": "fail_closed",
    }


@pytest.mark.integration
@pytest.mark.asyncio
async def test_health_endpoint_reports_healthy_dependencies(client) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["service"] == "distributed-rate-limiter-test"
    assert body["postgres"]["ok"] is True
    assert body["redis"]["ok"] is True


@pytest.mark.integration
@pytest.mark.asyncio
async def test_metrics_endpoint_returns_prometheus_text_payload(client) -> None:
    response = await client.get("/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "distributed_rate_limiter_http_requests_total" in response.text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_metrics_endpoint_exposes_allow_and_block_counters(client, admin_headers) -> None:
    await client.post(
        "/admin/policies",
        json=protected_policy(rate=1),
        headers=admin_headers,
    )

    await client.get("/demo/protected")
    await client.get("/demo/protected")
    metrics_response = await client.get("/metrics")

    assert metrics_response.status_code == 200
    assert "distributed_rate_limiter_allowed_requests_total" in metrics_response.text
    assert "distributed_rate_limiter_blocked_requests_total" in metrics_response.text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_metrics_endpoint_exposes_policy_cache_metrics_after_requests(
    client,
    admin_headers,
) -> None:
    await client.post(
        "/admin/policies",
        json=protected_policy(name="cache-metric-policy", rate=2),
        headers=admin_headers,
    )

    await client.get("/demo/protected")
    await client.get("/demo/protected")
    metrics_response = await client.get("/metrics")

    assert metrics_response.status_code == 200
    assert "distributed_rate_limiter_policy_cache_hits_total" in metrics_response.text
    assert "distributed_rate_limiter_policy_cache_misses_total" in metrics_response.text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_metrics_endpoint_exposes_failover_and_retry_counters(
    client,
    app,
    admin_headers,
    monkeypatch,
) -> None:
    await client.post(
        "/admin/policies",
        json=protected_policy(name="metrics-failover-policy", rate=1),
        headers=admin_headers,
    )
    monkeypatch.setattr(app.state.settings, "enable_local_fallback_limiter", True)
    monkeypatch.setattr(app.state.settings, "redis_retry_attempts", 1)
    attempts = {"count": 0}

    async def flaky_eval(*args, **kwargs):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RedisError("temporary redis failure")
        raise RedisError("persistent redis failure")

    monkeypatch.setattr(app.state.redis, "eval", flaky_eval)

    await client.get("/demo/protected")
    metrics_response = await client.get("/metrics")

    assert metrics_response.status_code == 200
    assert "distributed_rate_limiter_local_failover_total" in metrics_response.text
    assert "distributed_rate_limiter_redis_retries_total" in metrics_response.text
