#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from ji_engine.ai.augment import compute_content_hash, load_cached_ai, save_cached_ai
from ji_engine.ai.extract_rules import RULES_VERSION, extract_ai_fields
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
    ap.add_argument("--in_path", help="Input enriched jobs JSON (default: config ENRICHED_JOBS_JSON)")
    ap.add_argument("--out_path", help="Output AI-enriched jobs JSON (default: data/openai_enriched_jobs_ai.json)")
    return ap.parse_args(argv)


def _select_provider(args: argparse.Namespace) -> AIProvider:
    if args.ai_live:
        api_key = os.environ.get("OPENAI_API_KEY", "").strip()
        if api_key:
            logger.info("Using OpenAIProvider (ai_live enabled).")
            return OpenAIProvider(api_key=api_key)
        logger.warning("ai_live requested but OPENAI_API_KEY not set; falling back to StubProvider.")
    return StubProvider()


_RULE_FIELDS = (
    "skills_required",
    "skills_preferred",
    "role_family",
    "seniority",
    "red_flags",
    "security_required_reason",
    "security_required_match",
    "security_required_context",
)


def _needs_rule_upgrade(payload: Dict[str, Any]) -> bool:
    if not payload:
        return True
    return payload.get("rules_version") != RULES_VERSION


def _apply_rule_fields(payload: Dict[str, Any], job: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(payload)
    overrides = extract_ai_fields(job)
    for k in _RULE_FIELDS:
        merged[k] = overrides.get(k, [])
    merged["rules_version"] = overrides.get("rules_version", RULES_VERSION)
    return merged


def _ensure_rules(payload: Dict[str, Any], job: Dict[str, Any], provider: AIProvider) -> tuple[Dict[str, Any], bool]:
    needs_upgrade = isinstance(provider, StubProvider) or _needs_rule_upgrade(payload)
    if needs_upgrade:
        payload = _apply_rule_fields(payload, job)
    return payload, needs_upgrade


def main(argv: Optional[List[str]] = None, provider: Optional[AIProvider] = None) -> int:
    args = _parse_args(argv or [])
    provider = provider or _select_provider(args)

    in_path = Path(args.in_path) if args.in_path else ENRICHED_JOBS_JSON
    out_path = Path(args.out_path) if args.out_path else OUTPUT_PATH

    if not in_path.exists():
        raise SystemExit(f"Input not found: {in_path}")

    candidate_profile = None
    if PROFILE_PATH.exists():
        try:
            candidate_profile = load_candidate_profile(str(PROFILE_PATH))
            logger.info("Loaded candidate_profile.json for match scoring.")
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(f"Could not load candidate_profile.json; proceeding without match scoring: {exc}")

    jobs: List[Dict[str, Any]] = json.loads(in_path.read_text(encoding="utf-8"))
    augmented: List[Dict[str, Any]] = []
    cache_hits = 0

    for job in jobs:
        job_id = job.get("apply_url") or job.get("id") or job.get("applyId") or "unknown"
        chash = compute_content_hash(job)
        cached = load_cached_ai(job_id, chash)
        if cached:
            cache_hits += 1
            payload = ensure_ai_payload(cached)
            payload, upgraded = _ensure_rules(payload, job, provider)
            if upgraded:
                save_cached_ai(job_id, chash, payload)
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
            # Backfill/augment fields deterministically when using stub provider or when skills are missing/empty.
            rules = extract_ai_fields(job) if isinstance(provider, StubProvider) else {}
            if not (raw.get("skills_required") or raw.get("skills_preferred")):
                rules = extract_ai_fields(job)
            merged = dict(raw)
            for k in ("skills_required", "skills_preferred", "role_family", "seniority", "red_flags"):
                v = merged.get(k)
                add = rules.get(k)
                if isinstance(v, list):
                    seen = set(str(x) for x in v)
                    for x in add or []:
                        sx = str(x)
                        if sx not in seen:
                            v.append(sx)
                            seen.add(sx)
                elif not v:
                    merged[k] = add
            payload = ensure_ai_payload(merged)
            save_cached_ai(job_id, chash, payload)

        # If cached payload was produced before rules existed (or provider returned empty skills), backfill now.
        if isinstance(provider, StubProvider) or not (payload.get("skills_required") or payload.get("skills_preferred")):
            rules = extract_ai_fields(job)
            merged = dict(payload)
            for k in ("skills_required", "skills_preferred", "role_family", "seniority", "red_flags"):
                v = merged.get(k)
                add = rules.get(k)
                if isinstance(v, list):
                    seen = set(str(x) for x in v)
                    for x in add or []:
                        sx = str(x)
                        if sx not in seen:
                            v.append(sx)
                            seen.add(sx)
                elif not v:
                    merged[k] = add
            payload = ensure_ai_payload(merged)
            payload, upgraded = _ensure_rules(payload, job, provider)
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

    atomic_write_text(out_path, json.dumps(augmented, ensure_ascii=False, indent=2))
    logger.info(f"AI augment complete. cache_hits={cache_hits}, total={len(jobs)}")
    logger.info(f"Output: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
