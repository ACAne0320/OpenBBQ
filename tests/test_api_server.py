from pathlib import Path

import pytest

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
        project=Path("/tmp/project").expanduser().resolve(),
        config=None,
        plugins=(),
        host="127.0.0.1",
        port=0,
        token="secret",
        allow_dev_cors=False,
        allow_no_token_dev=False,
    )


def test_parse_args_rejects_missing_token_without_dev_override():
    with pytest.raises(SystemExit):
        parse_args([])


def test_parse_args_allows_explicit_no_token_dev_mode():
    args = parse_args(["--no-token-dev"])

    assert args.token is None
    assert args.allow_no_token_dev is True


def test_build_startup_payload_is_machine_readable():
    payload = build_startup_payload(host="127.0.0.1", port=53124, pid=123)

    assert payload == {"ok": True, "host": "127.0.0.1", "port": 53124, "pid": 123}
