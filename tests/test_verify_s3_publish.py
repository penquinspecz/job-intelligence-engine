from __future__ import annotations

import json
from typing import Any

import scripts.verify_s3_publish as verify


class _StubBody:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def read(self) -> bytes:
        return self._data


class _StubS3:
    def __init__(self, keys: set[str], pointer: dict[str, Any]) -> None:
        self._keys = keys
        self._pointer = pointer

    def get_object(self, Bucket: str, Key: str):
        data = json.dumps(self._pointer).encode("utf-8")
        return {"Body": _StubBody(data)}

    def head_object(self, Bucket: str, Key: str) -> None:
        if Key not in self._keys:
            raise verify.ClientError({"Error": {"Code": "NotFound", "Message": "missing"}}, "HeadObject")


class _StubSession:
    def __init__(self, client) -> None:
        self._client = client

    def client(self, name: str):
        assert name == "s3"
        return self._client


def test_missing_env(monkeypatch, capsys) -> None:
    monkeypatch.delenv("JOBINTEL_S3_BUCKET", raising=False)
    monkeypatch.delenv("AWS_REGION", raising=False)
    monkeypatch.delenv("JOBINTEL_AWS_REGION", raising=False)
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
    rc = verify.main()
    assert rc == 2
    err = capsys.readouterr().err
    assert "JOBINTEL_S3_BUCKET" in err


def test_verify_ok(monkeypatch, capsys) -> None:
    monkeypatch.setenv("JOBINTEL_S3_BUCKET", "bucket")
    monkeypatch.setenv("JOBINTEL_AWS_REGION", "us-east-1")
    monkeypatch.setenv("JOBINTEL_S3_PREFIX", "jobintel")

    run_id = "2026-01-01T00:00:00Z"
    pointer = {"run_id": run_id}
    keys = set()
    for base in (
        "jobintel/latest/openai/cs",
        f"jobintel/runs/{run_id}/openai/cs",
    ):
        for name in verify.REQUIRED_KEYS:
            keys.add(f"{base}/{name}")

    client = _StubS3(keys, pointer)
    monkeypatch.setattr(verify.boto3.session, "Session", lambda region_name=None: _StubSession(client))

    rc = verify.main()
    assert rc == 0
    out = capsys.readouterr().out
    assert "verify_s3_publish: ok" in out


def test_missing_key(monkeypatch, capsys) -> None:
    monkeypatch.setenv("JOBINTEL_S3_BUCKET", "bucket")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    run_id = "2026-01-01T00:00:00Z"
    pointer = {"run_id": run_id}
    client = _StubS3(set(), pointer)
    monkeypatch.setattr(verify.boto3.session, "Session", lambda region_name=None: _StubSession(client))

    rc = verify.main()
    assert rc == 3
    err = capsys.readouterr().err
    assert "missing key" in err
