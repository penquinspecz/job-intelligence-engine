#!/usr/bin/env python3
"""
Entry point to run the job classification pipeline.

Usage (from repo root, with venv active):
  python scripts/run_classify.py
"""

from __future__ import annotations

try:
    import _bootstrap  # type: ignore
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from ji_engine.config import EMBED_CACHE_JSON, LABELED_JOBS_JSON, RAW_JOBS_JSON
from ji_engine.embeddings.provider import EmbeddingProvider, OpenAIEmbeddingProvider, StubEmbeddingProvider
from ji_engine.embeddings.simple import (
    build_profile_text,
    cosine_similarity,
    load_cache,
    save_cache,
    text_hash,
)
from ji_engine.models import JobSource, RawJobPosting
from ji_engine.pipeline.classifier import label_jobs
from ji_engine.profile_loader import load_candidate_profile
from ji_engine.utils.compat import zip_pairs

logger = logging.getLogger(__name__)


def _load_raw_jobs(path: Path) -> List[RawJobPosting]:
    if not path.exists():
        raise FileNotFoundError(f"Jobs file not found: {path}")

    jobs: List[RawJobPosting] = []
    data = json.loads(path.read_text(encoding="utf-8"))

    for d in data:
        # Normalize types for RawJobPosting(**d)
        try:
            d["source"] = JobSource(d["source"])
        except Exception:
            d["source"] = JobSource.OPENAI
        d["scraped_at"] = datetime.fromisoformat(d["scraped_at"])
        jobs.append(RawJobPosting(**d))

    return jobs


def _select_provider(kind: str, api_key: str | None = None) -> EmbeddingProvider:
    if kind == "openai":
        if not api_key:
            raise SystemExit("OPENAI_API_KEY required for openai embedding provider")
        return OpenAIEmbeddingProvider(api_key=api_key)
    return StubEmbeddingProvider()


def _reclassify_maybe(
    jobs: List[RawJobPosting],
    labeled: List[Dict[str, Any]],
    profile_vec: List[float],
    provider: EmbeddingProvider,
    cache_path: Path,
    threshold: float = 0.30,
) -> None:
    if not profile_vec:
        return

    cache = load_cache(cache_path)
    job_cache = cache.setdefault("job", {})
    changed = False

    for job, labeled_result in zip_pairs(jobs, labeled):
        if labeled_result.get("relevance") != "MAYBE":
            continue
        text = job.raw_text or job.title or ""
        h = text_hash(text)
        vec = job_cache.get(h)
        if vec is None:
            vec = provider.embed(text)
            job_cache[h] = vec
            changed = True
        sim = cosine_similarity(profile_vec, vec)
        if sim >= threshold:
            labeled_result["relevance"] = "RELEVANT"
    if changed:
        save_cache(cache_path, cache)


def main(argv: Optional[List[str]] = None) -> int:
    if not logging.getLogger().hasHandlers():
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    ap = argparse.ArgumentParser()
    ap.add_argument("--in_path", help="Input raw jobs JSON (default: config RAW_JOBS_JSON)")
    ap.add_argument("--out_path", help="Output labeled jobs JSON (default: config LABELED_JOBS_JSON)")
    args = ap.parse_args(argv)

    profile = load_candidate_profile()
    provider_kind = os.getenv("EMBED_PROVIDER", "stub").strip().lower()
    api_key = os.getenv("OPENAI_API_KEY", "").strip() or None
    provider = _select_provider(provider_kind, api_key)

    try:
        in_path = Path(args.in_path) if args.in_path else RAW_JOBS_JSON
        jobs = _load_raw_jobs(in_path)
    except FileNotFoundError as e:
        logger.error(f"Error: {e}")
        return 1

    labeled = label_jobs(jobs, profile)

    cache = load_cache(EMBED_CACHE_JSON)
    profile_cache = cache.setdefault("profile", {})
    profile_text = build_profile_text(profile)
    p_hash = text_hash(profile_text)
    profile_vec = profile_cache.get(p_hash)
    if profile_vec is None:
        profile_vec = provider.embed(profile_text)
        profile_cache[p_hash] = profile_vec
        save_cache(EMBED_CACHE_JSON, cache)

    _reclassify_maybe(jobs, labeled, profile_vec, provider, EMBED_CACHE_JSON)

    counts = {"RELEVANT": 0, "MAYBE": 0, "IRRELEVANT": 0}
    for result in labeled:
        counts[result["relevance"]] += 1

    logger.info("\nClassification Summary:")
    logger.info(f"  RELEVANT:   {counts['RELEVANT']}")
    logger.info(f"  MAYBE:      {counts['MAYBE']}")
    logger.info(f"  IRRELEVANT: {counts['IRRELEVANT']}")
    logger.info(f"  Total:      {len(labeled)}")

    relevant_jobs = [r for r in labeled if r["relevance"] == "RELEVANT"]
    logger.info(f"\nFirst {min(10, len(relevant_jobs))} RELEVANT jobs:")
    for i, job in enumerate(relevant_jobs[:10], 1):
        logger.info(f"\n{i}. {job['title']}")
        logger.info(f"   {job['apply_url']}")

    # Write labeled jobs to JSON file
    output_data = []
    for job, labeled_result in zip_pairs(jobs, labeled):
        output_data.append(
            {
                "title": job.title,
                "apply_url": job.apply_url,
                "detail_url": job.detail_url,
                "location": job.location,
                "team": job.team,
                "relevance": labeled_result["relevance"],
                "job_id": labeled_result.get("job_id"),
                "location_norm": labeled_result.get("location_norm"),
                "is_us_or_remote_us_guess": labeled_result.get("is_us_or_remote_us_guess"),
                "us_guess_reason": labeled_result.get("us_guess_reason"),
            }
        )

    out_path = Path(args.out_path) if args.out_path else LABELED_JOBS_JSON
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(output_data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    logger.info(f"\nWrote labeled jobs to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
