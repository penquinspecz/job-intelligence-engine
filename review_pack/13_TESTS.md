# Tests & Fixtures
Included files: all pytest modules under `tests/` and mention of fixtures.

Why they matter: validate enrichment robustness, regex extraction, provider parsing, and golden-master scoring stability.

Omitted sections: fixture `tests/fixtures/openai_enriched_jobs.sample.json` not expanded here (20-record sample) to save space; refer to file directly if needed. `tests/fixtures/ashby_jobPosting_null.json` similarly referenced in tests.

## tests/test_score_jobs_golden_master.py
```
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def run_score_jobs(tmp_path: Path) -> list[dict]:
    repo_root = Path(__file__).resolve().parents[1]
    fixture = repo_root / "tests" / "fixtures" / "openai_enriched_jobs.sample.json"

    out_json = tmp_path / "ranked.json"
    out_csv = tmp_path / "ranked.csv"
    out_families = tmp_path / "families.json"
    out_md = tmp_path / "shortlist.md"

    cmd = [
        sys.executable,
        "scripts/score_jobs.py",
        "--profile",
        "cs",
        "--in_path",
        str(fixture),
        "--out_json",
        str(out_json),
        "--out_csv",
        str(out_csv),
        "--out_families",
        str(out_families),
        "--out_md",
        str(out_md),
    ]

    subprocess.run(cmd, cwd=repo_root, check=True)
    return json.loads(out_json.read_text(encoding="utf-8"))


def test_score_jobs_golden_master(tmp_path: Path) -> None:
    ranked = run_score_jobs(tmp_path)

    assert len(ranked) == 20  # fixture count

    titles = [j["title"] for j in ranked[:10]]
    scores = [j.get("score") for j in ranked[:10]]

    expected_titles = [
        "Manager, AI Deployment - AMER",
        "Partner Solutions Architect",
        "Forward Deployed Software Engineer - Munich",
        "Forward Deployed Software Engineer - NYC",
        "Forward Deployed Software Engineer - SF",
        "Forward Deployed Engineer, Gov",
        "Forward Deployed Engineer - Life Sciences - NYC",
        "Forward Deployed Engineer - Life Sciences - SF",
        "Solution Architect Manager, Digital Natives",
        "Forward Deployed Engineer - Financial Services",
    ]

    expected_scores = [146, 132, 105, 105, 105, 100, 98, 98, 98, 94]

    assert titles == expected_titles
    assert scores == expected_scores
```

## tests/test_enrich_jobPosting_null.py
```
"""Test handling of jobPosting null response."""

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.enrich_jobs import _apply_api_response


def test_jobposting_null_marks_unavailable_no_fallback():
    fixture_path = ROOT / "tests" / "fixtures" / "ashby_jobPosting_null.json"
    api_data = json.loads(fixture_path.read_text(encoding="utf-8"))

    job = {
        "title": "Original Title",
        "location": "Original Location",
        "team": "Original Team",
        "apply_url": "https://jobs.ashbyhq.com/openai/0c22b805-3976-492e-81f2-7cf91f63a630/application",
    }
    fallback_url = "https://jobs.ashbyhq.com/openai/0c22b805-3976-492e-81f2-7cf91f63a630"

    updated, fallback_needed = _apply_api_response(job, api_data, fallback_url)

    assert updated.get("enrich_status") == "unavailable"
    assert updated.get("enrich_reason") == "api_jobPosting_null"
    assert updated.get("jd_text") is None
    assert fallback_needed is False
```

## tests/test_enrich_html_fallback_url.py
```
"""Test fallback URL derivation for HTML enrichment."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.enrich_jobs import _derive_fallback_url


def test_fallback_url_derivation():
    apply_url = "https://jobs.ashbyhq.com/openai/0c22b805-3976-492e-81f2-7cf91f63a630/application"
    expected = "https://jobs.ashbyhq.com/openai/0c22b805-3976-492e-81f2-7cf91f63a630"
    assert _derive_fallback_url(apply_url) == expected
```

