from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
import typer
from rich.console import Console
from rich.style import Style

import openbbq.cli.commands.fetch as fetchcmd
from openbbq.cli.output import Output
from openbbq.core import fetch as fetchlib
from openbbq.core import workspace as ws
from openbbq.core.auth import store
from openbbq.errors import OpenBBQError
from openbbq.schemas import Manifest, Source, Stage, StageState, StageStatus


def _output_line(path: Path) -> str:
    return f"openbbq-output\t{json.dumps(str(path))}\n"


def _manifest() -> Manifest:
    return Manifest(
        created_at=datetime.now(timezone.utc),
        source=Source(type="url", ref="https://www.youtube.com/watch?v=test"),
        stages={},
    )


def test_fetch_defaults_to_anonymous_ytdlp(tmp_path, monkeypatch) -> None:
    wsdir = tmp_path / "ws"
    wsdir.mkdir()
    manifest = _manifest()
    calls: list[list[str]] = []

    monkeypatch.setattr(fetchlib, "_yt_dlp_command", lambda: ["yt-dlp"])

    def fake_run(
        args: list[str], *, on_progress=None, on_metadata=None
    ) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if on_progress is not None:
            on_progress(fetchlib.FetchProgress(phase="download", done=512, total=1024))
        output = wsdir / "media" / "video.webm"
        output.write_bytes(b"media")
        return subprocess.CompletedProcess(args, 0, stdout=_output_line(output))

    monkeypatch.setattr(fetchlib, "_run_yt_dlp", fake_run)

    result = fetchlib.fetch_media(wsdir, manifest)

    assert result.artifact == "media/video.webm"
    assert "--cookies" not in calls[0]
    assert "--write-thumbnail" in calls[0]
    assert "--write-subs" in calls[0]
    assert "--write-auto-subs" in calls[0]
    assert "--progress-template" in calls[0]
    assert any(arg.startswith("before_dl:openbbq-title") for arg in calls[0])
    assert any(arg.startswith("before_dl:openbbq-uploader") for arg in calls[0])
    assert calls[0][calls[0].index("-o") + 1].endswith("%(title)s.%(ext)s")


