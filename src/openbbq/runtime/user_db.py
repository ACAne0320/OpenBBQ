from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
import os

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from openbbq.runtime.models import ProviderProfile
from openbbq.storage.database_records import (
    dump_json,
    dump_nullable_json,
    model_from_optional_row,
    model_from_row,
    record_payload,
    upsert_row,
)
from openbbq.storage.database import create_sqlite_engine
from openbbq.storage.migration_runner import run_schema_migrations
from openbbq.storage.models import QuickstartTaskRecord
from openbbq.storage.orm import QuickstartTaskRow, UserCredentialRow, UserProviderRow


DEFAULT_USER_DB_PATH = Path("~/.openbbq/openbbq.db")


def default_user_db_path(env: Mapping[str, str] | None = None) -> Path:
    env = os.environ if env is None else env
    configured = env.get("OPENBBQ_USER_DB")
    if configured:
        return Path(configured).expanduser().resolve()
    user_config = env.get("OPENBBQ_USER_CONFIG")
    if user_config:
        return (Path(user_config).expanduser().resolve().parent / "openbbq.db").resolve()
    return DEFAULT_USER_DB_PATH.expanduser().resolve()


class UserRuntimeDatabase:
    def __init__(self, path: Path | None = None, *, env: Mapping[str, str] | None = None) -> None:
        self.path = path or default_user_db_path(env)
        self.engine = create_sqlite_engine(self.path)
        self.session_factory = sessionmaker(self.engine, expire_on_commit=False, future=True)
        self.initialize()

    def initialize(self) -> None:
        run_schema_migrations(self.path, "user")

    def upsert_provider(self, provider: ProviderProfile) -> ProviderProfile:
        with self.session_factory.begin() as session:
            row = session.get(UserProviderRow, provider.name)
            if row is None:
                row = UserProviderRow(name=provider.name)
                session.add(row)
            row.type = provider.type
            row.base_url = provider.base_url
            row.api_key = provider.api_key
            row.default_chat_model = provider.default_chat_model
            row.display_name = provider.display_name
            row.enabled = provider.enabled
        return provider

    def list_providers(self) -> tuple[ProviderProfile, ...]:
        with self.session_factory.begin() as session:
            rows = session.scalars(select(UserProviderRow).order_by(UserProviderRow.name)).all()
            return tuple(
                ProviderProfile(
                    name=row.name,
                    type=row.type,
                    base_url=row.base_url,
                    api_key=row.api_key,
                    default_chat_model=row.default_chat_model,
                    display_name=row.display_name,
                    enabled=row.enabled,
                )
                for row in rows
            )

    def set_credential(self, reference: str, value: str) -> None:
        timestamp = datetime.now(UTC).isoformat()
        with self.session_factory.begin() as session:
            row = session.get(UserCredentialRow, reference)
            if row is None:
                row = UserCredentialRow(reference=reference)
                session.add(row)
            row.value = value
            row.updated_at = timestamp

    def get_credential(self, reference: str) -> str | None:
        with self.session_factory.begin() as session:
            row = session.get(UserCredentialRow, reference)
            return row.value if row is not None else None

    def upsert_quickstart_task(self, task: QuickstartTaskRecord) -> QuickstartTaskRecord:
        payload = record_payload(task)
        with self.session_factory.begin() as session:
            row = upsert_row(session, QuickstartTaskRow, task.id)
            row.run_id = task.run_id
            row.workflow_id = task.workflow_id
            row.workspace_root = str(task.workspace_root)
            row.generated_project_root = str(task.generated_project_root)
            row.generated_config_path = str(task.generated_config_path)
            row.plugin_paths_json = dump_json(payload["plugin_paths"])
            row.source_kind = task.source_kind
            row.source_uri = task.source_uri
            row.source_summary = task.source_summary
            row.source_lang = task.source_lang
            row.target_lang = task.target_lang
            row.provider = task.provider
            row.model = task.model
            row.asr_model = task.asr_model
            row.asr_device = task.asr_device
            row.asr_compute_type = task.asr_compute_type
            row.quality = task.quality
            row.auth = task.auth
            row.browser = task.browser
            row.browser_profile = task.browser_profile
            row.output_path = str(task.output_path) if task.output_path is not None else None
            row.source_artifact_id = task.source_artifact_id
            row.cache_key = task.cache_key
            row.status = task.status
            row.created_at = task.created_at
            row.updated_at = task.updated_at
            row.completed_at = task.completed_at
            row.error_json = dump_nullable_json(payload.get("error"))
            row.record_json = dump_json(payload)
        return task

    def read_quickstart_task(self, run_id: str) -> QuickstartTaskRecord | None:
        with self.session_factory.begin() as session:
            row = session.scalar(
                select(QuickstartTaskRow).where(QuickstartTaskRow.run_id == run_id)
            )
            return model_from_optional_row(QuickstartTaskRecord, row)

    def list_quickstart_tasks(self) -> tuple[QuickstartTaskRecord, ...]:
        with self.session_factory.begin() as session:
            rows = session.scalars(
                select(QuickstartTaskRow).order_by(
                    QuickstartTaskRow.updated_at.desc(), QuickstartTaskRow.id.desc()
                )
            ).all()
            return tuple(model_from_row(QuickstartTaskRecord, row) for row in rows)

    def find_quickstart_tasks_by_cache_key(
        self, cache_key: str
    ) -> tuple[QuickstartTaskRecord, ...]:
        with self.session_factory.begin() as session:
            rows = session.scalars(
                select(QuickstartTaskRow)
                .where(QuickstartTaskRow.cache_key == cache_key)
                .order_by(QuickstartTaskRow.updated_at.desc(), QuickstartTaskRow.id.desc())
            ).all()
            return tuple(model_from_row(QuickstartTaskRecord, row) for row in rows)
