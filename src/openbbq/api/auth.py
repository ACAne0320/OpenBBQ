from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from openbbq.api.schemas import ApiError, ApiErrorResponse

AUTH_EXEMPT_PATHS = frozenset({"/health", "/openapi.json", "/docs", "/redoc"})


def install_auth_middleware(app: FastAPI, settings) -> None:
    @app.middleware("http")
    async def require_bearer_token(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        token = settings.token
        if token is None or request.url.path in AUTH_EXEMPT_PATHS:
            return await call_next(request)
        expected = f"Bearer {token}"
        if request.headers.get("Authorization") != expected:
            payload = ApiErrorResponse(
                error=ApiError(
                    code="unauthorized",
                    message="Missing or invalid bearer token.",
                )
            )
            return JSONResponse(status_code=401, content=payload.model_dump(mode="json"))
        return await call_next(request)
