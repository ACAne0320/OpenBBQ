"""Smoke-test an installed pywhispercpp build the way OpenBBQ uses it.

Checks the accelerator OpenBBQ reports, then transcribes one clip with the GPU
requested so a broken backend fails loudly instead of silently.

Usage: python whisper_gpu_smoke.py <expected accelerator prefix> <ggml model> <wav>
"""

from __future__ import annotations

import sys

from pywhispercpp.model import Model

from openbbq.core.asr.whispercpp import WhisperCppBackend

expected, model_path, audio = sys.argv[1:4]

accelerator = WhisperCppBackend().accelerator()
print(f"accelerator: {accelerator}", flush=True)
if not accelerator.startswith(expected):
    sys.exit(f"expected a {expected} accelerator, got {accelerator!r}")

model = Model(model_path, context_params={"use_gpu": True}, print_progress=False)
text = " ".join(segment.text for segment in model.transcribe(audio)).lower()
print(f"text: {text}", flush=True)
if "ask not what your country can do for you" not in text:
    sys.exit("transcription does not match the sample")
