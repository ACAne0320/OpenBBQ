from importlib import resources

from openbbq.application.quickstart import (
    LocalSubtitleJobRequest,
    YouTubeSubtitleJobRequest,
    create_local_subtitle_job,
    create_youtube_subtitle_job,
    write_local_subtitle_workflow,
    write_youtube_subtitle_workflow,
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
