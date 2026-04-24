from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any


LEGACY_PROVIDER_NAME = "openai_compatible"


@dataclass(frozen=True, slots=True)
class LlmProviderCredentials:
    name: str
    type: str
    api_key: str
    base_url: str | None
    model_default: str | None = None


def llm_provider_from_request(
    request: dict[str, Any], *, error_prefix: str
) -> LlmProviderCredentials:
    parameters = request.get("parameters", {})
    provider_name = parameters.get("provider")
    runtime = request.get("runtime", {})
    providers = runtime.get("providers", {}) if isinstance(runtime, dict) else {}
    if (
        isinstance(provider_name, str)
        and provider_name.strip()
        and provider_name != LEGACY_PROVIDER_NAME
    ):
        provider = providers.get(provider_name)
        if not isinstance(provider, dict):
            raise ValueError(f"Provider '{provider_name}' is not configured for {error_prefix}.")
        provider_type = provider.get("type")
        if provider_type != "openai_compatible":
            raise ValueError(
                f"{error_prefix} provider '{provider_name}' must be openai_compatible."
            )
        api_key = provider.get("api_key")
        if not isinstance(api_key, str) or not api_key:
            raise RuntimeError(
                f"{error_prefix} provider '{provider_name}' API key is not resolved."
            )
        base_url = provider.get("base_url")
        model_default = provider.get("default_chat_model")
        return LlmProviderCredentials(
            name=provider_name,
            type="openai_compatible",
            api_key=api_key,
            base_url=base_url if isinstance(base_url, str) and base_url else None,
            model_default=model_default
            if isinstance(model_default, str) and model_default
            else None,
        )

    api_key = os.environ.get("OPENBBQ_LLM_API_KEY")
    if not api_key:
        raise RuntimeError(f"OPENBBQ_LLM_API_KEY is required for {error_prefix}.")
    base_url = parameters.get("base_url") or os.environ.get("OPENBBQ_LLM_BASE_URL")
    return LlmProviderCredentials(
        name=LEGACY_PROVIDER_NAME,
        type="openai_compatible",
        api_key=api_key,
        base_url=str(base_url) if base_url else None,
        model_default=None,
    )
