#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import boto3
from botocore.exceptions import ClientError

from ji_engine.config import RUN_METADATA_DIR
from jobintel.aws_runs import build_state_payload, write_last_success_state, write_provider_last_success_state

logger = logging.getLogger(__name__)
DEFAULT_PREFIX = "jobintel"


def _sanitize_run_id(run_id: str) -> str:
    return run_id.replace(":", "").replace("-", "").replace(".", "")


def _run_dir(run_id: str) -> Path:
    return RUN_METADATA_DIR / _sanitize_run_id(run_id)


def _last_run_id() -> Optional[str]:
    last_run = RUN_METADATA_DIR.parent / "last_run.json"
    if not last_run.exists():
        return None
    try:
        payload = json.loads(last_run.read_text(encoding="utf-8"))
    except Exception:
        return None
    if isinstance(payload, dict):
        return payload.get("run_id")
    return None


def _select_run_id(run_id: Optional[str], latest: bool) -> str:
    if latest and run_id:
        raise SystemExit("cannot specify --run_id and --latest together")
    if run_id:
        return run_id
    last = _last_run_id()
    if last:
        return last
    raise SystemExit("no runs recorded yet")


def _collect_artifacts(base_dir: Path) -> List[Path]:
    if not base_dir.exists():
        return []
    files = sorted(p for p in base_dir.rglob("*") if p.is_file())
    return files


def _upload_files(
    client,
    bucket: str,
    prefix: str,
    base_dir: Path,
    files: List[Path],
    dry_run: bool,
) -> int:
    prefix = prefix.strip("/")
    uploaded = 0
    for path in files:
        rel = path.relative_to(base_dir)
        key = f"{prefix}/{rel.as_posix()}" if prefix else rel.as_posix()
        if dry_run:
            logger.info("dry-run: %s -> s3://%s/%s", path, bucket, key)
            continue
        try:
            client.upload_file(str(path), bucket, key)
            logger.info("uploaded %s -> s3://%s/%s", path, bucket, key)
            uploaded += 1
        except ClientError as exc:
            logger.error("upload failed: %s", exc)
            raise
    return uploaded


