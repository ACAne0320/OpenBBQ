# Glossary Reference

The default agent workflow learns reusable terminology without adding another
decision step to the happy path.

## Default behavior

- An explicit `--glossary <name>` always wins.
- For a fetched URL, OpenBBQ derives a stable author-and-target-language
  glossary after metadata is available. Later videos with the same author and
  target language reuse it without mixing translations across languages.
- Every non-deletion `source_fix` becomes a workspace glossary candidate. The
  agent only marks it `reusable: true/false`; OpenBBQ promotes reusable
  candidates into the overlay automatically. `glossary_updates` remains for a
  new term that is not represented by a source correction.
- Segmentation and translation use the merged base glossary plus overlay
  immediately; the same applies if the rare `review_source` action is emitted.
- A successful `agent finish` publishes non-conflicting reusable entries.
  Conflicts or permission failures do not block video delivery; the overlay is
  retained with a retry command.

Only record a reusable alias when the same incorrect form is expected to mean
the same canonical term in future related videos. Common words and
context-sensitive mistakes belong in a cue- or segment-scoped `source_fix`, not
in the global glossary; mark those fixes `reusable: false`.

Useful fields are:

- `source`: canonical source spelling.
- `target`: preferred translation, when known.
- `aliases`: reusable ASR spellings or mishearings.
- `note`: context that helps disambiguate the term.
- `keep: true`: preserve the source form in translations.

## Expert commands

These commands are optional inspection and maintenance tools. They are not
steps in the default one-shot workflow.

```bash
openbbq --json glossary list
openbbq --json glossary show <name>
openbbq glossary new <name> --context "<domain context>"
openbbq glossary use <name> --workspace <workspace>
openbbq glossary apply --workspace <workspace> <patch.json>
```

Apply bounded JSON patches rather than editing the global glossary file
directly:

```json
{
  "terms": [
    {
      "source": "Codex",
      "target": "Codex",
      "aliases": ["Code X"],
      "note": "OpenAI coding agent",
      "keep": true
    }
  ]
}
```

The command is atomic: conflicting ownership of a source or alias rejects the
patch instead of overwriting an existing entry.
