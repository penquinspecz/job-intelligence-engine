from __future__ import annotations

import hashlib
import importlib
import json
import os
import shutil
import sys
from pathlib import Path


HASHED_OUTPUT_FILES = [
    "openai_ranked_jobs.cs.json",
    "openai_ranked_jobs.cs.csv",
    "openai_ranked_families.cs.json",
    "openai_shortlist.cs.md",
]
REQUIRED_OUTPUT_FILES = HASHED_OUTPUT_FILES


def _copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(src, dst)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fp:
        for chunk in iter(lambda: fp.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()


def test_pipeline_golden_master_e2e(tmp_path, monkeypatch, request):
    repo_root = Path(__file__).resolve().parents[1]
    data_dir = tmp_path / "data"
    if os.getenv("JOBINTEL_TEST_DEBUG_PATHS") == "1":
        print(f"[TEST_TMP_DATA_DIR] {data_dir}")

    # Isolate all pipeline artifacts under tmp_path
    monkeypatch.setenv("JOBINTEL_DATA_DIR", str(data_dir))
    monkeypatch.setenv("CAREERS_MODE", "SNAPSHOT")
    monkeypatch.setenv("EMBED_PROVIDER", "stub")
    monkeypatch.setenv("ENRICH_MAX_WORKERS", "1")
    monkeypatch.delenv("ENRICH_LIMIT", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "")

    # Seed required inputs
    _copy(repo_root / "data" / "openai_snapshots" / "index.html", data_dir / "openai_snapshots" / "index.html")
    _copy(repo_root / "data" / "candidate_profile.json", data_dir / "candidate_profile.json")

    # Reload modules to pick up env-based config overrides
    import ji_engine.config as config

    config = importlib.reload(config)
    run_scrape = importlib.reload(importlib.import_module("scripts.run_scrape"))
    run_classify = importlib.reload(importlib.import_module("scripts.run_classify"))
    enrich_jobs = importlib.reload(importlib.import_module("scripts.enrich_jobs"))
    score_jobs = importlib.reload(importlib.import_module("scripts.score_jobs"))
    run_daily = importlib.reload(importlib.import_module("scripts.run_daily"))

    # Stub network calls for enrichment
    def _stub_fetch_job_posting(**kwargs):
        return {
            "data": {
                "jobPosting": {
                    "title": None,
                    "locationName": None,
                    "teamNames": None,
                    "descriptionHtml": "<p>Stub JD text for testing.</p>",
                }
            }
        }

    monkeypatch.setattr(enrich_jobs, "fetch_job_posting", _stub_fetch_job_posting)
    monkeypatch.setattr(enrich_jobs, "_fetch_html_fallback", lambda url: None)
    sys.modules["scripts.enrich_jobs"] = enrich_jobs
    monkeypatch.setattr(score_jobs, "is_us_or_remote_us", lambda job: True)
    sys.modules["scripts.score_jobs"] = score_jobs
    sys.modules["scripts.run_scrape"] = run_scrape
    sys.modules["scripts.run_classify"] = run_classify

    # Run pipeline in-process to avoid subprocess/env drift
    run_daily.USE_SUBPROCESS = False
    sys.modules["scripts.run_daily"] = run_daily

    def _run_stage(cmd, *, stage: str):
        argv = cmd[1:] if cmd and cmd[0] == sys.executable else cmd
        if argv and argv[0] == "-m" and argv[1] == "scripts.enrich_jobs":
            sys.argv = [argv[1], *argv[2:]]
            rc = enrich_jobs.main()
            if rc not in (None, 0):
                raise SystemExit(rc)
            return

        script_path = Path(argv[0]).name if argv else ""
        if script_path == "run_scrape.py":
            sys.argv = [script_path, *argv[1:]]
            rc = run_scrape.main()
        elif script_path == "run_classify.py":
            sys.argv = [script_path, *argv[1:]]
            rc = run_classify.main()
        elif script_path == "enrich_jobs.py":
            sys.argv = [script_path, *argv[1:]]
            rc = enrich_jobs.main()
        elif script_path == "score_jobs.py":
            sys.argv = [script_path, *argv[1:]]
            rc = score_jobs.main()
        else:
            raise RuntimeError(f"Unsupported stage {stage}: {cmd}")

        if rc not in (None, 0):
            raise SystemExit(rc)

    monkeypatch.setattr(run_daily, "_run", _run_stage)
    monkeypatch.setattr(
        sys,
        "argv",
        ["run_daily.py", "--no_subprocess", "--profile", "cs", "--us_only", "--no_post"],
    )

    rc = run_daily.main()
    assert rc == 0

    ranked_path = data_dir / "openai_ranked_jobs.cs.json"
    assert ranked_path.exists()

    results = json.loads(ranked_path.read_text())
    assert isinstance(results, list) and results
    assert len(results) >= 20

    top20 = results[:20]
    seen_urls = set()
    last_score = float("inf")

    top20_count = len(top20)
    top20_scores_non_increasing = True

    for idx, item in enumerate(top20):
        assert {"title", "apply_url", "score"} <= set(item.keys())
        score = item.get("score", 0)
        if score > last_score:
            top20_scores_non_increasing = False
        assert score <= last_score, f"Scores must be non-increasing at index {idx}"
        last_score = score
        url = item.get("apply_url")
        assert url not in seen_urls, f"apply_url must be unique in top 20 but found duplicate {url}"
        seen_urls.add(url)

    # Build manifest of generated artifacts
    manifest = {
        "files": {},
        "stats": {
            "ranked_jobs_count": len(results),
            "top20_count": top20_count,
            "top20_scores_non_increasing": top20_scores_non_increasing,
            "top20_unique_apply_urls": len(seen_urls),
        },
    }

    for filename in REQUIRED_OUTPUT_FILES:
        file_path = data_dir / filename
        assert file_path.exists(), f"Missing required pipeline output {filename}"
        manifest["files"][filename] = {"sha256": _sha256(file_path), "bytes": file_path.stat().st_size}

    fixture_path = repo_root / "tests" / "fixtures" / "golden" / "openai_snapshot_cs.manifest.json"
    update_golden = bool(request.config.getoption("--update-golden"))

    if update_golden:
        fixture_path.parent.mkdir(parents=True, exist_ok=True)
        fixture_path.write_text(json.dumps(manifest, indent=2, sort_keys=True))
        assert True
    else:
        expected_manifest = json.loads(fixture_path.read_text())
        assert manifest["files"] == expected_manifest.get("files", {})
        assert manifest["stats"]["top20_scores_non_increasing"] is True
        assert manifest["stats"]["top20_unique_apply_urls"] == len(seen_urls)
        assert manifest["stats"]["top20_count"] == top20_count

    # Document regeneration approach for maintainers
    # To refresh the manifest fixture: run
    #   pytest -q tests/test_pipeline_golden_master_e2e.py --update-golden

