import json
from pathlib import Path

from ji_engine.providers.ashby_provider import AshbyProvider
from ji_engine.providers.registry import load_providers_config
from ji_engine.utils.job_id import extract_job_id_from_url
from ji_engine.utils.verification import compute_sha256_file


def test_openai_snapshot_contract() -> None:
    snapshot_path = Path("data/openai_snapshots/index.html")
    assert snapshot_path.exists(), f"Missing snapshot fixture: {snapshot_path}"
    provider = AshbyProvider(
        provider_id="openai",
        board_url="https://jobs.ashbyhq.com/openai",
        snapshot_dir=Path("data/openai_snapshots"),
        mode="SNAPSHOT",
    )
    jobs = provider.load_from_snapshot()
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
    missing: list[str] = []
    for entry in ashby_entries:
        snapshot_path = Path(entry["snapshot_path"])
        if not snapshot_path.exists():
            missing.append(str(snapshot_path))
            continue
        assert snapshot_path.stat().st_size > 0
    assert not missing, f"Missing ashby snapshot fixtures: {', '.join(sorted(missing))}"


def test_enabled_snapshot_providers_are_manifest_pinned_and_immutable() -> None:
    providers = load_providers_config(Path("config/providers.json"))
    manifest_path = Path("tests/fixtures/golden/snapshot_bytes.manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    missing_fixture: list[str] = []
    missing_manifest_entry: list[str] = []
    hash_mismatch: list[str] = []
    for provider in providers:
        if not provider.get("enabled", True):
            continue
        if not provider.get("snapshot_enabled", True):
            continue
        mode = str(provider.get("mode") or "snapshot").strip().lower()
        if mode not in {"snapshot", "auto"}:
            continue

        rel_path = str(provider["snapshot_path"])
        fixture_path = Path(rel_path)
        if not fixture_path.exists():
            missing_fixture.append(rel_path)
            continue
        manifest_entry = manifest.get(rel_path)
        if not isinstance(manifest_entry, dict):
            missing_manifest_entry.append(rel_path)
            continue
        actual_sha = compute_sha256_file(fixture_path)
        actual_bytes = fixture_path.stat().st_size
        if actual_sha != manifest_entry.get("sha256") or actual_bytes != manifest_entry.get("bytes"):
            hash_mismatch.append(rel_path)

    assert not missing_fixture, f"Missing snapshot fixtures for enabled providers: {', '.join(sorted(missing_fixture))}"
    assert not missing_manifest_entry, "Manifest missing entries for enabled snapshot providers: " + ", ".join(
        sorted(missing_manifest_entry)
    )
    assert not hash_mismatch, f"Pinned snapshot manifest hash mismatch: {', '.join(sorted(hash_mismatch))}"
