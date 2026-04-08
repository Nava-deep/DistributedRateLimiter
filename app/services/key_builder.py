from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import Request


@dataclass(slots=True, frozen=True)
class RequestIdentity:
    route: str
    user_id: str | None
    ip_address: str | None
    tenant_id: str | None
    api_key: str | None


def extract_client_ip(request: Request) -> str | None:
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()

    if request.client and request.client.host:
        return request.client.host

    return None


def build_request_identity(request: Request) -> RequestIdentity:
    route_template = getattr(request.scope.get("route"), "path", request.url.path)
    return RequestIdentity(
        route=route_template,
        user_id=request.path_params.get("user_id") or request.headers.get("X-User-Id"),
        ip_address=extract_client_ip(request),
        tenant_id=request.headers.get("X-Tenant-Id"),
        api_key=request.headers.get("X-Api-Key"),
    )


def build_rate_limit_key(policy: Any, identity: RequestIdentity) -> str:
    segments = [
        "rl",
        str(policy.algorithm),
        str(policy.id),
        f"v{policy.version}",
    ]

    if policy.route is not None:
        segments.append(f"route={identity.route}")
    if policy.user_id is not None:
        segments.append(f"user={identity.user_id or policy.user_id}")
    if policy.ip_address is not None:
        segments.append(f"ip={identity.ip_address or policy.ip_address}")
    if policy.tenant_id is not None:
        segments.append(f"tenant={identity.tenant_id or policy.tenant_id}")
    if policy.api_key is not None:
        segments.append(f"api_key={identity.api_key or policy.api_key}")

    return ":".join(segments)

