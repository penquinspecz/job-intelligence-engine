from __future__ import annotations

import json
from pathlib import Path

import scripts.replay_run as replay_run


def _write_bytes(path: Path, data: bytes) -> str:
    import hashlib

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def _build_run_dir(tmp_path: Path) -> Path:
    run_dir = tmp_path / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    replay_run.DATA_DIR = data_dir
    ranked = data_dir / "openai_ranked_jobs.cs.json"
    sha = _write_bytes(ranked, b"[1]")
    report = {
        "run_id": "cli-test",
        "verifiable_artifacts": {
            "openai:cs:ranked_json": {
                "path": ranked.name,
                "sha256": sha,
                "bytes": ranked.stat().st_size,
                "hash_algo": "sha256",
            }
        },
    }
    report_path = run_dir / "run_report.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    return run_dir


def test_replay_cli_json_ok(tmp_path: Path, capsys) -> None:
    run_dir = _build_run_dir(tmp_path)
    exit_code = replay_run.main(["--run-dir", str(run_dir), "--json"])
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert exit_code == 0
    assert payload["run_id"] == "cli-test"
    assert payload["checked"] == 1
    assert payload["matched"] == 1
    assert payload["mismatched"] == 0
    assert payload["missing"] == 0
    assert "openai:cs:ranked_json" in payload["artifacts"]


def test_replay_cli_json_mismatch(tmp_path: Path, capsys) -> None:
    run_dir = _build_run_dir(tmp_path)
    corrupt = replay_run.DATA_DIR / "openai_ranked_jobs.cs.json"
    corrupt.write_bytes(b"[2]")
    exit_code = replay_run.main(["--run-dir", str(run_dir), "--json", "--strict"])
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert exit_code == 2
    assert payload["mismatched"] == 1
    artifact = payload["artifacts"]["openai:cs:ranked_json"]
    assert artifact["expected"]
    assert artifact["actual"]
    assert artifact["path"].endswith("openai_ranked_jobs.cs.json")


def test_replay_cli_json_mismatch_non_strict(tmp_path: Path, capsys) -> None:
    run_dir = _build_run_dir(tmp_path)
    corrupt = replay_run.DATA_DIR / "openai_ranked_jobs.cs.json"
    corrupt.write_bytes(b"[2]")
    exit_code = replay_run.main(["--run-dir", str(run_dir), "--json"])
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert exit_code == 0
    assert payload["mismatched"] == 1
