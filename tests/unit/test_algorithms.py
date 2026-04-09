from __future__ import annotations

import pytest

from app.services.algorithms import (
    FixedWindowState,
    TokenBucketState,
    apply_fixed_window,
    apply_sliding_window_log,
    apply_token_bucket,
)


@pytest.mark.unit
def test_token_bucket_refills_over_time() -> None:
    state = TokenBucketState(tokens=0.0, last_refill_ms=0)

    next_state, decision = apply_token_bucket(
        now_ms=5_000,
        state=state,
        capacity=10,
        refill_rate_per_second=2.0,
    )

    assert decision.allowed is True
    assert next_state.tokens == pytest.approx(9.0)
    assert decision.remaining == 9


@pytest.mark.unit
def test_token_bucket_allows_burst_until_capacity() -> None:
    state = TokenBucketState(tokens=3.0, last_refill_ms=0)

    state, first = apply_token_bucket(
        now_ms=0,
        state=state,
        capacity=3,
        refill_rate_per_second=1.0,
    )
    state, second = apply_token_bucket(
        now_ms=0,
        state=state,
        capacity=3,
        refill_rate_per_second=1.0,
    )
    state, third = apply_token_bucket(
        now_ms=0,
        state=state,
        capacity=3,
        refill_rate_per_second=1.0,
    )

    assert [first.allowed, second.allowed, third.allowed] == [True, True, True]
    assert state.tokens == pytest.approx(0.0)


@pytest.mark.unit
def test_token_bucket_blocks_when_empty() -> None:
    state = TokenBucketState(tokens=0.25, last_refill_ms=0)

    _, decision = apply_token_bucket(
        now_ms=0,
        state=state,
        capacity=5,
        refill_rate_per_second=1.0,
    )

    assert decision.allowed is False
    assert decision.retry_after_ms == 750


@pytest.mark.unit
def test_token_bucket_refill_does_not_exceed_capacity() -> None:
    state = TokenBucketState(tokens=1.0, last_refill_ms=0)

    next_state, decision = apply_token_bucket(
        now_ms=30_000,
        state=state,
        capacity=5,
        refill_rate_per_second=10.0,
    )

    assert decision.allowed is True
    assert next_state.tokens == pytest.approx(4.0)
    assert decision.remaining == 4


@pytest.mark.unit
def test_fixed_window_counts_within_same_window() -> None:
    state = FixedWindowState(window_start_ms=0, count=0)

    state, first = apply_fixed_window(now_ms=1_000, state=state, limit=2, window_seconds=60)
    state, second = apply_fixed_window(now_ms=2_000, state=state, limit=2, window_seconds=60)

    assert first.allowed is True
    assert second.allowed is True
    assert state.count == 2


@pytest.mark.unit
def test_fixed_window_resets_on_next_window() -> None:
    state = FixedWindowState(window_start_ms=0, count=2)

    next_state, decision = apply_fixed_window(
        now_ms=61_000,
        state=state,
        limit=2,
        window_seconds=60,
    )

    assert decision.allowed is True
    assert next_state.window_start_ms == 60_000
    assert next_state.count == 1


@pytest.mark.unit
def test_sliding_window_drops_expired_events() -> None:
    events = [0, 10_000, 70_000]

    next_events, decision = apply_sliding_window_log(
        now_ms=80_000,
        events_ms=events,
        limit=2,
        window_seconds=60,
    )

    assert decision.allowed is True
    assert next_events == [70_000, 80_000]


@pytest.mark.unit
def test_sliding_window_blocks_at_limit() -> None:
    events = [40_000, 45_000]

    next_events, decision = apply_sliding_window_log(
        now_ms=50_000,
        events_ms=events,
        limit=2,
        window_seconds=60,
    )

    assert decision.allowed is False
    assert next_events == events
    assert decision.retry_after_ms == 50_000
