from __future__ import annotations

import argparse
from pathlib import Path

from openbbq.application.plugins import plugin_info as plugin_info_command
from openbbq.application.plugins import plugin_list as plugin_list_command
from openbbq.cli.output import emit as _emit


def register(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    parents: list[argparse.ArgumentParser],
) -> None:
    plugin = subparsers.add_parser("plugin", parents=parents)
    plugin_sub = plugin.add_subparsers(dest="plugin_command", required=True)
    plugin_sub.add_parser("list", parents=parents)
    plugin_info = plugin_sub.add_parser("info", parents=parents)
    plugin_info.add_argument("name")


def dispatch(args: argparse.Namespace) -> int | None:
    if args.command == "plugin":
        if args.plugin_command == "list":
            return _plugin_list(args)
        if args.plugin_command == "info":
            return _plugin_info(args)
    return None


def _plugin_list(args: argparse.Namespace) -> int:
    result = plugin_list_command(
        project_root=Path(args.project),
        config_path=Path(args.config) if args.config else None,
        plugin_paths=tuple(Path(path) for path in args.plugins),
    )
    payload = {
        "ok": True,
        "plugins": list(result.plugins),
        "invalid_plugins": list(result.invalid_plugins),
        "warnings": list(result.warnings),
    }
    _emit(payload, args.json_output, "\n".join(plugin["name"] for plugin in result.plugins))
    return 0


def _plugin_info(args: argparse.Namespace) -> int:
    result = plugin_info_command(
        project_root=Path(args.project),
        config_path=Path(args.config) if args.config else None,
        plugin_paths=tuple(Path(path) for path in args.plugins),
        plugin_name=args.name,
    )
    payload = {"ok": True, "plugin": result.plugin}
    _emit(payload, args.json_output, result.plugin["name"])
    return 0
