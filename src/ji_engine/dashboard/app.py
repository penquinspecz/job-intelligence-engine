"""
SignalCraft
Copyright (c) 2026 Chris Menendez.
All Rights Reserved.
See LICENSE for permitted use.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import boto3
from botocore.exceptions import ClientError

try:
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import Response
except ModuleNotFoundError as exc:  # pragma: no cover - exercised in environments without dashboard extras
    raise RuntimeError("Dashboard dependencies are not installed. Install with: pip install -e '.[dashboard]'") from exc

from ji_engine.config import RUN_METADATA_DIR, STATE_DIR
from jobintel import aws_runs

app = FastAPI(title="SignalCraft Dashboard API")


def _sanitize_run_id(run_id: str) -> str:
    return run_id.replace(":", "").replace("-", "").replace(".", "")


def _run_dir(run_id: str) -> Path:
    return RUN_METADATA_DIR / _sanitize_run_id(run_id)


def _load_index(run_id: str) -> Dict[str, Any]:
    index_path = _run_dir(run_id) / "index.json"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="Run not found")
    try:
        data = json.loads(index_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail="Run index is invalid JSON") from exc
    if not isinstance(data, dict):
        raise HTTPException(status_code=500, detail="Run index has invalid shape")
    return data


def _load_json_object(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _load_first_ai_prompt_version(run_dir: Path) -> Optional[str]:
    for path in sorted(run_dir.glob("ai_insights.*.json"), key=lambda p: p.name):
        payload = _load_json_object(path)
        if not payload:
            continue
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        prompt_version = (metadata or {}).get("prompt_version")
        if isinstance(prompt_version, str) and prompt_version.strip():
            return prompt_version
    return None


def _list_runs() -> List[Dict[str, Any]]:
    if not RUN_METADATA_DIR.exists():
        return []
    runs: List[Dict[str, Any]] = []
    for path in RUN_METADATA_DIR.iterdir():
        if not path.is_dir():
            continue
        index_path = path / "index.json"
        if not index_path.exists():
            continue
        try:
            data = json.loads(index_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            runs.append(data)
    runs.sort(key=lambda r: r.get("timestamp") or "", reverse=True)
    return runs


def _resolve_artifact_path(run_dir: Path, index: Dict[str, Any], name: str) -> Path:
    if "/" in name or "\\" in name:
        raise HTTPException(status_code=400, detail="Invalid artifact name")

    artifacts = index.get("artifacts") if isinstance(index.get("artifacts"), dict) else {}
    rel = artifacts.get(name)
    if not isinstance(rel, str) or not rel.strip():
        raise HTTPException(status_code=404, detail="Artifact not found")

    rel_path = Path(rel)
    if rel_path.is_absolute() or ".." in rel_path.parts:
        raise HTTPException(status_code=500, detail="Artifact mapping is invalid")

    candidate = (run_dir / rel_path).resolve()
    if run_dir.resolve() not in candidate.parents and candidate != run_dir.resolve():
        raise HTTPException(status_code=400, detail="Invalid artifact path")
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


def _state_last_success_path() -> Path:
    return STATE_DIR / "last_success.json"


def _read_local_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise HTTPException(status_code=404, detail="Local state not found")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail="Local state invalid JSON") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=500, detail="Local state has invalid shape")
    return payload


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
    try:
        payload = json.loads(body.read().decode("utf-8"))
    except Exception:
        return None, "invalid_json"
    if not isinstance(payload, dict):
        return None, "invalid_shape"
    return payload, "ok"


def _local_proof_path(run_id: str) -> Path:
    return STATE_DIR / "proofs" / f"{run_id}.json"


def _s3_proof_key(prefix: str, run_id: str) -> str:
    return f"{prefix}/state/proofs/{run_id}.json".strip("/")


def _s3_latest_prefix(prefix: str, provider: str, profile: str) -> str:
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
def runs() -> List[Dict[str, Any]]:
    return _list_runs()


@app.get("/runs/{run_id}")
def run_detail(run_id: str) -> Dict[str, Any]:
    index = _load_index(run_id)
    run_dir = _run_dir(run_id)
    run_report = _load_json_object(run_dir / "run_report.json") or {}
    costs = _load_json_object(run_dir / "costs.json")
    prompt_version = _load_first_ai_prompt_version(run_dir)
    enriched = dict(index)
    enriched["semantic_enabled"] = bool(run_report.get("semantic_enabled", False))
    enriched["semantic_mode"] = run_report.get("semantic_mode")
    enriched["ai_prompt_version"] = prompt_version
    enriched["cost_summary"] = costs
    return enriched


@app.get("/runs/{run_id}/artifact/{name}")
def run_artifact(run_id: str, name: str) -> Response:
    index = _load_index(run_id)
    run_dir = _run_dir(run_id)
    path = _resolve_artifact_path(run_dir, index, name)
    return Response(path.read_bytes(), media_type=_content_type(path))


@app.get("/runs/{run_id}/semantic_summary/{profile}")
def run_semantic_summary(run_id: str, profile: str) -> Dict[str, Any]:
    run_dir = _run_dir(run_id)
    semantic_dir = run_dir / "semantic"
    summary = _load_json_object(semantic_dir / "semantic_summary.json")
    if not summary:
        raise HTTPException(status_code=404, detail="Semantic summary not found")

    entries: List[Dict[str, Any]] = []
    for path in sorted(semantic_dir.glob(f"scores_*_{profile}.json"), key=lambda p: p.name):
        payload = _load_json_object(path)
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
def latest() -> Dict[str, Any]:
    if _s3_enabled():
        bucket = _s3_bucket()
        prefix = _s3_prefix()
        payload, status, key = aws_runs.read_last_success_state(bucket, prefix)
        if status != "ok" or not payload:
            raise HTTPException(status_code=404, detail=f"s3 last_success not found ({status})")
        return {
            "source": "s3",
            "bucket": bucket,
            "prefix": prefix,
            "key": key,
            "payload": payload,
        }
    payload = _read_local_json(_state_last_success_path())
    return {"source": "local", "path": str(_state_last_success_path()), "payload": payload}


@app.get("/v1/runs/{run_id}")
def run_receipt(run_id: str) -> Dict[str, Any]:
    if _s3_enabled():
        bucket = _s3_bucket()
        prefix = _s3_prefix()
        proof_key = _s3_proof_key(prefix, run_id)
        payload, status = _read_s3_json(bucket, proof_key)
        if status == "ok" and payload:
            return {
                "source": "s3",
                "bucket": bucket,
                "prefix": prefix,
                "key": proof_key,
                "payload": payload,
            }
    local_path = _local_proof_path(run_id)
    payload = _read_local_json(local_path)
    return {"source": "local", "path": str(local_path), "payload": payload}


@app.get("/v1/artifacts/latest/{provider}/{profile}")
def latest_artifacts(provider: str, profile: str) -> Dict[str, Any]:
    if _s3_enabled():
        bucket = _s3_bucket()
        prefix = _s3_prefix()
        latest_prefix = _s3_latest_prefix(prefix, provider, profile)
        keys = _s3_list_keys(bucket, latest_prefix)
        return {"source": "s3", "bucket": bucket, "prefix": latest_prefix, "keys": keys}

    pointer = _read_local_json(_state_last_success_path())
    run_id = pointer.get("run_id")
    if not run_id:
        raise HTTPException(status_code=404, detail="Local last_success missing run_id")
    run_dir = _run_dir(run_id)
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
