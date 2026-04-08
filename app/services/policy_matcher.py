from __future__ import annotations

from typing import Any, Iterable

from app.services.key_builder import RequestIdentity


def policy_matches(policy: Any, identity: RequestIdentity) -> bool:
    if policy.route is not None and policy.route != identity.route:
        return False
    if policy.user_id is not None and policy.user_id != identity.user_id:
        return False
    if policy.ip_address is not None and policy.ip_address != identity.ip_address:
        return False
    if policy.tenant_id is not None and policy.tenant_id != identity.tenant_id:
        return False
    if policy.api_key is not None and policy.api_key != identity.api_key:
        return False
    return True


def policy_score(policy: Any) -> tuple[int, int, int, int]:
    specificity = sum(
        value is not None
        for value in (
            policy.route,
            policy.user_id,
            policy.ip_address,
            policy.tenant_id,
            policy.api_key,
        )
    )
    selector_weight = (
        (20 if policy.user_id is not None else 0)
        + (18 if policy.api_key is not None else 0)
        + (16 if policy.tenant_id is not None else 0)
        + (14 if policy.ip_address is not None else 0)
        + (12 if policy.route is not None else 0)
    )
    return specificity, selector_weight, policy.priority, policy.version


def select_best_policy(policies: Iterable[Any], identity: RequestIdentity) -> Any | None:
    matching = [policy for policy in policies if policy.active and policy_matches(policy, identity)]
    if not matching:
        return None
    return max(matching, key=policy_score)

