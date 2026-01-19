import hashlib
import json

from ji_engine.utils.job_identity import job_identity


def test_job_identity_prefers_apply_url():
    job = {"apply_url": " https://example.com/a ", "title": "A", "location": "SF"}
    assert job_identity(job) == "https://example.com/a"


def test_job_identity_falls_back_to_detail_url():
    job = {"detail_url": " /jobs/123 ", "title": "A", "location": "SF"}
    assert job_identity(job) == "/jobs/123"


def test_job_identity_falls_back_to_title_location():
    job = {"title": " Role ", "location": "  Remote  "}
    assert job_identity(job) == "role|remote"


def test_job_identity_strips_extra_fields():
    base = {"title": "Role", "location": "Remote"}
    variant = {"title": "Role", "location": "Remote", "description": "desc"}
    assert job_identity(base) == job_identity(variant)


def test_job_identity_returns_hash_when_nothing_else():
    job = {"description": "Only description"}
    expected = hashlib.sha256(
        json.dumps(job, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    assert job_identity(job) == expected


def test_job_identity_is_deterministic_for_identical_dicts():
    job = {"apply_url": "https://example.com/a", "title": "A"}
    assert job_identity(job) == job_identity({"apply_url": "https://example.com/a", "title": "A"})


def test_job_identity_returns_hash_if_missing():
    first = job_identity({})
    second = job_identity({})
    assert first == second
    assert isinstance(first, str)
    assert len(first) == 64
    int(first, 16)


def test_job_identity_normalizes_url_query_params():
    base = {"apply_url": "https://example.com/jobs/123?utm_source=a&utm_medium=b"}
    variant = {"apply_url": "https://example.com/jobs/123?utm_source=other"}
    assert job_identity(base) == job_identity(variant)


def test_job_identity_normalizes_url_fragments():
    base = {"detail_url": "https://example.com/jobs/123#section-a"}
    variant = {"detail_url": "https://example.com/jobs/123#section-b"}
    assert job_identity(base) == job_identity(variant)
