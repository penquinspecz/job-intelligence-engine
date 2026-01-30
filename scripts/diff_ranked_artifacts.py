#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

VOLATILE_FIELDS = {
    "fetched_at",
    "scraped_at",
    "enriched_at",
    "scored_at",
    "run_started_at",
    "run_id",
    "timestamp",
    "created_at",
    "updated_at",
}

CANONICAL_JSON_KWARGS = {"ensure_ascii": False, "sort_keys": True, "separators": (",", ":")}


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _job_key(job: Dict[str, Any]) -> str:
    for key in ("job_id", "id", "apply_url", "detail_url", "url"):
        val = job.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip().lower()
    return json.dumps(job, **CANONICAL_JSON_KWARGS)


def _extract_jobs(payload: Any) -> Optional[List[Dict[str, Any]]]:
    if isinstance(payload, list) and all(isinstance(item, dict) for item in payload):
        return list(payload)
    if isinstance(payload, dict):
        for key in ("jobs", "ranked_jobs", "items", "results"):
            val = payload.get(key)
            if isinstance(val, list) and all(isinstance(item, dict) for item in val):
                return list(val)
    return None


def _first_last_ids(jobs: Sequence[Dict[str, Any]], count: int = 5) -> Tuple[List[str], List[str]]:
    ids = [_job_key(job) for job in jobs]
    return ids[:count], ids[-count:] if len(ids) >= count else ids


def _find_volatile_fields(jobs: Iterable[Dict[str, Any]]) -> Dict[str, List[Any]]:
    found: Dict[str, List[Any]] = {}
    for job in jobs:
        for key in VOLATILE_FIELDS:
            if key in job:
                found.setdefault(key, [])
                if len(found[key]) < 3:
                    found[key].append(job.get(key))
    return found


def _canonical_hash(payload: Any) -> Optional[str]:
    jobs = _extract_jobs(payload)
    if jobs is None:
        return None
    ordered = sorted(jobs, key=_job_key)
    data = json.dumps(ordered, **CANONICAL_JSON_KWARGS).encode("utf-8") + b"\n"
    return _sha256_bytes(data)


def _describe(path: Path) -> Dict[str, Any]:
    raw = path.read_bytes()
    payload = _load_json(path)
    jobs = _extract_jobs(payload)

    out: Dict[str, Any] = {
        "path": str(path),
        "raw_sha256": _sha256_bytes(raw),
        "jobs_count": len(jobs) if jobs is not None else None,
        "first_ids": None,
        "last_ids": None,
        "volatile_fields": None,
        "normalized_sha256": _canonical_hash(payload),
    }
    if jobs is not None:
        first_ids, last_ids = _first_last_ids(jobs)
        out["first_ids"] = first_ids
        out["last_ids"] = last_ids
        out["volatile_fields"] = _find_volatile_fields(jobs)
    return out


def _print_block(label: str, info: Dict[str, Any]) -> None:
    print(f"== {label} ==")
    print(f"path: {info['path']}")
    print(f"raw_sha256: {info['raw_sha256']}")
    print(f"jobs_count: {info['jobs_count']}")
    print(f"first_ids: {info['first_ids']}")
    print(f"last_ids: {info['last_ids']}")
    print(f"volatile_fields: {info['volatile_fields']}")
    print(f"normalized_sha256: {info['normalized_sha256']}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Compare ranked JSON artifacts deterministically.")
    ap.add_argument("left", type=Path, help="Left JSON file path")
    ap.add_argument("right", type=Path, help="Right JSON file path")
    args = ap.parse_args()

    left = _describe(args.left)
    right = _describe(args.right)

    _print_block("left", left)
    _print_block("right", right)

    if left["normalized_sha256"] and right["normalized_sha256"]:
        same_norm = left["normalized_sha256"] == right["normalized_sha256"]
        print(f"normalized_equal: {same_norm}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
