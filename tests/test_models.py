from openbbq.domain import ProjectConfig as DomainProjectConfig
from openbbq.models.workflow import ProjectConfig


def test_workflow_models_reexport_domain_types():
    assert ProjectConfig is DomainProjectConfig
