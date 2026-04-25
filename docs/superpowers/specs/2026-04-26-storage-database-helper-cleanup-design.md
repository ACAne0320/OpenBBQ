# Storage database helper cleanup design

## Context

`src/openbbq/storage/database.py` is the project SQLite repository boundary for
runs, workflow state, step runs, events, artifacts, and artifact versions. It
currently preserves the desired storage shape: each record is written both to
query-friendly columns and to a full `record_json` snapshot that is used for
model reconstruction.

The repository is functional, but every write path repeats the same mechanics:

- dump the Pydantic record with `model_dump(mode="json")`;
- look up a SQLAlchemy row by primary key;
- create and add a row when it does not exist;
- serialize JSON columns with the same deterministic `json.dumps()` settings;
- serialize nullable JSON fields only when a value exists;
- rebuild Pydantic records from `row.record_json`.

That repetition makes later desktop-facing storage changes easier to implement
inconsistently. The cleanup should remove only the repeated mechanics while
keeping record-specific column assignments visible.

## Goals

- Keep `ProjectDatabase` as the stable storage API.
- Preserve the current SQLite tables, columns, indexes, ordering, and
  `record_json` snapshots.
- Preserve existing storage model round trips and repository behavior.
- Extract repeated serialization, nullable serialization, row upsert, and
  row-to-model helpers into one focused internal module.
- Add characterization tests for helper behavior and database upsert semantics.
- Keep record-specific write methods readable and explicit.

## Non-goals

- Do not introduce a generic repository abstraction.
- Do not change migrations or SQLAlchemy ORM row definitions.
- Do not change public storage imports or artifact content behavior.
- Do not change how events allocate sequence numbers.
- Do not change JSON field names, sort order, path serialization, or read
  ordering.
- Do not split the large storage test module in this slice; that is the next
  audit item.

## Proposed architecture

Add `src/openbbq/storage/database_records.py` as a private helper module for
database record mechanics:

- `record_payload(record: RecordModel) -> JsonObject`
  - Returns the existing `model_dump(mode="json")` payload.
- `dump_json(value: Any) -> str`
  - Owns the deterministic JSON settings currently in `database.py`.
- `dump_nullable_json(value: Any) -> str | None`
  - Returns `None` for absent optional JSON fields, otherwise delegates to
    `dump_json()`.
- `model_from_row(model_type, row)`
  - Reconstructs a storage record from `row.record_json`.
- `model_from_optional_row(model_type, row)`
  - Keeps nullable read methods small.
- `upsert_row(session, row_type, row_id)`
  - Centralizes the repeated `session.get()` plus row creation pattern.

`src/openbbq/storage/database.py` will keep all record-specific write methods
and query methods. It will import the helpers and continue assigning each row's
typed columns in place. This preserves query visibility while removing the
duplicated mechanics that caused the audit finding.

## Data flow

Write paths continue to follow the same shape:

1. Convert the record to its JSON-compatible payload with `record_payload()`.
2. Upsert the row by primary key with `upsert_row()`.
3. Assign record-specific columns exactly as today.
4. Assign JSON columns through `dump_json()` and `dump_nullable_json()`.
5. Assign `row.record_json` from the same payload.

Read paths continue to select ORM rows and reconstruct storage models from the
stored `record_json` snapshot.

## Error handling

This cleanup does not introduce new domain errors. Existing SQLAlchemy,
Pydantic, and storage errors should surface exactly as they do today.

## Testing

Add focused tests for the extracted mechanics:

- helper serialization is deterministic and keeps non-ASCII values readable;
- nullable JSON helper returns `None` only for absent values;
- helper row upsert returns the same row for an existing primary key;
- helper row-to-model reconstruction reads from `record_json`;
- `ProjectDatabase.write_workflow_state()` updates an existing row instead of
  creating duplicate state;
- `ProjectDatabase.write_run()` preserves path and tuple serialization in the
  full `record_json` snapshot.

Run targeted storage tests first, then the full verification suite:

- `uv run pytest tests/test_storage.py tests/test_package_layout.py::test_new_package_modules_are_importable`
- `uv run pytest`
- `uv run ruff check .`
- `uv run ruff format --check .`

## Acceptance criteria

- `src/openbbq/storage/database_records.py` owns shared storage record
  mechanics.
- `src/openbbq/storage/database.py` no longer defines duplicate JSON/model
  helper functions or inline row creation blocks in every write method.
- Each `ProjectDatabase` write method still shows the record-specific column
  assignments plainly.
- Storage behavior, SQLite row facts, read ordering, and record round trips are
  unchanged.
- Focused tests cover the extracted helpers and upsert behavior.
- The code-quality audit closure document marks storage database helper cleanup
  complete after implementation and verification.
