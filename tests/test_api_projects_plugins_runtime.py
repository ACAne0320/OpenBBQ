import sqlite3

from fastapi.testclient import TestClient

from openbbq.api.app import ApiAppSettings, create_app
from openbbq.application.quickstart import SubtitleJobResult
from openbbq.config.loader import load_project_config
from openbbq.runtime.user_db import UserRuntimeDatabase
from openbbq.storage.models import QuickstartTaskRecord, RunRecord
from openbbq.storage.project_store import ProjectStore
from openbbq.storage.runs import write_run
from tests.helpers import authed_client, write_project_fixture


def test_project_and_plugin_routes(tmp_path):
    project = write_project_fixture(tmp_path, "text-basic")
    client, headers = authed_client(project)

    project_response = client.get("/projects/current", headers=headers)
    plugins_response = client.get("/plugins", headers=headers)
    plugin_response = client.get("/plugins/mock_text", headers=headers)

    assert project_response.status_code == 200
    assert project_response.json()["data"]["name"] == "Text Basic"
    assert plugins_response.json()["data"]["plugins"][0]["name"] == "mock_text"
    assert plugin_response.json()["data"]["plugin"]["name"] == "mock_text"


def test_project_init_route_creates_project_config(tmp_path):
    project = tmp_path / "new-project"
    client = TestClient(create_app(ApiAppSettings(token="token")))
    headers = {"Authorization": "Bearer token"}

    response = client.post(
        "/projects/init",
        headers=headers,
        json={"project_root": str(project)},
    )

    assert response.status_code == 200
    assert response.json()["data"]["config_path"] == str(project / "openbbq.yaml")
    assert (project / "openbbq.yaml").is_file()

    current = client.get("/projects/current", headers=headers)

    assert current.status_code == 200
    assert current.json()["data"]["root_path"] == str(project)


def test_runtime_routes(tmp_path, monkeypatch):
    project = write_project_fixture(tmp_path, "text-basic")
    monkeypatch.setenv("OPENBBQ_USER_CONFIG", str(tmp_path / "user-config.toml"))
    client, headers = authed_client(project)

    settings_response = client.get("/runtime/settings", headers=headers)
    models_response = client.get("/runtime/models", headers=headers)
    doctor_response = client.get("/doctor", headers=headers)

    assert settings_response.status_code == 200
    assert "settings" in settings_response.json()["data"]
    assert models_response.json()["data"]["models"][0]["provider"] == "faster_whisper"
    assert isinstance(doctor_response.json()["data"]["checks"], list)


def test_runtime_auth_and_secret_routes(tmp_path, monkeypatch):
    project = write_project_fixture(tmp_path, "text-basic")
    monkeypatch.setenv("OPENBBQ_USER_CONFIG", str(tmp_path / "user-config.toml"))
    monkeypatch.setenv("OPENBBQ_LLM_API_KEY", "sk-test")
    client, headers = authed_client(project)

    provider = client.put(
        "/runtime/providers/openai-compatible/auth",
        headers=headers,
        json={
            "type": "openai_compatible",
            "api_key_ref": "env:OPENBBQ_LLM_API_KEY",
            "default_chat_model": "gpt-4o-mini",
        },
    )
    check = client.get("/runtime/providers/openai-compatible/check", headers=headers)
    secret = client.post(
        "/runtime/secrets/check",
        headers=headers,
        json={"reference": "env:OPENBBQ_LLM_API_KEY"},
    )

    assert provider.status_code == 200
    assert provider.json()["data"]["provider"]["name"] == "openai-compatible"
    assert check.json()["data"]["secret"]["resolved"] is True
    assert secret.json()["data"]["secret"]["value_preview"] == "sk-...test"


def test_runtime_defaults_and_faster_whisper_routes(tmp_path, monkeypatch):
    project = write_project_fixture(tmp_path, "text-basic")
    monkeypatch.setenv("OPENBBQ_USER_CONFIG", str(tmp_path / "user-config.toml"))
    client, headers = authed_client(project)

    defaults = client.put(
        "/runtime/defaults",
        headers=headers,
        json={"llm_provider": "openai-compatible", "asr_provider": "faster-whisper"},
    )
    asr = client.put(
        "/runtime/models/faster-whisper",
        headers=headers,
        json={
            "cache_dir": str(tmp_path / "fw-cache"),
            "default_model": "small",
            "default_device": "cpu",
            "default_compute_type": "int8",
        },
    )
    settings = client.get("/runtime/settings", headers=headers)
    models = client.get("/runtime/models", headers=headers)

    assert defaults.status_code == 200
    assert (
        defaults.json()["data"]["settings"]["defaults"]["llm_provider"]
        == "openai-compatible"
    )
    assert asr.status_code == 200
    assert (
        settings.json()["data"]["settings"]["models"]["faster_whisper"]["default_model"]
        == "small"
    )
    assert models.json()["data"]["models"][0]["model"] == "small"
    assert models.json()["data"]["models"][0]["cache_dir"] == str(
        (tmp_path / "fw-cache").resolve()
    )


