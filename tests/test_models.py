from dataclasses import is_dataclass

from openbbq.domain import models


def test_domain_models_exports_phase1_dataclasses():
    exported_names = {
        "ProjectMetadata",
        "StorageConfig",
        "PluginConfig",
        "StepOutput",
        "StepConfig",
        "WorkflowConfig",
        "ProjectConfig",
    }

    for name in exported_names:
        exported = getattr(models, name)

        assert is_dataclass(exported)


def test_domain_models_exports_artifact_type_registry():
    assert {
        "text",
        "video",
        "audio",
        "asr_transcript",
        "glossary",
        "translation",
        "subtitle",
    }.issubset(models.ARTIFACT_TYPES)
