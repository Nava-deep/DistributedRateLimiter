from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.services.key_builder import RequestIdentity
from app.services.policy_matcher import policy_matches, select_best_policy


@dataclass(slots=True)
class DummyPolicy:
    name: str
    active: bool = True
    route: str | None = None
    user_id: str | None = None
    ip_address: str | None = None
    tenant_id: str | None = None
    api_key: str | None = None
    priority: int = 0
    version: int = 1


@pytest.mark.unit
def test_select_best_policy_prefers_user_route_over_route() -> None:
    identity = RequestIdentity(
        route="/demo/user/{user_id}",
        user_id="alice",
        ip_address="127.0.0.1",
        tenant_id=None,
        api_key=None,
    )
    policies = [
        DummyPolicy(name="route-default", route="/demo/user/{user_id}"),
        DummyPolicy(name="user-route", route="/demo/user/{user_id}", user_id="alice"),
    ]

    selected = select_best_policy(policies, identity)

    assert selected is not None
    assert selected.name == "user-route"


@pytest.mark.unit
def test_select_best_policy_prefers_user_over_route_with_same_specificity() -> None:
    identity = RequestIdentity(
        route="/demo/protected",
        user_id="alice",
        ip_address="127.0.0.1",
        tenant_id=None,
        api_key=None,
    )
    policies = [
        DummyPolicy(name="route-default", route="/demo/protected"),
        DummyPolicy(name="user-default", user_id="alice"),
    ]

    selected = select_best_policy(policies, identity)

    assert selected is not None
    assert selected.name == "user-default"


@pytest.mark.unit
def test_select_best_policy_returns_route_fallback_when_user_specific_absent() -> None:
    identity = RequestIdentity(
        route="/demo/user/{user_id}",
        user_id="bob",
        ip_address="127.0.0.1",
        tenant_id=None,
        api_key=None,
    )
    policies = [
        DummyPolicy(name="user-default", user_id="alice"),
        DummyPolicy(name="route-default", route="/demo/user/{user_id}"),
    ]

    selected = select_best_policy(policies, identity)

    assert selected is not None
    assert selected.name == "route-default"


@pytest.mark.unit
def test_select_best_policy_supports_tenant_and_api_key() -> None:
    identity = RequestIdentity(
        route="/demo/protected",
        user_id=None,
        ip_address="127.0.0.1",
        tenant_id="tenant-a",
        api_key="key-123",
    )
    policies = [
        DummyPolicy(name="tenant-only", tenant_id="tenant-a"),
        DummyPolicy(name="tenant-api-key", tenant_id="tenant-a", api_key="key-123"),
    ]

    selected = select_best_policy(policies, identity)

    assert selected is not None
    assert selected.name == "tenant-api-key"


@pytest.mark.unit
def test_policy_matches_requires_all_non_null_selectors() -> None:
    identity = RequestIdentity(
        route="/demo/protected",
        user_id="alice",
        ip_address="127.0.0.1",
        tenant_id=None,
        api_key=None,
    )
    policy = DummyPolicy(name="mismatch", route="/demo/public", user_id="alice")

    assert policy_matches(policy, identity) is False


@pytest.mark.unit
def test_select_best_policy_prefers_higher_priority_for_same_scope() -> None:
    identity = RequestIdentity(
        route="/demo/protected",
        user_id=None,
        ip_address="127.0.0.1",
        tenant_id=None,
        api_key=None,
    )
    policies = [
        DummyPolicy(name="low-priority", route="/demo/protected", priority=1),
        DummyPolicy(name="high-priority", route="/demo/protected", priority=10),
    ]

    selected = select_best_policy(policies, identity)

    assert selected is not None
    assert selected.name == "high-priority"
