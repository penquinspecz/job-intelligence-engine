from ji_engine.utils.job_identity import job_identity


def test_job_identity_prefers_apply_url():
    job = {"apply_url": "https://example.com/a", "title": "A", "location": "SF"}
    assert job_identity(job) == "https://example.com/a"


def test_job_identity_falls_back_to_detail_url():
    job = {"detail_url": "/jobs/123", "title": "A", "location": "SF"}
    assert job_identity(job) == "/jobs/123"


def test_job_identity_falls_back_to_title_location():
    job = {"title": "Role", "location": "Remote"}
    assert job_identity(job) == "Role|Remote"


def test_job_identity_returns_empty_if_missing():
    assert job_identity({}) == ""
