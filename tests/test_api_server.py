from pathlib import Path

from openbbq.api.server import ServerArgs, build_startup_payload, parse_args


def test_parse_args_accepts_sidecar_options():
    args = parse_args(
        [
            "--project",
            "/tmp/project",
            "--host",
            "127.0.0.1",
            "--port",
            "0",
            "--token",
            "secret",
        ]
    )

    assert args == ServerArgs(
        project=Path("/tmp/project"),
        config=None,
        plugins=(),
        host="127.0.0.1",
        port=0,
        token="secret",
    )


def test_build_startup_payload_is_machine_readable():
    payload = build_startup_payload(host="127.0.0.1", port=53124, pid=123)

    assert payload == {"ok": True, "host": "127.0.0.1", "port": 53124, "pid": 123}
