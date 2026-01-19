from ji_engine.utils.content_fingerprint import content_fingerprint


def test_content_fingerprint_stable_for_irrelevant_fields() -> None:
    base = {
        "title": "Role A",
        "location": "Remote",
        "team": "Ops",
        "jd_text": "Hello world",
    }
    variant = dict(base)
    variant["score"] = 99
    variant["run_id"] = "x"
    assert content_fingerprint(base) == content_fingerprint(variant)


def test_content_fingerprint_changes_for_meaningful_fields() -> None:
    base = {
        "title": "Role A",
        "location": "Remote",
        "team": "Ops",
        "jd_text": "Hello world",
    }
    changed = dict(base)
    changed["jd_text"] = "Hello world v2"
    assert content_fingerprint(base) != content_fingerprint(changed)
