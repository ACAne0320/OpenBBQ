from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
import os

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from openbbq.runtime.models import ProviderProfile
from openbbq.storage.database import create_sqlite_engine
from openbbq.storage.migration_runner import run_schema_migrations
from openbbq.storage.orm import UserCredentialRow, UserProviderRow


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
