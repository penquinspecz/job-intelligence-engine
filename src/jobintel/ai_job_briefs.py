from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ji_engine.config import REPO_ROOT, RUN_METADATA_DIR, STATE_DIR
from ji_engine.utils.content_fingerprint import content_fingerprint
from ji_engine.utils.job_identity import job_identity
from ji_engine.utils.time import utc_now_z

logger = logging.getLogger(__name__)

PROMPT_VERSION = "job_briefs_v1"
PROMPT_PATH = REPO_ROOT / "docs" / "prompts" / "job_briefs_v1.md"


def _utcnow_iso() -> str:
    return utc_now_z(seconds_precision=True)


def _sanitize_run_id(run_id: str) -> str:
    return run_id.replace(":", "").replace("-", "").replace(".", "")


def _run_dir(run_id: str) -> Path:
    return RUN_METADATA_DIR / _sanitize_run_id(run_id)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_path(path: Path) -> Optional[str]:
    if not path.exists():
        return None
    return _sha256_bytes(path.read_bytes())


def _load_prompt(path: Path) -> Tuple[str, str]:
    if not path.exists():
        raise FileNotFoundError(f"Prompt template not found: {path}")
    text = path.read_text(encoding="utf-8")
    return text, _sha256_bytes(text.encode("utf-8"))


