from __future__ import annotations

import importlib
from pathlib import Path


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
