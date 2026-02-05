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

try:
    import _bootstrap  # type: ignore
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

import argparse
import csv
import io
import json
import logging
import os
import re
from collections import Counter
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ji_engine.ai.augment import compute_content_hash
from ji_engine.ai.cache import AICache, FileSystemAICache, S3AICache
from ji_engine.ai.provider import AIProvider, OpenAIProvider, StubProvider
from ji_engine.ai.schema import ensure_ai_payload
from ji_engine.config import (
    ENRICHED_JOBS_JSON,
    USER_STATE_DIR,
    ranked_families_json,
    ranked_jobs_csv,
    ranked_jobs_json,
    shortlist_md,
)
from ji_engine.profile_loader import load_candidate_profile
from ji_engine.utils.atomic_write import atomic_write_text, atomic_write_with
from ji_engine.utils.content_fingerprint import content_fingerprint
from ji_engine.utils.job_identity import job_identity
from ji_engine.utils.location_normalize import normalize_location_guess
from ji_engine.utils.user_state import load_user_state

logger = logging.getLogger(__name__)
JSON_DUMP_SETTINGS = {"ensure_ascii": False, "separators": (",", ":"), "sort_keys": True}
CSV_FIELDNAMES = [
    "job_id",
    "score",
    "heuristic_score",
    "final_score",
    "explanation_summary",
    "base_score",
    "profile_delta",
    "role_band",
    "title",
    "department",
    "team",
    "location",
    "enrich_status",
    "enrich_reason",
    "jd_text_chars",
    "fit_signals",
    "risk_signals",
    "apply_url",
    "why_top3",
]


def _serialize_json(obj: Any) -> str:
    return json.dumps(obj, **JSON_DUMP_SETTINGS) + "\n"


def _score_meta_path(out_json: Path) -> Path:
    return out_json.with_suffix(".score_meta.json")


EPHEMERAL_FIELDS = {
    "scraped_at",
    "fetched_at",
    "enriched_at",
    "scored_at",
    "generated_at",
    "run_started_at",
    "run_id",
    "timestamp",
    "created_at",
    "updated_at",
    "location_norm",
    "is_us_or_remote_us_guess",
    "us_guess_reason",
    "final_score_raw",
}


def _strip_ephemeral_fields(job: Dict[str, Any]) -> Dict[str, Any]:
    cleaned = dict(job)
    for field in EPHEMERAL_FIELDS:
        cleaned.pop(field, None)
    return cleaned


def _format_us_only_reason_summary(jobs: List[Dict[str, Any]]) -> str:
    counts = Counter()
    for job in jobs:
        reason = job.get("us_guess_reason")
        if isinstance(reason, str) and reason:
            counts[reason] += 1
    if not counts:
        return "(no reason fields present)"
    parts = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return ", ".join(f"{reason}={count}" for reason, count in parts)


def _stable_job_id(job: Dict[str, Any]) -> str:
    job_id = _norm(job.get("job_id") or job.get("id"))
    if job_id:
        return job_id.lower()
    url = _norm(job.get("apply_url") or job.get("detail_url") or job.get("url"))
    if url:
        return url.lower()
    title = _norm(job.get("title"))
    return title.lower()


def _stable_job_sort_key(job: Dict[str, Any]) -> Tuple[str, str, str]:
    provider = _norm(job.get("provider") or job.get("source"))
    profile = _norm(job.get("profile") or job.get("scoring_profile"))
    return (provider.lower(), profile.lower(), _stable_job_id(job))


def _ranked_sort_key(job: Dict[str, Any]) -> Tuple[int, str, str, str]:
    score = int(job.get("score", 0) or 0)
    provider, profile, stable_id = _stable_job_sort_key(job)
    return (-score, provider, profile, stable_id)


CSV_FIELDNAMES = [
    "job_id",
    "score",
    "heuristic_score",
    "final_score",
    "explanation_summary",
    "base_score",
    "profile_delta",
    "role_band",
    "title",
    "department",
    "team",
    "location",
    "enrich_status",
    "enrich_reason",
    "jd_text_chars",
    "fit_signals",
    "risk_signals",
    "apply_url",
    "why_top3",
]


def _print_explain_top(scored: List[Dict[str, Any]], n: int) -> None:
    """
    Print a deterministic, output-only report for the top N jobs.
    Does not affect scoring or outputs on disk.
    """
    if not n or n <= 0:
        return

    header = [
        "title",
        "heuristic_score",
        "ai_match_score",
        "role_family",
        "seniority",
        "blend_weight_used",
        "final_score",
        "ai_influenced",
    ]
    print("\t".join(header))

    for job in scored[:n]:
        title = _norm(job.get("title")) or "Untitled"
        heuristic_score = int(job.get("heuristic_score", job.get("score", 0)) or 0)
        final_score = int(job.get("final_score", job.get("score", 0)) or 0)
        ai_payload = ensure_ai_payload(job.get("ai") or {}) if job.get("ai") else ensure_ai_payload({})
        ai_match_score = int(ai_payload.get("match_score", 0))
        role_family = str(ai_payload.get("role_family") or "") if job.get("ai") else ""
        seniority = str(ai_payload.get("seniority") or "") if job.get("ai") else ""

        ai_present = bool(job.get("ai"))
        blend_weight_used = AI_BLEND_CONFIG.weight if ai_present else 0.0
        ai_influenced = bool(ai_present and blend_weight_used > 0.0)

        row = [
            title,
            str(heuristic_score),
            str(ai_match_score),
            role_family,
            seniority,
            str(blend_weight_used),
            str(final_score),
            str(ai_influenced),
        ]
        print("\t".join(row))


def _print_family_counts(scored: List[Dict[str, Any]]) -> None:
    """
    Print deterministic role_family frequency table for the ranked list.
    Order is first-seen in the ranked list (top-to-bottom).
    """
    counts: Dict[str, int] = {}
    order: List[str] = []
    for job in scored:
        if job.get("ai"):
            ai_payload = ensure_ai_payload(job.get("ai") or {})
            rf = str(ai_payload.get("role_family") or "").strip()
        else:
            rf = ""
        key = rf if rf else "(blank)"
        if key not in counts:
            counts[key] = 0
            order.append(key)
        counts[key] += 1

    print("\t".join(["role_family", "count"]))
    for k in order:
        print(f"{k}\t{counts[k]}")


