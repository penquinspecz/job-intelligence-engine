from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ji_engine.config import REPO_ROOT, RUN_METADATA_DIR

logger = logging.getLogger(__name__)

PROMPT_VERSION = "weekly_insights_v1"
PROMPT_PATH = REPO_ROOT / "docs" / "prompts" / "weekly_insights_v1.md"


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def _top_roles(jobs: List[Dict[str, Any]], limit: int = 5) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for job in jobs[:limit]:
        out.append(
            {
                "title": job.get("title") or "Untitled",
                "score": int(job.get("score", 0) or 0),
                "apply_url": job.get("apply_url") or "",
            }
        )
    return out


def _count_signals(jobs: List[Dict[str, Any]], field: str) -> List[Tuple[str, int]]:
    counts: Dict[str, int] = {}
    for job in jobs:
        signals = job.get(field) or []
        if not isinstance(signals, list):
            continue
        for sig in signals:
            key = str(sig).strip()
            if not key:
                continue
            counts[key] = counts.get(key, 0) + 1
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))


def _build_insights_payload(
    jobs: List[Dict[str, Any]],
    *,
    provider: str,
    profile: str,
    status: str,
    reason: str,
    metadata: Dict[str, Any],
) -> Dict[str, Any]:
    top = _top_roles(jobs, limit=5)
    themes_counts = _count_signals(jobs, "fit_signals")
    risks_counts = _count_signals(jobs, "risk_signals")
    themes = [name for name, _ in themes_counts[:5]]
    risks = [name for name, _ in risks_counts[:3]]

    recommended_actions = []
    if themes:
        for theme in themes[:3]:
            recommended_actions.append(f"Prioritize roles matching {theme}.")
    if not recommended_actions:
        recommended_actions = [
            "Review top-ranked roles and align outreach with highest-scoring themes.",
            "Validate role bands with the shortlist and adjust thresholds if needed.",
            "Track new roles weekly to spot emerging demand shifts.",
        ]

    return {
        "status": status,
        "reason": reason,
        "provider": provider,
        "profile": profile,
        "themes": themes,
        "recommended_actions": recommended_actions[:5],
        "top_roles": top,
        "risks": risks,
        "metadata": metadata,
    }


def _render_markdown(payload: Dict[str, Any]) -> str:
    lines = [
        "# Weekly AI Insights",
        "",
        f"Provider: **{payload.get('provider')}**",
        f"Profile: **{payload.get('profile')}**",
        f"Status: **{payload.get('status')}**",
        "",
    ]
    if payload.get("status") != "ok":
        lines.append(f"Reason: {payload.get('reason')}")
        lines.append("")

    lines.append("## Themes")
    themes = payload.get("themes") or []
    if themes:
        lines.extend([f"- {t}" for t in themes])
    else:
        lines.append("- (none)")
    lines.append("")

    lines.append("## Recommended actions")
    actions = payload.get("recommended_actions") or []
    if actions:
        lines.extend([f"- {a}" for a in actions])
    else:
        lines.append("- (none)")
    lines.append("")

    lines.append("## Top roles")
    for role in payload.get("top_roles") or []:
        title = role.get("title") or "Untitled"
        score = role.get("score", 0)
        url = role.get("apply_url") or ""
        if url:
            lines.append(f"- **{score}** {title} — {url}")
        else:
            lines.append(f"- **{score}** {title}")
    lines.append("")

    lines.append("## Risks/concerns")
    risks = payload.get("risks") or []
    if risks:
        lines.extend([f"- {r}" for r in risks])
    else:
        lines.append("- (none)")
    lines.append("")

    meta = payload.get("metadata") or {}
    lines.append("## Metadata")
    for key in sorted(meta.keys()):
        lines.append(f"- {key}: {meta[key]}")
    lines.append("")
    return "\n".join(lines)


def _should_use_cache(existing: Dict[str, Any], metadata: Dict[str, Any]) -> bool:
    if not isinstance(existing, dict):
        return False
    existing_meta = existing.get("metadata")
    if not isinstance(existing_meta, dict):
        return False
    for key in ("input_hashes", "prompt_sha256", "prompt_version", "model", "provider"):
        if existing_meta.get(key) != metadata.get(key):
            return False
    return True


def generate_insights(
    *,
    provider: str,
    profile: str,
    ranked_path: Path,
    prev_path: Optional[Path],
    run_id: str,
    prompt_path: Path = PROMPT_PATH,
    ai_enabled: bool,
    ai_reason: str,
    model_name: str,
) -> Tuple[Path, Path, Dict[str, Any]]:
    prompt_text, prompt_sha = _load_prompt(prompt_path)
    prompt_text = prompt_text.strip()

    input_hashes = {"ranked": _sha256_path(ranked_path), "previous": _sha256_path(prev_path) if prev_path else None}
    metadata = {
        "prompt_version": PROMPT_VERSION,
        "prompt_sha256": prompt_sha,
        "model": model_name,
        "provider": provider,
        "profile": profile,
        "timestamp": _utcnow_iso(),
        "input_hashes": input_hashes,
    }

    run_dir = _run_dir(run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    json_path = run_dir / f"ai_insights.{profile}.json"
    md_path = run_dir / f"ai_insights.{profile}.md"

    if json_path.exists():
        try:
            existing = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception:
            existing = None
        if _should_use_cache(existing, metadata):
            logger.info("AI insights cache hit (%s/%s).", provider, profile)
            return md_path, json_path, existing

    jobs = _load_ranked(ranked_path)
    if not ai_enabled:
        payload = _build_insights_payload(
            jobs,
            provider=provider,
            profile=profile,
            status="disabled",
            reason=ai_reason,
            metadata=metadata,
        )
    else:
        payload = _build_insights_payload(
            jobs,
            provider=provider,
            profile=profile,
            status="ok",
            reason="",
            metadata=metadata,
        )

    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(_render_markdown(payload), encoding="utf-8")
    return md_path, json_path, payload
