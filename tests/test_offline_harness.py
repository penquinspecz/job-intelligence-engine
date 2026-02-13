from __future__ import annotations

import os
from pathlib import Path


def test_aws_offline_env_defaults_are_present() -> None:
    # Values may be explicitly overridden by callers, but keys must always exist in tests.
    assert os.environ.get("AWS_EC2_METADATA_DISABLED")
    assert os.environ.get("AWS_CONFIG_FILE")
    assert os.environ.get("AWS_SHARED_CREDENTIALS_FILE")


def test_aws_integration_opt_in_is_disabled_by_default(pytestconfig) -> None:
    assert pytestconfig.getoption("--run-aws-integration") is False


def test_aws_integration_marker_registered(pytestconfig) -> None:
    markers = pytestconfig.getini("markers")
    assert any(str(marker).startswith("aws_integration") for marker in markers)


def test_default_test_state_dirs_are_isolated_from_repo_root() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    data_dir = Path(os.environ["JOBINTEL_DATA_DIR"]).resolve()
    state_dir = Path(os.environ["JOBINTEL_STATE_DIR"]).resolve()
    assert str(data_dir).startswith(("/tmp/", "/private/tmp/"))
    assert str(state_dir).startswith(("/tmp/", "/private/tmp/"))
    assert data_dir != (repo_root / "data").resolve()
    assert state_dir != (repo_root / "state").resolve()