def _candidate_skill_set() -> set[str]:
    """
    Best-effort load of candidate_profile.json for explanation-only overlap/gap reporting.
    Does not affect scoring.
    """
    try:
        profile = load_candidate_profile()
    except Exception:
        return set()

    skills: List[str] = []
    try:
        s = profile.skills
        skills = (
            list(s.technical_core or [])
            + list(s.ai_specific or [])
            + list(s.customer_success or [])
            + list(s.domain_knowledge or [])
        )
    except Exception:
        skills = []
    return {str(x).strip().lower() for x in skills if str(x).strip()}


def _build_explanation(job: Dict[str, Any], candidate_skills: set[str]) -> Dict[str, Any]:
    heuristic_score = int(job.get("heuristic_score", job.get("score", 0)) or 0)
    final_score = int(job.get("final_score", job.get("score", 0)) or 0)

    hits = job.get("score_hits") or []
    top3_reasons: List[str] = []
    for h in hits[:3]:
        rule = h.get("rule")
        delta = h.get("delta")
        if rule:
            top3_reasons.append(f"{rule}({delta})")

    ai = ensure_ai_payload(job.get("ai") or {}) if job.get("ai") else ensure_ai_payload({})
    match_score = int(ai.get("match_score", 0))
    skills_required = [str(s) for s in (ai.get("skills_required") or [])]
    skills_preferred = [str(s) for s in (ai.get("skills_preferred") or [])]

    req_overlap = sum(1 for s in skills_required if s.strip().lower() in candidate_skills) if candidate_skills else 0
    pref_overlap = sum(1 for s in skills_preferred if s.strip().lower() in candidate_skills) if candidate_skills else 0
    role_family = str(ai.get("role_family") or "")
    seniority = str(ai.get("seniority") or "")

    match_bits = [
        f"required_overlap={req_overlap}/{len(skills_required)}",
        f"preferred_overlap={pref_overlap}/{len(skills_preferred)}",
    ]
    if role_family:
        match_bits.append(f"role_family={role_family}")
    if seniority:
        match_bits.append(f"seniority={seniority}")
    match_rationale = ", ".join(match_bits)

    missing_required = []
    if candidate_skills and skills_required:
        missing_required = [s for s in skills_required if s.strip().lower() not in candidate_skills]
    missing_required = missing_required[:5]

    blend_weight_used = AI_BLEND_CONFIG.weight if job.get("ai") else 0.0

    if job.get("ai"):
        ai_phrase = f"AI match score {match_score} (weight {blend_weight_used})"
    else:
        ai_phrase = f"AI match score {match_score} not applied (weight {blend_weight_used})"

    explanation_summary = (
        f"Final score {final_score} (Heuristic score {heuristic_score}; {ai_phrase}); "
        f"Top reasons: {', '.join(top3_reasons) or '—'}; "
        f"Missing required skills: {', '.join(missing_required) or '—'}"
    )

    return {
        "heuristic_score": heuristic_score,
        "heuristic_reasons_top3": top3_reasons,
        "match_score": match_score,
        "match_rationale": match_rationale,
        "final_score": final_score,
        "blend_weight_used": blend_weight_used,
        "ai_blend_config": {
            "weight_used": blend_weight_used,
            "min_heuristic_floor": AI_BLEND_CONFIG.min_heuristic_floor,
            "max_ai_contribution": AI_BLEND_CONFIG.max_ai_contribution,
        },
        "missing_required_skills": missing_required,
        "explanation_summary": explanation_summary,
    }


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
    global AI_BLEND_CONFIG
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

    AI_BLEND_CONFIG = replace(
        AI_BLEND_CONFIG,
        weight=float(cfg.get("ai_match_weight", AI_BLEND_CONFIG.weight)),
    )


def _select_ai_provider(ai_live: bool) -> AIProvider:
    if ai_live:
        key = os.environ.get("OPENAI_API_KEY", "").strip()
        if key:
            logger.info("Using OpenAIProvider for application kit.")
            return OpenAIProvider(api_key=key)
        logger.warning("ai_live requested but OPENAI_API_KEY not set; falling back to StubProvider.")
    return StubProvider()


def _select_ai_cache() -> AICache:
    bucket = os.getenv("JOBINTEL_S3_BUCKET", "").strip()
    prefix = os.getenv("JOBINTEL_S3_PREFIX", "").strip()
    if bucket:
        try:
            return S3AICache(bucket=bucket, prefix=prefix)
        except Exception as exc:
            logger.warning("S3AICache unavailable (%s); falling back to filesystem cache.", exc)
    return FileSystemAICache()


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


@dataclass(frozen=True)
class AIBlendConfig:
    """
    Centralized controls for how AI affects scoring.

    NOTE: To preserve existing behavior exactly, the additional controls
    (min_heuristic_floor / max_ai_contribution) default to None (disabled).
    """

    weight: float = 0.35
    min_heuristic_floor: Optional[int] = None
    max_ai_contribution: Optional[int] = None


