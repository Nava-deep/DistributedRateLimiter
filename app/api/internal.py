from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.core.dependencies import PolicyServiceDependency, RateLimiterDependency
from app.core.security import require_service_token
from app.schemas.internal import (
    ConfigControlSyncRequest,
    ConfigControlSyncResponse,
    RateLimitEvaluationRequest,
    RateLimitEvaluationResponse,
)
from app.services.config_control_sync import ConfigControlSyncError, ConfigControlSyncService
from app.services.key_builder import RequestIdentity

router = APIRouter(
    prefix="/internal",
    tags=["internal"],
    dependencies=[Depends(require_service_token)],
)


@router.post("/evaluate", response_model=RateLimitEvaluationResponse)
async def evaluate_rate_limit(
    payload: RateLimitEvaluationRequest,
    rate_limiter: RateLimiterDependency,
) -> RateLimitEvaluationResponse:
    identity = RequestIdentity(**payload.model_dump())
    decision, policy = await rate_limiter.evaluate(identity)
    if decision is None:
        return RateLimitEvaluationResponse(allowed=True, applied=False)

    return RateLimitEvaluationResponse(
        allowed=decision.allowed,
        applied=policy is not None,
        degraded=decision.degraded,
        local_fallback=decision.local_fallback,
        retry_after_seconds=decision.retry_after_seconds,
        headers=decision.headers,
        policy=policy,
    )


@router.post("/sync/config-control", response_model=ConfigControlSyncResponse)
async def sync_policy_from_config_control(
    payload: ConfigControlSyncRequest,
    request: Request,
    policy_service: PolicyServiceDependency,
) -> ConfigControlSyncResponse:
    sync_service = ConfigControlSyncService(
        settings=request.app.state.settings,
        logger=request.app.state.logger,
    )
    try:
        policy, action, config_payload = await sync_service.sync_policy(
            policy_service=policy_service,
            config_name=payload.config_name,
            environment=payload.environment,
            target=payload.target,
        )
    except ConfigControlSyncError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    return ConfigControlSyncResponse(
        config_name=config_payload["name"],
        environment=config_payload["environment"],
        target=config_payload["target"],
        config_version=config_payload["version"],
        action=action,
        policy=policy,
    )
