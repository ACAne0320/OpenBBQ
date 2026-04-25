from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from openbbq.api.schemas import ApiError, ApiErrorResponse
from openbbq.errors import NotFoundError, OpenBBQError


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(OpenBBQError)
    async def openbbq_error_handler(request: Request, exc: OpenBBQError) -> JSONResponse:
        payload = ApiErrorResponse(error=ApiError(code=exc.code, message=exc.message))
        return JSONResponse(
            status_code=_status_code(exc),
            content=payload.model_dump(mode="json"),
        )

    @app.exception_handler(RequestValidationError)
    async def request_validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        payload = ApiErrorResponse(
            error=ApiError(
                code="validation_error",
                message=_validation_message(exc),
                details={"errors": jsonable_encoder(exc.errors())},
            )
        )
        return JSONResponse(status_code=422, content=payload.model_dump(mode="json"))


def _status_code(error: OpenBBQError) -> int:
    if error.code == "validation_error":
        return 422
    if isinstance(error, NotFoundError):
        return 404
    if error.code in {"invalid_workflow_state", "invalid_command_usage"}:
        return 409
    return 500 if error.exit_code >= 5 else 400


def _validation_message(error: RequestValidationError) -> str:
    first = error.errors()[0] if error.errors() else {}
    message = str(first.get("msg", "Invalid request."))
    location = ".".join(str(part) for part in first.get("loc", ()) if part != "body")
    if location:
        return f"{location}: {message}"
    return message
