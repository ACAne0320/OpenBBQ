from importlib import resources

import pytest
import yaml

from openbbq.application.quickstart import (
    LocalSubtitleJobRequest,
    YouTubeSubtitleJobRequest,
    create_local_subtitle_job,
    create_youtube_subtitle_job,
    write_local_subtitle_workflow,
    write_youtube_subtitle_workflow,
)
from openbbq.application.quickstart_workflows import (
    subtitle_workflow_template_for_source,
    write_local_subtitle_workflow as write_local_subtitle_workflow_direct,
    write_youtube_subtitle_workflow as write_youtube_subtitle_workflow_direct,
)
from openbbq.errors import ValidationError
from openbbq.runtime.models import (
    CacheSettings,
    FasterWhisperSettings,
    ModelsSettings,
    ProviderProfile,
    RuntimeDefaults,
    RuntimeSettings,
)
from openbbq.storage.models import RunRecord


def test_youtube_workflow_template_is_packaged_as_workflow_dsl():
    template = (
        resources.files("openbbq.workflow_templates.youtube_subtitle")
        .joinpath("openbbq.yaml")
        .read_text(encoding="utf-8")
    )

    assert "workflows:" in template
    assert "youtube-to-srt:" in template
    assert "tool_ref: remote_video.download" in template
    assert "tool_ref: translation.translate" in template


def test_quickstart_re_exports_template_constants_for_compatibility():
    from openbbq.application.quickstart import (
        LOCAL_SUBTITLE_TEMPLATE_NAME,
        LOCAL_SUBTITLE_TEMPLATE_PACKAGE,
        YOUTUBE_SUBTITLE_TEMPLATE_NAME,
        YOUTUBE_SUBTITLE_TEMPLATE_PACKAGE,
    )

    assert YOUTUBE_SUBTITLE_TEMPLATE_PACKAGE == "openbbq.workflow_templates.youtube_subtitle"
    assert YOUTUBE_SUBTITLE_TEMPLATE_NAME == "openbbq.yaml"
    assert LOCAL_SUBTITLE_TEMPLATE_PACKAGE == "openbbq.workflow_templates.local_subtitle"
    assert LOCAL_SUBTITLE_TEMPLATE_NAME == "openbbq.yaml"


def test_subtitle_template_exposes_segment_profile_as_select():
    template = subtitle_workflow_template_for_source(source_kind="local_file")
    steps = {step["id"]: step for step in template["steps"]}

    profile = next(
        parameter for parameter in steps["segment"]["parameters"] if parameter["key"] == "profile"
    )

    assert profile == {
        "kind": "select",
        "key": "profile",
        "label": "Profile",
        "value": "default",
        "options": ("default", "readable", "dense", "short_form"),
    }


def test_direct_youtube_workflow_generation_renders_expected_config(tmp_path):
    generated = write_youtube_subtitle_workflow_direct(
        workspace_root=tmp_path,
        url="https://www.youtube.com/watch?v=direct",
        source_lang="en",
        target_lang="zh-Hans",
        provider="openai",
        model=None,
        asr_model="tiny",
        asr_device="cpu",
        asr_compute_type="int8",
        quality="best",
        auth="auto",
        browser=None,
        browser_profile=None,
        run_id="youtube-direct",
    )

    config = yaml.safe_load(generated.config_path.read_text(encoding="utf-8"))
    steps = _workflow_steps(config, "youtube-to-srt")

    assert generated.project_root == (
        tmp_path / ".openbbq" / "generated" / "youtube-subtitle" / "youtube-direct"
    )
    assert generated.config_path == generated.project_root / "openbbq.yaml"
    assert generated.workflow_id == "youtube-to-srt"
    assert generated.run_id == "youtube-direct"
    assert config["storage"] == {
        "root": "../../../r/youtube-direct",
        "artifacts": "../../../a/youtube-direct",
        "state": "../../../r/youtube-direct/s",
    }

    download = steps["download"]["parameters"]
    assert download["url"] == "https://www.youtube.com/watch?v=direct"
    assert download["quality"] == "best"
    assert download["auth"] == "auto"
    assert "browser" not in download
    assert "browser_profile" not in download

    transcribe = steps["transcribe"]["parameters"]
    assert transcribe["model"] == "tiny"
    assert transcribe["device"] == "cpu"
    assert transcribe["compute_type"] == "int8"
    assert transcribe["language"] == "en"

    correction = steps["correct"]["parameters"]
    assert correction["provider"] == "openai"
    assert correction["source_lang"] == "en"
    assert "model" not in correction

    translation = steps["translate"]["parameters"]
    assert translation["provider"] == "openai"
    assert translation["source_lang"] == "en"
    assert translation["target_lang"] == "zh-Hans"
    assert "model" not in translation


