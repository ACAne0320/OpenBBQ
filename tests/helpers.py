from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fastapi.testclient import TestClient

FIXTURE_ROOT = Path(__file__).parent / "fixtures"
PROJECT_FIXTURE_ROOT = FIXTURE_ROOT / "projects"
PLUGIN_FIXTURE_ROOT = FIXTURE_ROOT / "plugins"
DEFAULT_API_TOKEN = "token"


def write_project_fixture(
    tmp_path: Path,
    fixture_name: str,
    *,
    project_dir_name: str = "project",
) -> Path:
    project = tmp_path / project_dir_name
    project.mkdir()
    source = (PROJECT_FIXTURE_ROOT / fixture_name / "openbbq.yaml").read_text(encoding="utf-8")
    (project / "openbbq.yaml").write_text(
        source.replace("../../plugins", str(PLUGIN_FIXTURE_ROOT.resolve())),
        encoding="utf-8",
    )
    return project


def api_auth_headers(token: str = DEFAULT_API_TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def authed_client(
    project: Path,
    *,
    token: str = DEFAULT_API_TOKEN,
    execute_runs_inline: bool = True,
    raise_server_exceptions: bool = True,
    **settings_overrides: Any,
) -> tuple["TestClient", dict[str, str]]:
    from fastapi.testclient import TestClient

    from openbbq.api.app import ApiAppSettings, create_app

    settings_overrides.setdefault("user_db_path", project.parent / "openbbq-user.db")
    settings = ApiAppSettings(
        project_root=project,
        token=token,
        execute_runs_inline=execute_runs_inline,
        **settings_overrides,
    )
    client = TestClient(
        create_app(settings),
        raise_server_exceptions=raise_server_exceptions,
    )
    return client, api_auth_headers(token)
