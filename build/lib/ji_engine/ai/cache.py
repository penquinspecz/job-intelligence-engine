from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

from ji_engine.config import DATA_DIR
from ji_engine.utils.atomic_write import atomic_write_text


class AICache:
    def get(self, job_id: str, content_hash: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    def put(self, job_id: str, content_hash: str, payload: Dict[str, Any]) -> None:
        raise NotImplementedError


class FileSystemAICache(AICache):
    def __init__(self, root: Path = DATA_DIR / "ai_cache"):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, job_id: str, content_hash: str) -> Path:
        return self.root / f"{job_id}.{content_hash}.json"

    def get(self, job_id: str, content_hash: str) -> Optional[Dict[str, Any]]:
        path = self._path(job_id, content_hash)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def put(self, job_id: str, content_hash: str, payload: Dict[str, Any]) -> None:
        path = self._path(job_id, content_hash)
        atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2))


def _get_boto3_client():
    try:
        import boto3  # type: ignore
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError("boto3 is required for S3 cache but is not installed. Install with extra 'aws'.") from exc
    region = os.getenv("AWS_REGION") or None
    return boto3.client("s3", region_name=region)


def _s3_key(prefix: str, kind: str, name: str) -> str:
    clean_prefix = prefix.strip("/")
    full_prefix = f"{clean_prefix}/" if clean_prefix else ""
    return f"{full_prefix}{kind}/{name}"


def _sanitize(name: str) -> str:
    return name.replace("/", "_").replace(":", "_")


class S3AICache(AICache):
    """
    S3-backed AI cache. Defaults to filesystem unless explicitly selected.
    """

    def __init__(self, bucket: str, prefix: str = "", client: Any = None):
        self.bucket = bucket
        self.prefix = prefix
        self.client = client or _get_boto3_client()

    def _key(self, job_id: str, content_hash: str) -> str:
        safe = _sanitize(job_id)
        return _s3_key(self.prefix, "ai_cache", f"{safe}.{content_hash}.json")

    def get(self, job_id: str, content_hash: str) -> Optional[Dict[str, Any]]:
        key = self._key(job_id, content_hash)
        try:
            obj = self.client.get_object(Bucket=self.bucket, Key=key)
            body = obj["Body"].read()
            return json.loads(body.decode("utf-8"))
        except self.client.exceptions.NoSuchKey:
            return None
        except Exception:
            return None

    def put(self, job_id: str, content_hash: str, payload: Dict[str, Any]) -> None:
        key = self._key(job_id, content_hash)
        data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data)
