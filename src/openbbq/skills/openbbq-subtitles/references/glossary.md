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

## File Format

Maintain `~/.openbbq/glossaries/<name>.json`:

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
```

Then actively audit both candidates and transcript text. Do not treat
suggestions as optional notes. For bilingual ASS / hard-subtitled videos, audit
source lines because the English source text is rendered in the final video; a
correct translated line is not enough.

Classify candidates into three groups:

1. **ASR mistakes or spelling variants**
   Known proper nouns misheard by ASR, misspelled character names, joined/split
   work titles. Add the incorrect form to an existing term's `aliases`, or add a
   new canonical `source` term and put the incorrect form in `aliases`. These
   should not flow into `segment` unchanged.
2. **Confirmed new key terms**
   Recurring names, places, organizations, abilities, work titles, brands, and
   other important series terminology. If the translation is known, add it to the
   glossary; if not, ask the user or mark it as pending in `note`.
3. **One-off common words / low-confidence candidates**
   Do not add them to the glossary. Mention them in a reply or work note if
   useful, but do not block the workflow on them.

Update the glossary before `segment`. If `segment` already ran, rerun:

```bash
openbbq segment --workspace workspaces/demo
openbbq translate init zh --workspace workspaces/demo
```

## Checks

- Fix all `term_issues` from `translate check`.
- Passing `translate check` does not prove source cues are free of ASR
  proper-noun errors.
- Before bilingual output, spot-check source lines in `cues.json` or
  `translation.<lang>.json`.
