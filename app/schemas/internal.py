from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.policy import PolicyRead


class RateLimitEvaluationRequest(BaseModel):
    route: str = Field(..., min_length=1, max_length=255)
    user_id: str | None = Field(default=None, max_length=128)
    ip_address: str | None = Field(default=None, max_length=64)
    tenant_id: str | None = Field(default=None, max_length=128)
    api_key: str | None = Field(default=None, max_length=128)


class RateLimitEvaluationResponse(BaseModel):
    allowed: bool
    applied: bool
    degraded: bool = False
    local_fallback: bool = False
    retry_after_seconds: int = 0
    headers: dict[str, str] = Field(default_factory=dict)
    policy: PolicyRead | None = None


class ConfigControlSyncRequest(BaseModel):
    config_name: str | None = None
    environment: str | None = None
    target: str | None = None


class ConfigControlSyncResponse(BaseModel):
    config_name: str
    environment: str
    target: str
    config_version: int
    action: str
    policy: PolicyRead
