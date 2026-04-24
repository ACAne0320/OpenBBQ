from pathlib import Path

from openbbq.config.loader import load_project_config
from openbbq.plugins.registry import discover_plugins
from openbbq.runtime.doctor import DoctorProbes, check_workflow
from openbbq.runtime.models import (
    CacheSettings,
    FasterWhisperSettings,
    ModelsSettings,
    ProviderProfile,
    RuntimeSettings,
)


def _runtime_settings(tmp_path):
    return RuntimeSettings(
        version=1,
        config_path=tmp_path / "config.toml",
        cache=CacheSettings(root=tmp_path / "cache"),
        providers={
            "openai": ProviderProfile(
                name="openai",
                type="openai_compatible",
                api_key="env:OPENBBQ_LLM_API_KEY",
                default_chat_model="gpt-4o-mini",
            )
        },
        models=ModelsSettings(
            faster_whisper=FasterWhisperSettings(cache_dir=tmp_path / "cache/models/fw")
        ),
    )


def _runtime_settings_without_providers(tmp_path):
    return RuntimeSettings(
        version=1,
        config_path=tmp_path / "config.toml",
        cache=CacheSettings(root=tmp_path / "cache"),
        providers={},
        models=ModelsSettings(
            faster_whisper=FasterWhisperSettings(cache_dir=tmp_path / "cache/models/fw")
        ),
    )


def _write_project(tmp_path, fixture_name: str) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    source = Path(f"tests/fixtures/projects/{fixture_name}/openbbq.yaml").read_text(
        encoding="utf-8"
    )
    (project / "openbbq.yaml").write_text(source, encoding="utf-8")
    return project


def test_doctor_reports_missing_llm_secret_for_translation_workflow(tmp_path):
    project = _write_project(tmp_path, "local-video-corrected-translate-subtitle")
    config = load_project_config(project)
    registry = discover_plugins(config.plugin_paths)
    probes = DoctorProbes(
        env={},
        which=lambda name: "/usr/bin/ffmpeg" if name == "ffmpeg" else None,
        importable=lambda name: True,
        path_writable=lambda path: True,
    )

    result = check_workflow(
        config=config,
        registry=registry,
        workflow_id="local-video-corrected-translate-subtitle",
        settings=_runtime_settings(tmp_path),
        probes=probes,
    )

    failed = {check.id: check for check in result if check.status == "failed"}
    assert "provider.openai.api_key" in failed


def test_doctor_reports_missing_named_provider_for_translation_workflow(tmp_path):
    project = _write_project(tmp_path, "local-video-corrected-translate-subtitle")
    config = load_project_config(project)
    registry = discover_plugins(config.plugin_paths)
    probes = DoctorProbes(
        env={"OPENBBQ_LLM_API_KEY": "sk-legacy"},
        which=lambda name: "/usr/bin/ffmpeg" if name == "ffmpeg" else None,
        importable=lambda name: True,
        path_writable=lambda path: True,
    )

    result = check_workflow(
        config=config,
        registry=registry,
        workflow_id="local-video-corrected-translate-subtitle",
        settings=_runtime_settings_without_providers(tmp_path),
        probes=probes,
    )

    failed = {check.id: check for check in result if check.status == "failed"}
    assert "provider.openai.configured" in failed


def test_doctor_reports_missing_ffmpeg_for_media_workflow(tmp_path):
    project = _write_project(tmp_path, "local-video-subtitle")
    config = load_project_config(project)
    registry = discover_plugins(config.plugin_paths)
    probes = DoctorProbes(
        env={},
        which=lambda name: None,
        importable=lambda name: True,
        path_writable=lambda path: True,
    )

    result = check_workflow(
        config=config,
        registry=registry,
        workflow_id="local-video-subtitle",
        settings=_runtime_settings(tmp_path),
        probes=probes,
    )

    failed = {check.id: check for check in result if check.status == "failed"}
    assert "binary.ffmpeg" in failed


def test_doctor_passes_writable_model_cache(tmp_path):
    project = _write_project(tmp_path, "local-video-subtitle")
    config = load_project_config(project)
    registry = discover_plugins(config.plugin_paths)
    probes = DoctorProbes(
        env={"OPENBBQ_LLM_API_KEY": "sk-test"},
        which=lambda name: "/usr/bin/ffmpeg",
        importable=lambda name: True,
        path_writable=lambda path: True,
    )

    result = check_workflow(
        config=config,
        registry=registry,
        workflow_id="local-video-subtitle",
        settings=_runtime_settings(tmp_path),
        probes=probes,
    )

    statuses = {check.id: check.status for check in result}
    assert statuses["model.faster_whisper.cache_writable"] == "passed"
