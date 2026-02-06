import json

import scripts.aws_env_check as aws_env_check


def _clear_aws_env(monkeypatch) -> None:
    keys = [
        "JOBINTEL_S3_BUCKET",
        "BUCKET",
        "AWS_REGION",
        "AWS_DEFAULT_REGION",
        "REGION",
        "JOBINTEL_AWS_REGION",
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


class _StubCreds:
    def __init__(self, method: str = "stub") -> None:
        self.method = method


class _StubSTS:
    def get_caller_identity(self):
        return {"Account": "123456789012"}


class _StubSession:
    def __init__(self, creds):
        self._creds = creds

    def get_credentials(self):
        return self._creds

    def client(self, _service, region_name=None):
        assert region_name
        return _StubSTS()


def test_aws_env_check_missing_required(monkeypatch, capsys):
    _clear_aws_env(monkeypatch)
    monkeypatch.setattr(aws_env_check.boto3.session, "Session", lambda: _StubSession(None))
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
    monkeypatch.setenv("JOBINTEL_AWS_REGION", "us-west-2")
    monkeypatch.setattr(aws_env_check.boto3.session, "Session", lambda: _StubSession(_StubCreds("env")))
    code = aws_env_check.main(["--json"])
    payload = _load_json_output(capsys)
    assert code == 0
    assert payload["ok"] is True
    assert payload["resolved"]["credentials"]["present"] is True
    assert payload["resolved"]["credentials"]["source"] == "env"
    serialized = json.dumps(payload)
    assert "AKIA_TEST_KEY" not in serialized


def test_aws_env_check_profile_creds_ok(monkeypatch, capsys):
    _clear_aws_env(monkeypatch)
    monkeypatch.setenv("JOBINTEL_S3_BUCKET", "bucket")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setattr(aws_env_check.boto3.session, "Session", lambda: _StubSession(_StubCreds("profile")))
    code = aws_env_check.main(["--json"])
    payload = _load_json_output(capsys)
    assert code == 0
    assert payload["ok"] is True
    assert payload["resolved"]["credentials"]["present"] is True
    assert payload["resolved"]["credentials"]["source"] == "profile"


def test_aws_env_check_ecs_creds_ok(monkeypatch, capsys):
    _clear_aws_env(monkeypatch)
    monkeypatch.setenv("JOBINTEL_S3_BUCKET", "bucket")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-2")
    monkeypatch.setattr(aws_env_check.boto3.session, "Session", lambda: _StubSession(_StubCreds("ecs")))
    code = aws_env_check.main(["--json"])
    payload = _load_json_output(capsys)
    assert code == 0
    assert payload["ok"] is True
    assert payload["resolved"]["credentials"]["present"] is True
    assert payload["resolved"]["credentials"]["source"] == "ecs"


def test_aws_env_check_prefix_empty_warn(monkeypatch, capsys):
    _clear_aws_env(monkeypatch)
    monkeypatch.setenv("JOBINTEL_S3_BUCKET", "bucket")
    monkeypatch.setenv("AWS_REGION", "us-west-1")
    monkeypatch.setattr(aws_env_check.boto3.session, "Session", lambda: _StubSession(_StubCreds("env")))
    monkeypatch.setenv("JOBINTEL_S3_PREFIX", "///")
    code = aws_env_check.main(["--json"])
    payload = _load_json_output(capsys)
    assert code == 0
    assert payload["ok"] is True
    assert payload["resolved"]["prefix"] is None
    assert any("prefix resolved to empty" in warning for warning in payload["warnings"])
