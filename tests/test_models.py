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
