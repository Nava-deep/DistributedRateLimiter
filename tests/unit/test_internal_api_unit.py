from __future__ import annotations

import logging
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.internal import evaluate_rate_limit, sync_policy_from_config_control
from app.models.policy import FailureMode, RateLimitAlgorithm
from app.schemas.internal import ConfigControlSyncRequest, RateLimitEvaluationRequest
from app.schemas.policy import PolicyRead
from app.services.config_control_sync import ConfigControlSyncError
from app.services.rate_limiter import RateLimitDecision


@pytest.mark.unit
@pytest.mark.asyncio
async def test_evaluate_rate_limit_returns_non_applied_allow_when_no_policy_matches() -> None:
    rate_limiter = SimpleNamespace(evaluate=AsyncMock(return_value=(None, None)))

    response = await evaluate_rate_limit(
        RateLimitEvaluationRequest(route="/api/submissions/submit/"),
        rate_limiter,
    )

    assert response.allowed is True
    assert response.applied is False
    assert response.policy is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_evaluate_rate_limit_returns_policy_decision_payload() -> None:
    decision = RateLimitDecision(
        allowed=False,
        limit=5,
        remaining=0,
        reset_at_epoch_seconds=1700000000,
        retry_after_seconds=7,
        degraded=True,
        local_fallback=True,
    )
    policy = PolicyRead(
        id=uuid4(),
        name="judge-vortex-submission-limit",
        description="Protect submission spikes.",
        algorithm=RateLimitAlgorithm.TOKEN_BUCKET,
        rate=5,
        window_seconds=60,
        burst_capacity=5,
        active=True,
        priority=1,
        version=1,
        route="/api/submissions/submit/",
        user_id=None,
        ip_address=None,
        tenant_id=None,
        api_key=None,
        failure_mode=FailureMode.FAIL_CLOSED,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    rate_limiter = SimpleNamespace(evaluate=AsyncMock(return_value=(decision, policy)))

    response = await evaluate_rate_limit(
        RateLimitEvaluationRequest(
            route="/api/submissions/submit/",
            user_id="student-1",
        ),
        rate_limiter,
    )

    assert response.allowed is False
    assert response.applied is True
    assert response.retry_after_seconds == 7
    assert response.degraded is True
    assert response.local_fallback is True
    assert response.headers["X-RateLimit-Limit"] == "5"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sync_policy_from_config_control_returns_sync_metadata(monkeypatch) -> None:
    synced_policy = PolicyRead(
        id=uuid4(),
        name="judge-vortex-submission-limit",
        description="Protect submission spikes.",
        algorithm=RateLimitAlgorithm.TOKEN_BUCKET,
        rate=6,
        window_seconds=60,
        burst_capacity=8,
        active=True,
        priority=10,
        version=1,
        route="/api/submissions/submit/",
        user_id=None,
        ip_address=None,
        tenant_id=None,
        api_key=None,
        failure_mode=FailureMode.FAIL_CLOSED,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                settings=SimpleNamespace(),
                logger=logging.getLogger("test-sync"),
            )
        )
    )
    policy_service = object()

    async def fake_sync_policy(self, *, policy_service, config_name, environment, target):
        assert config_name is None
        assert environment is None
        assert target is None
        return (
            synced_policy,
            "created",
            {
                "name": "judge-vortex.submission-rate-limit-policy",
                "environment": "prod",
                "target": "judge-vortex",
                "version": 3,
            },
        )

    monkeypatch.setattr(
        "app.api.internal.ConfigControlSyncService.sync_policy",
        fake_sync_policy,
    )

    response = await sync_policy_from_config_control(
        ConfigControlSyncRequest(),
        request,
        policy_service,
    )

    assert response.action == "created"
    assert response.config_version == 3
    assert response.target == "judge-vortex"
    assert response.policy.name == "judge-vortex-submission-limit"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sync_policy_from_config_control_maps_errors_to_503(monkeypatch) -> None:
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                settings=SimpleNamespace(),
                logger=logging.getLogger("test-sync"),
            )
        )
    )

    async def fake_sync_policy(self, *, policy_service, config_name, environment, target):
        raise ConfigControlSyncError("config fetch failed")

    monkeypatch.setattr(
        "app.api.internal.ConfigControlSyncService.sync_policy",
        fake_sync_policy,
    )

    with pytest.raises(HTTPException) as exc_info:
        await sync_policy_from_config_control(
            ConfigControlSyncRequest(),
            request,
            object(),
        )

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "config fetch failed"
