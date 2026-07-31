import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--hw", action="store_true", default=False,
        help="run tests that require a physical WaveAnalyzer 1500S",
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--hw"):
        return
    skip_hw = pytest.mark.skip(reason="requires physical instrument (use --hw)")
    for item in items:
        if "hw" in item.keywords:
            item.add_marker(skip_hw)
