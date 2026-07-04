from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from openbbq.core.asr import whispercpp
from openbbq.core.asr.whispercpp import WhisperCppBackend
from openbbq.core.asr.whispercpp import _segment_words, _to_segments


class Native:
    # " wor" + "ld" exercises sub-word merging; "," exercises punctuation
    # attaching to the preceding word; "[_BEG_]" is a skipped special token.
    _TEXT = ["[_BEG_]", " Hello", ",", " wor", "ld"]
    _DATA = [
        SimpleNamespace(t0=0, t1=0, p=0.5),
        SimpleNamespace(t0=12, t1=34, p=0.9),
        SimpleNamespace(t0=34, t1=40, p=0.8),
        SimpleNamespace(t0=40, t1=70, p=0.7),
        SimpleNamespace(t0=70, t1=88, p=0.6),
    ]

    def whisper_full_n_tokens(self, ctx: object, segment: int) -> int:
        return len(self._TEXT)

    def whisper_full_get_token_text(self, ctx: object, segment: int, token: int) -> str:
        return self._TEXT[token]

    def whisper_full_get_token_data(self, ctx: object, segment: int, token: int) -> object:
        return self._DATA[token]


def test_adapter_merges_tokens_into_words_from_centiseconds() -> None:
    words = _segment_words(object(), Native(), 0)
    segments = _to_segments(
        [SimpleNamespace(t0=10, t1=90, text=" Hello, world ")],
        [words],
    )

    assert segments[0].start == 0.1
    assert segments[0].end == 0.9
    assert segments[0].text == "Hello, world"
    # sub-words merged, punctuation attached, leading space dropped
    assert [w.word for w in segments[0].words or []] == ["Hello,", "world"]
    hello = (segments[0].words or [])[0]
    assert (hello.start, hello.end, hello.prob) == (0.12, 0.4, 0.9)
    world = (segments[0].words or [])[1]
    assert (world.start, world.end, world.prob) == (0.4, 0.88, 0.7)


def test_transcribe_passes_cpu_context_to_pywhispercpp(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("OPENBBQ_HOME", str(tmp_path / "home"))
    model = tmp_path / "home" / "models" / "whisper.cpp" / "ggml-base.bin"
    model.parent.mkdir(parents=True)
    model.write_bytes(b"fake")
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"fake")

    seen: dict[str, object] = {}

    class Model:
        def __init__(self, path: str, **kwargs: object) -> None:
            seen["path"] = path
            seen["kwargs"] = kwargs
            self._ctx = object()

        def transcribe(self, _audio: str, **_kwargs: object) -> list[object]:
            return [SimpleNamespace(t0=0, t1=100, text="hello")]

    class Native:
        def whisper_full_n_segments(self, _ctx: object) -> int:
            return 1

        def whisper_full_n_tokens(self, _ctx: object, _segment: int) -> int:
            return 0

    monkeypatch.setattr(whispercpp, "_pywhispercpp", lambda: (Model, Native()))
    monkeypatch.setattr(whispercpp.media, "wav_duration", lambda _path: 1.0)

    result = WhisperCppBackend().transcribe(
        audio, model="base", language="en", use_gpu=False
    )

    assert result.language == "en"
    assert seen["path"] == str(model)
    assert seen["kwargs"] == {
        "print_progress": False,
        "redirect_whispercpp_logs_to": None,
        "context_params": {"use_gpu": False},
    }
