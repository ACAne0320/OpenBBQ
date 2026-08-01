"""Translation generation ownership for the agent facade.

Language rules describe what a good translation looks like.  This module owns
the separate question of who is allowed to generate it.  Keeping that decision
behind ``resolve_policy`` leaves one small seam for another explicitly selected
generator without coupling provider details to the agent workflow.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

CURRENT_AGENT_MODE = "current_agent"


@dataclass(frozen=True)
class TranslationGenerationPolicy:
    mode: str
    instruction: str
    external_translation_services: str
    external_llm_services: str
    automation: str

    def payload(self) -> dict[str, str]:
        return asdict(self)


_CURRENT_AGENT_POLICY = TranslationGenerationPolicy(
    mode=CURRENT_AGENT_MODE,
    instruction=(
        "Generate every translation directly with the current agent's own "
        "language reasoning from the supplied source, context, glossary, and "
        "rules. Do not call an external translation service or external LLM."
    ),
    external_translation_services="forbidden",
    external_llm_services="forbidden",
    automation="serialization_only",
)


def resolve_policy() -> TranslationGenerationPolicy:
    """Return the generation policy for a new translation lease."""

    return _CURRENT_AGENT_POLICY


def expected_mode(lease_payload: dict[str, Any]) -> str | None:
    """Read the expected mode, allowing leases created before this contract."""

    value = lease_payload.get("generation_policy")
    if not isinstance(value, dict):
        return None
    mode = value.get("mode")
    return mode if isinstance(mode, str) and mode else None
