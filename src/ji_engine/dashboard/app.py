"""
SignalCraft
Copyright (c) 2026 Chris Menendez.
All Rights Reserved.
See LICENSE for permitted use.
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Type

import boto3
from botocore.exceptions import ClientError

try:
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import Response
    from pydantic import BaseModel, ConfigDict, Field, ValidationError
except ModuleNotFoundError as exc:  # pragma: no cover - exercised in environments without dashboard extras
    raise RuntimeError("Dashboard dependencies are not installed. Install with: pip install -e '.[dashboard]'") from exc

from ji_engine.config import (
    DEFAULT_CANDIDATE_ID,
    RUN_METADATA_DIR,
    STATE_DIR,
    candidate_state_dir,
    sanitize_candidate_id,
)
from ji_engine.run_repository import FileSystemRunRepository, RunRepository
from jobintel import aws_runs

app = FastAPI(title="SignalCraft Dashboard API")
logger = logging.getLogger(__name__)
RUN_REPOSITORY: RunRepository = FileSystemRunRepository(RUN_METADATA_DIR)


_RUN_ID_RE = re.compile(r"^[A-Za-z0-9_.:+-]{1,128}$")
_DEFAULT_MAX_JSON_BYTES = 2 * 1024 * 1024


class _RunIndexSchema(BaseModel):
    model_config = ConfigDict(extra="allow")

    run_id: Optional[str] = None
    timestamp: Optional[str] = None
    artifacts: Dict[str, str] = Field(default_factory=dict)


class _RunReportSchema(BaseModel):
    model_config = ConfigDict(extra="allow")

    semantic_enabled: Optional[bool] = None
    semantic_mode: Optional[str] = None
    outputs_by_provider: Dict[str, Dict[str, Dict[str, Dict[str, Any]]]] = Field(default_factory=dict)


class _AiInsightsSchema(BaseModel):
    model_config = ConfigDict(extra="allow")

    metadata: Dict[str, Any] = Field(default_factory=dict)


class _DashboardJsonError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _max_json_bytes() -> int:
    raw = os.environ.get("JOBINTEL_DASHBOARD_MAX_JSON_BYTES", str(_DEFAULT_MAX_JSON_BYTES)).strip()
    try:
        parsed = int(raw)
    except ValueError:
        logger.warning(
            "Invalid JOBINTEL_DASHBOARD_MAX_JSON_BYTES=%r; using default=%d",
            raw,
            _DEFAULT_MAX_JSON_BYTES,
        )
        return _DEFAULT_MAX_JSON_BYTES
    if parsed <= 0:
        logger.warning(
            "Non-positive JOBINTEL_DASHBOARD_MAX_JSON_BYTES=%d; using default=%d",
            parsed,
            _DEFAULT_MAX_JSON_BYTES,
        )
        return _DEFAULT_MAX_JSON_BYTES
    return parsed


def _validate_schema(payload: Dict[str, Any], schema: Optional[Type[BaseModel]]) -> None:
    if schema is None:
        return
    try:
        schema.model_validate(payload)
    except ValidationError as exc:
        raise _DashboardJsonError("invalid_schema") from exc


def _read_local_json_object(path: Path, *, schema: Optional[Type[BaseModel]] = None) -> Dict[str, Any]:
    if not path.exists():
        raise _DashboardJsonError("not_found")
    max_bytes = _max_json_bytes()
    try:
        size_bytes = path.stat().st_size
    except OSError as exc:
        raise _DashboardJsonError("io_error") from exc
    if size_bytes > max_bytes:
        raise _DashboardJsonError("too_large")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise _DashboardJsonError("invalid_json") from exc
    except OSError as exc:
        raise _DashboardJsonError("io_error") from exc
    if not isinstance(payload, dict):
        raise _DashboardJsonError("invalid_shape")
    _validate_schema(payload, schema)
    return payload


def _load_optional_json_object(
    path: Path,
    *,
    context: str,
    schema: Optional[Type[BaseModel]] = None,
) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        return _read_local_json_object(path, schema=schema)
    except _DashboardJsonError as exc:
        logger.warning("Skipping %s at %s (%s)", context, path, exc.code)
        return None


def _sanitize_candidate_id(candidate_id: str) -> str:
    try:
        return sanitize_candidate_id(candidate_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid candidate_id") from exc


def _sanitize_run_id(run_id: str) -> str:
    if not isinstance(run_id, str):
        raise HTTPException(status_code=400, detail="Invalid run_id")
    raw = run_id.strip()
    if not _RUN_ID_RE.fullmatch(raw):
        raise HTTPException(status_code=400, detail="Invalid run_id")
    return raw.replace(":", "").replace("-", "").replace(".", "")


def _run_dir(run_id: str, candidate_id: str) -> Path:
    _sanitize_run_id(run_id)
    return RUN_REPOSITORY.resolve_run_dir(run_id, candidate_id=_sanitize_candidate_id(candidate_id))


def _load_index(run_id: str, candidate_id: str) -> Dict[str, Any]:
    safe_candidate = _sanitize_candidate_id(candidate_id)
    index_path = RUN_REPOSITORY.resolve_run_artifact_path(run_id, "index.json", candidate_id=safe_candidate)
    try:
        return _read_local_json_object(index_path, schema=_RunIndexSchema)
    except _DashboardJsonError as exc:
        logger.warning("Failed to load run index at %s (%s)", index_path, exc.code)
        if exc.code == "not_found":
            raise HTTPException(status_code=404, detail="Run not found") from exc
        if exc.code == "too_large":
            raise HTTPException(status_code=413, detail="Run index payload too large") from exc
        if exc.code == "invalid_json":
            raise HTTPException(status_code=500, detail="Run index is invalid JSON") from exc
        raise HTTPException(status_code=500, detail="Run index has invalid shape") from exc


def _load_first_ai_prompt_version(run_dir: Path) -> Optional[str]:
    for path in sorted(run_dir.glob("ai_insights.*.json"), key=lambda p: p.name):
        payload = _load_optional_json_object(path, context="AI insights payload", schema=_AiInsightsSchema)
        if not payload:
            continue
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        prompt_version = (metadata or {}).get("prompt_version")
        if isinstance(prompt_version, str) and prompt_version.strip():
            return prompt_version
    return None


def _list_runs(candidate_id: str) -> List[Dict[str, Any]]:
    runs: List[Dict[str, Any]] = []
    safe_candidate = _sanitize_candidate_id(candidate_id)
    for path in RUN_REPOSITORY.list_run_dirs(candidate_id=safe_candidate):
        index_path = path / "index.json"
        if not index_path.exists():
            continue
        try:
            data = _read_local_json_object(index_path, schema=_RunIndexSchema)
        except _DashboardJsonError as exc:
            logger.warning("Skipping run index at %s (%s)", index_path, exc.code)
            continue
        runs.append(data)
    runs.sort(key=lambda r: r.get("timestamp") or "", reverse=True)
    return runs

def _resolve_artifact_path(run_id: str, candidate_id: str, index: Dict[str, Any], name: str) -> Path:
    if "/" in name or "\\" in name:
        raise HTTPException(status_code=400, detail="Invalid artifact name")
    artifacts = index.get("artifacts") if isinstance(index.get("artifacts"), dict) else {}
    rel = artifacts.get(name)
    if not isinstance(rel, str) or not rel.strip():
        raise HTTPException(status_code=404, detail="Artifact not found")

    rel_path = Path(rel)
    if rel_path.is_absolute() or ".." in rel_path.parts:
        raise HTTPException(status_code=500, detail="Artifact mapping is invalid")

    safe_candidate = _sanitize_candidate_id(candidate_id)
    try:
        candidate = RUN_REPOSITORY.resolve_run_artifact_path(
            run_id,
            rel_path.as_posix(),
            candidate_id=safe_candidate,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid artifact path") from exc
    if not candidate.exists():
        raise HTTPException(status_code=404, detail="Artifact not found")
    return candidate


def _content_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".json":
        return "application/json"
    if suffix == ".csv":
        return "text/csv"
    if suffix in {".md", ".markdown"}:
        return "text/markdown"
    return "text/plain"


def _s3_bucket() -> str:
    return os.environ.get("JOBINTEL_S3_BUCKET", "").strip()


def _s3_prefix() -> str:
    return os.environ.get("JOBINTEL_S3_PREFIX", "jobintel").strip().strip("/")


def _s3_enabled() -> bool:
    return bool(_s3_bucket())


def _state_last_success_path(candidate_id: str) -> Path:
    safe_candidate = _sanitize_candidate_id(candidate_id)
    namespaced = candidate_state_dir(safe_candidate) / "last_success.json"
    if namespaced.exists():
        return namespaced
    if safe_candidate == DEFAULT_CANDIDATE_ID:
        return STATE_DIR / "last_success.json"
    return namespaced


def _read_local_json(path: Path) -> Dict[str, Any]:
    try:
        return _read_local_json_object(path)
    except _DashboardJsonError as exc:
        logger.warning("Failed to read local JSON at %s (%s)", path, exc.code)
        if exc.code == "not_found":
            raise HTTPException(status_code=404, detail="Local state not found") from exc
        if exc.code == "too_large":
            raise HTTPException(status_code=413, detail="Local state payload too large") from exc
        if exc.code == "invalid_json":
            raise HTTPException(status_code=500, detail="Local state invalid JSON") from exc
        raise HTTPException(status_code=500, detail="Local state has invalid shape") from exc


def _read_s3_json(bucket: str, key: str) -> Tuple[Optional[Dict[str, Any]], str]:
    s3 = boto3.client("s3")
    try:
        resp = s3.get_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in {"NoSuchKey", "404"}:
            return None, "not_found"
        if code in {"AccessDenied", "403"}:
            return None, "access_denied"
        return None, f"error:{code or exc.__class__.__name__}"
    body = resp.get("Body")
    if body is None:
        return None, "empty_body"
    max_bytes = _max_json_bytes()
    content_length = resp.get("ContentLength")
    if isinstance(content_length, int) and content_length > max_bytes:
        logger.warning(
            "S3 JSON payload too large: s3://%s/%s bytes=%d limit=%d", bucket, key, content_length, max_bytes
        )
        return None, "too_large"
    try:
        raw = body.read(max_bytes + 1)
        if len(raw) > max_bytes:
            logger.warning("S3 JSON payload exceeded read limit: s3://%s/%s limit=%d", bucket, key, max_bytes)
            return None, "too_large"
        payload = json.loads(raw.decode("utf-8"))
    except Exception:
        return None, "invalid_json"
    if not isinstance(payload, dict):
        return None, "invalid_shape"
    return payload, "ok"


def _local_proof_path(run_id: str, candidate_id: str) -> Path:
    safe_candidate = _sanitize_candidate_id(candidate_id)
    namespaced = candidate_state_dir(safe_candidate) / "proofs" / f"{run_id}.json"
    if namespaced.exists():
        return namespaced
    if safe_candidate == DEFAULT_CANDIDATE_ID:
        return STATE_DIR / "proofs" / f"{run_id}.json"
    return namespaced


def _s3_proof_key(prefix: str, run_id: str, candidate_id: str) -> str:
    safe_candidate = _sanitize_candidate_id(candidate_id)
    return f"{prefix}/state/candidates/{safe_candidate}/proofs/{run_id}.json".strip("/")


def _s3_legacy_proof_key(prefix: str, run_id: str) -> str:
    return f"{prefix}/state/proofs/{run_id}.json".strip("/")


def _s3_latest_prefix(prefix: str, provider: str, profile: str, candidate_id: str) -> str:
    safe_candidate = _sanitize_candidate_id(candidate_id)
    if safe_candidate == DEFAULT_CANDIDATE_ID:
        return f"{prefix}/latest/{provider}/{profile}/".strip("/")
    return f"{prefix}/candidates/{safe_candidate}/latest/{provider}/{profile}/".strip("/")


def _s3_legacy_latest_prefix(prefix: str, provider: str, profile: str) -> str:
    return f"{prefix}/latest/{provider}/{profile}/".strip("/")


def _s3_list_keys(bucket: str, prefix: str) -> List[str]:
    s3 = boto3.client("s3")
    keys: List[str] = []
    token = None
    while True:
        kwargs: Dict[str, Any] = {"Bucket": bucket, "Prefix": prefix}
        if token:
            kwargs["ContinuationToken"] = token
        resp = s3.list_objects_v2(**kwargs)
        for obj in resp.get("Contents") or []:
            key = obj.get("Key")
            if key:
                keys.append(key)
        if not resp.get("IsTruncated"):
            break
        token = resp.get("NextContinuationToken")
    return keys


@app.get("/healthz")
def healthz() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/runs")
def runs(candidate_id: str = DEFAULT_CANDIDATE_ID) -> List[Dict[str, Any]]:
    return _list_runs(candidate_id)


@app.get("/runs/{run_id}")
def run_detail(run_id: str, candidate_id: str = DEFAULT_CANDIDATE_ID) -> Dict[str, Any]:
    _sanitize_run_id(run_id)
    index = _load_index(run_id, candidate_id)
    run_dir = _run_dir(run_id, candidate_id)
    run_report = (
        _load_optional_json_object(run_dir / "run_report.json", context="run report", schema=_RunReportSchema) or {}
    )
    costs = _load_optional_json_object(run_dir / "costs.json", context="run costs")
    prompt_version = _load_first_ai_prompt_version(run_dir)
    enriched = dict(index)
    enriched["semantic_enabled"] = bool(run_report.get("semantic_enabled", False))
    enriched["semantic_mode"] = run_report.get("semantic_mode")
    enriched["ai_prompt_version"] = prompt_version
    enriched["cost_summary"] = costs
    return enriched


@app.get("/runs/{run_id}/artifact/{name}")
def run_artifact(run_id: str, name: str, candidate_id: str = DEFAULT_CANDIDATE_ID) -> Response:
    _sanitize_run_id(run_id)
    index = _load_index(run_id, candidate_id)
    path = _resolve_artifact_path(run_id, candidate_id, index, name)
    return Response(path.read_bytes(), media_type=_content_type(path))


@app.get("/runs/{run_id}/semantic_summary/{profile}")
def run_semantic_summary(run_id: str, profile: str, candidate_id: str = DEFAULT_CANDIDATE_ID) -> Dict[str, Any]:
    _sanitize_run_id(run_id)
    run_dir = _run_dir(run_id, candidate_id)
    semantic_dir = run_dir / "semantic"
    summary_path = semantic_dir / "semantic_summary.json"
    if not summary_path.exists():
        raise HTTPException(status_code=404, detail="Semantic summary not found")
    try:
        summary = _read_local_json_object(summary_path)
    except _DashboardJsonError as exc:
        logger.warning("Semantic summary read failed at %s (%s)", summary_path, exc.code)
        if exc.code == "too_large":
            raise HTTPException(status_code=413, detail="Semantic summary payload too large") from exc
        if exc.code == "invalid_json":
            raise HTTPException(status_code=500, detail="Semantic summary invalid JSON") from exc
        raise HTTPException(status_code=500, detail="Semantic summary has invalid shape") from exc

    entries: List[Dict[str, Any]] = []
    for path in sorted(semantic_dir.glob(f"scores_*_{profile}.json"), key=lambda p: p.name):
        payload = _load_optional_json_object(path, context="semantic scores payload")
        if not payload:
            continue
        payload_entries = payload.get("entries")
        if not isinstance(payload_entries, list):
            continue
        for item in payload_entries:
            if isinstance(item, dict):
                entries.append(item)

    entries.sort(key=lambda item: (str(item.get("provider") or ""), str(item.get("job_id") or "")))
    return {"run_id": run_id, "profile": profile, "summary": summary, "entries": entries}


@app.get("/v1/latest")
def latest(candidate_id: str = DEFAULT_CANDIDATE_ID) -> Dict[str, Any]:
    safe_candidate = _sanitize_candidate_id(candidate_id)
    if _s3_enabled():
        bucket = _s3_bucket()
        prefix = _s3_prefix()
        payload, status, key = aws_runs.read_last_success_state(bucket, prefix, candidate_id=safe_candidate)
        if status != "ok" or not payload:
            raise HTTPException(status_code=404, detail=f"s3 last_success not found ({status})")
        return {
            "source": "s3",
            "bucket": bucket,
            "prefix": prefix,
            "key": key,
            "payload": payload,
        }
    pointer_path = _state_last_success_path(safe_candidate)
    payload = _read_local_json(pointer_path)
    return {"source": "local", "path": str(pointer_path), "payload": payload}


@app.get("/v1/runs/{run_id}")
def run_receipt(run_id: str, candidate_id: str = DEFAULT_CANDIDATE_ID) -> Dict[str, Any]:
    _sanitize_run_id(run_id)
    safe_candidate = _sanitize_candidate_id(candidate_id)
    if _s3_enabled():
        bucket = _s3_bucket()
        prefix = _s3_prefix()
        proof_key = _s3_proof_key(prefix, run_id, safe_candidate)
        payload, status = _read_s3_json(bucket, proof_key)
        if status != "ok" and safe_candidate == DEFAULT_CANDIDATE_ID:
            legacy_key = _s3_legacy_proof_key(prefix, run_id)
            payload, status = _read_s3_json(bucket, legacy_key)
            proof_key = legacy_key
        if status == "ok" and payload:
            return {
                "source": "s3",
                "bucket": bucket,
                "prefix": prefix,
                "key": proof_key,
                "payload": payload,
            }
    local_path = _local_proof_path(run_id, safe_candidate)
    payload = _read_local_json(local_path)
    return {"source": "local", "path": str(local_path), "payload": payload}


@app.get("/v1/artifacts/latest/{provider}/{profile}")
def latest_artifacts(provider: str, profile: str, candidate_id: str = DEFAULT_CANDIDATE_ID) -> Dict[str, Any]:
    safe_candidate = _sanitize_candidate_id(candidate_id)
    if _s3_enabled():
        bucket = _s3_bucket()
        prefix = _s3_prefix()
        latest_prefix = _s3_latest_prefix(prefix, provider, profile, safe_candidate)
        keys = _s3_list_keys(bucket, latest_prefix)
        if not keys and safe_candidate == DEFAULT_CANDIDATE_ID:
            latest_prefix = _s3_legacy_latest_prefix(prefix, provider, profile)
            keys = _s3_list_keys(bucket, latest_prefix)
        return {"source": "s3", "bucket": bucket, "prefix": latest_prefix, "keys": keys}

    pointer = _read_local_json(_state_last_success_path(safe_candidate))
    run_id = pointer.get("run_id")
    if not run_id:
        raise HTTPException(status_code=404, detail="Local last_success missing run_id")
    run_dir = _run_dir(run_id, safe_candidate)
    report_path = run_dir / "run_report.json"
    if not report_path.exists():
        raise HTTPException(status_code=404, detail="Local run_report not found")
    report = _read_local_json(report_path)
    outputs = report.get("outputs_by_provider", {}).get(provider, {}).get(profile, {})
    if not isinstance(outputs, dict) or not outputs:
        raise HTTPException(status_code=404, detail="No artifacts for provider/profile")
    files = [item.get("path") for item in outputs.values() if isinstance(item, dict) and item.get("path")]
    return {
        "source": "local",
        "run_id": run_id,
        "paths": files,
    }
