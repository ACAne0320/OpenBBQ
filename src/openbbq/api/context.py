from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import Request

from openbbq.errors import ValidationError

if TYPE_CHECKING:
    from openbbq.api.app import ApiAppSettings


def active_project_settings(request: Request) -> ApiAppSettings:
    settings = request.app.state.openbbq_settings
    if settings.project_root is None:
        raise ValidationError("API sidecar does not have an active project root.")
    return settings