def test_fetch_preserves_optional_youtube_caption_as_asr_reference(
    tmp_path, monkeypatch
) -> None:
    wsdir = tmp_path / "ws"
    wsdir.mkdir()
    manifest = _manifest()
    monkeypatch.setattr(fetchlib, "_yt_dlp_command", lambda: ["yt-dlp"])

    def fake_run(
        args: list[str], *, on_progress=None, on_metadata=None
    ) -> subprocess.CompletedProcess[str]:
        output = wsdir / "media" / "Demo.webm"
        output.write_bytes(b"media")
        (wsdir / "media" / "Demo.en.vtt").write_text(
            "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nHello\n",
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(args, 0, stdout=_output_line(output))

    monkeypatch.setattr(fetchlib, "_run_yt_dlp", fake_run)

    result = fetchlib.fetch_media(wsdir, manifest)

    assert result.reference_caption == ".openbbq/reference-caption.vtt"
    caption = ws.read_reference_caption_optional(wsdir)
    assert caption is not None
    assert caption.startswith("WEBVTT")


def test_fetch_max_height_adds_bounded_format_selector(tmp_path, monkeypatch) -> None:
    wsdir = tmp_path / "ws"
    wsdir.mkdir()
    manifest = _manifest()
    calls: list[list[str]] = []
    monkeypatch.setattr(fetchlib, "_yt_dlp_command", lambda: ["yt-dlp"])

    def fake_run(
        args: list[str], *, on_progress=None, on_metadata=None
    ) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        output = wsdir / "media" / "video.webm"
        output.write_bytes(b"media")
        return subprocess.CompletedProcess(args, 0, stdout=_output_line(output))

    monkeypatch.setattr(fetchlib, "_run_yt_dlp", fake_run)

    result = fetchlib.fetch_media(wsdir, manifest, max_height=720)

    assert result.max_height == 720
    selector = calls[0][calls[0].index("--format") + 1]
    assert selector == "bestvideo[height<=720]+bestaudio/best[height<=720]"


def test_fetch_auth_exports_temp_cookies_and_cleans_up(tmp_path, monkeypatch) -> None:
    wsdir = tmp_path / "ws"
    wsdir.mkdir()
    manifest = _manifest()
    cookie_file = tmp_path / "youtube.cookies.txt"
    calls: list[list[str]] = []

    monkeypatch.setattr(fetchlib, "_yt_dlp_command", lambda: ["yt-dlp"])

    def fake_export(site: str) -> Path:
        assert site == "youtube"
        cookie_file.write_text("# cookies\n", encoding="utf-8")
        return cookie_file

    def fake_run(
        args: list[str], *, on_progress=None, on_metadata=None
    ) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        assert cookie_file.exists()
        output = wsdir / "media" / "video.webm"
        output.write_bytes(b"media")
        return subprocess.CompletedProcess(args, 0, stdout=_output_line(output))

    monkeypatch.setattr(fetchlib.auth_store, "export_netscape_temp", fake_export)
    monkeypatch.setattr(fetchlib, "_run_yt_dlp", fake_run)

    result = fetchlib.fetch_media(wsdir, manifest, auth_site="youtube")

    assert result.artifact == "media/video.webm"
    assert calls[0][1:3] == ["--cookies", str(cookie_file)]
    assert not cookie_file.exists()


def test_fetch_auth_cookie_export_permission_error_is_structured(
    tmp_path, monkeypatch
) -> None:
    wsdir = tmp_path / "ws"
    wsdir.mkdir()
    manifest = _manifest()
    calls: list[list[str]] = []

    monkeypatch.setattr(fetchlib, "_yt_dlp_command", lambda: ["yt-dlp"])

    def fake_export(site: str) -> Path:
        assert site == "youtube"
        raise PermissionError("operation not permitted")

    def fake_run(
        args: list[str], *, on_progress=None, on_metadata=None
    ) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, stdout="")

    monkeypatch.setattr(fetchlib.auth_store, "export_netscape_temp", fake_export)
    monkeypatch.setattr(fetchlib, "_run_yt_dlp", fake_run)

    with pytest.raises(OpenBBQError) as raised:
        fetchlib.fetch_media(wsdir, manifest, auth_site="youtube")

    assert raised.value.code == "auth_cookie_export_failed"
    assert raised.value.context["site"] == "youtube"
    assert "OPENBBQ_HOME" in (raised.value.fix or "")
    assert "--no-auth" in (raised.value.fix or "")
    assert calls == []


def test_fetch_auth_403_is_structured_and_cleans_cookie(tmp_path, monkeypatch) -> None:
    wsdir = tmp_path / "ws"
    wsdir.mkdir()
    manifest = _manifest()
    cookie_file = tmp_path / "youtube.cookies.txt"
    cookie_file.write_text("# cookies\n", encoding="utf-8")

    monkeypatch.setattr(fetchlib, "_yt_dlp_command", lambda: ["yt-dlp"])
    monkeypatch.setattr(
        fetchlib.auth_store,
        "export_netscape_temp",
        lambda site: cookie_file,
    )
    monkeypatch.setattr(
        fetchlib,
        "_run_yt_dlp",
        lambda args, *, on_progress=None, on_metadata=None: subprocess.CompletedProcess(
            args, 1, stdout="unable to download video data: HTTP Error 403: Forbidden"
        ),
    )

    with pytest.raises(OpenBBQError) as raised:
        fetchlib.fetch_media(wsdir, manifest, auth_site="youtube")

    assert raised.value.code == "authenticated_download_forbidden"
    assert not cookie_file.exists()