def test_direct_local_workflow_generation_renders_expected_config(tmp_path):
    generated = write_local_subtitle_workflow_direct(
        workspace_root=tmp_path,
        video_selector="project.art_source_video",
        source_lang="ja",
        target_lang="en",
        provider="openai",
        model="gpt-4.1-mini",
        asr_model="small",
        asr_device="cuda",
        asr_compute_type="float16",
        run_id="local-direct",
    )

    config = yaml.safe_load(generated.config_path.read_text(encoding="utf-8"))
    steps = _workflow_steps(config, "local-to-srt")

    assert generated.project_root == (
        tmp_path / ".openbbq" / "generated" / "local-subtitle" / "local-direct"
    )
    assert generated.config_path == generated.project_root / "openbbq.yaml"
    assert generated.workflow_id == "local-to-srt"
    assert generated.run_id == "local-direct"
    assert config["storage"] == {
        "root": "../../../r/local-direct",
        "artifacts": "../../../a/local-direct",
        "state": "../../../r/local-direct/s",
    }
    assert steps["extract_audio"]["inputs"]["video"] == "project.art_source_video"

    transcribe = steps["transcribe"]["parameters"]
    assert transcribe["model"] == "small"
    assert transcribe["device"] == "cuda"
    assert transcribe["compute_type"] == "float16"
    assert transcribe["language"] == "ja"

    correction = steps["correct"]["parameters"]
    assert correction["provider"] == "openai"
    assert correction["source_lang"] == "ja"
    assert correction["model"] == "gpt-4.1-mini"

    translation = steps["translate"]["parameters"]
    assert translation["provider"] == "openai"
    assert translation["source_lang"] == "ja"
    assert translation["target_lang"] == "en"
    assert translation["model"] == "gpt-4.1-mini"


def test_direct_local_workflow_generation_can_skip_correction(tmp_path):
    generated = write_local_subtitle_workflow_direct(
        workspace_root=tmp_path,
        video_selector="project.art_source_video",
        source_lang="ja",
        target_lang="en",
        provider="openai",
        model="gpt-4.1-mini",
        asr_model="small",
        asr_device="cuda",
        asr_compute_type="float16",
        correct_transcript=False,
        run_id="local-direct",
    )

    config = yaml.safe_load(generated.config_path.read_text(encoding="utf-8"))
    workflow = config["workflows"]["local-to-srt"]
    steps = _workflow_steps(config, "local-to-srt")

    assert [step["id"] for step in workflow["steps"]] == [
        "extract_audio",
        "transcribe",
        "segment",
        "translate",
        "subtitle",
    ]
    assert steps["segment"]["inputs"]["transcript"] == "transcribe.transcript"


def test_direct_local_workflow_generation_applies_segment_parameters(tmp_path):
    generated = write_local_subtitle_workflow_direct(
        workspace_root=tmp_path,
        video_selector="project.art_source_video",
        source_lang="ja",
        target_lang="en",
        provider="openai",
        model="gpt-4.1-mini",
        asr_model="small",
        asr_device="cuda",
        asr_compute_type="float16",
        segment_parameters={
            "profile": "readable",
            "merge_short_segments": "true",
            "max_chars_total": "64",
        },
        run_id="local-direct",
    )

    config = yaml.safe_load(generated.config_path.read_text(encoding="utf-8"))
    steps = _workflow_steps(config, "local-to-srt")

    segment = steps["segment"]["parameters"]
    assert segment["profile"] == "readable"
    assert segment["merge_short_segments"] is True
    assert segment["max_chars_total"] == 64


def test_direct_local_workflow_generation_inserts_extra_workflow_steps(tmp_path):
    generated = write_local_subtitle_workflow_direct(
        workspace_root=tmp_path,
        video_selector="project.art_source_video",
        source_lang="ja",
        target_lang="en",
        provider="openai",
        model="gpt-4.1-mini",
        asr_model="small",
        asr_device="cuda",
        asr_compute_type="float16",
        extra_steps=(
            {
                "id": "translation_qa",
                "name": "Translation QA",
                "tool_ref": "translation.qa",
                "inputs": {"translation": "translate.translation"},
                "outputs": [{"name": "qa", "type": "translation_qa"}],
                "parameters": {"max_lines": 2},
            },
        ),
        run_id="local-direct",
    )

    config = yaml.safe_load(generated.config_path.read_text(encoding="utf-8"))
    workflow = config["workflows"]["local-to-srt"]
    steps = _workflow_steps(config, "local-to-srt")

    assert [step["id"] for step in workflow["steps"]] == [
        "extract_audio",
        "transcribe",
        "correct",
        "segment",
        "translate",
        "translation_qa",
        "subtitle",
    ]
    assert steps["translation_qa"] == {
        "id": "translation_qa",
        "name": "Translation QA",
        "tool_ref": "translation.qa",
        "inputs": {"translation": "translate.translation"},
        "outputs": [{"name": "qa", "type": "translation_qa"}],
        "parameters": {"max_lines": 2},
        "on_error": "abort",
        "max_retries": 0,
    }