def test_runtime_auth_route_stores_user_secret_in_sqlite(tmp_path, monkeypatch):
    project = write_project_fixture(tmp_path, "text-basic")
    monkeypatch.setenv("OPENBBQ_USER_CONFIG", str(tmp_path / "user-config.toml"))
    client, headers = authed_client(project)

    response = client.put(
        "/runtime/providers/openai/auth",
        headers=headers,
        json={
            "type": "openai_compatible",
            "secret_value": "sk-api",
            "default_chat_model": "gpt-4o-mini",
        },
    )
    check = client.get("/runtime/providers/openai/check", headers=headers)

    with sqlite3.connect(tmp_path / "openbbq.db") as connection:
        row = connection.execute("select reference, value from credentials").fetchone()

    assert response.status_code == 200
    assert response.json()["data"]["provider"]["api_key"] == (
        "sqlite:openbbq/providers/openai/api_key"
    )
    assert check.json()["data"]["secret"]["resolved"] is True
    assert row == ("sqlite:openbbq/providers/openai/api_key", "sk-api")


def test_quickstart_subtitle_routes_return_generated_job_metadata(tmp_path, monkeypatch):
    project = write_project_fixture(tmp_path, "text-basic")
    client, headers = authed_client(project)

    def fake_local_job(request):
        return SubtitleJobResult(
            generated_project_root=tmp_path / "generated-local",
            generated_config_path=tmp_path / "generated-local" / "openbbq.yaml",
            workflow_id="local-to-srt",
            run_id="run_local",
            output_path=request.output_path,
            source_artifact_id="art_source",
        )

    def fake_youtube_job(request):
        return SubtitleJobResult(
            generated_project_root=tmp_path / "generated-youtube",
            generated_config_path=tmp_path / "generated-youtube" / "openbbq.yaml",
            workflow_id="youtube-to-srt",
            run_id="run_youtube",
            output_path=request.output_path,
            source_artifact_id=None,
        )

    monkeypatch.setattr("openbbq.api.routes.quickstart.create_local_subtitle_job", fake_local_job)
    monkeypatch.setattr(
        "openbbq.api.routes.quickstart.create_youtube_subtitle_job", fake_youtube_job
    )

    local = client.post(
        "/quickstart/subtitle/local",
        headers=headers,
        json={
            "input_path": str(tmp_path / "source.mp4"),
            "source_lang": "en",
            "target_lang": "zh",
            "provider": "openai",
            "output_path": str(tmp_path / "out.local.srt"),
        },
    )
    youtube = client.post(
        "/quickstart/subtitle/youtube",
        headers=headers,
        json={
            "url": "https://www.youtube.com/watch?v=demo",
            "source_lang": "en",
            "target_lang": "zh",
            "provider": "openai",
            "output_path": str(tmp_path / "out.youtube.srt"),
        },
    )

    assert local.status_code == 200
    assert local.json()["data"]["workflow_id"] == "local-to-srt"
    assert local.json()["data"]["source_artifact_id"] == "art_source"
    assert youtube.status_code == 200
    assert youtube.json()["data"]["workflow_id"] == "youtube-to-srt"


def test_quickstart_subtitle_route_persists_task_history(tmp_path, monkeypatch):
    project = write_project_fixture(tmp_path, "text-basic")
    generated_project = write_project_fixture(
        tmp_path,
        "text-basic",
        project_dir_name="generated-project",
    )
    generated_config = load_project_config(generated_project)
    write_run(
        generated_config.storage.state,
        RunRecord(
            id="run_generated",
            workflow_id="text-demo",
            mode="start",
            status="queued",
            project_root=generated_project,
            config_path=generated_config.config_path,
            created_by="api",
        ),
    )

    def fake_youtube_job(request):
        return SubtitleJobResult(
            generated_project_root=generated_project,
            generated_config_path=generated_config.config_path,
            workflow_id="text-demo",
            run_id="run_generated",
            output_path=request.output_path,
            source_artifact_id=None,
        )

    monkeypatch.setattr(
        "openbbq.api.routes.quickstart.create_youtube_subtitle_job", fake_youtube_job
    )
    user_db_path = tmp_path / "user.db"
    client = TestClient(
        create_app(ApiAppSettings(project_root=project, token="token", user_db_path=user_db_path))
    )
    headers = {"Authorization": "Bearer token"}

    response = client.post(
        "/quickstart/subtitle/youtube",
        headers=headers,
        json={
            "url": "https://www.youtube.com/watch?v=demo",
            "source_lang": "en",
            "target_lang": "zh",
            "provider": "openai",
            "model": "gpt-4o-mini",
            "asr_model": "base",
            "asr_device": "cpu",
            "asr_compute_type": "int8",
            "quality": "best",
        },
    )
    history = UserRuntimeDatabase(user_db_path).read_quickstart_task("run_generated")

    assert response.status_code == 200
    assert history is not None
    assert history.source_kind == "remote_url"
    assert history.source_uri == "https://www.youtube.com/watch?v=demo"
    assert history.generated_project_root == generated_project
    assert history.generated_config_path == generated_config.config_path
    assert history.status == "queued"


