from __future__ import annotations

import logging
import math
import time
import uuid
from dataclasses import dataclass
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.logging import log_event
from app.core.metrics import mark_rate_limit_allowed, mark_rate_limit_blocked, mark_redis_error
from app.models.policy import FailureMode, RateLimitAlgorithm
from app.redis.scripts import FIXED_WINDOW_LUA, SLIDING_WINDOW_LOG_LUA, TOKEN_BUCKET_LUA
from app.schemas.policy import PolicyRead
from app.services.key_builder import RequestIdentity, build_rate_limit_key
from app.services.policy_service import PolicyService


@dataclass(slots=True)
class RateLimitDecision:
    allowed: bool
    limit: int
    remaining: int
    reset_at_epoch_seconds: int
    retry_after_seconds: int
    degraded: bool = False

    @property
    def headers(self) -> dict[str, str]:
        return {
            "X-RateLimit-Limit": str(self.limit),
            "X-RateLimit-Remaining": str(max(0, self.remaining)),
            "X-RateLimit-Reset": str(self.reset_at_epoch_seconds),
            "Retry-After": str(max(0, self.retry_after_seconds)),
        }


class RateLimiterService:
    def __init__(
        self,
        *,
        policy_service: PolicyService,
        redis_client: Redis,
        logger: logging.Logger,
    ) -> None:
        self.policy_service = policy_service
        self.redis_client = redis_client
        self.logger = logger

    async def evaluate(
        self,
        identity: RequestIdentity,
    ) -> tuple[RateLimitDecision | None, PolicyRead | None]:
        policy = await self.policy_service.resolve_policy(identity)
        if policy is None:
            return None, None

        try:
            decision = await self._run_policy(policy, identity)
        except RedisError as exc:
            mark_redis_error("rate_limit_apply")
            log_event(
                self.logger,
                logging.WARNING,
                "redis_fallback",
                operation="rate_limit_apply",
                policy_name=policy.name,
                error=str(exc),
            )
            decision = self._build_degraded_decision(policy)

        if decision.allowed:
            mark_rate_limit_allowed(str(policy.algorithm), policy.selector_kind)
            log_event(
                self.logger,
                logging.INFO,
                "allow",
                policy_name=policy.name,
                algorithm=str(policy.algorithm),
                selector_kind=policy.selector_kind,
                remaining=decision.remaining,
                degraded=decision.degraded,
            )
        else:
            mark_rate_limit_blocked(str(policy.algorithm), policy.selector_kind)
            log_event(
                self.logger,
                logging.WARNING,
                "block",
                policy_name=policy.name,
                algorithm=str(policy.algorithm),
                selector_kind=policy.selector_kind,
                remaining=decision.remaining,
                degraded=decision.degraded,
            )

        return decision, policy

    async def _run_policy(self, policy: PolicyRead, identity: RequestIdentity) -> RateLimitDecision:
        key = build_rate_limit_key(policy, identity)

        if policy.algorithm == RateLimitAlgorithm.FIXED_WINDOW:
            result = await self.redis_client.eval(
                FIXED_WINDOW_LUA,
                1,
                key,
                policy.rate,
                policy.window_seconds * 1000,
            )
            return self._parse_common_decision(result)

        if policy.algorithm == RateLimitAlgorithm.SLIDING_WINDOW_LOG:
            result = await self.redis_client.eval(
                SLIDING_WINDOW_LOG_LUA,
                1,
                key,
                policy.rate,
                policy.window_seconds * 1000,
                uuid.uuid4().hex,
            )
            return self._parse_common_decision(result)

        capacity = policy.burst_capacity or policy.rate
        window_ms = policy.window_seconds * 1000
        refill_per_ms = policy.rate / window_ms
        ttl_ms = int(max(window_ms, math.ceil((capacity / refill_per_ms) + window_ms)))
        result = await self.redis_client.eval(
            TOKEN_BUCKET_LUA,
            1,
            key,
            capacity,
            refill_per_ms,
            1,
            ttl_ms,
        )
        return self._parse_common_decision(result)

    def _build_degraded_decision(self, policy: PolicyRead) -> RateLimitDecision:
        now_epoch = int(time.time())
        if policy.failure_mode == FailureMode.FAIL_OPEN:
            return RateLimitDecision(
                allowed=True,
                limit=policy.header_limit,
                remaining=policy.header_limit,
                reset_at_epoch_seconds=now_epoch + policy.window_seconds,
                retry_after_seconds=0,
                degraded=True,
            )

        return RateLimitDecision(
            allowed=False,
            limit=policy.header_limit,
            remaining=0,
            reset_at_epoch_seconds=now_epoch + 1,
            retry_after_seconds=1,
            degraded=True,
        )

    @staticmethod
    def _parse_common_decision(result: Any) -> RateLimitDecision:
        allowed = bool(int(result[0]))
        limit = int(float(result[1]))
        remaining = int(float(result[2]))
        reset_at_epoch_seconds = math.ceil(int(float(result[3])) / 1000)
        retry_after_seconds = 0 if allowed else math.ceil(int(float(result[4])) / 1000)
        return RateLimitDecision(
            allowed=allowed,
            limit=limit,
            remaining=remaining,
            reset_at_epoch_seconds=reset_at_epoch_seconds,
            retry_after_seconds=retry_after_seconds,
        )
