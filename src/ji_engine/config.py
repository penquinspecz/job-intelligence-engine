"""
SignalCraft
Copyright (c) 2026 Chris Menendez.
All Rights Reserved.
See LICENSE for permitted use.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List

# Base directories
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_DATA_DIR = REPO_ROOT / "data"
_ENV_DATA_DIR = os.environ.get("JOBINTEL_DATA_DIR")
_STATE_DIR_OVERRIDE = os.environ.get("JOBINTEL_STATE_DIR")
DATA_DIR = Path(_ENV_DATA_DIR).expanduser() if _ENV_DATA_DIR else _DEFAULT_DATA_DIR
STATE_DIR = Path(_STATE_DIR_OVERRIDE).expanduser() if _STATE_DIR_OVERRIDE else REPO_ROOT / "state"
SNAPSHOT_DIR = DATA_DIR / "openai_snapshots"
HISTORY_DIR = STATE_DIR / "history"
RUN_METADATA_DIR = STATE_DIR / "runs"
USER_STATE_DIR = STATE_DIR / "user_state"
DEFAULT_CANDIDATE_ID = "local"
_CANDIDATE_ID_RE = re.compile(r"^[a-z0-9_]{1,64}$")

# Retention defaults (used by scripts/prune_state.py; can be overridden by env vars there).
DEFAULT_KEEP_RUN_REPORTS = 60
DEFAULT_KEEP_HISTORY_SNAPSHOTS_PER_PROFILE = 30
DEFAULT_PRUNE_MAX_AGE_DAYS = 90
# Canonical pipeline artifacts
RAW_JOBS_JSON = DATA_DIR / "openai_raw_jobs.json"
LABELED_JOBS_JSON = DATA_DIR / "openai_labeled_jobs.json"
ENRICHED_JOBS_JSON = DATA_DIR / "openai_enriched_jobs.json"
ASHBY_CACHE_DIR = DATA_DIR / "ashby_cache"
EMBED_CACHE_JSON = STATE_DIR / "embed_cache.json"

RANKED_FAMILIES_JSON = DATA_DIR / "openai_ranked_families.json"


def sanitize_candidate_id(candidate_id: str) -> str:
    """
    Validate candidate_id using a strict allowlist.

    Allowed pattern: lowercase [a-z0-9_]{1,64}
    """
    if not isinstance(candidate_id, str):
        raise ValueError("candidate_id must be a string")
    normalized = candidate_id.strip()
    if normalized != normalized.lower():
        raise ValueError("candidate_id must be lowercase")
    if not _CANDIDATE_ID_RE.fullmatch(normalized):
        raise ValueError("candidate_id must match [a-z0-9_]{1,64}")
    return normalized


def candidate_state_dir(candidate_id: str) -> Path:
    return STATE_DIR / "candidates" / sanitize_candidate_id(candidate_id)


def candidate_run_metadata_dir(candidate_id: str) -> Path:
    return candidate_state_dir(candidate_id) / "runs"


def candidate_history_dir(candidate_id: str) -> Path:
    return candidate_state_dir(candidate_id) / "history"


def candidate_user_state_dir(candidate_id: str) -> Path:
    return candidate_state_dir(candidate_id) / "user_state"


@dataclass(frozen=True)
class CandidateStatePaths:
    """
    Canonical candidate state contract paths.

    Contract groups:
    - user_inputs: candidate-provided inputs (profiles/resumes)
    - system_state: pointers/indexes (last_success, last_run, run index)
    - derived_artifacts: generated run outputs/history/user overlays
    """

    candidate_id: str
    root: Path
    user_inputs: Path
    system_state: Path
    derived_artifacts: Path
    runs: Path
    history: Path
    user_state: Path
    profile_path: Path
    last_run_pointer_path: Path
    last_success_pointer_path: Path
    run_index_path: Path
    proofs_dir: Path


def candidate_state_paths(candidate_id: str) -> CandidateStatePaths:
    safe_candidate = sanitize_candidate_id(candidate_id)
    root = candidate_state_dir(safe_candidate)
    user_inputs = root / "inputs"
    system_state = root / "system_state"
    return CandidateStatePaths(
        candidate_id=safe_candidate,
        root=root,
        user_inputs=user_inputs,
        system_state=system_state,
        derived_artifacts=root,
        runs=candidate_run_metadata_dir(safe_candidate),
        history=candidate_history_dir(safe_candidate),
        user_state=candidate_user_state_dir(safe_candidate),
        profile_path=user_inputs / "candidate_profile.json",
        last_run_pointer_path=system_state / "last_run.json",
        last_success_pointer_path=system_state / "last_success.json",
        run_index_path=system_state / "run_index.sqlite",
        proofs_dir=root / "proofs",
    )


def candidate_profile_path(candidate_id: str) -> Path:
    return candidate_state_paths(candidate_id).profile_path


def candidate_last_run_pointer_path(candidate_id: str) -> Path:
    return candidate_state_paths(candidate_id).last_run_pointer_path


def candidate_last_success_pointer_path(candidate_id: str) -> Path:
    return candidate_state_paths(candidate_id).last_success_pointer_path


def candidate_run_index_path(candidate_id: str) -> Path:
    return candidate_state_paths(candidate_id).run_index_path


def candidate_last_run_read_paths(candidate_id: str) -> List[Path]:
    """
    Deterministic read order for last_run pointers with backward compatibility.
    """
    safe_candidate = sanitize_candidate_id(candidate_id)
    paths = [
        candidate_last_run_pointer_path(safe_candidate),
        candidate_state_dir(safe_candidate) / "last_run.json",
    ]
    if safe_candidate == DEFAULT_CANDIDATE_ID:
        paths.append(STATE_DIR / "last_run.json")
    return paths


def candidate_last_success_read_paths(candidate_id: str) -> List[Path]:
    """
    Deterministic read order for last_success pointers with backward compatibility.
    """
    safe_candidate = sanitize_candidate_id(candidate_id)
    paths = [
        candidate_last_success_pointer_path(safe_candidate),
        candidate_state_dir(safe_candidate) / "last_success.json",
    ]
    if safe_candidate == DEFAULT_CANDIDATE_ID:
        paths.append(STATE_DIR / "last_success.json")
    return paths


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
    # Reserve a deterministic default candidate namespace without changing legacy paths.
    candidate_state_dir(DEFAULT_CANDIDATE_ID).mkdir(parents=True, exist_ok=True)
    candidate_run_metadata_dir(DEFAULT_CANDIDATE_ID).mkdir(parents=True, exist_ok=True)
    candidate_history_dir(DEFAULT_CANDIDATE_ID).mkdir(parents=True, exist_ok=True)
    candidate_user_state_dir(DEFAULT_CANDIDATE_ID).mkdir(parents=True, exist_ok=True)
    local_paths = candidate_state_paths(DEFAULT_CANDIDATE_ID)
    local_paths.user_inputs.mkdir(parents=True, exist_ok=True)
    local_paths.system_state.mkdir(parents=True, exist_ok=True)
    local_paths.proofs_dir.mkdir(parents=True, exist_ok=True)
