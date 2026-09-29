"""Tests for the environments in `tools.regression_tests.environments`."""

import pytest

from tools.regression_tests.environments import Environment, load_environments


def test_environments_file_includes_dev():
    assert "dev" in load_environments()


@pytest.mark.parametrize("base_url", ["https://test", "https://test/"])
def test_urls_are_built_from_the_base_url(base_url):
    environment = Environment(base_url=base_url)

    assert environment.search_url == "https://test/api/natural_language_search_function"
    assert environment.health_check_url == "https://test/health_check"
