from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.dependencies import get_health_service
from app.core.metrics import render_metrics
from app.schemas.health import HealthResponse
from app.services.health_service import HealthService

router = APIRouter(tags=["ops"])

HealthServiceDependency = Annotated[HealthService, Depends(get_health_service)]


@router.get("/health", response_model=HealthResponse)
async def health(health_service: HealthServiceDependency) -> HealthResponse:
    return await health_service.get_health()


@router.get("/metrics")
async def metrics():
    return render_metrics()
