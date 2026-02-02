import json
from pathlib import Path

import scripts.aws_env_check as aws_env_check


def _clear_aws_env(monkeypatch) -> None:
    keys = [
        "JOBINTEL_S3_BUCKET",
        "BUCKET",
        "AWS_REGION",
        "AWS_DEFAULT_REGION",
        "REGION",
        "JOBINTEL_S3_PREFIX",
        "PREFIX",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AWS_PROFILE",
        "AWS_SHARED_CREDENTIALS_FILE",
        "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI",
        "AWS_CONTAINER_CREDENTIALS_FULL_URI",
        "AWS_EC2_METADATA_DISABLED",
    ]
    for key in keys:
        monkeypatch.delenv(key, raising=False)


def _load_json_output(capsys):
    out = capsys.readouterr().out
    return json.loads(out)


def test_aws_env_check_missing_required(monkeypatch, capsys):
    _clear_aws_env(monkeypatch)
    code = aws_env_check.main(["--json"])
    payload = _load_json_output(capsys)
    assert code == 2
    assert payload["ok"] is False
    assert "bucket is required" in " ".join(payload["errors"])
    assert "region is required" in " ".join(payload["errors"])
    assert "credentials not detected" in " ".join(payload["errors"])


def test_aws_env_check_env_creds_ok(monkeypatch, capsys):
    _clear_aws_env(monkeypatch)
    monkeypatch.setenv("JOBINTEL_S3_BUCKET", "bucket")
    monkeypatch.setenv("AWS_REGION", "us-west-2")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIA_TEST_KEY")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "SUPER_SECRET")
    code = aws_env_check.main(["--json"])
    payload = _load_json_output(capsys)
    assert code == 0
    assert payload["ok"] is True
    assert payload["resolved"]["credentials"] == {"present": True, "source": "env"}
    serialized = json.dumps(payload)
    assert "AKIA_TEST_KEY" not in serialized
    assert "SUPER_SECRET" not in serialized


def test_aws_env_check_profile_creds_ok(monkeypatch, capsys, tmp_path: Path):
    _clear_aws_env(monkeypatch)
    monkeypatch.setenv("JOBINTEL_S3_BUCKET", "bucket")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    cred_file = tmp_path / "credentials"
    cred_file.write_text("[default]\naws_access_key_id=abc\naws_secret_access_key=def\n", encoding="utf-8")
    monkeypatch.setenv("AWS_PROFILE", "default")
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(cred_file))
    code = aws_env_check.main(["--json"])
    payload = _load_json_output(capsys)
    assert code == 0
    assert payload["ok"] is True
    assert payload["resolved"]["credentials"] == {"present": True, "source": "profile"}


def test_aws_env_check_ecs_creds_ok(monkeypatch, capsys):
    _clear_aws_env(monkeypatch)
    monkeypatch.setenv("JOBINTEL_S3_BUCKET", "bucket")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-2")
    monkeypatch.setenv("AWS_CONTAINER_CREDENTIALS_RELATIVE_URI", "/v2/credentials")
    code = aws_env_check.main(["--json"])
    payload = _load_json_output(capsys)
    assert code == 0
    assert payload["ok"] is True
    assert payload["resolved"]["credentials"] == {"present": True, "source": "ecs"}


def test_aws_env_check_prefix_empty_warn(monkeypatch, capsys):
    _clear_aws_env(monkeypatch)
    monkeypatch.setenv("JOBINTEL_S3_BUCKET", "bucket")
    monkeypatch.setenv("AWS_REGION", "us-west-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIA_TEST_KEY")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "SUPER_SECRET")
    monkeypatch.setenv("JOBINTEL_S3_PREFIX", "///")
    code = aws_env_check.main(["--json"])
    payload = _load_json_output(capsys)
    assert code == 0
    assert payload["ok"] is True
    assert payload["resolved"]["prefix"] is None
    assert any("prefix resolved to empty" in warning for warning in payload["warnings"])
