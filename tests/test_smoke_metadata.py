from scripts.smoke_metadata import RUN_REPORT_SCHEMA_VERSION, build_metadata


def test_build_metadata_defaults() -> None:
    payload = build_metadata(["openai"], ["cs"])

    assert payload["providers"] == ["openai"]
    assert payload["profiles"] == ["cs"]
    assert payload["run_report_schema_version"] == RUN_REPORT_SCHEMA_VERSION
    assert payload["smoke_contract_version"] == 1
