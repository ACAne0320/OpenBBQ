from pathlib import Path
import sqlite3
import sys
import types

from fastapi.testclient import TestClient
import pytest

from openbbq.api.app import ApiAppSettings, create_app
from openbbq.application.quickstart import SubtitleJobResult
from openbbq.config.loader import load_project_config
from openbbq.runtime.models import (
    CacheSettings,
    FasterWhisperSettings,
    ModelsSettings,
    ProviderProfile,
    RuntimeDefaults,
    RuntimeSettings,
)
from openbbq.runtime.user_db import UserRuntimeDatabase
from openbbq.storage.models import QuickstartTaskRecord, RunRecord
from openbbq.storage.project_store import ProjectStore
from openbbq.storage.runs import write_run
from tests.helpers import authed_client, write_project_fixture

FASTER_WHISPER_PAYLOAD_FILES = {
    "model.bin": b"base",
    "config.json": b"{}",
    "tokenizer.json": b"tokenizer",
}
FASTER_WHISPER_PAYLOAD_SIZE = sum(len(content) for content in FASTER_WHISPER_PAYLOAD_FILES.values())


def _write_faster_whisper_payload(path: Path) -> int:
    path.mkdir(parents=True, exist_ok=True)
    for filename, content in FASTER_WHISPER_PAYLOAD_FILES.items():
        (path / filename).write_bytes(content)
    return FASTER_WHISPER_PAYLOAD_SIZE


