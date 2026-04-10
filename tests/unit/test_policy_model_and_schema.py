from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.models.policy import (
    FailureMode,
    RateLimitAlgorithm,
    RateLimitPolicy,
    describe_policy_scope,
)
from app.schemas.policy import PolicyCreate, PolicyRead

SCOPE_CASES = [
    (
        {
            "route": None,
            "user_id": None,
            "ip_address": None,
            "tenant_id": None,
            "api_key": None,
        },
        "global",
    ),
    (
        {
            "route": "/demo/public",
            "user_id": None,
            "ip_address": None,
            "tenant_id": None,
            "api_key": None,
        },
        "route",
    ),
    (
        {
            "route": None,
            "user_id": "alice",
            "ip_address": None,
            "tenant_id": None,
            "api_key": None,
        },
        "user",
    ),
    (
        {
            "route": None,
            "user_id": None,
            "ip_address": "203.0.113.10",
            "tenant_id": None,
            "api_key": None,
        },
        "ip",
    ),
    (
        {
            "route": None,
            "user_id": None,
            "ip_address": None,
            "tenant_id": "tenant-a",
            "api_key": None,
        },
        "tenant",
    ),
    (
        {
            "route": None,
            "user_id": None,
            "ip_address": None,
            "tenant_id": None,
            "api_key": "key-123",
        },
        "api_key",
    ),
    (
        {
            "route": "/demo/user/{user_id}",
            "user_id": "alice",
            "ip_address": None,
            "tenant_id": None,
            "api_key": None,
        },
        "user+route",
    ),
    (
        {
            "route": "/demo/protected",
            "user_id": None,
            "ip_address": "203.0.113.10",
            "tenant_id": None,
            "api_key": None,
        },
        "ip+route",
    ),
    (
        {
            "route": None,
            "user_id": None,
            "ip_address": None,
            "tenant_id": "tenant-a",
            "api_key": "key-123",
        },
        "tenant+api_key",
    ),
    (
        {
            "route": "/demo/protected",
            "user_id": "alice",
            "ip_address": "203.0.113.10",
            "tenant_id": "tenant-a",
            "api_key": "key-123",
        },
        "tenant+api_key+user+ip+route",
    ),
]


def build_policy_read(**overrides) -> PolicyRead:
    payload = {
        "id": uuid4(),
        "name": "default-policy",
        "description": "default description",
        "algorithm": RateLimitAlgorithm.TOKEN_BUCKET,
        "rate": 10,
        "window_seconds": 60,
        "burst_capacity": 15,
        "active": True,
        "priority": 1,
        "version": 2,
        "route": "/demo/protected",
        "user_id": None,
        "ip_address": None,
        "tenant_id": None,
        "api_key": None,
        "failure_mode": FailureMode.FAIL_CLOSED,
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }
    payload.update(overrides)
    return PolicyRead(**payload)


@pytest.mark.unit
@pytest.mark.parametrize(("selectors", "expected"), SCOPE_CASES)
def test_describe_policy_scope_returns_expected_labels(
    selectors: dict[str, str | None],
    expected: str,
) -> None:
    assert describe_policy_scope(**selectors) == expected


@pytest.mark.unit
@pytest.mark.parametrize(
    "algorithm",
    [RateLimitAlgorithm.FIXED_WINDOW, RateLimitAlgorithm.SLIDING_WINDOW_LOG],
)
def test_policy_create_rejects_burst_capacity_for_non_token_bucket(
    algorithm: RateLimitAlgorithm,
) -> None:
    with pytest.raises(ValidationError):
        PolicyCreate(
            name="invalid-policy",
            algorithm=algorithm,
            rate=5,
            window_seconds=60,
            burst_capacity=10,
            route="/demo/public",
        )


@pytest.mark.unit
def test_policy_create_accepts_burst_capacity_for_token_bucket() -> None:
    policy = PolicyCreate(
        name="token-policy",
        algorithm=RateLimitAlgorithm.TOKEN_BUCKET,
        rate=5,
        window_seconds=60,
        burst_capacity=10,
        route="/demo/public",
    )

    assert policy.burst_capacity == 10


@pytest.mark.unit
@pytest.mark.parametrize(
    ("burst_capacity", "rate", "expected"),
    [(None, 10, 10), (15, 10, 15)],
)
def test_policy_read_header_limit_uses_burst_capacity_when_available(
    burst_capacity: int | None,
    rate: int,
    expected: int,
) -> None:
    policy = build_policy_read(rate=rate, burst_capacity=burst_capacity)

    assert policy.header_limit == expected


@pytest.mark.unit
@pytest.mark.parametrize(
    ("rate", "window_seconds", "expected"),
    [(10, 60, 0.166667), (3, 2, 1.5), (7, 3, 2.333333)],
)
def test_policy_read_refill_rate_is_computed_and_rounded(
    rate: int,
    window_seconds: int,
    expected: float,
) -> None:
    policy = build_policy_read(rate=rate, window_seconds=window_seconds)

    assert policy.refill_rate_per_second == expected


@pytest.mark.unit
@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"route": "/demo/public", "user_id": None}, "route"),
        ({"route": "/demo/user/{user_id}", "user_id": "alice"}, "user+route"),
        ({"tenant_id": "tenant-a", "api_key": "key-123", "route": None}, "tenant+api_key"),
        (
            {
                "tenant_id": "tenant-a",
                "api_key": "key-123",
                "user_id": "alice",
                "ip_address": "203.0.113.10",
                "route": "/demo/protected",
            },
            "tenant+api_key+user+ip+route",
        ),
    ],
)
def test_policy_read_selector_kind_matches_scope(
    overrides: dict[str, str | None],
    expected: str,
) -> None:
    policy = build_policy_read(**overrides)

    assert policy.selector_kind == expected


@pytest.mark.unit
def test_rate_limit_policy_helper_methods_match_schema_properties() -> None:
    policy = RateLimitPolicy(
        name="helper-policy",
        algorithm=RateLimitAlgorithm.TOKEN_BUCKET,
        rate=12,
        window_seconds=60,
        burst_capacity=18,
        route="/demo/protected",
        failure_mode=FailureMode.FAIL_CLOSED,
    )

    assert policy.to_selector_kind() == "route"
    assert policy.to_header_limit() == 18
    assert policy.to_refill_rate_per_second() == 0.2


@pytest.mark.unit
def test_rate_limit_policy_identity_selectors_return_all_scope_fields() -> None:
    policy = RateLimitPolicy(
        name="selector-policy",
        algorithm=RateLimitAlgorithm.FIXED_WINDOW,
        rate=5,
        window_seconds=60,
        route="/demo/user/{user_id}",
        user_id="alice",
        ip_address="203.0.113.10",
        tenant_id="tenant-a",
        api_key="key-123",
        failure_mode=FailureMode.FAIL_OPEN,
    )

    assert policy.as_identity_selectors() == {
        "route": "/demo/user/{user_id}",
        "user_id": "alice",
        "ip_address": "203.0.113.10",
        "tenant_id": "tenant-a",
        "api_key": "key-123",
    }
