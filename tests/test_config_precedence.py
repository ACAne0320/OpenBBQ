import json
import logging
from pathlib import Path

from openbbq.cli.app import _build_parser, main
from openbbq.config.loader import load_project_config


def write_config(path: Path, name: str, plugin_path: str = "./plugins-a") -> None:
    path.write_text(
        f"""
version: 1
project:
  name: {name}
plugins:
  paths:
    - {plugin_path}
workflows:
  demo:
    name: Demo
    steps:
      - id: seed
        name: Seed
        tool_ref: mock_text.echo
        inputs:
          text: hello
        outputs:
          - name: text
            type: text
""",
        encoding="utf-8",
    )


def test_plugin_paths_use_cli_then_env_then_project_config(tmp_path):
    write_config(tmp_path / "openbbq.yaml", "Config")

    config = load_project_config(
        tmp_path,
        extra_plugin_paths=["./plugins-c"],
        env={"OPENBBQ_PLUGIN_PATH": "./plugins-b"},
    )

    assert [path.name for path in config.plugin_paths] == [
        "plugins-c",
        "plugins-b",
        "plugins-a",
        "builtin_plugins",
    ]


def test_cli_project_root_defaults_to_openbbq_project(tmp_path, monkeypatch, capsys):
    write_config(tmp_path / "openbbq.yaml", "From Env Project")
    monkeypatch.setenv("OPENBBQ_PROJECT", str(tmp_path))

    code = main(["--json", "project", "info"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["project"]["name"] == "From Env Project"


def test_cli_config_defaults_to_openbbq_config_and_cli_flag_overrides(
    tmp_path, monkeypatch, capsys
):
    write_config(tmp_path / "openbbq.yaml", "Default")
    write_config(tmp_path / "env.yaml", "From Env Config")
    write_config(tmp_path / "cli.yaml", "From CLI Config")
    monkeypatch.setenv("OPENBBQ_PROJECT", str(tmp_path))
    monkeypatch.setenv("OPENBBQ_CONFIG", "env.yaml")

    assert main(["--json", "project", "info"]) == 0
    env_payload = json.loads(capsys.readouterr().out)
    assert env_payload["project"]["name"] == "From Env Config"

    assert main(["--config", "cli.yaml", "--json", "project", "info"]) == 0
    cli_payload = json.loads(capsys.readouterr().out)
    assert cli_payload["project"]["name"] == "From CLI Config"


def test_openbbq_log_level_env_combines_with_verbose(monkeypatch):
    from openbbq.cli.app import _effective_log_level

    monkeypatch.setenv("OPENBBQ_LOG_LEVEL", "debug")

    args = _build_parser().parse_args(["--verbose", "version"])

    assert args.verbose is True
    assert _effective_log_level(args) == logging.DEBUG
