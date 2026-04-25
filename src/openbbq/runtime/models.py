from __future__ import annotations

from pathlib import Path
import re
from typing import TypeAlias

from pydantic import Field, field_validator

from openbbq.domain.base import JsonObject, OpenBBQModel, model_payload

SUPPORTED_PROVIDER_TYPES: frozenset[str] = frozenset({"openai_compatible"})
PROVIDER_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
ProviderMap: TypeAlias = dict[str, "ProviderProfile"]
ResolvedProviderMap: TypeAlias = dict[str, "ResolvedProvider"]


class CacheSettings(OpenBBQModel):
    root: Path


class ProviderProfile(OpenBBQModel):
    name: str
    type: str
    base_url: str | None = None
    api_key: str | None = None
    default_chat_model: str | None = None
    display_name: str | None = None

    @field_validator("name")
    @classmethod
    def valid_name(cls, value: str) -> str:
        if not value or PROVIDER_NAME_PATTERN.fullmatch(value) is None:
            raise ValueError("Provider names must use only letters, digits, '_' or '-'")
        return value

    @field_validator("type")
    @classmethod
    def valid_type(cls, value: str) -> str:
        if value not in SUPPORTED_PROVIDER_TYPES:
            allowed = ", ".join(sorted(SUPPORTED_PROVIDER_TYPES))
            raise ValueError(f"must be one of: {allowed}")
        return value

    @field_validator("api_key")
    @classmethod
    def valid_secret_reference(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if value.startswith("env:") and value != "env:":
            return value
        if value.startswith("sqlite:") and value != "sqlite:":
            return value
        if value.startswith("keyring:"):
            payload = value.removeprefix("keyring:")
            service, separator, username = payload.partition("/")
            if separator and service and username:
                return value
        raise ValueError("must use an env:, sqlite:, or keyring: secret reference")

    def public_dict(self) -> JsonObject:
        return model_payload(self)


class FasterWhisperSettings(OpenBBQModel):
    cache_dir: Path
    default_model: str = "base"
    default_device: str = "cpu"
    default_compute_type: str = "int8"


class ModelsSettings(OpenBBQModel):
    faster_whisper: FasterWhisperSettings


class RuntimeSettings(OpenBBQModel):
    version: int
    config_path: Path
    cache: CacheSettings
    providers: ProviderMap = Field(default_factory=dict)
    models: ModelsSettings | None = None

    @field_validator("version")
    @classmethod
    def version_one(cls, value: int) -> int:
        if type(value) is not int or value != 1:
            raise ValueError("Runtime settings version must be 1")
        return value

    def public_dict(self) -> JsonObject:
        return model_payload(self)


class SecretCheck(OpenBBQModel):
    reference: str
    resolved: bool
    display: str
    value_preview: str | None = None
    error: str | None = None


class ResolvedProvider(OpenBBQModel):
    name: str
    type: str
    api_key: str | None
    base_url: str | None
    default_chat_model: str | None = None

    def request_payload(self) -> JsonObject:
        return model_payload(self)


class RuntimeContext(OpenBBQModel):
    providers: ResolvedProviderMap = Field(default_factory=dict)
    cache_root: Path | None = None
    faster_whisper_cache_dir: Path | None = None
    redaction_values: tuple[str, ...] = ()

    def request_payload(self) -> JsonObject:
        return {
            "providers": {
                name: provider.request_payload()
                for name, provider in sorted(self.providers.items())
            },
            "cache": {
                "root": str(self.cache_root) if self.cache_root is not None else None,
                "faster_whisper": str(self.faster_whisper_cache_dir)
                if self.faster_whisper_cache_dir is not None
                else None,
            },
        }


class ModelAssetStatus(OpenBBQModel):
    provider: str
    model: str
    cache_dir: Path
    present: bool
    size_bytes: int = 0
    error: str | None = None

    def public_dict(self) -> JsonObject:
        return model_payload(self)


class DoctorCheck(OpenBBQModel):
    id: str
    status: str
    severity: str
    message: str

    def public_dict(self) -> JsonObject:
        return model_payload(self)
