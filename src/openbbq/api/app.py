from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI

from openbbq import __version__
from openbbq.api.auth import install_auth_middleware
from openbbq.api.errors import install_error_handlers
from openbbq.api.routes import health
from openbbq.domain.base import OpenBBQModel


class ApiAppSettings(OpenBBQModel):
    project_root: Path | None = None
    config_path: Path | None = None
    plugin_paths: tuple[Path, ...] = ()
    token: str | None = None
    allow_dev_cors: bool = False
    execute_runs_inline: bool = False


def create_app(settings: ApiAppSettings | None = None) -> FastAPI:
    app_settings = settings or ApiAppSettings()
    app = FastAPI(title="OpenBBQ API", version=__version__)
    app.state.openbbq_settings = app_settings
    install_error_handlers(app)
    install_auth_middleware(app, app_settings)
    app.include_router(health.router)
    return app


def app_settings(app: FastAPI) -> ApiAppSettings:
    return app.state.openbbq_settings
