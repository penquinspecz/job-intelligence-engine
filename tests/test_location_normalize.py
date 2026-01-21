from ji_engine.utils.location_normalize import normalize_location_guess


def test_normalize_remote_us() -> None:
    result = normalize_location_guess("Engineer", "Remote - US")
    assert result["is_us_or_remote_us_guess"] is True
    assert result["us_guess_reason"] == "remote_us"


def test_normalize_city_state_sf() -> None:
    result = normalize_location_guess("Engineer", "San Francisco, CA")
    assert result["is_us_or_remote_us_guess"] is True
    assert result["us_guess_reason"] == "city_state"


def test_normalize_city_state_ny() -> None:
    result = normalize_location_guess("Engineer", "New York, NY")
    assert result["is_us_or_remote_us_guess"] is True
    assert result["us_guess_reason"] == "city_state"


def test_normalize_non_us() -> None:
    result = normalize_location_guess("Engineer", "London, UK")
    assert result["is_us_or_remote_us_guess"] is False
    assert result["us_guess_reason"] == "none"


def test_normalize_empty() -> None:
    result = normalize_location_guess(None, None)
    assert result["is_us_or_remote_us_guess"] is False
    assert result["us_guess_reason"] == "none"
