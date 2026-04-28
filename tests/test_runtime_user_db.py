from __future__ import annotations

import sqlite3
from pathlib import Path

from openbbq.runtime.user_db import UserRuntimeDatabase
from openbbq.storage.models import QuickstartTaskRecord, RunErrorRecord


def test_user_runtime_database_stores_quickstart_tasks(tmp_path):
    database = UserRuntimeDatabase(tmp_path / "openbbq.db")
    task = _quickstart_task(tmp_path)

    database.upsert_quickstart_task(task)

    assert database.read_quickstart_task(task.run_id) == task
    assert database.list_quickstart_tasks() == (task,)
    assert database.find_quickstart_tasks_by_cache_key("cache-1") == (task,)


def test_user_runtime_database_updates_quickstart_task_status(tmp_path):
    database = UserRuntimeDatabase(tmp_path / "openbbq.db")
    task = _quickstart_task(tmp_path)
    database.upsert_quickstart_task(task)

    updated = task.model_copy(
        update={
            "status": "failed",
            "updated_at": "2026-04-28T01:02:03+00:00",
            "completed_at": "2026-04-28T01:02:03+00:00",
            "error": RunErrorRecord(code="connection_error", message="Connection error."),
        }
    )
    database.upsert_quickstart_task(updated)

    assert database.read_quickstart_task(task.run_id) == updated


def test_existing_user_database_is_migrated_to_quickstart_tasks(tmp_path):
    path = tmp_path / "openbbq.db"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "create table providers (name text primary key, type text not null, base_url text, "
            "api_key text, default_chat_model text, display_name text)"
        )
        connection.execute(
            "create table credentials (reference text primary key, value text not null, "
            "updated_at text not null)"
        )

    UserRuntimeDatabase(path)

    with sqlite3.connect(path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "select name from sqlite_master where type = 'table'"
            ).fetchall()
        }

    assert "quickstart_tasks" in tables


def _quickstart_task(tmp_path: Path) -> QuickstartTaskRecord:
    return QuickstartTaskRecord(
        id="task_run_1",
        run_id="run_1",
        workflow_id="youtube-to-srt",
        workspace_root=tmp_path / "workspace",
        generated_project_root=tmp_path / "workspace/.openbbq/generated/youtube-subtitle/run_1",
        generated_config_path=tmp_path
        / "workspace/.openbbq/generated/youtube-subtitle/run_1/openbbq.yaml",
        plugin_paths=(tmp_path / "plugins",),
        source_kind="remote_url",
        source_uri="https://www.youtube.com/watch?v=demo",
        source_summary="https://www.youtube.com/watch?v=demo",
        source_lang="en",
        target_lang="zh",
        provider="openai",
        model="gpt-4o-mini",
        asr_model="base",
        asr_device="cpu",
        asr_compute_type="int8",
        quality="best",
        auth="auto",
        browser=None,
        browser_profile=None,
        output_path=tmp_path / "out.srt",
        source_artifact_id=None,
        cache_key="cache-1",
        status="queued",
        created_at="2026-04-28T00:00:00+00:00",
        updated_at="2026-04-28T00:00:00+00:00",
        completed_at=None,
        error=None,
    )
