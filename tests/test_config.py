from pathlib import Path

import pytest

from openbbq.config.loader import load_project_config
from openbbq.errors import ValidationError


def test_load_text_basic_defaults():
    config = load_project_config(Path("tests/fixtures/projects/text-basic"))
    assert config.project.name == "Text Basic"
    assert config.storage.root.name == ".openbbq"
    assert config.workflows["text-demo"].steps[0].id == "seed"


def test_rejects_invalid_step_id(tmp_path):
    (tmp_path / "openbbq.yaml").write_text(
        "version: 1\nproject: {name: Bad}\nworkflows:\n  demo:\n    name: Demo\n"
        "    steps:\n      - id: Bad ID\n        name: Bad\n        tool_ref: x.y\n"
        "        outputs: [{name: out, type: text}]\n"
    )
    with pytest.raises(ValidationError) as exc:
        load_project_config(tmp_path)
    assert "step id" in str(exc.value).lower()


@pytest.mark.parametrize("version_value", ["true", "1.0"])
def test_rejects_non_integer_version(tmp_path, version_value):
    (tmp_path / "openbbq.yaml").write_text(
        f"version: {version_value}\n"
        "project: {name: Bad}\n"
        "workflows:\n"
        "  demo:\n"
        "    name: Demo\n"
        "    steps:\n"
        "      - id: seed\n"
        "        name: Seed\n"
        "        tool_ref: x.y\n"
        "        outputs: [{name: out, type: text}]\n"
    )
    with pytest.raises(ValidationError) as exc:
        load_project_config(tmp_path)
    assert "version" in str(exc.value).lower()


def test_rejects_duplicate_step_ids(tmp_path):
    (tmp_path / "openbbq.yaml").write_text(
        "version: 1\n"
        "project: {name: Bad}\n"
        "workflows:\n"
        "  demo:\n"
        "    name: Demo\n"
        "    steps:\n"
        "      - id: seed\n"
        "        name: Seed\n"
        "        tool_ref: x.y\n"
        "        outputs: [{name: out, type: text}]\n"
        "      - id: seed\n"
        "        name: Duplicate Seed\n"
        "        tool_ref: x.y\n"
        "        outputs: [{name: out, type: text}]\n"
    )
    with pytest.raises(ValidationError) as exc:
        load_project_config(tmp_path)
    assert "duplicate step id" in str(exc.value).lower()


def test_rejects_forward_step_input_reference(tmp_path):
    (tmp_path / "openbbq.yaml").write_text(
        "version: 1\n"
        "project: {name: Bad}\n"
        "workflows:\n"
        "  demo:\n"
        "    name: Demo\n"
        "    steps:\n"
        "      - id: seed\n"
        "        name: Seed\n"
        "        tool_ref: x.y\n"
        "        inputs: {text: later.out}\n"
        "        outputs: [{name: out, type: text}]\n"
        "      - id: later\n"
        "        name: Later\n"
        "        tool_ref: x.y\n"
        "        outputs: [{name: out, type: text}]\n"
    )
    with pytest.raises(ValidationError) as exc:
        load_project_config(tmp_path)
    assert "forward reference" in str(exc.value).lower()


def test_accepts_project_artifact_selector(tmp_path):
    (tmp_path / "openbbq.yaml").write_text(
        "version: 1\n"
        "project: {name: Bad}\n"
        "workflows:\n"
        "  demo:\n"
        "    name: Demo\n"
        "    steps:\n"
        "      - id: seed\n"
        "        name: Seed\n"
        "        tool_ref: x.y\n"
        "        inputs: {text: hello world}\n"
        "        outputs: [{name: out, type: text}]\n"
        "      - id: glossary_step\n"
        "        name: Glossary\n"
        "        tool_ref: x.y\n"
        "        inputs: {glossary: project.art_123}\n"
        "        outputs: [{name: out, type: text}]\n"
    )

    config = load_project_config(tmp_path)

    assert config.workflows["demo"].steps[1].inputs["glossary"] == "project.art_123"


def test_rejects_missing_output_selector(tmp_path):
    (tmp_path / "openbbq.yaml").write_text(
        "version: 1\n"
        "project: {name: Bad}\n"
        "workflows:\n"
        "  demo:\n"
        "    name: Demo\n"
        "    steps:\n"
        "      - id: seed\n"
        "        name: Seed\n"
        "        tool_ref: x.y\n"
        "        outputs: [{name: out, type: text}]\n"
        "      - id: use_seed\n"
        "        name: Use Seed\n"
        "        tool_ref: x.y\n"
        "        inputs: {text: seed.missing_output}\n"
        "        outputs: [{name: out, type: text}]\n"
    )

    with pytest.raises(ValidationError) as exc:
        load_project_config(tmp_path)

    assert "missing_output" in str(exc.value).lower()


def test_missing_config_file_raises_validation_error(tmp_path):
    with pytest.raises(ValidationError) as exc:
        load_project_config(tmp_path)

    assert "openbbq.yaml" in str(exc.value)


def test_malformed_yaml_raises_validation_error(tmp_path):
    (tmp_path / "openbbq.yaml").write_text("version: [")

    with pytest.raises(ValidationError) as exc:
        load_project_config(tmp_path)

    assert "yaml" in str(exc.value).lower()


def test_rejects_non_string_plugin_path_entry(tmp_path):
    (tmp_path / "openbbq.yaml").write_text(
        "version: 1\n"
        "project: {name: Bad}\n"
        "plugins:\n"
        "  paths: [123]\n"
        "workflows:\n"
        "  demo:\n"
        "    name: Demo\n"
        "    steps:\n"
        "      - id: seed\n"
        "        name: Seed\n"
        "        tool_ref: x.y\n"
        "        outputs: [{name: out, type: text}]\n"
    )

    with pytest.raises(ValidationError) as exc:
        load_project_config(tmp_path)

    assert "plugins.paths" in str(exc.value).lower()


def test_rejects_invalid_storage_path_value(tmp_path):
    (tmp_path / "openbbq.yaml").write_text(
        "version: 1\n"
        "project: {name: Bad}\n"
        "storage:\n"
        "  root: [123]\n"
        "workflows:\n"
        "  demo:\n"
        "    name: Demo\n"
        "    steps:\n"
        "      - id: seed\n"
        "        name: Seed\n"
        "        tool_ref: x.y\n"
        "        outputs: [{name: out, type: text}]\n"
    )

    with pytest.raises(ValidationError) as exc:
        load_project_config(tmp_path)

    assert "storage.root" in str(exc.value).lower()