def test_fetch_anonymous_bot_error_reports_auth_required(tmp_path, monkeypatch) -> None:
    wsdir = tmp_path / "ws"
    wsdir.mkdir()
    manifest = _manifest()

    monkeypatch.setattr(fetchlib, "_yt_dlp_command", lambda: ["yt-dlp"])
    monkeypatch.setattr(
        fetchlib,
        "_run_yt_dlp",
        lambda args, *, on_progress=None, on_metadata=None: subprocess.CompletedProcess(
            args,
            1,
            stdout="ERROR: mlAqT7kGDoc: Sign in to confirm you're not a bot. Use --cookies-from-browser",
        ),
    )

    with pytest.raises(OpenBBQError) as raised:
        fetchlib.fetch_media(wsdir, manifest)

    assert raised.value.code == "auth_required"
    assert raised.value.fix == "openbbq auth browser-login youtube"


def test_fetch_progress_line_uses_real_request_fields() -> None:
    assert fetchlib._parse_progress_line(
        'openbbq-progress\tdownload\t"downloading"\t1024\tNA\t2048\t'
        '"dash-video"\t"248"\t"webm"\t"vp9"\t"none"\t"1080p"\tNA\n'
    ) == fetchlib.FetchProgress(
        phase="download",
        status="downloading",
        done=1024,
        total=2048,
        format_id="248",
        ext="webm",
        vcodec="vp9",
        acodec="none",
        format_note="1080p",
    )


def test_fetch_postprocess_progress_line_reports_postprocessor() -> None:
    assert fetchlib._parse_progress_line(
        'openbbq-progress\tpostprocess\t"started"\tNA\tNA\tNA\tNA\tNA\t'
        'NA\tNA\tNA\tNA\t"Merger"\n'
    ) == fetchlib.FetchProgress(
        phase="postprocess",
        status="started",
        postprocessor="Merger",
    )


def test_fetch_forwards_ytdlp_progress(tmp_path, monkeypatch) -> None:
    wsdir = tmp_path / "ws"
    wsdir.mkdir()
    manifest = _manifest()
    seen: list[fetchlib.FetchProgress] = []

    monkeypatch.setattr(fetchlib, "_yt_dlp_command", lambda: ["yt-dlp"])

    def fake_run(
        args: list[str], *, on_progress=None, on_metadata=None
    ) -> subprocess.CompletedProcess[str]:
        if on_progress is not None:
            on_progress(fetchlib.FetchProgress(phase="download", done=7, total=11))
        output = wsdir / "media" / "video.webm"
        output.write_bytes(b"media")
        return subprocess.CompletedProcess(args, 0, stdout=_output_line(output))

    monkeypatch.setattr(fetchlib, "_run_yt_dlp", fake_run)

    fetchlib.fetch_media(wsdir, manifest, on_progress=seen.append)

    assert seen == [fetchlib.FetchProgress(phase="download", done=7, total=11)]


def test_fetch_metadata_line_reports_title_author() -> None:
    title = fetchlib._parse_metadata_line(f"openbbq-title\t{json.dumps('Demo')}\n")
    uploader = fetchlib._parse_metadata_line(
        f"openbbq-uploader\t{json.dumps('Channel')}\n"
    )

    assert title == fetchlib.FetchMetadata(title="Demo")
    assert uploader == fetchlib.FetchMetadata(author="Channel")


