#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Optional

from ji_engine.config import (
    DATA_DIR,
    DEFAULT_CANDIDATE_ID,
    candidate_last_run_read_paths,
    sanitize_candidate_id,
)
from jobintel.ai_job_briefs import PROMPT_PATH, generate_job_briefs
from jobintel.discord_notify import post_discord, resolve_webhook

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def _read_last_run(path: Path) -> Optional[str]:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload.get("run_id") if isinstance(payload, dict) else None


def _last_run_id(candidate_id: str) -> Optional[str]:
    safe_candidate = sanitize_candidate_id(candidate_id)
    for path in candidate_last_run_read_paths(safe_candidate):
        run_id = _read_last_run(path)
        if run_id:
            return run_id
    return None


def _default_ranked_path(provider: str, profile: str) -> Path:
    if provider == "openai":
        return DATA_DIR / f"openai_ranked_jobs.{profile}.json"
    return DATA_DIR / f"{provider}_ranked_jobs.{profile}.json"


def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", default="openai")
    ap.add_argument("--profile", default="cs")
    ap.add_argument("--ranked_path", help="Path to ranked_jobs.json")
    ap.add_argument("--run_id", help="Run ID to write into state/runs/<run_id>")
    ap.add_argument("--max_jobs", type=int, default=10)
    ap.add_argument("--max_tokens_per_job", type=int, default=400)
    ap.add_argument("--total_budget", type=int, default=2000)
    ap.add_argument("--prompt_path", help="Path to prompt template markdown")
    return ap.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = _parse_args(argv)
    try:
        candidate_id = sanitize_candidate_id(os.environ.get("JOBINTEL_CANDIDATE_ID", DEFAULT_CANDIDATE_ID))
    except ValueError as exc:
        raise SystemExit(f"invalid JOBINTEL_CANDIDATE_ID: {exc}")
    run_id = args.run_id or _last_run_id(candidate_id)
    if not run_id:
        raise SystemExit("run_id is required (no last_run.json found).")

    ranked_path = Path(args.ranked_path) if args.ranked_path else _default_ranked_path(args.provider, args.profile)
    prompt_path = Path(args.prompt_path) if args.prompt_path else PROMPT_PATH

    ai_enabled = (
        os.environ.get("AI_ENABLED", "0").strip() == "1" and os.environ.get("AI_JOB_BRIEFS_ENABLED", "0").strip() == "1"
    )
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    model_name = os.environ.get("AI_MODEL", "stub")
    if ai_enabled and not api_key:
        ai_enabled = False
        ai_reason = "ai_enabled_but_missing_openai_api_key"
    else:
        ai_reason = "ai_disabled" if not ai_enabled else ""

    md_path, json_path, payload = generate_job_briefs(
        provider=args.provider,
        profile=args.profile,
        ranked_path=ranked_path,
        run_id=run_id,
        max_jobs=args.max_jobs,
        max_tokens_per_job=args.max_tokens_per_job,
        total_budget=args.total_budget,
        ai_enabled=ai_enabled,
        ai_reason=ai_reason,
        model_name=model_name,
        prompt_path=prompt_path,
        candidate_id=candidate_id,
    )

    logger.info("AI job briefs written: %s", json_path)
    logger.info("AI job briefs markdown: %s", md_path)

    if ai_enabled:
        webhook = resolve_webhook(args.profile)
        if webhook:
            base_url = os.environ.get("JOBINTEL_DASHBOARD_URL", "").rstrip("/")
            run_url = f"{base_url}/runs/{run_id}" if base_url else f"Run ID: {run_id}"
            message = f"AI briefs: generated for top {len(payload.get('briefs') or [])}. {run_url}"
            post_discord(webhook, message)

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
