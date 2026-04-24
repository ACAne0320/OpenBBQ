from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import importlib.util
import os
from pathlib import Path
import shutil

from openbbq.domain.models import ProjectConfig, WorkflowConfig
from openbbq.errors import ValidationError
from openbbq.plugins.registry import PluginRegistry
from openbbq.runtime.models import DoctorCheck, RuntimeSettings
from openbbq.runtime.provider import LEGACY_PROVIDER_NAME
from openbbq.runtime.secrets import SecretResolver

LLM_TOOL_REFS = {"translation.translate", "llm.translate", "transcript.correct"}


@dataclass(frozen=True, slots=True)
class DoctorProbes:
    env: Mapping[str, str] | None = None
    which: Callable[[str], str | None] = shutil.which
    importable: Callable[[str], bool] | None = None
    path_writable: Callable[[Path], bool] | None = None


def check_workflow(
    *,
    config: ProjectConfig,
    registry: PluginRegistry,
    workflow_id: str,
    settings: RuntimeSettings,
    probes: DoctorProbes | None = None,
) -> list[DoctorCheck]:
    probes = probes or DoctorProbes()
    workflow = config.workflows.get(workflow_id)
    if workflow is None:
        raise ValidationError(f"Workflow '{workflow_id}' is not defined.")
    tool_refs = {step.tool_ref for step in workflow.steps}
    checks: list[DoctorCheck] = [_project_storage_check(config)]
    if any(tool_ref == "ffmpeg.extract_audio" for tool_ref in tool_refs):
        checks.append(_binary_check("ffmpeg", probes))
    if any(tool_ref == "remote_video.download" for tool_ref in tool_refs):
        checks.append(_import_check("yt_dlp", "python.yt_dlp", probes))
    if any(tool_ref == "faster_whisper.transcribe" for tool_ref in tool_refs):
        checks.append(_import_check("faster_whisper", "python.faster_whisper", probes))
        checks.append(_cache_writable_check(settings, probes))
    if _workflow_uses_llm(workflow):
        checks.extend(_provider_checks(settings, probes, workflow))
    return checks


def _workflow_uses_llm(workflow: WorkflowConfig) -> bool:
    return any(step.tool_ref in LLM_TOOL_REFS for step in workflow.steps)


def _provider_checks(
    settings: RuntimeSettings,
    probes: DoctorProbes,
    workflow: WorkflowConfig,
) -> list[DoctorCheck]:
    env = probes.env if probes.env is not None else os.environ
    named_providers: set[str] = set()
    uses_legacy_provider = False
    for step in workflow.steps:
        if step.tool_ref not in LLM_TOOL_REFS:
            continue
        provider_name = step.parameters.get("provider")
        if (
            isinstance(provider_name, str)
            and provider_name.strip()
            and provider_name.strip() != LEGACY_PROVIDER_NAME
        ):
            named_providers.add(provider_name.strip())
            continue
        uses_legacy_provider = True

    checks: list[DoctorCheck] = []
    resolver = SecretResolver(env=env)
    for name in sorted(named_providers):
        provider = settings.providers.get(name)
        if provider is None:
            checks.append(
                DoctorCheck(
                    id=f"provider.{name}.configured",
                    status="failed",
                    severity="error",
                    message=f"Provider '{name}' is not configured in runtime settings.",
                )
            )
            continue
        if provider.api_key is None:
            checks.append(
                DoctorCheck(
                    id=f"provider.{name}.api_key",
                    status="failed",
                    severity="error",
                    message=f"Provider '{name}' does not define an api_key secret reference.",
                )
            )
            continue
        resolved = resolver.resolve(provider.api_key)
        checks.append(
            DoctorCheck(
                id=f"provider.{name}.api_key",
                status="passed" if resolved.resolved else "failed",
                severity="error",
                message=(
                    f"Provider '{name}' API key is resolved."
                    if resolved.resolved
                    else resolved.public.error or f"Provider '{name}' API key is not resolved."
                ),
            )
        )
    if uses_legacy_provider:
        checks.append(
            DoctorCheck(
                id="provider.openai_compatible.api_key",
                status="passed" if env.get("OPENBBQ_LLM_API_KEY") else "failed",
                severity="error",
                message=(
                    "OPENBBQ_LLM_API_KEY is set."
                    if env.get("OPENBBQ_LLM_API_KEY")
                    else "OPENBBQ_LLM_API_KEY is not set."
                ),
            )
        )
    return checks


def _project_storage_check(config: ProjectConfig) -> DoctorCheck:
    return DoctorCheck(
        id="project.storage",
        status="passed",
        severity="error",
        message=f"Project storage root is {config.storage.root}.",
    )


def _binary_check(name: str, probes: DoctorProbes) -> DoctorCheck:
    path = probes.which(name)
    return DoctorCheck(
        id=f"binary.{name}",
        status="passed" if path else "failed",
        severity="error",
        message=f"{name} is available at {path}." if path else f"{name} was not found on PATH.",
    )


def _import_check(module_name: str, check_id: str, probes: DoctorProbes) -> DoctorCheck:
    importable = probes.importable
    present = (
        importable(module_name)
        if importable is not None
        else importlib.util.find_spec(module_name) is not None
    )
    return DoctorCheck(
        id=check_id,
        status="passed" if present else "failed",
        severity="error",
        message=(
            f"Python module '{module_name}' is importable."
            if present
            else f"Python module '{module_name}' is not importable."
        ),
    )


def _cache_writable_check(settings: RuntimeSettings, probes: DoctorProbes) -> DoctorCheck:
    cache_dir = (
        settings.models.faster_whisper.cache_dir
        if settings.models is not None
        else settings.cache.root / "models" / "faster-whisper"
    )
    writable_probe = probes.path_writable or _path_writable
    writable = writable_probe(cache_dir)
    return DoctorCheck(
        id="model.faster_whisper.cache_writable",
        status="passed" if writable else "failed",
        severity="error",
        message=(
            f"faster-whisper cache directory is writable: {cache_dir}."
            if writable
            else f"faster-whisper cache directory is not writable: {cache_dir}."
        ),
    )


def _path_writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".openbbq-write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError:
        return False
    return True
