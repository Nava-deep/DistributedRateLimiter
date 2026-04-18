from __future__ import annotations

import pytest

from app.core.metrics import (
    LOCAL_FAILOVER_TOTAL,
    POLICY_CACHE_HITS_TOTAL,
    POLICY_CACHE_MISSES_TOTAL,
    RATE_LIMIT_ALLOWED_TOTAL,
    RATE_LIMIT_BLOCKED_TOTAL,
    REDIS_ERRORS_TOTAL,
    REDIS_RETRIES_TOTAL,
    mark_local_failover,
    mark_policy_cache_hit,
    mark_policy_cache_miss,
    mark_rate_limit_allowed,
    mark_rate_limit_blocked,
    mark_redis_error,
    mark_redis_retry,
    render_metrics,
)


def counter_value_or_zero(counter, **labels: str) -> float:
    sample_name = f"{counter._name}_total"
    for metric in counter.collect():
        for sample in metric.samples:
            if sample.name == sample_name and sample.labels == labels:
                return sample.value
    return 0.0


def scalar_counter_value(counter) -> float:
    sample_name = f"{counter._name}_total"
    for metric in counter.collect():
        for sample in metric.samples:
            if sample.name == sample_name:
                return sample.value
    raise AssertionError(f"No sample found for {sample_name}")


@pytest.mark.unit
def test_mark_rate_limit_allowed_increments_counter() -> None:
    before = counter_value_or_zero(
        RATE_LIMIT_ALLOWED_TOTAL,
        algorithm="token_bucket",
        selector_kind="route",
    )

    mark_rate_limit_allowed("token_bucket", "route")

    after = counter_value_or_zero(
        RATE_LIMIT_ALLOWED_TOTAL,
        algorithm="token_bucket",
        selector_kind="route",
    )
    assert after == before + 1


@pytest.mark.unit
def test_mark_rate_limit_blocked_increments_counter() -> None:
    before = counter_value_or_zero(
        RATE_LIMIT_BLOCKED_TOTAL,
        algorithm="fixed_window",
        selector_kind="ip+route",
    )

    mark_rate_limit_blocked("fixed_window", "ip+route")

    after = counter_value_or_zero(
        RATE_LIMIT_BLOCKED_TOTAL,
        algorithm="fixed_window",
        selector_kind="ip+route",
    )
    assert after == before + 1


@pytest.mark.unit
def test_mark_policy_cache_hit_increments_counter() -> None:
    before = scalar_counter_value(POLICY_CACHE_HITS_TOTAL)

    mark_policy_cache_hit()

    after = scalar_counter_value(POLICY_CACHE_HITS_TOTAL)
    assert after == before + 1


@pytest.mark.unit
def test_mark_policy_cache_miss_increments_counter() -> None:
    before = scalar_counter_value(POLICY_CACHE_MISSES_TOTAL)

    mark_policy_cache_miss()

    after = scalar_counter_value(POLICY_CACHE_MISSES_TOTAL)
    assert after == before + 1


@pytest.mark.unit
def test_mark_redis_error_increments_labelled_counter() -> None:
    before = counter_value_or_zero(REDIS_ERRORS_TOTAL, operation="policy_cache_get")

    mark_redis_error("policy_cache_get")

    after = counter_value_or_zero(REDIS_ERRORS_TOTAL, operation="policy_cache_get")
    assert after == before + 1


@pytest.mark.unit
def test_mark_redis_retry_increments_labelled_counter() -> None:
    before = counter_value_or_zero(REDIS_RETRIES_TOTAL, operation="rate_limit_apply")

    mark_redis_retry("rate_limit_apply")

    after = counter_value_or_zero(REDIS_RETRIES_TOTAL, operation="rate_limit_apply")
    assert after == before + 1


@pytest.mark.unit
def test_mark_local_failover_increments_labelled_counter() -> None:
    before = counter_value_or_zero(
        LOCAL_FAILOVER_TOTAL,
        algorithm="sliding_window_log",
        selector_kind="user+route",
    )

    mark_local_failover("sliding_window_log", "user+route")

    after = counter_value_or_zero(
        LOCAL_FAILOVER_TOTAL,
        algorithm="sliding_window_log",
        selector_kind="user+route",
    )
    assert after == before + 1


@pytest.mark.unit
def test_render_metrics_contains_new_failover_and_retry_metrics() -> None:
    response = render_metrics()
    body = response.body.decode("utf-8")

    assert "distributed_rate_limiter_local_failover_total" in body
    assert "distributed_rate_limiter_redis_retries_total" in body
