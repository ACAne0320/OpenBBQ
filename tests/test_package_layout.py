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
        "openbbq.cli.app",
        "openbbq.config.loader",
        "openbbq.domain.models",
        "openbbq.engine.service",
        "openbbq.engine.validation",
        "openbbq.plugins.registry",
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
        "llm",
        "remote_video",
        "subtitle",
        "transcript",
    }
    assert package_data["openbbq.builtin_plugins"] == ["*/openbbq.plugin.toml"]


def test_llm_extra_declares_openai_sdk_dependency() -> None:
    root = Path(__file__).resolve().parents[1]
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))

    assert pyproject["project"]["optional-dependencies"]["llm"] == ["openai>=1.0"]


def test_download_extra_declares_yt_dlp_dependency() -> None:
    root = Path(__file__).resolve().parents[1]
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))

    assert pyproject["project"]["optional-dependencies"]["download"] == ["yt-dlp>=2024.12.0"]


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
