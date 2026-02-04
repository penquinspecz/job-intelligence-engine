import json

import pytest

try:
    import boto3
    from moto import mock_s3
except Exception:  # pragma: no cover
    boto3 = None
    mock_s3 = None

from scripts.resolve_s3_run_id import resolve_run_id

pytestmark = pytest.mark.skipif(boto3 is None or mock_s3 is None, reason="boto3/moto not installed")


def _put_json(client, bucket: str, key: str, payload: dict) -> None:
    client.put_object(
        Bucket=bucket,
        Key=key,
        Body=json.dumps(payload).encode("utf-8"),
        ContentType="application/json",
    )


def _put_text(client, bucket: str, key: str, body: str = "[]") -> None:
    client.put_object(
        Bucket=bucket,
        Key=key,
        Body=body.encode("utf-8"),
        ContentType="application/json",
    )


def test_resolve_prefers_pointer_over_latest() -> None:
    with mock_s3():
        bucket = "bucket"
        prefix = "jobintel"
        provider = "openai"
        profile = "cs"
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=bucket)

        run_id_pointer = "2026-01-02T00:00:00Z"
        run_id_new = "2026-01-03T00:00:00Z"

        _put_json(client, bucket, f"{prefix}/state/{provider}/{profile}/last_success.json", {"run_id": run_id_pointer})
        _put_text(client, bucket, f"{prefix}/runs/{run_id_pointer}/run_report.json")
        _put_text(
            client,
            bucket,
            f"{prefix}/runs/{run_id_pointer}/{provider}/{profile}/{provider}_ranked_families.{profile}.json",
        )
        _put_text(client, bucket, f"{prefix}/runs/{run_id_new}/run_report.json")
        _put_text(
            client, bucket, f"{prefix}/runs/{run_id_new}/{provider}/{profile}/{provider}_ranked_families.{profile}.json"
        )

        resolved = resolve_run_id(bucket, prefix, provider, profile, client=client)
        assert resolved == run_id_pointer


def test_resolve_skips_missing_ranked_and_falls_back() -> None:
    with mock_s3():
        bucket = "bucket"
        prefix = "jobintel"
        provider = "openai"
        profile = "cs"
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=bucket)

        run_id_valid = "2026-01-01T00:00:00Z"
        run_id_missing = "2026-01-02T00:00:00Z"

        _put_text(client, bucket, f"{prefix}/runs/{run_id_missing}/run_report.json")
        _put_text(client, bucket, f"{prefix}/runs/{run_id_valid}/run_report.json")
        _put_text(
            client,
            bucket,
            f"{prefix}/runs/{run_id_valid}/{provider}/{profile}/{provider}_ranked_families.{profile}.json",
        )

        resolved = resolve_run_id(bucket, prefix, provider, profile, client=client)
        assert resolved == run_id_valid


def test_resolve_pointer_missing_artifacts_falls_back() -> None:
    with mock_s3():
        bucket = "bucket"
        prefix = "jobintel"
        provider = "openai"
        profile = "cs"
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=bucket)

        run_id_bad = "2026-01-02T00:00:00Z"
        run_id_good = "2026-01-03T00:00:00Z"

        _put_json(client, bucket, f"{prefix}/state/{provider}/{profile}/last_success.json", {"run_id": run_id_bad})
        _put_text(client, bucket, f"{prefix}/runs/{run_id_bad}/run_report.json")

        _put_text(client, bucket, f"{prefix}/runs/{run_id_good}/run_report.json")
        _put_text(
            client,
            bucket,
            f"{prefix}/runs/{run_id_good}/{provider}/{profile}/{provider}_ranked_families.{profile}.json",
        )

        resolved = resolve_run_id(bucket, prefix, provider, profile, client=client)
        assert resolved == run_id_good
