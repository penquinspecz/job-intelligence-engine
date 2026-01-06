from __future__ import annotations

from pathlib import Path

# Base directories
REPO_ROOT = Path(".")
DATA_DIR = REPO_ROOT / "data"
STATE_DIR = DATA_DIR / "state"
SNAPSHOT_DIR = DATA_DIR / "openai_snapshots"

# Canonical pipeline artifacts
RAW_JOBS_JSON = DATA_DIR / "openai_raw_jobs.json"
LABELED_JOBS_JSON = DATA_DIR / "openai_labeled_jobs.json"
ENRICHED_JOBS_JSON = DATA_DIR / "openai_enriched_jobs.json"
ASHBY_CACHE_DIR = DATA_DIR / "ashby_cache"
EMBED_CACHE_JSON = STATE_DIR / "embed_cache.json"

RANKED_FAMILIES_JSON = DATA_DIR / "openai_ranked_families.json"

def ranked_jobs_json(profile: str) -> Path:
    return DATA_DIR / f"openai_ranked_jobs.{profile}.json"

def ranked_jobs_csv(profile: str) -> Path:
    return DATA_DIR / f"openai_ranked_jobs.{profile}.csv"

def ranked_families_json(profile: str) -> Path:
    return DATA_DIR / f"openai_ranked_families.{profile}.json"

def shortlist_md(profile: str) -> Path:
    return DATA_DIR / f"openai_shortlist.{profile}.md"

def state_last_ranked(profile: str) -> Path:
    return STATE_DIR / f"last_ranked.{profile}.json"

LOCK_PATH = STATE_DIR / "run_daily.lock"


def ensure_dirs() -> None:
    """
    Ensure key data directories exist. Safe to call repeatedly.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    ASHBY_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    EMBED_CACHE_JSON.parent.mkdir(parents=True, exist_ok=True)