def test_direct_local_workflow_generation_applies_step_order(tmp_path):
    generated = write_local_subtitle_workflow_direct(
        workspace_root=tmp_path,
        video_selector="project.art_source_video",
        source_lang="ja",
        target_lang="en",
        provider="openai",
        model="gpt-4.1-mini",
        asr_model="small",
        asr_device="cuda",
        asr_compute_type="float16",
        extra_steps=(
            {
                "id": "translation_qa",
                "name": "Translation QA",
                "tool_ref": "translation.qa",
                "inputs": {"translation": "translate.translation"},
                "outputs": [{"name": "qa", "type": "translation_qa"}],
                "parameters": {"max_lines": 2},
            },
        ),
        step_order=(
            "extract_audio",
            "transcribe",
            "correct",
            "segment",
            "translate",
            "subtitle",
            "translation_qa",
        ),
        run_id="local-direct",
    )

    config = yaml.safe_load(generated.config_path.read_text(encoding="utf-8"))
    workflow = config["workflows"]["local-to-srt"]

    assert [step["id"] for step in workflow["steps"]][-2:] == ["subtitle", "translation_qa"]


def _workflow_steps(config, workflow_id):
    return {step["id"]: step for step in config["workflows"][workflow_id]["steps"]}


def _runtime_settings(tmp_path, *, llm_provider="openai-compatible"):
    return RuntimeSettings(
        version=1,
        config_path=tmp_path / "config.toml",
        cache=CacheSettings(root=tmp_path / "cache"),
        defaults=RuntimeDefaults(
            llm_provider=llm_provider,
            asr_provider="faster-whisper",
        ),
        providers={
            llm_provider: ProviderProfile(
                name=llm_provider,
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


def test_youtube_workflow_generation_can_create_isolated_jobs(tmp_path):
    first = write_youtube_subtitle_workflow(
        workspace_root=tmp_path,
        url="https://www.youtube.com/watch?v=one",
        source_lang="en",
        target_lang="zh",
        provider="openai",
        model=None,
        asr_model="tiny",
        asr_device="cpu",
        asr_compute_type="int8",
        quality="best",
        auth="auto",
        browser=None,
        browser_profile=None,
        run_id="job-one",
    )
    second = write_youtube_subtitle_workflow(
        workspace_root=tmp_path,
        url="https://www.youtube.com/watch?v=two",
        source_lang="en",
        target_lang="ja",
        provider="openai",
        model=None,
        asr_model="tiny",
        asr_device="cpu",
        asr_compute_type="int8",
        quality="best",
        auth="auto",
        browser=None,
        browser_profile=None,
        run_id="job-two",
    )

    assert first.project_root != second.project_root
    assert "watch?v=one" in first.config_path.read_text(encoding="utf-8")
    assert "watch?v=two" in second.config_path.read_text(encoding="utf-8")


def test_local_workflow_generation_uses_imported_video_selector(tmp_path):
    generated = write_local_subtitle_workflow(
        workspace_root=tmp_path,
        video_selector="project.art_source_video",
        source_lang="en",
        target_lang="zh",
        provider="openai",
        model=None,
        asr_model="tiny",
        asr_device="cpu",
        asr_compute_type="int8",
        run_id="local-job",
    )

    rendered = generated.config_path.read_text(encoding="utf-8")

    assert generated.workflow_id == "local-to-srt"
    assert "local video to translated SRT" in rendered
    assert "video: project.art_source_video" in rendered
    assert "provider: openai" in rendered
    assert "target_lang: zh" in rendered


def test_local_subtitle_job_imports_video_and_starts_run(tmp_path, monkeypatch):
    video = tmp_path / "source.mp4"
    video.write_bytes(b"fake-video")
    captured = {}
    monkeypatch.setenv("OPENBBQ_LLM_API_KEY", "sk-test")
    monkeypatch.setattr(
        "openbbq.application.quickstart.load_runtime_settings",
        lambda: _runtime_settings(tmp_path, llm_provider="openai"),
    )
    monkeypatch.setattr("openbbq.application.quickstart_workflows._new_run_id", lambda: "r")

    def fake_create_run(request, *, execute_inline=False):
        captured["request"] = request
        captured["execute_inline"] = execute_inline
        return RunRecord(
            id="run_local",
            workflow_id=request.workflow_id,
            mode="start",
            status="queued",
            project_root=request.project_root,
            config_path=request.config_path,
            plugin_paths=request.plugin_paths,
            created_by=request.created_by,
        )

    monkeypatch.setattr("openbbq.application.quickstart.create_run", fake_create_run)

    result = create_local_subtitle_job(
        LocalSubtitleJobRequest(
            workspace_root=tmp_path,
            input_path=video,
            source_lang="en",
            target_lang="zh",
            provider="openai",
            asr_model="tiny",
            asr_device="cpu",
            asr_compute_type="int8",
        )
    )

    assert result.workflow_id == "local-to-srt"
    assert result.run_id == "run_local"
    assert result.source_artifact_id is not None
    assert "project." in result.generated_config_path.read_text(encoding="utf-8")
    assert captured["request"].project_root == result.generated_project_root
    assert captured["execute_inline"] is False


def test_youtube_subtitle_job_starts_generated_run(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENBBQ_LLM_API_KEY", "sk-test")
    monkeypatch.setattr(
        "openbbq.application.quickstart.load_runtime_settings",
        lambda: _runtime_settings(tmp_path, llm_provider="openai"),
    )

    def fake_create_run(request, *, execute_inline=False):
        return RunRecord(
            id="run_youtube",
            workflow_id=request.workflow_id,
            mode="start",
            status="queued",
            project_root=request.project_root,
            config_path=request.config_path,
            plugin_paths=request.plugin_paths,
            created_by=request.created_by,
        )

    monkeypatch.setattr("openbbq.application.quickstart.create_run", fake_create_run)

    result = create_youtube_subtitle_job(
        YouTubeSubtitleJobRequest(
            workspace_root=tmp_path,
            url="https://www.youtube.com/watch?v=demo",
            source_lang="en",
            target_lang="zh",
            provider="openai",
            asr_model="tiny",
            asr_device="cpu",
            asr_compute_type="int8",
            quality="best",
            auth="auto",
        )
    )

    assert result.workflow_id == "youtube-to-srt"
    assert result.run_id == "run_youtube"
    assert result.source_artifact_id is None
    assert "watch?v=demo" in result.generated_config_path.read_text(encoding="utf-8")


def test_youtube_subtitle_job_uses_runtime_defaults_when_request_omits_runtime_fields(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("OPENBBQ_LLM_API_KEY", "sk-test")
    monkeypatch.setattr(
        "openbbq.application.quickstart.load_runtime_settings",
        lambda: _runtime_settings(tmp_path),
    )
    monkeypatch.setattr(
        "openbbq.application.quickstart.create_run",
        lambda request, execute_inline=False: RunRecord(
            id="run_youtube",
            workflow_id=request.workflow_id,
            mode="start",
            status="queued",
            project_root=request.project_root,
            config_path=request.config_path,
            plugin_paths=request.plugin_paths,
            created_by=request.created_by,
        ),
    )

    result = create_youtube_subtitle_job(
        YouTubeSubtitleJobRequest(
            workspace_root=tmp_path,
            url="https://www.youtube.com/watch?v=demo",
            source_lang="en",
            target_lang="zh",
            quality="best",
            auth="auto",
        )
    )

    rendered = yaml.safe_load(result.generated_config_path.read_text(encoding="utf-8"))
    steps = _workflow_steps(rendered, "youtube-to-srt")

    assert result.provider == "openai-compatible"
    assert result.model == "gpt-4o-mini"
    assert result.asr_model == "small"
    assert result.asr_device == "cpu"
    assert result.asr_compute_type == "int8"
    assert steps["correct"]["parameters"]["provider"] == "openai-compatible"
    assert steps["correct"]["parameters"]["model"] == "gpt-4o-mini"
    assert steps["translate"]["parameters"]["provider"] == "openai-compatible"
    assert steps["translate"]["parameters"]["model"] == "gpt-4o-mini"
    assert steps["transcribe"]["parameters"]["model"] == "small"
    assert steps["transcribe"]["parameters"]["device"] == "cpu"
    assert steps["transcribe"]["parameters"]["compute_type"] == "int8"


def test_quickstart_fails_when_default_llm_provider_is_missing(tmp_path, monkeypatch):
    settings = _runtime_settings(tmp_path).model_copy(update={"providers": {}})
    monkeypatch.setattr(
        "openbbq.application.quickstart.load_runtime_settings",
        lambda: settings,
    )

    with pytest.raises(
        ValidationError,
        match="Default LLM provider 'openai-compatible' is not configured",
    ):
        create_youtube_subtitle_job(
            YouTubeSubtitleJobRequest(
                workspace_root=tmp_path,
                url="https://www.youtube.com/watch?v=demo",
                source_lang="en",
                target_lang="zh",
                quality="best",
                auth="auto",
            )
        )
