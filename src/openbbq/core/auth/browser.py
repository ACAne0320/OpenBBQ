from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import shutil
import socket
import sqlite3
import struct
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from contextlib import closing
from pathlib import Path
from typing import cast
from urllib.parse import urlparse
from urllib.request import urlopen

from openbbq.errors import OpenBBQError

from . import sites, store


# Per-machine installs live under Program Files, per-user ones under LocalAppData.
_WINDOWS_INSTALL_ROOTS = ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")
_WINDOWS_BROWSERS = (
    ("Google", "Chrome", "Application", "chrome.exe"),
    ("Chromium", "Application", "chrome.exe"),
    ("BraveSoftware", "Brave-Browser", "Application", "brave.exe"),
    ("Microsoft", "Edge", "Application", "msedge.exe"),
)


def _browser_candidates() -> list[str | None]:
    if sys.platform == "win32":
        roots = [root for key in _WINDOWS_INSTALL_ROOTS if (root := os.environ.get(key))]
        installed: list[str | None] = [
            str(Path(root, *parts)) for parts in _WINDOWS_BROWSERS for root in roots
        ]
        return [*installed, shutil.which("chrome"), shutil.which("msedge")]
    return [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        shutil.which("google-chrome"),
        shutil.which("chromium"),
        shutil.which("chromium-browser"),
        shutil.which("brave-browser"),
        shutil.which("microsoft-edge"),
    ]


def chrome_path() -> str:
    for candidate in _browser_candidates():
        if candidate and Path(candidate).exists():
            return str(candidate)
    raise OpenBBQError(
        "browser_missing",
        fix="install Chrome, Chromium, Brave, or Microsoft Edge",
    )


def read_devtools_port(profile: Path, timeout_s: float = 20) -> int:
    path = profile / "DevToolsActivePort"
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
            if lines:
                return int(lines[0])
        except (OSError, ValueError):
            pass
        time.sleep(0.1)
    raise OpenBBQError("browser_cdp_unavailable", fix="close Chrome and try again")


