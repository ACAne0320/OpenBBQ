from __future__ import annotations

import argparse


def register(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    parents: list[argparse.ArgumentParser],
) -> None:
    api = subparsers.add_parser("api", parents=parents)
    api_sub = api.add_subparsers(dest="api_command", required=True)
    api_serve = api_sub.add_parser("serve", parents=parents)
    api_serve.add_argument("--host", default="127.0.0.1")
    api_serve.add_argument("--port", type=int, default=0)
    api_serve.add_argument("--token")
    api_serve.add_argument("--allow-dev-cors", action="store_true")
    api_serve.add_argument("--no-token-dev", action="store_true")


def dispatch(args: argparse.Namespace) -> int | None:
    if args.command == "api":
        if args.api_command == "serve":
            from openbbq.api.server import main as api_server_main

            argv = [
                "--project",
                str(args.project),
                "--host",
                args.host,
                "--port",
                str(args.port),
            ]
            if args.config:
                argv.extend(["--config", str(args.config)])
            for plugin_path in args.plugins:
                argv.extend(["--plugins", str(plugin_path)])
            if args.token:
                argv.extend(["--token", args.token])
            if args.allow_dev_cors:
                argv.append("--allow-dev-cors")
            if args.no_token_dev:
                argv.append("--no-token-dev")
            return api_server_main(argv)
    return None
