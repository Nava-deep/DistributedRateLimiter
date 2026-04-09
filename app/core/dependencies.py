from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.health_service import HealthService
from app.services.key_builder import build_request_identity
from app.services.policy_service import PolicyService
from app.services.rate_limiter import RateLimiterService


async def get_db_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.db.session() as session:
        yield session


async def get_policy_service(
    request: Request,
    session: DatabaseSessionDependency,
) -> PolicyService:
    return PolicyService(
        session=session,
        redis_client=request.app.state.redis,
        settings=request.app.state.settings,
        snapshot_store=request.app.state.policy_snapshot,
        logger=request.app.state.logger,
    )


async def get_rate_limiter(
    request: Request,
    policy_service: PolicyServiceDependency,
) -> RateLimiterService:
    return RateLimiterService(
        policy_service=policy_service,
        redis_client=request.app.state.redis,
        logger=request.app.state.logger,
    )


async def get_health_service(request: Request) -> HealthService:
    return HealthService(
        settings=request.app.state.settings,
        db_manager=request.app.state.db,
        redis_client=request.app.state.redis,
    )


DatabaseSessionDependency = Annotated[AsyncSession, Depends(get_db_session)]
PolicyServiceDependency = Annotated[PolicyService, Depends(get_policy_service)]
RateLimiterDependency = Annotated[RateLimiterService, Depends(get_rate_limiter)]


async def enforce_rate_limit(
    request: Request,
    response: Response,
    rate_limiter: RateLimiterDependency,
) -> None:
    identity = build_request_identity(request)
    decision, policy = await rate_limiter.evaluate(identity)

    if decision is None:
        return

    request.state.rate_limit_decision = decision
    request.state.effective_policy = policy

    for header_name, header_value in decision.headers.items():
        response.headers[header_name] = header_value

    if not decision.allowed:
        detail = "Rate limit exceeded."
        if decision.degraded:
            detail = "Rate limiter unavailable in fail-closed mode."
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=detail,
            headers=decision.headers,
        )
