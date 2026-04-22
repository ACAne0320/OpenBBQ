import os
import subprocess
import sys
from pathlib import Path

from openbbq.cli.app import main


def test_version_json(capsys):
    code = main(["--json", "version"])
    assert code == 0
    assert capsys.readouterr().out.strip() == '{"ok": true, "version": "0.1.0"}'


def test_installed_console_script():
    script = Path(sys.executable).with_name("openbbq")
    if os.name == "nt":
        script = script.with_suffix(".exe")

    result = subprocess.run(
        [str(script), "--json", "version"],
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout.strip() == '{"ok": true, "version": "0.1.0"}'
