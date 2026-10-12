from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import cast

import pytest

from openbbq.core.auth import browser
from openbbq.errors import OpenBBQError


def _install(root: Path, *parts: str) -> Path:
    exe = root.joinpath(*parts)
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"")
    return exe


@pytest.fixture
def windows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    program_files = tmp_path / "Program Files"
    local = tmp_path / "AppData" / "Local"
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(browser.shutil, "which", lambda _name: None)
    monkeypatch.setenv("PROGRAMFILES", str(program_files))
    monkeypatch.delenv("PROGRAMFILES(X86)", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    return program_files, local


def test_windows_finds_preinstalled_edge_outside_path(windows: tuple[Path, Path]) -> None:
    program_files, _local = windows
    edge = _install(program_files, "Microsoft", "Edge", "Application", "msedge.exe")

    assert browser.chrome_path() == str(edge)


def test_windows_prefers_chrome_including_per_user_installs(windows: tuple[Path, Path]) -> None:
    program_files, local = windows
    _install(program_files, "Microsoft", "Edge", "Application", "msedge.exe")
    chrome = _install(local, "Google", "Chrome", "Application", "chrome.exe")

    assert browser.chrome_path() == str(chrome)


class _Proc:
    def __init__(self, exit_after: int | None = None) -> None:
        self._polls = 0
        self._exit_after = exit_after

    def poll(self) -> int | None:
        self._polls += 1
        return 0 if self._exit_after is not None and self._polls > self._exit_after else None


def _proc(exit_after: int | None = None) -> subprocess.Popen[bytes]:
    return cast(subprocess.Popen[bytes], _Proc(exit_after))


def _devtools(monkeypatch: pytest.MonkeyPatch, responses: list[object]) -> list[str]:
    """Serve successive /json/list responses; an Exception instance is raised instead."""
    calls: list[str] = []

    def fetch_json(url: str) -> object:
        calls.append(url)
        response = responses.pop(0) if responses else []
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(browser, "read_devtools_port", lambda profile: 9222)
    monkeypatch.setattr(browser, "fetch_json", fetch_json)
    monkeypatch.setattr(browser.time, "sleep", lambda seconds: None)
    return calls


PAGE = {"type": "page", "url": "https://accounts.google.com/"}
WORKER = {"type": "service_worker", "url": "https://www.youtube.com/sw.js"}


def test_login_wait_ends_when_the_last_page_closes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # macOS keeps the browser process alive after its last window closes.
    calls = _devtools(monkeypatch, [[PAGE], [PAGE, WORKER], [WORKER]])

    browser.wait_for_login_window(_proc(), tmp_path)

    assert calls == ["http://127.0.0.1:9222/json/list"] * 3


def test_login_wait_ends_when_the_browser_exits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _devtools(monkeypatch, [[PAGE], [PAGE]])

    browser.wait_for_login_window(_proc(exit_after=2), tmp_path)

    assert len(calls) == 2


def test_login_wait_ends_when_devtools_goes_away(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _devtools(monkeypatch, [[PAGE], ConnectionRefusedError()])

    browser.wait_for_login_window(_proc(), tmp_path)


def test_login_wait_times_out_while_the_window_stays_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _devtools(monkeypatch, [[PAGE]] * 10)

    with pytest.raises(OpenBBQError) as raised:
        browser.wait_for_login_window(_proc(), tmp_path, timeout_s=0)

    assert raised.value.code == "browser_login_timeout"
