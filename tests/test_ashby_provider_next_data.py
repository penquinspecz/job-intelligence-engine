from pathlib import Path

from ji_engine.providers.ashby_provider import AshbyProvider


def test_parse_next_data_payload() -> None:
    html = Path("tests/fixtures/ashby_next_data.html").read_text(encoding="utf-8")
    provider = AshbyProvider(provider_id="acme", board_url="https://jobs.ashbyhq.com/acme", snapshot_dir=Path("data"))
    results = provider._parse_html(html)
    assert len(results) == 1
    assert results[0].title == "Customer Success Lead"
    assert "ashbyhq.com" in (results[0].apply_url or "")


def test_parse_fallback_anchor() -> None:
    html = """
    <html><body>
      <article class="job-card">
        <h2>Support Engineer</h2>
        <a href="https://jobs.ashbyhq.com/acme/22222222-2222-2222-2222-222222222222/application">Apply</a>
        <span class="location">Remote</span>
      </article>
    </body></html>
    """
    provider = AshbyProvider(provider_id="acme", board_url="https://jobs.ashbyhq.com/acme", snapshot_dir=Path("data"))
    results = provider._parse_html(html)
    assert len(results) == 1
    assert results[0].title == "Support Engineer"
    assert results[0].location == "Remote"


def test_job_id_hash_includes_apply_url() -> None:
    provider = AshbyProvider(provider_id="acme", board_url="https://jobs.ashbyhq.com/acme", snapshot_dir=Path("data"))
    job_id_a = provider._extract_job_id(
        "https://jobs.ashbyhq.com/acme/custom/apply",
        "Same Title",
        "Remote",
        "Team",
    )
    job_id_b = provider._extract_job_id(
        "https://jobs.ashbyhq.com/acme/other/apply",
        "Same Title",
        "Remote",
        "Team",
    )
    assert job_id_a != job_id_b
