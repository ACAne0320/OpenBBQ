# Built-in LLM helper extraction design

## Purpose

The transcript correction and translation built-in plugins both invoke an
OpenAI-compatible chat model and validate JSON array responses. The current
implementation keeps those mechanics inside each plugin module, which makes
provider compatibility fixes and response-validation changes easy to apply in
one place but miss in the other.

This cleanup extracts the shared LLM plumbing into a focused helper module
while preserving plugin behavior, tool contracts, deterministic fixtures, and
existing monkeypatch seams used by tests.

## Scope

In scope:

- Add a small shared helper module under `src/openbbq/builtin_plugins/`.
- Reuse the helper from:
  - `src/openbbq/builtin_plugins/transcript/plugin.py`
  - `src/openbbq/builtin_plugins/translation/plugin.py`
- Preserve the public plugin entrypoints:
  - `transcript.plugin.run()`
  - `transcript.plugin.run_correct()`
  - `transcript.plugin.run_segment()`
  - `translation.plugin.run()`
  - `translation.plugin.run_translate()`
  - `translation.plugin.run_translation()`
  - `translation.plugin.run_qa()`
- Preserve existing test monkeypatch points:
  - `transcript.plugin._default_client_factory`
  - `translation.plugin._default_client_factory`
- Preserve the current plugin request payloads, response payloads, metadata, and
  error message wording.
- Add coverage for the existing `llm_json.py` compatibility modules, which
  currently attempt to re-export a missing `_parse_json_array` symbol.

Out of scope:

- Changing prompts, model parameters, retry behavior, provider selection, or
  runtime provider configuration.
- Introducing typed internal transcript/translation segment models. That is a
  later audit slice.
- Changing chunk split fallback behavior when the model returns invalid JSON or
  the wrong number of items.
- Rewriting transcript segmentation, translation QA, glossary normalization, or
  subtitle export behavior.
- Changing plugin manifests or workflow fixture YAML files.

## Current code evidence

The audit item is recorded in
`docs/superpowers/specs/2026-04-25-code-quality-audit-design.md` as
**P2: Built-in LLM plugins duplicate client and JSON-response plumbing**.

Current code shape:

- `src/openbbq/builtin_plugins/transcript/plugin.py` is about 602 lines.
- `src/openbbq/builtin_plugins/translation/plugin.py` is about 494 lines.
- Both modules define `_default_client_factory()` with the same optional
  dependency import and error message.
- Both modules read `completion.choices[0].message.content` and raise
  plugin-specific `ValueError` messages when choices or content are invalid.
- Both modules split timed segment lists into chunks and reject non-positive
  chunk sizes.
- Both modules parse JSON model responses as arrays of indexed objects with a
  required string `text` field, but the plugin-specific details differ:
  - translation expects translated segment items;
  - transcript correction allows optional `status` and `uncertain_reason`.
- `src/openbbq/builtin_plugins/transcript/llm_json.py` and
  `src/openbbq/builtin_plugins/translation/llm_json.py` both re-export
  `_parse_json_array`, but neither plugin module defines that symbol. Importing
  either module in the project environment currently raises `ImportError`.

Relevant existing tests:

- `tests/test_builtin_plugins.py`
  - translation client setup and response shape;
  - translation runtime provider defaults;
  - malformed translation JSON;
  - translation batching and chunk splitting;
  - transcript correction client setup and response shape;
  - transcript runtime provider defaults;
  - transcript chunk splitting.
- `tests/test_phase2_asr_correction_segmentation.py`
- `tests/test_phase2_translation_slice.py`
- `tests/test_phase2_contract_regressions.py`

## Design

Add `src/openbbq/builtin_plugins/llm.py` as a shared internal helper module.
The module should own only generic OpenAI-compatible and JSON-list mechanics:

- `default_openai_client_factory(api_key, base_url)`
  - Imports `OpenAI` lazily.
  - Preserves the current missing dependency message:
    `openai is not installed. Install OpenBBQ with the llm optional dependencies.`
- `completion_content(completion, error_prefix)`
  - Reads `completion.choices[0].message.content`.
  - Raises:
    - `{error_prefix} received no choices from the model.`
    - `{error_prefix} model response content must be a string.`
- `segment_chunks(segments, chunk_size, error_prefix)`
  - Returns deterministic list chunks.
  - Raises `{error_prefix} chunk size must be positive.` for non-positive sizes.
