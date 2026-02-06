from __future__ import annotations

import json
from typing import Any

import pytest
from botocore.exceptions import ClientError

import scripts.s3_preflight as s3_preflight


class _StubSTS:
    def __init__(self, calls: list[str]) -> None:
        self._calls = calls

    def get_caller_identity(self) -> dict[str, str]:
        self._calls.append("sts.get_caller_identity")
        return {"Account": "123"}


class _StubS3:
    def __init__(self, calls: list[str], error_response: dict | None = None) -> None:
        self._calls = calls
        self._error_response = error_response

    def head_bucket(self, Bucket: str) -> None:
        self._calls.append(f"s3.head_bucket:{Bucket}")
        if self._error_response:
            raise ClientError(self._error_response, "HeadBucket")

    def list_objects_v2(self, Bucket: str, Prefix: str, MaxKeys: int) -> dict[str, Any]:
        self._calls.append(f"s3.list_objects_v2:{Bucket}:{Prefix}:{MaxKeys}")
        return {"KeyCount": 0}


class _StubSession:
    def __init__(self, calls: list[str], error_response: dict | None = None) -> None:
        self._calls = calls
        self._error_response = error_response

    def client(self, name: str):
        if name == "sts":
            return _StubSTS(self._calls)
        if name == "s3":
            return _StubS3(self._calls, error_response=self._error_response)
        raise AssertionError(f"unexpected client: {name}")


def test_missing_env_vars(monkeypatch, capsys) -> None:
    monkeypatch.delenv("JOBINTEL_S3_BUCKET", raising=False)
    monkeypatch.delenv("BUCKET", raising=False)
    monkeypatch.delenv("AWS_REGION", raising=False)
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
    monkeypatch.delenv("JOBINTEL_AWS_REGION", raising=False)
    monkeypatch.delenv("REGION", raising=False)

    rc = s3_preflight.main()
    assert rc == 2
    err = capsys.readouterr().err
    assert "JOBINTEL_S3_BUCKET" in err
    assert "AWS_REGION" in err


def test_success_calls_clients(monkeypatch, capsys) -> None:
    monkeypatch.setenv("JOBINTEL_S3_BUCKET", "bucket")
    monkeypatch.setenv("JOBINTEL_AWS_REGION", "us-east-1")
    monkeypatch.setenv("JOBINTEL_S3_PREFIX", "jobintel")

    calls: list[str] = []
    monkeypatch.setattr(s3_preflight.boto3.session, "Session", lambda region_name=None: _StubSession(calls))

    rc = s3_preflight.main()
    assert rc == 0
    out = capsys.readouterr().out
    payload = json.loads(out.splitlines()[0])
    assert payload["bucket"] == "bucket"
    assert payload["region"] == "us-east-1"
    assert "sts.get_caller_identity" in calls
    assert "s3.head_bucket:bucket" in calls
    assert "s3.list_objects_v2:bucket:jobintel:5" in calls


def test_client_error(monkeypatch, capsys) -> None:
    monkeypatch.setenv("JOBINTEL_S3_BUCKET", "bucket")
    monkeypatch.setenv("AWS_REGION", "us-east-1")

    calls: list[str] = []
    error_response = {
        "Error": {"Code": "AccessDenied", "Message": "Denied"},
        "ResponseMetadata": {"HTTPStatusCode": 403, "HTTPHeaders": {}},
    }
    monkeypatch.setattr(
        s3_preflight.boto3.session, "Session", lambda region_name=None: _StubSession(calls, error_response)
    )

    rc = s3_preflight.main()
    assert rc == 3
    err = capsys.readouterr().err
    assert "Access denied to bucket: bucket" in err


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (
            {"Error": {"Code": "NoSuchBucket", "Message": "Missing"}, "ResponseMetadata": {"HTTPStatusCode": 404}},
            "S3 bucket not found: bucket.",
        ),
        (
            {"Error": {"Code": "AccessDenied", "Message": "Denied"}, "ResponseMetadata": {"HTTPStatusCode": 403}},
            "Access denied to bucket: bucket.",
        ),
        (
            {
                "Error": {"Code": "PermanentRedirect", "Message": "Wrong region"},
                "ResponseMetadata": {
                    "HTTPStatusCode": 301,
                    "HTTPHeaders": {"x-amz-bucket-region": "us-west-2"},
                },
            },
            "Bucket exists in region us-west-2; set JOBINTEL_AWS_REGION accordingly.",
        ),
    ],
)
def test_error_messages(monkeypatch, capsys, response, expected) -> None:
    monkeypatch.setenv("JOBINTEL_S3_BUCKET", "bucket")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    calls: list[str] = []
    monkeypatch.setattr(s3_preflight.boto3.session, "Session", lambda region_name=None: _StubSession(calls, response))
    rc = s3_preflight.main()
    assert rc == 3
    err = capsys.readouterr().err
    assert expected in err
