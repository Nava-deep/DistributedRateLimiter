from __future__ import annotations

import asyncio
import math
import time
from dataclasses import dataclass

from app.models.policy import RateLimitAlgorithm
from app.schemas.policy import PolicyRead
from app.services.algorithms import (
    FixedWindowState,
    TokenBucketState,
    apply_fixed_window,
    apply_sliding_window_log,
    apply_token_bucket,
)
from app.services.key_builder import RequestIdentity, build_rate_limit_key


@dataclass(slots=True)
class LocalFallbackDecision:
    allowed: bool
    limit: int
    remaining: int
    reset_at_epoch_seconds: int
    retry_after_seconds: int


@dataclass(slots=True)
class _StoredState:
    value: object
    expires_at_ms: int


class LocalFallbackLimiter:
    def __init__(self, *, state_ttl_seconds: int = 120) -> None:
        self._fixed_windows: dict[str, _StoredState] = {}
        self._sliding_windows: dict[str, _StoredState] = {}
        self._token_buckets: dict[str, _StoredState] = {}
        self._lock = asyncio.Lock()
        self._state_ttl_ms = max(1, state_ttl_seconds) * 1000

    async def clear(self) -> None:
        async with self._lock:
            self._fixed_windows.clear()
            self._sliding_windows.clear()
            self._token_buckets.clear()

    async def apply(
        self,
        policy: PolicyRead,
        identity: RequestIdentity,
        *,
        now_ms: int | None = None,
    ) -> LocalFallbackDecision:
        now_ms = now_ms or int(time.time() * 1000)
        key = build_rate_limit_key(policy, identity)

        async with self._lock:
            self._evict_expired(now_ms)

            if policy.algorithm == RateLimitAlgorithm.FIXED_WINDOW:
                return self._apply_fixed_window(policy, key, now_ms)

            if policy.algorithm == RateLimitAlgorithm.SLIDING_WINDOW_LOG:
                return self._apply_sliding_window(policy, key, now_ms)

            return self._apply_token_bucket(policy, key, now_ms)

    def _apply_fixed_window(
        self,
        policy: PolicyRead,
        key: str,
        now_ms: int,
    ) -> LocalFallbackDecision:
        stored = self._fixed_windows.get(key)
        state = stored.value if stored is not None else None
        if state is not None and not isinstance(state, FixedWindowState):
            raise TypeError("Unexpected fixed window state.")

        next_state, computation = apply_fixed_window(
            now_ms=now_ms,
            state=state,
            limit=policy.rate,
            window_seconds=policy.window_seconds,
        )
        self._fixed_windows[key] = _StoredState(
            value=next_state,
            expires_at_ms=max(computation.reset_at_ms, now_ms + self._state_ttl_ms),
        )
        return self._to_decision(policy, computation.allowed, computation.remaining, computation)

    def _apply_sliding_window(
        self,
        policy: PolicyRead,
        key: str,
        now_ms: int,
    ) -> LocalFallbackDecision:
        stored = self._sliding_windows.get(key)
        events = list(stored.value) if stored is not None else []
        if not isinstance(events, list):
            raise TypeError("Unexpected sliding window state.")

        next_events, computation = apply_sliding_window_log(
            now_ms=now_ms,
            events_ms=events,
            limit=policy.rate,
            window_seconds=policy.window_seconds,
        )
        self._sliding_windows[key] = _StoredState(
            value=next_events,
            expires_at_ms=max(computation.reset_at_ms, now_ms + self._state_ttl_ms),
        )
        return self._to_decision(policy, computation.allowed, computation.remaining, computation)

    def _apply_token_bucket(
        self,
        policy: PolicyRead,
        key: str,
        now_ms: int,
    ) -> LocalFallbackDecision:
        stored = self._token_buckets.get(key)
        state = stored.value if stored is not None else None
        if state is not None and not isinstance(state, TokenBucketState):
            raise TypeError("Unexpected token bucket state.")

        capacity = policy.burst_capacity or policy.rate
        next_state, computation = apply_token_bucket(
            now_ms=now_ms,
            state=state,
            capacity=capacity,
            refill_rate_per_second=policy.rate / policy.window_seconds,
        )
        refill_to_full_ms = math.ceil(
            ((capacity - next_state.tokens) / (policy.rate / policy.window_seconds)) * 1000,
        )
        self._token_buckets[key] = _StoredState(
            value=next_state,
            expires_at_ms=max(now_ms + refill_to_full_ms + self._state_ttl_ms, now_ms + 1000),
        )
        return self._to_decision(policy, computation.allowed, computation.remaining, computation)

    def _evict_expired(self, now_ms: int) -> None:
        for bucket in (self._fixed_windows, self._sliding_windows, self._token_buckets):
            expired = [key for key, state in bucket.items() if state.expires_at_ms <= now_ms]
            for key in expired:
                bucket.pop(key, None)

    @staticmethod
    def _to_decision(
        policy: PolicyRead,
        allowed: bool,
        remaining: int,
        computation,
    ) -> LocalFallbackDecision:
        retry_after_seconds = 0
        if not allowed:
            retry_after_seconds = math.ceil(computation.retry_after_ms / 1000)

        return LocalFallbackDecision(
            allowed=allowed,
            limit=policy.header_limit,
            remaining=remaining,
            reset_at_epoch_seconds=math.ceil(computation.reset_at_ms / 1000),
            retry_after_seconds=retry_after_seconds,
        )
