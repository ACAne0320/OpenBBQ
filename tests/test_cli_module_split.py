import importlib
from argparse import Namespace

from openbbq.cli.app import _build_parser


CLI_MODULES = (
    "openbbq.cli.output",
    "openbbq.cli.context",
    "openbbq.cli.projects",
    "openbbq.cli.plugins",
    "openbbq.cli.api",
    "openbbq.cli.workflows",
    "openbbq.cli.artifacts",
    "openbbq.cli.runtime",
    "openbbq.cli.quickstart",
)


def test_cli_split_modules_are_importable():
    for module_name in CLI_MODULES:
        importlib.import_module(module_name)


def test_parser_accepts_representative_command_groups():
    parser = _build_parser()

    cases = [
        (["version"], ("version", None)),
        (["init"], ("init", None)),
        (["project", "info"], ("project", "info")),
        (["validate", "text-demo"], ("validate", None)),
        (["run", "text-demo", "--force"], ("run", None)),
        (["resume", "text-demo"], ("resume", None)),
        (["abort", "text-demo"], ("abort", None)),
        (["unlock", "text-demo", "--yes"], ("unlock", None)),
        (["status", "text-demo"], ("status", None)),
        (["logs", "text-demo"], ("logs", None)),
        (["artifact", "list"], ("artifact", "list")),
        (
            ["artifact", "import", "sample.mp4", "--type", "video", "--name", "source.video"],
            ("artifact", "import"),
        ),
        (["plugin", "info", "mock_text"], ("plugin", "info")),
        (["settings", "show"], ("settings", "show")),
        (["auth", "check", "openai"], ("auth", "check")),
        (["secret", "check", "env:OPENBBQ_LLM_API_KEY"], ("secret", "check")),
        (["models", "list"], ("models", "list")),
        (["doctor", "--workflow", "text-demo"], ("doctor", None)),
        (["api", "serve", "--host", "127.0.0.1", "--port", "0"], ("api", "serve")),
        (
            [
                "subtitle",
                "local",
                "--input",
                "sample.mp4",
                "--source",
                "en",
                "--target",
                "zh",
                "--output",
                "subtitle.srt",
            ],
            ("subtitle", "local"),
        ),
        (
            [
                "subtitle",
                "youtube",
                "--url",
                "https://www.youtube.com/watch?v=test",
                "--source",
                "en",
                "--target",
                "zh",
                "--output",
                "subtitle.srt",
            ],
            ("subtitle", "youtube"),
        ),
    ]

    for argv, expected in cases:
        args = parser.parse_args(argv)
        assert (args.command, _subcommand(args)) == expected


def test_dispatch_delegates_project_plugin_api_workflow_artifact_and_runtime_modules(monkeypatch):
    app = importlib.import_module("openbbq.cli.app")
    calls = []

    def project_dispatch(args):
        calls.append(("projects", args.command))
        return 7 if args.command == "init" else None

    def plugin_dispatch(args):
        calls.append(("plugins", args.command))
        return 8 if args.command == "plugin" else None

    def api_dispatch(args):
        calls.append(("api", args.command))
        return 9 if args.command == "api" else None

    def workflow_dispatch(args):
        calls.append(("workflows", args.command))
        return 10 if args.command == "validate" else None

    def artifact_dispatch(args):
        calls.append(("artifacts", args.command))
        return 11 if args.command == "artifact" else None

    def runtime_dispatch(args):
        calls.append(("runtime", args.command))
        return 12 if args.command == "settings" else None

    def quickstart_dispatch(args):
        calls.append(("quickstart", args.command))
        return 13 if args.command == "subtitle" else None

    monkeypatch.setattr(app.projects, "dispatch", project_dispatch)
    monkeypatch.setattr(app.plugins, "dispatch", plugin_dispatch)
    monkeypatch.setattr(app.api, "dispatch", api_dispatch)
    monkeypatch.setattr(app.workflows, "dispatch", workflow_dispatch)
    monkeypatch.setattr(app.artifacts, "dispatch", artifact_dispatch)
    monkeypatch.setattr(app.runtime, "dispatch", runtime_dispatch)
    monkeypatch.setattr(app.quickstart, "dispatch", quickstart_dispatch)

    common = {
        "json_output": False,
        "debug": False,
        "verbose": False,
    }

    assert app._dispatch(Namespace(command="init", **common)) == 7
    assert calls == [("projects", "init")]

    calls.clear()
    assert app._dispatch(Namespace(command="plugin", plugin_command="list", **common)) == 8
    assert calls == [
        ("projects", "plugin"),
        ("workflows", "plugin"),
        ("artifacts", "plugin"),
        ("plugins", "plugin"),
    ]

    calls.clear()
    assert app._dispatch(Namespace(command="api", api_command="serve", **common)) == 9
    assert calls == [
        ("projects", "api"),
        ("workflows", "api"),
        ("artifacts", "api"),
        ("plugins", "api"),
        ("runtime", "api"),
        ("api", "api"),
    ]

    calls.clear()
    assert app._dispatch(Namespace(command="validate", workflow="text-demo", **common)) == 10
    assert calls == [
        ("projects", "validate"),
        ("workflows", "validate"),
    ]

    calls.clear()
    assert app._dispatch(Namespace(command="artifact", artifact_command="list", **common)) == 11
    assert calls == [
        ("projects", "artifact"),
        ("workflows", "artifact"),
        ("artifacts", "artifact"),
    ]

    calls.clear()
    assert app._dispatch(Namespace(command="settings", settings_command="show", **common)) == 12
    assert calls == [
        ("projects", "settings"),
        ("workflows", "settings"),
        ("artifacts", "settings"),
        ("plugins", "settings"),
        ("runtime", "settings"),
    ]

    calls.clear()
    assert app._dispatch(Namespace(command="subtitle", subtitle_command="local", **common)) == 13
    assert calls == [
        ("projects", "subtitle"),
        ("workflows", "subtitle"),
        ("artifacts", "subtitle"),
        ("plugins", "subtitle"),
        ("runtime", "subtitle"),
        ("api", "subtitle"),
        ("quickstart", "subtitle"),
    ]


def test_app_no_longer_defines_split_command_handlers():
    app = importlib.import_module("openbbq.cli.app")

    for handler_name in (
        "_init_project",
        "_project_list",
        "_project_info",
        "_plugin_list",
        "_plugin_info",
        "_validate",
        "_run",
        "_resume",
        "_abort",
        "_unlock",
        "_status",
        "_logs",
        "_format_event",
        "_artifact_list",
        "_artifact_diff",
        "_artifact_import",
        "_artifact_show",
        "_settings_show",
        "_settings_set_provider",
        "_auth_set",
        "_auth_check",
        "_secret_check",
        "_secret_set",
        "_models_list",
        "_doctor",
        "_secret_payload",
        "_subtitle_local",
        "_subtitle_youtube",
        "_latest_workflow_artifact_content",
    ):
        assert not hasattr(app, handler_name)


def _subcommand(args):
    for name in (
        "project_command",
        "artifact_command",
        "plugin_command",
        "settings_command",
        "auth_command",
        "secret_command",
        "models_command",
        "api_command",
        "subtitle_command",
    ):
        if hasattr(args, name):
            return getattr(args, name)
    return None
