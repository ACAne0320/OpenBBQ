from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from openbbq.api.schemas import ApiError, ApiErrorResponse
from openbbq.errors import OpenBBQError


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(OpenBBQError)
    async def openbbq_error_handler(request: Request, exc: OpenBBQError) -> JSONResponse:
        payload = ApiErrorResponse(error=ApiError(code=exc.code, message=exc.message))
        return JSONResponse(
            status_code=_status_code(exc),
            content=payload.model_dump(mode="json"),
        )


def _status_code(error: OpenBBQError) -> int:
    if error.code == "validation_error":
        return 422
    if error.code == "artifact_not_found":
        return 404
    if error.code in {"invalid_workflow_state", "invalid_command_usage"}:
        return 409
    return 500 if error.exit_code >= 5 else 400
