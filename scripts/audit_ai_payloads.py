#!/usr/bin/env python3
from __future__ import annotations

"""
Deterministic audit of AI payloads (offline/stub) to quantify extractor changes.

Reads the AI-enriched jobs JSON produced by scripts/run_ai_augment.py:
  data/openai_enriched_jobs_ai.json

Optionally compares against a "before" file (same schema) to compute deltas.

Exit codes:
- 0: success
- 2: invalid input / missing file / malformed JSON
"""

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from ji_engine.utils.job_identity import job_identity


def _job_id(job: Dict[str, Any]) -> str:
    return job_identity(job)


def _as_list_str(v: Any) -> List[str]:
    if isinstance(v, list):
        return [str(x) for x in v if str(x).strip()]
    if v is None:
        return []
    return [str(v)]


def _load_jobs(path: Path) -> List[Dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(data, list):
        raise ValueError(f"{path} must be a JSON list")
    return data


def _ai(job: Dict[str, Any]) -> Dict[str, Any]:
    a = job.get("ai")
    return a if isinstance(a, dict) else {}


def _skills_required(job: Dict[str, Any]) -> List[str]:
    return _as_list_str(_ai(job).get("skills_required"))


def _skills_preferred(job: Dict[str, Any]) -> List[str]:
    return _as_list_str(_ai(job).get("skills_preferred"))

def _security_required_reason(job: Dict[str, Any]) -> str:
    return str(_ai(job).get("security_required_reason") or "").strip()


def _role_family(job: Dict[str, Any]) -> str:
    return str(_ai(job).get("role_family") or "").strip()


def _match_score(job: Dict[str, Any]) -> int:
    try:
        return int(_ai(job).get("match_score", 0) or 0)
    except Exception:
        return 0


def _freq(items: Iterable[str]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for it in items:
        s = str(it).strip()
        if not s:
            continue
        out[s] = out.get(s, 0) + 1
    return out


def _top_k(freq: Dict[str, int], k: int) -> List[Tuple[str, int]]:
    # deterministic: sort by count desc, then name asc
    return sorted(freq.items(), key=lambda kv: (-kv[1], kv[0]))[:k]


def _print_table(rows: List[Tuple[str, int]], header_left: str) -> None:
    print(f"{header_left}\tcount")
    for name, c in rows:
        print(f"{name}\t{c}")


def _match_stats(jobs: List[Dict[str, Any]]) -> Tuple[int, int, int, float, float]:
    ms = [_match_score(j) for j in jobs]
    nonzero = sum(1 for x in ms if x > 0)
    if not ms:
        return 0, 0, 0, 0.0, 0.0
    return len(ms), nonzero, min(ms), max(ms), float(statistics.mean(ms)), float(statistics.median(ms))


def _print_match_stats_section(title: str, jobs: List[Dict[str, Any]]) -> None:
    n, nonzero, mn, mx, mean, med = _match_stats(jobs)
    pct = (nonzero / n) if n else 0.0
    print(f"{title}")
    print(f"jobs\t{n}")
    print(f"nonzero_match_score\t{nonzero}\t({pct:.0%})")
    if n:
        print(f"match_score_min\t{mn}")
        print(f"match_score_max\t{mx}")
        print(f"match_score_mean\t{mean:.1f}")
        print(f"match_score_median\t{med:.1f}")


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--current",
        default="data/openai_enriched_jobs_ai.json",
        help="Path to current AI-enriched jobs JSON",
    )
    ap.add_argument(
        "--before",
        default="",
        help="Optional path to previous AI-enriched jobs JSON for diff",
    )
    ap.add_argument("--top_k", type=int, default=10, help="Top-K skills_required to print")
    args = ap.parse_args(argv)

    cur_path = Path(args.current)
    try:
        if not cur_path.exists():
            print(f"current file not found: {cur_path}", file=sys.stderr)
            return 2
        cur = _load_jobs(cur_path)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 2

    before_path = Path(args.before) if args.before else None
    try:
        if before_path and (not before_path.exists()):
            print(f"before file not found: {before_path}", file=sys.stderr)
            return 2
        before = _load_jobs(before_path) if before_path else None
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 2

    cur_by_id = {jid: j for j in cur if (jid := _job_id(j))}
    before_by_id = {jid: j for j in before if (jid := _job_id(j))} if before is not None else {}

    # --- current summary ---
    print("== CURRENT SUMMARY ==")
    _print_match_stats_section("current_match_score", cur)

    rf_cur = _freq(_role_family(j) or "(blank)" for j in cur)
    print("")
    print("== role_family counts (current) ==")
    _print_table(_top_k(rf_cur, len(rf_cur)), "role_family")

    skills_cur = _freq(s for j in cur for s in _skills_required(j))
    print("")
    print(f"== top {int(args.top_k)} skills_required (current) ==")
    _print_table(_top_k(skills_cur, int(args.top_k)), "skill")

    reasons_cur = _freq(r for j in cur for r in [_security_required_reason(j)] if r)
    print("")
    print("== security_required_reason counts (current) ==")
    _print_table(_top_k(reasons_cur, len(reasons_cur)), "security_required_reason")

    # --- diff vs before ---
    if before is None:
        print("")
        print("== DIFF ==")
        print("before file not provided or not found; skipping diff.")
        return 0

    # Only compare intersection (stable/deterministic).
    ids = sorted(set(cur_by_id.keys()) & set(before_by_id.keys()))
    changed_required = 0
    sec_moved_req_to_pref = 0
    sec_moved_pref_to_req = 0
    sec_disappeared = 0
    sec_appeared = 0

    for jid in ids:
        c = cur_by_id[jid]
        b = before_by_id[jid]
        c_req = _skills_required(c)
        b_req = _skills_required(b)
        c_pref = _skills_preferred(c)
        b_pref = _skills_preferred(b)

        if c_req != b_req:
            changed_required += 1

        b_has_req = "Security" in b_req
        b_has_pref = "Security" in b_pref
        c_has_req = "Security" in c_req
        c_has_pref = "Security" in c_pref

        if b_has_req and (not c_has_req) and c_has_pref:
            sec_moved_req_to_pref += 1
        if b_has_pref and (not b_has_req) and c_has_req:
            sec_moved_pref_to_req += 1
        if (b_has_req or b_has_pref) and (not c_has_req) and (not c_has_pref):
            sec_disappeared += 1
        if (not b_has_req) and (not b_has_pref) and (c_has_req or c_has_pref):
            sec_appeared += 1

    print("")
    print("== DIFF (before -> current) ==")
    print(f"jobs_compared\t{len(ids)}")
    print(f"skills_required_changed\t{changed_required}")

    print("")
    print("== Security movement (before -> current) ==")
    print(f"security_required_to_preferred\t{sec_moved_req_to_pref}")
    print(f"security_preferred_to_required\t{sec_moved_pref_to_req}")
    print(f"security_disappeared\t{sec_disappeared}")
    print(f"security_appeared\t{sec_appeared}")

    skills_before = _freq(s for j in before for s in _skills_required(j))
    print("")
    print(f"== top {int(args.top_k)} skills_required (before) ==")
    _print_table(_top_k(skills_before, int(args.top_k)), "skill")
    print("")
    print(f"== top {int(args.top_k)} skills_required (current) ==")
    _print_table(_top_k(skills_cur, int(args.top_k)), "skill")

    print("")
    print("== match_score summary (before vs current) ==")
    _print_match_stats_section("before_match_score", before)
    print("")
    _print_match_stats_section("current_match_score", cur)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

