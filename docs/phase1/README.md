# Phase 1 Documentation

Phase 1 establishes the backend core and CLI needed to run, inspect, and debug early OpenBBQ workflows without a desktop UI.

Use these documents as the launch source of truth:

- [Phase 1 Scope](./Phase-1-Scope.md) - MVP boundaries, non-goals, and definition of done.
- [Backend & CLI Goals](./Backend-CLI-Goals.md) - checklist of short-term implementation goals.
- [Project Config](./Project-Config.md) - YAML schema, canonical fixtures, mock plugin fixture design, and precedence tests.
- [Domain Model](./Domain-Model.md) - core entities, relationships, states, and serialization rules.
- [Workflow Engine](./Workflow-Engine.md) - execution lifecycle, pause/resume, retries, and events.
- [Plugin System](./Plugin-System.md) - plugin manifest, discovery, execution contract, and validation.
- [CLI Spec](./CLI-Spec.md) - command behavior, output rules, and exit codes.

Phase 1 should launch only after the golden workflow in [Phase 1 Scope](./Phase-1-Scope.md) can run from the CLI and the expected artifact versions can be inspected.
