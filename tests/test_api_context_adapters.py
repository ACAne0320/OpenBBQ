from pathlib import Path

import pytest
from fastapi import FastAPI, Request

from openbbq.api.adapters import api_model, api_models
from openbbq.api.app import ApiAppSettings
from openbbq.api.context import active_project_settings
from openbbq.api.schemas import ProjectInitData
from openbbq.domain.base import OpenBBQModel
from openbbq.errors import ValidationError


class SourceModel(OpenBBQModel):
    config_path: Path


def test_active_project_settings_returns_configured_settings(tmp_path):
    settings = ApiAppSettings(project_root=tmp_path, token="token")
    request = _request_for_settings(settings)

    result = active_project_settings(request)

    assert result is settings
    assert result.project_root == tmp_path


def test_active_project_settings_requires_project_root():
    request = _request_for_settings(ApiAppSettings(token="token"))

    with pytest.raises(
        ValidationError,
        match="API sidecar does not have an active project root.",
    ):
        active_project_settings(request)


def test_api_model_adapts_matching_openbbq_models(tmp_path):
    source = SourceModel(config_path=tmp_path / "openbbq.yaml")

    result = api_model(ProjectInitData, source)

    assert isinstance(result, ProjectInitData)
    assert result.config_path == tmp_path / "openbbq.yaml"


def test_api_models_returns_tuple_of_adapted_models(tmp_path):
    first = SourceModel(config_path=tmp_path / "one.yaml")
    second = SourceModel(config_path=tmp_path / "two.yaml")

    result = api_models(ProjectInitData, (first, second))

    assert isinstance(result, tuple)
    assert result == (
        ProjectInitData(config_path=tmp_path / "one.yaml"),
        ProjectInitData(config_path=tmp_path / "two.yaml"),
    )


def _request_for_settings(settings: ApiAppSettings) -> Request:
    app = FastAPI()
    app.state.openbbq_settings = settings
    return Request(
        {
            "type": "http",
            "app": app,
            "method": "GET",
            "path": "/",
            "headers": [],
        }
    )