# Single source of truth for AI blend behavior. Weight can be overridden by profile.
AI_BLEND_CONFIG = AIBlendConfig()


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
        Rule("value_realization", re.compile(r"\bvalue realization\b|\bbusiness value\b|\bROI\b", re.I), 8, "either"),
        Rule(
            "adoption_onboarding_enablement",
            re.compile(r"\badoption\b|\bonboarding\b|\benablement\b", re.I),
            6,
            "text",
        ),
        Rule(
            "deployment_implementation",
            re.compile(r"\bdeploy(ment|ing|ed)?\b|\bimplementation\b", re.I),
            5,
            "either",
        ),
        Rule("support_delivery", re.compile(r"\bsupport delivery\b|\bservice delivery\b", re.I), 4, "either"),
        Rule(
            "post_sales",
            re.compile(r"\bpost[- ]sales\b|\bpost sales\b|\bcustomer success\b", re.I),
            4,
            "either",
        ),
        Rule("stakeholder_exec", re.compile(r"\bstakeholder(s)?\b|\bexecutive\b|\bC-?level\b", re.I), 2, "text"),
        Rule("enterprise_strategic", re.compile(r"\benterprise\b|\bstrategic\b|\bkey account\b", re.I), 1, "text"),
        Rule("customer_facing", re.compile(r"\bcustomer-?facing\b|\bexternal\b clients?\b", re.I), 2, "text"),
        Rule("consultative_advisory", re.compile(r"\badvis(e|ory)\b|\bconsult(ing|ative)\b", re.I), 1, "text"),
        Rule(
            "discovery_requirements",
            re.compile(r"\bdiscovery\b|\bneeds assessment\b|\brequirements gathering\b", re.I),
            1,
            "text",
        ),
        Rule("integrations_apis", re.compile(r"\bintegration(s)?\b|\bAPI(s)?\b|\bSDK\b", re.I), 2, "text"),
        Rule(
            "governance_security_compliance", re.compile(r"\bgovernance\b|\bsecurity\b|\bcompliance\b", re.I), 2, "text"
        ),
        Rule(
            "renewal_retention_expansion",
            re.compile(r"\brenewal(s)?\b|\bretention\b|\bexpansion\b|\bupsell\b|\bcross-?sell\b", re.I),
            1,
            "text",
        ),
        # title-forward signals (but keep weights lower than CS/value/adoption)
        Rule("solutions_architect", re.compile(r"\bsolutions architect\b", re.I), 6, "title"),
        Rule("solutions_engineer", re.compile(r"\bsolutions engineer\b", re.I), 5, "title"),
        Rule("forward_deployed", re.compile(r"\bforward deployed\b", re.I), 3, "either"),
        Rule("program_manager", re.compile(r"\bprogram manager\b", re.I), 2, "title"),
    ]

    neg = [
        Rule("research_scientist", re.compile(r"\bresearch scientist\b|\bresearcher\b", re.I), -6, "either"),
        Rule("phd_required", re.compile(r"\bPhD\b|\bdoctoral\b", re.I), -4, "text"),
        Rule(
            "model_training_pretraining",
            re.compile(r"\bpretraining\b|\bRLHF\b|\btraining pipeline\b|\bmodel training\b", re.I),
            -4,
            "text",
        ),
        Rule(
            "compiler_kernels_cuda",
            re.compile(r"\bcompiler\b|\bkernels?\b|\bCUDA\b|\bTPU\b|\bASIC\b", re.I),
            -3,
            "text",
        ),
        Rule("theory_math_heavy", re.compile(r"\btheoretical\b|\bproof\b|\bnovel algorithm\b", re.I), -2, "text"),
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


def _blend_with_ai(heuristic_score: int, ai_payload: Optional[Dict[str, Any]]) -> int:
    """
    Blend heuristic score with AI match score when available.
    """
    if not ai_payload:
        return heuristic_score
    ai = ensure_ai_payload(ai_payload)
    ai_score = int(ai.get("match_score", 0))
    cfg = AI_BLEND_CONFIG

    # Centralized controls (disabled by default to preserve historical behavior).
    base = heuristic_score
    if cfg.min_heuristic_floor is not None:
        base = max(base, int(cfg.min_heuristic_floor))

    blended = int(round((1 - cfg.weight) * base + cfg.weight * ai_score))

    if cfg.max_ai_contribution is not None:
        cap = int(cfg.max_ai_contribution)
        delta = blended - base
        if delta > cap:
            blended = base + cap
        elif delta < -cap:
            blended = base - cap

    return blended


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

    if has_any(
        [
            "customer success",
            "csm",
            "success plan",
            "value realization",
            "adoption",
            "onboarding",
            "retention",
            "renewal",
            "deployment and adoption",
            "ai deployment",
            "support delivery",
        ]
    ):
        return "CS_CORE"

    if has_any(
        [
            "program manager",
            "delivery lead",
            "enablement",
            "engagement",
            "operations",
            "gtm",
            "go to market",
            "account director",
            "partner",
            "alliances",
        ]
    ):
        return "CS_ADJACENT"

    if has_any(
        [
            "solutions architect",
            "solutions engineer",
            "forward deployed",
            "field engineer",
            "pre-sales",
            "presales",
            "sales engineer",
            "partner solutions",
        ]
    ):
        return "SOLUTIONS"

    return "OTHER"


def _title_family(title: str) -> str:
    """
    Normalize title into a family bucket for clustering.
    """
    t = _norm(title).lower()
    t = re.sub(
        r"\s*\([^)]*(remote|san francisco|new york|london|dublin|tokyo|munich|sydney)[^)]*\)\s*$", "", t, flags=re.I
    )
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
    jd_rich = (not title_only_mode) and len(text) >= 200

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

        weight = rule.weight
        if (
            rule.name
            in {
                "research_scientist",
                "phd_required",
                "model_training_pretraining",
                "compiler_kernels_cuda",
                "theory_math_heavy",
            }
            and not jd_rich
        ):
            weight = int(round(weight * 0.25))
        delta = weight * c
        base_score += delta
        hits.append({"rule": rule.name, "count": c, "delta": delta})

    for r in pos_rules:
        apply_rule(r)
    for r in neg_rules:
        apply_rule(r)

    relevance = _norm(job.get("relevance")).upper()
    if relevance == "RELEVANT":
        base_score += 10
        hits.append({"rule": "boost_relevant", "count": 1, "delta": 10})
    elif relevance == "MAYBE":
        base_score += 5
        hits.append({"rule": "boost_maybe", "count": 1, "delta": 5})
    elif relevance == "IRRELEVANT":
        base_score -= 5
        hits.append({"rule": "penalty_irrelevant", "count": 1, "delta": -5})

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
        hits.append(
            {"rule": "pin_manager_ai_deployment", "count": 1, "delta": PROFILE_WEIGHTS["pin_manager_ai_deployment"]}
        )

    # Risk penalties based on JD/text
    blob = title if title_only_mode else (title + "\n" + text)
    penalty_factor = 1.0 if jd_rich else 0.25
    if re.search(r"\bPhD\b|\bdoctoral\b", blob, re.I):
        profile_delta += int(round(PROFILE_WEIGHTS["penalty_research_heavy"] * penalty_factor))
    if re.search(r"\bcompiler\b|\bCUDA\b|\bkernels?\b|\bASIC\b|\bTPU\b", blob, re.I):
        profile_delta += int(round(PROFILE_WEIGHTS["penalty_low_level"] * penalty_factor))
    if re.search(r"\bC\+\+\b|\brust\b|\boperating systems\b|\bkernel\b", blob, re.I):
        profile_delta += int(round(PROFILE_WEIGHTS["penalty_strong_swe_only"] * penalty_factor))

    heuristic_score = int(round((base_score + profile_delta) * mult))
    final_score_raw = _blend_with_ai(heuristic_score, job.get("ai"))
    final_score = max(0, min(100, final_score_raw))

    fit_signals = _signals(blob, FIT_PATTERNS)
    risk_signals = _signals(blob, RISK_PATTERNS)

    out = dict(job)
    out["base_score"] = base_score
    out["profile_delta"] = profile_delta
    out["heuristic_score"] = heuristic_score
    out["final_score_raw"] = final_score_raw
    out["final_score"] = final_score
    out["score"] = final_score  # backward compatibility
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
        expl = j.get("explanation") or {}
        expl_summary = _norm(expl.get("explanation_summary") or "")
        rows.append(
            {
                "job_id": _norm(j.get("job_id")),
                "score": j.get("score", 0),
                "heuristic_score": j.get("heuristic_score", j.get("score", 0)),
                "final_score": j.get("final_score", j.get("score", 0)),
                "explanation_summary": expl_summary,
                "base_score": j.get("base_score", 0),
                "profile_delta": j.get("profile_delta", 0),
                "role_band": _norm(j.get("role_band")),
                "title": _norm(j.get("title")),
                "department": _norm(j.get("department") or j.get("departmentName")),
                "team": ", ".join(j.get("teamNames") or [])
                if isinstance(j.get("teamNames"), list)
                else _norm(j.get("team")),
                "location": _norm(j.get("location") or j.get("locationName")),
                "enrich_status": _norm(j.get("enrich_status")),
                "enrich_reason": _norm(j.get("enrich_reason")),
                "jd_text_chars": j.get("jd_text_chars", 0),
                "fit_signals": ", ".join(j.get("fit_signals") or []),
                "risk_signals": ", ".join(j.get("risk_signals") or []),
                "apply_url": _norm(j.get("apply_url")),
                "why_top3": top3,
            }
        )
    return rows


# ------------------------------------------------------------
# Step 5: clustering / families output
# ------------------------------------------------------------


def build_families(scored: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not scored:
        return []

    families: Dict[str, Dict[str, Any]] = {}
    variants: Dict[str, List[Tuple[Tuple[str, str, str], Dict[str, Any]]]] = {}

    for j in scored:
        fam = _norm(j.get("title_family"))
        if not fam:
            fam = _title_family(_norm(j.get("title")))
        if not fam:
            fam = _norm(j.get("title")).lower()

        variant = {
            "job_id": _norm(j.get("job_id")),
            "title": _norm(j.get("title")),
            "location": _norm(j.get("location") or j.get("locationName")),
            "apply_url": _norm(j.get("apply_url")),
            "score": j.get("score", 0),
            "role_band": _norm(j.get("role_band")),
        }
        variants.setdefault(fam, []).append((_stable_job_sort_key(j), variant))

        current_best = families.get(fam)
        if current_best is None or j.get("score", 0) > current_best.get("score", 0):
            families[fam] = dict(j)

    entries: List[Tuple[str, Dict[str, Any], List[Dict[str, Any]]]] = []
    for fam, best in families.items():
        entries.append((fam or "", best, variants.get(fam, [])))

    entries.sort(key=lambda item: (item[0], _stable_job_sort_key(item[1])))

    out: List[Dict[str, Any]] = []
    for fam, best, fam_variants in entries:
        sorted_variants = [v for _, v in sorted(fam_variants, key=lambda item: item[0])]
        entry = dict(best)
        entry["title_family"] = fam
        entry["family_variants"] = sorted_variants
        out.append(entry)
    return out


def _dedupe_jobs_for_scoring(jobs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Deterministically collapse duplicate postings by `job_id` before scoring.

    Canonical selection (deterministic, in priority order):
    1) Prefer richer description (longer jd_text/description_text/descriptionHtml/description).
    2) Prefer records with non-unavailable enrichment status (if present).
    3) Prefer records with more non-empty core fields (title/location/team/apply_url/detail_url).
    4) Prefer having an apply_url over only a detail_url.
    5) Final tiebreaker: stable JSON representation (sort_keys=True).

    Provenance:
    - Canonical record gets `duplicates`: a sorted list of the other source records' identifiers
      (apply_url/detail_url/id/applyId) to audit merges.
    """

    def _desc_len(job: Dict[str, Any]) -> int:
        text = (
            job.get("jd_text")
            or job.get("description_text")
            or job.get("descriptionHtml")
            or job.get("description")
            or ""
        )
        return len(_norm(text))

    def _core_field_count(job: Dict[str, Any]) -> int:
        fields = [
            job.get("title"),
            job.get("location") or job.get("locationName"),
            job.get("team") or job.get("department"),
            job.get("apply_url"),
            job.get("detail_url"),
        ]
        return sum(1 for v in fields if _norm(v))

    def _enrich_rank(job: Dict[str, Any]) -> int:
        s = _norm(job.get("enrich_status")).lower()
        if not s:
            return 0
        return 0 if s == "unavailable" else 1

    def _url_rank(job: Dict[str, Any]) -> int:
        return 2 if _norm(job.get("apply_url")) else (1 if _norm(job.get("detail_url")) else 0)

    def _stable_repr(job: Dict[str, Any]) -> str:
        return json.dumps(job, ensure_ascii=False, sort_keys=True, default=str)

    groups: Dict[str, List[Dict[str, Any]]] = {}
    order: List[str] = []
    for job in jobs:
        jid = _norm(job.get("job_id")) or job_identity(job)
        job["job_id"] = jid
        if jid not in groups:
            groups[jid] = []
            order.append(jid)
        groups[jid].append(job)

    out: List[Dict[str, Any]] = []
    for jid in order:
        members = groups[jid]
        if len(members) == 1:
            out.append(members[0])
            continue

        def _canonical_key(job: Dict[str, Any]):
            return (
                _desc_len(job),
                _enrich_rank(job),
                _core_field_count(job),
                _url_rank(job),
                _stable_repr(job),
            )

        canonical = max(members, key=_canonical_key)
        dup_sources: List[Dict[str, Any]] = []
        for m in members:
            if m is canonical:
                continue
            entry: Dict[str, Any] = {}
            for k in ("apply_url", "detail_url", "id", "applyId"):
                v = m.get(k)
                if _norm(v):
                    entry[k] = _norm(v)
            if entry:
                dup_sources.append(entry)

        if dup_sources:
            dup_sources.sort(key=lambda d: json.dumps(d, ensure_ascii=False, sort_keys=True, default=str))
            canonical["duplicates"] = dup_sources
        out.append(canonical)

    return out


# ------------------------------------------------------------
# Step 8: shortlist output
# ------------------------------------------------------------


def write_shortlist_md(scored: List[Dict[str, Any]], out_path: Path, min_score: int) -> None:
    def _shortlist_profile(path: Path) -> Optional[str]:
        name = path.name
        if name.startswith("openai_shortlist.") and name.endswith(".md"):
            return name[len("openai_shortlist.") : -len(".md")]
        return None

    def _truncate_note(note: str, limit: int = 160) -> str:
        trimmed = " ".join(note.split()).strip()
        if len(trimmed) <= limit:
            return trimmed
        return trimmed[: limit - 1].rstrip() + "…"

    def _load_user_state_map(profile: Optional[str]) -> Dict[str, Dict[str, Any]]:
        if not profile:
            return {}
        path = USER_STATE_DIR / f"{profile}.json"
        try:
            data = load_user_state(path)
        except Exception:
            return {}
        if isinstance(data, dict):
            if all(isinstance(v, dict) for v in data.values()):
                return {str(k): v for k, v in data.items()}
            jobs = data.get("jobs")
            if isinstance(jobs, list):
                mapping: Dict[str, Dict[str, Any]] = {}
                for item in jobs:
                    if isinstance(item, dict) and item.get("id"):
                        mapping[str(item["id"])] = item
                return mapping
        return {}

    shortlist = [
        _strip_ephemeral_fields(j)
        for j in scored
        if j.get("score", 0) >= min_score and j.get("enrich_status") != "unavailable"
    ]
    profile = _shortlist_profile(out_path)
    user_state = _load_user_state_map(profile)

    lines: List[str] = ["# OpenAI Shortlist", "", f"Min score: **{min_score}**", ""]
    for idx, job in enumerate(shortlist):
        title = _norm(job.get("title")) or "Untitled"
        score = job.get("score", 0)
        role_band = _norm(job.get("role_band"))
        apply_url = _norm(job.get("apply_url"))
        job_id = _norm(job.get("job_id"))
        identity = job_identity(job)
        status = ""
        note = ""
        if identity and identity in user_state:
            record = user_state.get(identity) or {}
            if isinstance(record, dict):
                status = _norm(record.get("status") or "")
                note = _norm(record.get("notes") or "")

        status_tag = f" [{status}]" if status else ""
        lines.append(f"## {title} — {score} [{role_band}]{status_tag}")
        if apply_url:
            lines.append(f"[Apply link]({apply_url})")
        if job_id:
            lines.append(f"(job_id: {job_id})")
        if note:
            lines.append(f"Note: {_truncate_note(note)}")

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

        if idx < 10:
            expl = job.get("explanation") or {}
            expl_summary = _norm(expl.get("explanation_summary") or "")
            if expl_summary:
                lines.append(f"**Explanation:** {expl_summary}")

        jd = _norm(job.get("jd_text"))
        if jd:
            excerpt = jd[:700] + ("…" if len(jd) > 700 else "")
            lines.append("")
            lines.append(excerpt)

        lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")


def _score_distribution(scores: List[int]) -> Dict[str, Any]:
    if not scores:
        return {
            "min": 0,
            "p50": 0,
            "p90": 0,
            "max": 0,
            "buckets": {">=90": 0, ">=80": 0, ">=70": 0, ">=60": 0},
        }
    ordered = sorted(scores)
    n = len(ordered)
    p50_idx = (n - 1) // 2
    p90_idx = max(int((0.9 * n) - 1), 0)
    buckets = {
        ">=90": sum(1 for s in ordered if s >= 90),
        ">=80": sum(1 for s in ordered if s >= 80),
        ">=70": sum(1 for s in ordered if s >= 70),
        ">=60": sum(1 for s in ordered if s >= 60),
    }
    return {
        "min": ordered[0],
        "p50": ordered[p50_idx],
        "p90": ordered[p90_idx],
        "max": ordered[-1],
        "buckets": buckets,
    }


def _format_distribution_line(dist: Dict[str, Any]) -> str:
    buckets = dist.get("buckets", {})
    return (
        f"Score distribution: min={dist.get('min')}, "
        f"p50={dist.get('p50')}, p90={dist.get('p90')}, max={dist.get('max')} "
        f"(>=90: {buckets.get('>=90', 0)}, >=80: {buckets.get('>=80', 0)}, "
        f">=70: {buckets.get('>=70', 0)}, >=60: {buckets.get('>=60', 0)})"
    )


def write_top_n_md(scored: List[Dict[str, Any]], out_path: Path, top_n: int) -> None:
    cleaned = [_strip_ephemeral_fields(j) for j in scored]
    dist = _score_distribution([int(j.get("score", 0)) for j in cleaned])
    top = cleaned[: max(0, top_n)]

    lines: List[str] = [
        "# OpenAI Top Jobs",
        "",
        f"Top N: **{top_n}**",
        "",
        _format_distribution_line(dist),
        "",
    ]
    for job in top:
        title = _norm(job.get("title")) or "Untitled"
        score = job.get("score", 0)
        role_band = _norm(job.get("role_band"))
        apply_url = _norm(job.get("apply_url"))
        job_id = _norm(job.get("job_id"))

        lines.append(f"## {title} — {score} [{role_band}]")
        if apply_url:
            lines.append(f"[Apply link]({apply_url})")
        if job_id:
            lines.append(f"(job_id: {job_id})")
        lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")


def _print_explain_top_n(scored: List[Dict[str, Any]], top_n: int) -> None:
    if top_n <= 0:
        return
    logger.info("Explain top %d (rule breakdown):", top_n)
    for job in scored[:top_n]:
        title = _norm(job.get("title")) or "Untitled"
        score = job.get("score", 0)
        apply_url = _norm(job.get("apply_url"))
        hits = job.get("score_hits") or []
        hits_sorted = sorted(hits, key=lambda h: abs(h.get("delta", 0)), reverse=True)
        breakdown = ", ".join(f"{h.get('rule')}={h.get('delta')}" for h in hits_sorted[:8])
        logger.info(" - %s | %s | %s", score, title, apply_url or "no_url")
        if breakdown:
            logger.info("   %s", breakdown)


def write_shortlist_ai_md(scored: List[Dict[str, Any]], out_path: Path, min_score: int) -> None:
    shortlist = [
        _strip_ephemeral_fields(j)
        for j in scored
        if j.get("score", 0) >= min_score and j.get("enrich_status") != "unavailable"
    ]

    lines: List[str] = ["# OpenAI Shortlist (AI Insights)", "", f"Min score: **{min_score}**", ""]
    for idx, job in enumerate(shortlist):
        title = _norm(job.get("title")) or "Untitled"
        score = job.get("score", 0)
        final_score = job.get("final_score", score)
        heuristic_score = job.get("heuristic_score", score)
        role_band = _norm(job.get("role_band"))
        apply_url = _norm(job.get("apply_url"))

        lines.append(f"## {title} — {final_score} [heuristic={heuristic_score}] [{role_band}]")
        if apply_url:
            lines.append(f"[Apply link]({apply_url})")

        ai_payload = ensure_ai_payload(job.get("ai") or {})
        lines.append(f"- Match score: {ai_payload.get('match_score', 0)}")

        skills_required = ", ".join(ai_payload.get("skills_required") or [])
        skills_preferred = ", ".join(ai_payload.get("skills_preferred") or [])
        lines.append(f"- Skills required: {skills_required or '—'}")
        lines.append(f"- Skills preferred: {skills_preferred or '—'}")

        red_flags = ai_payload.get("red_flags") or []
        if red_flags:
            lines.append("- Red flags:")
            for rf in red_flags:
                lines.append(f"  - {rf}")

        notes = ai_payload.get("notes")
        if notes:
            lines.append(f"- Notes: {notes}")

        # Add compact explanation block for the top items (deterministic)
        if idx < 10:
            expl = job.get("explanation") or {}
            if expl:
                lines.append("- Explanation:")
                lines.append(
                    f"  - final_score={expl.get('final_score')} (heuristic={expl.get('heuristic_score')}, w={expl.get('blend_weight_used')})"
                )
                lines.append(f"  - heuristic_top3={', '.join(expl.get('heuristic_reasons_top3') or []) or '—'}")
                lines.append(f"  - match_rationale={expl.get('match_rationale') or '—'}")
                miss = expl.get("missing_required_skills") or []
                lines.append(f"  - missing_required={', '.join(miss) if miss else '—'}")

        lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")


def write_application_kit_md(
    shortlist: List[Dict[str, Any]],
    out_path: Path,
    provider: AIProvider,
    cache: AICache,
) -> None:
    lines: List[str] = ["# Application Kit", ""]
    for job in shortlist:
        title = _norm(job.get("title")) or "Untitled"
        job_id = job.get("apply_url") or job.get("id") or job.get("applyId") or title
        chash = compute_content_hash(job)
        cached = cache.get(job_id, chash)
        payload = None
        if cached and isinstance(cached, dict) and cached.get("application_kit"):
            payload = cached.get("application_kit")
        if payload is None:
            try:
                payload = provider.application_kit(job)
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("application kit generation failed: %s", exc)
                payload = {
                    "resume_bullets": [f"Generation failed: {exc}"],
                    "cover_letter_points": [],
                    "interview_prompts": [],
                    "star_prompts": [],
                    "gap_plan": [],
                }
            cache.put(job_id, chash, {"application_kit": payload, "content_hash": chash})

        ai_payload = ensure_ai_payload(job.get("ai") or {})
        match_score = ai_payload.get("match_score", 0)
        summary_bullets = ai_payload.get("summary_bullets") or []
        skills_required = ai_payload.get("skills_required") or []
        skills_preferred = ai_payload.get("skills_preferred") or []

        def _take(items: List[str], n: int) -> List[str]:
            return [x for x in items if x][:n]

        def _fallback_why() -> List[str]:
            return [
                f"Relevant domain alignment for {title}.",
                "Experience collaborating with product/eng and customers.",
                "Ability to ship demos and measure value quickly.",
            ]

        why_bullets = _take(summary_bullets, 3) or _fallback_why()

        def _gap_suggestions(skills: List[str]) -> List[str]:
            take = _take(skills, 3)
            if not take:
                take = ["Advanced system design", "Performance tuning", "Security hardening"]
            out: List[str] = []
            for s in take:
                out.append(f"{s}: show via a small demo or write-up proving proficiency.")
            return out

        gap_lines = _gap_suggestions(skills_required)

        resume_bullets = payload.get("resume_bullets") or [
            f"Quantify impact aligning to {title}; highlight shipped work.",
            "Show customer-facing collaboration and iterative delivery.",
            "Emphasize measurable outcomes (latency, adoption, reliability).",
        ]

        interview_prompts = payload.get("interview_prompts") or [
            "Walk through a project where you balanced speed vs quality.",
            "Describe how you debugged a hard production issue.",
            "Explain a time you aligned stakeholders with competing goals.",
            "Share how you validated impact post-launch.",
            "Describe how you handled a security or privacy concern.",
        ]

        star_prompts = payload.get("star_prompts") or [
            "S/T: adoption gap; A: build demo + enablement; R: usage up.",
            "S/T: reliability issue; A: root-cause, fix, rollback plan; R: errors down.",
            "S/T: unclear scope; A: align, define MVP; R: on-time delivery.",
            "S/T: performance pain; A: profile/optimize; R: latency down.",
            "S/T: security risk; A: coordinate mitigation; R: risk reduced.",
        ]

        plan = payload.get("gap_plan") or [
            "Day 1: Review team charter, top risks, recent postmortems.",
            "Day 2: Map required skills vs strengths; pick top 3 gaps.",
            "Day 3: Build small demo targeting gap #1; capture baseline.",
            "Day 4: Pair review demo; apply feedback.",
            "Day 5: Add metrics/logging; draft runbook snippet.",
            "Day 6: Study gap #2; apply a fix or improvement.",
            "Day 7: Polish demo UX; rehearse walkthrough.",
            "Day 8: Add second scenario; compare metrics.",
            "Day 9: Write short retro; list next steps.",
            "Day 10: Mock customer conversation; log objections.",
            "Day 11: Address objections; update docs.",
            "Day 12: Study gap #3; integrate into demo.",
            "Day 13: Finalize artifacts (screenshots/docs).",
            "Day 14: Share internally; collect feedback.",
        ]

        location = _norm(job.get("location") or job.get("locationName") or "")
        team = _norm(job.get("team") or job.get("department") or "")

        lines.append(f"## {title}")
        lines.append(f"- Apply URL: {job.get('apply_url', '')}")
        lines.append("")
        lines.append("### Role snapshot")
        lines.append(f"- Title: {title}")
        lines.append(f"- Location: {location or '—'}")
        lines.append(f"- Team: {team or '—'}")
        lines.append("")
        lines.append("### Match summary")
        lines.append(f"- Match score: {match_score}")
        for b in why_bullets:
            lines.append(f"- Why: {b}")
        lines.append("")
        lines.append("### Skill gaps (top 3)")
        for g in gap_lines:
            lines.append(f"- {g}")
        lines.append("")
        lines.append("### Resume bullets (tailored)")
        for b in _take(resume_bullets, 5):
            lines.append(f"- {b}")
        lines.append("")
        lines.append("### Interview prep")
        lines.append("- Questions:")
        for q in _take(interview_prompts, 5):
            lines.append(f"  - {q}")
        lines.append("- STAR prompts:")
        for sp in _take(star_prompts, 5):
            lines.append(f"  - {sp}")
        lines.append("")
        lines.append("### 2-week plan (daily)")
        for day_idx, step in enumerate(plan[:14], start=1):
            text = str(step)
            # Remove any existing "Day X:" prefix to avoid duplication.
            if ":" in text and text.lower().startswith("day"):
                try:
                    text = text.split(":", 1)[1].strip()
                except Exception:
                    text = text
            lines.append(f"- Day {day_idx}: {text}")
        lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")


def is_us_or_remote_us(job: Dict[str, Any]) -> bool:
    guess = job.get("is_us_or_remote_us_guess")
    if isinstance(guess, bool):
        return guess

    normalized = normalize_location_guess(
        job.get("title"),
        job.get("location") or job.get("locationName"),
    )
    if normalized["us_guess_reason"] != "none":
        return normalized["is_us_or_remote_us_guess"]

    loc = (job.get("location") or job.get("locationName") or "").strip().lower()

    # allow remote only if explicitly US
    if "remote" in loc:
        return "us" in loc or "united states" in loc

    # common non-US markers to exclude
    non_us_markers = [
        "london",
        "uk",
        "united kingdom",
        "dublin",
        "ireland",
        "tokyo",
        "japan",
        "munich",
        "germany",
        "sydney",
        "australia",
        "emea",
        "apac",
        "singapore",
        "paris",
        "france",
        "canada",
    ]
    if any(x in loc for x in non_us_markers):
        return False

    # If it isn't clearly non-US and isn't remote, assume it's US (works well for SF/NYC/DC etc)
    return bool(loc)


# ------------------------------------------------------------
# Main
# ------------------------------------------------------------


def main() -> int:
    if not logging.getLogger().hasHandlers():
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    ap = argparse.ArgumentParser()

    ap.add_argument("--profile", default="cs")
    ap.add_argument("--profiles", default="config/profiles.json")
    ap.add_argument("--in_path", default=str(ENRICHED_JOBS_JSON))
    ap.add_argument(
        "--prefer_ai",
        action="store_true",
        help="If set, and --in_path is the default enriched path, prefer AI-enriched input when present.",
    )

    ap.add_argument("--out_json", default=str(ranked_jobs_json("cs")))
    ap.add_argument("--out_csv", default=str(ranked_jobs_csv("cs")))
    ap.add_argument("--out_families", default=str(ranked_families_json("cs")))
    ap.add_argument("--out_md", default=str(shortlist_md("cs")))
    ap.add_argument(
        "--out_md_top_n",
        default="",
        help="Top N markdown output path (always written if provided).",
    )
    ap.add_argument("--top_n", type=int, default=25, help="Number of jobs to include in Top N markdown output.")
    ap.add_argument(
        "--out_md_ai",
        default="",
        help="AI-aware shortlist markdown output",
    )
    ap.add_argument(
        "--out_app_kit",
        default=str(shortlist_md("cs").with_name("openai_application_kit.cs.md")),
        help="Application kit markdown output",
    )

    ap.add_argument("--min_score", type=int, default=40)
    ap.add_argument(
        "--shortlist_score",
        type=int,
        default=None,
        help="Deprecated: use --min_score instead.",
    )
    ap.add_argument("--us_only", action="store_true")
    ap.add_argument("--app_kit", action="store_true", help="Generate application kit for shortlisted jobs.")
    ap.add_argument(
        "--ai_live", action="store_true", help="Use live AI provider for application kit (requires OPENAI_API_KEY)."
    )
    ap.add_argument(
        "--explain_top", type=int, default=0, help="Print a TSV debug report for the top N jobs (output-only)."
    )
    ap.add_argument(
        "--explain_top_n",
        type=int,
        default=0,
        help="Print top N jobs with score breakdown (rule deltas).",
    )
    ap.add_argument(
        "--family_counts",
        action="store_true",
        help="Print a TSV frequency table of role_family for the ranked list (output-only).",
    )
    args = ap.parse_args()
    if args.shortlist_score is not None:
        args.min_score = args.shortlist_score

    # ---- HARDEN OUTPUT PATHS ----
    out_json = Path(args.out_json)
    out_csv = Path(args.out_csv)
    out_families = Path(args.out_families)
    out_md = Path(args.out_md)
    out_md_top_n = Path(args.out_md_top_n) if args.out_md_top_n else None
    if args.out_md_ai:
        out_md_ai = Path(args.out_md_ai)
    else:
        base_md = out_md
        out_md_ai = base_md.with_name(f"{base_md.stem}_ai{base_md.suffix}") if base_md else None
    out_app_kit = Path(args.out_app_kit) if args.out_app_kit else None

    for p in (
        [out_json, out_csv, out_families, out_md]
        + ([out_md_top_n] if out_md_top_n else [])
        + ([out_md_ai] if out_md_ai else [])
        + ([out_app_kit] if out_app_kit else [])
    ):
        if "<function " in str(p):
            raise SystemExit(f"Refusing invalid output path (looks like function repr): {p}")

    for p in (
        [out_json, out_csv, out_families, out_md]
        + ([out_md_top_n] if out_md_top_n else [])
        + ([out_md_ai] if out_md_ai else [])
        + ([out_app_kit] if out_app_kit else [])
    ):
        p.parent.mkdir(parents=True, exist_ok=True)
    # ----------------------------

    profiles = load_profiles(args.profiles)
    apply_profile(args.profile, profiles)

    ai_input = ENRICHED_JOBS_JSON.with_name("openai_enriched_jobs_ai.json")
    requested_in = Path(args.in_path)
    if args.prefer_ai:
        if requested_in == ENRICHED_JOBS_JSON:
            if ai_input.exists():
                in_path = ai_input
                logger.info("Using AI-enriched input %s (prefer_ai)", in_path)
            else:
                raise SystemExit(
                    f"Input not found: {ai_input}. Prefer-ai was requested; ensure it exists or omit --prefer_ai."
                )
        else:
            logger.info("Prefer-ai requested but --in_path is custom (%s); using requested path.", requested_in)
            in_path = requested_in
    else:
        in_path = requested_in

    if not in_path.exists():
        raise SystemExit(f"Input not found: {in_path}")

    jobs = json.loads(in_path.read_text(encoding="utf-8"))
    if not isinstance(jobs, list):
        raise SystemExit("Input JSON must be a list of jobs")

    us_only_fallback: Optional[Dict[str, Any]] = None
    if args.us_only:

        def _has_location_signal(job: Dict[str, Any]) -> bool:
            if job.get("location") or job.get("locationName") or job.get("location_norm"):
                return True
            if isinstance(job.get("is_us_or_remote_us_guess"), bool):
                return True
            normalized = normalize_location_guess(
                job.get("title"),
                job.get("location") or job.get("locationName"),
            )
            return normalized["us_guess_reason"] != "none"

        if not any(_has_location_signal(j) for j in jobs):
            logger.info("US-only filter skipped (no location signals in input).")
        else:
            before = len(jobs)
            unfiltered_jobs = jobs
            filtered_jobs = [j for j in jobs if is_us_or_remote_us(j)]
            after = len(filtered_jobs)
            logger.info(f"US-only filter: {before} -> {after} jobs")
            if before > 0 and after == 0:
                logger.warning(
                    "US-only filter removed all jobs (input=%d, after=%d). "
                    "Falling back to unfiltered set because locations likely aren't normalized "
                    "(common with --no_enrich). If you ran with --no_enrich, did you pass labeled input "
                    "instead of enriched?",
                    before,
                    after,
                )
                jobs = unfiltered_jobs
                us_only_fallback = {
                    "input_count": before,
                    "post_filter_count": after,
                    "fallback_applied": True,
                    "reason": "us_only_filter_removed_all_jobs",
                    "note": "Fallback to unfiltered set; locations likely aren't normalized (common with --no_enrich).",
                }
            else:
                jobs = filtered_jobs
        logger.info("US-only kept jobs by reason: %s", _format_us_only_reason_summary(jobs))

    jobs = _dedupe_jobs_for_scoring(jobs)

    pos_rules, neg_rules = _compile_rules()
    scored = [score_job(j, pos_rules, neg_rules) for j in jobs]
    candidate_skills = _candidate_skill_set()
    for j in scored:
        j["explanation"] = _build_explanation(j, candidate_skills)
        j["content_fingerprint"] = content_fingerprint(j)
    # Stable sort: primary by score desc, secondary by job identity (apply_url/detail_url/title/location)
    scored.sort(key=lambda x: (-x.get("score", 0), x.get("job_id") or job_identity(x)))
    _print_explain_top(scored, int(args.explain_top or 0))
    _print_explain_top_n(scored, int(args.explain_top_n or 0))
    if args.family_counts:
        _print_family_counts(scored)

    raw_scores = [int(j.get("final_score_raw", j.get("score", 0)) or 0) for j in scored]
    dist_raw = _score_distribution(raw_scores)
    dist = _score_distribution([int(j.get("score", 0)) for j in scored])
    logger.info("Scoring summary: total=%d", len(scored))
    if dist_raw["max"] != dist["max"]:
        logger.info("Scores max: pre-clamp=%d post-clamp=%d", dist_raw["max"], dist["max"])
    logger.info(
        "Scores: min=%d p50=%d p90=%d max=%d",
        dist["min"],
        dist["p50"],
        dist["p90"],
        dist["max"],
    )
    logger.info(
        "Buckets: >=90=%d >=80=%d >=70=%d >=60=%d",
        dist["buckets"][">=90"],
        dist["buckets"][">=80"],
        dist["buckets"][">=70"],
        dist["buckets"][">=60"],
    )
    logger.info("Shortlist threshold: %d", args.min_score)
    logger.info("Top 10 jobs:")
    for job in scored[:10]:
        title = _norm(job.get("title")) or "Untitled"
        score = job.get("score", 0)
        apply_url = _norm(job.get("apply_url"))
        logger.info(" - %s | %s | %s", score, title, apply_url or "no_url")

    sanitized_scored = [_strip_ephemeral_fields(j) for j in scored]
    ranked_scored = sorted(sanitized_scored, key=_ranked_sort_key)

    atomic_write_text(out_json, _serialize_json(ranked_scored))
    if us_only_fallback:
        meta_payload = {"us_only_fallback": us_only_fallback}
        atomic_write_text(_score_meta_path(out_json), _serialize_json(meta_payload))

    rows = to_csv_rows(ranked_scored)

    def _write_csv(tmp_path: Path) -> None:
        with tmp_path.open("w", encoding="utf-8", newline="") as f:
            if rows:
                w = csv.DictWriter(
                    f,
                    fieldnames=CSV_FIELDNAMES,
                    extrasaction="ignore",
                    lineterminator="\n",
                )
                w.writeheader()
                w.writerows(rows)

    atomic_write_with(out_csv, _write_csv)

    families = build_families(ranked_scored)
    atomic_write_text(out_families, _serialize_json(families))

    shortlist_content: str
    shortlist_buffer = io.StringIO()
    shortlist = [
        _strip_ephemeral_fields(j)
        for j in scored
        if j.get("score", 0) >= args.min_score and j.get("enrich_status") != "unavailable"
    ]

    lines: List[str] = ["# OpenAI Shortlist", "", f"Min score: **{args.min_score}**", ""]
    for job in shortlist:
        title = _norm(job.get("title")) or "Untitled"
        score = job.get("score", 0)
        role_band = _norm(job.get("role_band"))
        apply_url = _norm(job.get("apply_url"))
        job_id = _norm(job.get("job_id"))

        lines.append(f"## {title} — {score} [{role_band}]")
        if apply_url:
            lines.append(f"[Apply link]({apply_url})")
        if job_id:
            lines.append(f"(job_id: {job_id})")

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

    shortlist_content = "\n".join(lines)
    atomic_write_text(out_md, shortlist_content)

    if out_md_top_n:
        write_top_n_md(scored, out_md_top_n, int(args.top_n))
    if out_md_ai:
        write_shortlist_ai_md(scored, out_md_ai, args.min_score)
    if args.app_kit and out_app_kit:
        provider = _select_ai_provider(args.ai_live)
        cache = _select_ai_cache()
        write_application_kit_md(shortlist, out_app_kit, provider, cache)

    logger.info(f"Wrote ranked JSON     : {out_json}")
    logger.info(f"Wrote ranked CSV      : {out_csv}")
    logger.info(f"Wrote ranked families : {out_families}")
    logger.info(f"Wrote shortlist MD    : {out_md} (score >= {args.min_score})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
