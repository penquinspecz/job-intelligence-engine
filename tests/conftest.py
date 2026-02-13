import os

import pytest

_AWS_TEST_ENV_DEFAULTS = {
    "AWS_EC2_METADATA_DISABLED": "true",
    "AWS_CONFIG_FILE": "/dev/null",
    "AWS_SHARED_CREDENTIALS_FILE": "/dev/null",
}


def pytest_addoption(parser) -> None:
    parser.addoption(
        "--run-aws-integration",
        action="store_true",
        default=False,
        help="run tests marked aws_integration (live AWS credentials/network required)",
    )


def pytest_configure(config) -> None:
    # Register marker in code so Docker/alternate test harnesses without pytest.ini stay consistent.
    config.addinivalue_line(
        "markers",
        "aws_integration: requires live AWS credentials/network access; skipped unless --run-aws-integration is provided",
    )
    # Test-only offline defaults: avoid AWS credential/provider discovery side effects.
    for key, value in _AWS_TEST_ENV_DEFAULTS.items():
        os.environ.setdefault(key, value)


def pytest_collection_modifyitems(config, items) -> None:
    if config.getoption("--run-aws-integration"):
        return

    skip_live = pytest.mark.skip(reason="requires --run-aws-integration (live AWS opt-in)")
    for item in items:
        if "aws_integration" in item.keywords:
            item.add_marker(skip_live)


@pytest.fixture(autouse=True)
def _clear_output_dir_env(monkeypatch) -> None:
    monkeypatch.delenv("JOBINTEL_OUTPUT_DIR", raising=False)
