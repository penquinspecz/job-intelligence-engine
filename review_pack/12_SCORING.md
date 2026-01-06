# Scoring & Profiles
Included: scoring logic excerpts from `scripts/score_jobs.py` (rules, role bands, apply_profile, main I/O) and `config/profiles.json`.

Why they matter: define how jobs are scored, weighted per profile, and outputs produced.

Omitted: none (full relevant sections below).

## scripts/score_jobs.py (scoring core + CLI)
```
from __future__ import annotations

import argparse
import csv
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ji_engine.config import (
    ENRICHED_JOBS_JSON,
    LABELED_JOBS_JSON,
    ranked_families_json,
    ranked_jobs_csv,
    ranked_jobs_json,
    shortlist_md,
)

logger = logging.getLogger(__name__)

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
```

### Tunables and rules
```
ROLE_BAND_MULTIPLIERS: Dict[str, float] = {
    "CS_CORE": 1.25,
    "CS_ADJACENT": 1.15,
    "SOLUTIONS": 1.05,
    "OTHER": 0.95,
}

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
```

### Role band classification (excerpt)
```
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
```

### CLI defaults (paths centralized via config)
```
ap.add_argument("--profile", default="cs")
ap.add_argument("--profiles", default="config/profiles.json")
ap.add_argument("--in_path", default=str(ENRICHED_JOBS_JSON))
ap.add_argument("--out_json", default=str(ranked_jobs_json("cs")))
ap.add_argument("--out_csv", default=str(ranked_jobs_csv("cs")))
ap.add_argument("--out_families", default=str(ranked_families_json("cs")))
ap.add_argument("--out_md", default=str(shortlist_md("cs")))
```

## config/profiles.json
```
{
  "cs": {
    "role_band_multipliers": {
      "CS_CORE": 1.25,
      "CS_ADJACENT": 1.15,
      "SOLUTIONS": 1.05,
      "OTHER": 0.95
    },
    "profile_weights": {
      "boost_cs_core": 15,
      "boost_cs_adjacent": 5,
      "boost_solutions": 2,
      "penalty_research_heavy": -8,
      "penalty_low_level": -5,
      "penalty_strong_swe_only": -4,
      "pin_manager_ai_deployment": 30
    }
  },
  "tam": {
    "role_band_multipliers": {
      "CS_CORE": 1.25,
      "CS_ADJACENT": 1.20,
      "SOLUTIONS": 1.00,
      "OTHER": 0.90
    },
    "profile_weights": {
      "boost_cs_core": 14,
      "boost_cs_adjacent": 8,
      "boost_solutions": 1,
      "penalty_research_heavy": -8,
      "penalty_low_level": -5,
      "penalty_strong_swe_only": -4,
      "pin_manager_ai_deployment": 15
    }
  },
  "se": {
    "role_band_multipliers": {
      "CS_CORE": 1.10,
      "CS_ADJACENT": 1.05,
      "SOLUTIONS": 1.20,
      "OTHER": 0.95
    },
    "profile_weights": {
      "boost_cs_core": 8,
      "boost_cs_adjacent": 4,
      "boost_solutions": 10,
      "penalty_research_heavy": -8,
      "penalty_low_level": -5,
      "penalty_strong_swe_only": -4,
      "pin_manager_ai_deployment": 10
    }
  }
}
```