def test_quickstart_history_resolves_run_after_app_restart(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    generated_project = write_project_fixture(
        tmp_path,
        "text-basic",
        project_dir_name="generated-project",
    )
    generated_config = load_project_config(generated_project)
    generated_store = ProjectStore(
        generated_config.storage.root,
        artifacts_root=generated_config.storage.artifacts,
        state_root=generated_config.storage.state,
    )
    generated_store.append_event(
        "text-demo",
        {"type": "workflow.completed", "message": "Generated workflow completed."},
    )
    write_run(
        generated_config.storage.state,
        RunRecord(
            id="run_generated",
            workflow_id="text-demo",
            mode="start",
            status="completed",
            project_root=generated_project,
            config_path=generated_config.config_path,
            latest_event_sequence=1,
            created_by="api",
        ),
    )
    user_db_path = tmp_path / "user.db"
    UserRuntimeDatabase(user_db_path).upsert_quickstart_task(
        QuickstartTaskRecord(
            id="task_run_generated",
            run_id="run_generated",
            workflow_id="text-demo",
            workspace_root=workspace,
            generated_project_root=generated_project,
            generated_config_path=generated_config.config_path,
            plugin_paths=(),
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
            output_path=None,
            source_artifact_id=None,
            cache_key="cache-1",
            status="queued",
            created_at="2026-04-28T00:00:00+00:00",
            updated_at="2026-04-28T00:00:00+00:00",
        )
    )
    client = TestClient(
        create_app(
            ApiAppSettings(project_root=workspace, token="token", user_db_path=user_db_path)
        ),
        raise_server_exceptions=False,
    )
    headers = {"Authorization": "Bearer token"}

    run = client.get("/runs/run_generated", headers=headers)
    events = client.get("/runs/run_generated/events", headers=headers)
    tasks = client.get("/quickstart/tasks", headers=headers)

    assert run.status_code == 200
    assert run.json()["data"]["project_root"] == str(generated_project)
    assert events.status_code == 200
    assert events.json()["data"]["events"][0]["type"] == "workflow.completed"
    assert tasks.status_code == 200
    assert tasks.json()["data"]["tasks"][0]["run_id"] == "run_generated"
    assert tasks.json()["data"]["tasks"][0]["status"] == "completed"


def test_quickstart_subtitle_route_reuses_existing_cached_task(tmp_path, monkeypatch):
    project = write_project_fixture(tmp_path, "text-basic")
    generated_project = write_project_fixture(
        tmp_path,
        "text-basic",
        project_dir_name="generated-project",
    )
    generated_config = load_project_config(generated_project)
    write_run(
        generated_config.storage.state,
        RunRecord(
            id="run_generated",
            workflow_id="text-demo",
            mode="start",
            status="completed",
            project_root=generated_project,
            config_path=generated_config.config_path,
            created_by="api",
        ),
    )
    calls = []

    def fake_youtube_job(request):
        calls.append(request)
        return SubtitleJobResult(
            generated_project_root=generated_project,
            generated_config_path=generated_config.config_path,
            workflow_id="text-demo",
            run_id="run_generated",
            output_path=request.output_path,
            source_artifact_id=None,
        )

    monkeypatch.setattr(
        "openbbq.api.routes.quickstart.create_youtube_subtitle_job", fake_youtube_job
    )
    user_db_path = tmp_path / "user.db"
    client = TestClient(
        create_app(ApiAppSettings(project_root=project, token="token", user_db_path=user_db_path))
    )
    headers = {"Authorization": "Bearer token"}
    body = {
        "url": "https://www.youtube.com/watch?v=demo",
        "source_lang": "en",
        "target_lang": "zh",
        "provider": "openai",
        "model": "gpt-4o-mini",
        "asr_model": "base",
        "asr_device": "cpu",
        "asr_compute_type": "int8",
        "quality": "best",
    }

    first = client.post("/quickstart/subtitle/youtube", headers=headers, json=body)
    second = client.post("/quickstart/subtitle/youtube", headers=headers, json=body)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["data"]["run_id"] == "run_generated"
    assert len(calls) == 1


def test_quickstart_job_run_events_and_artifacts_are_trackable(tmp_path, monkeypatch):
    project = write_project_fixture(tmp_path, "text-basic")
    generated_project = write_project_fixture(
        tmp_path,
        "text-basic",
        project_dir_name="generated-project",
    )
    generated_config = load_project_config(generated_project)
    generated_store = ProjectStore(
        generated_config.storage.root,
        artifacts_root=generated_config.storage.artifacts,
        state_root=generated_config.storage.state,
    )
    write_run(
        generated_config.storage.state,
        RunRecord(
            id="run_generated",
            workflow_id="text-demo",
            mode="start",
            status="completed",
            project_root=generated_project,
            config_path=generated_config.config_path,
            latest_event_sequence=1,
            created_by="api",
        ),
    )
    generated_store.append_event(
        "text-demo",
        {"type": "workflow.completed", "message": "Generated workflow completed."},
    )
    artifact, version = generated_store.write_artifact_version(
        artifact_type="text",
        name="generated.text",
        content="generated artifact",
        metadata={},
        created_by_step_id=None,
        lineage={"workflow_id": "text-demo"},
    )

    def fake_local_job(request):
        return SubtitleJobResult(
            generated_project_root=generated_project,
            generated_config_path=generated_config.config_path,
            workflow_id="text-demo",
            run_id="run_generated",
            output_path=request.output_path,
            source_artifact_id="art_source",
        )

    monkeypatch.setattr("openbbq.api.routes.quickstart.create_local_subtitle_job", fake_local_job)
    client, headers = authed_client(project)

    job = client.post(
        "/quickstart/subtitle/local",
        headers=headers,
        json={
            "input_path": str(tmp_path / "source.mp4"),
            "source_lang": "en",
            "target_lang": "zh",
        },
    )
    run = client.get("/runs/run_generated", headers=headers)
    events = client.get("/runs/run_generated/events", headers=headers)
    artifacts = client.get("/runs/run_generated/artifacts", headers=headers)
    preview = client.get(f"/artifact-versions/{version.id}/preview", headers=headers)

    assert job.status_code == 200
    assert run.status_code == 200
    assert run.json()["data"]["project_root"] == str(generated_project)
    assert events.status_code == 200
    assert events.json()["data"]["events"][0]["type"] == "workflow.completed"
    assert artifacts.status_code == 200
    assert artifacts.json()["data"]["artifacts"][0]["id"] == artifact.id
    assert preview.status_code == 200
    assert preview.json()["data"]["content"] == "generated artifact"


def test_quickstart_generated_run_is_trackable_from_uninitialized_workspace(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    generated_project = write_project_fixture(
        tmp_path,
        "text-basic",
        project_dir_name="generated-project",
    )
    generated_config = load_project_config(generated_project)
    ProjectStore(
        generated_config.storage.root,
        artifacts_root=generated_config.storage.artifacts,
        state_root=generated_config.storage.state,
    ).append_event(
        "text-demo",
        {"type": "workflow.completed", "message": "Generated workflow completed."},
    )
    write_run(
        generated_config.storage.state,
        RunRecord(
            id="run_generated",
            workflow_id="text-demo",
            mode="start",
            status="completed",
            project_root=generated_project,
            config_path=generated_config.config_path,
            latest_event_sequence=1,
            created_by="api",
        ),
    )

    def fake_youtube_job(request):
        return SubtitleJobResult(
            generated_project_root=generated_project,
            generated_config_path=generated_config.config_path,
            workflow_id="text-demo",
            run_id="run_generated",
            output_path=request.output_path,
            source_artifact_id=None,
        )

    monkeypatch.setattr(
        "openbbq.api.routes.quickstart.create_youtube_subtitle_job", fake_youtube_job
    )
    client = TestClient(
        create_app(
            ApiAppSettings(
                project_root=workspace,
                token="token",
                user_db_path=tmp_path / "user.db",
            )
        ),
        raise_server_exceptions=False,
    )
    headers = {"Authorization": "Bearer token"}

    job = client.post(
        "/quickstart/subtitle/youtube",
        headers=headers,
        json={
            "url": "https://www.youtube.com/watch?v=demo",
            "source_lang": "en",
            "target_lang": "zh",
        },
    )
    run = client.get("/runs/run_generated", headers=headers)
    events = client.get("/runs/run_generated/events", headers=headers)

    assert job.status_code == 200
    assert run.status_code == 200
    assert run.json()["data"]["project_root"] == str(generated_project)
    assert events.status_code == 200
    assert events.json()["data"]["events"][0]["type"] == "workflow.completed"
