from __future__ import annotations

from fastapi import Request

from openbbq.runtime.user_db import UserRuntimeDatabase


def user_runtime_database(request: Request) -> UserRuntimeDatabase:
    settings = request.app.state.openbbq_settings
    return UserRuntimeDatabase(path=settings.user_db_path)
