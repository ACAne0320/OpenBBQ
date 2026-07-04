from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from openbbq.core import workspace as ws
from openbbq.schemas import Manifest, Source


def _manifest(title: str) -> Manifest:
    return Manifest(
        created_at=datetime.now(timezone.utc),
        source=Source(type="local_audio", ref="/tmp/source.wav", title=title),
        stages={},
    )


def test_write_manifest_uses_unique_temp_files_for_concurrent_writes(tmp_path) -> None:
    wsdir = tmp_path / "ws"
    wsdir.mkdir()

    def write(i: int) -> None:
        ws.write_manifest(wsdir, _manifest(f"title-{i}"))

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(write, range(50)))

    manifest = ws.read_manifest(wsdir)
    assert manifest.source.title is not None
    assert not list(wsdir.glob(".manifest.json.*.tmp"))
