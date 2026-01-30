#!/usr/bin/env python3
try:
    import _bootstrap  # type: ignore
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

"""
Deterministic enrichment step (derived from existing job fields).

Usage (from repo root, with venv active):

    python scripts/run_enrich.py --in_path data/openai_labeled_jobs.json --out_path data/openai_enriched_jobs.json
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from ji_engine.config import ENRICHED_JOBS_JSON, LABELED_JOBS_JSON
from jobintel.enrichment import enrich_jobs

try:
    from schema_validate import resolve_named_schema_path, validate_payload
except ImportError:  # pragma: no cover - script execution fallback
    from scripts.schema_validate import resolve_named_schema_path, validate_payload


def _canonical_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description="Deterministic enrichment step.")
    ap.add_argument("--in_path", help="Input labeled jobs JSON (default: config LABELED_JOBS_JSON)")
    ap.add_argument("--out_path", help="Output enriched jobs JSON (default: config ENRICHED_JOBS_JSON)")
    ap.add_argument("--cache_dir", help="Optional cache dir (default: JOBINTEL_CACHE_DIR or data/ashby_cache)")
    ap.add_argument("--providers", help="Optional providers list (unused; for compatibility)")
    args = ap.parse_args()

    labeled_path = Path(args.in_path) if args.in_path else LABELED_JOBS_JSON
    output_path = Path(args.out_path) if args.out_path else ENRICHED_JOBS_JSON
    cache_dir = Path(args.cache_dir) if args.cache_dir else None

    if not labeled_path.exists():
        print(f"Error: Labeled jobs file not found: {labeled_path}")
        print("Run scripts/run_classify.py first to generate labeled jobs.")
        sys.exit(1)

    labeled_jobs = json.loads(labeled_path.read_text(encoding="utf-8"))
    if not isinstance(labeled_jobs, list):
        print(f"Error: Labeled jobs file is not a list: {labeled_path}")
        sys.exit(1)

    enriched_jobs = enrich_jobs(labeled_jobs, cache_dir)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(_canonical_json(enriched_jobs), encoding="utf-8")

    schema_path = resolve_named_schema_path("enriched_jobs", 1)
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    errors = validate_payload(enriched_jobs, schema)
    if errors:
        print("Enriched schema validation failed:")
        for err in errors[:8]:
            print(f"- {err}")
        sys.exit(2)

    print(f"Enriched {len(enriched_jobs)} jobs -> {output_path}")


if __name__ == "__main__":
    main()
