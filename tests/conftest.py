"""Keep persistent user demo cases isolated from the test databases."""

import pytest

from loanpilot import config


@pytest.fixture(scope="session", autouse=True)
def isolate_persistent_custom_cases(tmp_path_factory):
    """Prevent local permanent cases from changing deterministic fixture counts."""
    original = config.CUSTOM_CASES_PATH
    config.CUSTOM_CASES_PATH = (
        tmp_path_factory.mktemp("isolated-custom-cases") / "custom_cases.json"
    )
    yield
    config.CUSTOM_CASES_PATH = original
