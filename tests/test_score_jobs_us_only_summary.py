from scripts import score_jobs


def test_format_us_only_reason_summary_sorted() -> None:
    jobs = [
        {"us_guess_reason": "city_state"},
        {"us_guess_reason": "remote_us"},
        {"us_guess_reason": "remote_us"},
        {"us_guess_reason": "explicit_us"},
        {"us_guess_reason": ""},
        {},
    ]
    summary = score_jobs._format_us_only_reason_summary(jobs)
    assert summary == "remote_us=2, city_state=1, explicit_us=1"


def test_format_us_only_reason_summary_empty() -> None:
    summary = score_jobs._format_us_only_reason_summary([{"title": "No reason"}])
    assert summary == "(no reason fields present)"
