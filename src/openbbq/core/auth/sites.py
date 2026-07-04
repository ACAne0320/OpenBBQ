from __future__ import annotations

from dataclasses import dataclass
from time import time
from urllib.parse import urlparse

from openbbq.errors import OpenBBQError


YOUTUBE_AUTH_COOKIE_NAMES = {
    "APISID",
    "HSID",
    "LOGIN_INFO",
    "SAPISID",
    "SID",
    "SSID",
    "__Secure-1PAPISID",
    "__Secure-1PSID",
    "__Secure-1PSIDCC",
    "__Secure-1PSIDTS",
    "__Secure-3PAPISID",
    "__Secure-3PSID",
    "__Secure-3PSIDCC",
    "__Secure-3PSIDTS",
}


@dataclass(frozen=True)
class SitePolicy:
    key: str
    label: str
    login_url: str
    domains: tuple[str, ...]
    auth_cookie_names: frozenset[str]


YOUTUBE = SitePolicy(
    key="youtube",
    label="YouTube",
    login_url=(
        "https://accounts.google.com/ServiceLogin?service=youtube&uilel=3&passive=true"
        "&continue=https%3A%2F%2Fwww.youtube.com%2Fsignin%3Faction_handle_signin%3Dtrue"
        "%26app%3Ddesktop%26hl%3Den%26next%3Dhttps%253A%252F%252Fwww.youtube.com%252F"
    ),
    domains=(
        "youtube.com",
        "youtu.be",
        "youtube-nocookie.com",
        "google.com",
        "googleusercontent.com",
        "gstatic.com",
        "ytimg.com",
    ),
    auth_cookie_names=frozenset(YOUTUBE_AUTH_COOKIE_NAMES),
)

POLICIES = {YOUTUBE.key: YOUTUBE}


def _float_value(value: object) -> float:
    if not isinstance(value, (int, float, str)):
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _int_value(value: object) -> int:
    if not isinstance(value, (int, float, str)):
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def require_policy(site: str) -> SitePolicy:
    key = site.strip().lower()
    try:
        return POLICIES[key]
    except KeyError as e:
        raise OpenBBQError(
            "unsupported_auth_site",
            site=site,
            fix="supported sites: " + ", ".join(sorted(POLICIES)),
        ) from e


def domain_matches(domain: str, allowed: str) -> bool:
    host = domain.lower().strip().lstrip(".")
    allowed = allowed.lower().strip().lstrip(".")
    return host == allowed or host.endswith("." + allowed)


def domain_allowed(domain: str, policy: SitePolicy) -> bool:
    return any(domain_matches(domain, allowed) for allowed in policy.domains)


def policy_for_url(raw_url: str) -> SitePolicy | None:
    parsed = urlparse(raw_url.strip())
    host = parsed.hostname or ""
    if not host:
        return None
    for policy in POLICIES.values():
        if domain_allowed(host, policy):
            return policy
    return None


def normalize_cookie(cookie: dict[str, object]) -> dict[str, object] | None:
    name = str(cookie.get("name", "")).strip()
    value = str(cookie.get("value", ""))
    domain = str(cookie.get("domain", "")).strip()
    path = str(cookie.get("path", "") or "/").strip() or "/"
    if not name or not value or not domain:
        return None
    expires = cookie.get("expires", 0) or cookie.get("expirationDate", 0) or 0
    expires_float = _float_value(expires)
    return {
        "name": name,
        "value": value,
        "domain": domain,
        "path": path,
        "expires": int(expires_float) if expires_float > 0 else 0,
        "httpOnly": bool(cookie.get("httpOnly", False)),
        "secure": bool(cookie.get("secure", False)),
        "sameSite": str(cookie.get("sameSite", "")).lower().strip(),
    }


def filter_cookies(site: str, cookies: list[dict[str, object]]) -> list[dict[str, object]]:
    policy = require_policy(site)
    now = int(time())
    result: list[dict[str, object]] = []
    for raw in cookies:
        cookie = normalize_cookie(raw)
        if cookie is None:
            continue
        expires = _int_value(cookie.get("expires", 0))
        if expires > 0 and expires < now:
            continue
        if not domain_allowed(str(cookie["domain"]), policy):
            continue
        result.append(cookie)
    return result


def auth_cookie_names(site: str, cookies: list[dict[str, object]]) -> set[str]:
    policy = require_policy(site)
    names = {str(cookie.get("name", "")).strip().lower() for cookie in cookies}
    return {
        name
        for name in policy.auth_cookie_names
        if name.strip().lower() in names
    }


def has_auth_cookies(site: str, cookies: list[dict[str, object]]) -> bool:
    return bool(auth_cookie_names(site, cookies))


def nearest_auth_expiry(site: str, cookies: list[dict[str, object]]) -> int | None:
    policy = require_policy(site)
    wanted = {name.lower() for name in policy.auth_cookie_names}
    now = int(time())
    expiries: list[int] = []
    for cookie in cookies:
        name = str(cookie.get("name", "")).strip().lower()
        if name not in wanted:
            continue
        expires = _int_value(cookie.get("expires", 0))
        if expires > now:
            expiries.append(expires)
    return min(expiries) if expiries else None
