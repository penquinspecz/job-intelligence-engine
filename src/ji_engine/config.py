from __future__ import annotations

import os
from pathlib import Path

# Base directories
REPO_ROOT = Path(".")
_DEFAULT_DATA_DIR = REPO_ROOT / "data"
_ENV_DATA_DIR = os.environ.get("JOBINTEL_DATA_DIR")
_STATE_DIR_OVERRIDE = os.environ.get("JOBINTEL_STATE_DIR")
DATA_DIR = Path(_ENV_DATA_DIR).expanduser() if _ENV_DATA_DIR else _DEFAULT_DATA_DIR
STATE_DIR = Path(_STATE_DIR_OVERRIDE).expanduser() if _STATE_DIR_OVERRIDE else Path("/app/state" if os.environ.get("CI") else REPO_ROOT / "state")
SNAPSHOT_DIR = DATA_DIR / "openai_snapshots"
HISTORY_DIR = STATE_DIR / "history"
RUN_METADATA_DIR = STATE_DIR / "runs"

# Canonical pipeline artifacts
RAW_JOBS_JSON = DATA_DIR / "openai_raw_jobs.json"
LABELED_JOBS_JSON = DATA_DIR / "openai_labeled_jobs.json"
ENRICHED_JOBS_JSON = DATA_DIR / "openai_enriched_jobs.json"
ASHBY_CACHE_DIR = DATA_DIR / "ashby_cache"
EMBED_CACHE_JSON = STATE_DIR / "embed_cache.json"

RANKED_FAMILIES_JSON = DATA_DIR / "openai_ranked_families.json"

HISTORY_DIR = STATE_DIR / "history"
RUN_METADATA_DIR = STATE_DIR / "runs"

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
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    RUN_METADATA_DIR.mkdir(parents=True, exist_ok=True)
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    RUN_METADATA_DIR.mkdir(parents=True, exist_ok=True)