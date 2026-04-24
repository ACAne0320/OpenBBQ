from pathlib import Path

from pydantic import ValidationError as PydanticValidationError

from openbbq.config.loader import load_project_config
from openbbq.domain.models import StepConfig, StepOutput
from openbbq.errors import ValidationError
from openbbq.plugins.payloads import PluginOutputPayload, PluginResponse
from openbbq.plugins.registry import ToolSpec
from openbbq.workflow.bindings import build_plugin_inputs, persist_step_outputs
from openbbq.plugins.registry import discover_plugins
from openbbq.storage.project_store import ProjectStore
import pytest


def test_plugin_response_requires_outputs_object():
    with pytest.raises(PydanticValidationError):
        PluginResponse.model_validate({"pause_requested": False})


def test_plugin_output_payload_requires_exactly_one_payload(tmp_path):
    with pytest.raises(PydanticValidationError):
        PluginOutputPayload(type="text")

    with pytest.raises(PydanticValidationError):
        PluginOutputPayload(type="text", content="hello", file_path=tmp_path / "content.txt")

    assert PluginOutputPayload(type="text", content="hello").content == "hello"


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


def test_build_plugin_inputs_passes_file_path_for_file_backed_artifact(tmp_path):
    store = ProjectStore(tmp_path / ".openbbq")
    source = tmp_path / "audio.wav"
    source.write_bytes(b"audio")
    artifact, version = store.write_artifact_version(
        artifact_type="audio",
        name="audio.source",
        content=None,
        file_path=source,
        metadata={"format": "wav"},
        created_by_step_id=None,
        lineage={"source": "test"},
    )
    step = StepConfig(
        id="transcribe",
        name="Transcribe",
        tool_ref="faster_whisper.transcribe",
        inputs={"audio": f"project.{artifact.id}"},
        outputs=(StepOutput(name="transcript", type="asr_transcript"),),
        parameters={},
        on_error="abort",
        max_retries=0,
    )

    inputs, input_versions = build_plugin_inputs(store, step, {})

    assert inputs["audio"]["file_path"] == str(version.content["file_path"])
    assert "content" not in inputs["audio"]
    assert input_versions[f"project.{artifact.id}"] == version.id


def test_persist_step_outputs_accepts_file_path_payload(tmp_path):
    store = ProjectStore(tmp_path / ".openbbq")
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"audio")
    step = StepConfig(
        id="extract_audio",
        name="Extract Audio",
        tool_ref="ffmpeg.extract_audio",
        inputs={},
        outputs=(StepOutput(name="audio", type="audio"),),
        parameters={},
        on_error="abort",
        max_retries=0,
    )
    tool = ToolSpec(
        plugin_name="ffmpeg",
        name="extract_audio",
        description="Extract audio",
        input_artifact_types=["video"],
        output_artifact_types=["audio"],
        parameter_schema={},
        effects=["reads_files", "writes_files"],
        manifest_path=tmp_path / "openbbq.plugin.toml",
    )

    bindings = persist_step_outputs(
        store,
        "workflow",
        step,
        tool,
        {"outputs": {"audio": {"type": "audio", "file_path": str(audio), "metadata": {}}}},
        {},
    )

    version = store.read_artifact_version(bindings["audio"]["artifact_version_id"])
    assert version.record["content_encoding"] == "file"
    assert Path(version.content["file_path"]).read_bytes() == b"audio"


def test_persist_step_outputs_rejects_content_and_file_path_together(tmp_path):
    store = ProjectStore(tmp_path / ".openbbq")
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"audio")
    step = StepConfig(
        id="extract_audio",
        name="Extract Audio",
        tool_ref="ffmpeg.extract_audio",
        inputs={},
        outputs=(StepOutput(name="audio", type="audio"),),
        parameters={},
        on_error="abort",
        max_retries=0,
    )
    tool = ToolSpec(
        plugin_name="ffmpeg",
        name="extract_audio",
        description="Extract audio",
        input_artifact_types=["video"],
        output_artifact_types=["audio"],
        parameter_schema={},
        effects=[],
        manifest_path=tmp_path / "openbbq.plugin.toml",
    )

    with pytest.raises(ValidationError, match="exactly one"):
        persist_step_outputs(
            store,
            "workflow",
            step,
            tool,
            {
                "outputs": {
                    "audio": {
                        "type": "audio",
                        "content": b"audio",
                        "file_path": str(audio),
                    }
                }
            },
            {},
        )
