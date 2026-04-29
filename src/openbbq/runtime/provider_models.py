from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from openbbq.errors import ValidationError
from openbbq.runtime.models import ProviderModel, ProviderProfile


def fetch_provider_models(
    provider: ProviderProfile,
    *,
    api_key: str | None,
    timeout: float = 20,
) -> tuple[ProviderModel, ...]:
    if provider.type != "openai_compatible":
        raise ValidationError(f"Provider '{provider.name}' does not support model listing.")
    if provider.base_url is None:
        raise ValidationError(f"Provider '{provider.name}' does not define a base URL.")

    request = Request(
        urljoin(provider.base_url.rstrip("/") + "/", "models"),
        headers=_request_headers(api_key),
        method="GET",
    )

    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise ValidationError(
            f"Provider '{provider.name}' model list request failed with HTTP {exc.code}."
        ) from exc
    except URLError as exc:
        raise ValidationError(
            f"Provider '{provider.name}' model list request failed: {exc}."
        ) from exc
    except json.JSONDecodeError as exc:
        raise ValidationError(
            f"Provider '{provider.name}' model list response was not valid JSON."
        ) from exc

    return normalize_provider_models(payload)


def test_provider_connection(
    *,
    base_url: str,
    api_key: str | None,
    model: str,
    timeout: float = 30,
) -> str:
    if not base_url.strip():
        raise ValidationError("Base URL is required.")
    if not model.strip():
        raise ValidationError("Model is required.")

    payload = json.dumps(
        {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": "Reply with OK.",
                }
            ],
            "max_tokens": 4,
            "temperature": 0,
        }
    ).encode("utf-8")
    request = Request(
        urljoin(base_url.rstrip("/") + "/", "chat/completions"),
        data=payload,
        headers={**_request_headers(api_key), "Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urlopen(request, timeout=timeout) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise ValidationError(f"Connection test failed with HTTP {exc.code}.") from exc
    except URLError as exc:
        raise ValidationError(f"Connection test failed: {exc}.") from exc
    except json.JSONDecodeError as exc:
        raise ValidationError("Connection test response was not valid JSON.") from exc

    choices = response_payload.get("choices") if isinstance(response_payload, dict) else None
    if not isinstance(choices, list) or not choices:
        raise ValidationError("Connection test response did not include model choices.")

    return "Connection test succeeded."


def normalize_provider_models(payload: Any) -> tuple[ProviderModel, ...]:
    if not isinstance(payload, dict):
        raise ValidationError("Provider model list response must be a JSON object.")

    data = payload.get("data")
    if not isinstance(data, list):
        raise ValidationError("Provider model list response must include a data array.")

    models: list[ProviderModel] = []
    seen: set[str] = set()
    for item in data:
        if not isinstance(item, dict):
            continue
        model_id = item.get("id")
        if not isinstance(model_id, str) or not model_id or model_id in seen:
            continue
        seen.add(model_id)
        models.append(
            ProviderModel(
                id=model_id,
                label=_optional_str(item.get("name")),
                owned_by=_optional_str(item.get("owned_by")),
                context_length=_context_length(item),
            )
        )

    return tuple(models)


def _request_headers(api_key: str | None) -> dict[str, str]:
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _optional_str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _context_length(item: dict[str, Any]) -> int | None:
    value = item.get("context_length")
    if isinstance(value, int) and value > 0:
        return value
    top_provider = item.get("top_provider")
    if isinstance(top_provider, dict):
        nested = top_provider.get("context_length")
        if isinstance(nested, int) and nested > 0:
            return nested
    return None
