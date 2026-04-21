from openbbq.cli import main


def test_version_json(capsys):
    code = main(["--json", "version"])
    assert code == 0
    assert capsys.readouterr().out.strip() == '{"ok": true, "version": "0.1.0"}'
