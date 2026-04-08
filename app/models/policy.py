from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import Boolean, DateTime, Enum, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RateLimitAlgorithm(StrEnum):
    FIXED_WINDOW = "fixed_window"
    SLIDING_WINDOW_LOG = "sliding_window_log"
    TOKEN_BUCKET = "token_bucket"


class FailureMode(StrEnum):
    FAIL_OPEN = "fail_open"
    FAIL_CLOSED = "fail_closed"


def describe_policy_scope(
    *,
    route: str | None,
    user_id: str | None,
    ip_address: str | None,
    tenant_id: str | None,
    api_key: str | None,
) -> str:
    labels: list[str] = []
    if tenant_id is not None:
        labels.append("tenant")
    if api_key is not None:
        labels.append("api_key")
    if user_id is not None:
        labels.append("user")
    if ip_address is not None:
        labels.append("ip")
    if route is not None:
        labels.append("route")
    return "+".join(labels) if labels else "global"


class RateLimitPolicy(Base):
    __tablename__ = "rate_limit_policies"
    __table_args__ = (
        UniqueConstraint("name", name="uq_rate_limit_policies_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    algorithm: Mapped[RateLimitAlgorithm] = mapped_column(
        Enum(
            RateLimitAlgorithm,
            name="rate_limit_algorithm",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
        default=RateLimitAlgorithm.TOKEN_BUCKET,
    )
    rate: Mapped[int] = mapped_column(Integer, nullable=False)
    window_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    burst_capacity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    route: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    user_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    tenant_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    api_key: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    failure_mode: Mapped[FailureMode] = mapped_column(
        Enum(
            FailureMode,
            name="failure_mode",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
        default=FailureMode.FAIL_CLOSED,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    def to_selector_kind(self) -> str:
        return describe_policy_scope(
            route=self.route,
            user_id=self.user_id,
            ip_address=self.ip_address,
            tenant_id=self.tenant_id,
            api_key=self.api_key,
        )

    def to_header_limit(self) -> int:
        return self.burst_capacity or self.rate

    def to_refill_rate_per_second(self) -> float:
        return self.rate / self.window_seconds

    def as_identity_selectors(self) -> dict[str, Any]:
        return {
            "route": self.route,
            "user_id": self.user_id,
            "ip_address": self.ip_address,
            "tenant_id": self.tenant_id,
            "api_key": self.api_key,
        }
