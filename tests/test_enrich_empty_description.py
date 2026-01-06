from scripts.enrich_jobs import _apply_api_response


def test_empty_description_marks_unavailable():
    job = {"title": "Test", "location": "X", "team": "Y", "apply_url": "u"}
    api_data = {"data": {"jobPosting": {"title": "Test", "locationName": "X", "teamNames": [], "descriptionHtml": "   "}}}
    updated, fallback = _apply_api_response(job, api_data, fallback_url="http://example.com")
    assert updated["enrich_status"] == "unavailable"
    assert updated["enrich_reason"] == "empty_description"
    assert fallback is False

