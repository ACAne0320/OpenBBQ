from __future__ import annotations

import sqlite3
import subprocess
import sys
from collections.abc import Callable
from contextlib import closing
from pathlib import Path
from typing import cast

import pytest

from openbbq.core.auth import browser, sites
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
    return cast("subprocess.Popen[bytes]", _Proc(exit_after))


def _cookie_db(profile: Path, rows: list[tuple[str, str, int]], *, network: bool = True) -> None:
    db = profile / "Default" / ("Network" if network else "") / "Cookies"
    db.parent.mkdir(parents=True, exist_ok=True)
    db.unlink(missing_ok=True)
    with closing(sqlite3.connect(db)) as conn:
        conn.execute("CREATE TABLE cookies (host_key TEXT, name TEXT, creation_utc INTEGER)")
        conn.executemany("INSERT INTO cookies VALUES (?, ?, ?)", rows)
        conn.commit()


def _on_sleep(monkeypatch: pytest.MonkeyPatch, *steps: Callable[[], None]) -> list[float]:
    """Run one step per poll interval, standing in for the user acting in the browser."""
    pending = list(steps)
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        if pending:
            pending.pop(0)()

    monkeypatch.setattr(browser.time, "sleep", sleep)
    return sleeps


YOUTUBE = sites.require_policy("youtube")


def test_login_cookie_reads_only_the_sites_sign_in_cookie(tmp_path: Path) -> None:
    assert browser.login_cookie_created(tmp_path, YOUTUBE) == 0
    _cookie_db(
        tmp_path,
        [
            (".youtube.com", "LOGIN_INFO", 200),
            (".youtube.com", "PREF", 900),
            (".google.com", "LOGIN_INFO", 900),
        ],
        network=False,
    )

    assert browser.login_cookie_created(tmp_path, YOUTUBE) == 200


def test_login_cookie_is_unknown_when_the_database_is_unreadable(tmp_path: Path) -> None:
    db = tmp_path / "Default" / "Network" / "Cookies"
    db.parent.mkdir(parents=True)
    db.write_bytes(b"not a database")

    assert browser.login_cookie_created(tmp_path, YOUTUBE) is None


def test_login_wait_ends_once_a_new_sign_in_cookie_appears(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # macOS keeps the browser running after its last window closes.
    _cookie_db(tmp_path, [(".youtube.com", "LOGIN_INFO", 100)])  # an earlier login
    sleeps = _on_sleep(
        monkeypatch,
        lambda: None,
        lambda: _cookie_db(tmp_path, [(".youtube.com", "LOGIN_INFO", 300)]),
    )

    browser.wait_for_login(_proc(), tmp_path, YOUTUBE)

    assert len(sleeps) == 2


def test_login_wait_ends_when_the_browser_exits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Windows locks the cookie database, so only the browser exiting ends the wait.
    monkeypatch.setattr(browser, "login_cookie_created", lambda profile, policy: None)
    sleeps = _on_sleep(monkeypatch)

    browser.wait_for_login(_proc(exit_after=3), tmp_path, YOUTUBE)

    assert len(sleeps) == 3


def test_login_wait_times_out_while_the_window_stays_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _on_sleep(monkeypatch)

    with pytest.raises(OpenBBQError) as raised:
        browser.wait_for_login(_proc(), tmp_path, YOUTUBE, timeout_s=0)

    assert raised.value.code == "browser_login_timeout"


def test_login_browser_runs_without_remote_debugging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Google refuses to sign in to a browser with remote debugging on.
    launched: list[list[str]] = []

    def popen(argv: list[str], **kwargs: object) -> subprocess.Popen[bytes]:
        launched.append(argv)
        return _proc(exit_after=0)

    monkeypatch.setattr(browser, "chrome_path", lambda: "chrome")
    monkeypatch.setattr(browser.store, "browser_profile_dir", lambda site: tmp_path / site)
    monkeypatch.setattr(browser.subprocess, "Popen", popen)
    monkeypatch.setattr(browser, "extract_cookies_from_profile", lambda profile, on_message: [])

    browser.browser_login("youtube")

    assert launched and not any("remote-debugging" in arg for arg in launched[0])
