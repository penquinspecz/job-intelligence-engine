from __future__ import annotations

import importlib
import json
import os
import shutil
import sys
from typing import Any, Dict, Iterable, List
from pathlib import Path
import csv
import hashlib

HASHED_OUTPUT_FILES = [
    "openai_ranked_jobs.cs.json",
    "openai_ranked_jobs.cs.csv",
    "openai_ranked_families.cs.json",
    "openai_shortlist.cs.md",
]
REQUIRED_OUTPUT_FILES = HASHED_OUTPUT_FILES

_CANONICAL_JSON_KWARGS = {"ensure_ascii": False, "sort_keys": True, "separators": (",", ":")}
_JOB_PROJECTION_FIELDS = ("job_id", "apply_url", "title", "score_bucket")


def _stable_job_key(job: Dict[str, Any]) -> str:
    for key in ("job_id", "apply_url"):
        value = job.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().lower()
    title = job.get("title")
    return str(title or "").strip().lower()


def _score_bucket(score: Any) -> int:
    try:
        return int(round(float(score)))
    except (TypeError, ValueError):
        return 0


def _project_job(job: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "job_id": job.get("job_id"),
        "apply_url": job.get("apply_url"),
        "title": job.get("title"),
        "score_bucket": _score_bucket(job.get("score")),
    }


def _normalized_hash_jobs(jobs: Iterable[Dict[str, Any]]) -> str:
    projected: List[Dict[str, Any]] = [_project_job(job) for job in jobs]
    projected.sort(key=_stable_job_key)
    payload = json.dumps(projected, **_CANONICAL_JSON_KWARGS).encode("utf-8") + b"\n"
    return hashlib.sha256(payload).hexdigest()


def _normalized_hash_families(families: Iterable[Dict[str, Any]]) -> str:
    projected: List[Dict[str, Any]] = []
    for entry in families:
        fam = entry.get("title_family") or ""
        variants = entry.get("family_variants") or []
        job_ids = []
        for variant in variants:
            job_id = variant.get("job_id") or variant.get("apply_url") or ""
            if job_id:
                job_ids.append(str(job_id).strip())
        projected.append({"title_family": fam, "job_ids": sorted(job_ids)})
    projected.sort(key=lambda item: (str(item.get("title_family") or "").lower(), item.get("job_ids") or []))
    payload = json.dumps(projected, **_CANONICAL_JSON_KWARGS).encode("utf-8") + b"\n"
    return hashlib.sha256(payload).hexdigest()


def _normalized_hash_csv(path: Path) -> str:
    with path.open(newline="", encoding="utf-8") as fp:
        reader = csv.DictReader(fp)
        rows = [_project_job(row) for row in reader]
    rows.sort(key=_stable_job_key)
    payload = json.dumps(rows, **_CANONICAL_JSON_KWARGS).encode("utf-8") + b"\n"
    return hashlib.sha256(payload).hexdigest()


def _copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(src, dst)


def test_pipeline_golden_master_e2e(tmp_path, monkeypatch, request):
    repo_root = Path(__file__).resolve().parents[1]
    data_dir = tmp_path / "data"
    state_dir = tmp_path / "state"
    if os.getenv("JOBINTEL_TEST_DEBUG_PATHS") == "1":
        print(f"[TEST_TMP_DATA_DIR] {data_dir}")

    # Isolate all pipeline artifacts under tmp_path
    monkeypatch.setenv("JOBINTEL_DATA_DIR", str(data_dir))
    monkeypatch.setenv("JOBINTEL_STATE_DIR", str(state_dir))
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
    run_enrich = importlib.reload(importlib.import_module("scripts.run_enrich"))
    score_jobs = importlib.reload(importlib.import_module("scripts.score_jobs"))
    run_daily = importlib.reload(importlib.import_module("scripts.run_daily"))

    sys.modules["scripts.run_enrich"] = run_enrich
    monkeypatch.setattr(score_jobs, "is_us_or_remote_us", lambda job: True)
    sys.modules["scripts.score_jobs"] = score_jobs
    sys.modules["scripts.run_scrape"] = run_scrape
    sys.modules["scripts.run_classify"] = run_classify

    # Run pipeline in-process to avoid subprocess/env drift
    run_daily.USE_SUBPROCESS = False
    sys.modules["scripts.run_daily"] = run_daily

    def _run_stage(cmd, *, stage: str):
        argv = cmd[1:] if cmd and cmd[0] == sys.executable else cmd
        if argv and argv[0] == "-m" and argv[1] == "scripts.run_enrich":
            sys.argv = [argv[1], *argv[2:]]
            rc = run_enrich.main()
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
        elif script_path == "run_enrich.py":
            sys.argv = [script_path, *argv[1:]]
            rc = run_enrich.main()
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
        [
            "run_daily.py",
            "--no_subprocess",
            "--profile",
            "cs",
            "--us_only",
            "--no_post",
            "--min_score",
            "70",
        ],
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
        if filename.endswith(".cs.json") and "ranked_jobs" in filename:
            ranked_jobs = json.loads(file_path.read_text(encoding="utf-8"))
            manifest["files"][filename] = {"normalized_sha256": _normalized_hash_jobs(ranked_jobs)}
        elif filename.endswith(".cs.csv"):
            manifest["files"][filename] = {"normalized_sha256": _normalized_hash_csv(file_path)}
        elif filename.endswith(".cs.json") and "ranked_families" in filename:
            ranked_families = json.loads(file_path.read_text(encoding="utf-8"))
            manifest["files"][filename] = {"normalized_sha256": _normalized_hash_families(ranked_families)}
        else:
            manifest["files"][filename] = {"present": True}

    # Golden fixtures assert deterministic transforms, not immutability of upstream job postings.
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
