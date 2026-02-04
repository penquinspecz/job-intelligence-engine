#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import boto3
from botocore.exceptions import ClientError

from ji_engine.config import DATA_DIR, RUN_METADATA_DIR
from jobintel.aws_runs import build_state_payload, write_last_success_state, write_provider_last_success_state

try:
    from scripts import aws_env_check  # type: ignore
except ModuleNotFoundError:
    import importlib.util

    _spec = importlib.util.spec_from_file_location("aws_env_check", Path(__file__).with_name("aws_env_check.py"))
    if not _spec or not _spec.loader:
        raise
    aws_env_check = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(aws_env_check)

logger = logging.getLogger(__name__)
DEFAULT_PREFIX = "jobintel"
LATEST_OUTPUT_ALLOWLIST = {
    "ranked_json",
    "ranked_csv",
    "ranked_families_json",
    "shortlist_md",
    "top_md",
}


class UploadItem:
    def __init__(
        self,
        *,
        source: Path,
        key: str,
        content_type: Optional[str],
        logical_key: str,
        scope: str,
    ) -> None:
        self.source = source
        self.key = key
        self.content_type = content_type
        self.logical_key = logical_key
        self.scope = scope


def _fail_validation(message: str) -> None:
    logger.error(message)
    raise SystemExit(2)


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


def _content_type_for(path: Path) -> Optional[str]:
    suffix = path.suffix.lower()
    if suffix == ".json":
        return "application/json"
    if suffix == ".csv":
        return "text/csv; charset=utf-8"
    if suffix in {".md", ".markdown"}:
        return "text/markdown; charset=utf-8"
    if suffix in {".html", ".htm"}:
        return "text/html; charset=utf-8"
    if suffix == ".txt":
        return "text/plain; charset=utf-8"
    return "application/octet-stream"


