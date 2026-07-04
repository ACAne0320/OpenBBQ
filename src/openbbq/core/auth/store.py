from __future__ import annotations

import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from openbbq.errors import OpenBBQError

from . import cookies as cookiefile
from . import sites


def openbbq_home() -> Path:
    return Path(os.environ.get("OPENBBQ_HOME", "~/.openbbq")).expanduser()


def auth_root() -> Path:
    return openbbq_home() / "auth"


def site_dir(site: str) -> Path:
    policy = sites.require_policy(site)
    return auth_root() / policy.key


def browser_profile_dir(site: str) -> Path:
    return site_dir(site) / "browser-profile"


def cookies_path(site: str) -> Path:
    return site_dir(site) / "cookies.json"


def metadata_path(site: str) -> Path:
    return site_dir(site) / "metadata.json"


@dataclass(frozen=True)
class AuthStatus:
    site: str
    configured: bool
    cookie_count: int = 0
    auth_cookie_count: int = 0
    expires_at: datetime | None = None


def _write_json_secure(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name("." + path.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def save_cookies(site: str, cookies: list[dict[str, object]]) -> AuthStatus:
    policy = sites.require_policy(site)
    filtered = sites.filter_cookies(policy.key, cookies)
    auth_names = sites.auth_cookie_names(policy.key, filtered)
    if not auth_names:
        raise OpenBBQError(
            "auth_cookies_missing",
            site=policy.key,
            fix=f"log in to {policy.label} and try again",
        )
    now = datetime.now(timezone.utc)
    _write_json_secure(
        cookies_path(policy.key),
        {"site": policy.key, "updated_at": now.isoformat(), "cookies": filtered},
    )
    _write_json_secure(
        metadata_path(policy.key),
        {
            "site": policy.key,
            "updated_at": now.isoformat(),
            "cookie_count": len(filtered),
            "auth_cookie_count": len(auth_names),
        },
    )
    return status(policy.key)


def load_cookies(site: str) -> list[dict[str, object]]:
    policy = sites.require_policy(site)
    path = cookies_path(policy.key)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise OpenBBQError(
            "auth_missing",
            site=policy.key,
            fix=f"openbbq auth browser-login {policy.key}",
        ) from e
    except (OSError, json.JSONDecodeError) as e:
        raise OpenBBQError(
            "auth_invalid",
            site=policy.key,
            fix=f"run openbbq auth clear {policy.key}, then browser-login again",
        ) from e
    raw = data.get("cookies")
    if not isinstance(raw, list):
        raise OpenBBQError(
            "auth_invalid",
            site=policy.key,
            fix=f"run openbbq auth clear {policy.key}, then browser-login again",
        )
    cookies = [item for item in raw if isinstance(item, dict)]
    filtered = sites.filter_cookies(policy.key, cookies)
    if not sites.has_auth_cookies(policy.key, filtered):
        raise OpenBBQError(
            "auth_missing",
            site=policy.key,
            fix=f"openbbq auth browser-login {policy.key}",
        )
    return filtered


def status(site: str) -> AuthStatus:
    policy = sites.require_policy(site)
    try:
        cookies = load_cookies(policy.key)
    except OpenBBQError as err:
        if err.code in {"auth_missing", "auth_invalid"}:
            return AuthStatus(site=policy.key, configured=False)
        raise
    expires = sites.nearest_auth_expiry(policy.key, cookies)
    expires_at = (
        datetime.fromtimestamp(expires, timezone.utc) if expires is not None else None
    )
    return AuthStatus(
        site=policy.key,
        configured=True,
        cookie_count=len(cookies),
        auth_cookie_count=len(sites.auth_cookie_names(policy.key, cookies)),
        expires_at=expires_at,
    )


def clear(site: str) -> None:
    policy = sites.require_policy(site)
    for path in (cookies_path(policy.key), metadata_path(policy.key)):
        path.unlink(missing_ok=True)
    shutil.rmtree(browser_profile_dir(policy.key), ignore_errors=True)


def export_netscape_temp(site: str) -> Path:
    policy = sites.require_policy(site)
    cookies = load_cookies(policy.key)
    directory = site_dir(policy.key)
    directory.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(
        prefix=f"{policy.key}-cookies-", suffix=".txt", dir=directory
    )
    os.close(fd)
    path = Path(name)
    cookiefile.write_netscape(path, cookies)
    return path
