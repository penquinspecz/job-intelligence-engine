from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response

from ji_engine.config import RUN_METADATA_DIR

app = FastAPI()


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
    rel = None
    artifacts = index.get("artifacts") if isinstance(index.get("artifacts"), dict) else {}
    if name in artifacts:
        rel = artifacts[name]
    elif "/" in name:
        rel = name
    if not rel:
        raise HTTPException(status_code=404, detail="Artifact not found")
    candidate = (run_dir / rel).resolve()
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


@app.get("/healthz")
def healthz() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/runs")
def runs() -> List[Dict[str, Any]]:
    return _list_runs()


@app.get("/runs/{run_id}")
def run_detail(run_id: str) -> Dict[str, Any]:
    return _load_index(run_id)


@app.get("/runs/{run_id}/artifact/{name}")
def run_artifact(run_id: str, name: str) -> Response:
    index = _load_index(run_id)
    run_dir = _run_dir(run_id)
    path = _resolve_artifact_path(run_dir, index, name)
    return Response(path.read_bytes(), media_type=_content_type(path))
