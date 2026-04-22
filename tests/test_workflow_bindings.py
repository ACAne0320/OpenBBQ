from pathlib import Path

from openbbq.config import load_project_config
from openbbq.core.workflow.bindings import build_plugin_inputs, persist_step_outputs
from openbbq.plugins import discover_plugins
from openbbq.storage import ProjectStore


def test_build_plugin_inputs_resolves_literals_and_artifacts(tmp_path):
    config = load_project_config(Path("tests/fixtures/projects/text-basic"))
    workflow = config.workflows["text-demo"]
    seed_step = workflow.steps[0]
    uppercase_step = workflow.steps[1]
    store = ProjectStore(tmp_path / ".openbbq")
    artifact, version = store.write_artifact_version(
        artifact_type="text",
        name="seed.text",
        content="hello openbbq",
        metadata={},
        created_by_step_id="seed",
        lineage={"workflow_id": "text-demo"},
    )

    literal_inputs, literal_versions = build_plugin_inputs(store, seed_step, {})
    artifact_inputs, artifact_versions = build_plugin_inputs(
        store,
        uppercase_step,
        {
            "seed.text": {
                "artifact_id": artifact.id,
                "artifact_version_id": version.id,
            }
        },
    )

    assert literal_inputs["text"] == {"literal": "hello openbbq"}
    assert literal_versions == {}
    assert artifact_inputs["text"]["content"] == "hello openbbq"
    assert artifact_versions == {"seed.text": version.id}


def test_persist_step_outputs_writes_declared_artifact_version(tmp_path):
    config = load_project_config(Path("tests/fixtures/projects/text-basic"))
    registry = discover_plugins(config.plugin_paths)
    step = config.workflows["text-demo"].steps[0]
    tool = registry.tools[step.tool_ref]
    store = ProjectStore(tmp_path / ".openbbq")

    bindings = persist_step_outputs(
        store,
        "text-demo",
        step,
        tool,
        {"outputs": {"text": {"type": "text", "content": "hello openbbq", "metadata": {}}}},
        {},
    )

    version = store.read_artifact_version(bindings["text"]["artifact_version_id"])
    assert version.content == "hello openbbq"
