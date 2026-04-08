from __future__ import annotations

import asyncio

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.db.session import DatabaseSessionManager
from app.redis.client import close_redis_client, create_redis_client
from app.schemas.policy import PolicyCreate
from app.services.policy_cache import PolicySnapshotStore
from app.services.policy_service import PolicyService


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    logger = get_logger("seed-demo-policies")
    db_manager = DatabaseSessionManager(settings.database_url)
    redis_client = create_redis_client(settings)

    seed_policies = [
        PolicyCreate(
            name="demo-public-route",
            description="Fail-open public route policy for demos.",
            algorithm="token_bucket",
            rate=30,
            window_seconds=60,
            burst_capacity=60,
            route="/demo/public",
            failure_mode="fail_open",
        ),
        PolicyCreate(
            name="demo-protected-route",
            description="Fail-closed protected route policy.",
            algorithm="token_bucket",
            rate=10,
            window_seconds=60,
            burst_capacity=15,
            route="/demo/protected",
            failure_mode="fail_closed",
        ),
        PolicyCreate(
            name="vip-user-route",
            description="User-specific override for the demo user route.",
            algorithm="sliding_window_log",
            rate=20,
            window_seconds=60,
            route="/demo/user/{user_id}",
            user_id="vip-user",
            failure_mode="fail_closed",
        ),
    ]

    try:
        async with db_manager.session() as session:
            policy_service = PolicyService(
                session=session,
                redis_client=redis_client,
                settings=settings,
                snapshot_store=PolicySnapshotStore(),
                logger=logger,
            )
            existing = {policy.name for policy in await policy_service.list_policies(active_only=False)}
            for payload in seed_policies:
                if payload.name not in existing:
                    await policy_service.create_policy(payload)
    finally:
        await close_redis_client(redis_client)
        await db_manager.dispose()


if __name__ == "__main__":
    asyncio.run(main())