def test_fetch_collects_title_author_and_thumbnail(tmp_path, monkeypatch) -> None:
    wsdir = tmp_path / "ws"
    wsdir.mkdir()
    manifest = _manifest()

    monkeypatch.setattr(fetchlib, "_yt_dlp_command", lambda: ["yt-dlp"])

    def fake_run(
        args: list[str], *, on_progress=None, on_metadata=None
    ) -> subprocess.CompletedProcess[str]:
        media = wsdir / "media" / "Demo Title.webm"
        thumbnail = wsdir / "media" / "Demo Title.webp"
        media.write_bytes(b"media")
        thumbnail.write_bytes(b"cover")
        stdout = "\n".join(
            [
                f"openbbq-output\t{json.dumps(str(media))}",
                f"openbbq-title\t{json.dumps('Demo Title')}",
                "openbbq-uploader\tNA",
                f"openbbq-channel\t{json.dumps('Demo Channel')}",
                f"openbbq-id\t{json.dumps('testid')}",
            ]
        )
        return subprocess.CompletedProcess(args, 0, stdout=stdout)

    monkeypatch.setattr(fetchlib, "_run_yt_dlp", fake_run)

    result = fetchlib.fetch_media(wsdir, manifest)

    assert result.artifact == "media/Demo Title.webm"
    assert result.title == "Demo Title"
    assert result.author == "Demo Channel"
    assert result.thumbnail == "media/Demo Title.webp"


def test_fetch_requires_structured_after_move_output(tmp_path, monkeypatch) -> None:
    wsdir = tmp_path / "ws"
    wsdir.mkdir()
    manifest = _manifest()
    existing = wsdir / "media" / "old.webm"
    existing.parent.mkdir()
    existing.write_bytes(b"old")

    monkeypatch.setattr(fetchlib, "_yt_dlp_command", lambda: ["yt-dlp"])

    def fake_run(
        args: list[str], *, on_progress=None, on_metadata=None
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args,
            0,
            stdout=f"WARNING: keeping existing artifact {existing}\n",
        )

    monkeypatch.setattr(fetchlib, "_run_yt_dlp", fake_run)

    with pytest.raises(OpenBBQError) as raised:
        fetchlib.fetch_media(wsdir, manifest)

    assert raised.value.code == "fetch_no_output"
    assert "yt-dlp" in (raised.value.fix or "")


def test_fetch_label_uses_only_action_and_format() -> None:
    assert fetchcmd._progress_label(
        "youtube",
        fetchlib.FetchProgress(
            phase="download",
            format_id="248",
            ext="webm",
            vcodec="vp9",
            acodec="none",
            format_note="1080p",
        ),
    ) == ("Downloading video (webm 1080p)")


def test_fetch_label_reports_postprocess() -> None:
    assert fetchcmd._progress_label(
        "youtube",
        fetchlib.FetchProgress(phase="postprocess", postprocessor="Merger"),
    ) == ("Merging media")


def test_fetch_label_reports_metadata_before_progress() -> None:
    assert fetchcmd._progress_label("youtube") == "Fetching metadata"


def test_fetch_result_renders_rich_field_table() -> None:
    console = Console(record=True, width=50)
    result = fetchcmd.FetchResult(
        workspace="/tmp/openbbq/ws",
        artifact="media/video.webm",
        title="A [literal] title that should wrap cleanly",
        author="Demo Channel",
        thumbnail="media/video.webp",
        auth="youtube",
    )
    console.print(result.render())
    rendered = console.export_text()

    assert "✓ media fetched" in rendered
    assert "file" in rendered
    assert "title" in rendered
    assert "A [literal] title" in rendered
    assert "workspace" in rendered
    assert "/tmp/openbbq/ws" in rendered
    assert "auth" in rendered
    known_labels = {"title", "author", "workspace", "file", "cover", "auth"}
    labels = [
        label
        for line in rendered.splitlines()[1:]
        if (label := line.split()[0]) in known_labels
    ]
    assert labels == ["title", "author", "workspace", "file", "cover", "auth"]

    workspace_text = result._workspace_text()
    file_text = result._artifact_text(result.artifact)
    cover_text = result._artifact_text(result.thumbnail or "")
    workspace_style = cast(Style, workspace_text.style)
    file_style = cast(Style, file_text.style)
    cover_style = cast(Style, cover_text.style)
    workspace_uri = Path("/tmp/openbbq/ws").resolve().as_uri()
    assert workspace_style.link == workspace_uri
    assert file_style.link == f"{workspace_uri}/media/video.webm"
    assert cover_style.link == f"{workspace_uri}/media/video.webp"


