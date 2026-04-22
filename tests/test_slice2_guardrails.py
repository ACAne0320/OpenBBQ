from openbbq.cli import main


def test_artifact_diff_is_clear_slice_2_error(capsys):
    code = main(["artifact", "diff", "a", "b"])

    assert code == 1
    assert "not implemented in Slice 2" in capsys.readouterr().err


def test_run_step_is_clear_slice_2_error(capsys):
    code = main(["run", "demo", "--step", "seed"])

    assert code == 1
    assert "not implemented in Slice 2" in capsys.readouterr().err
