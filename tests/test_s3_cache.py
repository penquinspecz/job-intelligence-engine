from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from ji_engine.ai.cache import S3AICache
from ji_engine.embeddings.simple import load_cache, save_cache


try:
    import boto3
    from moto import mock_s3
except ImportError:  # pragma: no cover - optional dependency
    boto3 = None
    mock_s3 = None


pytestmark = pytest.mark.skipif(boto3 is None or mock_s3 is None, reason="boto3/moto not installed")


if mock_s3:
    @mock_s3
    def test_s3_ai_cache_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
        bucket = "test-bucket"
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=bucket)

        cache = S3AICache(bucket=bucket, prefix="pref")
        payload = {"foo": "bar"}
        cache.put("job/1", "hash123", payload)

        got = cache.get("job/1", "hash123")
        assert got == payload


    @mock_s3
    def test_s3_embedding_cache_load_save(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        bucket = "test-bucket"
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=bucket)

        monkeypatch.setenv("JOBINTEL_S3_BUCKET", bucket)
        monkeypatch.setenv("JOBINTEL_S3_PREFIX", "pref")

        cache_path = Path("state/embed_cache.json")
        data = {"profile": {"p": [1]}, "job": {"j": [1, 2]}}
        save_cache(cache_path, data)

        out = load_cache(cache_path)
        assert out == data

        # ensure stored object exists in S3
        key = "pref/state/embed_cache.json"
        obj = client.get_object(Bucket=bucket, Key=key)
        stored = json.loads(obj["Body"].read().decode("utf-8"))
        assert stored == data

