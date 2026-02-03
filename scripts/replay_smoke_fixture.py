#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict

from ji_engine.utils.verification import compute_sha256_file


def _write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def _write_json(path: Path, payload: Dict[str, object]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")


def _build_fixture() -> Path:
    base_dir = Path(tempfile.mkdtemp(prefix="jobintel_replay_smoke_"))
    run_dir = base_dir / "run"
    run_dir.mkdir(parents=True, exist_ok=True)

    input_path = run_dir / "openai_enriched_jobs.json"
    ranked_json = run_dir / "openai_ranked_jobs.cs.json"
    ranked_csv = run_dir / "openai_ranked_jobs.cs.csv"
    ranked_families = run_dir / "openai_ranked_families.cs.json"
    shortlist_md = run_dir / "openai_shortlist.cs.md"

    _write_text(input_path, '[{"job_id":"1"},{"job_id":"2"}]')
    _write_text(ranked_json, '[{"job_id":"1","score":99},{"job_id":"2","score":97}]')
    _write_text(ranked_csv, "job_id,score\n1,99\n2,97\n")
    _write_text(ranked_families, '[{"family":"core","job_ids":["1","2"]}]')
    _write_text(shortlist_md, "# Shortlist\n- job_id: 1\n- job_id: 2\n")

    report = {
        "run_report_schema_version": 1,
        "run_id": "replay-smoke",
        "inputs": {
            "enriched_jobs_json": {"path": str(input_path), "sha256": compute_sha256_file(input_path)},
        },
        "scoring_inputs_by_profile": {
            "cs": {"path": str(input_path), "sha256": compute_sha256_file(input_path)},
        },
        "outputs_by_profile": {
            "cs": {
                "ranked_json": {"path": str(ranked_json), "sha256": compute_sha256_file(ranked_json)},
                "ranked_csv": {"path": str(ranked_csv), "sha256": compute_sha256_file(ranked_csv)},
                "ranked_families_json": {
                    "path": str(ranked_families),
                    "sha256": compute_sha256_file(ranked_families),
                },
                "shortlist_md": {"path": str(shortlist_md), "sha256": compute_sha256_file(shortlist_md)},
            }
        },
    }
    _write_json(run_dir / "run_report.json", report)
    return run_dir


def main() -> int:
    run_dir = _build_fixture()
    try:
        cmd = [
            sys.executable,
            str(Path(__file__).with_name("replay_run.py")),
            "--run-dir",
            str(run_dir),
            "--profile",
            "cs",
            "--strict",
        ]
        result = subprocess.run(cmd, check=False)
        return result.returncode
    finally:
        shutil.rmtree(run_dir.parent, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
