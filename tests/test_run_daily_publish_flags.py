import os
import subprocess
import sys
from pathlib import Path


def _build_env(data_dir: Path, state_dir: Path) -> dict:
    env = os.environ.copy()
    env["JOBINTEL_DATA_DIR"] = str(data_dir)
    env["JOBINTEL_STATE_DIR"] = str(state_dir)
    env["CAREERS_MODE"] = "SNAPSHOT"
    return env


def _write_minimal_inputs(data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    snapshot_dir = data_dir / "openai_snapshots"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    (snapshot_dir / "index.html").write_text("<html>test</html>", encoding="utf-8")
    (data_dir / "openai_raw_jobs.json").write_text("[]", encoding="utf-8")
    (data_dir / "openai_labeled_jobs.json").write_text("[]", encoding="utf-8")
    (data_dir / "openai_enriched_jobs.json").write_text("[]", encoding="utf-8")
    (data_dir / "candidate_profile.json").write_text('{"skills": [], "roles": []}', encoding="utf-8")


def test_publish_s3_flag_missing_env_fails(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    state_dir = tmp_path / "state"
    _write_minimal_inputs(data_dir)
    state_dir.mkdir(parents=True, exist_ok=True)

    env = _build_env(data_dir, state_dir)
    env.pop("JOBINTEL_S3_BUCKET", None)
    env.pop("AWS_REGION", None)
    env.pop("AWS_DEFAULT_REGION", None)
    env.pop("AWS_ACCESS_KEY_ID", None)
    env.pop("AWS_SECRET_ACCESS_KEY", None)
    env.pop("AWS_CONTAINER_CREDENTIALS_RELATIVE_URI", None)
    env.pop("AWS_CONTAINER_CREDENTIALS_FULL_URI", None)
    env.pop("AWS_PROFILE", None)
    env.pop("AWS_SHARED_CREDENTIALS_FILE", None)

    result = subprocess.run(
        [
            sys.executable,
            "scripts/run_daily.py",
            "--profiles",
            "cs",
            "--providers",
            "openai",
            "--snapshot-only",
            "--no_post",
            "--no_subprocess",
            "--publish-s3",
        ],
        cwd=str(Path(__file__).parent.parent),
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    combined = f"{result.stdout}\n{result.stderr}"
    assert "AWS preflight failed" in combined
    assert "bucket is required" in combined


def test_publish_s3_dry_run_without_creds_succeeds(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    state_dir = tmp_path / "state"
    _write_minimal_inputs(data_dir)
    state_dir.mkdir(parents=True, exist_ok=True)

    env = _build_env(data_dir, state_dir)
    env["JOBINTEL_S3_BUCKET"] = "bucket"
    env["AWS_REGION"] = "us-east-1"
    env.pop("AWS_ACCESS_KEY_ID", None)
    env.pop("AWS_SECRET_ACCESS_KEY", None)
    env.pop("AWS_CONTAINER_CREDENTIALS_RELATIVE_URI", None)
    env.pop("AWS_CONTAINER_CREDENTIALS_FULL_URI", None)
    env.pop("AWS_PROFILE", None)
    env.pop("AWS_SHARED_CREDENTIALS_FILE", None)

    result = subprocess.run(
        [
            sys.executable,
            "scripts/run_daily.py",
            "--profiles",
            "cs",
            "--providers",
            "openai",
            "--snapshot-only",
            "--no_post",
            "--no_subprocess",
            "--publish-s3",
            "--publish-dry-run",
        ],
        cwd=str(Path(__file__).parent.parent),
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    combined = f"{result.stdout}\n{result.stderr}"
    assert "dry-run" in combined
