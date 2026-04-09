from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.core.dependencies import get_policy_service
from app.core.security import require_admin_token
from app.schemas.policy import PolicyCreate, PolicyListResponse, PolicyRead, PolicyUpdate
from app.services.policy_service import PolicyNotFoundError, PolicyService

router = APIRouter(
    prefix="/admin/policies",
    tags=["admin"],
    dependencies=[Depends(require_admin_token)],
)

PolicyServiceDependency = Annotated[PolicyService, Depends(get_policy_service)]


@router.post("", response_model=PolicyRead, status_code=status.HTTP_201_CREATED)
async def create_policy(
    payload: PolicyCreate,
    policy_service: PolicyServiceDependency,
) -> PolicyRead:
    return await policy_service.create_policy(payload)


@router.get("", response_model=PolicyListResponse)
async def list_policies(
    policy_service: PolicyServiceDependency,
    active_only: Annotated[bool, Query()] = True,
) -> PolicyListResponse:
    items = await policy_service.list_policies(active_only=active_only)
    return PolicyListResponse(items=items, count=len(items))


@router.get("/{policy_id}", response_model=PolicyRead)
async def get_policy(
    policy_id: UUID,
    policy_service: PolicyServiceDependency,
) -> PolicyRead:
    try:
        return await policy_service.get_policy(policy_id)
    except PolicyNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Policy not found.",
        ) from exc


@router.put("/{policy_id}", response_model=PolicyRead)
async def update_policy(
    policy_id: UUID,
    payload: PolicyUpdate,
    policy_service: PolicyServiceDependency,
) -> PolicyRead:
    try:
        return await policy_service.update_policy(policy_id, payload)
    except PolicyNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Policy not found.",
        ) from exc


@router.delete("/{policy_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_policy(
    policy_id: UUID,
    policy_service: PolicyServiceDependency,
) -> Response:
    try:
        await policy_service.delete_policy(policy_id)
    except PolicyNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Policy not found.",
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
