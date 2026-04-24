from __future__ import annotations

import os

from fastapi import APIRouter, Request

from openbbq import __version__
from openbbq.api.schemas import ApiSuccess, HealthData

router = APIRouter(tags=["health"])


@router.get("/health", response_model=ApiSuccess[HealthData])
def health(request: Request) -> ApiSuccess[HealthData]:
    settings = request.app.state.openbbq_settings
    return ApiSuccess(
        data=HealthData(
            version=__version__,
            pid=os.getpid(),
            project_root=settings.project_root,
        )
    )
