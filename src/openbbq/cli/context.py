from __future__ import annotations

import argparse
from pathlib import Path

from openbbq.config.loader import load_project_config
from openbbq.domain.models import ProjectConfig
from openbbq.plugins.registry import PluginRegistry, discover_plugins
from openbbq.storage.project_store import ProjectStore


def load_config(args: argparse.Namespace):
    return load_project_config(
        Path(args.project),
        config_path=args.config,
        extra_plugin_paths=args.plugins,
    )


def load_registry(args: argparse.Namespace) -> PluginRegistry:
    config = load_config(args)
    return discover_plugins(config.plugin_paths)


def load_config_and_plugins(args: argparse.Namespace):
    config = load_config(args)
    return config, discover_plugins(config.plugin_paths)


def project_store(config: ProjectConfig) -> ProjectStore:
    return ProjectStore(
        config.storage.root,
        artifacts_root=config.storage.artifacts,
        state_root=config.storage.state,
    )
