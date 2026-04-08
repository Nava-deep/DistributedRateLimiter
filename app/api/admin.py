from __future__ import annotations

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


@router.post("", response_model=PolicyRead, status_code=status.HTTP_201_CREATED)
async def create_policy(
    payload: PolicyCreate,
    policy_service: PolicyService = Depends(get_policy_service),
) -> PolicyRead:
    return await policy_service.create_policy(payload)


@router.get("", response_model=PolicyListResponse)
async def list_policies(
    active_only: bool = Query(default=True),
    policy_service: PolicyService = Depends(get_policy_service),
) -> PolicyListResponse:
    items = await policy_service.list_policies(active_only=active_only)
    return PolicyListResponse(items=items, count=len(items))


@router.get("/{policy_id}", response_model=PolicyRead)
async def get_policy(
    policy_id: UUID,
    policy_service: PolicyService = Depends(get_policy_service),
) -> PolicyRead:
    try:
        return await policy_service.get_policy(policy_id)
    except PolicyNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Policy not found.") from exc


@router.put("/{policy_id}", response_model=PolicyRead)
async def update_policy(
    policy_id: UUID,
    payload: PolicyUpdate,
    policy_service: PolicyService = Depends(get_policy_service),
) -> PolicyRead:
    try:
        return await policy_service.update_policy(policy_id, payload)
    except PolicyNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Policy not found.") from exc


@router.delete("/{policy_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_policy(
    policy_id: UUID,
    policy_service: PolicyService = Depends(get_policy_service),
) -> Response:
    try:
        await policy_service.delete_policy(policy_id)
    except PolicyNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Policy not found.") from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)

