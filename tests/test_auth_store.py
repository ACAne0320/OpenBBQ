from __future__ import annotations

import stat
from time import time

from openbbq.core.auth import store


def test_auth_store_saves_status_exports_and_clears(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("OPENBBQ_HOME", str(tmp_path / "home"))
    expires = int(time()) + 3600

    status = store.save_cookies(
        "youtube",
        [
            {
                "name": "SID",
                "value": "secret",
                "domain": ".youtube.com",
                "path": "/",
                "expires": expires,
                "httpOnly": True,
                "secure": True,
            }
        ],
    )

    assert status.configured is True
    assert status.cookie_count == 1
    assert status.auth_cookie_count == 1

    exported = store.export_netscape_temp("youtube")
    try:
        text = exported.read_text(encoding="utf-8")
        mode = stat.S_IMODE(exported.stat().st_mode)
        assert "# Netscape HTTP Cookie File" in text
        assert "\tSID\tsecret" in text
        assert mode == 0o600
    finally:
        exported.unlink(missing_ok=True)

    store.browser_profile_dir("youtube").mkdir(parents=True)
    store.clear("youtube")
    assert store.status("youtube").configured is False
    assert not store.browser_profile_dir("youtube").exists()
