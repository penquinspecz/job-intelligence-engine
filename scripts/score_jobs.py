#!/usr/bin/env python3
"""
Score enriched job postings for CS-fit / customer-facing technical roles.

Input:
  data/openai_enriched_jobs.json (produced by scripts.enrich_jobs)

Outputs:
  data/openai_ranked_jobs.json
  data/openai_ranked_jobs.csv
  data/openai_ranked_families.json
  data/openai_shortlist.md

Usage:
  python scripts/score_jobs.py
  # optional:
  python scripts/score_jobs.py --in data/openai_enriched_jobs.json \
      --out_json data/openai_ranked_jobs.json \
      --out_csv data/openai_ranked_jobs.csv \
      --out_families data/openai_ranked_families.json \
      --out_md data/openai_shortlist.md
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

def load_profiles(path: str) -> Dict[str, Any]:
    p = Path(path)
    if not p.exists():
        raise SystemExit(f"Profiles config not found: {p}")
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit("profiles.json must be an object mapping profile_name -> config")
    return data


def apply_profile(profile_name: str, profiles: Dict[str, Any]) -> None:
    """
    Overwrite global ROLE_BAND_MULTIPLIERS + PROFILE_WEIGHTS with selected profile settings.
    """
    if profile_name not in profiles:
        raise SystemExit(f"Unknown profile '{profile_name}'. Available: {', '.join(sorted(profiles.keys()))}")

    cfg = profiles[profile_name]
    rbm = cfg.get("role_band_multipliers")
    pw = cfg.get("profile_weights")

    if not isinstance(rbm, dict) or not isinstance(pw, dict):
        raise SystemExit(f"Profile '{profile_name}' must contain role_band_multipliers and profile_weights dicts")

    # overwrite in-place so rest of script doesn't change
    ROLE_BAND_MULTIPLIERS.clear()
    ROLE_BAND_MULTIPLIERS.update({str(k): float(v) for k, v in rbm.items()})

    PROFILE_WEIGHTS.clear()
    PROFILE_WEIGHTS.update({str(k): int(v) for k, v in pw.items()})



# ------------------------------------------------------------
# Tunables: role-band multipliers (this is your big lever)
# ------------------------------------------------------------

ROLE_BAND_MULTIPLIERS: Dict[str, float] = {
    "CS_CORE": 1.25,
    "CS_ADJACENT": 1.15,
    "SOLUTIONS": 1.05,
    "OTHER": 0.95,
}


# ------------------------------------------------------------
# Tunables: profile weights (Step 3)
# You can tweak these numbers anytime without touching logic.
# ------------------------------------------------------------

PROFILE_WEIGHTS = {
    "boost_cs_core": 15,
    "boost_cs_adjacent": 5,
    "boost_solutions": 2,

    "penalty_research_heavy": -8,
    "penalty_low_level": -5,
    "penalty_strong_swe_only": -4,

    # was 6 — increase so it outranks Partner Solutions Architect
    "pin_manager_ai_deployment": 30,
}


# ------------------------------------------------------------
# Rules for base scoring
# ------------------------------------------------------------

@dataclass(frozen=True)
class Rule:
    name: str
    pattern: re.Pattern
    weight: int
    scope: str  # "title" | "text" | "either"


def _compile_rules() -> Tuple[List[Rule], List[Rule]]:
    """
    Returns (positive_rules, negative_rules).
    Patterns are intentionally broad but phrase-ish to avoid noise.
    """
    pos = [
        Rule("customer_success", re.compile(r"\bcustomer success\b", re.I), 8, "either"),
        Rule("value_realization", re.compile(r"\bvalue realization\b|\bbusiness value\b|\bROI\b", re.I), 7, "either"),
        Rule("adoption_onboarding_enablement", re.compile(r"\badoption\b|\bonboarding\b|\benablement\b", re.I), 6, "text"),
        Rule("deployment_implementation", re.compile(r"\bdeploy(ment|ing|ed)?\b|\bimplementation\b", re.I), 5, "either"),
        Rule("stakeholder_exec", re.compile(r"\bstakeholder(s)?\b|\bexecutive\b|\bC-?level\b", re.I), 4, "text"),
        Rule("enterprise_strategic", re.compile(r"\benterprise\b|\bstrategic\b|\bkey account\b", re.I), 3, "text"),
        Rule("customer_facing", re.compile(r"\bcustomer-?facing\b|\bexternal\b clients?\b", re.I), 4, "text"),
        Rule("consultative_advisory", re.compile(r"\badvis(e|ory)\b|\bconsult(ing|ative)\b", re.I), 3, "text"),
        Rule("discovery_requirements", re.compile(r"\bdiscovery\b|\bneeds assessment\b|\brequirements gathering\b", re.I), 3, "text"),
        Rule("integrations_apis", re.compile(r"\bintegration(s)?\b|\bAPI(s)?\b|\bSDK\b", re.I), 2, "text"),
        Rule("governance_security_compliance", re.compile(r"\bgovernance\b|\bsecurity\b|\bcompliance\b", re.I), 2, "text"),
        Rule("renewal_retention_expansion", re.compile(r"\brenewal(s)?\b|\bretention\b|\bexpansion\b|\bupsell\b|\bcross-?sell\b", re.I), 3, "text"),

        # title-forward signals (but keep weights lower than CS/value/adoption)
        Rule("solutions_architect", re.compile(r"\bsolutions architect\b", re.I), 6, "title"),
        Rule("solutions_engineer", re.compile(r"\bsolutions engineer\b", re.I), 6, "title"),
        Rule("forward_deployed", re.compile(r"\bforward deployed\b", re.I), 5, "either"),
        Rule("program_manager", re.compile(r"\bprogram manager\b", re.I), 2, "title"),
    ]

    neg = [
        Rule("research_scientist", re.compile(r"\bresearch scientist\b|\bresearcher\b", re.I), -10, "either"),
        Rule("phd_required", re.compile(r"\bPhD\b|\bdoctoral\b", re.I), -8, "text"),
        Rule("model_training_pretraining", re.compile(r"\bpretraining\b|\bRLHF\b|\btraining pipeline\b|\bmodel training\b", re.I), -8, "text"),
        Rule("compiler_kernels_cuda", re.compile(r"\bcompiler\b|\bkernels?\b|\bCUDA\b|\bTPU\b|\bASIC\b", re.I), -5, "text"),
        Rule("theory_math_heavy", re.compile(r"\btheoretical\b|\bproof\b|\bnovel algorithm\b", re.I), -4, "text"),
    ]
    return pos, neg


# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------

def _norm(s: Optional[str]) -> str:
    return (s or "").strip()


def _get_text_blob(job: Dict[str, Any]) -> str:
    """
    Prefer jd_text. If missing, try other possible fields.
    """
    jd = _norm(job.get("jd_text"))
    if jd:
        return jd

    for k in ("description", "description_text", "job_description", "descriptionHtml"):
        v = job.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()

    return ""


def _count_matches(pattern: re.Pattern, s: str) -> int:
    if not s:
        return 0
    matches = list(pattern.finditer(s))
    return min(len(matches), 5)


def _classify_role_band(job: Dict[str, Any]) -> str:
    """
    Classify role band using title + jd_text + department/team strings.
    Priority: CS_CORE -> CS_ADJACENT -> SOLUTIONS -> OTHER (your preference ordering).
    """
    title = _norm(job.get("title"))
    jd = _norm(job.get("jd_text"))
    dept = _norm(job.get("department") or job.get("departmentName"))
    team = _norm(job.get("team"))
    team_names = job.get("teamNames") if isinstance(job.get("teamNames"), list) else []
    team_blob = " ".join([t for t in team_names if isinstance(t, str)])
    combined = " ".join([title, jd, dept, team, team_blob]).lower()

    def has_any(subs: List[str]) -> bool:
        return any(s in combined for s in subs)

    if has_any([
        "customer success", "csm", "success plan", "value realization", "adoption", "onboarding",
        "retention", "renewal", "deployment and adoption", "ai deployment", "support delivery",
    ]):
        return "CS_CORE"

    if has_any([
        "program manager", "delivery lead", "enablement", "engagement", "operations", "gtm", "go to market",
        "account director", "partner", "alliances",
    ]):
        return "CS_ADJACENT"

    if has_any([
        "solutions architect", "solutions engineer", "forward deployed", "field engineer", "pre-sales",
        "presales", "sales engineer", "partner solutions",
    ]):
        return "SOLUTIONS"

    return "OTHER"


def _title_family(title: str) -> str:
    """
    Normalize title into a family bucket for clustering.
    """
    t = _norm(title).lower()
    t = re.sub(r"\s*\([^)]*(remote|san francisco|new york|london|dublin|tokyo|munich|sydney)[^)]*\)\s*$", "", t, flags=re.I)
    t = re.sub(r"\s*[-–—]\s*(sf|nyc|new york|san francisco|london|dublin|tokyo|munich|sydney)\s*$", "", t, flags=re.I)
    t = re.sub(r"\s+", " ", t).strip()
    return t


# ------------------------------------------------------------
# Explainability buckets (Step 1)
# ------------------------------------------------------------

FIT_PATTERNS = [
    ("fit:value_realization", re.compile(r"\bvalue realization\b|\bbusiness value\b|\bROI\b", re.I)),
    ("fit:adoption", re.compile(r"\badoption\b|\bonboarding\b|\benablement\b", re.I)),
    ("fit:stakeholders", re.compile(r"\bstakeholder(s)?\b|\bexecutive\b|\bC-?level\b", re.I)),
    ("fit:post_sales", re.compile(r"\bpost[- ]sales\b|\bcustomer success\b|\brenewal\b|\bretention\b", re.I)),
    ("fit:deployment", re.compile(r"\bdeployment\b|\bimplementation\b|\bintegration\b", re.I)),
]

RISK_PATTERNS = [
    ("risk:phd", re.compile(r"\bPhD\b|\bdoctoral\b", re.I)),
    ("risk:research_heavy", re.compile(r"\bresearch\b|\bnovel algorithm\b|\btheoretical\b", re.I)),
    ("risk:low_level", re.compile(r"\bcompiler\b|\bCUDA\b|\bkernels?\b|\bASIC\b|\bTPU\b", re.I)),
    ("risk:strong_swe_only", re.compile(r"\bC\+\+\b|\brust\b|\boperating systems\b|\bkernel\b", re.I)),
    ("risk:security_clearance", re.compile(r"\b(clearance|ts\/sc|secret|top secret)\b", re.I)),
]


def _signals(text: str, patterns: List[Tuple[str, re.Pattern]]) -> List[str]:
    out: List[str] = []
    for name, pat in patterns:
        if pat.search(text):
            out.append(name)
    return out


# ------------------------------------------------------------
# Scoring
# ------------------------------------------------------------

def score_job(job: Dict[str, Any], pos_rules: List[Rule], neg_rules: List[Rule]) -> Dict[str, Any]:
    title = _norm(job.get("title"))
    text = _get_text_blob(job)
    enrich_status = job.get("enrich_status")  # "enriched" | "unavailable" | etc.

    # If JD unavailable, score title-only lightly.
    title_only_mode = (enrich_status == "unavailable") or (not text)

    base_score = 0
    hits: List[Dict[str, Any]] = []

    def apply_rule(rule: Rule) -> None:
        nonlocal base_score

        if rule.scope == "title":
            hay = title
        elif rule.scope == "text":
            hay = "" if title_only_mode else text
        else:  # either
            hay = title if title_only_mode else (title + "\n" + text)

        c = _count_matches(rule.pattern, hay)
        if c <= 0:
            return

        delta = rule.weight * c
        base_score += delta
        hits.append({"rule": rule.name, "count": c, "delta": delta})

    for r in pos_rules:
        apply_rule(r)
    for r in neg_rules:
        apply_rule(r)

    if (not title_only_mode) and len(text) >= 800:
        base_score += 2
        hits.append({"rule": "has_full_jd_text", "count": 1, "delta": 2})

    # Role band multiplier
    role_band = _classify_role_band(job)
    mult = ROLE_BAND_MULTIPLIERS.get(role_band, 1.0)

    # Profile weights (Step 3): additive nudges
    profile_delta = 0
    if role_band == "CS_CORE":
        profile_delta += PROFILE_WEIGHTS["boost_cs_core"]
    elif role_band == "CS_ADJACENT":
        profile_delta += PROFILE_WEIGHTS["boost_cs_adjacent"]
    elif role_band == "SOLUTIONS":
        profile_delta += PROFILE_WEIGHTS["boost_solutions"]

    # Optional pin for your explicitly mentioned target
    if re.search(r"\bmanager,\s*ai deployment\b", title, re.I):
        profile_delta += PROFILE_WEIGHTS["pin_manager_ai_deployment"]
        hits.append({"rule": "pin_manager_ai_deployment", "count": 1, "delta": PROFILE_WEIGHTS["pin_manager_ai_deployment"]})

    # Risk penalties based on JD/text
    blob = (title if title_only_mode else (title + "\n" + text))
    if re.search(r"\bPhD\b|\bdoctoral\b", blob, re.I):
        profile_delta += PROFILE_WEIGHTS["penalty_research_heavy"]
    if re.search(r"\bcompiler\b|\bCUDA\b|\bkernels?\b|\bASIC\b|\bTPU\b", blob, re.I):
        profile_delta += PROFILE_WEIGHTS["penalty_low_level"]
    if re.search(r"\bC\+\+\b|\brust\b|\boperating systems\b|\bkernel\b", blob, re.I):
        profile_delta += PROFILE_WEIGHTS["penalty_strong_swe_only"]

    score = int(round((base_score + profile_delta) * mult))

    fit_signals = _signals(blob, FIT_PATTERNS)
    risk_signals = _signals(blob, RISK_PATTERNS)

    out = dict(job)
    out["base_score"] = base_score
    out["profile_delta"] = profile_delta
    out["score"] = score
    out["role_band"] = role_band
    out["score_hits"] = sorted(hits, key=lambda x: abs(x["delta"]), reverse=True)
    out["fit_signals"] = fit_signals
    out["risk_signals"] = risk_signals
    out["jd_text_chars"] = len(text)
    out["title_only_mode"] = title_only_mode
    out["title_family"] = _title_family(title)
    return out


def to_csv_rows(scored: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for j in scored:
        top_hits = j.get("score_hits") or []
        top3 = ", ".join([f"{h['rule']}({h['delta']})" for h in top_hits[:3]])
        rows.append({
            "score": j.get("score", 0),
            "base_score": j.get("base_score", 0),
            "profile_delta": j.get("profile_delta", 0),
            "role_band": _norm(j.get("role_band")),
            "title": _norm(j.get("title")),
            "department": _norm(j.get("department") or j.get("departmentName")),
            "team": ", ".join(j.get("teamNames") or []) if isinstance(j.get("teamNames"), list) else _norm(j.get("team")),
            "location": _norm(j.get("location") or j.get("locationName")),
            "enrich_status": _norm(j.get("enrich_status")),
            "enrich_reason": _norm(j.get("enrich_reason")),
            "jd_text_chars": j.get("jd_text_chars", 0),
            "fit_signals": ", ".join(j.get("fit_signals") or []),
            "risk_signals": ", ".join(j.get("risk_signals") or []),
            "apply_url": _norm(j.get("apply_url")),
            "why_top3": top3,
        })
    return rows


# ------------------------------------------------------------
# Step 5: clustering / families output
# ------------------------------------------------------------

def build_families(scored: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    families: Dict[str, Dict[str, Any]] = {}
    variants: Dict[str, List[Dict[str, Any]]] = {}

    for j in scored:
        fam = _norm(j.get("title_family"))
        if not fam:
            fam = _title_family(_norm(j.get("title")))
        if not fam:
            fam = _norm(j.get("title")).lower()

        variants.setdefault(fam, []).append({
            "title": _norm(j.get("title")),
            "location": _norm(j.get("location") or j.get("locationName")),
            "apply_url": _norm(j.get("apply_url")),
            "score": j.get("score", 0),
            "role_band": _norm(j.get("role_band")),
        })

        if fam not in families or j.get("score", 0) > families[fam].get("score", 0):
            families[fam] = dict(j)

    out: List[Dict[str, Any]] = []
    for fam, best in families.items():
        entry = dict(best)
        entry["title_family"] = fam
        entry["family_variants"] = variants.get(fam, [])
        out.append(entry)

    out.sort(key=lambda x: x.get("score", 0), reverse=True)
    return out


# ------------------------------------------------------------
# Step 8: shortlist output
# ------------------------------------------------------------

def write_shortlist_md(scored: List[Dict[str, Any]], out_path: Path, min_score: int) -> None:
    shortlist = [
        j for j in scored
        if j.get("score", 0) >= min_score and j.get("enrich_status") != "unavailable"
    ]

    lines: List[str] = ["# OpenAI Shortlist", f"", f"Min score: **{min_score}**", ""]
    for job in shortlist:
        title = _norm(job.get("title")) or "Untitled"
        score = job.get("score", 0)
        role_band = _norm(job.get("role_band"))
        apply_url = _norm(job.get("apply_url"))

        lines.append(f"## {title} — {score} [{role_band}]")
        if apply_url:
            lines.append(f"[Apply link]({apply_url})")

        fit = job.get("fit_signals") or []
        risk = job.get("risk_signals") or []
        if fit:
            lines.append("**Fit signals:** " + ", ".join(fit))
        if risk:
            lines.append("**Risk signals:** " + ", ".join(risk))

        hits = job.get("score_hits") or []
        reasons = [h.get("rule") for h in hits[:5] if h.get("rule")]
        if reasons:
            lines.append("**Top rules:** " + ", ".join(reasons))

        jd = _norm(job.get("jd_text"))
        if jd:
            excerpt = jd[:700] + ("…" if len(jd) > 700 else "")
            lines.append("")
            lines.append(excerpt)

        lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")

def is_us_or_remote_us(job: Dict[str, Any]) -> bool:
    loc = (job.get("location") or job.get("locationName") or "").strip().lower()

    # allow remote only if explicitly US
    if "remote" in loc:
        return "us" in loc or "united states" in loc

    # common non-US markers to exclude
    non_us_markers = [
        "london", "uk", "united kingdom",
        "dublin", "ireland",
        "tokyo", "japan",
        "munich", "germany",
        "sydney", "australia",
        "emea", "apac", "singapore", "paris", "france", "canada",
    ]
    if any(x in loc for x in non_us_markers):
        return False

    # If it isn't clearly non-US and isn't remote, assume it's US (works well for SF/NYC/DC etc)
    return bool(loc)

# ------------------------------------------------------------
# Main
# ------------------------------------------------------------



def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="in_path", default="data/openai_enriched_jobs.json")
    ap.add_argument("--out_json", default="data/openai_ranked_jobs.json")
    ap.add_argument("--out_csv", default="data/openai_ranked_jobs.csv")
    ap.add_argument("--out_families", default="data/openai_ranked_families.json")
    ap.add_argument("--out_md", default="data/openai_shortlist.md")
    ap.add_argument("--shortlist_score", type=int, default=70)
    ap.add_argument("--us_only", action="store_true", help="Only keep US locations or Remote - US")
    ap.add_argument("--profile", default="cs", help="Scoring profile (cs|tam|se)")
    ap.add_argument("--profiles", default="config/profiles.json", help="Path to profiles.json")
    
    args = ap.parse_args()
    profiles = load_profiles(args.profiles)
    apply_profile(args.profile, profiles)

    in_path = Path(args.in_path)
    if not in_path.exists():
        raise SystemExit(f"Input not found: {in_path}")

    jobs = json.loads(in_path.read_text(encoding="utf-8"))
    if not isinstance(jobs, list):
        raise SystemExit("Input JSON must be a list of jobs")

    if args.us_only:
        before = len(jobs)
        jobs = [j for j in jobs if is_us_or_remote_us(j)]
        print(f"US-only filter: {before} -> {len(jobs)} jobs")

    pos_rules, neg_rules = _compile_rules()
    scored = [score_job(j, pos_rules, neg_rules) for j in jobs]
    scored.sort(key=lambda x: x.get("score", 0), reverse=True)

    # Write ranked JSON
    Path(args.out_json).write_text(
        json.dumps(scored, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # Write CSV
    rows = to_csv_rows(scored)
    out_csv = Path(args.out_csv)
    with out_csv.open("w", encoding="utf-8", newline="") as f:
        if rows:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)

    # Write families (Step 5)
    families = build_families(scored)
    Path(args.out_families).write_text(
        json.dumps(families, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # Write shortlist (Step 8)
    write_shortlist_md(scored, Path(args.out_md), min_score=args.shortlist_score)

    enriched = sum(1 for j in scored if (j.get("enrich_status") != "unavailable") and (j.get("jd_text_chars", 0) > 0))
    unavailable = sum(1 for j in scored if j.get("enrich_status") == "unavailable")

    print(f"Wrote ranked JSON     : {args.out_json}")
    print(f"Wrote ranked CSV      : {args.out_csv}")
    print(f"Wrote ranked families : {args.out_families}")
    print(f"Wrote shortlist MD    : {args.out_md} (score >= {args.shortlist_score})")
    print(f"Jobs: {len(scored)} | enriched-ish: {enriched} | unavailable: {unavailable}")
    print("Top 5:")
    for j in scored[:5]:
        loc = j.get("location") or j.get("locationName") or ""
        print(f"  {j.get('score', 0):>4} [{j.get('role_band')}] {j.get('title')} ({loc})")

    return 0



if __name__ == "__main__":
    raise SystemExit(main())
