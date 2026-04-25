import os
from pathlib import Path

import pytest

from openbbq.config.loader import load_project_config
from openbbq.config.paths import (
    load_plugin_paths,
    merge_paths,
    normalize_plugin_paths,
    resolve_config_path,
    resolve_project_path,
)
from openbbq.config.raw import load_yaml_mapping
from openbbq.config.workflows import build_workflows
from openbbq.errors import ValidationError


def test_load_text_basic_defaults():
    config = load_project_config(Path("tests/fixtures/projects/text-basic"))
    assert config.project.name == "Text Basic"
    assert config.storage.root.name == ".openbbq"
    assert config.workflows["text-demo"].steps[0].id == "seed"


def test_load_yaml_mapping_reports_missing_file(tmp_path):
    missing = tmp_path / "missing.yaml"

    with pytest.raises(ValidationError) as exc:
        load_yaml_mapping(missing)

    assert str(missing) in str(exc.value)
    assert "was not found" in str(exc.value)


def test_load_yaml_mapping_reports_malformed_yaml(tmp_path):
    config = tmp_path / "openbbq.yaml"
    config.write_text("version: [", encoding="utf-8")

    with pytest.raises(ValidationError) as exc:
        load_yaml_mapping(config)

    assert "malformed yaml" in str(exc.value).lower()


def test_load_yaml_mapping_requires_mapping(tmp_path):
    config = tmp_path / "openbbq.yaml"
    config.write_text("- not\n- a\n- mapping\n", encoding="utf-8")

    with pytest.raises(ValidationError) as exc:
        load_yaml_mapping(config)

    assert "yaml mapping" in str(exc.value).lower()


def test_resolve_config_path_defaults_and_resolves_relative_path(tmp_path):
    assert resolve_config_path(tmp_path, None) == (tmp_path / "openbbq.yaml").resolve()
    assert resolve_config_path(tmp_path, "configs/demo.yaml") == (
        tmp_path / "configs/demo.yaml"
    ).resolve()


def test_resolve_project_path_rejects_non_path_value(tmp_path):
    with pytest.raises(ValidationError) as exc:
        resolve_project_path(tmp_path, ["bad"], "storage.root")

    assert "storage.root" in str(exc.value)
    assert "string path" in str(exc.value)


def test_normalize_plugin_paths_deduplicates_after_resolution(tmp_path):
    paths = normalize_plugin_paths(
        tmp_path,
        ["plugins", tmp_path / "plugins", "other"],
        "plugins.paths",
    )

    assert paths == [(tmp_path / "plugins").resolve(), (tmp_path / "other").resolve()]


def test_load_plugin_paths_uses_env_then_config_order(tmp_path):
    raw_config = {"plugins": {"paths": ["./plugins-a"]}}

    paths = load_plugin_paths(
        tmp_path,
        raw_config,
        {"OPENBBQ_PLUGIN_PATH": f"./plugins-b{os.pathsep}./plugins-c"},
    )

    assert [path.name for path in paths] == ["plugins-b", "plugins-c", "plugins-a"]


def test_merge_paths_preserves_preferred_then_fallback_order(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"

    assert merge_paths([first, second], [second, first]) == [first, second]


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


def test_build_workflows_rejects_duplicate_step_ids():
    raw_config = {
        "workflows": {
            "demo": {
                "name": "Demo",
                "steps": [
                    {
                        "id": "seed",
                        "name": "Seed",
                        "tool_ref": "x.y",
                        "outputs": [{"name": "out", "type": "text"}],
                    },
                    {
                        "id": "seed",
                        "name": "Duplicate",
                        "tool_ref": "x.y",
                        "outputs": [{"name": "out", "type": "text"}],
                    },
                ],
            }
        }
    }

    with pytest.raises(ValidationError) as exc:
        build_workflows(raw_config)

    assert "duplicate step id" in str(exc.value).lower()


def test_build_workflows_rejects_unregistered_output_type():
    raw_config = {
        "workflows": {
            "demo": {
                "name": "Demo",
                "steps": [
                    {
                        "id": "seed",
                        "name": "Seed",
                        "tool_ref": "x.y",
                        "outputs": [{"name": "out", "type": "unknown"}],
                    }
                ],
            }
        }
    }

    with pytest.raises(ValidationError) as exc:
        build_workflows(raw_config)

    assert "not registered" in str(exc.value).lower()


def test_build_workflows_rejects_forward_input_reference():
    raw_config = {
        "workflows": {
            "demo": {
                "name": "Demo",
                "steps": [
                    {
                        "id": "seed",
                        "name": "Seed",
                        "tool_ref": "x.y",
                        "inputs": {"text": "later.out"},
                        "outputs": [{"name": "out", "type": "text"}],
                    },
                    {
                        "id": "later",
                        "name": "Later",
                        "tool_ref": "x.y",
                        "outputs": [{"name": "out", "type": "text"}],
                    },
                ],
            }
        }
    }

    with pytest.raises(ValidationError) as exc:
        build_workflows(raw_config)

    assert "forward reference" in str(exc.value).lower()


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
