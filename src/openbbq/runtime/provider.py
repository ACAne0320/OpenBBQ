from __future__ import annotations

from openbbq.domain.base import JsonObject, OpenBBQModel


class LlmProviderCredentials(OpenBBQModel):
    name: str
    type: str
    api_key: str
    base_url: str | None
    model_default: str | None = None


def llm_provider_from_request(request: JsonObject, *, error_prefix: str) -> LlmProviderCredentials:
    parameters = request.get("parameters", {})
    provider_name = parameters.get("provider")
    if not isinstance(provider_name, str) or not provider_name.strip():
        raise ValueError(f"{error_prefix} requires a provider parameter.")
    provider_name = provider_name.strip()

    runtime = request.get("runtime", {})
    providers = runtime.get("providers", {}) if isinstance(runtime, dict) else {}
    provider = providers.get(provider_name)
    if not isinstance(provider, dict):
        raise ValueError(f"provider '{provider_name}' is not configured for {error_prefix}.")
    provider_type = provider.get("type")
    if provider_type != "openai_compatible":
        raise ValueError(f"{error_prefix} provider '{provider_name}' must be openai_compatible.")
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
        model_default=model_default if isinstance(model_default, str) and model_default else None,
    )
