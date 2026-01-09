from __future__ import annotations

import importlib
import json
import os
import shutil
import sys
from pathlib import Path


def _copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(src, dst)


def test_pipeline_golden_master_e2e(tmp_path, monkeypatch):
    repo_root = Path(__file__).resolve().parents[1]
    data_dir = tmp_path / "data"

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

    for idx, item in enumerate(top20):
        assert {"title", "apply_url", "score"} <= set(item.keys())
        score = item.get("score", 0)
        assert score <= last_score, f"Scores must be non-increasing at index {idx}"
        last_score = score
        url = item.get("apply_url")
        assert url not in seen_urls, f"apply_url must be unique in top 20 but found duplicate {url}"
        seen_urls.add(url)

    # Document regeneration approach for maintainers
    # To refresh the fixture: set JOBINTEL_DATA_DIR to a temp dir, run this test with
    # --maxfail=1 -k pipeline_golden_master_e2e --update-golden (manual), then copy the
    # new top10 from the generated ranked file into the fixture.

