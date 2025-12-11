"""
Improved relevance scoring for job titles based on candidate profile.
Uses weighted scoring, location gating, and negative filters to reduce false positives.
"""

from typing import List, Dict, Any
from ji_engine.models import RawJobPosting
from ji_engine.profile_loader import CandidateProfile


def _location_is_valid_us(job: RawJobPosting, profile: CandidateProfile) -> bool:
    loc = (job.location or "").lower()
    if not loc:
        return True  # unknown → don't auto-reject

    # Hard reject clearly non-US
    foreign_markers = [
        "tokyo", "japan", "india", "sydney", "australia",
        "dublin", "london", "uk", "singapore", "paris",
        "berlin", "amsterdam", "zurich", "hong kong"
    ]
    if any(f in loc for f in foreign_markers):
        return False

    # Very rough US markers
    us_markers = ["united states", "us", "u.s.", "usa", "new york", "san francisco", "austin", "seattle", "remote"]
    if any(m in loc for m in us_markers):
        return True

    # If it's not obviously foreign, treat as maybe-US
    return True


def score_title_relevance(job: RawJobPosting, profile: CandidateProfile) -> str:
    """
    Returns: 'RELEVANT', 'MAYBE', 'IRRELEVANT'

    Priority:
      1) CS / AI deployment / adoption / value / CSM / TAM (US / Remote / NYC)
      2) Solutions Architect / Solutions Engineer / Forward Deployed / Partner Engineer (US / Remote / NYC)
      3) Adjacent TPM / GTM as MAYBE
    """
    title = (job.title or "").lower()
    loc_field = (job.location or "").lower()
    # Some locations are baked into the title text, so combine them
    location_text = f"{job.title or ''} {job.location or ''}".lower()

    # ---- 1. HARD LOCATION FILTER ----
    foreign_markers = [
        "tokyo", "japan", "india", "delhi",
        "sydney", "australia",
        "dublin", "london", "uk", "united kingdom",
        "singapore", "paris", "berlin",
        "amsterdam", "zurich", "hong kong"
    ]
    if any(f in location_text for f in foreign_markers):
        return "IRRELEVANT"

    # ---- 2. HARD KILL WORDS ----
    kill_words = [
        "audiovisual", "a/v", "events engineer",
        "it support", "helpdesk", "desktop support",
        "technician", "datacenter technician",
        "payroll", "legal", "counsel",
        "security guard",
        "intern", "university", "residency",
        "hr", "talent", "recruiter",
        "account executive", "sales development", "seller"
    ]
    if any(kw in title for kw in kill_words):
        return "IRRELEVANT"

    # Profile-defined anti-patterns
    for ap in profile.preferences.anti_patterns:
        words = [w for w in ap.lower().split() if len(w) > 3]
        if any(w in title for w in words):
            return "IRRELEVANT"

    score = 0

    # ---- 3. ROLE / TYPE SCORING ----
    # Tier A: CS / deployment / adoption / value / TAM / CSM
    cs_terms = [
        "customer success", "ai deployment", "ai adoption",
        "deployment manager", "adoption manager",
        "value realization", "value realisation",
        "csm", "customer success manager",
        "technical account manager", "tam",
        "customer engineer", "customer engineering"
    ]
    if any(t in title for t in cs_terms):
        score += 15

    # Tier B: solutions / forward deployed / partner engineer
    sa_terms = [
        "solutions architect", "solution architect",
        "solutions engineer", "solution engineer",
        "forward deployed", "forward-deployed",
        "partner engineer", "field engineer"
    ]
    has_sa = any(t in title for t in sa_terms)
    if has_sa:
        score += 10

    # Tier C: adjacent leadership / TPM / GTM-ish
    tpm_terms = [
        "program manager", "technical program manager",
        "tpm", "product operations", "g tm", "go-to-market"
    ]
    if any(t in title for t in tpm_terms):
        score += 5

    # ---- 4. SENIORITY & CONTEXT MODIFIERS ----
    seniority_terms = ["senior", "sr.", "lead", "principal", "manager", "director"]
    if any(s in title for s in seniority_terms):
        score += 3

    # Penalize pure SWE / DS without customer angle
    if "software engineer" in title or "backend engineer" in title or "full stack engineer" in title:
        if not has_sa and not any(t in title for t in cs_terms):
            score -= 6

    if "data scientist" in title or "data science" in title or "research scientist" in title:
        score -= 6

    # ---- 5. LOCATION PREFERENCE BONUSES ----
    # Strong preference for remote & NYC, but open to general US.
    if "remote" in location_text:
        score += 6
    if "new york" in location_text:
        score += 5

    # Rough US markers (doesn't hard-gate, just nudge)
    us_markers = ["united states", "us ", " u.s.", " usa", "san francisco", "austin", "seattle", "chicago"]
    if any(m in location_text for m in us_markers):
        score += 2

    # ---- 6. SA OVERRIDE FOR US-BASED ROLES ----
    # If it's a Solutions/Forward-Deployed style role and looks US-based, treat as relevant even if score is a bit lower.
    if has_sa and score >= 12:
        return "RELEVANT"

    # ---- 7. FINAL DECISION ----
    if score >= 18:
        return "RELEVANT"
    elif score >= 10:
        return "MAYBE"
    else:
        return "IRRELEVANT"


def label_jobs(jobs: List[RawJobPosting], profile: CandidateProfile) -> List[Dict[str, Any]]:
    """Return labeled jobs with relevance tags."""
    return [
        {
            "title": job.title,
            "apply_url": job.apply_url,
            "location": job.location,
            "relevance": score_title_relevance(job, profile),
        }
        for job in jobs
    ]
