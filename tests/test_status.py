from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import cast

from rich.console import Console

from openbbq.cli.commands.status import StatusResult
from openbbq.core import workspace as ws
from openbbq.schemas import Manifest, Source, Stage, StageState, StageStatus


def test_status_result_includes_resume_fields_and_stale_stage(tmp_path) -> None:
    wsdir = tmp_path / "ws"
    wsdir.mkdir()
    src = tmp_path / "source.wav"
    src.write_bytes(b"")
    (wsdir / "translation.zh.json").write_text("{}", encoding="utf-8")
    manifest = Manifest(
        created_at=datetime.now(timezone.utc),
        source=Source(type="local_audio", ref=str(src), title="Demo"),
        glossary="frieren",
        stages={
            Stage.TRANSCRIBE: StageState(
                status=StageStatus.RUNNING,
                updated_at=datetime.now(timezone.utc) - timedelta(seconds=61),
            )
        },
    )
    ws.write_manifest(wsdir, manifest)

    result = StatusResult.of(wsdir, ws.read_manifest(wsdir))
    payload = result.payload()

    source = cast(dict[str, object], payload["source"])
    worksheets = cast(list[str], payload["worksheets"])
    stages = cast(dict[str, dict[str, object]], payload["stages"])
    assert source == {"type": "local_audio", "ref": str(src)}
    assert payload["glossary"] == "frieren"
    assert "next" not in payload
    assert worksheets == ["zh"]
    assert stages["transcribe"]["stale"] is True

    console = Console(record=True, width=80)
    console.print(result.render())
    rendered = console.export_text()
    assert "source: local_audio" in rendered
    assert "glossary: frieren" in rendered
    assert "worksheets: zh" in rendered
    assert "(stale)" in rendered
