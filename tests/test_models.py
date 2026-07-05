from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, cast

import pytest
import typer

from openbbq.cli.commands import models as modelcmd
from openbbq.cli.output import Output
from openbbq.core import models
from openbbq.core.asr.whispercpp import PROVIDER, WhisperCppBackend
from openbbq.errors import OpenBBQError

B = WhisperCppBackend()


class FakeResponse:
    def __init__(
        self,
        body: bytes,
        *,
        status: int = 200,
        headers: dict[str, str] | None = None,
        fail_after_reads: int | None = None,
        read_size: int = 4,
    ) -> None:
        self._body = body
        self._offset = 0
        self._reads = 0
        self._fail_after_reads = fail_after_reads
        self._read_size = read_size
        self.status = status
        self.headers = headers or {"Content-Length": str(len(body))}

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: Any,
    ) -> None:
        return None

    def read(self, size: int) -> bytes:
        if self._fail_after_reads is not None and self._reads >= self._fail_after_reads:
            raise OSError("connection dropped")
        if self._offset >= len(self._body):
            return b""
        self._reads += 1
        end = min(len(self._body), self._offset + min(size, self._read_size))
        chunk = self._body[self._offset : end]
        self._offset = end
        return chunk


def _range_header(request: object) -> str | None:
    get_header = getattr(request, "get_header", None)
    if callable(get_header):
        value = get_header("Range")
        return str(value) if value is not None else None
    return None


def _size_mb(size: int) -> float:
    return size / 1024 / 1024


def _cache(tmp_path, monkeypatch, *names: str):
    monkeypatch.setenv("OPENBBQ_HOME", str(tmp_path))
    cache = models.cache_dir(PROVIDER)
    cache.mkdir(parents=True)
    for name in names:
        (cache / f"ggml-{name}.bin").write_bytes(b"x")
    return cache


def test_default_model_uses_quality_order(tmp_path, monkeypatch) -> None:
    _cache(tmp_path, monkeypatch, "base", "large-v2-q8_0", "small.en")
    assert B.default_model() == "large-v2-q8_0"


def test_default_model_returns_single_cached(tmp_path, monkeypatch) -> None:
    _cache(tmp_path, monkeypatch, "base")
    assert B.default_model() == "base"


def test_default_model_is_none_when_empty(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("OPENBBQ_HOME", str(tmp_path))
    assert B.default_model() is None


def test_catalog_entries_have_provider_and_size() -> None:
    catalog = B.available_models()
    assert catalog
    assert all(m.provider and m.size_mb > 0 for m in catalog)


def test_pull_unknown_model_is_offline_error(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("OPENBBQ_HOME", str(tmp_path))
    with pytest.raises(OpenBBQError) as exc:  # rejected before any network call
        B.pull("not-a-real-model")
    assert exc.value.code == "model_missing"


def test_pull_returns_cached_path_without_download(tmp_path, monkeypatch) -> None:
    _cache(tmp_path, monkeypatch, "base")
    path = B.pull("base")
    assert path.is_file() and path.name == "ggml-base.bin"


def test_has_model_accepts_direct_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("OPENBBQ_HOME", str(tmp_path))
    f = tmp_path / "custom.bin"
    f.write_bytes(b"x")
    assert B.has_model(str(f)) is True
    assert B.has_model("definitely-missing") is False


def test_download_resumes_tmp_with_range_after_failure(tmp_path, monkeypatch) -> None:
    data = b"abcdefghij"
    dst = tmp_path / "model.bin"
    calls: list[str | None] = []

    def fake_urlopen(request: object, timeout: int = 30) -> FakeResponse:
        calls.append(_range_header(request))
        if len(calls) == 1:
            return FakeResponse(data, fail_after_reads=1)
        assert calls[-1] == "bytes=4-"
        return FakeResponse(
            data[4:],
            status=206,
            headers={"Content-Length": "6", "Content-Range": "bytes 4-9/10"},
        )

    monkeypatch.setattr(models.urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(OSError, match="connection dropped"):
        models.download("https://example.test/model.bin", dst, expected_size_mb=_size_mb(10))

    assert dst.with_suffix(".bin.tmp").read_bytes() == b"abcd"

    models.download("https://example.test/model.bin", dst, expected_size_mb=_size_mb(10))

    assert calls == [None, "bytes=4-"]
    assert dst.read_bytes() == data
    assert not dst.with_suffix(".bin.tmp").exists()


def test_download_truncates_tmp_when_server_ignores_range(tmp_path, monkeypatch) -> None:
    data = b"fresh-bytes"
    dst = tmp_path / "model.bin"
    tmp = dst.with_suffix(".bin.tmp")
    tmp.write_bytes(b"stale")
    calls: list[str | None] = []

    def fake_urlopen(request: object, timeout: int = 30) -> FakeResponse:
        calls.append(_range_header(request))
        return FakeResponse(data, status=200)

    monkeypatch.setattr(models.urllib.request, "urlopen", fake_urlopen)

    models.download("https://example.test/model.bin", dst, expected_size_mb=_size_mb(11))

    assert calls == ["bytes=5-"]
    assert dst.read_bytes() == data
    assert not tmp.exists()


def test_download_size_validation_removes_bad_file(tmp_path, monkeypatch) -> None:
    dst = tmp_path / "model.bin"

    monkeypatch.setattr(
        models.urllib.request,
        "urlopen",
        lambda request, timeout=30: FakeResponse(b"too-small"),
    )

    with pytest.raises(models.DownloadSizeMismatch) as raised:
        models.download("https://example.test/model.bin", dst, expected_size_mb=1.0)

    assert raised.value.actual_bytes == len(b"too-small")
    assert not dst.exists()
    assert not dst.with_suffix(".bin.tmp").exists()


def test_pull_size_mismatch_is_structured_error(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("OPENBBQ_HOME", str(tmp_path))
    monkeypatch.setattr(
        models.urllib.request,
        "urlopen",
        lambda request, timeout=30: FakeResponse(b"tiny"),
    )

    with pytest.raises(OpenBBQError) as raised:
        B.pull("base")

    assert raised.value.code == "model_size_mismatch"
    assert raised.value.context["model"] == "base"
    assert not (models.cache_dir(PROVIDER) / "ggml-base.bin").exists()


def test_machine_pull_reports_progress_on_stderr(tmp_path, monkeypatch, capsys) -> None:
    class FakeBackend:
        def pull(self, name: str, on_progress=None):
            if on_progress is not None:
                on_progress(1, 4)
                on_progress(4, 4)
            path = tmp_path / f"ggml-{name}.bin"
            path.write_bytes(b"data")
            return path

    monkeypatch.setattr(modelcmd, "_backend_for", lambda name: FakeBackend())

    ctx = cast(typer.Context, SimpleNamespace(obj=Output(json_mode=True)))
    modelcmd.pull_model(ctx, "base")

    captured = capsys.readouterr()
    lines = captured.out.strip().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["model"] == "base"
    assert "openbbq: pulling model base" in captured.err
    assert "openbbq: downloaded" in captured.err
