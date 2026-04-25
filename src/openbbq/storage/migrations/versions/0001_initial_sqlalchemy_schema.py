from __future__ import annotations

from alembic import context, op
import sqlalchemy as sa

revision = "0001_initial_sqlalchemy_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    if _includes("project"):
        _upgrade_project()
    if _includes("user"):
        _upgrade_user()


def downgrade() -> None:
    if _includes("user"):
        _downgrade_user()
    if _includes("project"):
        _downgrade_project()


def _includes(kind: str) -> bool:
    tag = context.get_tag_argument()
    return tag in (None, "all", kind)


def _upgrade_project() -> None:
    op.create_table(
        "runs",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("workflow_id", sa.Text(), nullable=False),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("project_root", sa.Text(), nullable=False),
        sa.Column("config_path", sa.Text()),
        sa.Column("plugin_paths_json", sa.Text(), nullable=False),
        sa.Column("started_at", sa.Text()),
        sa.Column("completed_at", sa.Text()),
        sa.Column("latest_event_sequence", sa.Integer(), nullable=False),
        sa.Column("error_json", sa.Text()),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("record_json", sa.Text(), nullable=False),
    )
    op.create_index("idx_runs_workflow_status", "runs", ["workflow_id", "status"])

    op.create_table(
        "workflow_states",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("name", sa.Text()),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("current_step_id", sa.Text()),
        sa.Column("config_hash", sa.Text()),
        sa.Column("step_run_ids_json", sa.Text(), nullable=False),
        sa.Column("record_json", sa.Text(), nullable=False),
    )

    op.create_table(
        "step_runs",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("workflow_id", sa.Text(), nullable=False),
        sa.Column("step_id", sa.Text()),
        sa.Column("attempt", sa.Integer()),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("input_artifact_version_ids_json", sa.Text(), nullable=False),
        sa.Column("output_bindings_json", sa.Text(), nullable=False),
        sa.Column("started_at", sa.Text()),
        sa.Column("completed_at", sa.Text()),
        sa.Column("error_json", sa.Text()),
        sa.Column("record_json", sa.Text(), nullable=False),
    )
    op.create_index("idx_step_runs_workflow", "step_runs", ["workflow_id"])

    op.create_table(
        "workflow_events",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("workflow_id", sa.Text(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("level", sa.Text(), nullable=False),
        sa.Column("message", sa.Text()),
        sa.Column("data_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("step_id", sa.Text()),
        sa.Column("attempt", sa.Integer()),
        sa.Column("record_json", sa.Text(), nullable=False),
        sa.UniqueConstraint(
            "workflow_id",
            "sequence",
            name="uq_workflow_events_workflow_sequence",
        ),
    )
    op.create_index(
        "idx_workflow_events_workflow_sequence",
        "workflow_events",
        ["workflow_id", "sequence"],
    )

    op.create_table(
        "artifacts",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("versions_json", sa.Text(), nullable=False),
        sa.Column("current_version_id", sa.Text()),
        sa.Column("created_by_step_id", sa.Text()),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("record_json", sa.Text(), nullable=False),
    )

    op.create_table(
        "artifact_versions",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("artifact_id", sa.Text(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("content_path", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("content_encoding", sa.Text(), nullable=False),
        sa.Column("content_size", sa.Integer(), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=False),
        sa.Column("lineage_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("record_json", sa.Text(), nullable=False),
    )
    op.create_index("idx_artifact_versions_artifact", "artifact_versions", ["artifact_id"])


def _upgrade_user() -> None:
    op.create_table(
        "providers",
        sa.Column("name", sa.Text(), primary_key=True),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("base_url", sa.Text()),
        sa.Column("api_key", sa.Text()),
        sa.Column("default_chat_model", sa.Text()),
        sa.Column("display_name", sa.Text()),
    )

    op.create_table(
        "credentials",
        sa.Column("reference", sa.Text(), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
    )


def _downgrade_project() -> None:
    op.drop_index("idx_artifact_versions_artifact", table_name="artifact_versions")
    op.drop_table("artifact_versions")
    op.drop_table("artifacts")
    op.drop_index("idx_workflow_events_workflow_sequence", table_name="workflow_events")
    op.drop_table("workflow_events")
    op.drop_index("idx_step_runs_workflow", table_name="step_runs")
    op.drop_table("step_runs")
    op.drop_table("workflow_states")
    op.drop_index("idx_runs_workflow_status", table_name="runs")
    op.drop_table("runs")


def _downgrade_user() -> None:
    op.drop_table("credentials")
    op.drop_table("providers")
