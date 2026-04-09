from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.core.dependencies import enforce_rate_limit

router = APIRouter(prefix="/demo", tags=["demo"])


def build_demo_payload(request: Request, message: str) -> dict[str, object]:
    policy = getattr(request.state, "effective_policy", None)
    decision = getattr(request.state, "rate_limit_decision", None)

    return {
        "message": message,
        "instance": request.app.state.settings.app_instance_name,
        "route": getattr(request.scope.get("route"), "path", request.url.path),
        "policy": policy.model_dump(mode="json") if policy else None,
        "decision": decision.headers if decision else None,
    }


@router.get("/public", dependencies=[Depends(enforce_rate_limit)])
async def demo_public(request: Request) -> dict[str, object]:
    return build_demo_payload(
        request,
        (
            "Public endpoint reached. "
            "If Redis is unavailable and the policy is fail-open, requests continue."
        ),
    )


@router.get("/protected", dependencies=[Depends(enforce_rate_limit)])
async def demo_protected(request: Request) -> dict[str, object]:
    return build_demo_payload(
        request,
        (
            "Protected endpoint reached. "
            "In fail-closed mode the limiter blocks when Redis is unavailable."
        ),
    )


@router.get("/user/{user_id}", dependencies=[Depends(enforce_rate_limit)])
async def demo_user(user_id: str, request: Request) -> dict[str, object]:
    return build_demo_payload(
        request,
        (
            f"User-scoped endpoint reached for {user_id}. "
            "User-specific or composite policies take priority."
        ),
    )
