from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import os
from typing import Protocol

from openbbq.errors import ValidationError
from openbbq.runtime.models import SecretCheck


class KeyringBackend(Protocol):
    def get_password(self, service_name: str, username: str) -> str | None: ...

    def set_password(self, service_name: str, username: str, password: str) -> None: ...


@dataclass(frozen=True, slots=True)
class ResolvedSecret:
    reference: str
    resolved: bool
    value: str | None
    public: SecretCheck


_UNSET = object()


class SecretResolver:
    def __init__(
        self,
        *,
        env: Mapping[str, str] | None = None,
        keyring_backend: KeyringBackend | object | None = _UNSET,
    ) -> None:
        self.env = os.environ if env is None else env
        self.keyring_backend = _load_keyring() if keyring_backend is _UNSET else keyring_backend

    def resolve(self, reference: str) -> ResolvedSecret:
        if reference.startswith("env:"):
            name = reference.removeprefix("env:")
            if not name:
                raise ValidationError("env secret reference must include a variable name.")
            value = self.env.get(name)
            if value is None:
                return ResolvedSecret(
                    reference=reference,
                    resolved=False,
                    value=None,
                    public=SecretCheck(
                        reference=reference,
                        resolved=False,
                        display=reference,
                        error=f"Environment variable '{name}' is not set.",
                    ),
                )
            return ResolvedSecret(
                reference=reference,
                resolved=True,
                value=value,
                public=SecretCheck(
                    reference=reference,
                    resolved=True,
                    display=reference,
                    value_preview=_preview(value),
                ),
            )
        if reference.startswith("keyring:"):
            service, username = _parse_keyring_reference(reference)
            if self.keyring_backend is None:
                return ResolvedSecret(
                    reference=reference,
                    resolved=False,
                    value=None,
                    public=SecretCheck(
                        reference=reference,
                        resolved=False,
                        display=reference,
                        error="Python keyring support is not installed or not available.",
                    ),
                )
            try:
                value = self.keyring_backend.get_password(service, username)
            except Exception as exc:
                return ResolvedSecret(
                    reference=reference,
                    resolved=False,
                    value=None,
                    public=SecretCheck(
                        reference=reference,
                        resolved=False,
                        display=reference,
                        error=f"Keyring secret '{reference}' could not be read: {exc}",
                    ),
                )
            if value is None:
                return ResolvedSecret(
                    reference=reference,
                    resolved=False,
                    value=None,
                    public=SecretCheck(
                        reference=reference,
                        resolved=False,
                        display=reference,
                        error=f"Keyring secret '{reference}' was not found.",
                    ),
                )
            return ResolvedSecret(
                reference=reference,
                resolved=True,
                value=value,
                public=SecretCheck(
                    reference=reference,
                    resolved=True,
                    display=reference,
                    value_preview=_preview(value),
                ),
            )
        raise ValidationError("Unsupported secret reference scheme. Use env: or keyring:.")

    def set_secret(self, reference: str, value: str) -> None:
        if not reference.startswith("keyring:"):
            raise ValidationError("Only keyring: secret references can be set by OpenBBQ.")
        if not value:
            raise ValidationError("Secret value must be non-empty.")
        service, username = _parse_keyring_reference(reference)
        if self.keyring_backend is None:
            raise ValidationError("Python keyring support is not installed or not available.")
        try:
            self.keyring_backend.set_password(service, username, value)
        except Exception as exc:
            raise ValidationError(
                f"Keyring secret '{reference}' could not be stored: {exc}"
            ) from exc


def _parse_keyring_reference(reference: str) -> tuple[str, str]:
    payload = reference.removeprefix("keyring:")
    service, separator, username = payload.partition("/")
    if not separator or not service or not username:
        raise ValidationError("keyring secret reference must be keyring:<service>/<username>.")
    return service, username


def _load_keyring() -> KeyringBackend | None:
    try:
        import keyring
    except ImportError:
        return None
    return keyring


def _preview(value: str) -> str:
    if len(value) <= 4:
        return "[REDACTED]"
    return f"{value[:3]}...{value[-4:]}"
