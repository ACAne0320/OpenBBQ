from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from openbbq.schemas import Segment


class Capability(StrEnum):
    WORD_TIMESTAMPS = "word_timestamps"
    PROGRESS = "progress"
    BIASING = "biasing"  # context biasing toward known terms (whisper: initial_prompt)
    DIARIZATION = "diarization"
    ALIGNMENT = "alignment"


@dataclass(frozen=True)
class ModelInfo:
    name: str  # e.g. "large-v3", "base.en-q5_1"
    provider: str  # the backend that consumes it (== backend.name)
    size_mb: float  # reference download size


@dataclass(frozen=True)
class TranscriptResult:
    segments: list[Segment]
    language: str


class ASRBackend(Protocol):
    """A speech-to-text backend and the single seam for everything specific to
    it: its models (catalog / cache / download), accelerator, availability, and
    transcription. Commands and ``doctor`` depend on this Protocol, never on a
    concrete backend or its model format — so adding a backend is one adapter,
    no command/schema change (DESIGN §7).
    """

    name: str
    install_hint: str  # how to install it (doctor remediation)
    capabilities: set[Capability]

    def is_available(self) -> bool: ...
    def version(self) -> str | None: ...
    def accelerator(self) -> str: ...  # "Metal" / "CUDA" / "Vulkan" / "CPU" / "unknown"

    # Models are backend-owned: format, source, naming, and cache layout are all
    # backend-specific, so the backend — not a shared module — manages them.
    def available_models(self) -> list[ModelInfo]: ...  # the catalog
    def cached_models(self) -> list[str]: ...  # already downloaded
    def default_model(self) -> str | None: ...  # best cached, or None
    def has_model(self, name: str) -> bool: ...  # cached name or a direct file path
    def pull(
        self, name: str, on_progress: Callable[[int, int], None] | None = None
    ) -> Path: ...

    def transcribe(
        self,
        audio: Path,
        *,
        model: str,
        language: str | None,
        on_progress: Callable[[int, int], None] | None = None,
        bias: Sequence[str] | None = None,  # term biasing (Capability.BIASING), native per backend
        **opts: object,  # backend-specific knobs (e.g. whisper's raw initial_prompt)
    ) -> TranscriptResult: ...
