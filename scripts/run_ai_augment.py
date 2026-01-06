#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from ji_engine.ai.augment import compute_content_hash, load_cached_ai, save_cached_ai
from ji_engine.ai.match import compute_match
from ji_engine.ai.provider import OpenAIProvider, StubProvider, AIProvider
from ji_engine.config import ENRICHED_JOBS_JSON
from ji_engine.utils.atomic_write import atomic_write_text
from ji_engine.ai.schema import ensure_ai_payload
from ji_engine.profile_loader import load_candidate_profile

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

OUTPUT_PATH = Path("data/openai_enriched_jobs_ai.json")
PROFILE_PATH = Path("data/candidate_profile.json")


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ai_live", action="store_true", help="Use live AI provider (requires OPENAI_API_KEY)")
    return ap.parse_args(argv if argv is not None else [])


def _select_provider(args: argparse.Namespace) -> AIProvider:
    if args.ai_live:
        api_key = os.environ.get("OPENAI_API_KEY", "").strip()
        if api_key:
            logger.info("Using OpenAIProvider (ai_live enabled).")
            return OpenAIProvider(api_key=api_key)
        logger.warning("ai_live requested but OPENAI_API_KEY not set; falling back to StubProvider.")
    return StubProvider()


def main(argv: Optional[List[str]] = None, provider: Optional[AIProvider] = None) -> int:
    args = _parse_args(argv)
    provider = provider or _select_provider(args)

    if not ENRICHED_JOBS_JSON.exists():
        raise SystemExit(f"Input not found: {ENRICHED_JOBS_JSON}")

    candidate_profile = None
    if PROFILE_PATH.exists():
        try:
            candidate_profile = load_candidate_profile(str(PROFILE_PATH))
            logger.info("Loaded candidate_profile.json for match scoring.")
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(f"Could not load candidate_profile.json; proceeding without match scoring: {exc}")

    jobs: List[Dict[str, Any]] = json.loads(ENRICHED_JOBS_JSON.read_text(encoding="utf-8"))
    augmented: List[Dict[str, Any]] = []
    cache_hits = 0

    for job in jobs:
        job_id = job.get("apply_url") or job.get("id") or job.get("applyId") or "unknown"
        chash = compute_content_hash(job)
        cached = load_cached_ai(job_id, chash)
        if cached:
            cache_hits += 1
            payload = ensure_ai_payload(cached)
        else:
            try:
                raw = provider.extract(job)
            except Exception as exc:  # pragma: no cover - defensive
                logger.error("AI provider extract failed: %s", exc, exc_info=True)
                raw = {
                    "summary": f"AI extraction failed for {job.get('title','(untitled)')}",
                    "confidence": 0.0,
                    "notes": f"provider_error:{exc}",
                }
            payload = ensure_ai_payload(raw)
            save_cached_ai(job_id, chash, payload)

        if candidate_profile:
            match_score, match_notes = compute_match(payload, candidate_profile)
            payload["match_score"] = match_score
            # concatenate notes (payload may already contain notes)
            notes_text = "; ".join(str(n) for n in match_notes) if isinstance(match_notes, list) else str(match_notes)
            if payload.get("notes"):
                payload["notes"] = f"{payload['notes']} | {notes_text}"
            else:
                payload["notes"] = notes_text
            payload = ensure_ai_payload(payload)
            # keep cache in sync with computed match score
            save_cached_ai(job_id, chash, payload)

        job_out = dict(job)
        job_out["ai"] = payload
        job_out["ai_content_hash"] = chash
        augmented.append(job_out)

    atomic_write_text(OUTPUT_PATH, json.dumps(augmented, ensure_ascii=False, indent=2))
    logger.info(f"AI augment complete. cache_hits={cache_hits}, total={len(jobs)}")
    logger.info(f"Output: {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