- `parse_indexed_text_items(content, expected_count, error_prefix, item_label)`
  - Parses JSON into a list of objects.
  - Validates array shape, expected count, zero-based indexes, and string text.
  - Preserves existing error wording by receiving the plugin-specific
    `item_label`, for example `translated segment` or `corrected segment`.
  - Returns validated item copies with `index` normalized to the expected
    zero-based integer and `text` preserved as the validated string.
  - Keeps any additional item fields so transcript correction can validate
    `status` and `uncertain_reason` without parsing the same JSON twice.

Keep plugin-specific behavior in each plugin module:

- Translation keeps `_parse_translation_response()` as the public local
  semantic parser for translation behavior. It should call
  `parse_indexed_text_items(..., item_label="translated segment")` and return
  the same shape it returns today.
- Transcript correction keeps `_parse_correction_response()` because it owns
  correction-only fields and validation:
  - allowed `status` values: `unchanged`, `corrected`, `uncertain`;
  - optional string `uncertain_reason`;
  - output key preservation for `uncertain_reason`.
  It should call the shared parser for the common JSON/index/text validation,
  then apply correction-specific field checks.
- Both plugin modules should keep `_default_client_factory` as a module-level
  alias or wrapper so existing tests and callers can continue monkeypatching it.
- The `llm_json.py` modules should become compatibility modules that import the
  shared helper functions and expose a real `_parse_json_array` compatibility
  wrapper. This wrapper should use the shared JSON parser and keep callers from
  failing at import time. It is compatibility-only; plugin runtime code should
  call explicit helpers directly.

## Dependency direction

The dependency direction should remain simple:

- `transcript/plugin.py` imports generic helpers from
  `openbbq.builtin_plugins.llm`.
- `translation/plugin.py` imports generic helpers from
  `openbbq.builtin_plugins.llm`.
- `openbbq.builtin_plugins.llm` must not import transcript or translation
  plugin modules.
- `transcript/llm_json.py` and `translation/llm_json.py` may import from the
  shared helper module for compatibility exports, but runtime plugin modules
  should not depend on these compatibility shims.

## Behavior preservation

The cleanup must preserve:

- OpenAI-compatible client construction arguments:
  - `api_key=provider.api_key`
  - `base_url=provider.base_url`
- Missing OpenAI dependency error text.
- Completion extraction error text after substituting the plugin's existing
  prefix:
  - `transcript.correct`
  - `translation.translate`
  - any custom `error_prefix` passed through `run_translation()`
- Translation JSON response errors:
  - model response is not valid JSON;
  - model response is not an array;
  - expected translated segment count mismatch;
  - translated segments must be objects;
  - translated segment index mismatch;
  - translated segment text must be a string.
- Transcript correction JSON response errors:
  - model response is not valid JSON;
  - model response is not an array;
  - expected corrected segment count mismatch;
  - corrected segments must be objects;
  - corrected segment index mismatch;
  - corrected segment text must be a string;
  - corrected segment status is invalid;
  - uncertain reason must be a string.
- Chunking behavior and recursive split fallback when a chunk-level model
  response fails validation.
- Translation and transcript output content and metadata shapes.

## Testing

Add characterization tests before moving behavior:

- Import both compatibility modules:
  - `openbbq.builtin_plugins.transcript.llm_json`
  - `openbbq.builtin_plugins.translation.llm_json`
- Verify the shared helper extracts completion content and preserves the
  no-choices and non-string-content error messages.
- Verify the shared indexed JSON parser preserves representative translation
  error messages for malformed JSON, non-array JSON, count mismatch, index
  mismatch, and non-string text.
- Verify transcript correction still accepts optional `status` and
  `uncertain_reason`, and still rejects invalid correction-specific values.

Existing focused tests must continue to pass:

- `uv run pytest tests/test_builtin_plugins.py -q`
- `uv run pytest tests/test_phase2_asr_correction_segmentation.py tests/test_phase2_translation_slice.py -q`
- `uv run pytest tests/test_phase2_contract_regressions.py -q`

Final verification must include:

- `uv run pytest`
- `uv run ruff check .`
- `uv run ruff format --check .`

## Acceptance criteria

- `src/openbbq/builtin_plugins/llm.py` owns generic LLM client, completion, JSON
  list parsing, and chunking helpers.
- Transcript and translation plugin modules no longer duplicate those generic
  helper bodies.
- Plugin-specific response validation remains local to the relevant plugin
  module.
- The two `llm_json.py` compatibility modules import successfully.
- Existing monkeypatch seams for `_default_client_factory` still work.
- Existing plugin contracts, CLI/API behavior, fixture behavior, and error
  message wording are preserved.
- The audit tracking spec can mark **P2: Built-in LLM plugins duplicate client
  and JSON-response plumbing** as done after implementation and verification.
