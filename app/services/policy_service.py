from __future__ import annotations

import json
import logging
from typing import Sequence
from uuid import UUID

from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.logging import log_event
from app.core.metrics import (
    mark_policy_cache_hit,
    mark_policy_cache_miss,
    mark_redis_error,
)
from app.models.policy import RateLimitPolicy
from app.schemas.policy import PolicyCreate, PolicyRead, PolicyUpdate
from app.services.key_builder import RequestIdentity
from app.services.policy_cache import PolicySnapshotStore
from app.services.policy_matcher import select_best_policy


class PolicyNotFoundError(Exception):
    pass


class PolicyService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        redis_client: Redis,
        settings: Settings,
        snapshot_store: PolicySnapshotStore,
        logger: logging.Logger,
    ) -> None:
        self.session = session
        self.redis_client = redis_client
        self.settings = settings
        self.snapshot_store = snapshot_store
        self.logger = logger

    async def create_policy(self, payload: PolicyCreate) -> PolicyRead:
        policy = RateLimitPolicy(**payload.model_dump())
        self.session.add(policy)
        await self.session.commit()
        await self.session.refresh(policy)
        await self.invalidate_policy_cache(reason="create", policy_id=str(policy.id))
        return PolicyRead.model_validate(policy)

    async def list_policies(self, *, active_only: bool = True) -> list[PolicyRead]:
        statement = select(RateLimitPolicy).order_by(
            desc(RateLimitPolicy.priority),
            desc(RateLimitPolicy.updated_at),
            RateLimitPolicy.name,
        )
        if active_only:
            statement = statement.where(RateLimitPolicy.active.is_(True))

        result = await self.session.execute(statement)
        policies: Sequence[RateLimitPolicy] = result.scalars().all()
        return [PolicyRead.model_validate(policy) for policy in policies]

    async def get_policy(self, policy_id: UUID) -> PolicyRead:
        policy = await self.session.get(RateLimitPolicy, policy_id)
        if policy is None:
            raise PolicyNotFoundError(str(policy_id))
        return PolicyRead.model_validate(policy)

    async def update_policy(self, policy_id: UUID, payload: PolicyUpdate) -> PolicyRead:
        policy = await self.session.get(RateLimitPolicy, policy_id)
        if policy is None:
            raise PolicyNotFoundError(str(policy_id))

        update_data = payload.model_dump(exclude_unset=True)
        if update_data:
            merged_payload = self._to_policy_payload(policy) | update_data
            PolicyCreate(**merged_payload)

            for field, value in update_data.items():
                setattr(policy, field, value)
            policy.version += 1

            await self.session.commit()
            await self.session.refresh(policy)
            await self.invalidate_policy_cache(reason="update", policy_id=str(policy.id))

        return PolicyRead.model_validate(policy)

    async def delete_policy(self, policy_id: UUID) -> None:
        policy = await self.session.get(RateLimitPolicy, policy_id)
        if policy is None:
            raise PolicyNotFoundError(str(policy_id))

        await self.session.delete(policy)
        await self.session.commit()
        await self.invalidate_policy_cache(reason="delete", policy_id=str(policy.id))

    async def resolve_policy(self, identity: RequestIdentity) -> PolicyRead | None:
        policies = await self.list_active_policies_cached()
        return select_best_policy(policies, identity)

    async def list_active_policies_cached(self) -> list[PolicyRead]:
        try:
            payload = await self.redis_client.get(self.settings.policy_cache_key)
        except RedisError as exc:
            mark_redis_error("policy_cache_get")
            log_event(
                self.logger,
                logging.WARNING,
                "redis_fallback",
                operation="policy_cache_get",
                error=str(exc),
            )
            local_policies = await self.snapshot_store.get_fresh(
                self.settings.local_policy_cache_ttl_seconds,
            )
            if local_policies is not None:
                return local_policies

            database_policies = await self.list_policies(active_only=True)
            await self.snapshot_store.set(database_policies)
            return database_policies

        if payload:
            mark_policy_cache_hit()
            policies = [PolicyRead.model_validate(item) for item in json.loads(payload)]
            await self.snapshot_store.set(policies)
            log_event(
                self.logger,
                logging.INFO,
                "policy_load",
                source="redis",
                count=len(policies),
            )
            return policies

        mark_policy_cache_miss()
        policies = await self.list_policies(active_only=True)
        serialized = json.dumps([policy.model_dump(mode="json") for policy in policies])

        try:
            await self.redis_client.setex(
                self.settings.policy_cache_key,
                self.settings.policy_cache_ttl_seconds,
                serialized,
            )
        except RedisError as exc:
            mark_redis_error("policy_cache_set")
            log_event(
                self.logger,
                logging.WARNING,
                "redis_fallback",
                operation="policy_cache_set",
                error=str(exc),
            )

        await self.snapshot_store.set(policies)
        log_event(
            self.logger,
            logging.INFO,
            "policy_load",
            source="postgres",
            count=len(policies),
        )
        return policies

    async def invalidate_policy_cache(self, *, reason: str, policy_id: str) -> None:
        await self.snapshot_store.clear()

        payload = json.dumps({"reason": reason, "policy_id": policy_id})
        try:
            await self.redis_client.delete(self.settings.policy_cache_key)
            if self.settings.enable_policy_pubsub:
                await self.redis_client.publish(self.settings.policy_refresh_channel, payload)
        except RedisError as exc:
            mark_redis_error("policy_cache_invalidate")
            log_event(
                self.logger,
                logging.WARNING,
                "redis_fallback",
                operation="policy_cache_invalidate",
                error=str(exc),
            )
            return

        log_event(
            self.logger,
            logging.INFO,
            "policy_cache_invalidated",
            reason=reason,
            policy_id=policy_id,
        )

    @staticmethod
    def _to_policy_payload(policy: RateLimitPolicy) -> dict[str, object]:
        return {
            "name": policy.name,
            "description": policy.description,
            "algorithm": policy.algorithm,
            "rate": policy.rate,
            "window_seconds": policy.window_seconds,
            "burst_capacity": policy.burst_capacity,
            "active": policy.active,
            "priority": policy.priority,
            "route": policy.route,
            "user_id": policy.user_id,
            "ip_address": policy.ip_address,
            "tenant_id": policy.tenant_id,
            "api_key": policy.api_key,
            "failure_mode": policy.failure_mode,
        }

