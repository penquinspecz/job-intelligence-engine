import pytest


@pytest.fixture(autouse=True)
def _clear_output_dir_env(monkeypatch) -> None:
    monkeypatch.delenv("JOBINTEL_OUTPUT_DIR", raising=False)
