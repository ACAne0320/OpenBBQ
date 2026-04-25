from __future__ import annotations

import argparse
import logging
import os

from openbbq import __version__
from openbbq.cli import api, artifacts, plugins, projects, quickstart, runtime, workflows
from openbbq.cli.output import (
    emit as _emit,
    emit_error as _emit_error,
)
from openbbq.errors import OpenBBQError


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code)

    try:
        return _dispatch(args)
    except OpenBBQError as exc:
        _emit_error(exc, json_output=getattr(args, "json_output", False))
        return exc.exit_code


def _build_parser() -> argparse.ArgumentParser:
    global_options = _global_options(defaults=True)
    subcommand_global_options = _global_options(defaults=False)

    parser = argparse.ArgumentParser(prog="openbbq", parents=[global_options])
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("version", parents=[subcommand_global_options])
    projects.register(subparsers, [subcommand_global_options])
    workflows.register(subparsers, [subcommand_global_options])
    artifacts.register(subparsers, [subcommand_global_options])
    plugins.register(subparsers, [subcommand_global_options])

    runtime.register(subparsers, [subcommand_global_options])
    api.register(subparsers, [subcommand_global_options])
    quickstart.register(subparsers, [subcommand_global_options])

    return parser


def _global_options(*, defaults: bool) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    if defaults:
        parser.add_argument("--project", default=os.environ.get("OPENBBQ_PROJECT", "."))
        parser.add_argument("--config", default=os.environ.get("OPENBBQ_CONFIG"))
        parser.add_argument("--plugins", action="append", default=[])
        parser.add_argument("--json", action="store_true", dest="json_output")
        parser.add_argument("--verbose", action="store_true")
        parser.add_argument("--debug", action="store_true")
    else:
        parser.add_argument("--project", default=argparse.SUPPRESS)
        parser.add_argument("--config", default=argparse.SUPPRESS)
        parser.add_argument("--plugins", action="append", default=argparse.SUPPRESS)
        parser.add_argument(
            "--json", action="store_true", dest="json_output", default=argparse.SUPPRESS
        )
        parser.add_argument("--verbose", action="store_true", default=argparse.SUPPRESS)
        parser.add_argument("--debug", action="store_true", default=argparse.SUPPRESS)
    return parser


def _configure_logging(args: argparse.Namespace) -> None:
    logging.getLogger("openbbq").setLevel(_effective_log_level(args))


def _effective_log_level(args: argparse.Namespace) -> int:
    if getattr(args, "debug", False):
        return logging.DEBUG
    env_level = os.environ.get("OPENBBQ_LOG_LEVEL")
    if env_level:
        return getattr(logging, env_level.upper(), logging.WARNING)
    if getattr(args, "verbose", False):
        return logging.INFO
    return logging.WARNING


def _dispatch(args: argparse.Namespace) -> int:
    _configure_logging(args)
    if args.command == "version":
        _emit({"ok": True, "version": __version__}, args.json_output, __version__)
        return 0
    for module in (projects, plugins, api, workflows, artifacts, runtime, quickstart):
        result = module.dispatch(args)
        if result is not None:
            return result
    return 2
