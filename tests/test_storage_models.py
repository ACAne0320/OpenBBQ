from openbbq.storage.models import ArtifactRecord, OutputBinding, WorkflowState


def test_storage_models_dump_to_current_json_shape(tmp_path):
    state = WorkflowState(
        id="text-demo",
        name="Text Demo",
        status="running",
        current_step_id="seed",
        config_hash="abc",
        step_run_ids=("sr_1",),
    )

    assert state.model_dump(mode="json") == {
        "id": "text-demo",
        "name": "Text Demo",
        "status": "running",
        "current_step_id": "seed",
        "config_hash": "abc",
        "step_run_ids": ["sr_1"],
    }


def test_output_binding_is_typed():
    binding = OutputBinding(artifact_id="art_1", artifact_version_id="av_1")

    assert binding.artifact_id == "art_1"
    assert binding.model_dump(mode="json") == {
        "artifact_id": "art_1",
        "artifact_version_id": "av_1",
    }


def test_artifact_record_versions_are_tuple_for_internal_use():
    artifact = ArtifactRecord(
        id="art_1",
        type="text",
        name="seed.text",
        versions=["av_1"],
        current_version_id="av_1",
        created_by_step_id="seed",
        created_at="2026-04-24T00:00:00+00:00",
        updated_at="2026-04-24T00:00:00+00:00",
    )

    assert artifact.versions == ("av_1",)