def _load_run_report(run_dir: Path) -> Dict[str, Any]:
    report_path = run_dir / "run_report.json"
    if not report_path.exists():
        _fail_validation(f"run_report.json not found: {report_path}")
    data = json.loads(report_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        _fail_validation("run_report.json has invalid shape")
    return data


def _parse_logical_key(logical_key: str) -> Optional[Tuple[str, str, str]]:
    parts = logical_key.split(":")
    if len(parts) < 3:
        return None
    provider, profile = parts[0], parts[1]
    output_key = ":".join(parts[2:])
    return provider, profile, output_key


def _collect_verifiable(report: Dict[str, Any]) -> Dict[str, Dict[str, str]]:
    verifiable = report.get("verifiable_artifacts")
    if not isinstance(verifiable, dict) or not verifiable:
        _fail_validation("run_report.json missing verifiable_artifacts; refusing to publish")
    return verifiable


def _providers_profiles_from_report(
    report: Dict[str, Any],
    verifiable: Dict[str, Dict[str, str]],
) -> Tuple[List[str], List[str]]:
    providers = report.get("providers")
    profiles = report.get("profiles")
    if isinstance(providers, list) and isinstance(profiles, list):
        return providers, profiles
    provider_set = set()
    profile_set = set()
    for logical_key in verifiable.keys():
        parsed = _parse_logical_key(logical_key)
        if not parsed:
            continue
        provider, profile, _ = parsed
        provider_set.add(provider)
        profile_set.add(profile)
    return sorted(provider_set), sorted(profile_set)


def _build_upload_plan(
    *,
    run_id: str,
    run_dir: Path,
    prefix: str,
    verifiable: Dict[str, Dict[str, str]],
    providers: Iterable[str],
    profiles: Iterable[str],
    allow_missing: bool = False,
) -> Tuple[List[UploadItem], Dict[str, Dict[str, str]]]:
    runs_uploads: List[UploadItem] = []
    latest_uploads: List[UploadItem] = []
    latest_prefixes: Dict[str, Dict[str, str]] = {}
    provider_filter = {p.strip() for p in providers if p.strip()}
    profile_filter = {p.strip() for p in profiles if p.strip()}

    for logical_key, meta in verifiable.items():
        if not isinstance(meta, dict):
            _fail_validation(f"invalid verifiable_artifacts entry for {logical_key}")
        path_str = meta.get("path")
        if not path_str:
            _fail_validation(f"missing path for verifiable artifact {logical_key}")
        path = Path(path_str)
        if not path.is_absolute():
            path = DATA_DIR / path
        if not path.exists():
            msg = f"verifiable artifact missing on disk: {path}"
            if allow_missing:
                logger.warning("%s; including in upload plan", msg)
            else:
                _fail_validation(msg)
        rel_path = Path(path_str).as_posix()
        parsed = _parse_logical_key(logical_key)
        if parsed:
            provider, profile, _ = parsed
            run_key = f"{prefix}/runs/{run_id}/{provider}/{profile}/{path.name}".strip("/")
        else:
            run_key = f"{prefix}/runs/{run_id}/{rel_path}".strip("/")
        runs_uploads.append(
            UploadItem(
                source=path,
                key=run_key,
                content_type=_content_type_for(path),
                logical_key=logical_key,
                scope="runs",
            )
        )
        if not parsed:
            continue
        provider, profile, output_key = parsed
        if provider_filter and provider not in provider_filter:
            continue
        if profile_filter and profile not in profile_filter:
            continue
        if output_key not in LATEST_OUTPUT_ALLOWLIST:
            continue
        latest_key = f"{prefix}/latest/{provider}/{profile}/{path.name}".strip("/")
        latest_uploads.append(
            UploadItem(
                source=path,
                key=latest_key,
                content_type=_content_type_for(path),
                logical_key=logical_key,
                scope="latest",
            )
        )
        latest_prefixes.setdefault(provider, {})[profile] = f"{prefix}/latest/{provider}/{profile}".strip("/")

    runs_uploads.sort(key=lambda item: item.key)
    latest_uploads.sort(key=lambda item: item.key)
    uploads = runs_uploads + latest_uploads
    return uploads, latest_prefixes


def _build_plan_entries(
    *,
    run_dir: Path,
    uploads: List[UploadItem],
    verifiable: Dict[str, Dict[str, str]],
) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    for item in uploads:
        meta = verifiable.get(item.logical_key, {}) if isinstance(verifiable, dict) else {}
        sha = meta.get("sha256")
        bytes_value = meta.get("bytes")
        if not isinstance(bytes_value, int):
            try:
                bytes_value = item.source.stat().st_size
            except OSError:
                bytes_value = None
        local_path = meta.get("path")
        if not local_path:
            local_path = item.source.name
        entries.append(
            {
                "logical_key": item.logical_key,
                "local_path": local_path,
                "sha256": sha,
                "bytes": bytes_value,
                "content_type": item.content_type,
                "s3_key": item.key,
                "kind": item.scope,
            }
        )
    return entries


def _upload_plan(client, bucket: str, plan: List[UploadItem], dry_run: bool) -> int:
    uploaded = 0
    for item in plan:
        if dry_run:
            logger.info("dry-run: %s -> s3://%s/%s", item.source, bucket, item.key)
            continue
        try:
            extra_args: Dict[str, str] = {}
            if item.content_type:
                extra_args["ContentType"] = item.content_type
            if extra_args:
                client.upload_file(str(item.source), bucket, item.key, ExtraArgs=extra_args)
            else:
                client.upload_file(str(item.source), bucket, item.key)
            logger.info("uploaded %s -> s3://%s/%s", item.source, bucket, item.key)
            uploaded += 1
        except ClientError as exc:
            logger.error("upload failed: %s", exc)
            raise
    return uploaded


def _resolve_bucket_prefix(bucket: Optional[str], prefix: Optional[str]) -> Tuple[str, str]:
    env_bucket = os.getenv("JOBINTEL_S3_BUCKET", "").strip()
    env_bucket_alias = os.getenv("BUCKET", "").strip()
    resolved_bucket = (bucket or env_bucket or env_bucket_alias).strip()

    env_prefix = os.getenv("JOBINTEL_S3_PREFIX", "").strip()
    env_prefix_alias = os.getenv("PREFIX", "").strip()
    resolved_prefix = (prefix or env_prefix or env_prefix_alias or DEFAULT_PREFIX).strip("/")
    return resolved_bucket, resolved_prefix


def _run_preflight(
    *,
    bucket: Optional[str],
    region: Optional[str],
    prefix: Optional[str],
    dry_run: bool,
) -> Dict[str, Any]:
    resolved_bucket = aws_env_check._resolve_bucket(bucket)
    resolved_region = aws_env_check._resolve_region(region)
    resolved_prefix, prefix_warnings = aws_env_check._resolve_prefix(prefix)
    report = aws_env_check._build_report(resolved_bucket, resolved_region, resolved_prefix)
    report["warnings"].extend(prefix_warnings)
    if dry_run and report.get("errors"):
        errors = []
        for err in report["errors"]:
            if err.startswith("credentials not detected"):
                report["warnings"].append(err)
            else:
                errors.append(err)
        report["errors"] = errors
        report["ok"] = len(errors) == 0
    return report


def publish_run(
    *,
    run_id: str,
    bucket: Optional[str],
    prefix: Optional[str],
    run_dir: Optional[Path] = None,
    dry_run: bool,
    require_s3: bool,
    providers: Optional[List[str]] = None,
    profiles: Optional[List[str]] = None,
    write_last_success: bool = True,
) -> Dict[str, Any]:
    resolved_bucket, resolved_prefix = _resolve_bucket_prefix(bucket, prefix)
    pointer_write: Dict[str, Any] = {"global": "skipped", "provider_profile": {}, "error": None}
    if not resolved_bucket and not dry_run:
        logger.info("S3 bucket unset; skipping publish.")
        if require_s3:
            _fail_validation("PUBLISH_S3=1 requires JOBINTEL_S3_BUCKET.")
        return {
            "status": "skipped",
            "reason": "missing_bucket",
            "uploaded_files_count": 0,
            "pointer_write": pointer_write,
        }

    run_dir = run_dir or _run_dir(run_id)
    report = _load_run_report(run_dir)
    report_run_id = report.get("run_id")
    if report_run_id and report_run_id != run_id:
        _fail_validation(f"run_report.json run_id mismatch: report={report_run_id} arg={run_id}")
    verifiable = _collect_verifiable(report)
    logger.info("S3 publish target: s3://%s/%s", resolved_bucket or "dry-run", resolved_prefix)
    plan, latest_prefixes = _build_upload_plan(
        run_id=run_id,
        run_dir=run_dir,
        prefix=resolved_prefix,
        verifiable=verifiable,
        providers=providers or [],
        profiles=profiles or [],
        allow_missing=dry_run,
    )
    if not plan:
        logger.error("no verifiable artifacts found for run %s", run_id)
        if require_s3 and not dry_run:
            raise SystemExit(2)
        return {"status": "error", "uploaded_files_count": 0}
    if dry_run:
        uploaded = _upload_plan(None, resolved_bucket or "dry-run", plan, dry_run=True)
    else:
        client = boto3.client("s3")
        uploaded = _upload_plan(client, resolved_bucket, plan, dry_run=False)
    if uploaded == 0 and not dry_run:
        logger.error("no artifacts uploaded for run %s", run_id)
        if require_s3:
            raise SystemExit(2)
        return {"status": "error", "uploaded_files_count": 0}

    provider_profiles: Dict[str, str] = {}
    for provider, profiles_payload in latest_prefixes.items():
        for profile in profiles_payload.keys():
            provider_profiles[f"{provider}:{profile}"] = run_id

    dashboard_url = os.environ.get("JOBINTEL_DASHBOARD_URL", "").strip().rstrip("/")
    if dashboard_url:
        dashboard_url = f"{dashboard_url}/runs/{run_id}"

    providers_list, profiles_list = _providers_profiles_from_report(report, verifiable)
    ended_at = None
    timestamps = report.get("timestamps") if isinstance(report.get("timestamps"), dict) else {}
    if isinstance(timestamps, dict):
        ended_at = timestamps.get("ended_at")
    if not ended_at:
        ended_at = report.get("ended_at") or report.get("finished_at")
    run_path = f"{resolved_prefix.strip('/')}/runs/{run_id}".strip("/")
    state_payload = build_state_payload(
        run_id,
        run_path,
        ended_at,
        providers_list,
        profiles_list,
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
    ap.add_argument("--region")
    ap.add_argument("--run-id", "--run_id", dest="run_id")
    ap.add_argument("--run-dir", "--run_dir", dest="run_dir")
    ap.add_argument("--latest", action="store_true")
    ap.add_argument("--dry-run", "--dry_run", dest="dry_run", action="store_true")
    ap.add_argument("--require-s3", "--require_s3", dest="require_s3", action="store_true")
    ap.add_argument("--plan", action="store_true", help="Emit a deterministic upload plan (no AWS calls).")
    ap.add_argument("--json", action="store_true", help="Emit machine-readable JSON output.")
    ap.add_argument(
        "--providers",
        default="",
        help="Comma-separated provider ids to publish latest pointers for (default: all).",
    )
    ap.add_argument(
        "--profiles",
        default="",
        help="Comma-separated profiles to publish latest pointers for (default: all).",
    )
    args = ap.parse_args()

    preflight = _run_preflight(
        bucket=args.bucket,
        region=args.region,
        prefix=args.prefix,
        dry_run=args.dry_run,
    )
    allow_preflight_fail = args.plan or args.dry_run
    if not preflight.get("ok"):
        if allow_preflight_fail:
            logger.warning("AWS preflight failed (plan/dry-run): %s", ", ".join(preflight.get("errors", [])))
        else:
            if args.json:
                print(
                    json.dumps(
                        {
                            "ok": False,
                            "preflight": preflight,
                            "plan": [],
                            "warnings": preflight.get("warnings", []),
                            "errors": preflight.get("errors", []),
                        },
                        sort_keys=True,
                    )
                )
            _fail_validation(f"AWS preflight failed: {', '.join(preflight.get('errors', []))}")

    if args.latest and args.run_dir:
        raise SystemExit("cannot specify --latest and --run-dir together")
    if args.latest:
        run_id = _select_run_id(None, True)
    elif args.run_id:
        run_id = args.run_id
    elif args.run_dir:
        report = _load_run_report(Path(args.run_dir))
        report_run_id = report.get("run_id")
        if not report_run_id:
            _fail_validation("run_report.json missing run_id; provide --run-id")
        run_id = report_run_id
    else:
        _fail_validation("must provide --run-id or --run-dir (or --latest)")
    providers = [p.strip() for p in args.providers.split(",") if p.strip()]
    profiles = [p.strip() for p in args.profiles.split(",") if p.strip()]
    run_dir = Path(args.run_dir) if args.run_dir else None
    if args.plan:
        plan_run_dir = run_dir or _run_dir(run_id)
        report = _load_run_report(plan_run_dir)
        verifiable = _collect_verifiable(report)
        plan, _latest = _build_upload_plan(
            run_id=run_id,
            run_dir=plan_run_dir,
            prefix=_resolve_bucket_prefix(args.bucket, args.prefix)[1],
            verifiable=verifiable,
            providers=providers,
            profiles=profiles,
            allow_missing=True,
        )
        plan_entries = _build_plan_entries(run_dir=plan_run_dir, uploads=plan, verifiable=verifiable)
        if args.json:
            print(
                json.dumps(
                    {
                        "ok": True,
                        "preflight": preflight,
                        "plan": plan_entries,
                        "warnings": preflight.get("warnings", []),
                        "errors": preflight.get("errors", []),
                    },
                    sort_keys=True,
                )
            )
        else:
            bucket = _resolve_bucket_prefix(args.bucket, args.prefix)[0]
            for entry in plan_entries:
                print(f"{entry['local_path']} -> s3://{bucket}/{entry['s3_key']}")
        return 0
    result = publish_run(
        run_id=run_id,
        bucket=args.bucket,
        prefix=args.prefix,
        run_dir=run_dir,
        dry_run=args.dry_run,
        require_s3=args.require_s3,
        providers=providers,
        profiles=profiles,
    )
    if args.json:
        print(json.dumps({"ok": True, "preflight": preflight, "result": result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    raise SystemExit(main())
