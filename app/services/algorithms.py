from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(slots=True)
class FixedWindowState:
    window_start_ms: int
    count: int


@dataclass(slots=True)
class TokenBucketState:
    tokens: float
    last_refill_ms: int


@dataclass(slots=True)
class RateLimitComputation:
    allowed: bool
    remaining: int
    reset_at_ms: int
    retry_after_ms: int
    observed_value: float


def apply_fixed_window(
    *,
    now_ms: int,
    state: FixedWindowState | None,
    limit: int,
    window_seconds: int,
) -> tuple[FixedWindowState, RateLimitComputation]:
    window_ms = window_seconds * 1000
    expected_start = now_ms - (now_ms % window_ms)

    if state is None or state.window_start_ms != expected_start:
        state = FixedWindowState(window_start_ms=expected_start, count=0)

    next_count = state.count + 1
    allowed = next_count <= limit
    if allowed:
        state.count = next_count

    reset_at_ms = expected_start + window_ms
    remaining = max(0, limit - (state.count if allowed else next_count))
    retry_after_ms = max(0, reset_at_ms - now_ms)

    return state, RateLimitComputation(
        allowed=allowed,
        remaining=remaining,
        reset_at_ms=reset_at_ms,
        retry_after_ms=retry_after_ms,
        observed_value=float(state.count if allowed else next_count),
    )


def apply_sliding_window_log(
    *,
    now_ms: int,
    events_ms: list[int],
    limit: int,
    window_seconds: int,
) -> tuple[list[int], RateLimitComputation]:
    window_ms = window_seconds * 1000
    cutoff = now_ms - window_ms
    active_events = [value for value in events_ms if value > cutoff]

    allowed = len(active_events) < limit
    if allowed:
        active_events.append(now_ms)

    oldest_ts = active_events[0] if active_events else now_ms
    reset_at_ms = oldest_ts + window_ms
    retry_after_ms = max(0, reset_at_ms - now_ms)
    remaining = max(0, limit - len(active_events))

    return active_events, RateLimitComputation(
        allowed=allowed,
        remaining=remaining,
        reset_at_ms=reset_at_ms,
        retry_after_ms=retry_after_ms,
        observed_value=float(len(active_events)),
    )


def apply_token_bucket(
    *,
    now_ms: int,
    state: TokenBucketState | None,
    capacity: int,
    refill_rate_per_second: float,
    requested_tokens: float = 1.0,
) -> tuple[TokenBucketState, RateLimitComputation]:
    if state is None:
        state = TokenBucketState(tokens=float(capacity), last_refill_ms=now_ms)

    elapsed_ms = max(0, now_ms - state.last_refill_ms)
    refill_amount = (elapsed_ms / 1000.0) * refill_rate_per_second
    available_tokens = min(float(capacity), state.tokens + refill_amount)

    allowed = available_tokens >= requested_tokens
    if allowed:
        available_tokens -= requested_tokens

    state.tokens = available_tokens
    state.last_refill_ms = now_ms

    missing_tokens = max(0.0, requested_tokens - available_tokens)
    retry_after_ms = 0
    if not allowed:
        retry_after_ms = math.ceil((missing_tokens / refill_rate_per_second) * 1000)

    refill_to_full_ms = math.ceil(((capacity - available_tokens) / refill_rate_per_second) * 1000)
    reset_at_ms = now_ms + max(0, refill_to_full_ms)

    return state, RateLimitComputation(
        allowed=allowed,
        remaining=max(0, math.floor(available_tokens)),
        reset_at_ms=reset_at_ms,
        retry_after_ms=retry_after_ms,
        observed_value=available_tokens,
    )

