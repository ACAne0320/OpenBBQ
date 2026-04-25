from __future__ import annotations

import importlib
from pathlib import Path
import zipfile
import tomllib

import pytest


def test_cli_app_does_not_keep_obsolete_slice_guard() -> None:
    cli_app = importlib.import_module("openbbq.cli.app")

    assert not hasattr(cli_app, "_unsupported_slice_2")


def test_new_package_modules_are_importable() -> None:
    modules = [
        "openbbq.builtin_plugins.llm",
        "openbbq.builtin_plugins.segments",
        "openbbq.builtin_plugins.transcript.llm_json",
        "openbbq.builtin_plugins.translation.llm_json",
        "openbbq.cli.api",
        "openbbq.cli.app",
        "openbbq.cli.artifacts",
        "openbbq.cli.context",
        "openbbq.cli.output",
        "openbbq.cli.plugins",
        "openbbq.cli.projects",
        "openbbq.cli.quickstart",
        "openbbq.cli.runtime",
        "openbbq.cli.workflows",
        "openbbq.config.loader",
        "openbbq.config.paths",
        "openbbq.config.raw",
        "openbbq.config.workflows",
        "openbbq.domain.models",
        "openbbq.engine.service",
        "openbbq.engine.validation",
        "openbbq.plugins.discovery",
        "openbbq.plugins.execution",
        "openbbq.plugins.manifests",
        "openbbq.plugins.models",
        "openbbq.plugins.registry",
        "openbbq.runtime.settings_parser",
        "openbbq.storage.project_store",
        "openbbq.workflow.aborts",
        "openbbq.workflow.bindings",
        "openbbq.workflow.diff",
        "openbbq.workflow.execution",
        "openbbq.workflow.locks",
        "openbbq.workflow.rerun",
        "openbbq.workflow.state",
    ]

    for module in modules:
        importlib.import_module(module)


def test_obsolete_source_modules_are_removed() -> None:
    root = Path(__file__).resolve().parents[1]
    obsolete_paths = [
        "src/openbbq/cli.py",
        "src/openbbq/config.py",
        "src/openbbq/domain.py",
        "src/openbbq/engine.py",
        "src/openbbq/plugins.py",
        "src/openbbq/storage.py",
        "src/openbbq/storage/events.py",
        "src/openbbq/storage/workflows.py",
        "src/openbbq/core",
        "src/openbbq/models",
    ]

    remaining = [path for path in obsolete_paths if (root / path).exists()]

    assert remaining == []


def test_builtin_plugin_manifests_are_configured_as_package_data() -> None:
    root = Path(__file__).resolve().parents[1]
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    package_data = pyproject["tool"]["setuptools"]["package-data"]

    manifests = sorted((root / "src/openbbq/builtin_plugins").glob("*/openbbq.plugin.toml"))

    assert {manifest.parent.name for manifest in manifests} == {
        "faster_whisper",
        "ffmpeg",
        "glossary",
        "remote_video",
        "subtitle",
        "translation",
        "transcript",
    }
    assert package_data["openbbq.builtin_plugins"] == ["*/openbbq.plugin.toml"]


def test_workflow_templates_are_configured_as_package_data() -> None:
    root = Path(__file__).resolve().parents[1]
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    package_data = pyproject["tool"]["setuptools"]["package-data"]

    assert package_data["openbbq.workflow_templates.youtube_subtitle"] == ["openbbq.yaml"]
    assert package_data["openbbq.workflow_templates.local_subtitle"] == ["openbbq.yaml"]


def test_llm_extra_declares_openai_sdk_dependency() -> None:
    root = Path(__file__).resolve().parents[1]
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))

    assert pyproject["project"]["optional-dependencies"]["llm"] == ["openai>=1.0"]


def test_download_extra_declares_yt_dlp_dependency() -> None:
    root = Path(__file__).resolve().parents[1]
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))

    assert pyproject["project"]["optional-dependencies"]["download"] == ["yt-dlp>=2024.12.0"]


def test_secrets_extra_declares_keyring_dependency() -> None:
    root = Path(__file__).resolve().parents[1]
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))

    assert pyproject["project"]["optional-dependencies"]["secrets"] == ["keyring>=25"]


