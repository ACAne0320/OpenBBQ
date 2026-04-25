from openbbq.application.project_context import (
    load_project_context,
    project_store_from_config,
)
from openbbq.config.loader import load_project_config
from tests.helpers import write_project_fixture


def test_project_store_from_config_uses_configured_storage_roots(tmp_path):
    project = write_project_fixture(tmp_path, "text-basic")
    config_path = project / "openbbq.yaml"
    source = config_path.read_text(encoding="utf-8")
    target = "storage:\n  root: .openbbq\n"
    assert target in source
    config_path.write_text(
        source.replace(
            target,
            "storage:\n"
            "  root: runtime-root\n"
            "  artifacts: artifact-store\n"
            "  state: workflow-state\n",
        ),
        encoding="utf-8",
    )
    config = load_project_config(project)

    store = project_store_from_config(config)

    assert store.root == project / "runtime-root"
    assert store.artifacts_root == project / "artifact-store"
    assert store.state_base == project / "workflow-state"


def test_load_project_context_applies_extra_plugin_paths(tmp_path):
    project = write_project_fixture(tmp_path, "text-basic")
    extra_plugins = tmp_path / "extra-plugins"
    extra_plugins.mkdir()

    context = load_project_context(project, plugin_paths=(extra_plugins,))

    assert context.config.root_path == project
    assert context.config.plugin_paths[0] == extra_plugins
    assert context.store.root == project / ".openbbq"
    assert context.store.artifacts_root == project / ".openbbq" / "artifacts"
    assert context.store.state_base == project / ".openbbq" / "state"
