#!/usr/bin/env python3
from __future__ import annotations

try:
    import _bootstrap  # type: ignore
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

import argparse
import hashlib
import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ji_engine.config import DATA_DIR, RAW_JOBS_JSON
from ji_engine.providers.ashby_provider import AshbyProvider
from ji_engine.providers.openai_provider import CAREERS_SEARCH_URL, OpenAICareersProvider
from ji_engine.providers.registry import load_providers_config
from ji_engine.providers.retry import (
    ProviderFetchError,
    classify_failure_type,
    evaluate_robots_policy,
    get_politeness_policy,
    record_policy_block,
)
from ji_engine.providers.snapshot_json_provider import SnapshotJsonProvider
from jobintel.snapshots.validate import validate_snapshot_file

_STATUS_CODE_RE = re.compile(r"status (\d+)")

logger = logging.getLogger(__name__)


def _sort_key(job: Dict[str, Any]) -> tuple[str, str]:
    url = str(job.get("apply_url") or job.get("detail_url") or "").lower()
    title = str(job.get("title") or "").lower()
    return (url, title)


def _normalize_jobs(raw: List[Any]) -> List[Dict[str, Any]]:
    jobs: List[Dict[str, Any]] = []
    for item in raw:
        if hasattr(item, "to_dict"):
            jobs.append(item.to_dict())
        elif isinstance(item, dict):
            jobs.append(item)
    return sorted(jobs, key=_sort_key)


def _write_raw_jobs(provider_id: str, jobs: List[Dict[str, Any]], output_dir: Path) -> Path:
    filename = f"{provider_id}_raw_jobs.json"
    out_path = output_dir / filename
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(jobs, f, indent=2, ensure_ascii=False)
    print(f"Scraped {len(jobs)} jobs.")
    print(f"Wrote JSON to {out_path.resolve()}")
    return out_path


def _sha256(path: Path) -> Optional[str]:
    if not path.exists():
        return None
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except Exception:
        return None


def _scrape_meta_path(provider_id: str, output_dir: Path) -> Path:
    return output_dir / f"{provider_id}_scrape_meta.json"


def _snapshot_meta_path(snapshot_path: Path) -> Path:
    return snapshot_path.with_suffix(".meta.json")


