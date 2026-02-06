from __future__ import annotations

import json

import scripts.prove_cloud_run as prove_cloud_run


class _Result:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_prove_cloud_run_extracts_and_writes(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBINTEL_STATE_DIR", str(tmp_path))

    calls = {"kubectl": 0, "verify": 0, "git": 0}

    def fake_run(cmd, check=False, capture_output=True, text=True):
        if cmd[0] == "kubectl":
            calls["kubectl"] += 1
            return _Result(
                0,
                "\n".join(
                    [
                        "JOBINTEL_RUN_ID=2026-01-02T03:04:05Z",
                        "===== jobintel start 2026-01-01T00:00:00Z =====",
                        '[run_scrape][provenance] {"openai": {"scrape_mode": "live"}}',
                        "s3_status=ok",
                        "PUBLISH_CONTRACT enabled=True required=True bucket=b prefix=p pointer_global=ok pointer_profiles={} error=None",
                    ]
                )
                + "\n",
            )
        if any("verify_published_s3.py" in part for part in cmd):
            calls["verify"] += 1
            return _Result(0, "OK\n")
        if cmd[:2] == ["git", "rev-parse"]:
            calls["git"] += 1
            return _Result(0, "deadbeef\n")
        return _Result(0, "")

    monkeypatch.setattr(prove_cloud_run, "_run", fake_run)
    monkeypatch.setattr(prove_cloud_run, "_repo_root", lambda: tmp_path)

    exit_code = prove_cloud_run.main(
        [
            "--bucket",
            "proof-bucket",
            "--prefix",
            "jobintel",
            "--namespace",
            "jobintel",
            "--job-name",
            "jobintel-manual-20260102",
        ]
    )

    assert exit_code == 0
    proof_path = tmp_path / "proofs" / "2026-01-02T03:04:05Z.json"
    assert proof_path.exists()
    payload = json.loads(proof_path.read_text(encoding="utf-8"))
    assert payload["run_id"] == "2026-01-02T03:04:05Z"
    assert payload["bucket"] == "proof-bucket"
    assert payload["prefix"] == "jobintel"
    assert payload["job_name"] == "jobintel-manual-20260102"
    assert payload["verified_ok"] is True
    assert payload["commit_sha"] == "deadbeef"
    assert payload["provenance"] == {"openai": {"scrape_mode": "live"}}
    assert payload["publish_markers"]["s3_status"] == "ok"
    assert payload["publish_markers"]["pointer_global"] == "ok"
    liveproof_log = tmp_path / "ops" / "proof" / "liveproof-2026-01-02T03:04:05Z.log"
    assert liveproof_log.exists()
    assert calls["kubectl"] == 1
    assert calls["verify"] == 1
    assert calls["git"] == 1
