from pathlib import Path

from ji_engine.providers.openai_provider import OpenAICareersProvider
from ji_engine.utils.job_id import extract_job_id_from_url
from ji_engine.providers.registry import load_providers_config


def test_openai_snapshot_contract() -> None:
    snapshot_path = Path("data/openai_snapshots/index.html")
    html = snapshot_path.read_text(encoding="utf-8")
    provider = OpenAICareersProvider(mode="SNAPSHOT", data_dir="data")
    jobs = provider._parse_html(html)
    assert len(jobs) > 100

    apply_urls = [job.apply_url for job in jobs if job.apply_url]
    assert len(apply_urls) / len(jobs) >= 0.8

    job_ids = [extract_job_id_from_url(url) for url in apply_urls]
    with_job_id = sum(1 for jid in job_ids if jid)
    assert with_job_id / len(jobs) >= 0.8


def test_ashby_snapshots_exist() -> None:
    providers = load_providers_config(Path("config/providers.json"))
    ashby_entries = [p for p in providers if p.get("type") == "ashby"]
    assert ashby_entries
    for entry in ashby_entries:
        snapshot_path = Path(entry["snapshot_path"])
        assert snapshot_path.exists()
        assert snapshot_path.stat().st_size > 0