def _load_snapshot_meta(snapshot_path: Path) -> Dict[str, Any]:
    meta_path = _snapshot_meta_path(snapshot_path)
    if not meta_path.exists():
        return {}
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _write_scrape_meta(provider_id: str, output_dir: Path, meta: Dict[str, Any]) -> None:
    path = _scrape_meta_path(provider_id, output_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(meta)
    payload["provider"] = provider_id
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")


def _parse_status_code(error: str) -> Optional[int]:
    match = _STATUS_CODE_RE.search(error or "")
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _mtime_iso(path: Path) -> Optional[str]:
    try:
        ts = path.stat().st_mtime
    except FileNotFoundError:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _log_provenance(provider_id: str, payload: Dict[str, Any]) -> None:
    logger.info("[run_scrape][provenance] %s", json.dumps({provider_id: payload}, sort_keys=True))


def main(argv: List[str] | None = None) -> int:
    if not logging.getLogger().hasHandlers():
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    ap = argparse.ArgumentParser()
    ap.add_argument("--providers", default="openai", help="Comma-separated provider ids.")
    ap.add_argument(
        "--mode",
        choices=["SNAPSHOT", "LIVE", "AUTO"],
        default=os.getenv("CAREERS_MODE"),
        help="Scrape mode override. Default from CAREERS_MODE env var when set.",
    )
    ap.add_argument(
        "--providers-config",
        default=str(Path("config") / "providers.json"),
        help="Path to providers config JSON.",
    )
    ap.add_argument(
        "--snapshot-write-dir",
        help="Explicit directory for live snapshot writes (required to persist HTML).",
    )
    ap.add_argument(
        "--snapshot-only",
        action="store_true",
        help="Fail if any provider would use live scraping; enforce snapshot-only determinism.",
    )
    args = ap.parse_args(argv or [])

    providers = load_providers_config(Path(args.providers_config))
    provider_map = {p["provider_id"]: p for p in providers}
    requested = [p.strip() for p in args.providers.split(",") if p.strip()]
    for provider_id in requested:
        if provider_id not in provider_map:
            raise SystemExit(f"Unknown provider_id '{provider_id}' in --providers")

    output_dir = Path(os.environ.get("JOBINTEL_OUTPUT_DIR") or (Path(DATA_DIR) / "ashby_cache"))
    output_dir.mkdir(parents=True, exist_ok=True)
    snapshot_write_dir = Path(args.snapshot_write_dir).expanduser() if args.snapshot_write_dir else None
    for provider_id in requested:
        os.environ["JOBINTEL_PROVENANCE_LOG"] = "1"
        provider_cfg = provider_map[provider_id]
        provider_type = provider_cfg.get("type", "snapshot")
        mode = (args.mode or provider_cfg.get("mode") or "snapshot").upper()
        if args.snapshot_only and mode != "SNAPSHOT":
            logger.error(
                "[run_scrape] snapshot-only enforced; provider %s requested %s",
                provider_id,
                mode,
            )
            raise SystemExit(2)
        provenance: Dict[str, Any] = {
            "provider_id": provider_id,
            "mode": mode,
            "live_attempted": False,
            "live_result": None,
            "live_http_status": None,
            "live_error_type": None,
            "snapshot_used": False,
            "snapshot_path": None,
            "snapshot_mtime_iso": None,
            "snapshot_sha256": None,
            "snapshot_validated": None,
            "snapshot_reason": None,
            "scrape_mode": None,
            "live_status_code": None,
            "error": None,
            "availability": "available",
            "unavailable_reason": None,
            "attempts_made": 0,
            "parsed_job_count": 0,
            "snapshot_baseline_count": None,
            "robots_url": None,
            "robots_fetched": None,
            "robots_status": None,
            "robots_allowed": None,
            "allowlist_allowed": None,
            "robots_final_allowed": None,
            "robots_reason": None,
            "robots_user_agent": None,
            "rate_limit_min_delay_s": None,
            "rate_limit_jitter_s": None,
            "max_attempts": None,
            "backoff_base_s": None,
            "backoff_max_s": None,
            "backoff_jitter_s": None,
            "circuit_breaker_threshold": None,
            "circuit_breaker_cooldown_s": None,
        }
        policy = get_politeness_policy(provider_id)
        provenance["rate_limit_min_delay_s"] = policy.get("min_delay_s")
        provenance["rate_limit_jitter_s"] = policy.get("rate_jitter_s")
        provenance["max_attempts"] = policy.get("max_attempts")
        provenance["backoff_base_s"] = policy.get("backoff_base_s")
        provenance["backoff_max_s"] = policy.get("backoff_max_s")
        provenance["backoff_jitter_s"] = policy.get("backoff_jitter_s")
        provenance["circuit_breaker_threshold"] = policy.get("max_consecutive_failures")
        provenance["circuit_breaker_cooldown_s"] = policy.get("cooldown_s")

        if provider_type == "openai":
            if mode == "AUTO":
                mode = "LIVE"
            provider = OpenAICareersProvider(
                mode=mode,
                data_dir=str(output_dir),
                snapshot_write_dir=snapshot_write_dir,
            )
            snapshot_path = provider._snapshot_file()
            snapshot_meta = _load_snapshot_meta(snapshot_path)
            if mode == "LIVE":
                robots = evaluate_robots_policy(CAREERS_SEARCH_URL, provider_id=provider_id)
                provenance["robots_url"] = robots.get("robots_url")
                provenance["robots_fetched"] = robots.get("robots_fetched")
                provenance["robots_status"] = robots.get("robots_status")
                provenance["robots_allowed"] = robots.get("robots_allowed")
                provenance["allowlist_allowed"] = robots.get("allowlist_allowed")
                provenance["robots_final_allowed"] = robots.get("final_allowed")
                provenance["robots_reason"] = robots.get("reason")
                provenance["robots_user_agent"] = robots.get("user_agent")
                if not robots.get("final_allowed"):
                    reason = robots.get("reason") or "policy_denied"
                    provenance["live_attempted"] = True
                    provenance["live_result"] = "skipped"
                    provenance["live_error_reason"] = reason
                    provenance["live_unavailable_reason"] = reason
                    provenance["live_error_type"] = classify_failure_type(str(reason))
                    provenance["availability"] = "unavailable"
                    provenance["unavailable_reason"] = reason
                    record_policy_block(provider_id, str(reason))
                    logger.warning(
                        "[run_scrape] LIVE blocked by robots/policy (%s) → falling back to SNAPSHOT",
                        reason,
                    )
                    provider = OpenAICareersProvider(mode="SNAPSHOT", data_dir=str(output_dir))
                    raw_jobs = provider.load_from_snapshot()
                    provenance["scrape_mode"] = "snapshot"
                    provenance["snapshot_used"] = True
                else:
                    raw_jobs = None
                try:
                    if raw_jobs is None:
                        raw_jobs = provider.scrape_live()
                    provenance["scrape_mode"] = "live"
                    provenance["attempts_made"] = 1
                    provenance["live_attempted"] = True
                    provenance["live_result"] = "success"
                    provenance["live_error_type"] = "success"
                except ProviderFetchError as e:
                    err = str(e)
                    provenance["live_status_code"] = e.status_code
                    provenance["live_http_status"] = e.status_code
                    provenance["error"] = err
                    provenance["attempts_made"] = e.attempts
                    provenance["live_error_reason"] = e.reason
                    provenance["live_unavailable_reason"] = e.reason
                    provenance["live_error_type"] = classify_failure_type(e.reason)
                    if e.reason in {"auth_error", "blocked", "circuit_breaker"}:
                        provenance["availability"] = "unavailable"
                        provenance["unavailable_reason"] = e.reason
                        provenance["live_result"] = "skipped" if e.reason == "circuit_breaker" else "blocked"
                    else:
                        provenance["live_result"] = "failed"
                    provenance["live_attempted"] = e.reason != "circuit_breaker"
                    logger.warning(f"[run_scrape] LIVE failed ({e!r}) → falling back to SNAPSHOT")
                    provider = OpenAICareersProvider(mode="SNAPSHOT", data_dir=str(output_dir))
                    raw_jobs = provider.load_from_snapshot()
                    provenance["scrape_mode"] = "snapshot"
                    provenance["snapshot_used"] = True
                except Exception as e:
                    err = str(e)
                    provenance["live_status_code"] = _parse_status_code(err)
                    provenance["live_http_status"] = _parse_status_code(err)
                    provenance["error"] = err
                    provenance["attempts_made"] = 1
                    provenance["live_error_reason"] = "network_error"
                    provenance["live_unavailable_reason"] = "network_error"
                    provenance["live_error_type"] = "transient_error"
                    provenance["live_attempted"] = True
                    provenance["live_result"] = "failed"
                    logger.warning(f"[run_scrape] LIVE failed ({e!r}) → falling back to SNAPSHOT")
                    provider = OpenAICareersProvider(mode="SNAPSHOT", data_dir=str(output_dir))
                    raw_jobs = provider.load_from_snapshot()
                    provenance["scrape_mode"] = "snapshot"
                    provenance["snapshot_used"] = True
            else:
                raw_jobs = provider.fetch_jobs()
                provenance["scrape_mode"] = "snapshot"
                provenance["live_result"] = "skipped"
            provenance["snapshot_path"] = str(snapshot_path)
            provenance["snapshot_mtime_iso"] = _mtime_iso(snapshot_path)
            provenance["snapshot_sha256"] = snapshot_meta.get("sha256") or _sha256(snapshot_path)
            if snapshot_path.exists():
                ok, reason = validate_snapshot_file(provider_id, snapshot_path)
                provenance["snapshot_validated"] = ok
                if not ok:
                    provenance["snapshot_reason"] = reason
            if snapshot_meta.get("fetched_at"):
                provenance["fetched_at"] = snapshot_meta.get("fetched_at")
            jobs = _normalize_jobs(raw_jobs)
            _write_raw_jobs(provider_id, jobs, output_dir)
            provenance["parsed_job_count"] = len(jobs)
            if mode == "LIVE" and snapshot_path.exists():
                try:
                    baseline_jobs = provider.load_from_snapshot()
                    provenance["snapshot_baseline_count"] = len(_normalize_jobs(baseline_jobs))
                except Exception:
                    provenance["snapshot_baseline_count"] = None
            if provenance.get("scrape_mode") == "snapshot" and provenance.get("attempts_made", 0) == 0:
                provenance["attempts_made"] = 1
                provenance["snapshot_used"] = True
            if len(jobs) == 0 and not snapshot_path.exists():
                provenance["availability"] = "unavailable"
                provenance["unavailable_reason"] = provenance.get("live_unavailable_reason") or "parse_error"
            if provenance.get("live_result") is None:
                provenance["live_result"] = "skipped"
            _write_scrape_meta(provider_id, output_dir, provenance)
            _log_provenance(provider_id, provenance)
            # For backward compatibility, also write to canonical RAW_JOBS_JSON when writable.
            if provider_id == "openai" and RAW_JOBS_JSON.parent.exists() and os.access(RAW_JOBS_JSON.parent, os.W_OK):
                RAW_JOBS_JSON.write_text(json.dumps(jobs, indent=2, ensure_ascii=False), encoding="utf-8")
        else:
            if provider_type == "ashby":
                if mode == "AUTO":
                    mode = "LIVE" if provider_cfg.get("live_enabled", True) else "SNAPSHOT"
                snapshot_dir = Path(provider_cfg["snapshot_dir"])
                snapshot_path = Path(provider_cfg["snapshot_path"])
                if mode == "SNAPSHOT" and not snapshot_path.exists():
                    msg = (
                        f"Snapshot not found at {snapshot_path} for provider {provider_id}. "
                        "Add a snapshot file or update providers config."
                    )
                    logger.error(msg)
                    raise SystemExit(2)
                provider = AshbyProvider(
                    provider_id=provider_id,
                    board_url=provider_cfg["board_url"],
                    snapshot_dir=snapshot_dir,
                    mode=mode,
                    snapshot_write_dir=snapshot_write_dir,
                )
                if mode == "LIVE":
                    robots = evaluate_robots_policy(provider_cfg["board_url"], provider_id=provider_id)
                    provenance["robots_url"] = robots.get("robots_url")
                    provenance["robots_fetched"] = robots.get("robots_fetched")
                    provenance["robots_status"] = robots.get("robots_status")
                    provenance["robots_allowed"] = robots.get("robots_allowed")
                    provenance["allowlist_allowed"] = robots.get("allowlist_allowed")
                    provenance["robots_final_allowed"] = robots.get("final_allowed")
                    provenance["robots_reason"] = robots.get("reason")
                    provenance["robots_user_agent"] = robots.get("user_agent")
                    if not robots.get("final_allowed"):
                        reason = robots.get("reason") or "policy_denied"
                        provenance["live_attempted"] = True
                        provenance["live_result"] = "skipped"
                        provenance["live_error_reason"] = reason
                        provenance["live_unavailable_reason"] = reason
                        provenance["live_error_type"] = classify_failure_type(str(reason))
                        provenance["availability"] = "unavailable"
                        provenance["unavailable_reason"] = reason
                        record_policy_block(provider_id, str(reason))
                        logger.warning(
                            "[run_scrape] LIVE blocked by robots/policy (%s) → falling back to SNAPSHOT",
                            reason,
                        )
                        if not snapshot_path.exists():
                            msg = (
                                f"Snapshot not found at {snapshot_path} for provider {provider_id}. "
                                "Add a snapshot file or update providers config."
                            )
                            logger.error(msg)
                            raise SystemExit(2)
                        raw_jobs = provider.load_from_snapshot()
                        provenance["scrape_mode"] = "snapshot"
                        provenance["snapshot_used"] = True
                    else:
                        raw_jobs = None
                    try:
                        if raw_jobs is None:
                            raw_jobs = provider.scrape_live()
                        provenance["scrape_mode"] = "live"
                        provenance["attempts_made"] = 1
                        provenance["live_attempted"] = True
                        provenance["live_result"] = "success"
                        provenance["live_error_type"] = "success"
                    except ProviderFetchError as e:
                        err = str(e)
                        provenance["live_status_code"] = e.status_code
                        provenance["live_http_status"] = e.status_code
                        provenance["error"] = err
                        provenance["attempts_made"] = e.attempts
                        provenance["live_error_reason"] = e.reason
                        provenance["live_unavailable_reason"] = e.reason
                        provenance["live_error_type"] = classify_failure_type(e.reason)
                        if e.reason in {"auth_error", "blocked", "circuit_breaker"}:
                            provenance["availability"] = "unavailable"
                            provenance["unavailable_reason"] = e.reason
                            provenance["live_result"] = "skipped" if e.reason == "circuit_breaker" else "blocked"
                        else:
                            provenance["live_result"] = "failed"
                        provenance["live_attempted"] = e.reason != "circuit_breaker"
                        logger.warning(f"[run_scrape] LIVE failed ({e!r}) → falling back to SNAPSHOT")
                        if not snapshot_path.exists():
                            msg = (
                                f"Snapshot not found at {snapshot_path} for provider {provider_id}. "
                                "Add a snapshot file or update providers config."
                            )
                            logger.error(msg)
                            raise SystemExit(2)
                        raw_jobs = provider.load_from_snapshot()
                        provenance["scrape_mode"] = "snapshot"
                        provenance["snapshot_used"] = True
                    except Exception as e:
                        err = str(e)
                        provenance["live_status_code"] = _parse_status_code(err)
                        provenance["live_http_status"] = _parse_status_code(err)
                        provenance["error"] = err
                        provenance["attempts_made"] = 1
                        provenance["live_error_reason"] = "network_error"
                        provenance["live_unavailable_reason"] = "network_error"
                        provenance["live_error_type"] = "transient_error"
                        provenance["live_attempted"] = True
                        provenance["live_result"] = "failed"
                        logger.warning(f"[run_scrape] LIVE failed ({e!r}) → falling back to SNAPSHOT")
                        if not snapshot_path.exists():
                            msg = (
                                f"Snapshot not found at {snapshot_path} for provider {provider_id}. "
                                "Add a snapshot file or update providers config."
                            )
                            logger.error(msg)
                            raise SystemExit(2)
                        raw_jobs = provider.load_from_snapshot()
                        provenance["scrape_mode"] = "snapshot"
                        provenance["snapshot_used"] = True
                else:
                    raw_jobs = provider.load_from_snapshot()
                    provenance["scrape_mode"] = "snapshot"
                    provenance["live_result"] = "skipped"
                jobs = _normalize_jobs(raw_jobs)
                _write_raw_jobs(provider_id, jobs, output_dir)
                snapshot_meta = _load_snapshot_meta(snapshot_path)
                provenance.update(
                    {
                        "snapshot_path": str(snapshot_path),
                        "snapshot_mtime_iso": _mtime_iso(snapshot_path),
                        "snapshot_sha256": snapshot_meta.get("sha256") or _sha256(snapshot_path),
                        "parsed_job_count": len(jobs),
                    }
                )
                if mode == "LIVE" and snapshot_path.exists():
                    try:
                        baseline_jobs = provider.load_from_snapshot()
                        provenance["snapshot_baseline_count"] = len(_normalize_jobs(baseline_jobs))
                    except Exception:
                        provenance["snapshot_baseline_count"] = None
                if snapshot_path.exists():
                    ok, reason = validate_snapshot_file(provider_id, snapshot_path)
                    provenance["snapshot_validated"] = ok
                    if not ok:
                        provenance["snapshot_reason"] = reason
                if snapshot_meta.get("fetched_at"):
                    provenance["fetched_at"] = snapshot_meta.get("fetched_at")
                if provenance.get("scrape_mode") == "snapshot" and provenance.get("attempts_made", 0) == 0:
                    provenance["attempts_made"] = 1
                    provenance["snapshot_used"] = True
                _write_scrape_meta(provider_id, output_dir, provenance)
                _log_provenance(provider_id, provenance)
                if (
                    provider_id == "openai"
                    and RAW_JOBS_JSON.parent.exists()
                    and os.access(RAW_JOBS_JSON.parent, os.W_OK)
                ):
                    RAW_JOBS_JSON.write_text(json.dumps(jobs, indent=2, ensure_ascii=False), encoding="utf-8")
            else:
                if mode == "AUTO":
                    mode = "SNAPSHOT"
                if mode != "SNAPSHOT":
                    raise SystemExit(f"Provider {provider_id} supports SNAPSHOT mode only")
                snapshot_path = Path(provider_cfg["snapshot_path"])
                if not snapshot_path.exists():
                    msg = (
                        f"Snapshot not found at {snapshot_path} for provider {provider_id}. "
                        "Add a snapshot file or update providers config."
                    )
                    logger.error(msg)
                    raise SystemExit(2)
                provider = SnapshotJsonProvider(snapshot_path)
                jobs = _normalize_jobs(provider.fetch_jobs())
                _write_raw_jobs(provider_id, jobs, output_dir)
                snapshot_meta = _load_snapshot_meta(snapshot_path)
                provenance.update(
                    {
                        "scrape_mode": "snapshot",
                        "snapshot_path": str(snapshot_path),
                        "snapshot_mtime_iso": _mtime_iso(snapshot_path),
                        "snapshot_sha256": snapshot_meta.get("sha256") or _sha256(snapshot_path),
                        "parsed_job_count": len(jobs),
                    }
                )
                provenance["snapshot_validated"] = True
                provenance["snapshot_reason"] = "not_applicable"
                if snapshot_meta.get("fetched_at"):
                    provenance["fetched_at"] = snapshot_meta.get("fetched_at")
                if provenance.get("attempts_made", 0) == 0:
                    provenance["attempts_made"] = 1
                    provenance["snapshot_used"] = True
                provenance["live_result"] = "skipped"
                _write_scrape_meta(provider_id, output_dir, provenance)
                _log_provenance(provider_id, provenance)

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
