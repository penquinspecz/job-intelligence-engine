import hashlib
import json

from ji_engine.utils.job_identity import job_identity


def _hash_payload(payload: dict) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def test_job_identity_prefers_job_id():
    job = {"provider": "openai", "job_id": "ABC-123", "apply_url": "https://example.com/a"}
    expected = _hash_payload(
        {
            "strategy": "provider_requisition",
            "provider": "openai",
            "requisition_id": "abc-123",
        }
    )
    assert job_identity(job, mode="provider") == expected


def test_job_identity_prefers_apply_url():
    job = {
        "provider": "openai",
        "apply_url": " https://example.com/a ",
        "title": "A",
        "location": "SF",
    }
    identity = job_identity(job, mode="provider")
    assert identity == job_identity(
        {
            "provider": "openai",
            "apply_url": "https://example.com/a?utm_source=ignored",
            "title": " a ",
            "location": " sf ",
        },
        mode="provider",
    )
    assert len(identity) == 64


def test_job_identity_falls_back_to_detail_url():
    job = {
        "provider": "openai",
        "detail_url": " https://example.com/jobs/123 ",
        "title": "A",
        "location": "SF",
    }
    identity = job_identity(job, mode="provider")
    assert identity == job_identity(
        {
            "provider": "openai",
            "detail_url": "https://example.com/jobs/123#fragment",
            "title": "A",
            "location": "SF",
        },
        mode="provider",
    )
    assert len(identity) == 64


def test_job_identity_falls_back_to_content_hash():
    job = {"provider": "openai", "title": " Role ", "location": "  Remote  "}
    identity = job_identity(job, mode="provider")
    assert identity == job_identity(
        {"provider": "openai", "title": "role", "location": "remote"},
        mode="provider",
    )
    assert len(identity) == 64


def test_job_identity_changes_with_description():
    base = {"provider": "openai", "title": "Role", "location": "Remote"}
    variant = {"provider": "openai", "title": "Role", "location": "Remote", "description": "desc"}
    assert job_identity(base, mode="provider") != job_identity(variant, mode="provider")


def test_job_identity_returns_hash_when_nothing_else():
    job = {"provider": "openai", "description": "Only description"}
    identity = job_identity(job, mode="provider")
    assert identity == job_identity({"provider": "openai", "description": " only description "}, mode="provider")
    assert len(identity) == 64


def test_job_identity_is_deterministic_for_identical_dicts():
    job = {"provider": "openai", "apply_url": "https://example.com/a", "title": "A"}
    assert job_identity(job, mode="provider") == job_identity(
        {"provider": "openai", "apply_url": "https://example.com/a", "title": "A"},
        mode="provider",
    )


def test_job_identity_provider_namespace_changes_id():
    job = {"provider": "OpenAI", "job_id": "ABC-123"}
    other = {"provider": "Anthropic", "job_id": "ABC-123"}
    assert job_identity(job, mode="provider") != job_identity(other, mode="provider")


def test_job_identity_returns_hash_if_missing():
    first = job_identity({})
    second = job_identity({})
    assert first == second
    assert isinstance(first, str)
    assert len(first) == 64
    int(first, 16)


def test_job_identity_normalizes_url_query_params():
    base = {"provider": "openai", "apply_url": "https://example.com/jobs/123?utm_source=a&utm_medium=b"}
    variant = {"provider": "openai", "apply_url": "https://example.com/jobs/123?utm_source=other"}
    assert job_identity(base, mode="provider") == job_identity(variant, mode="provider")


def test_job_identity_normalizes_url_fragments():
    base = {"provider": "openai", "detail_url": "https://example.com/jobs/123#section-a"}
    variant = {"provider": "openai", "detail_url": "https://example.com/jobs/123#section-b"}
    assert job_identity(base, mode="provider") == job_identity(variant, mode="provider")


def test_job_identity_drops_tracking_params():
    base = {"provider": "openai", "apply_url": "https://example.com/jobs/123?gh_jid=abc&utm_campaign=x"}
    variant = {"provider": "openai", "apply_url": "https://example.com/jobs/123?gh_jid=def&utm_campaign=y"}
    assert job_identity(base, mode="provider") == job_identity(variant, mode="provider")


def test_job_identity_normalizes_whitespace_and_case():
    job = {"provider": "openai", "title": "  Senior  Manager ", "location": " REMOTE ", "team": " CS "}
    variant = {"provider": "openai", "title": "senior manager", "location": "remote", "team": "cs"}
    assert job_identity(job, mode="provider") == job_identity(variant, mode="provider")


def test_job_identity_changes_when_key_fields_change_without_req_id():
    base = {
        "provider": "openai",
        "apply_url": "https://example.com/jobs/123",
        "title": "Solutions Architect",
        "location": "Remote",
    }
    variant = {**base, "location": "San Francisco"}
    assert job_identity(base, mode="provider") != job_identity(variant, mode="provider")
