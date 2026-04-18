from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.api.services import build_service_payload
from app.models.policy import FailureMode, RateLimitAlgorithm
from app.schemas.policy import PolicyRead
from app.services.rate_limiter import RateLimitDecision


def build_policy() -> PolicyRead:
    return PolicyRead(
        id=uuid4(),
        name="service-policy",
        description="service policy",
        algorithm=RateLimitAlgorithm.TOKEN_BUCKET,
        rate=10,
        window_seconds=60,
        burst_capacity=10,
        active=True,
        priority=0,
        version=1,
        route="/services/auth/session",
        user_id=None,
        ip_address=None,
        tenant_id=None,
        api_key=None,
        failure_mode=FailureMode.FAIL_CLOSED,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def build_request(*, route_path: str, url_path: str) -> SimpleNamespace:
    return SimpleNamespace(
        state=SimpleNamespace(),
        scope={"route": SimpleNamespace(path=route_path)},
        url=SimpleNamespace(path=url_path),
        app=SimpleNamespace(state=SimpleNamespace(settings=SimpleNamespace(app_instance_name="api-1"))),
    )


@pytest.mark.unit
def test_build_service_payload_includes_policy_and_decision() -> None:
    request = build_request(route_path="/services/auth/session", url_path="/services/auth/session")
    request.state.effective_policy = build_policy()
    request.state.rate_limit_decision = RateLimitDecision(
        allowed=True,
        limit=10,
        remaining=9,
        reset_at_epoch_seconds=100,
        retry_after_seconds=0,
    )

    payload = build_service_payload(request, service="auth", operation="create-session")

    assert payload["service"] == "auth"
    assert payload["operation"] == "create-session"
    assert payload["instance"] == "api-1"
    assert payload["policy"] is not None
    assert payload["decision"] == {
        "X-RateLimit-Limit": "10",
        "X-RateLimit-Remaining": "9",
        "X-RateLimit-Reset": "100",
        "Retry-After": "0",
    }


@pytest.mark.unit
def test_build_service_payload_omits_policy_and_decision_when_missing() -> None:
    request = build_request(route_path="/services/search/query", url_path="/services/search/query")

    payload = build_service_payload(request, service="search", operation="query-index")

    assert payload["policy"] is None
    assert payload["decision"] is None


@pytest.mark.unit
def test_build_service_payload_falls_back_to_request_url_path() -> None:
    request = SimpleNamespace(
        state=SimpleNamespace(),
        scope={},
        url=SimpleNamespace(path="/services/payments/authorize"),
        app=SimpleNamespace(state=SimpleNamespace(settings=SimpleNamespace(app_instance_name="api-2"))),
    )

    payload = build_service_payload(request, service="payments", operation="authorize-charge")

    assert payload["route"] == "/services/payments/authorize"
    assert payload["instance"] == "api-2"
