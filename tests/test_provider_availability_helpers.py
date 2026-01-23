import scripts.run_daily as run_daily


def test_all_providers_unavailable_true() -> None:
    provenance = {"openai": {"availability": "unavailable"}}
    assert run_daily._all_providers_unavailable(provenance, ["openai"]) is True


def test_all_providers_unavailable_false() -> None:
    provenance = {"openai": {"availability": "available"}}
    assert run_daily._all_providers_unavailable(provenance, ["openai"]) is False


def test_provider_unavailable_line() -> None:
    line = run_daily._provider_unavailable_line(
        "openai",
        {"availability": "unavailable", "unavailable_reason": "rate_limited", "attempts_made": 3},
    )
    assert "openai" in line
    assert "rate_limited" in line
    assert "attempts=3" in line
