from __future__ import annotations

import os
import subprocess
import sys

from openbbq.core.processes import pid_alive


def test_pid_alive_reports_running_and_exited_processes() -> None:
    assert pid_alive(os.getpid()) is True

    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()
    assert pid_alive(child.pid) is False


def test_pid_alive_rejects_a_pid_that_never_existed() -> None:
    assert pid_alive(99999999) is False