def fetch_json(url: str) -> object:
    with urlopen(url, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


class CDPWebSocket:
    def __init__(self, ws_url: str) -> None:
        parsed = urlparse(ws_url)
        if parsed.scheme != "ws":
            raise ValueError(f"unsupported websocket URL: {ws_url}")
        self.host = parsed.hostname or "127.0.0.1"
        self.port = parsed.port or 80
        self.path = parsed.path
        if parsed.query:
            self.path += "?" + parsed.query
        self.sock = socket.create_connection((self.host, self.port), timeout=5)
        self.next_id = 0
        self._handshake()

    def close(self) -> None:
        self.sock.close()

    def command(self, method: str, params: dict[str, object] | None = None) -> dict[str, object]:
        self.next_id += 1
        payload: dict[str, object] = {"id": self.next_id, "method": method}
        if params is not None:
            payload["params"] = params
        self._send_text(json.dumps(payload, separators=(",", ":")))
        while True:
            data = json.loads(self._recv_text())
            if data.get("id") == self.next_id:
                if "error" in data:
                    raise RuntimeError(f"{method}: {data['error']}")
                result = data.get("result", {})
                return result if isinstance(result, dict) else {}

    def _handshake(self) -> None:
        key = base64.b64encode(secrets.token_bytes(16)).decode("ascii")
        request = (
            f"GET {self.path} HTTP/1.1\r\n"
            f"Host: {self.host}:{self.port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        )
        self.sock.sendall(request.encode("ascii"))
        response = b""
        while b"\r\n\r\n" not in response:
            response += self.sock.recv(4096)
        if b" 101 " not in response.split(b"\r\n", 1)[0]:
            raise RuntimeError(response.decode("latin1", errors="replace"))
        accept = base64.b64encode(
            hashlib.sha1(
                (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()
            ).digest()
        )
        if accept not in response:
            raise RuntimeError("websocket accept key mismatch")

    def _send_text(self, text: str) -> None:
        data = text.encode("utf-8")
        header = bytearray([0x81])
        length = len(data)
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", length))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", length))
        mask = secrets.token_bytes(4)
        masked = bytes(byte ^ mask[i % 4] for i, byte in enumerate(data))
        self.sock.sendall(bytes(header) + mask + masked)

    def _recv_exact(self, n: int) -> bytes:
        data = bytearray()
        while len(data) < n:
            chunk = self.sock.recv(n - len(data))
            if not chunk:
                raise EOFError("websocket closed")
            data.extend(chunk)
        return bytes(data)

    def _recv_text(self) -> str:
        while True:
            first, second = self._recv_exact(2)
            opcode = first & 0x0F
            masked = bool(second & 0x80)
            length = second & 0x7F
            if length == 126:
                length = struct.unpack("!H", self._recv_exact(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", self._recv_exact(8))[0]
            mask = self._recv_exact(4) if masked else b""
            payload = self._recv_exact(length)
            if masked:
                payload = bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload))
            if opcode == 1:
                return payload.decode("utf-8")
            if opcode == 8:
                raise EOFError("websocket closed")


def extract_cookies_from_profile(profile: Path, *, on_message: Callable[[str], None]) -> list[dict[str, object]]:
    browser = chrome_path()
    devtools = profile / "DevToolsActivePort"
    devtools.unlink(missing_ok=True)
    proc = subprocess.Popen(
        [
            browser,
            f"--user-data-dir={profile}",
            "--remote-debugging-address=127.0.0.1",
            "--remote-debugging-port=0",
            "--no-first-run",
            "--no-default-browser-check",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        port = read_devtools_port(profile)
        version = fetch_json(f"http://127.0.0.1:{port}/json/version")
        if not isinstance(version, dict):
            raise OpenBBQError("browser_cdp_unavailable", fix="close Chrome and try again")
        ws_url = version.get("webSocketDebuggerUrl")
        if not isinstance(ws_url, str) or not ws_url:
            raise OpenBBQError("browser_cdp_unavailable", fix="close Chrome and try again")
        ws = CDPWebSocket(ws_url)
        try:
            result = ws.command("Storage.getCookies")
            cookies = result.get("cookies", [])
            if not isinstance(cookies, list):
                return []
            return [
                cast(dict[str, object], item)
                for item in cookies
                if isinstance(item, dict)
            ]
        finally:
            ws.close()
    finally:
        on_message("Stopping browser")
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


# Logging in can involve 2FA or a bot check; give up eventually so agents do not hang.
LOGIN_TIMEOUT_S = 15 * 60


def login_cookie_created(profile: Path, policy: sites.SitePolicy) -> int | None:
    """Creation time of the newest sign-in cookie in a browser profile.

    0 when there is none yet, None when the cookie database cannot be read. Reads a
    copy, since Chrome keeps the database locked; on Windows the lock is exclusive
    and the copy always fails.
    """
    for db in (profile / "Default" / "Network" / "Cookies", profile / "Default" / "Cookies"):
        if not db.is_file():
            continue
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "Cookies"
            try:
                shutil.copyfile(db, copy)
                with closing(sqlite3.connect(copy)) as conn:
                    rows = conn.execute(
                        "SELECT host_key, creation_utc FROM cookies WHERE name = ?",
                        (policy.login_cookie,),
                    ).fetchall()
            except (OSError, sqlite3.Error):
                return None
        return max(
            (int(created) for host, created in rows if sites.domain_matches(host, policy.domains[0])),
            default=0,
        )
    return 0


def wait_for_login(
    proc: subprocess.Popen[bytes],
    profile: Path,
    policy: sites.SitePolicy,
    *,
    timeout_s: float = LOGIN_TIMEOUT_S,
    poll_s: float = 2.0,
) -> None:
    """Return once the user has signed in or closed the browser.

    Never enables DevTools on the login browser: Google refuses to sign in to a
    browser with remote debugging on. Chrome exits with its last window on Windows
    and Linux; on macOS it keeps running, so also watch the profile for a new
    sign-in cookie (Chrome writes cookies to disk within about 30 seconds).
    """
    baseline = login_cookie_created(profile, policy)
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return
        created = login_cookie_created(profile, policy)
        if baseline is None:
            baseline = created  # an earlier login's cookie must not end the wait
        elif created is not None and created > baseline:
            return
        time.sleep(poll_s)
    raise OpenBBQError(
        "browser_login_timeout",
        timeout_s=int(timeout_s),
        fix="run openbbq auth browser-login again, then close the login window when done",
    )


def browser_login(
    site: str,
    *,
    on_message: Callable[[str], None] = lambda _: None,
) -> list[dict[str, object]]:
    policy = sites.require_policy(site)
    profile = store.browser_profile_dir(policy.key)
    profile.mkdir(mode=0o700, parents=True, exist_ok=True)
    browser = chrome_path()
    on_message(f"Opening {policy.label} login browser")
    proc = subprocess.Popen(
        [
            browser,
            f"--user-data-dir={profile}",
            "--no-first-run",
            "--no-default-browser-check",
            "--new-window",
            policy.login_url,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        if sys.platform == "darwin":
            on_message(
                "Log in (and pass any verification) in that window, then quit the"
                " browser (Cmd+Q). It may also close by itself once you are signed in."
            )
        else:
            on_message("Log in (and pass any verification) in that window, then close it.")
        wait_for_login(proc, profile, policy)
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
    on_message("Reading cookies from the login profile")
    return extract_cookies_from_profile(profile, on_message=on_message)
