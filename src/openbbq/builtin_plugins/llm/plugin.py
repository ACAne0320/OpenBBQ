from __future__ import annotations

from openbbq.builtin_plugins.translation import plugin as translation_plugin


_default_client_factory = translation_plugin._default_client_factory


def run(request: dict, client_factory=None) -> dict:
    effective_client_factory = _default_client_factory if client_factory is None else client_factory
    return translation_plugin.run_translation(
        request,
        client_factory=effective_client_factory,
        error_prefix="llm.translate",
        include_provider_metadata=False,
    )
