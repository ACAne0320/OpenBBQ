from __future__ import annotations

import importlib
from pathlib import Path
import tomllib


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

    manifest_packages = {
        f"openbbq.builtin_plugins.{manifest.parent.name}"
        for manifest in (root / "src/openbbq/builtin_plugins").glob("*/openbbq.plugin.toml")
    }

    assert manifest_packages == {
        "openbbq.builtin_plugins.faster_whisper",
        "openbbq.builtin_plugins.ffmpeg",
        "openbbq.builtin_plugins.subtitle",
    }
    for package_name in manifest_packages:
        assert "openbbq.plugin.toml" in package_data[package_name]