def _load_index(run_id: str) -> Dict[str, Any]:
    index_path = _run_dir(run_id) / "index.json"
    if not index_path.exists():
        raise SystemExit(f"run index not found: {index_path}")
    data = json.loads(index_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit("run index has invalid shape")
    return data


def _resolve_bucket_prefix(bucket: Optional[str], prefix: Optional[str]) -> Tuple[str, str]:
    resolved_bucket = bucket or os.getenv("JOBINTEL_S3_BUCKET", "").strip()
    resolved_prefix = prefix or os.getenv("JOBINTEL_S3_PREFIX", DEFAULT_PREFIX).strip("/")
    return resolved_bucket, resolved_prefix


def publish_run(
    *,
    run_id: str,
    bucket: Optional[str],
    prefix: Optional[str],
    dry_run: bool,
    require_s3: bool,
    write_last_success: bool = True,
) -> Dict[str, Any]:
    resolved_bucket, resolved_prefix = _resolve_bucket_prefix(bucket, prefix)
    pointer_write: Dict[str, Any] = {"global": "skipped", "provider_profile": {}, "error": None}
    if not resolved_bucket:
        logger.info("S3 bucket unset; skipping publish.")
        if require_s3:
            raise SystemExit(2)
        return {
            "status": "skipped",
            "reason": "missing_bucket",
            "uploaded_files_count": 0,
            "pointer_write": pointer_write,
        }

    run_dir = _run_dir(run_id)
    index = _load_index(run_id)
    client = boto3.client("s3")
    logger.info("S3 publish target: s3://%s/%s", resolved_bucket, resolved_prefix)

    files = _collect_artifacts(run_dir)
    if not files:
        logger.error("no artifacts found for run %s", run_id)
        return {"status": "error", "uploaded_files_count": 0}

    runs_prefix = f"{resolved_prefix}/runs/{run_id}".strip("/")
    uploaded = _upload_files(client, resolved_bucket, runs_prefix, run_dir, files, dry_run)

    latest_prefixes: Dict[str, Dict[str, str]] = {}
    providers = index.get("providers") if isinstance(index.get("providers"), dict) else {}
    provider_profiles: Dict[str, str] = {}
    for provider, provider_payload in providers.items():
        profiles = provider_payload.get("profiles") if isinstance(provider_payload, dict) else {}
        for profile in profiles:
            profile_dir = run_dir / provider / profile
            profile_files = _collect_artifacts(profile_dir)
            if not profile_files:
                continue
            latest_prefix = f"{resolved_prefix}/latest/{provider}/{profile}".strip("/")
            _upload_files(client, resolved_bucket, latest_prefix, profile_dir, profile_files, dry_run)
            latest_prefixes.setdefault(provider, {})[profile] = latest_prefix
            provider_profiles[f"{provider}:{profile}"] = run_id

    dashboard_url = os.environ.get("JOBINTEL_DASHBOARD_URL", "").strip().rstrip("/")
    if dashboard_url:
        dashboard_url = f"{dashboard_url}/runs/{run_id}"

    run_path = f"{resolved_prefix.strip('/')}/runs/{run_id}".strip("/")
    state_payload = build_state_payload(
        run_id,
        run_path,
        index.get("timestamp"),
        list(providers.keys()),
        list({p for profiles in providers.values() for p in (profiles.get("profiles") or {}).keys()}),
        schema_version=1,
    )
    state_payload["provider_profiles"] = provider_profiles
    if dry_run:
        pointer_write["global"] = "skipped"
    elif not write_last_success:
        logger.info("Skipping baseline pointer write (run not successful).")
        pointer_write["global"] = "skipped"
    else:
        try:
            logger.info(
                "writing baseline pointer: s3://%s/%s/state/last_success.json",
                resolved_bucket,
                resolved_prefix,
            )
            write_last_success_state(resolved_bucket, resolved_prefix, state_payload, client=client)
            logger.info(
                "baseline pointer write ok: s3://%s/%s/state/last_success.json",
                resolved_bucket,
                resolved_prefix,
            )
            pointer_write["global"] = "ok"
        except ClientError as exc:
            logger.error("baseline pointer write failed: %s", exc)
            pointer_write["global"] = "error"
            pointer_write["error"] = str(exc)
        if pointer_write["global"] == "ok":
            for provider, profiles in latest_prefixes.items():
                for profile in profiles.keys():
                    key = f"{provider}:{profile}"
                    try:
                        logger.info(
                            "writing baseline pointer: s3://%s/%s/state/%s/%s/last_success.json",
                            resolved_bucket,
                            resolved_prefix,
                            provider,
                            profile,
                        )
                        write_provider_last_success_state(
                            resolved_bucket,
                            resolved_prefix,
                            provider,
                            profile,
                            state_payload,
                            client=client,
                        )
                        logger.info(
                            "baseline pointer write ok: s3://%s/%s/state/%s/%s/last_success.json",
                            resolved_bucket,
                            resolved_prefix,
                            provider,
                            profile,
                        )
                        pointer_write["provider_profile"][key] = "ok"
                    except ClientError as exc:
                        logger.error("baseline pointer write failed: %s", exc)
                        pointer_write["provider_profile"][key] = "error"
                        pointer_write["error"] = str(exc)
        else:
            for provider, profiles in latest_prefixes.items():
                for profile in profiles.keys():
                    pointer_write["provider_profile"][f"{provider}:{profile}"] = "skipped"

    status = "ok"
    if pointer_write["global"] == "error" or "error" in pointer_write["provider_profile"].values():
        status = "error"

    return {
        "status": status,
        "reason": "pointer_write_failed" if status == "error" else None,
        "bucket": resolved_bucket,
        "prefixes": build_s3_prefixes(resolved_prefix, run_id, latest_prefixes),
        "uploaded_files_count": uploaded,
        "dashboard_url": dashboard_url or None,
        "pointer_write": pointer_write,
    }


def build_s3_prefixes(prefix: str, run_id: str, latest: Dict[str, Dict[str, str]]) -> Dict[str, Any]:
    clean_prefix = prefix.strip("/")
    runs_prefix = f"{clean_prefix}/runs/{run_id}".strip("/")
    return {
        "runs": runs_prefix,
        "latest": latest,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bucket")
    ap.add_argument("--prefix")
    ap.add_argument("--run_id")
    ap.add_argument("--latest", action="store_true")
    ap.add_argument("--dry_run", action="store_true")
    ap.add_argument("--require_s3", action="store_true")
    args = ap.parse_args()

    run_id = _select_run_id(args.run_id, args.latest)
    publish_run(
        run_id=run_id,
        bucket=args.bucket,
        prefix=args.prefix,
        dry_run=args.dry_run,
        require_s3=args.require_s3,
    )
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    raise SystemExit(main())
