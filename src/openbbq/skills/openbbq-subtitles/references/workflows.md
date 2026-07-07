# OpenBBQ Single-Video Command Templates

## YouTube Input

```bash
openbbq init --workspace workspaces/demo --glossary <name> '<youtube-url>'
openbbq auth status youtube
openbbq fetch --workspace workspaces/demo --auth youtube
openbbq extract-audio --workspace workspaces/demo
openbbq transcribe --workspace workspaces/demo --model large-v3-turbo --language en --gpu
openbbq glossary suggest --workspace workspaces/demo
openbbq segment --workspace workspaces/demo
openbbq translate init zh --workspace workspaces/demo
```

If there is no glossary, remove `--glossary <name>`; if transcription reveals
names or terms, create or bind a glossary according to `glossary.md` before
continuing to `segment`.

If `auth status youtube` is not configured, try anonymous fetch first. If
anonymous fetch fails because cookies or bot checks are needed, run:

```bash
openbbq auth browser-login youtube
```

## Local File Input

```bash
openbbq init --workspace workspaces/demo --glossary <name> /path/to/video.mp4
openbbq extract-audio --workspace workspaces/demo
openbbq transcribe --workspace workspaces/demo --model large-v3-turbo --language en --gpu
openbbq glossary suggest --workspace workspaces/demo
openbbq segment --workspace workspaces/demo
openbbq translate init zh --workspace workspaces/demo
```

Local files skip `fetch`.

## Fill Translations

First read `workspaces/demo/translation.zh.json` for source text,
`budget.max_chars`, and the embedded worksheet glossary map. Keep translations
within budget.

For a few cues (up to about 30), edit `target` fields with the Edit tool. For
many cues, write a batch JSON:

```json
{"1": "First translated line", "2": "Second translated line"}
```

Merge:

```bash
openbbq translate apply zh --workspace workspaces/demo targets.batch1.json
```

Multiple batches are fine; later batches only overwrite provided cue ids.

## Check, Export, Burn

```bash
openbbq translate check zh --workspace workspaces/demo
openbbq export --workspace workspaces/demo --to zh --mode bilingual --format ass --ass-preset fansub --output out/zh.ass
openbbq burn --workspace workspaces/demo --subtitle out/zh.ass --output out/zh-burned.mp4
```

Clear `missing`, `over_budget`, and `term_issues` before export.

## Completion QA

```bash
openbbq --json status --workspace workspaces/demo
openbbq translate check zh --workspace workspaces/demo
ffprobe -v error -show_entries format=duration,size -of json workspaces/demo/out/zh-burned.mp4
ffmpeg -y -ss 60 -i workspaces/demo/out/zh-burned.mp4 -frames:v 1 workspaces/demo/qa-frame-60s.png
```

Confirm:

- Relevant manifest stages are complete, with no failed/stale/running state.
- `missing`, `over_budget`, and `term_issues` are clear.
- Output MP4 is non-empty and matches the source duration.
- The captured frame shows rendered subtitles in the right position; for
  bilingual output, both lines are readable.
