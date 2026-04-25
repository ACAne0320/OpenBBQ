import importlib

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
