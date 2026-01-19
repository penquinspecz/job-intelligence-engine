import hashlib
import json
from pathlib import Path

import scripts.replay_run as replay_run


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fp:
        for chunk in iter(lambda: fp.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()


def test_replay_run_happy_path(tmp_path: Path) -> None:
    input_path = tmp_path / "input.json"
    output_path = tmp_path / "output.json"
    input_path.write_text('{"a": 1}', encoding="utf-8")
    output_path.write_text('{"b": 2}', encoding="utf-8")

    report = {
        "inputs": {
            "raw_jobs_json": {"path": str(input_path), "sha256": _sha256(input_path)},
        },
        "scoring_inputs_by_profile": {
            "cs": {"path": str(input_path), "sha256": _sha256(input_path)},
        },
        "outputs_by_profile": {
            "cs": {
                "ranked_json": {"path": str(output_path), "sha256": _sha256(output_path)},
            }
        },
    }
    report_path = tmp_path / "run.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")

    rc = replay_run.main(["--run-report", str(report_path), "--profile", "cs"])
    assert rc == 0


def test_replay_run_missing_file_returns_2(tmp_path: Path) -> None:
    missing_path = tmp_path / "missing.json"
    report = {
        "inputs": {
            "raw_jobs_json": {"path": str(missing_path), "sha256": "abc"},
        },
        "scoring_inputs_by_profile": {
            "cs": {"path": str(missing_path), "sha256": "abc"},
        },
        "outputs_by_profile": {
            "cs": {
                "ranked_json": {"path": str(missing_path), "sha256": "abc"},
            }
        },
    }
    report_path = tmp_path / "run.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")

    rc = replay_run.main(["--run-report", str(report_path), "--profile", "cs"])
    assert rc == 2


def test_replay_run_hash_mismatch_returns_3(tmp_path: Path) -> None:
    input_path = tmp_path / "input.json"
    output_path = tmp_path / "output.json"
    input_path.write_text('{"a": 1}', encoding="utf-8")
    output_path.write_text('{"b": 2}', encoding="utf-8")

    report = {
        "inputs": {
            "raw_jobs_json": {"path": str(input_path), "sha256": "bad"},
        },
        "scoring_inputs_by_profile": {
            "cs": {"path": str(input_path), "sha256": _sha256(input_path)},
        },
        "outputs_by_profile": {
            "cs": {
                "ranked_json": {"path": str(output_path), "sha256": _sha256(output_path)},
            }
        },
    }
    report_path = tmp_path / "run.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")

    rc = replay_run.main(["--run-report", str(report_path), "--profile", "cs"])
    assert rc == 3
