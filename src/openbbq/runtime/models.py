from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True, slots=True)
class CacheSettings:
    root: Path


@dataclass(frozen=True, slots=True)
class ProviderProfile:
    name: str
    type: str
    base_url: str | None = None
    api_key: str | None = None
    default_chat_model: str | None = None
    display_name: str | None = None

    def public_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "type": self.type,
            "base_url": self.base_url,
            "api_key": self.api_key,
            "default_chat_model": self.default_chat_model,
            "display_name": self.display_name,
        }


@dataclass(frozen=True, slots=True)
class FasterWhisperSettings:
    cache_dir: Path
    default_model: str = "base"
    default_device: str = "cpu"
    default_compute_type: str = "int8"


@dataclass(frozen=True, slots=True)
class ModelsSettings:
    faster_whisper: FasterWhisperSettings


@dataclass(frozen=True, slots=True)
class RuntimeSettings:
    version: int
    config_path: Path
    cache: CacheSettings
    providers: dict[str, ProviderProfile] = field(default_factory=dict)
    models: ModelsSettings | None = None

    def public_dict(self) -> dict[str, object]:
        models = self.models
        return {
            "version": self.version,
            "config_path": str(self.config_path),
            "cache": {"root": str(self.cache.root)},
            "providers": {
                name: provider.public_dict() for name, provider in sorted(self.providers.items())
            },
            "models": {
                "faster_whisper": {
                    "cache_dir": str(models.faster_whisper.cache_dir),
                    "default_model": models.faster_whisper.default_model,
                    "default_device": models.faster_whisper.default_device,
                    "default_compute_type": models.faster_whisper.default_compute_type,
                }
            }
            if models is not None
            else {},
        }


@dataclass(frozen=True, slots=True)
class SecretCheck:
    reference: str
    resolved: bool
    display: str
    value_preview: str | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class ResolvedProvider:
    name: str
    type: str
    api_key: str | None
    base_url: str | None
    default_chat_model: str | None = None

    def request_payload(self) -> dict[str, object]:
        return {
            "name": self.name,
            "type": self.type,
            "api_key": self.api_key,
            "base_url": self.base_url,
            "default_chat_model": self.default_chat_model,
        }


@dataclass(frozen=True, slots=True)
class RuntimeContext:
    providers: dict[str, ResolvedProvider] = field(default_factory=dict)
    cache_root: Path | None = None
    faster_whisper_cache_dir: Path | None = None
    redaction_values: tuple[str, ...] = ()

    def request_payload(self) -> dict[str, object]:
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


@dataclass(frozen=True, slots=True)
class ModelAssetStatus:
    provider: str
    model: str
    cache_dir: Path
    present: bool
    size_bytes: int = 0
    error: str | None = None

    def public_dict(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "model": self.model,
            "cache_dir": str(self.cache_dir),
            "present": self.present,
            "size_bytes": self.size_bytes,
            "error": self.error,
        }


@dataclass(frozen=True, slots=True)
class DoctorCheck:
    id: str
    status: str
    severity: str
    message: str

    def public_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "status": self.status,
            "severity": self.severity,
            "message": self.message,
        }
