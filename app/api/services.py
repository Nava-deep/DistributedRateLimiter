from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.core.dependencies import enforce_rate_limit

router = APIRouter(prefix="/services", tags=["services"])


def build_service_payload(request: Request, *, service: str, operation: str) -> dict[str, object]:
    policy = getattr(request.state, "effective_policy", None)
    decision = getattr(request.state, "rate_limit_decision", None)
    return {
        "service": service,
        "operation": operation,
        "instance": request.app.state.settings.app_instance_name,
        "route": getattr(request.scope.get("route"), "path", request.url.path),
        "policy": policy.model_dump(mode="json") if policy else None,
        "decision": decision.headers if decision else None,
        "message": (
            f"{service} handled {operation}. "
            "This route demonstrates how the limiter can protect platform services."
        ),
    }


@router.post("/auth/session", dependencies=[Depends(enforce_rate_limit)])
async def auth_session(request: Request) -> dict[str, object]:
    return build_service_payload(request, service="auth", operation="create-session")


@router.post("/payments/authorize", dependencies=[Depends(enforce_rate_limit)])
async def payments_authorize(request: Request) -> dict[str, object]:
    return build_service_payload(request, service="payments", operation="authorize-charge")


@router.get("/search/query", dependencies=[Depends(enforce_rate_limit)])
async def search_query(request: Request) -> dict[str, object]:
    return build_service_payload(request, service="search", operation="query-index")
