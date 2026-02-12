from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from ji_engine.ai.insights_input import build_weekly_insights_input
from ji_engine.config import REPO_ROOT, RUN_METADATA_DIR
from ji_engine.utils.time import utc_now_z

logger = logging.getLogger(__name__)

PROMPT_VERSION = "weekly_insights_v3"
PROMPT_PATH = REPO_ROOT / "docs" / "prompts" / "weekly_insights_v3.md"


def _utcnow_iso() -> str:
    return utc_now_z(seconds_precision=True)


def _sanitize_run_id(run_id: str) -> str:
    return run_id.replace(":", "").replace("-", "").replace(".", "")


def _run_dir(run_id: str) -> Path:
    return RUN_METADATA_DIR / _sanitize_run_id(run_id)


def _sha256_bytes(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


def _load_prompt(path: Path) -> Tuple[str, str]:
    if not path.exists():
        raise FileNotFoundError(f"Prompt template not found: {path}")
    text = path.read_text(encoding="utf-8")
    return text, _sha256_bytes(text.encode("utf-8"))


def _build_insights_payload(
    insights_input: Dict[str, Any],
    *,
    provider: str,
    profile: str,
    status: str,
    reason: str,
    metadata: Dict[str, Any],
) -> Dict[str, Any]:
    diff_counts = ((insights_input.get("diffs") or {}).get("counts") or {}) if isinstance(insights_input, dict) else {}
    top_families = insights_input.get("top_families") or []
    skill_keywords = insights_input.get("skill_keywords") or []
    score_distribution = insights_input.get("score_distribution") or {}
    themes = [str(item.get("family")) for item in top_families[:5] if isinstance(item, dict) and item.get("family")]
    risks = [str(item.get("keyword")) for item in skill_keywords[:3] if isinstance(item, dict) and item.get("keyword")]

    recommended_actions = []
    if int(diff_counts.get("new", 0) or 0) > 0:
        recommended_actions.append("Prioritize outreach on newly added roles from this week.")
    if int(diff_counts.get("changed", 0) or 0) > 0:
        recommended_actions.append("Re-check changed roles for updated scope, level, or location signals.")
    gte80 = int(((score_distribution.get("buckets") or {}).get("gte80", 0)) or 0)
    if gte80 > 0:
        recommended_actions.append("Focus on score >= 80 opportunities for immediate applications.")
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
        "top_roles": insights_input.get("top_roles") or [],
        "risks": risks,
        "structured_inputs": {
            "diffs": insights_input.get("diffs") or {},
            "top_families": top_families,
            "score_distribution": score_distribution,
            "skill_keywords": skill_keywords,
        },
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
    for key in ("cache_key", "structured_input_hash", "prompt_sha256", "prompt_version", "model", "provider"):
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
    ranked_families_path = ranked_path.parent / ranked_path.name.replace("ranked_jobs", "ranked_families")
    insights_input_path, insights_input_payload = build_weekly_insights_input(
        provider=provider,
        profile=profile,
        ranked_path=ranked_path,
        prev_path=prev_path,
        ranked_families_path=ranked_families_path if ranked_families_path.exists() else None,
        run_id=run_id,
        run_metadata_dir=RUN_METADATA_DIR,
    )

    structured_input_hash = _sha256_bytes(insights_input_path.read_bytes())
    input_hashes = {
        "insights_input": _sha256_bytes(insights_input_path.read_bytes()),
        "ranked": (insights_input_payload.get("input_hashes") or {}).get("ranked"),
        "previous": (insights_input_payload.get("input_hashes") or {}).get("previous"),
        "ranked_families": (insights_input_payload.get("input_hashes") or {}).get("ranked_families"),
    }
    cache_key = _sha256_bytes(
        json.dumps(
            {
                "prompt_version": PROMPT_VERSION,
                "prompt_sha256": prompt_sha,
                "model": model_name,
                "provider": provider,
                "profile": profile,
                "input_hashes": input_hashes,
                "structured_input_hash": structured_input_hash,
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    )
    metadata = {
        "prompt_version": PROMPT_VERSION,
        "prompt_sha256": prompt_sha,
        "model": model_name,
        "provider": provider,
        "profile": profile,
        "timestamp": _utcnow_iso(),
        "input_hashes": input_hashes,
        "structured_input_hash": structured_input_hash,
        "cache_key": cache_key,
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

    if not ai_enabled:
        payload = _build_insights_payload(
            insights_input_payload,
            provider=provider,
            profile=profile,
            status="disabled",
            reason=ai_reason,
            metadata=metadata,
        )
    else:
        payload = _build_insights_payload(
            insights_input_payload,
            provider=provider,
            profile=profile,
            status="ok",
            reason="",
            metadata=metadata,
        )

    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(_render_markdown(payload), encoding="utf-8")
    return md_path, json_path, payload
