from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)


def resolve_webhook(profile: str) -> str:
    override = os.environ.get(f"DISCORD_WEBHOOK_URL_{profile.upper()}", "").strip()
    if override:
        return override
    return os.environ.get("DISCORD_WEBHOOK_URL", "").strip()


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_ranked(path: Path) -> list[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    if isinstance(data, list):
        return data
    return []


def _count_shortlist(jobs: Iterable[Dict[str, Any]], min_score: int) -> int:
    count = 0
    for job in jobs:
        if job.get("enrich_status") == "unavailable":
            continue
        if int(job.get("score", 0) or 0) >= min_score:
            count += 1
    return count


def build_run_summary_message(
    *,
    provider: str,
    profile: str,
    ranked_json: Path,
    diff_counts: Dict[str, int],
    min_score: int,
    timestamp: Optional[str] = None,
    top_n: int = 5,
    extra_lines: Optional[List[str]] = None,
) -> str:
    ts = timestamp or _utcnow_iso()
    jobs = _load_ranked(ranked_json)
    shortlist_count = _count_shortlist(jobs, min_score)

    lines = [f"**JobIntel — {provider} / {profile} — {ts}**"]
    lines.append(
        "Deltas: new={new} changed={changed} removed={removed}".format(
            new=diff_counts.get("new", 0),
            changed=diff_counts.get("changed", 0),
            removed=diff_counts.get("removed", 0),
        )
    )
    lines.append(f"Shortlist (>= {min_score}): {shortlist_count}")
    lines.append("")
    lines.append(f"Top {top_n}:")

    for job in jobs[:top_n]:
        title = str(job.get("title") or "Untitled").strip()
        score = int(job.get("score", 0) or 0)
        apply_url = str(job.get("apply_url") or "").strip()
        if apply_url:
            lines.append(f"- **{score}** {title} — {apply_url}")
        else:
            lines.append(f"- **{score}** {title}")

    if extra_lines:
        lines.append("")
        lines.extend(extra_lines)

    return "\n".join(lines)


def post_discord(webhook_url: str, message: str) -> bool:
    if not webhook_url:
        logger.info("Discord webhook unset; skipping run summary alert.")
        return False
    if "discord.com/api/webhooks/" not in webhook_url:
        logger.warning("⚠️ DISCORD_WEBHOOK_URL missing or doesn't look like a Discord webhook URL. Skipping post.")
        return False

    payload = json.dumps({"content": message}).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return 200 <= resp.status < 300
    except urllib.error.HTTPError as e:
        logger.error("Discord webhook POST failed: %s", e.code)
        return False
    except Exception as e:  # pragma: no cover - network edge
        logger.error("Discord webhook POST failed: %r", e)
        return False
