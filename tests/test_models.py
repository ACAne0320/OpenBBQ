from openbbq.domain.models import ProjectConfig as DomainProjectConfig
from openbbq.domain.models import ProjectConfig


def test_workflow_models_reexport_domain_types():
    assert ProjectConfig is DomainProjectConfig
