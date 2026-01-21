from pathlib import Path

from ji_engine.providers.ashby_provider import AshbyProvider


def test_ashby_provider_parses_fixture() -> None:
    snapshot_dir = Path("tests/fixtures/ashby")
    provider = AshbyProvider(
        provider_id="anthropic",
        board_url="https://jobs.ashbyhq.com/anthropic",
        snapshot_dir=snapshot_dir,
        mode="SNAPSHOT",
    )
    jobs = provider.load_from_snapshot()
    assert len(jobs) == 2
    assert all(job.apply_url for job in jobs)
    assert all(job.job_id for job in jobs)
    assert jobs[0].job_id != jobs[1].job_id
