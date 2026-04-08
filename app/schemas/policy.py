from __future__ import annotations

from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from app.models.policy import FailureMode, RateLimitAlgorithm, describe_policy_scope


class PolicyBase(BaseModel):
    name: str = Field(..., min_length=3, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    algorithm: RateLimitAlgorithm = RateLimitAlgorithm.TOKEN_BUCKET
    rate: int = Field(..., gt=0, description="Number of requests or tokens added per window.")
    window_seconds: int = Field(..., gt=0, description="Window size in seconds.")
    burst_capacity: int | None = Field(
        default=None,
        gt=0,
        description="Token bucket capacity. Only valid when algorithm=token_bucket.",
    )
    active: bool = True
    priority: int = 0
    route: str | None = Field(default=None, max_length=255)
    user_id: str | None = Field(default=None, max_length=128)
    ip_address: str | None = Field(default=None, max_length=64)
    tenant_id: str | None = Field(default=None, max_length=128)
    api_key: str | None = Field(default=None, max_length=128)
    failure_mode: FailureMode = FailureMode.FAIL_CLOSED

    @model_validator(mode="after")
    def validate_algorithm_specifics(self) -> Self:
        if self.algorithm != RateLimitAlgorithm.TOKEN_BUCKET and self.burst_capacity is not None:
            raise ValueError("burst_capacity is only supported for token_bucket policies.")
        return self

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "name": "protected-route-default",
                    "description": "Default production policy for the protected demo endpoint.",
                    "algorithm": "token_bucket",
                    "rate": 10,
                    "window_seconds": 60,
                    "burst_capacity": 15,
                    "route": "/demo/protected",
                    "failure_mode": "fail_closed",
                },
                {
                    "name": "vip-user-override",
                    "description": "User-specific override for a single user on a route.",
                    "algorithm": "sliding_window_log",
                    "rate": 30,
                    "window_seconds": 60,
                    "route": "/demo/user/{user_id}",
                    "user_id": "vip-user",
                    "failure_mode": "fail_closed",
                },
            ]
        }
    )


class PolicyCreate(PolicyBase):
    pass


class PolicyUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=3, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    algorithm: RateLimitAlgorithm | None = None
    rate: int | None = Field(default=None, gt=0)
    window_seconds: int | None = Field(default=None, gt=0)
    burst_capacity: int | None = Field(default=None, gt=0)
    active: bool | None = None
    priority: int | None = None
    route: str | None = Field(default=None, max_length=255)
    user_id: str | None = Field(default=None, max_length=128)
    ip_address: str | None = Field(default=None, max_length=64)
    tenant_id: str | None = Field(default=None, max_length=128)
    api_key: str | None = Field(default=None, max_length=128)
    failure_mode: FailureMode | None = None


class PolicyRead(PolicyBase):
    id: UUID
    version: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @computed_field
    @property
    def selector_kind(self) -> str:
        return describe_policy_scope(
            route=self.route,
            user_id=self.user_id,
            ip_address=self.ip_address,
            tenant_id=self.tenant_id,
            api_key=self.api_key,
        )

    @computed_field
    @property
    def refill_rate_per_second(self) -> float:
        return round(self.rate / self.window_seconds, 6)

    @computed_field
    @property
    def header_limit(self) -> int:
        return self.burst_capacity or self.rate


class PolicyListResponse(BaseModel):
    items: list[PolicyRead]
    count: int

