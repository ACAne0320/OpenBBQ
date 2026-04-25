# Typed internal payloads design

## Context

The backend deliberately uses JSON-like dictionaries at plugin, artifact,
config, and workflow boundaries. That flexibility is still required because
plugin requests and artifact contents are external contracts.

The audit finding is narrower: some dynamic payloads leak too far inward after
the boundary has already been validated. The strongest examples are the
translation and transcript built-in plugins:

- `src/openbbq/builtin_plugins/translation/plugin.py` validates timed segment
  input, then repeatedly reads `segment["start"]`, `segment["end"]`,
  `segment.get("text")`, and `segment.get("source_text")` from dictionaries in
  translation, QA, request payload construction, and chunk splitting.
- `src/openbbq/builtin_plugins/transcript/plugin.py` validates transcript
  segment input, then repeatedly reads and mutates dictionaries in correction,
  low-confidence word payload construction, segmentation unit construction,
  line wrapping, and subtitle segment materialization.
- `src/openbbq/builtin_plugins/llm.py::segment_chunks()` is typed only for
  `list[dict[str, Any]]`, even though it is generic chunking logic.

These are internal transformation paths. They can use small typed value objects
without changing plugin input or output JSON shapes.

## Goals

- Keep plugin request and response payloads as JSON-like dictionaries.
- Keep artifact content and workflow bindings JSON-like.
- Add typed internal segment value objects for timed transcript/subtitle
  payloads after boundary validation.
- Reuse the typed segment boundary in both translation and transcript plugins.
- Make chunking generic so it can operate on typed segment lists.
- Preserve existing user-facing error messages and output payload shapes.
- Add focused tests for the new typed boundary before refactoring callers.

## Non-goals

- Do not introduce Pydantic models for plugin request or response envelopes.
- Do not change plugin manifest schemas or artifact type schemas.
- Do not change LLM prompt JSON shapes, response parsing, batching behavior, or
  fallback chunk splitting behavior.
- Do not type every dynamic dictionary in the backend.
- Do not move glossary rule normalization, provider selection, or artifact
  storage into typed models in this slice.
- Do not change public compatibility modules such as
  `openbbq.builtin_plugins.translation.translate`.

## Proposed architecture

Add `src/openbbq/builtin_plugins/segments.py` as an internal helper module:

- `TimedWord`
  - Owns normalized word timing, text, and optional confidence.
- `TimedSegment`
  - Owns normalized `start`, `end`, `text`, optional `source_text`, optional
    confidence, parsed words, and a deep-copyable original payload.
  - Offers `copy_payload()` for output paths that must preserve existing
    segment fields.
- `SegmentUnit`
  - Owns segmentation-unit timing, text, and source segment indexes used by
    transcript subtitle segmentation.
- `timed_segments_from_request()`
  - Reads `request["inputs"][input_name]["content"]`, preserves the current
    validation messages, and returns `list[TimedSegment]`.
- `timed_segments_from_any_input()`
  - Keeps translation's current fallback from `subtitle_segments` to
    `transcript`.

Update `src/openbbq/builtin_plugins/llm.py::segment_chunks()` to be generic:

- Accept `Sequence[T]`.
- Return `list[list[T]]`.
- Preserve the current positive-size validation and chunking behavior.

Update `translation/plugin.py`:

- `_timed_segments()` and `_timed_segments_any()` become thin wrappers around
  the shared segment helpers.
- Translation chunking receives `list[TimedSegment]`.
- LLM request payload construction reads typed segment attributes.
- Translation output payloads remain dictionaries with `start`, `end`,
  `source_text`, and `text`.
- QA logic reads typed attributes instead of dictionary keys.

Update `transcript/plugin.py`:

- `_segments()` becomes a thin wrapper around the shared segment helper.
- Correction chunking receives `list[TimedSegment]`.
- Low-confidence word payload construction reads typed word attributes.
- Correction output still deep-copies the original segment payload and adds the
  current correction fields.
- Subtitle segmentation uses `SegmentUnit` internally, then materializes the
  same subtitle segment dictionaries as before.

## Error handling

Keep the existing validation message families:

- `<prefix> requires <input_name> content.`
- `<prefix> <input_name> content must be a list of objects.`
- `<prefix> <input_name> segments must include start and end.`
- `<prefix> chunk size must be positive.`

Numeric conversion errors for malformed `start`, `end`, or word timing values
may continue to surface as Python conversion errors; this slice does not define
new validation contracts for malformed numeric values.

## Testing

Add focused tests:

- `timed_segments_from_request()` preserves current missing-content,
  non-list-content, non-object item, and missing timing messages.
- `TimedSegment` normalizes start/end/text/source_text/confidence/words while
  preserving the original payload for correction output.
- `timed_segments_from_any_input()` preserves translation's fallback from
  `subtitle_segments` to `transcript`.
- `segment_chunks()` works with a non-dict typed sequence and preserves existing
  chunk-size errors.

Run existing translation and transcript tests to prove output shapes and prompt
payloads remain unchanged:

- `uv run pytest tests/test_builtin_segments.py tests/test_builtin_translation.py tests/test_builtin_transcript.py tests/test_builtin_llm_helpers.py -q`
- `uv run pytest`
- `uv run ruff check .`
- `uv run ruff format --check .`

## Acceptance criteria

- `src/openbbq/builtin_plugins/segments.py` owns typed internal segment models
  and boundary parsing.
- Translation and transcript plugin internals use typed segment objects after
  request validation.
- Plugin request and response payloads remain JSON dictionaries.
- Existing translation and transcript behavior is unchanged.
- Focused typed-boundary tests cover validation and normalization behavior.
- The code-quality audit closure document marks typed internal payload cleanup
  complete after implementation and verification.
