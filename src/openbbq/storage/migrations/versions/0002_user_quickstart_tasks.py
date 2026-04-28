from __future__ import annotations

from alembic import context, op
import sqlalchemy as sa

revision = "0002_user_quickstart_tasks"
down_revision = "0001_initial_sqlalchemy_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not _includes("user"):
        return
    op.create_table(
        "quickstart_tasks",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("workflow_id", sa.Text(), nullable=False),
        sa.Column("workspace_root", sa.Text(), nullable=False),
        sa.Column("generated_project_root", sa.Text(), nullable=False),
        sa.Column("generated_config_path", sa.Text(), nullable=False),
        sa.Column("plugin_paths_json", sa.Text(), nullable=False),
        sa.Column("source_kind", sa.Text(), nullable=False),
        sa.Column("source_uri", sa.Text(), nullable=False),
        sa.Column("source_summary", sa.Text()),
        sa.Column("source_lang", sa.Text(), nullable=False),
        sa.Column("target_lang", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("model", sa.Text()),
        sa.Column("asr_model", sa.Text()),
        sa.Column("asr_device", sa.Text()),
        sa.Column("asr_compute_type", sa.Text()),
        sa.Column("quality", sa.Text()),
        sa.Column("auth", sa.Text()),
        sa.Column("browser", sa.Text()),
        sa.Column("browser_profile", sa.Text()),
        sa.Column("output_path", sa.Text()),
        sa.Column("source_artifact_id", sa.Text()),
        sa.Column("cache_key", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("completed_at", sa.Text()),
        sa.Column("error_json", sa.Text()),
        sa.Column("record_json", sa.Text(), nullable=False),
        sa.UniqueConstraint("run_id", name="uq_quickstart_tasks_run_id"),
    )
    op.create_index("idx_quickstart_tasks_cache_key", "quickstart_tasks", ["cache_key"])
    op.create_index("idx_quickstart_tasks_updated_at", "quickstart_tasks", ["updated_at"])


def downgrade() -> None:
    if not _includes("user"):
        return
    op.drop_index("idx_quickstart_tasks_updated_at", table_name="quickstart_tasks")
    op.drop_index("idx_quickstart_tasks_cache_key", table_name="quickstart_tasks")
    op.drop_table("quickstart_tasks")


def _includes(kind: str) -> bool:
    tag = context.get_tag_argument()
    return tag in (None, "all", kind)
