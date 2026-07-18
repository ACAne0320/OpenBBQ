# Active Glossary Workflow

Glossary is a living document maintained with the user. It is used by three
stages:

- ASR biasing: fewer misheard proper nouns.
- Segment correction: known mishearings or aliases are corrected to the
  canonical source.
- Translation checks: `translate check` reports `term_issues` for missing
  established translations.

Series videos, anime, games, courses, interviews, brands, or any named-entity
heavy content should actively maintain a glossary. If terms are discovered only
after transcription, still add them: the current workspace can use them during
segment/translate, and future related videos can use them for ASR biasing.

## Find Or Create

At the start, look for a reusable glossary:

```bash
openbbq --json glossary list
openbbq --json glossary show <name>
```

If a glossary already matches the same series, channel, or topic, bind it during
`init`:

```bash
openbbq init --workspace workspaces/demo --glossary frieren '<input>'
```

If the workspace already exists:

```bash
openbbq glossary use frieren --workspace workspaces/demo
```

If no suitable glossary exists, confirm core terms with the user and create one:

```bash
openbbq glossary new frieren --context "Frieren: Beyond Journey's End, fantasy anime"
```

Do not invent official translations. Ask the user for uncertain translations, or
mark them as pending in `note`.

## Safe Maintenance

Do not edit `~/.openbbq/glossaries/<name>.json` directly. Write a bounded patch
and apply it atomically:

```json
{
  "terms": [
    {
      "source": "Andy Matuschak",
      "target": "安迪·马图沙克",
      "aliases": ["Annie Matushak"],
      "note": "researcher; ASR variant confirmed from context"
    }
  ]
}
```

```bash
openbbq glossary apply --workspace workspaces/demo glossary-terms.json
```

The command adds new canonical terms, merges new aliases into existing terms,
and preserves omitted target/note/keep values. Conflicting ownership of the same
source or alias rejects the whole patch. A successful update invalidates
`segment` and later artifacts in the workspace; an idempotent no-op patch does
not invalidate anything.

The stored fields are:

- `source`: canonical source text used by ASR biasing, correction, and term
  checks.
- `target`: established translation.
- `aliases`: common ASR mishearings, spelling variants, or alternate names;
  segment corrects them back to `source`.
- `note`: disambiguation context for the agent.
- `keep: true`: keep the source form untranslated in the target language.

```json
{
  "schema": "openbbq/glossary@1",
  "name": "frieren",
  "context": "Frieren: Beyond Journey's End, fantasy anime",
  "terms": [
    {
      "source": "Frieren",
      "target": "芙莉莲",
      "aliases": ["Freiren", "Freeran", "Fearin", "Frieran"],
      "note": "series & title character"
    },
    {
      "source": "Kraft",
      "target": "克拉夫特",
      "aliases": ["Craft"],
      "note": "monk; ASR may hear it as Craft"
    }
  ]
}
```

## Active Audit After Transcribe

After `transcribe`, always run:

```bash
openbbq glossary suggest --workspace workspaces/demo
openbbq --json glossary audit --workspace workspaces/demo --offset 0 --limit 20
```

`suggest` is a prioritization hint, not a completeness check. Page through every
`audit` batch, including segments whose words have high probabilities. Each item
includes the resolved source, raw source when it changed, previous/next segment,
word probabilities, overlapping reference caption when available, and current
glossary matches. Judge likely errors from meaning, grammar, topic, names, and
surrounding discourse. Probabilities and reference captions are evidence, not
ground truth.

For bilingual ASS / hard-subtitled videos, this full source audit is required
because the source text is rendered in the final video; a correct translated
line is not enough. Continue with the returned `next_offset` until `remaining`
is zero.

Classify findings into four groups:

1. **Reusable ASR mistakes or spelling variants**
   Known proper nouns misheard by ASR, misspelled character names, joined/split
   work titles. Add the incorrect form to an existing term's `aliases`, or add a
   new canonical `source` term and put the incorrect form in `aliases`. These
   should not flow into `segment` unchanged.
2. **Confirmed new key terms**
   Recurring names, places, organizations, abilities, work titles, brands, and
   other important series terminology. If the translation is known, add it to the
   glossary; if not, ask the user or mark it as pending in `note`.
3. **One-off or context-sensitive ASR mistakes**
   Do not create a dangerous global alias such as a common word that may be
   correct in another context. Record the exact current correction instead:

   ```json
   {
     "amendments": [
       {
         "segment_id": 12,
         "find": "hot tick",
         "replacement": "hot take",
         "reason": "The surrounding sentence uses the idiom hot take."
       }
     ]
   }
   ```

   ```bash
   openbbq asr amend --workspace workspaces/demo asr-amendments.json
   ```

4. **Correct one-off words / irrelevant candidates**
   Do not add them to the glossary. Probability alone is never a reason to
   accept or replace a word.

Update the glossary before `segment`. If `segment` already ran, rerun:

```bash
openbbq segment --workspace workspaces/demo
openbbq translate init zh --workspace workspaces/demo --max-lines 2
```

## Checks

- Inspect `segment --json`: `glossary_matched_terms` shows canonical terms that
  actually appeared, `glossary_aliases_applied` proves known ASR variants were
  corrected, and `glossary_no_effect: true` means a binding existed but changed
  or matched nothing. Binding a glossary is not proof it was useful.
- Fix all `term_issues` from `translate check`.
- Passing `translate check` does not prove source cues are free of ASR
  proper-noun errors.
- Before bilingual output, spot-check source lines in `cues.json` or
  `translation.<lang>.json`.
