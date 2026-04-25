from __future__ import annotations

import argparse
import getpass
from pathlib import Path

from openbbq.application.diagnostics import doctor as doctor_command
from openbbq.application.runtime import (
    AuthSetRequest,
    ProviderSetRequest,
    SecretSetRequest,
    auth_check as auth_check_command,
    auth_set as auth_set_command,
    model_list as model_list_command,
    provider_set as provider_set_command,
    secret_check as secret_check_command,
    secret_set as secret_set_command,
    settings_show as settings_show_command,
)
from openbbq.cli.output import emit
from openbbq.errors import ValidationError


def register(subparsers, parents) -> None:
    settings = subparsers.add_parser("settings", parents=parents)
    settings_sub = settings.add_subparsers(dest="settings_command", required=True)
    settings_sub.add_parser("show", parents=parents)
    settings_provider = settings_sub.add_parser("set-provider", parents=parents)
    settings_provider.add_argument("name")
    settings_provider.add_argument("--type", required=True)
    settings_provider.add_argument("--base-url")
    settings_provider.add_argument("--api-key")
    settings_provider.add_argument("--default-chat-model")
    settings_provider.add_argument("--display-name")

    auth = subparsers.add_parser("auth", parents=parents)
    auth_sub = auth.add_subparsers(dest="auth_command", required=True)
    auth_set = auth_sub.add_parser("set", parents=parents)
    auth_set.add_argument("name")
    auth_set.add_argument("--type", default="openai_compatible")
    auth_set.add_argument("--base-url")
    auth_set.add_argument("--api-key-ref")
    auth_set.add_argument("--default-chat-model")
    auth_set.add_argument("--display-name")
    auth_check = auth_sub.add_parser("check", parents=parents)
    auth_check.add_argument("name")

    secret = subparsers.add_parser("secret", parents=parents)
    secret_sub = secret.add_subparsers(dest="secret_command", required=True)
    secret_check = secret_sub.add_parser("check", parents=parents)
    secret_check.add_argument("reference")
    secret_set = secret_sub.add_parser("set", parents=parents)
    secret_set.add_argument("reference")

    models = subparsers.add_parser("models", parents=parents)
    models_sub = models.add_subparsers(dest="models_command", required=True)
    models_sub.add_parser("list", parents=parents)

    doctor = subparsers.add_parser("doctor", parents=parents)
    doctor.add_argument("--workflow")


def dispatch(args) -> int | None:
    if args.command == "settings":
        if args.settings_command == "show":
            return _settings_show(args)
        if args.settings_command == "set-provider":
            return _settings_set_provider(args)
        return 2
    if args.command == "auth":
        if args.auth_command == "set":
            return _auth_set(args)
        if args.auth_command == "check":
            return _auth_check(args)
        return 2
    if args.command == "secret":
        if args.secret_command == "check":
            return _secret_check(args)
        if args.secret_command == "set":
            return _secret_set(args)
        return 2
    if args.command == "models":
        if args.models_command == "list":
            return _models_list(args)
        return 2
    if args.command == "doctor":
        return _doctor(args)
    return None


def _settings_show(args: argparse.Namespace) -> int:
    result = settings_show_command()
    payload = {"ok": True, "settings": result.settings.public_dict()}
    emit(payload, args.json_output, str(result.settings.config_path))
    return 0


def _settings_set_provider(args: argparse.Namespace) -> int:
    result = provider_set_command(
        ProviderSetRequest(
            name=args.name,
            type=args.type,
            base_url=args.base_url,
            api_key=args.api_key,
            default_chat_model=args.default_chat_model,
            display_name=args.display_name,
        )
    )
    payload = {
        "ok": True,
        "provider": result.provider.public_dict(),
        "config_path": str(result.config_path),
    }
    emit(payload, args.json_output, f"Updated provider '{result.provider.name}'.")
    return 0


def _auth_set(args: argparse.Namespace) -> int:
    secret_value = None
    if args.api_key_ref is None:
        if args.json_output:
            raise ValidationError("auth set requires --api-key-ref when --json is used.")
        secret_value = getpass.getpass("API key: ")
    result = auth_set_command(
        AuthSetRequest(
            name=args.name,
            type=args.type,
            base_url=args.base_url,
            api_key_ref=args.api_key_ref,
            secret_value=secret_value,
            default_chat_model=args.default_chat_model,
            display_name=args.display_name,
        )
    )
    payload = {
        "ok": True,
        "provider": result.provider.public_dict(),
        "secret_stored": result.secret_stored,
        "config_path": str(result.config_path),
    }
    emit(payload, args.json_output, f"Configured provider '{result.provider.name}'.")
    return 0


def _auth_check(args: argparse.Namespace) -> int:
    result = auth_check_command(args.name)
    secret = _secret_payload(result.secret)
    payload = {"ok": True, "provider": result.provider.public_dict(), "secret": secret}
    text = secret["value_preview"] if secret["resolved"] else secret["error"]
    emit(payload, args.json_output, text)
    return 0


def _secret_check(args: argparse.Namespace) -> int:
    result = secret_check_command(args.reference)
    payload = {"ok": True, "secret": _secret_payload(result.secret)}
    emit(payload, args.json_output, result.secret.display)
    return 0


def _secret_set(args: argparse.Namespace) -> int:
    if args.json_output:
        raise ValidationError("secret set requires interactive input and cannot run in JSON mode.")
    value = getpass.getpass("Secret value: ")
    secret_set_command(SecretSetRequest(reference=args.reference, value=value))
    emit({"ok": True, "reference": args.reference}, args.json_output, "Secret stored.")
    return 0


def _models_list(args: argparse.Namespace) -> int:
    result = model_list_command()
    payload = {"ok": True, "models": [model.public_dict() for model in result.models]}
    emit(payload, args.json_output, result.models[0].public_dict())
    return 0


def _doctor(args: argparse.Namespace) -> int:
    result = doctor_command(
        project_root=Path(args.project),
        config_path=Path(args.config) if args.config else None,
        plugin_paths=tuple(Path(path) for path in args.plugins),
        workflow_id=args.workflow,
    )
    payload = {
        "ok": result.ok,
        "checks": [check.public_dict() for check in result.checks],
    }
    emit(payload, args.json_output, "\n".join(check.message for check in result.checks))
    return 0 if payload["ok"] else 1


def _secret_payload(secret) -> dict[str, object]:
    return {
        "reference": secret.reference or None,
        "resolved": secret.resolved,
        "display": secret.display or None,
        "value_preview": secret.value_preview,
        "error": secret.error,
    }
