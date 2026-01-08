from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple


RULES_VERSION = "2025-01-AI-EXTRACT-4"
_WS_RE = re.compile(r"\s+")


def _norm_text(s: str) -> str:
    return _WS_RE.sub(" ", (s or "")).strip().lower()


def _job_text(job: Dict[str, Any]) -> str:
    parts: List[str] = []
    for k in ("title", "team", "department", "location", "locationName"):
        v = job.get(k)
        if isinstance(v, str) and v.strip():
            parts.append(v.strip())
    for k in ("jd_text", "description_text", "description", "text"):
        v = job.get(k)
        if isinstance(v, str) and v.strip():
            parts.append(v.strip())
    return _norm_text("\n".join(parts))


def _contains(text: str, patterns: List[str]) -> bool:
    for p in patterns:
        if re.search(p, text, flags=re.IGNORECASE):
            return True
    return False


# Keep this small and high-signal; order is the deterministic output order.
_SKILL_PATTERNS: List[Tuple[str, List[str]]] = [
    ("Robotics", [r"\brobotics\b", r"\brobot\b", r"\bmechatronics\b", r"\bworkcell\b", r"\bmanipulator\b"]),
    ("Embedded Systems", [r"\bembedded\b", r"\bfirmware\b", r"\bmcu\b", r"\brtos\b"]),
    ("Controls", [r"\bcontrols\b", r"\bplc\b", r"\bmotion control\b", r"\bpid\b"]),
    ("Electromechanical", [r"\belectromechanical\b", r"\bactuator\b", r"\bwire harness\b", r"\bservo\b", r"\bmotor\b"]),
    ("CAD", [r"\bcad\b", r"\bcomputer aided design\b", r"\bsolidworks\b", r"\bfusion\s*360\b"]),
    ("Automation", [r"\bautomation\b", r"\bautomated\b", r"\bautomation stack\b"]),
    ("Troubleshooting", [r"\btroubleshoot(?:ing)?\b", r"\bdebug\b", r"\btriage\b", r"\blogs?\b"]),
    ("Test Automation", [r"\btest automation\b", r"\bvalidation\b", r"\bqualification\b", r"\bqualify\b"]),
    ("Python", [r"\bpython\b"]),
    ("Linux", [r"\blinux\b"]),
    ("SQL", [r"\bsql\b"]),
    ("Kubernetes", [r"\bkubernetes\b", r"\bk8s\b"]),
    ("Terraform", [r"\bterraform\b"]),
    ("AWS", [r"\baws\b", r"\bamazon web services\b"]),
    ("GCP", [r"\bgcp\b", r"\bgoogle cloud\b"]),
    ("Azure", [r"\bazure\b"]),
    ("Docker", [r"\bdocker\b"]),
    ("Networking", [r"\bnetworking\b", r"\btcp\b", r"\bhttp\b"]),
    ("Observability", [r"\bobservability\b", r"\bmetrics\b", r"\btracing\b", r"\blogging\b"]),
    ("LLMs", [r"\bllm\b", r"\bllms\b", r"\blarge language model\b"]),
    ("RAG", [r"\brag\b", r"\bretrieval[- ]augmented\b"]),
    ("Prompting", [r"\bprompt\b", r"\bprompting\b", r"\bprompt engineering\b"]),
    ("APIs", [r"\bapi\b", r"\bapis\b", r"\brest\b"]),
    ("Security", [r"\bsecurity\b", r"\bthreat\b", r"\bprivacy\b"]),
    # Business / Customer Success (gated; see _CS_TRIGGER_PATTERNS)
    ("Adoption", [r"\badoption\b", r"\bactivation\b", r"\bactivate\b"]),
    ("Onboarding", [r"\bonboarding\b"]),
    ("Enablement", [r"\benablement\b", r"\btraining\b", r"\bplaybooks?\b"]),
    ("Change Management", [r"\bchange management\b"]),
    ("Stakeholder Management", [r"\bstakeholders?\b", r"\bexecutive\b", r"\bc-?level\b", r"\bsponsors?\b"]),
    ("Value Measurement", [r"\broi\b", r"\btco\b", r"\bkpis?\b", r"\bdashboards?\b", r"\bvalue reports?\b", r"\bbusiness outcomes?\b"]),
    ("Implementation", [r"\bimplementation\b", r"\bdeploy(?:ment|ing)?\b", r"\bintegration\b", r"\bconnectors?\b", r"\bcustom gpts?\b"]),
    ("Program Management", [r"\bprogram management\b", r"\boperating model\b", r"\boperating rhythms?\b", r"\boperating mechanisms?\b"]),
    ("Renewals", [r"\brenewals?\b", r"\bretention\b", r"\bexpansion\b"]),
]

