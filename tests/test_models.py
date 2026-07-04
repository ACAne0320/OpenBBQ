from __future__ import annotations

import pytest

from openbbq.core import models
from openbbq.core.asr.whispercpp import PROVIDER, WhisperCppBackend
from openbbq.errors import OpenBBQError

B = WhisperCppBackend()


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
