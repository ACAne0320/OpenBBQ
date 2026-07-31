# Expert and Compatibility Workflows

Use the agent facade in `SKILL.md` for normal one-shot subtitle tasks. This page
is only for diagnosis, recovery, authentication, or an explicitly requested
atomic-command workflow.

## Execution environment

Honor the machine-readable `execution` policy returned by `agent next`.
Fetch, GPU transcription, and finish commonly require host execution. Do not
silently replace a requested GPU transcription with sandbox CPU; use CPU only
after the declared host/GPU path genuinely fails and the returned policy permits
fallback.

For YouTube authentication:

```bash
openbbq auth status youtube
openbbq auth browser-login youtube
```

Try anonymous fetch first unless OpenBBQ reports that authentication is needed.

## Atomic commands

The compatible low-level pipeline remains available:

```bash
openbbq init --workspace <workspace> <input>
openbbq fetch --workspace <workspace>
openbbq extract-audio --workspace <workspace>
openbbq transcribe --workspace <workspace> --model large-v3-turbo --gpu
openbbq segment --workspace <workspace>
openbbq translate init zh --workspace <workspace>
openbbq --json translate batch zh --workspace <workspace> --limit 20 --only-missing
openbbq translate apply zh --workspace <workspace> <targets.json>
```

Local inputs skip `fetch`. To export an intentionally unreviewed low-level
draft, make that choice explicit:

```bash
openbbq export --workspace <workspace> --to zh --mode bilingual --format ass --allow-unreviewed
openbbq burn --workspace <workspace> --subtitle out/zh.ass --output out/zh-burned.mp4
```

`--allow-unreviewed` exports an intentionally uncertified draft; it does not
manufacture delivery evidence. `delivery check` becomes ready only after the
facade has produced fresh agent-draft evidence or a complete, current human
review exists. Prefer the facade when the desired outcome is a one-shot draft.

## Professional editing

The normal result is an editable draft. A subtitle editor may review it in the
OpenBBQ review UI or import the ASS into Aegisub or an NLE. Once a complete,
current human review exists, it is authoritative: the agent facade must not
overwrite those targets or force another semantic pass.

Visual QA and `fansub-compact` are never automatic. Run them only when the user
explicitly requests those expert diagnostics or presets.
