#!/usr/bin/env python3
from __future__ import annotations

try:
    import _bootstrap  # type: ignore
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

import importlib
import io
import json
import os
import shutil
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

try:
    from scripts import replay_run  # type: ignore
except ModuleNotFoundError:
    import importlib.util

    _spec = importlib.util.spec_from_file_location("replay_run", Path(__file__).with_name("replay_run.py"))
    if not _spec or not _spec.loader:
        raise
    replay_run = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(replay_run)


def _ensure_env() -> tuple[Path, Path]:
    data_dir = os.environ.get("JOBINTEL_DATA_DIR")
    state_dir = os.environ.get("JOBINTEL_STATE_DIR")
    if not data_dir:
        data_dir = tempfile.mkdtemp(prefix="jobintel_cronjob_data_")
        os.environ["JOBINTEL_DATA_DIR"] = data_dir
    if not state_dir:
        state_dir = tempfile.mkdtemp(prefix="jobintel_cronjob_state_")
        os.environ["JOBINTEL_STATE_DIR"] = state_dir
    os.environ.setdefault("CAREERS_MODE", "SNAPSHOT")
    os.environ.setdefault("EMBED_PROVIDER", "stub")
    os.environ.setdefault("ENRICH_MAX_WORKERS", "1")
    os.environ.setdefault("DISCORD_WEBHOOK_URL", "")
    return Path(data_dir), Path(state_dir)


def _seed_snapshots(data_dir: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    for provider in ("openai_snapshots", "anthropic_snapshots"):
        src = repo_root / "data" / provider
        dest = data_dir / provider
        if src.exists() and not dest.exists():
            shutil.copytree(src, dest)
    candidate_profile = repo_root / "data" / "candidate_profile.json"
    if candidate_profile.exists():
        dest = data_dir / candidate_profile.name
        if not dest.exists():
            shutil.copy2(candidate_profile, dest)


def main() -> int:
    run_id = os.environ.get("JOBINTEL_CRONJOB_RUN_ID", "2026-01-01T00:00:00Z")
    data_dir, _state_dir = _ensure_env()
    _seed_snapshots(data_dir)

    import ji_engine.config as config

    try:
        from scripts import run_daily  # type: ignore
    except ModuleNotFoundError:
        import importlib.util

        _spec = importlib.util.spec_from_file_location("run_daily", Path(__file__).with_name("run_daily.py"))
        if not _spec or not _spec.loader:
            raise
        run_daily = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(run_daily)

    importlib.reload(config)
    if run_daily.__name__ in sys.modules:
        importlib.reload(run_daily)
    replay_run.DATA_DIR = config.DATA_DIR

    run_daily._utcnow_iso = lambda: run_id  # type: ignore[assignment]
    argv = [
        "run_daily.py",
        "--profiles",
        "cs",
        "--us_only",
        "--no_post",
        "--snapshot-only",
        "--offline",
    ]
    sys.argv = argv
    exit_code = run_daily.main()
    if exit_code != 0:
        print(f"cronjob_simulate failed: exit_code={exit_code}", file=sys.stderr)
        return exit_code

    run_dir = run_daily.RUN_METADATA_DIR / run_daily._sanitize_run_id(run_id)
    report_path = run_dir / "run_report.json"
    if not report_path.exists():
        print(f"cronjob_simulate missing run_report.json at {report_path}", file=sys.stderr)
        return 2
    report = json.loads(report_path.read_text(encoding="utf-8"))
    verifiable = report.get("verifiable_artifacts") or {}
    print(f"cronjob_simulate run_id={run_id} verifiable_artifacts={len(verifiable)}")

    buf = io.StringIO()
    with redirect_stdout(buf):
        replay_code = replay_run.main(["--run-dir", str(run_dir), "--profile", "cs", "--strict", "--json"])
    replay_payload = buf.getvalue().strip()
    print(replay_payload)
    return 0 if replay_code == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
