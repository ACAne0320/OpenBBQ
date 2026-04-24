from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket

import uvicorn

from openbbq.api.app import ApiAppSettings, create_app
from openbbq.domain.base import OpenBBQModel


class ServerArgs(OpenBBQModel):
    project: Path | None = None
    config: Path | None = None
    plugins: tuple[Path, ...] = ()
    host: str = "127.0.0.1"
    port: int = 0
    token: str | None = None


def parse_args(argv: list[str] | None = None) -> ServerArgs:
    parser = argparse.ArgumentParser(prog="openbbq-api")
    parser.add_argument("--project")
    parser.add_argument("--config")
    parser.add_argument("--plugins", action="append", default=[])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--token")
    parsed = parser.parse_args(argv)
    return ServerArgs(
        project=Path(parsed.project).expanduser().resolve() if parsed.project else None,
        config=Path(parsed.config).expanduser().resolve() if parsed.config else None,
        plugins=tuple(Path(path).expanduser().resolve() for path in parsed.plugins),
        host=parsed.host,
        port=parsed.port,
        token=parsed.token,
    )


def build_startup_payload(*, host: str, port: int, pid: int) -> dict[str, object]:
    return {"ok": True, "host": host, "port": port, "pid": pid}


def bind_socket(host: str, port: int) -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((host, port))
    sock.listen(2048)
    return sock


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    app = create_app(
        ApiAppSettings(
            project_root=args.project,
            config_path=args.config,
            plugin_paths=args.plugins,
            token=args.token,
        )
    )
    sock = bind_socket(args.host, args.port)
    selected_port = sock.getsockname()[1]
    config = uvicorn.Config(app, host=args.host, port=selected_port, log_level="info")
    server = uvicorn.Server(config)
    print(
        json.dumps(
            build_startup_payload(host=args.host, port=selected_port, pid=os.getpid()),
            ensure_ascii=False,
        ),
        flush=True,
    )
    server.run(sockets=[sock])
    return 0