def _load_ranked(path: Path) -> List[Dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    if isinstance(data, list):
        return data
    return []


def _profile_hash(path: Path) -> str:
    if not path.exists():
        return "missing"
    return _sha256_bytes(path.read_bytes())


def _job_id(job: Dict[str, Any]) -> str:
    return str(job.get("job_id") or job.get("apply_url") or job_identity(job))


def _jd_hash(job: Dict[str, Any]) -> str:
    jd = job.get("jd_text") or ""
    if isinstance(jd, str) and jd:
        return _sha256_bytes(jd.encode("utf-8"))
    return content_fingerprint(job)


def _token_estimate(text: str) -> int:
    return max(1, len(text) // 4)


def _brief_cache_dir(profile: str) -> Path:
    return STATE_DIR / "ai_job_briefs_cache" / profile


def _cache_key(job: Dict[str, Any], profile_hash: str, model: str) -> str:
    parts = [
        _job_id(job),
        _jd_hash(job),
        profile_hash,
        PROMPT_VERSION,
        model,
    ]
    return _sha256_bytes("|".join(parts).encode("utf-8"))


def _load_cache(profile: str, key: str) -> Optional[Dict[str, Any]]:
    path = _brief_cache_dir(profile) / f"{key}.json"
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _save_cache(profile: str, key: str, payload: Dict[str, Any]) -> None:
    path = _brief_cache_dir(profile) / f"{key}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _fit_bullets(job: Dict[str, Any]) -> List[str]:
    bullets = []
    role_band = job.get("role_band") or ""
    if role_band:
        bullets.append(f"Role band aligns with {role_band}.")
    for sig in (job.get("fit_signals") or [])[:4]:
        bullets.append(f"Evidence of {sig.replace('fit:', '').replace('_', ' ')}.")
    return bullets[:5] or ["Matches core responsibilities in the role description."]


def _gap_bullets(job: Dict[str, Any]) -> List[str]:
    bullets = []
    for sig in (job.get("risk_signals") or [])[:3]:
        bullets.append(f"Address risk area: {sig.replace('risk:', '').replace('_', ' ')}.")
    if not bullets:
        bullets.append("No major gaps flagged; verify role-specific tooling and domain expertise.")
    return bullets


def _interview_focus(job: Dict[str, Any]) -> List[str]:
    bullets = []
    for sig in (job.get("fit_signals") or [])[:3]:
        bullets.append(f"Prepare impact story on {sig.replace('fit:', '').replace('_', ' ')}.")
    bullets.append("Be ready to quantify customer outcomes and adoption metrics.")
    return bullets[:5]


def _resume_tweaks(job: Dict[str, Any]) -> List[str]:
    title = job.get("title") or "the role"
    bullets = [
        f"Mirror {title} keywords in summary and recent role bullets.",
        "Highlight deployment/implementation outcomes with concrete metrics.",
        "Show cross-functional leadership and customer-facing delivery.",
    ]
    return bullets[:5]


def _brief_payload(job: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "job_id": _job_id(job),
        "apply_url": job.get("apply_url") or "",
        "title": job.get("title") or "Untitled",
        "score": int(job.get("score", 0) or 0),
        "why_fit": _fit_bullets(job),
        "gaps": _gap_bullets(job),
        "interview_focus": _interview_focus(job),
        "resume_tweaks": _resume_tweaks(job),
    }


def generate_job_briefs(
    *,
    provider: str,
    profile: str,
    ranked_path: Path,
    run_id: str,
    max_jobs: int,
    max_tokens_per_job: int,
    total_budget: int,
    ai_enabled: bool,
    ai_reason: str,
    model_name: str,
    prompt_path: Path = PROMPT_PATH,
    profile_path: Path = Path("data/candidate_profile.json"),
) -> Tuple[Path, Path, Dict[str, Any]]:
    prompt_text, prompt_sha = _load_prompt(prompt_path)
    prompt_text = prompt_text.strip()

    ranked = _load_ranked(ranked_path)
    top_jobs = ranked[: max(0, max_jobs)]
    profile_hash = _profile_hash(profile_path)

    metadata = {
        "prompt_version": PROMPT_VERSION,
        "prompt_sha256": prompt_sha,
        "model": model_name,
        "provider": provider,
        "profile": profile,
        "timestamp": _utcnow_iso(),
        "input_hashes": {"ranked": _sha256_path(ranked_path), "profile": profile_hash},
        "max_jobs": max_jobs,
        "max_tokens_per_job": max_tokens_per_job,
        "total_budget": total_budget,
    }

    run_dir = _run_dir(run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    json_path = run_dir / f"ai_job_briefs.{profile}.json"
    md_path = run_dir / f"ai_job_briefs.{profile}.md"

    briefs: List[Dict[str, Any]] = []
    cache_hits = 0
    used_tokens = 0
    skipped_budget = 0

    for job in top_jobs:
        jd_text = job.get("jd_text") or ""
        estimated_tokens = _token_estimate(jd_text if isinstance(jd_text, str) else "")
        if estimated_tokens > max_tokens_per_job:
            estimated_tokens = max_tokens_per_job
        if used_tokens + estimated_tokens > total_budget:
            skipped_budget += 1
            continue

        key = _cache_key(job, profile_hash, model_name)
        cached = _load_cache(profile, key)
        if cached:
            cache_hits += 1
            briefs.append(cached)
            continue

        if ai_enabled:
            brief = _brief_payload(job)
        else:
            brief = _brief_payload(job)
            brief["why_fit"] = []
            brief["gaps"] = []
            brief["interview_focus"] = []
            brief["resume_tweaks"] = []

        _save_cache(profile, key, brief)
        briefs.append(brief)
        used_tokens += estimated_tokens

    status = "ok" if ai_enabled else "disabled"
    payload = {
        "status": status,
        "reason": "" if ai_enabled else ai_reason,
        "provider": provider,
        "profile": profile,
        "briefs": briefs,
        "metadata": {
            **metadata,
            "cache_hits": cache_hits,
            "estimated_tokens_used": used_tokens,
            "skipped_due_to_budget": skipped_budget,
        },
    }

    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(_briefs_markdown(payload), encoding="utf-8")
    return md_path, json_path, payload


def _briefs_markdown(payload: Dict[str, Any]) -> str:
    lines = [
        "# AI Job Briefs",
        "",
        f"Provider: **{payload.get('provider')}**",
        f"Profile: **{payload.get('profile')}**",
        f"Status: **{payload.get('status')}**",
        "",
    ]
    if payload.get("status") != "ok":
        lines.append(f"Reason: {payload.get('reason')}")
        lines.append("")

    for brief in payload.get("briefs") or []:
        lines.append(f"## {brief.get('title')} — {brief.get('score')}")
        if brief.get("apply_url"):
            lines.append(f"[Apply link]({brief.get('apply_url')})")
        lines.append("")
        lines.append("**Why fit**")
        for item in brief.get("why_fit") or []:
            lines.append(f"- {item}")
        lines.append("")
        lines.append("**Gaps**")
        for item in brief.get("gaps") or []:
            lines.append(f"- {item}")
        lines.append("")
        lines.append("**Interview focus**")
        for item in brief.get("interview_focus") or []:
            lines.append(f"- {item}")
        lines.append("")
        lines.append("**Resume tweaks**")
        for item in brief.get("resume_tweaks") or []:
            lines.append(f"- {item}")
        lines.append("")

    meta = payload.get("metadata") or {}
    lines.append("## Metadata")
    for key in sorted(meta.keys()):
        lines.append(f"- {key}: {meta[key]}")
    lines.append("")
    return "\n".join(lines)
