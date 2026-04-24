from pathlib import Path

import pytest
from pydantic import ValidationError as PydanticValidationError

from openbbq.domain import models
from openbbq.domain.base import OpenBBQModel, format_pydantic_error


class ExampleModel(OpenBBQModel):
    name: str


def test_openbbq_model_is_frozen_and_forbids_extra_fields():
    value = ExampleModel(name="demo")

    with pytest.raises(PydanticValidationError):
        value.name = "changed"

    with pytest.raises(PydanticValidationError):
        ExampleModel(name="demo", extra=True)


def test_format_pydantic_error_includes_entity_and_field_path():
    with pytest.raises(PydanticValidationError) as exc:
        ExampleModel()

    assert format_pydantic_error("example", exc.value) == "example.name: Field required"


def test_domain_models_exports_artifact_type_registry():
    assert {
        "text",
        "video",
        "audio",
        "image",
        "asr_transcript",
        "subtitle_segments",
        "glossary",
        "translation",
        "translation_qa",
        "subtitle",
    }.issubset(models.ARTIFACT_TYPES)


def test_domain_models_export_pydantic_models():
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

        assert issubclass(exported, OpenBBQModel)


def test_domain_models_dump_paths_as_strings():
    storage = models.StorageConfig(
        root=Path(".openbbq"),
        artifacts=Path(".openbbq/artifacts"),
        state=Path(".openbbq/state"),
    )

    assert storage.model_dump(mode="json") == {
        "root": str(Path(".openbbq")),
        "artifacts": str(Path(".openbbq/artifacts")),
        "state": str(Path(".openbbq/state")),
    }


def test_step_config_rejects_bool_max_retries():
    with pytest.raises(PydanticValidationError) as exc:
        models.StepConfig(
            id="seed",
            name="Seed",
            tool_ref="mock_text.echo",
            outputs=(models.StepOutput(name="text", type="text"),),
            max_retries=True,
        )

    assert "max_retries" in str(exc.value)


def test_step_config_rejects_duplicate_output_names():
    with pytest.raises(PydanticValidationError) as exc:
        models.StepConfig(
            id="seed",
            name="Seed",
            tool_ref="mock_text.echo",
            outputs=(
                models.StepOutput(name="text", type="text"),
                models.StepOutput(name="text", type="text"),
            ),
        )

    assert "Duplicate output name" in str(exc.value)


def test_project_config_rejects_non_one_version(tmp_path):
    with pytest.raises(PydanticValidationError) as exc:
        models.ProjectConfig(
            version=2,
            root_path=tmp_path,
            config_path=tmp_path / "openbbq.yaml",
            project=models.ProjectMetadata(name="Demo"),
            storage=models.StorageConfig(
                root=tmp_path / ".openbbq",
                artifacts=tmp_path / ".openbbq" / "artifacts",
                state=tmp_path / ".openbbq" / "state",
            ),
            plugins=models.PluginConfig(),
            workflows={},
        )

    assert "version" in str(exc.value)
