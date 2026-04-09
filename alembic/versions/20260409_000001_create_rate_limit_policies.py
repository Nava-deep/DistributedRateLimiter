"""create rate limit policies table

Revision ID: 20260409_000001
Revises:
Create Date: 2026-04-09 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260409_000001"
down_revision: str | None = None
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


rate_limit_algorithm = sa.Enum(
    "fixed_window",
    "sliding_window_log",
    "token_bucket",
    name="rate_limit_algorithm",
)
failure_mode = sa.Enum("fail_open", "fail_closed", name="failure_mode")


def upgrade() -> None:
    op.create_table(
        "rate_limit_policies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("algorithm", rate_limit_algorithm, nullable=False),
        sa.Column("rate", sa.Integer(), nullable=False),
        sa.Column("window_seconds", sa.Integer(), nullable=False),
        sa.Column("burst_capacity", sa.Integer(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("route", sa.String(length=255), nullable=True),
        sa.Column("user_id", sa.String(length=128), nullable=True),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("tenant_id", sa.String(length=128), nullable=True),
        sa.Column("api_key", sa.String(length=128), nullable=True),
        sa.Column("failure_mode", failure_mode, nullable=False, server_default="fail_closed"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("name", name="uq_rate_limit_policies_name"),
    )
    op.create_index("ix_rate_limit_policies_name", "rate_limit_policies", ["name"])
    op.create_index("ix_rate_limit_policies_route", "rate_limit_policies", ["route"])
    op.create_index("ix_rate_limit_policies_user_id", "rate_limit_policies", ["user_id"])
    op.create_index("ix_rate_limit_policies_ip_address", "rate_limit_policies", ["ip_address"])
    op.create_index("ix_rate_limit_policies_tenant_id", "rate_limit_policies", ["tenant_id"])
    op.create_index("ix_rate_limit_policies_api_key", "rate_limit_policies", ["api_key"])


def downgrade() -> None:
    op.drop_index("ix_rate_limit_policies_api_key", table_name="rate_limit_policies")
    op.drop_index("ix_rate_limit_policies_tenant_id", table_name="rate_limit_policies")
    op.drop_index("ix_rate_limit_policies_ip_address", table_name="rate_limit_policies")
    op.drop_index("ix_rate_limit_policies_user_id", table_name="rate_limit_policies")
    op.drop_index("ix_rate_limit_policies_route", table_name="rate_limit_policies")
    op.drop_index("ix_rate_limit_policies_name", table_name="rate_limit_policies")
    op.drop_table("rate_limit_policies")

    bind = op.get_bind()
    failure_mode.drop(bind, checkfirst=True)
    rate_limit_algorithm.drop(bind, checkfirst=True)
