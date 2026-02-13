#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from typing import List

from ji_engine.config import DEFAULT_CANDIDATE_ID, sanitize_candidate_id
from ji_engine.run_repository import FileSystemRunRepository, discover_candidates


def _rebuild_for_candidates(candidate_ids: List[str]) -> List[dict]:
    repo = FileSystemRunRepository()
    results: List[dict] = []
    for candidate_id in sorted(candidate_ids):
        safe_candidate = sanitize_candidate_id(candidate_id)
        results.append(repo.rebuild_index(safe_candidate))
    return results


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Rebuild deterministic SQLite run index from run artifacts.")
    parser.add_argument("--candidate-id", default=DEFAULT_CANDIDATE_ID)
    parser.add_argument("--all-candidates", action="store_true")
    parser.add_argument("--json", action="store_true", help="Emit JSON output")
    args = parser.parse_args(argv)

    if args.all_candidates:
        candidate_ids = discover_candidates()
    else:
        candidate_ids = [sanitize_candidate_id(args.candidate_id)]

    results = _rebuild_for_candidates(candidate_ids)
    if args.json:
        print(json.dumps({"results": results}, sort_keys=True))
    else:
        for item in results:
            print(f"candidate_id={item['candidate_id']} runs_indexed={item['runs_indexed']} db_path={item['db_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
