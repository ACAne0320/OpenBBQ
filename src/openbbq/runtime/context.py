from __future__ import annotations

from openbbq.runtime.models import ResolvedProvider, RuntimeContext, RuntimeSettings
from openbbq.runtime.secrets import SecretResolver


def build_runtime_context(
    settings: RuntimeSettings,
    *,
    secret_resolver: SecretResolver | None = None,
) -> RuntimeContext:
    resolver = secret_resolver or SecretResolver()
    providers: dict[str, ResolvedProvider] = {}
    redaction_values: list[str] = []
    for name, profile in settings.providers.items():
        api_key = None
        if profile.api_key is not None:
            resolved = resolver.resolve(profile.api_key)
            api_key = resolved.value if resolved.resolved else None
            if api_key:
                redaction_values.append(api_key)
        providers[name] = ResolvedProvider(
            name=name,
            type=profile.type,
            api_key=api_key,
            base_url=profile.base_url,
            default_chat_model=profile.default_chat_model,
        )
    faster_whisper_cache_dir = (
        settings.models.faster_whisper.cache_dir if settings.models is not None else None
    )
    return RuntimeContext(
        providers=providers,
        cache_root=settings.cache.root,
        faster_whisper_cache_dir=faster_whisper_cache_dir,
        redaction_values=tuple(redaction_values),
    )