def test_core_storage_declares_sqlalchemy_and_alembic_dependencies() -> None:
    root = Path(__file__).resolve().parents[1]
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))

    dependencies = pyproject["project"]["dependencies"]

    assert any(dependency.startswith("SQLAlchemy>=") for dependency in dependencies)
    assert any(dependency.startswith("alembic>=") for dependency in dependencies)


def test_database_model_modules_are_importable() -> None:
    modules = [
        "openbbq.storage.artifact_content",
        "openbbq.storage.artifact_repository",
        "openbbq.storage.database",
        "openbbq.storage.database_records",
        "openbbq.storage.event_repository",
        "openbbq.storage.migration_runner",
        "openbbq.storage.orm",
        "openbbq.storage.workflow_repository",
        "openbbq.runtime.user_db",
    ]

    for module in modules:
        importlib.import_module(module)


def test_alembic_revision_is_packaged_with_storage_models() -> None:
    root = Path(__file__).resolve().parents[1]
    revisions = sorted(
        path
        for path in (root / "src/openbbq/storage/migrations/versions").glob("*.py")
        if path.name != "__init__.py"
    )

    assert [revision.name for revision in revisions] == ["0001_initial_sqlalchemy_schema.py"]


def test_alembic_initial_revision_applies_to_sqlite_database(tmp_path) -> None:
    import sqlite3

    from alembic import command
    from alembic.config import Config

    root = Path(__file__).resolve().parents[1]
    config = Config(root / "alembic.ini")
    config.set_main_option(
        "script_location",
        str(root / "src/openbbq/storage/migrations"),
    )
    config.set_main_option(
        "sqlalchemy.url",
        f"sqlite:///{(tmp_path / 'openbbq.db').as_posix()}",
    )

    command.upgrade(config, "head")

    with sqlite3.connect(tmp_path / "openbbq.db") as connection:
        table_names = {
            row[0]
            for row in connection.execute("select name from sqlite_master where type = 'table'")
        }
    assert {
        "alembic_version",
        "runs",
        "workflow_states",
        "step_runs",
        "workflow_events",
        "artifacts",
        "artifact_versions",
        "providers",
        "credentials",
    } <= table_names


def test_source_does_not_use_raw_sqlite3_access() -> None:
    root = Path(__file__).resolve().parents[1]
    offenders: list[str] = []
    for path in sorted((root / "src/openbbq").rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        if "sqlite3" in text:
            offenders.append(str(path.relative_to(root)))

    assert offenders == []


def test_builtin_plugin_manifests_are_included_in_wheel(tmp_path) -> None:
    import subprocess
    import sys

    root = Path(__file__).resolve().parents[1]

    # Build wheel using subprocess to avoid import conflicts in CI
    result = subprocess.run(
        [sys.executable, "-m", "pip", "wheel", str(root), "--no-deps", "-w", str(tmp_path)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.skip(f"Wheel build not available in environment: {result.stderr}")

    wheels = list(tmp_path.glob("*.whl"))
    if not wheels:
        pytest.skip("No wheel produced")
    wheel_path = wheels[0]

    expected = {
        f"openbbq/builtin_plugins/{manifest.parent.name}/openbbq.plugin.toml"
        for manifest in (root / "src/openbbq/builtin_plugins").glob("*/openbbq.plugin.toml")
    }
    with zipfile.ZipFile(wheel_path) as wheel:
        names = set(wheel.namelist())

    assert expected <= names


def test_workflow_templates_are_included_in_wheel(tmp_path) -> None:
    import subprocess
    import sys

    root = Path(__file__).resolve().parents[1]

    result = subprocess.run(
        [sys.executable, "-m", "pip", "wheel", str(root), "--no-deps", "-w", str(tmp_path)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.skip(f"Wheel build not available in environment: {result.stderr}")

    wheels = list(tmp_path.glob("*.whl"))
    if not wheels:
        pytest.skip("No wheel produced")
    wheel_path = wheels[0]

    with zipfile.ZipFile(wheel_path) as wheel:
        names = set(wheel.namelist())

    assert "openbbq/workflow_templates/youtube_subtitle/openbbq.yaml" in names
    assert "openbbq/workflow_templates/local_subtitle/openbbq.yaml" in names