_HW_TRIGGER_PATTERNS: List[str] = [
    r"\brobotics?\b",
    r"\bmechatronics?\b",
    r"\bworkcell\b",
    r"\bembedded\b",
    r"\bfirmware\b",
    r"\bmcu\b",
    r"\brtos\b",
    r"\bplc\b",
    r"\bmotion control\b",
    r"\bactuator\b",
    r"\bwire harness\b",
    r"\bservo\b",
    r"\bmotor\b",
    r"\bsensor\b",
    r"\bcad\b",
    r"\bsolidworks\b",
    r"\bfusion\s*360\b",
]

_GATED_HW_SKILLS = {"Robotics", "Embedded Systems", "Controls", "Electromechanical", "CAD", "Automation"}

# CS/business skills should only appear when there are explicit customer-success / adoption / value signals.
_CS_TRIGGER_PATTERNS: List[str] = [
    r"\bcustomer success\b",
    r"\bvalue realization\b",
    r"\badoption\b",
    r"\bonboarding\b",
    r"\benablement\b",
    r"\bchange management\b",
    r"\bpost[- ]sales\b",
    r"\bprofessional services\b",
    r"\brenewals?\b",
    r"\bretention\b",
    r"\broi\b",
    r"\btco\b",
    r"\bkpis?\b",
    r"\bqbrs?\b",
]

_GATED_CS_SKILLS = {
    "Adoption",
    "Onboarding",
    "Enablement",
    "Change Management",
    "Stakeholder Management",
    "Value Measurement",
    "Implementation",
    "Program Management",
    "Renewals",
}


def _hw_trigger_count(text: str) -> int:
    found = 0
    for p in _HW_TRIGGER_PATTERNS:
        if re.search(p, text, flags=re.IGNORECASE):
            found += 1
    return found


def _section_slices(text: str) -> Tuple[str, str, str]:
    """
    Roughly split JD into required/preferred/other sections based on headings/markers.
    Deterministic and intentionally simple.
    """
    t = text
    # common markers
    markers = [
        ("required", ["requirements", "required qualifications", "must have", "you will", "what you’ll do"]),
        ("preferred", ["preferred qualifications", "nice to have", "bonus", "preferred"]),
    ]

    def _find_any(needles: List[str]) -> int:
        idxs = [t.find(n) for n in needles if t.find(n) != -1]
        return min(idxs) if idxs else -1

    req_idx = _find_any([m for m in markers[0][1]])
    pref_idx = _find_any([m for m in markers[1][1]])

    if req_idx == -1 and pref_idx == -1:
        return "", "", t

    if req_idx != -1 and (pref_idx == -1 or req_idx < pref_idx):
        req = t[req_idx : pref_idx if pref_idx != -1 else None]
        pref = t[pref_idx:] if pref_idx != -1 else ""
        other = t[:req_idx]
        return req, pref, other

    # preferred appears first
    pref = t[pref_idx : req_idx if req_idx != -1 else None]
    req = t[req_idx:] if req_idx != -1 else ""
    other = t[:pref_idx]
    return req, pref, other


def _skills_from_text(text: str) -> List[str]:
    out: List[str] = []
    hw_triggers = _hw_trigger_count(text)
    cs_triggered = _contains(text, _CS_TRIGGER_PATTERNS)
    for skill, pats in _SKILL_PATTERNS:
        if skill in _GATED_HW_SKILLS and hw_triggers < 1:
            continue
        if skill in _GATED_CS_SKILLS and not cs_triggered:
            continue
        if _contains(text, pats):
            out.append(skill)
    return out


