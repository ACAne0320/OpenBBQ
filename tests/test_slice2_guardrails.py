import json

from openbbq.cli import main


def test_resume_is_clear_slice_2_error(capsys):
    code = main(["resume", "demo"])

    assert code == 1
    assert "not implemented in Slice 1" in capsys.readouterr().err


def test_artifact_diff_is_clear_slice_2_error(capsys):
    code = main(["artifact", "diff", "a", "b"])

    assert code == 1
    assert "not implemented in Slice 1" in capsys.readouterr().err


def test_run_force_is_clear_slice_2_json_error(capsys):
    code = main(["--json", "run", "demo", "--force"])

    assert code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "slice_1_unsupported"


def test_run_step_is_clear_slice_2_error(capsys):
    code = main(["run", "demo", "--step", "seed"])

    assert code == 1
    assert "not implemented in Slice 1" in capsys.readouterr().err
