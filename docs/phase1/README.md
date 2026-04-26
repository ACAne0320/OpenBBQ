# Phase 1 Documentation

Phase 1 established the backend core and CLI needed to run, inspect, and debug
early OpenBBQ workflows without a desktop UI. These documents remain the
historical Phase 1 contract; current repository state also includes Phase 2
media plugins and the local FastAPI sidecar documented in the roadmap and exit
checklists.

Use these documents as the Phase 1 contract source of truth:

- [Phase 1 Scope](./Phase-1-Scope.md) - MVP boundaries, non-goals, and definition of done.
- [Backend & CLI Goals](./Backend-CLI-Goals.md) - checklist of short-term implementation goals.
- [Project Config](./Project-Config.md) - YAML schema, canonical fixtures, mock plugin fixture design, and precedence tests.
- [Domain Model](./Domain-Model.md) - core entities, relationships, states, and serialization rules.
- [Workflow Engine](./Workflow-Engine.md) - execution lifecycle, pause/resume, retries, and events.
- [Plugin System](./Plugin-System.md) - plugin manifest, discovery, execution contract, and validation.
- [CLI Spec](./CLI-Spec.md) - command behavior, output rules, and exit codes.

The Phase 1 acceptance contract is covered by the CLI, workflow, storage,
plugin, and artifact tests. The golden workflow in
[Phase 1 Scope](./Phase-1-Scope.md) can run from the CLI and its expected
artifact versions can be inspected.