def _role_family(title_text: str, job_text: str) -> str:
    """
    Deterministic precedence list. Some families are TITLE-only to avoid JD-text false positives.
    """
    title = title_text or ""

    # TITLE-only business families / explicit mapping
    if re.search(r"\bvalue realization\b", title, flags=re.IGNORECASE):
        return "Customer Success"
    if re.search(r"\bcustomer success\b|\bcs\b", title, flags=re.IGNORECASE):
        return "Customer Success"
    # If team/dept/JD explicitly says Customer Success, treat as Customer Success before generic "product" matches.
    if _contains(job_text, [r"\bcustomer success\b", r"\bai deployment\b", r"\bdeployment and adoption\b", r"\bdeployment & adoption\b"]):
        return "Customer Success"

    rules = [
        # Explicit precedence list. Keep "Forward Deployed" explicit-only.
        ("Solutions Architect", [r"\bsolutions architect\b", r"\bsolution architect\b", r"\bpresales\b", r"\bsales engineer\b"]),
        ("Forward Deployed", [r"\bforward deployed\b", r"\bforward-deployed\b"]),
        ("Robotics", [r"\brobotics?\b", r"\bmechatronics?\b", r"\bembedded\b", r"\bfirmware\b", r"\bplc\b", r"\bmotion control\b"]),
        ("Product", [r"\bproduct manager\b", r"\bproduct lead\b", r"\bproduct\b"]),
        ("Engineering", [r"\bsoftware engineer\b", r"\bengineer\b", r"\bdeveloper\b"]),
        ("G&A", [r"\bfinance\b", r"\blegal\b", r"\bpeople\b", r"\bhr\b", r"\brecruit\b"]),
    ]
    for name, pats in rules:
        if _contains(job_text, pats):
            return name

    # Field is TITLE-only (do not trigger on JD text like "field feedback/signal").
    if re.search(r"\bfield\s+(engineer|service|technician)\b", title, flags=re.IGNORECASE):
        return "Field"
    if re.search(r"\btest\s+engineer\b", title, flags=re.IGNORECASE):
        return "Field"

    return ""


def _seniority_from_title(title: str) -> str:
    """
    Seniority is TITLE-first and TITLE-only to avoid false positives from JD text
    (e.g., "operations staff").
    """
    t = (title or "").lower()
    if re.search(r"\b(manager|director|vp|head of)\b", t):
        return "Manager"
    if re.search(r"\b(principal|staff)\b", t):
        return "Staff"
    if re.search(r"\b(senior|sr\.?)\b", t):
        return "Senior"
    if re.search(r"\blead\b", t):
        return "Senior"
    return "IC"


def _red_flags(job_text: str) -> List[str]:
    flags: List[str] = []
    if _contains(job_text, [r"\bclearance\b", r"\bts/sci\b", r"\btop secret\b"]):
        flags.append("Security clearance required")
    if _contains(job_text, [r"\brelocation\b", r"\bmust relocate\b"]):
        flags.append("Relocation required")
    # travel %
    m = re.search(r"travel\s+(up to\s+)?(\d{1,2})\s*%", job_text)
    if m:
        flags.append(f"Travel up to {m.group(2)}%")
    elif _contains(job_text, [r"\btravel\b"]):
        # keep generic if % not specified
        flags.append("Travel required")
    if _contains(job_text, [r"\bon[- ]?call\b"]):
        flags.append("On-call rotation")
    if _contains(job_text, [r"\bshift\b", r"\bnight\b", r"\bweekend\b"]):
        flags.append("Shift/weekend coverage")
    return flags


def extract_ai_fields(job: Dict[str, Any]) -> Dict[str, Any]:
    """
    Deterministic, offline extraction of AI payload fields from job text.
    Intended to backfill/augment provider outputs in stub mode.
    """
    text = _job_text(job)
    title_only = _norm_text(str(job.get("title") or ""))
    req_section, pref_section, other_section = _section_slices(text)

    req_skills = _skills_from_text(req_section) or _skills_from_text(text)
    pref_skills = _skills_from_text(pref_section)

    # Remove duplicates between required/preferred while preserving order.
    req_set = set(req_skills)
    pref_skills = [s for s in pref_skills if s not in req_set]

    return {
        "skills_required": req_skills,
        "skills_preferred": pref_skills,
        "role_family": _role_family(title_only, text),
        "seniority": _seniority_from_title(title_only),
        "red_flags": _red_flags(text),
        "rules_version": RULES_VERSION,
    }


__all__ = ["extract_ai_fields"]