def _patch_valid_quickstart_runtime(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENBBQ_LLM_API_KEY", "sk-test")
    monkeypatch.setattr(
        "openbbq.application.quickstart.load_runtime_settings",
        lambda: RuntimeSettings(
            version=1,
            config_path=tmp_path / "config.toml",
            cache=CacheSettings(root=tmp_path / "cache"),
            defaults=RuntimeDefaults(llm_provider="openai", asr_provider="faster-whisper"),
            providers={
                "openai": ProviderProfile(
                    name="openai",
                    type="openai_compatible",
                    api_key="env:OPENBBQ_LLM_API_KEY",
                    default_chat_model="gpt-4o-mini",
                )
            },
            models=ModelsSettings(
                faster_whisper=FasterWhisperSettings(
                    cache_dir=tmp_path / "fw-cache",
                    default_model="base",
                    default_device="cpu",
                    default_compute_type="int8",
                )
            ),
        ),
    )


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
    assert models_response.json()["data"]["models"][0]["provider"] == "faster-whisper"
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
    cache_root = tmp_path / "cache"
    monkeypatch.setenv("OPENBBQ_CACHE_DIR", str(cache_root))
    client, headers = authed_client(project)
    cache_dir = cache_root / "models" / "faster-whisper"

    defaults = client.put(
        "/runtime/defaults",
        headers=headers,
        json={"llm_provider": "openai-compatible", "asr_provider": "faster-whisper"},
    )
    asr = client.put(
        "/runtime/models/faster-whisper",
        headers=headers,
        json={
            "cache_dir": str(cache_dir),
            "default_model": "small",
            "default_device": "cpu",
            "default_compute_type": "int8",
        },
    )
    settings = client.get("/runtime/settings", headers=headers)
    models = client.get("/runtime/models", headers=headers)

    assert defaults.status_code == 200
    assert defaults.json()["data"]["settings"]["defaults"]["llm_provider"] == "openai-compatible"
    assert asr.status_code == 200
    assert (
        settings.json()["data"]["settings"]["models"]["faster_whisper"]["default_model"] == "small"
    )
    assert models.json()["data"]["models"][0]["model"] == "small"
    assert models.json()["data"]["models"][0]["cache_dir"] == str(cache_dir.resolve())


def test_runtime_models_lists_supported_faster_whisper_sizes(tmp_path, monkeypatch):
    project = write_project_fixture(tmp_path, "text-basic")
    cache_root = tmp_path / "cache"
    cache_dir = cache_root / "models" / "faster-whisper"
    hf_cache_dir = cache_dir / "models--Systran--faster-whisper-base"
    (hf_cache_dir / "refs").mkdir(parents=True)
    (hf_cache_dir / "refs" / "main").write_text("abc123", encoding="utf-8")
    payload_size = _write_faster_whisper_payload(hf_cache_dir / "snapshots" / "abc123")
    (hf_cache_dir / "blobs").mkdir()
    (hf_cache_dir / "blobs" / "unrelated").write_bytes(b"x" * 100)
    monkeypatch.setenv("OPENBBQ_USER_CONFIG", str(tmp_path / "user-config.toml"))
    monkeypatch.setenv("OPENBBQ_CACHE_DIR", str(cache_root))
    client, headers = authed_client(project)

    response = client.get("/runtime/models", headers=headers)

    assert response.status_code == 200
    models = response.json()["data"]["models"]
    assert [model["model"] for model in models] == ["base", "tiny", "small", "medium", "large-v3"]
    base = models[0]
    assert base["provider"] == "faster-whisper"
    assert base["cache_dir"] == str(cache_dir.resolve())
    assert base["present"] is True
    assert base["size_bytes"] == payload_size
    assert all(model["provider"] == "faster-whisper" for model in models)


def test_runtime_models_ignore_incomplete_faster_whisper_cache(tmp_path, monkeypatch):
    project = write_project_fixture(tmp_path, "text-basic")
    cache_root = tmp_path / "cache"
    cache_dir = cache_root / "models" / "faster-whisper"
    payload_size = _write_faster_whisper_payload(cache_dir / "models--Systran--faster-whisper-base")
    small_dir = cache_dir / "models--Systran--faster-whisper-small"
    small_dir.mkdir(parents=True)
    (small_dir / "model.bin").write_bytes(b"partial")
    monkeypatch.setenv("OPENBBQ_USER_CONFIG", str(tmp_path / "user-config.toml"))
    monkeypatch.setenv("OPENBBQ_CACHE_DIR", str(cache_root))
    client, headers = authed_client(project)

    response = client.get("/runtime/models", headers=headers)

    assert response.status_code == 200
    models_by_name = {model["model"]: model for model in response.json()["data"]["models"]}
    assert models_by_name["base"]["present"] is True
    assert models_by_name["base"]["size_bytes"] == payload_size
    assert models_by_name["small"]["present"] is False
    assert models_by_name["small"]["size_bytes"] == 0


def test_runtime_models_ignore_file_faster_whisper_cache_candidate(tmp_path, monkeypatch):
    project = write_project_fixture(tmp_path, "text-basic")
    cache_root = tmp_path / "cache"
    cache_dir = cache_root / "models" / "faster-whisper"
    cache_dir.mkdir(parents=True)
    (cache_dir / "base").write_bytes(b"stray")
    monkeypatch.setenv("OPENBBQ_USER_CONFIG", str(tmp_path / "user-config.toml"))
    monkeypatch.setenv("OPENBBQ_CACHE_DIR", str(cache_root))
    client, headers = authed_client(project)

    response = client.get("/runtime/models", headers=headers)

    assert response.status_code == 200
    base = response.json()["data"]["models"][0]
    assert base["model"] == "base"
    assert base["present"] is False
    assert base["size_bytes"] == 0


def test_runtime_downloads_faster_whisper_model_with_fake_adapter(tmp_path, monkeypatch):
    project = write_project_fixture(tmp_path, "text-basic")
    cache_root = tmp_path / "cache"
    cache_dir = cache_root / "models" / "faster-whisper"
    monkeypatch.setenv("OPENBBQ_USER_CONFIG", str(tmp_path / "user-config.toml"))
    monkeypatch.setenv("OPENBBQ_CACHE_DIR", str(cache_root))
    calls = []

    def fake_download(model, *, cache_dir, device, compute_type, progress=None):
        calls.append(
            {
                "model": model,
                "cache_dir": cache_dir,
                "device": device,
                "compute_type": compute_type,
            }
        )
        model_dir = cache_dir / f"models--Systran--faster-whisper-{model}"
        payload_size = _write_faster_whisper_payload(model_dir)
        if progress is not None:
            progress(percent=100, current_bytes=payload_size, total_bytes=payload_size)

    monkeypatch.setattr("openbbq.application.runtime.download_faster_whisper_model", fake_download)
    client, headers = authed_client(project)

    response = client.post(
        "/runtime/models/faster-whisper/download",
        headers=headers,
        json={"model": "small"},
    )

    assert response.status_code == 200
    job = response.json()["data"]["job"]
    assert job["model"] == "small"
    poll = _poll_download_job(client, headers, job["job_id"])
    assert calls == [
        {
            "model": "small",
            "cache_dir": cache_dir.resolve(),
            "device": "cpu",
            "compute_type": "int8",
        }
    ]
    assert poll.json()["data"]["job"]["model_status"] == {
        "provider": "faster-whisper",
        "model": "small",
        "cache_dir": str(cache_dir.resolve()),
        "present": True,
        "size_bytes": FASTER_WHISPER_PAYLOAD_SIZE,
        "error": None,
    }


def test_runtime_download_returns_completed_job_when_faster_whisper_model_present(
    tmp_path, monkeypatch
):
    project = write_project_fixture(tmp_path, "text-basic")
    cache_root = tmp_path / "cache"
    cache_dir = cache_root / "models" / "faster-whisper"
    model_dir = cache_dir / "models--Systran--faster-whisper-small"
    payload_size = _write_faster_whisper_payload(model_dir)
    monkeypatch.setenv("OPENBBQ_USER_CONFIG", str(tmp_path / "user-config.toml"))
    monkeypatch.setenv("OPENBBQ_CACHE_DIR", str(cache_root))
    calls = []

    def fake_download(model, *, cache_dir, device, compute_type, progress=None):
        calls.append(
            {
                "model": model,
                "cache_dir": cache_dir,
                "device": device,
                "compute_type": compute_type,
                "progress": progress,
            }
        )
        raise AssertionError("download should not be invoked for a present model")

    monkeypatch.setattr("openbbq.application.runtime.download_faster_whisper_model", fake_download)
    client, headers = authed_client(project)

    response = client.post(
        "/runtime/models/faster-whisper/download",
        headers=headers,
        json={"model": "small"},
    )

    assert response.status_code == 200
    job = response.json()["data"]["job"]
    assert job["status"] == "completed"
    assert job["percent"] == 100
    assert job["current_bytes"] == payload_size
    assert job["total_bytes"] == payload_size
    assert job["model_status"]["present"] is True
    assert job["model_status"]["size_bytes"] == payload_size
    assert calls == []

    poll = _poll_download_job(client, headers, job["job_id"])
    assert poll.json()["data"]["job"]["status"] == "completed"
    assert poll.json()["data"]["job"]["percent"] == 100


def test_model_download_job_manager_reports_queued_before_worker_starts(tmp_path):
    from openbbq.runtime.model_download_jobs import ModelDownloadJobManager
    from openbbq.runtime.models import ModelAssetStatus

    manager = ModelDownloadJobManager()
    manager._executor.shutdown(wait=False)
    submitted = []

    class DeferredExecutor:
        def submit(self, fn, *args):
            submitted.append((fn, args))

    manager._executor = DeferredExecutor()

    def worker(progress):
        progress(percent=50, current_bytes=5, total_bytes=10)
        return ModelAssetStatus(
            provider="faster-whisper",
            model="small",
            cache_dir=tmp_path,
            present=True,
            size_bytes=10,
        )

    job = manager.start(provider="faster-whisper", model="small", worker=worker)

    assert job.status == "queued"
    assert manager.get(job.job_id).status == "queued"
    assert len(submitted) == 1

    fn, args = submitted[0]
    fn(*args)

    completed = manager.get(job.job_id)
    assert completed.status == "completed"
    assert completed.percent == 100


def test_faster_whisper_download_adapter_uses_download_utility(tmp_path, monkeypatch):
    from openbbq.runtime.models_assets import download_faster_whisper_model

    huggingface_hub_module = types.ModuleType("huggingface_hub")
    api_calls = []
    snapshot_calls = []
    progress_events = []

    class FakeHfApi:
        def model_info(self, repo_id, *, files_metadata=False):
            api_calls.append({"repo_id": repo_id, "files_metadata": files_metadata})
            return types.SimpleNamespace(
                siblings=tuple(
                    types.SimpleNamespace(rfilename=filename, size=len(content))
                    for filename, content in FASTER_WHISPER_PAYLOAD_FILES.items()
                )
            )

    def fake_snapshot_download(repo_id, **kwargs):
        snapshot_calls.append({"repo_id": repo_id, **kwargs})
        first_progress_bar = kwargs["tqdm_class"](total=2, unit="B")
        first_progress_bar.update(2)
        first_progress_bar.close()
        second_progress_bar = kwargs["tqdm_class"](total=3, unit="B")
        second_progress_bar.update(3)
        second_progress_bar.close()
        return str(cache_dir / "models--Systran--faster-whisper-small")

    huggingface_hub_module.HfApi = FakeHfApi
    huggingface_hub_module.snapshot_download = fake_snapshot_download
    monkeypatch.setitem(sys.modules, "huggingface_hub", huggingface_hub_module)
    cache_dir = tmp_path / "model-cache"

    download_faster_whisper_model(
        "small",
        cache_dir=cache_dir,
        device="cuda",
        compute_type="float16",
        progress=lambda **payload: progress_events.append(payload),
    )

    assert cache_dir.is_dir()
    assert api_calls == [{"repo_id": "Systran/faster-whisper-small", "files_metadata": True}]
    assert snapshot_calls[0]["repo_id"] == "Systran/faster-whisper-small"
    assert snapshot_calls[0]["cache_dir"] == cache_dir
    assert snapshot_calls[0]["allow_patterns"] == [
        "config.json",
        "preprocessor_config.json",
        "model.bin",
        "tokenizer.json",
        "vocabulary.*",
    ]
    assert progress_events[-1] == {
        "percent": 100,
        "current_bytes": FASTER_WHISPER_PAYLOAD_SIZE,
        "total_bytes": FASTER_WHISPER_PAYLOAD_SIZE,
    }
    assert any(event["current_bytes"] == 5 for event in progress_events)


def test_faster_whisper_download_with_unknown_total_does_not_fabricate_percentages(
    tmp_path, monkeypatch
):
    from openbbq.runtime.models_assets import download_faster_whisper_model

    huggingface_hub_module = types.ModuleType("huggingface_hub")
    progress_events = []

    class FakeHfApi:
        def model_info(self, repo_id, *, files_metadata=False):
            return types.SimpleNamespace(
                siblings=(
                    types.SimpleNamespace(rfilename="model.bin", size=None),
                    types.SimpleNamespace(rfilename="config.json", size=None),
                )
            )

    def fake_snapshot_download(repo_id, **kwargs):
        first_progress_bar = kwargs["tqdm_class"](total=2, unit="B")
        first_progress_bar.update(2)
        first_progress_bar.close()
        second_progress_bar = kwargs["tqdm_class"](total=3, unit="B")
        second_progress_bar.update(3)
        second_progress_bar.close()
        return str(tmp_path / "model-cache" / "models--Systran--faster-whisper-small")

    huggingface_hub_module.HfApi = FakeHfApi
    huggingface_hub_module.snapshot_download = fake_snapshot_download
    monkeypatch.setitem(sys.modules, "huggingface_hub", huggingface_hub_module)

    download_faster_whisper_model(
        "small",
        cache_dir=tmp_path / "model-cache",
        device="cuda",
        compute_type="float16",
        progress=lambda **payload: progress_events.append(payload),
    )

    assert progress_events
    assert [event["percent"] for event in progress_events[:-1]] == [0] * (len(progress_events) - 1)
    assert progress_events[-1]["percent"] == 100
    assert any(event["current_bytes"] == 5 for event in progress_events)


def test_faster_whisper_download_with_mixed_size_metadata_treats_total_as_unknown(
    tmp_path, monkeypatch
):
    from openbbq.runtime.models_assets import download_faster_whisper_model

    huggingface_hub_module = types.ModuleType("huggingface_hub")
    progress_events = []

    class FakeHfApi:
        def model_info(self, repo_id, *, files_metadata=False):
            return types.SimpleNamespace(
                siblings=(
                    types.SimpleNamespace(rfilename="model.bin", size=2),
                    types.SimpleNamespace(rfilename="config.json", size=None),
                )
            )

    def fake_snapshot_download(repo_id, **kwargs):
        first_progress_bar = kwargs["tqdm_class"](total=2, unit="B")
        first_progress_bar.update(2)
        first_progress_bar.close()
        second_progress_bar = kwargs["tqdm_class"](total=3, unit="B")
        second_progress_bar.update(3)
        second_progress_bar.close()
        return str(tmp_path / "model-cache" / "models--Systran--faster-whisper-small")

    huggingface_hub_module.HfApi = FakeHfApi
    huggingface_hub_module.snapshot_download = fake_snapshot_download
    monkeypatch.setitem(sys.modules, "huggingface_hub", huggingface_hub_module)

    download_faster_whisper_model(
        "small",
        cache_dir=tmp_path / "model-cache",
        device="cuda",
        compute_type="float16",
        progress=lambda **payload: progress_events.append(payload),
    )

    assert progress_events
    assert [event["percent"] for event in progress_events[:-1]] == [0] * (len(progress_events) - 1)
    assert progress_events[-1] == {
        "percent": 100,
        "current_bytes": 5,
        "total_bytes": None,
    }


def test_runtime_starts_and_polls_faster_whisper_download_job(tmp_path, monkeypatch):
    project = write_project_fixture(tmp_path, "text-basic")
    cache_root = tmp_path / "cache"
    monkeypatch.setenv("OPENBBQ_USER_CONFIG", str(tmp_path / "user-config.toml"))
    monkeypatch.setenv("OPENBBQ_CACHE_DIR", str(cache_root))
    progress_values = [0, 40, 100]

    def fake_download(model, *, cache_dir, device, compute_type, progress=None):
        for percent in progress_values:
            progress(percent=percent, current_bytes=percent, total_bytes=100)
        model_dir = cache_dir / f"models--Systran--faster-whisper-{model}"
        _write_faster_whisper_payload(model_dir)

    monkeypatch.setattr("openbbq.application.runtime.download_faster_whisper_model", fake_download)

    client, headers = authed_client(project)
    start = client.post(
        "/runtime/models/faster-whisper/download",
        headers=headers,
        json={"model": "small"},
    )
    assert start.status_code == 200
    job = start.json()["data"]["job"]
    assert job["model"] == "small"
    assert job["status"] in {"queued", "running", "completed"}

    poll = _poll_download_job(client, headers, job["job_id"])
    assert poll.status_code == 200
    assert poll.json()["data"]["job"]["percent"] == 100
    assert poll.json()["data"]["job"]["status"] == "completed"


def test_runtime_download_job_reports_failure(tmp_path, monkeypatch):
    project = write_project_fixture(tmp_path, "text-basic")
    cache_root = tmp_path / "cache"
    monkeypatch.setenv("OPENBBQ_USER_CONFIG", str(tmp_path / "user-config.toml"))
    monkeypatch.setenv("OPENBBQ_CACHE_DIR", str(cache_root))

    def fake_download(model, *, cache_dir, device, compute_type, progress=None):
        progress(percent=10, current_bytes=10, total_bytes=100)
        raise RuntimeError("network failed")

    monkeypatch.setattr("openbbq.application.runtime.download_faster_whisper_model", fake_download)

    client, headers = authed_client(project)
    start = client.post(
        "/runtime/models/faster-whisper/download",
        headers=headers,
        json={"model": "small"},
    )
    job = start.json()["data"]["job"]

    poll = _poll_download_job(client, headers, job["job_id"])
    assert poll.json()["data"]["job"]["status"] == "failed"
    assert poll.json()["data"]["job"]["error"] == "network failed"


def _poll_download_job(client, headers, job_id: str):
    import time

    response = None
    for _ in range(20):
        response = client.get(f"/runtime/models/faster-whisper/downloads/{job_id}", headers=headers)
        status = response.json()["data"]["job"]["status"]
        if status in {"completed", "failed"}:
            return response
        time.sleep(0.01)
    assert response is not None
    return response


def test_runtime_download_rejects_unsupported_faster_whisper_model(tmp_path, monkeypatch):
    project = write_project_fixture(tmp_path, "text-basic")
    cache_root = tmp_path / "cache"
    monkeypatch.setenv("OPENBBQ_USER_CONFIG", str(tmp_path / "user-config.toml"))
    monkeypatch.setenv("OPENBBQ_CACHE_DIR", str(cache_root))
    client, headers = authed_client(project, raise_server_exceptions=False)

    response = client.post(
        "/runtime/models/faster-whisper/download",
        headers=headers,
        json={"model": "unknown-size"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert "unknown-size" in response.json()["error"]["message"]


def test_runtime_faster_whisper_rejects_unsupported_default_model(tmp_path, monkeypatch):
    project = write_project_fixture(tmp_path, "text-basic")
    cache_root = tmp_path / "cache"
    monkeypatch.setenv("OPENBBQ_USER_CONFIG", str(tmp_path / "user-config.toml"))
    monkeypatch.setenv("OPENBBQ_CACHE_DIR", str(cache_root))
    client, headers = authed_client(project)
    valid_body = {
        "cache_dir": str(cache_root / "models" / "faster-whisper"),
        "default_model": "small",
        "default_device": "cpu",
        "default_compute_type": "int8",
    }
    valid = client.put(
        "/runtime/models/faster-whisper",
        headers=headers,
        json=valid_body,
    )

    rejected = client.put(
        "/runtime/models/faster-whisper",
        headers=headers,
        json=valid_body | {"default_model": "unknown-size"},
    )
    settings = client.get("/runtime/settings", headers=headers)

    assert valid.status_code == 200
    assert rejected.status_code == 422
    assert rejected.json()["error"]["code"] == "validation_error"
    assert "unknown-size" in rejected.json()["error"]["message"]
    assert (
        settings.json()["data"]["settings"]["models"]["faster_whisper"]["default_model"] == "small"
    )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("default_model", ""),
        ("default_device", "   "),
        ("default_compute_type", "\t"),
    ),
)
def test_runtime_faster_whisper_rejects_blank_settings(tmp_path, monkeypatch, field, value):
    project = write_project_fixture(tmp_path, "text-basic")
    monkeypatch.setenv("OPENBBQ_USER_CONFIG", str(tmp_path / "user-config.toml"))
    cache_root = tmp_path / "cache"
    monkeypatch.setenv("OPENBBQ_CACHE_DIR", str(cache_root))
    client, headers = authed_client(project)
    valid_body = {
        "cache_dir": str(cache_root / "models" / "faster-whisper"),
        "default_model": "small",
        "default_device": "cpu",
        "default_compute_type": "int8",
    }
    valid = client.put(
        "/runtime/models/faster-whisper",
        headers=headers,
        json=valid_body,
    )

    rejected = client.put(
        "/runtime/models/faster-whisper",
        headers=headers,
        json=valid_body | {field: value},
    )
    settings = client.get("/runtime/settings", headers=headers)

    assert valid.status_code == 200
    assert rejected.status_code == 422
    assert rejected.json()["error"]["code"] == "validation_error"
    assert settings.status_code == 200
    assert (
        settings.json()["data"]["settings"]["models"]["faster_whisper"][field] == valid_body[field]
    )


def test_runtime_faster_whisper_rejects_cache_dir_outside_runtime_cache_root(tmp_path, monkeypatch):
    project = write_project_fixture(tmp_path, "text-basic")
    cache_root = tmp_path / "cache"
    monkeypatch.setenv("OPENBBQ_USER_CONFIG", str(tmp_path / "user-config.toml"))
    monkeypatch.setenv("OPENBBQ_CACHE_DIR", str(cache_root))
    client, headers = authed_client(project, raise_server_exceptions=False)
    valid_body = {
        "cache_dir": str(cache_root / "models" / "faster-whisper"),
        "default_model": "small",
        "default_device": "cpu",
        "default_compute_type": "int8",
    }
    valid = client.put(
        "/runtime/models/faster-whisper",
        headers=headers,
        json=valid_body,
    )

    rejected = client.put(
        "/runtime/models/faster-whisper",
        headers=headers,
        json=valid_body | {"cache_dir": str(tmp_path / "outside-model-cache")},
    )
    settings = client.get("/runtime/settings", headers=headers)

    assert valid.status_code == 200
    assert rejected.status_code == 422
    assert rejected.json()["error"]["code"] == "validation_error"
    assert "cache.root" in rejected.json()["error"]["message"]
    assert settings.json()["data"]["settings"]["models"]["faster_whisper"]["cache_dir"] == str(
        (cache_root / "models" / "faster-whisper").resolve()
    )


def test_runtime_defaults_invalid_provider_name_returns_validation_error(tmp_path, monkeypatch):
    project = write_project_fixture(tmp_path, "text-basic")
    monkeypatch.setenv("OPENBBQ_USER_CONFIG", str(tmp_path / "user-config.toml"))
    client, headers = authed_client(project, raise_server_exceptions=False)

    response = client.put(
        "/runtime/defaults",
        headers=headers,
        json={"llm_provider": "not valid", "asr_provider": "faster-whisper"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


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
    _patch_valid_quickstart_runtime(monkeypatch, tmp_path)

    def fake_local_job(request):
        assert request.correct_transcript is False
        return SubtitleJobResult(
            generated_project_root=tmp_path / "generated-local",
            generated_config_path=tmp_path / "generated-local" / "openbbq.yaml",
            workflow_id="local-to-srt",
            run_id="run_local",
            output_path=request.output_path,
            source_artifact_id="art_source",
            provider=request.provider or "openai",
            model=request.model,
            asr_model=request.asr_model or "base",
            asr_device=request.asr_device or "cpu",
            asr_compute_type=request.asr_compute_type or "int8",
        )

    def fake_youtube_job(request):
        return SubtitleJobResult(
            generated_project_root=tmp_path / "generated-youtube",
            generated_config_path=tmp_path / "generated-youtube" / "openbbq.yaml",
            workflow_id="youtube-to-srt",
            run_id="run_youtube",
            output_path=request.output_path,
            source_artifact_id=None,
            provider=request.provider or "openai",
            model=request.model,
            asr_model=request.asr_model or "base",
            asr_device=request.asr_device or "cpu",
            asr_compute_type=request.asr_compute_type or "int8",
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
            "correct_transcript": False,
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


def test_quickstart_subtitle_template_route_returns_packaged_workflow_steps(tmp_path):
    project = write_project_fixture(tmp_path, "text-basic")
    client, headers = authed_client(project)

    local = client.get(
        "/quickstart/subtitle/template",
        headers=headers,
        params={"source_kind": "local_file"},
    )
    remote = client.get(
        "/quickstart/subtitle/template",
        headers=headers,
        params={"source_kind": "remote_url", "url": "https://example.test/watch"},
    )

    assert local.status_code == 200
    local_data = local.json()["data"]
    assert local_data["template_id"] == "local-subtitle"
    assert local_data["workflow_id"] == "local-to-srt"
    assert [step["id"] for step in local_data["steps"]] == [
        "extract_audio",
        "transcribe",
        "correct",
        "segment",
        "translate",
        "subtitle",
    ]
    assert local_data["steps"][0]["tool_ref"] == "ffmpeg.extract_audio"
    assert local_data["steps"][2]["status"] == "enabled"
    assert local_data["steps"][4]["parameters"] == [
        {
            "kind": "text",
            "key": "source_lang",
            "label": "Source language",
            "value": "en",
        },
        {
            "kind": "text",
            "key": "target_lang",
            "label": "Target language",
            "value": "zh",
        },
        {
            "kind": "text",
            "key": "temperature",
            "label": "Temperature",
            "value": "0",
        },
    ]

    assert remote.status_code == 200
    remote_data = remote.json()["data"]
    assert remote_data["template_id"] == "youtube-subtitle"
    assert remote_data["workflow_id"] == "youtube-to-srt"
    assert remote_data["steps"][0]["id"] == "download"
    assert remote_data["steps"][0]["tool_ref"] == "remote_video.download"
    assert remote_data["steps"][0]["parameters"][0] == {
        "kind": "text",
        "key": "url",
        "label": "URL",
        "value": "https://example.test/watch",
    }


def test_quickstart_subtitle_route_persists_task_history(tmp_path, monkeypatch):
    project = write_project_fixture(tmp_path, "text-basic")
    _patch_valid_quickstart_runtime(monkeypatch, tmp_path)
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
            provider=request.provider or "openai",
            model=request.model,
            asr_model=request.asr_model or "base",
            asr_device=request.asr_device or "cpu",
            asr_compute_type=request.asr_compute_type or "int8",
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


def test_quickstart_task_history_records_resolved_runtime_defaults(tmp_path, monkeypatch):
    project = write_project_fixture(tmp_path, "text-basic")
    user_db_path = tmp_path / "user.db"
    monkeypatch.setenv("OPENBBQ_LLM_API_KEY", "sk-test")
    monkeypatch.setattr(
        "openbbq.application.quickstart.load_runtime_settings",
        lambda: RuntimeSettings(
            version=1,
            config_path=tmp_path / "config.toml",
            cache=CacheSettings(root=tmp_path / "cache"),
            defaults=RuntimeDefaults(
                llm_provider="openai-compatible",
                asr_provider="faster-whisper",
            ),
            providers={
                "openai-compatible": ProviderProfile(
                    name="openai-compatible",
                    type="openai_compatible",
                    api_key="env:OPENBBQ_LLM_API_KEY",
                    default_chat_model="gpt-4o-mini",
                )
            },
            models=ModelsSettings(
                faster_whisper=FasterWhisperSettings(
                    cache_dir=tmp_path / "fw-cache",
                    default_model="small",
                    default_device="cpu",
                    default_compute_type="int8",
                )
            ),
        ),
    )
    client = TestClient(
        create_app(ApiAppSettings(project_root=project, token="token", user_db_path=user_db_path))
    )
    headers = {"Authorization": "Bearer token"}

    body = {
        "url": "https://www.youtube.com/watch?v=demo",
        "source_lang": "en",
        "target_lang": "zh",
        "quality": "best",
    }

    response = client.post(
        "/quickstart/subtitle/youtube",
        headers=headers,
        json=body,
    )
    data = response.json()["data"]
    history = UserRuntimeDatabase(user_db_path).read_quickstart_task(data["run_id"])
    cached = client.post(
        "/quickstart/subtitle/youtube",
        headers=headers,
        json=body,
    )

    assert response.status_code == 200
    assert data["provider"] == "openai-compatible"
    assert data["model"] == "gpt-4o-mini"
    assert data["asr_model"] == "small"
    assert data["asr_device"] == "cpu"
    assert data["asr_compute_type"] == "int8"
    assert history is not None
    assert history.provider == "openai-compatible"
    assert history.model == "gpt-4o-mini"
    assert history.asr_model == "small"
    assert history.asr_device == "cpu"
    assert history.asr_compute_type == "int8"
    assert cached.status_code == 200
    assert cached.json()["data"] == data


def test_quickstart_cache_key_uses_current_resolved_runtime_defaults(tmp_path, monkeypatch):
    project = write_project_fixture(tmp_path, "text-basic")
    user_db_path = tmp_path / "user.db"
    default_provider = {"name": "provider-a", "model": "model-a"}
    monkeypatch.setenv("OPENBBQ_LLM_API_KEY", "sk-test")

    def runtime_settings():
        provider_name = default_provider["name"]
        return RuntimeSettings(
            version=1,
            config_path=tmp_path / "config.toml",
            cache=CacheSettings(root=tmp_path / "cache"),
            defaults=RuntimeDefaults(
                llm_provider=provider_name,
                asr_provider="faster-whisper",
            ),
            providers={
                provider_name: ProviderProfile(
                    name=provider_name,
                    type="openai_compatible",
                    api_key="env:OPENBBQ_LLM_API_KEY",
                    default_chat_model=default_provider["model"],
                )
            },
            models=ModelsSettings(
                faster_whisper=FasterWhisperSettings(
                    cache_dir=tmp_path / "fw-cache",
                    default_model="small",
                    default_device="cpu",
                    default_compute_type="int8",
                )
            ),
        )

    monkeypatch.setattr(
        "openbbq.application.quickstart.load_runtime_settings",
        runtime_settings,
    )
    client = TestClient(
        create_app(ApiAppSettings(project_root=project, token="token", user_db_path=user_db_path))
    )
    headers = {"Authorization": "Bearer token"}
    body = {
        "url": "https://www.youtube.com/watch?v=demo",
        "source_lang": "en",
        "target_lang": "zh",
        "quality": "best",
    }

    first = client.post("/quickstart/subtitle/youtube", headers=headers, json=body)
    default_provider.update({"name": "provider-b", "model": "model-b"})
    second = client.post("/quickstart/subtitle/youtube", headers=headers, json=body)
    third = client.post("/quickstart/subtitle/youtube", headers=headers, json=body)
    tasks = UserRuntimeDatabase(user_db_path).list_quickstart_tasks()

    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 200
    assert first.json()["data"]["provider"] == "provider-a"
    assert first.json()["data"]["model"] == "model-a"
    assert second.json()["data"]["provider"] == "provider-b"
    assert second.json()["data"]["model"] == "model-b"
    assert second.json()["data"]["run_id"] != first.json()["data"]["run_id"]
    assert third.json()["data"]["run_id"] == second.json()["data"]["run_id"]
    assert len(tasks) == 2
    assert len({task.cache_key for task in tasks}) == 2


def test_quickstart_cached_task_reuse_does_not_require_live_secret(tmp_path, monkeypatch):
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

    def runtime_settings():
        return RuntimeSettings(
            version=1,
            config_path=tmp_path / "config.toml",
            cache=CacheSettings(root=tmp_path / "cache"),
            defaults=RuntimeDefaults(
                llm_provider="openai-compatible",
                asr_provider="faster-whisper",
            ),
            providers={
                "openai-compatible": ProviderProfile(
                    name="openai-compatible",
                    type="openai_compatible",
                    api_key="env:OPENBBQ_LLM_API_KEY",
                    default_chat_model="gpt-4o-mini",
                )
            },
            models=ModelsSettings(
                faster_whisper=FasterWhisperSettings(
                    cache_dir=tmp_path / "fw-cache",
                    default_model="small",
                    default_device="cpu",
                    default_compute_type="int8",
                )
            ),
        )

    def fake_youtube_job(request):
        calls.append(request)
        return SubtitleJobResult(
            generated_project_root=generated_project,
            generated_config_path=generated_config.config_path,
            workflow_id="text-demo",
            run_id="run_generated",
            output_path=request.output_path,
            source_artifact_id=None,
            provider=request.provider,
            model=request.model,
            asr_model=request.asr_model,
            asr_device=request.asr_device,
            asr_compute_type=request.asr_compute_type,
        )

    monkeypatch.setattr(
        "openbbq.application.quickstart.load_runtime_settings",
        runtime_settings,
    )
    monkeypatch.setattr(
        "openbbq.api.routes.quickstart.create_youtube_subtitle_job", fake_youtube_job
    )
    monkeypatch.setenv("OPENBBQ_LLM_API_KEY", "sk-test")
    user_db_path = tmp_path / "user.db"
    client = TestClient(
        create_app(ApiAppSettings(project_root=project, token="token", user_db_path=user_db_path))
    )
    headers = {"Authorization": "Bearer token"}
    body = {
        "url": "https://www.youtube.com/watch?v=demo",
        "source_lang": "en",
        "target_lang": "zh",
        "quality": "best",
    }

    first = client.post("/quickstart/subtitle/youtube", headers=headers, json=body)
    monkeypatch.delenv("OPENBBQ_LLM_API_KEY", raising=False)
    second = client.post("/quickstart/subtitle/youtube", headers=headers, json=body)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["data"] == first.json()["data"]
    assert len(calls) == 1


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
            provider=request.provider or "openai",
            model=request.model,
            asr_model=request.asr_model or "base",
            asr_device=request.asr_device or "cpu",
            asr_compute_type=request.asr_compute_type or "int8",
        )

    monkeypatch.setattr(
        "openbbq.api.routes.quickstart.create_youtube_subtitle_job", fake_youtube_job
    )
    _patch_valid_quickstart_runtime(monkeypatch, tmp_path)
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
    _patch_valid_quickstart_runtime(monkeypatch, tmp_path)
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
            provider=request.provider or "openai",
            model=request.model,
            asr_model=request.asr_model or "base",
            asr_device=request.asr_device or "cpu",
            asr_compute_type=request.asr_compute_type or "int8",
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
    _patch_valid_quickstart_runtime(monkeypatch, tmp_path)
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
            provider=request.provider or "openai",
            model=request.model,
            asr_model=request.asr_model or "base",
            asr_device=request.asr_device or "cpu",
            asr_compute_type=request.asr_compute_type or "int8",
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
