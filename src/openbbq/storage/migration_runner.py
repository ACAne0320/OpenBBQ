from __future__ import annotations

from importlib.resources import files
from pathlib import Path
import threading
from typing import Literal

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

DatabaseKind = Literal["project", "user"]

PROJECT_TABLES = frozenset(
    {
        "runs",
        "workflow_states",
        "step_runs",
        "workflow_events",
        "artifacts",
        "artifact_versions",
    }
)
PROJECT_BASELINE_TABLES = PROJECT_TABLES
USER_BASELINE_TABLES = frozenset({"providers", "credentials"})

_MIGRATION_LOCK = threading.Lock()


def run_schema_migrations(path: Path, kind: DatabaseKind) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _MIGRATION_LOCK:
        config = _alembic_config(path)
        existing_tables = _table_names(path)
        baseline_tables = PROJECT_BASELINE_TABLES if kind == "project" else USER_BASELINE_TABLES
        if "alembic_version" not in existing_tables and baseline_tables <= existing_tables:
            command.stamp(config, "0001_initial_sqlalchemy_schema", tag=kind)
        command.upgrade(config, "head", tag=kind)


def sqlite_database_url(path: Path) -> str:
    return f"sqlite:///{Path(path).resolve().as_posix()}"


def _alembic_config(path: Path) -> Config:
    config = Config()
    config.set_main_option("script_location", str(files("openbbq.storage.migrations")))
    config.set_main_option("sqlalchemy.url", sqlite_database_url(path))
    return config


def _table_names(path: Path) -> set[str]:
    engine = create_engine(sqlite_database_url(path), future=True)
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