## tests/test_enrichment.py
```
"""Unit tests for enrichment pipeline."""

from pathlib import Path
import sys

# Add src to path
ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from ji_engine.pipeline.enrichment import _extract_job_id_from_url


def test_extract_job_id_from_url():
    """Test that jobPostingId is correctly extracted from apply_url using regex."""
    
    # Real apply_url from OpenAI jobs
    real_apply_url = "https://jobs.ashbyhq.com/openai/0c22b805-3976-492e-81f2-7cf91f63a630/application"
    expected_job_id = "0c22b805-3976-492e-81f2-7cf91f63a630"
    
    # Test extraction
    job_id = _extract_job_id_from_url(real_apply_url)
    assert job_id == expected_job_id, f"Expected {expected_job_id}, got {job_id}"
    
    # Test with different case (should still work due to re.IGNORECASE)
    uppercase_url = "https://jobs.ashbyhq.com/openai/0C22B805-3976-492E-81F2-7CF91F63A630/application"
    job_id_upper = _extract_job_id_from_url(uppercase_url)
    assert job_id_upper == "0C22B805-3976-492E-81F2-7CF91F63A630", f"Expected uppercase UUID, got {job_id_upper}"
    
    # Test invalid URLs (should return None)
    invalid_urls = [
        "https://jobs.ashbyhq.com/openai/",  # No UUID
        "https://jobs.ashbyhq.com/openai/123/application",  # Too short
        "https://jobs.ashbyhq.com/openai/0c22b805-3976-492e-81f2-7cf91f63a630",  # Missing /application
        "https://example.com/job/123",  # Wrong domain
        "https://jobs.ashbyhq.com/anthropic/0c22b805-3976-492e-81f2-7cf91f63a630/application",  # Wrong path
    ]
    
    for invalid_url in invalid_urls:
        job_id = _extract_job_id_from_url(invalid_url)
        assert job_id is None, f"Expected None for invalid URL '{invalid_url}', got {job_id}"
```

## tests/test_enrich_job_id_regex.py
```
"""Test job ID extraction regex."""

import re
from pathlib import Path
import sys

# Add root to path for imports
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.enrich_jobs import _extract_job_id_from_url


def test_extract_job_id_valid_url():
    """Test that regex extracts UUID from valid OpenAI Ashby URL."""
    url = "https://jobs.ashbyhq.com/openai/0c22b805-3976-492e-81f2-7cf91f63a630/application"
    expected = "0c22b805-3976-492e-81f2-7cf91f63a630"
    
    result = _extract_job_id_from_url(url)
    assert result == expected, f"Expected {expected}, got {result}"


def test_extract_job_id_case_insensitive():
    """Test that regex works with uppercase UUID."""
    url = "https://jobs.ashbyhq.com/openai/0C22B805-3976-492E-81F2-7CF91F63A630/application"
    expected = "0C22B805-3976-492E-81F2-7CF91F63A630"
    
    result = _extract_job_id_from_url(url)
    assert result == expected, f"Expected {expected}, got {result}"


def test_extract_job_id_invalid_urls():
    """Test that regex returns None for invalid URLs."""
    invalid_urls = [
        "https://jobs.ashbyhq.com/openai/",  # No UUID
        "https://jobs.ashbyhq.com/openai/123/application",  # Too short
        "https://jobs.ashbyhq.com/openai/0c22b805-3976-492e-81f2-7cf91f63a630",  # Missing /application
        "https://example.com/job/123",  # Wrong domain
        "https://jobs.ashbyhq.com/anthropic/0c22b805-3976-492e-81f2-7cf91f63a630/application",  # Wrong org
        "",  # Empty string
    ]
    
    for url in invalid_urls:
        result = _extract_job_id_from_url(url)
        assert result is None, f"Expected None for '{url}', got {result}"
```

## tests/test_openai_provider.py
```
"""Unit tests for OpenAI provider snapshot parser."""

from pathlib import Path
import sys

# Add src to path
ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from ji_engine.providers.openai_provider import OpenAICareersProvider


def test_titles_not_concatenated_with_metadata():
    """
    Regression test for historical bug where titles were concatenated with
    department/location without separators (e.g., '...SalesSan Francisco').
    """
    provider = OpenAICareersProvider(mode="SNAPSHOT", data_dir="data")

    snapshot_file = Path("data") / "openai_snapshots" / "index.html"
    if not snapshot_file.exists():
        print("⚠️  Snapshot file not found, skipping test")
        print(f"   Expected: {snapshot_file}")
        return

    html = snapshot_file.read_text(encoding="utf-8")
    jobs = provider._parse_html(html)

    bad_substrings = {
        "SalesSan Francisco",
        "MarketingRemote",
        "CommunicationsSan Francisco",
        "Product OperationsSan Francisco",
        "Customer SuccessSan Francisco",
        "Human DataSan Francisco",
    }

    for job in jobs:
        assert job.title, "Title should not be empty"
        assert job.apply_url, "apply_url should not be empty"

        for bad in bad_substrings:
            assert bad not in job.title, f"Title '{job.title}' contains concatenated metadata substring '{bad}'"


def test_sanitize_title_removes_concatenated_dept_location():
    """
    Ensure title sanitization strips concatenated department/location with no separator.
    """
    provider = OpenAICareersProvider(mode="SNAPSHOT", data_dir="data")
    raw = "Field EngineerRoboticsSan Francisco"
    sanitized = provider._sanitize_title(raw, team="Robotics", location="San Francisco")
    assert sanitized == "Field Engineer", f"Expected 'Field Engineer', got '{sanitized}'"
```

## Fixtures (referenced)
- `tests/fixtures/openai_enriched_jobs.sample.json` — 20-record enriched sample used for golden-master scoring (not inlined here).
- `tests/fixtures/ashby_jobPosting_null.json` — Ashby GraphQL null payload fixture for unavailable-path test (not inlined).

