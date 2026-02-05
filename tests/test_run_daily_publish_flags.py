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


def test_publish_s3_flag_missing_env_fails_when_required(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    state_dir = tmp_path / "state"
    _write_minimal_inputs(data_dir)
    state_dir.mkdir(parents=True, exist_ok=True)

    env = _build_env(data_dir, state_dir)
    env["PUBLISH_S3_REQUIRE"] = "1"
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
    assert "S3 publish required" in combined


def test_publish_s3_missing_bucket_skips_when_optional(tmp_path: Path) -> None:
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
    assert result.returncode == 0, result.stderr
    combined = f"{result.stdout}\n{result.stderr}"
    assert "skipping" in combined.lower()


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
    assert any(token in combined for token in ("dry_run", "dry-run", "dry run", "S3 publish enabled"))


def test_aws_preflight_irsa_credentials(monkeypatch) -> None:
    import scripts.aws_env_check as aws_env_check

    monkeypatch.setenv("JOBINTEL_S3_BUCKET", "bucket")
    monkeypatch.setenv("JOBINTEL_AWS_REGION", "us-east-1")
    monkeypatch.setenv("AWS_ROLE_ARN", "arn:aws:iam::123456789012:role/jobintel")
    monkeypatch.setenv("AWS_WEB_IDENTITY_TOKEN_FILE", "/var/run/secrets/eks.amazonaws.com/serviceaccount/token")

    class _StubCreds:
        method = "assume-role-with-web-identity"

    class _StubSTS:
        def get_caller_identity(self):
            return {"Account": "123456789012"}

    class _StubSession:
        def get_credentials(self):
            return _StubCreds()

        def client(self, _service, region_name=None):
            assert region_name
            return _StubSTS()

    monkeypatch.setattr(aws_env_check.boto3.session, "Session", _StubSession)

    report = aws_env_check._build_report("bucket", "us-east-1", "jobintel")
    assert report["ok"] is True
    creds = report["resolved"]["credentials"]
    assert creds["present"] is True
    assert creds["source"] == "assume-role-with-web-identity"
