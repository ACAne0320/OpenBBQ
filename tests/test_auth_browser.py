from __future__ import annotations

import sys
from pathlib import Path

import pytest

from openbbq.core.auth import browser


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
