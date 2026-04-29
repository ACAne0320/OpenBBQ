"""Add enabled state to user providers."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy import inspect

revision = "0003_user_provider_enabled"
down_revision = "0002_user_quickstart_tasks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not _includes("user"):
        return
    columns = {column["name"] for column in inspect(op.get_bind()).get_columns("providers")}
    if "enabled" in columns:
        return
    op.add_column(
        "providers",
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    if not _includes("user"):
        return
    columns = {column["name"] for column in inspect(op.get_bind()).get_columns("providers")}
    if "enabled" not in columns:
        return
    op.drop_column("providers", "enabled")


def _includes(kind: str) -> bool:
    tag = context.get_tag_argument()
    return tag in (None, "all", kind)