def test_fetch_command_records_json_progress_for_status(tmp_path, monkeypatch) -> None:
    wsdir = tmp_path / "ws"
    wsdir.mkdir()
    manifest = _manifest()
    ws.write_manifest(wsdir, manifest)
    recorded: list[StageState] = []

    monkeypatch.setattr(fetchcmd.fetchlib, "auto_auth_site", lambda url: None)

    def fake_fetch_media(
        path,
        manifest,
        *,
        auth_site=None,
        max_height=None,
        on_progress=None,
        on_metadata=None,
    ):
        if on_metadata is not None:
            on_metadata(fetchlib.FetchMetadata(title="Demo Title"))
            on_metadata(fetchlib.FetchMetadata(author="Demo Channel"))
        if on_progress is not None:
            on_progress(
                fetchlib.FetchProgress(
                    phase="download",
                    done=5,
                    total=10,
                    vcodec="vp9",
                    acodec="none",
                    format_id="248",
                    ext="webm",
                )
            )
            on_progress(
                fetchlib.FetchProgress(phase="postprocess", postprocessor="Merger")
            )
        return fetchlib.FetchResult(
            artifact="media/video.webm",
            title="Demo Title",
            author="Demo Channel",
            thumbnail="media/video.webp",
            auth=auth_site,
            max_height=max_height,
        )

    monkeypatch.setattr(fetchcmd.fetchlib, "fetch_media", fake_fetch_media)
    real_record_stage = ws.record_stage

    def capture_record_stage(path, manifest, stage, state):
        if stage is Stage.FETCH:
            recorded.append(state)
        real_record_stage(path, manifest, stage, state)

    monkeypatch.setattr(fetchcmd.ws, "record_stage", capture_record_stage)

    ctx = cast(typer.Context, SimpleNamespace(obj=Output(json_mode=True)))
    fetchcmd.fetch(ctx, workspace=str(wsdir), max_height=1080)

    assert recorded[0].status is StageStatus.RUNNING
    assert recorded[0].progress is None
    running_progress = [
        state.progress
        for state in recorded
        if state.status is StageStatus.RUNNING and state.progress is not None
    ]
    assert any(
        progress.done == 5 and progress.total == 10 for progress in running_progress
    )
    assert any(
        progress.label == "Downloading video (webm)" for progress in running_progress
    )
    assert any(
        progress.label == "Merging media"
        and progress.done == 0
        and progress.total is None
        for progress in running_progress
    )
    assert recorded[-1].status is StageStatus.DONE
    updated = ws.read_manifest(wsdir)
    assert updated.source.title == "Demo Title"
    assert updated.source.author == "Demo Channel"
    assert updated.source.thumbnail == "media/video.webp"


def test_auto_auth_site_uses_saved_youtube_session(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("OPENBBQ_HOME", str(tmp_path / "home"))
    url = "https://www.youtube.com/watch?v=test"

    assert fetchlib.auto_auth_site(url) is None

    store.save_cookies(
        "youtube",
        [
            {
                "name": "SID",
                "value": "secret",
                "domain": ".youtube.com",
                "path": "/",
                "expires": 4102444800,
                "httpOnly": True,
                "secure": True,
            }
        ],
    )

    assert fetchlib.auto_auth_site(url) == "youtube"


def test_media_input_resolves_relative_fetch_artifact(tmp_path) -> None:
    source = tmp_path / "source.wav"
    source.write_bytes(b"source")
    manifest = Manifest(
        created_at=datetime.now(timezone.utc),
        source=Source(type="url", ref="https://example.test/video"),
        stages={
            Stage.FETCH: StageState(
                status=StageStatus.DONE,
                artifact="media/video.webm",
                updated_at=datetime.now(timezone.utc),
            )
        },
    )

    assert ws.media_input(manifest, tmp_path) == tmp_path / "media" / "video.webm"
