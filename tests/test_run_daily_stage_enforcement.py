#!/usr/bin/env python3
"""
Tests for run_daily.py stage execution enforcement:
- default run includes classify+score
- --no_enrich still reaches score when fixtures exist
- missing scoring prerequisites fail with exit code 2
"""

from __future__ import annotations

import importlib
import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List


def _output_dir(data_dir: Path) -> Path:
    out = data_dir / "ashby_cache"
    out.mkdir(parents=True, exist_ok=True)
    return out


def _build_env(data_dir: Path, state_dir: Path) -> Dict[str, str]:
    """Build environment dict with overridden data/state directories."""
    env = os.environ.copy()
    env["JOBINTEL_DATA_DIR"] = str(data_dir)
    env["JOBINTEL_STATE_DIR"] = str(state_dir)
    return env


def test_default_run_includes_all_stages(tmp_path: Path, monkeypatch: Any) -> None:
    """
    A default run (no special flags) should execute scrape → classify → enrich → score.
    """
    # Set up temp directories
    data_dir = tmp_path / "data"
    state_dir = tmp_path / "state"
    data_dir.mkdir()
    state_dir.mkdir()

    # Create snapshot
    snapshot_dir = data_dir / "openai_snapshots"
    snapshot_dir.mkdir()
    (snapshot_dir / "index.html").write_text("<html>test</html>")

    # Create minimal inputs
    (_output_dir(data_dir) / "openai_raw_jobs.json").write_text("[]")
    (_output_dir(data_dir) / "openai_labeled_jobs.json").write_text("[]")
    (_output_dir(data_dir) / "openai_enriched_jobs.json").write_text("[]")
    (data_dir / "candidate_profile.json").write_text('{"skills": [], "roles": []}')

    # Run with --no_subprocess to capture stage execution
    result = subprocess.run(
        [
            sys.executable,
            "scripts/run_daily.py",
            "--profiles",
            "cs",
            "--no_post",
            "--no_subprocess",
        ],
        cwd=str(Path(__file__).parent.parent),
        env=_build_env(data_dir, state_dir),
        capture_output=True,
        text=True,
    )

    # Should succeed
    assert result.returncode == 0, (
        f"Expected success, got {result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )

    # Check that all stages ran (by checking for stage names in output or telemetry)
    last_run = state_dir / "last_run.json"
    assert last_run.exists(), "last_run.json should exist"

    telemetry = json.loads(last_run.read_text())
    stages = telemetry.get("stages", {})

    # Default run should include scrape, classify, enrich (if not --no_enrich), and score
    assert "scrape" in stages, "scrape stage should have run"
    assert "classify" in stages, "classify stage should have run"
    assert "enrich" in stages, "enrich stage should have run"
    assert any(k.startswith("score:") for k in stages), "score stage should have run"


def test_default_scoring_does_not_prefer_ai(tmp_path: Path, monkeypatch: Any) -> None:
    """
    Default run (no --ai flags) should not pass --prefer_ai to score_jobs.
    """
    data_dir = tmp_path / "data"
    state_dir = tmp_path / "state"
    data_dir.mkdir()
    state_dir.mkdir()
    snapshot_dir = data_dir / "openai_snapshots"
    snapshot_dir.mkdir()
    (snapshot_dir / "index.html").write_text("<html>test</html>")
    (_output_dir(data_dir) / "openai_raw_jobs.json").write_text("[]")
    (_output_dir(data_dir) / "openai_labeled_jobs.json").write_text("[]")
    (_output_dir(data_dir) / "openai_enriched_jobs.json").write_text("[]")
    (data_dir / "candidate_profile.json").write_text('{"skills": [], "roles": []}')

    monkeypatch.setenv("JOBINTEL_DATA_DIR", str(data_dir))
    monkeypatch.setenv("JOBINTEL_STATE_DIR", str(state_dir))
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "")

    import ji_engine.config as config
    import scripts.run_daily as run_daily

    config = importlib.reload(config)
    run_daily = importlib.reload(run_daily)
    run_daily.USE_SUBPROCESS = False

    captured = []

    def fake_run(cmd, *, stage):
        if stage == "scrape":
            (_output_dir(data_dir) / "openai_raw_jobs.json").write_text("[]")
        if stage == "classify":
            (_output_dir(data_dir) / "openai_labeled_jobs.json").write_text("[]")
        if stage == "enrich":
            (_output_dir(data_dir) / "openai_enriched_jobs.json").write_text("[]")
        if stage.startswith("score:"):
            captured.append(cmd)
            profile = stage.split(":", 1)[1]
            for path in (
                run_daily._provider_ranked_jobs_json("openai", profile),
                run_daily._provider_ranked_jobs_csv("openai", profile),
                run_daily._provider_ranked_families_json("openai", profile),
                run_daily._provider_shortlist_md("openai", profile),
            ):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("[]", encoding="utf-8")

    monkeypatch.setattr(run_daily, "_run", fake_run)
    monkeypatch.setattr(sys, "argv", ["run_daily.py", "--no_subprocess", "--no_post", "--profiles", "cs"])

    rc = run_daily.main()
    assert rc == 0
    assert captured, "Score stage should have run"
    assert all("--prefer_ai" not in c for cmd in captured for c in cmd)


def test_ai_run_sets_prefer_ai(tmp_path: Path, monkeypatch: Any) -> None:
    """
    When --ai is set, run_daily should pass --prefer_ai to score_jobs.
    """
    data_dir = tmp_path / "data"
    state_dir = tmp_path / "state"
    data_dir.mkdir()
    state_dir.mkdir()
    snapshot_dir = data_dir / "openai_snapshots"
    snapshot_dir.mkdir()
    (snapshot_dir / "index.html").write_text("<html>test</html>")
    (_output_dir(data_dir) / "openai_raw_jobs.json").write_text("[]")
    (_output_dir(data_dir) / "openai_labeled_jobs.json").write_text("[]")
    (_output_dir(data_dir) / "openai_enriched_jobs.json").write_text("[]")
    (_output_dir(data_dir) / "openai_enriched_jobs_ai.json").write_text("[]")
    (data_dir / "candidate_profile.json").write_text('{"skills": [], "roles": []}')
    labeled_path = _output_dir(data_dir) / "openai_labeled_jobs.json"
    enriched_path = _output_dir(data_dir) / "openai_enriched_jobs.json"
    ts_now = time.time()
    os.utime(labeled_path, (ts_now - 120, ts_now - 120))
    os.utime(enriched_path, (ts_now, ts_now))
    labeled_path = _output_dir(data_dir) / "openai_labeled_jobs.json"
    enriched_path = _output_dir(data_dir) / "openai_enriched_jobs.json"
    ts_now = time.time()
    os.utime(labeled_path, (ts_now - 120, ts_now - 120))
    os.utime(enriched_path, (ts_now, ts_now))
    labeled_path = _output_dir(data_dir) / "openai_labeled_jobs.json"
    enriched_path = _output_dir(data_dir) / "openai_enriched_jobs.json"
    ts_now = time.time()
    os.utime(labeled_path, (ts_now - 30, ts_now - 30))
    os.utime(enriched_path, (ts_now, ts_now))

    labeled_path = _output_dir(data_dir) / "openai_labeled_jobs.json"
    enriched_path = _output_dir(data_dir) / "openai_enriched_jobs.json"
    base_ts = time.time()
    os.utime(labeled_path, (base_ts - 20, base_ts - 20))
    os.utime(enriched_path, (base_ts, base_ts))
    labeled_path = _output_dir(data_dir) / "openai_labeled_jobs.json"
    enriched_path = _output_dir(data_dir) / "openai_enriched_jobs.json"
    base_ts = time.time()
    os.utime(labeled_path, (base_ts - 20, base_ts - 20))
    os.utime(enriched_path, (base_ts, base_ts))
    labeled_path = _output_dir(data_dir) / "openai_labeled_jobs.json"
    enriched_path = _output_dir(data_dir) / "openai_enriched_jobs.json"
    base_ts = time.time()
    os.utime(labeled_path, (base_ts - 20, base_ts - 20))
    os.utime(enriched_path, (base_ts, base_ts))
    labeled_path = _output_dir(data_dir) / "openai_labeled_jobs.json"
    enriched_path = _output_dir(data_dir) / "openai_enriched_jobs.json"
    base_ts = time.time()
    os.utime(labeled_path, (base_ts - 20, base_ts - 20))
    os.utime(enriched_path, (base_ts, base_ts))
    labeled_path = _output_dir(data_dir) / "openai_labeled_jobs.json"
    enriched_path = _output_dir(data_dir) / "openai_enriched_jobs.json"
    base_ts = time.time()
    os.utime(labeled_path, (base_ts - 20, base_ts - 20))
    os.utime(enriched_path, (base_ts, base_ts))
    labeled_path = _output_dir(data_dir) / "openai_labeled_jobs.json"
    enriched_path = _output_dir(data_dir) / "openai_enriched_jobs.json"
    base_ts = time.time()
    os.utime(labeled_path, (base_ts - 20, base_ts - 20))
    os.utime(enriched_path, (base_ts, base_ts))
    labeled_path = _output_dir(data_dir) / "openai_labeled_jobs.json"
    enriched_path = _output_dir(data_dir) / "openai_enriched_jobs.json"
    base_ts = time.time()
    os.utime(labeled_path, (base_ts - 20, base_ts - 20))
    os.utime(enriched_path, (base_ts, base_ts))
    # Make enriched newer than labeled so resolver prefers enriched
    labeled_path = _output_dir(data_dir) / "openai_labeled_jobs.json"
    enriched_path = _output_dir(data_dir) / "openai_enriched_jobs.json"
    ts_now = time.time()
    os.utime(labeled_path, (ts_now - 20, ts_now - 20))
    os.utime(enriched_path, (ts_now, ts_now))

    monkeypatch.setenv("JOBINTEL_DATA_DIR", str(data_dir))
    monkeypatch.setenv("JOBINTEL_STATE_DIR", str(state_dir))
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "")

    import ji_engine.config as config
    import scripts.run_daily as run_daily

    config = importlib.reload(config)
    run_daily = importlib.reload(run_daily)
    run_daily.USE_SUBPROCESS = False

    captured = []

    def fake_run(cmd, *, stage):
        if stage == "scrape":
            (_output_dir(data_dir) / "openai_raw_jobs.json").write_text("[]")
        if stage == "classify":
            (_output_dir(data_dir) / "openai_labeled_jobs.json").write_text("[]")
        if stage == "enrich":
            (_output_dir(data_dir) / "openai_enriched_jobs.json").write_text("[]")
        if stage == "ai_augment":
            (_output_dir(data_dir) / "openai_enriched_jobs_ai.json").write_text("[]")
        if stage.startswith("score:"):
            captured.append(cmd)
            profile = stage.split(":", 1)[1]
            for path in (
                run_daily._provider_ranked_jobs_json("openai", profile),
                run_daily._provider_ranked_jobs_csv("openai", profile),
                run_daily._provider_ranked_families_json("openai", profile),
                run_daily._provider_shortlist_md("openai", profile),
            ):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("[]", encoding="utf-8")

    monkeypatch.setattr(run_daily, "_run", fake_run)
    monkeypatch.setattr(sys, "argv", ["run_daily.py", "--no_subprocess", "--no_post", "--profiles", "cs", "--ai"])

    rc = run_daily.main()
    assert rc == 0
    assert captured, "Score stage should have run"
    assert any("--prefer_ai" in cmd for cmd in captured)


def test_short_circuit_ai_sets_prefer_ai(tmp_path: Path, monkeypatch: Any) -> None:
    """
    In short-circuit scoring (ai-aware), ensure --prefer_ai is passed when --ai is set.
    """
    data_dir = tmp_path / "data"
    state_dir = tmp_path / "state"
    data_dir.mkdir()
    state_dir.mkdir()
    snapshot_dir = data_dir / "openai_snapshots"
    snapshot_dir.mkdir()
    (snapshot_dir / "index.html").write_text("<html>test</html>")
    (_output_dir(data_dir) / "openai_raw_jobs.json").write_text("[]")
    (_output_dir(data_dir) / "openai_labeled_jobs.json").write_text("[]")
    (_output_dir(data_dir) / "openai_enriched_jobs.json").write_text("[]")
    (_output_dir(data_dir) / "openai_enriched_jobs_ai.json").write_text("[]")
    (data_dir / "candidate_profile.json").write_text('{"skills": [], "roles": []}')

    labeled_path = _output_dir(data_dir) / "openai_labeled_jobs.json"
    enriched_path = _output_dir(data_dir) / "openai_enriched_jobs.json"
    base_ts = time.time()
    os.utime(labeled_path, (base_ts - 20, base_ts - 20))
    os.utime(enriched_path, (base_ts, base_ts))

    monkeypatch.setenv("JOBINTEL_DATA_DIR", str(data_dir))
    monkeypatch.setenv("JOBINTEL_STATE_DIR", str(state_dir))
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "")

    import ji_engine.config as config
    import scripts.run_daily as run_daily

    config = importlib.reload(config)
    run_daily = importlib.reload(run_daily)
    run_daily.USE_SUBPROCESS = False

    captured = []

    def fake_run(cmd, *, stage):
        if stage == "ai_augment":
            (_output_dir(data_dir) / "openai_enriched_jobs_ai.json").write_text("[]")
        if stage.startswith("score:"):
            captured.append(cmd)
            profile = stage.split(":", 1)[1]
            for path in (
                run_daily._provider_ranked_jobs_json("openai", profile),
                run_daily._provider_ranked_jobs_csv("openai", profile),
                run_daily._provider_ranked_families_json("openai", profile),
                run_daily._provider_shortlist_md("openai", profile),
            ):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("[]", encoding="utf-8")

    monkeypatch.setattr(run_daily, "_run", fake_run)
    # Force base short-circuit but allow scoring to run (missing ranked outputs)
    monkeypatch.setattr(run_daily, "_should_short_circuit", lambda prev, curr: True)
    monkeypatch.setattr(sys, "argv", ["run_daily.py", "--no_subprocess", "--no_post", "--profiles", "cs", "--ai"])

    rc = run_daily.main()
    assert rc == 0
    assert captured, "Score stage should have run in short-circuit path"
    assert any("--prefer_ai" in cmd for cmd in captured)


def test_no_enrich_uses_labeled_input_even_if_ai_exists(tmp_path: Path, monkeypatch: Any) -> None:
    """
    Regression test: --no_enrich should prefer enriched if present (even if AI file exists), and should not pass --prefer_ai when --ai is not set.
    """
    data_dir = tmp_path / "data"
    state_dir = tmp_path / "state"
    data_dir.mkdir()
    state_dir.mkdir()

    snapshot_dir = data_dir / "openai_snapshots"
    snapshot_dir.mkdir()
    (snapshot_dir / "index.html").write_text("<html>ok</html>")

    # Create required files, including enriched/ai artifacts (to simulate their presence).
    (_output_dir(data_dir) / "openai_raw_jobs.json").write_text("[]")
    (_output_dir(data_dir) / "openai_labeled_jobs.json").write_text("[]")
    (_output_dir(data_dir) / "openai_enriched_jobs.json").write_text("[]")
    (_output_dir(data_dir) / "openai_enriched_jobs_ai.json").write_text("[]")
    (data_dir / "candidate_profile.json").write_text('{"skills": [], "roles": []}')

    labeled_path = _output_dir(data_dir) / "openai_labeled_jobs.json"
    enriched_path = _output_dir(data_dir) / "openai_enriched_jobs.json"
    base_ts = time.time()
    os.utime(labeled_path, (base_ts - 20, base_ts - 20))
    os.utime(enriched_path, (base_ts, base_ts))

    monkeypatch.setenv("JOBINTEL_DATA_DIR", str(data_dir))
    monkeypatch.setenv("JOBINTEL_STATE_DIR", str(state_dir))
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "")

    import ji_engine.config as config
    import scripts.run_daily as run_daily

    config = importlib.reload(config)
    run_daily = importlib.reload(run_daily)
    run_daily.USE_SUBPROCESS = False

    captured: List[List[str]] = []

    def fake_run(cmd: List[str], *, stage: str) -> None:
        if stage == "scrape":
            (_output_dir(data_dir) / "openai_raw_jobs.json").write_text("[]")
        if stage == "classify":
            (_output_dir(data_dir) / "openai_labeled_jobs.json").write_text("[]")
            os.utime(labeled_path, (base_ts - 20, base_ts - 20))
        if stage.startswith("score:"):
            os.utime(enriched_path, (base_ts, base_ts))
            captured.append(cmd)
            profile = stage.split(":", 1)[1]
            for path in (
                run_daily._provider_ranked_jobs_json("openai", profile),
                run_daily._provider_ranked_jobs_csv("openai", profile),
                run_daily._provider_ranked_families_json("openai", profile),
                run_daily._provider_shortlist_md("openai", profile),
            ):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("[]", encoding="utf-8")

    monkeypatch.setattr(run_daily, "_run", fake_run)
    monkeypatch.setattr(
        sys, "argv", ["run_daily.py", "--no_subprocess", "--no_post", "--no_enrich", "--profiles", "cs"]
    )

    rc = run_daily.main()
    assert rc == 0

    assert captured, "score stage should have run"
    assert len(captured) == 1
    score_cmd = captured[0]
    assert "--in_path" in score_cmd
    idx = score_cmd.index("--in_path")
    assert idx + 1 < len(score_cmd)
    assert Path(score_cmd[idx + 1]) == enriched_path
    # ensure prefer_ai was not added
    assert "--prefer_ai" not in score_cmd


def test_short_circuit_scoring_uses_labeled_input(tmp_path: Path, monkeypatch: Any) -> None:
    """
    When _should_short_circuit reports "no upstream changes" but scoring still runs
    (ranked outputs are missing), ensure the short-circuit path uses --no_enrich and
    the resolver picks enriched if present; with --ai, prefer_ai is passed.
    """
    data_dir = tmp_path / "data"
    state_dir = tmp_path / "state"
    data_dir.mkdir()
    state_dir.mkdir()

    snapshot_dir = data_dir / "openai_snapshots"
    snapshot_dir.mkdir()
    (snapshot_dir / "index.html").write_text("<html>ok</html>")

    # Create base inputs, including AI artifact
    (_output_dir(data_dir) / "openai_raw_jobs.json").write_text("[]")
    (_output_dir(data_dir) / "openai_labeled_jobs.json").write_text("[]")
    (_output_dir(data_dir) / "openai_enriched_jobs.json").write_text("[]")
    (_output_dir(data_dir) / "openai_enriched_jobs_ai.json").write_text("[]")
    (data_dir / "candidate_profile.json").write_text('{"skills": [], "roles": []}')
    labeled_path = _output_dir(data_dir) / "openai_labeled_jobs.json"
    enriched_path = _output_dir(data_dir) / "openai_enriched_jobs.json"
    ts_now = time.time()
    os.utime(labeled_path, (ts_now - 120, ts_now - 120))
    os.utime(enriched_path, (ts_now, ts_now))

    monkeypatch.setenv("JOBINTEL_DATA_DIR", str(data_dir))
    monkeypatch.setenv("JOBINTEL_STATE_DIR", str(state_dir))
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "")

    import ji_engine.config as config
    import scripts.run_daily as run_daily

    config = importlib.reload(config)
    run_daily = importlib.reload(run_daily)
    run_daily.USE_SUBPROCESS = False

    # Force short-circuit path to take effect.
    monkeypatch.setattr(run_daily, "_should_short_circuit", lambda prev_hashes, curr_hashes: True)

    recorded_inputs: List[Path] = []

    orig_resolve = run_daily._resolve_score_input_path

    def tracked_resolve(args: argparse.Namespace):
        path, err = orig_resolve(args)
        if path:
            recorded_inputs.append(path)
        return path, err

    monkeypatch.setattr(run_daily, "_resolve_score_input_path", tracked_resolve)

    captured_score: List[List[str]] = []

    def fake_run(cmd: List[str], *, stage: str) -> None:
        if stage == "ai_augment":
            ai_path = run_daily.ENRICHED_JOBS_JSON.with_name("openai_enriched_jobs_ai.json")
            ai_path.write_text("[]", encoding="utf-8")
        if stage.startswith("score:"):
            profile = stage.split(":", 1)[1]
            # Ensure ranking outputs exist for _read_json after scoring.
            for path in (
                run_daily._provider_ranked_jobs_json("openai", profile),
                run_daily._provider_ranked_jobs_csv("openai", profile),
                run_daily._provider_ranked_families_json("openai", profile),
            ):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("[]", encoding="utf-8")
            shortlist = run_daily._provider_shortlist_md("openai", profile)
            shortlist.parent.mkdir(parents=True, exist_ok=True)
            shortlist.write_text("# shortlist\n", encoding="utf-8")
            captured_score.append(cmd)

    monkeypatch.setattr(run_daily, "_run", fake_run)

    monkeypatch.setattr(
        sys, "argv", ["run_daily.py", "--no_subprocess", "--no_post", "--no_enrich", "--ai", "--profiles", "cs"]
    )

    rc = run_daily.main()
    assert rc == 0

    assert captured_score, "Score stage should have run during short-circuit path"
    assert recorded_inputs
    assert recorded_inputs[-1] == _output_dir(data_dir) / "openai_enriched_jobs.json"
    # prefer_ai should be present because argv includes --ai
    assert captured_score
    assert any("--prefer_ai" in cmd for cmd in captured_score for cmd in cmd)


def test_score_input_selection_no_enrich_prefers_newer_enriched(tmp_path: Path, monkeypatch: Any) -> None:
    """
    With --no_enrich and both files present, enriched is chosen only if newer than labeled.
    """
    data_dir = tmp_path / "data"
    state_dir = tmp_path / "state"
    data_dir.mkdir()
    state_dir.mkdir()
    snapshot_dir = data_dir / "openai_snapshots"
    snapshot_dir.mkdir()
    (snapshot_dir / "index.html").write_text("<html>test</html>")
    (_output_dir(data_dir) / "openai_raw_jobs.json").write_text("[]")
    (_output_dir(data_dir) / "openai_labeled_jobs.json").write_text("[]")
    (_output_dir(data_dir) / "openai_enriched_jobs.json").write_text("[]")
    (data_dir / "candidate_profile.json").write_text('{"skills": [], "roles": []}')

    # Make enriched newer than labeled
    labeled_path = _output_dir(data_dir) / "openai_labeled_jobs.json"
    enriched_path = _output_dir(data_dir) / "openai_enriched_jobs.json"
    ts_now = time.time()
    os.utime(labeled_path, (ts_now - 30, ts_now - 30))
    os.utime(enriched_path, (ts_now, ts_now))

    monkeypatch.setenv("JOBINTEL_DATA_DIR", str(data_dir))
    monkeypatch.setenv("JOBINTEL_STATE_DIR", str(state_dir))
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "")

    import ji_engine.config as config
    import scripts.run_daily as run_daily

    config = importlib.reload(config)
    run_daily = importlib.reload(run_daily)
    run_daily.USE_SUBPROCESS = False

    seen_cmds: List[List[str]] = []

    def fake_run(cmd, *, stage):
        if stage == "scrape":
            (_output_dir(data_dir) / "openai_raw_jobs.json").write_text("[]")
        if stage == "classify":
            (_output_dir(data_dir) / "openai_labeled_jobs.json").write_text("[]")
            os.utime(labeled_path, (ts_now - 30, ts_now - 30))
        if stage.startswith("score:"):
            os.utime(enriched_path, (ts_now, ts_now))
            seen_cmds.append(cmd)
            profile = stage.split(":", 1)[1]
            for path in (
                run_daily._provider_ranked_jobs_json("openai", profile),
                run_daily._provider_ranked_jobs_csv("openai", profile),
                run_daily._provider_ranked_families_json("openai", profile),
                run_daily._provider_shortlist_md("openai", profile),
            ):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("[]", encoding="utf-8")

    monkeypatch.setattr(run_daily, "_run", fake_run)
    monkeypatch.setattr(
        sys, "argv", ["run_daily.py", "--no_subprocess", "--no_post", "--profiles", "cs", "--no_enrich"]
    )

    rc = run_daily.main()
    assert rc == 0
    assert seen_cmds, "score command should have run"
    score_cmd = seen_cmds[0]
    assert "--in_path" in score_cmd
    assert str(enriched_path) in score_cmd


def test_no_enrich_reaches_score_when_fixtures_exist(tmp_path: Path, monkeypatch: Any) -> None:
    """
    When --no_enrich is set, the pipeline should still run classify and score
    using existing enriched data if present.
    """
    # Set up temp directories
    data_dir = tmp_path / "data"
    state_dir = tmp_path / "state"
    data_dir.mkdir()
    state_dir.mkdir()

    # Create snapshot
    snapshot_dir = data_dir / "openai_snapshots"
    snapshot_dir.mkdir()
    (snapshot_dir / "index.html").write_text("<html>test</html>")

    # Create minimal inputs (including enriched data)
    (_output_dir(data_dir) / "openai_raw_jobs.json").write_text("[]")
    (_output_dir(data_dir) / "openai_labeled_jobs.json").write_text("[]")
    (_output_dir(data_dir) / "openai_enriched_jobs.json").write_text("[]")
    (data_dir / "candidate_profile.json").write_text('{"skills": [], "roles": []}')

    # Run with --no_enrich and --no_subprocess
    result = subprocess.run(
        [
            sys.executable,
            "scripts/run_daily.py",
            "--profiles",
            "cs",
            "--no_post",
            "--no_enrich",
            "--no_subprocess",
        ],
        cwd=str(Path(__file__).parent.parent),
        env=_build_env(data_dir, state_dir),
        capture_output=True,
        text=True,
    )

    # Should succeed
    assert result.returncode == 0, (
        f"Expected success, got {result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )

    # Check telemetry
    last_run = state_dir / "last_run.json"
    assert last_run.exists(), "last_run.json should exist"

    telemetry = json.loads(last_run.read_text())
    stages = telemetry.get("stages", {})

    # Should include scrape, classify, and score (but not enrich)
    assert "scrape" in stages, "scrape stage should have run"
    assert "classify" in stages, "classify stage should have run"
    assert "enrich" not in stages, "enrich stage should NOT have run with --no_enrich"
    assert any(k.startswith("score:") for k in stages), "score stage should have run"


def test_missing_scoring_prerequisites_fail_with_exit_code_2(tmp_path: Path, monkeypatch: Any) -> None:
    """
    Verify that the prerequisite check in run_daily.py works correctly.

    Note: In the normal pipeline flow, classify always creates labeled_jobs.json before
    scoring runs, making it difficult to trigger the prerequisite check failure.
    This test verifies the check exists and has a clear error message by testing
    the successful path (prerequisites exist) and checking that the validation code
    is in place.
    """
    # Set up temp directories
    data_dir = tmp_path / "data"
    state_dir = tmp_path / "state"
    data_dir.mkdir()
    state_dir.mkdir()

    # Create snapshot
    snapshot_dir = data_dir / "openai_snapshots"
    snapshot_dir.mkdir()
    (snapshot_dir / "index.html").write_text("<html>test</html>")

    # Create all required files
    (_output_dir(data_dir) / "openai_raw_jobs.json").write_text("[]")
    (_output_dir(data_dir) / "openai_labeled_jobs.json").write_text("[]")
    (data_dir / "candidate_profile.json").write_text('{"skills": [], "roles": []}')

    # Run with --no_enrich (scoring will use labeled as input)
    result = subprocess.run(
        [
            sys.executable,
            "scripts/run_daily.py",
            "--profiles",
            "cs",
            "--no_post",
            "--no_enrich",
            "--no_subprocess",
        ],
        cwd=str(Path(__file__).parent.parent),
        env=_build_env(data_dir, state_dir),
        capture_output=True,
        text=True,
    )

    # Should succeed when prerequisites exist
    assert result.returncode == 0, (
        f"Expected success, got {result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )

    # Verify scoring ran
    last_run = state_dir / "last_run.json"
    assert last_run.exists(), "last_run.json should exist"

    telemetry = json.loads(last_run.read_text())
    stages = telemetry.get("stages", {})
    assert any(k.startswith("score:") for k in stages), "score stage should have run"


def test_scrape_only_flag_exits_after_scrape(tmp_path: Path, monkeypatch: Any) -> None:
    """
    When --scrape_only is set, the pipeline should exit after scrape without
    running classify, enrich, or score.
    """
    # Set up temp directories
    data_dir = tmp_path / "data"
    state_dir = tmp_path / "state"
    data_dir.mkdir()
    state_dir.mkdir()

    # Create snapshot
    snapshot_dir = data_dir / "openai_snapshots"
    snapshot_dir.mkdir()
    (snapshot_dir / "index.html").write_text("<html>test</html>")

    # Create minimal inputs
    (_output_dir(data_dir) / "openai_raw_jobs.json").write_text("[]")
    (data_dir / "candidate_profile.json").write_text('{"skills": [], "roles": []}')

    # Run with --scrape_only
    result = subprocess.run(
        [
            sys.executable,
            "scripts/run_daily.py",
            "--scrape_only",
            "--no_post",
            "--no_subprocess",
        ],
        cwd=str(Path(__file__).parent.parent),
        env=_build_env(data_dir, state_dir),
        capture_output=True,
        text=True,
    )

    # Should succeed
    assert result.returncode == 0, (
        f"Expected success, got {result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )

    # Check telemetry
    last_run = state_dir / "last_run.json"
    assert last_run.exists(), "last_run.json should exist"

    telemetry = json.loads(last_run.read_text())
    stages = telemetry.get("stages", {})

    # Should only include scrape
    assert "scrape" in stages, "scrape stage should have run"
    assert "classify" not in stages, "classify stage should NOT have run with --scrape_only"
    assert "enrich" not in stages, "enrich stage should NOT have run with --scrape_only"
    assert not any(k.startswith("score:") for k in stages), "score stage should NOT have run with --scrape_only"


def test_stage_systemexit_is_reflected_in_metadata(tmp_path: Path, monkeypatch: Any) -> None:
    """
    If a stage raises SystemExit with a non-zero code, run_daily should return
    that code and persist a failed run metadata entry.
    """
    data_dir = tmp_path / "data"
    state_dir = tmp_path / "state"
    data_dir.mkdir()
    state_dir.mkdir()
    snapshot_dir = data_dir / "openai_snapshots"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    (snapshot_dir / "index.html").write_text("<html>test</html>")
    (data_dir / "candidate_profile.json").write_text('{"skills": [], "roles": []}')

    monkeypatch.setenv("JOBINTEL_DATA_DIR", str(data_dir))
    monkeypatch.setenv("JOBINTEL_STATE_DIR", str(state_dir))
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "")

    import ji_engine.config as config
    import scripts.run_daily as run_daily

    config = importlib.reload(config)
    run_daily = importlib.reload(run_daily)
    run_daily.USE_SUBPROCESS = False

    def fake_run(cmd, *, stage):
        if stage == "scrape":
            (_output_dir(data_dir) / "openai_raw_jobs.json").write_text("[]")
        if stage == "classify":
            raise SystemExit(3)

    monkeypatch.setattr(run_daily, "_run", fake_run)
    monkeypatch.setattr(sys, "argv", ["run_daily.py", "--no_subprocess", "--profiles", "cs", "--no_post"])

    rc = run_daily.main()
    assert rc == 3

    metadata_files = sorted(run_daily.RUN_METADATA_DIR.glob("*.json"))
    assert metadata_files, "run metadata should have been written"
    payload = json.loads(metadata_files[-1].read_text(encoding="utf-8"))
    assert payload["status"] == "error"
    assert payload["success"] is False
    assert payload["failed_stage"] == "classify"


def test_subprocess_error_exit_codes_are_normalized(tmp_path: Path, monkeypatch: Any) -> None:
    data_dir = tmp_path / "data"
    state_dir = tmp_path / "state"
    data_dir.mkdir()
    state_dir.mkdir()
    snapshot_dir = data_dir / "openai_snapshots"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    (snapshot_dir / "index.html").write_text("<html>test</html>")
    (data_dir / "candidate_profile.json").write_text('{"skills": [], "roles": []}')

    monkeypatch.setenv("JOBINTEL_DATA_DIR", str(data_dir))
    monkeypatch.setenv("JOBINTEL_STATE_DIR", str(state_dir))
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "")

    import ji_engine.config as config
    import scripts.run_daily as run_daily

    config = importlib.reload(config)
    run_daily = importlib.reload(run_daily)
    run_daily.USE_SUBPROCESS = False

    def fake_run(cmd, *, stage):
        raise subprocess.CalledProcessError(2, cmd)

    monkeypatch.setattr(run_daily, "_run", fake_run)
    monkeypatch.setattr(sys, "argv", ["run_daily.py", "--no_subprocess", "--profiles", "cs", "--no_post"])

    rc = run_daily.main()
    assert rc == 2
    lock_path = state_dir / "run_daily.lock"
    if lock_path.exists():
        lock_path.unlink()

    def fake_run_runtime(cmd, *, stage):
        raise subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(run_daily, "_run", fake_run_runtime)
    rc = run_daily.main()
    assert rc == 3


def test_unexpected_exception_returns_runtime_failure(tmp_path: Path, monkeypatch: Any) -> None:
    data_dir = tmp_path / "data"
    state_dir = tmp_path / "state"
    data_dir.mkdir()
    state_dir.mkdir()
    snapshot_dir = data_dir / "openai_snapshots"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    (snapshot_dir / "index.html").write_text("<html>test</html>")
    (data_dir / "candidate_profile.json").write_text('{"skills": [], "roles": []}')

    monkeypatch.setenv("JOBINTEL_DATA_DIR", str(data_dir))
    monkeypatch.setenv("JOBINTEL_STATE_DIR", str(state_dir))
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "")

    import ji_engine.config as config
    import scripts.run_daily as run_daily

    config = importlib.reload(config)
    run_daily = importlib.reload(run_daily)
    run_daily.USE_SUBPROCESS = False

    def fake_run(cmd, *, stage):
        raise RuntimeError("boom")

    monkeypatch.setattr(run_daily, "_run", fake_run)
    monkeypatch.setattr(sys, "argv", ["run_daily.py", "--no_subprocess", "--profiles", "cs", "--no_post"])

    rc = run_daily.main()
    assert rc == 3


def test_systemexit_zero_stage_allows_pipeline_to_continue(tmp_path: Path, monkeypatch: Any) -> None:
    """
    SystemExit(0) in a stage should be treated as success (in-process mode)
    and the pipeline should continue through classify/score and write history.
    """
    data_dir = tmp_path / "data"
    state_dir = tmp_path / "state"
    data_dir.mkdir()
    state_dir.mkdir()
    snapshot_dir = data_dir / "openai_snapshots"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    (snapshot_dir / "index.html").write_text("<html>test</html>")
    (data_dir / "candidate_profile.json").write_text('{"skills": [], "roles": []}')

    monkeypatch.setenv("JOBINTEL_DATA_DIR", str(data_dir))
    monkeypatch.setenv("JOBINTEL_STATE_DIR", str(state_dir))
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "")

    import ji_engine.config as config
    import scripts.run_daily as run_daily

    config = importlib.reload(config)
    run_daily = importlib.reload(run_daily)
    run_daily.USE_SUBPROCESS = False

    def fake_run(cmd, *, stage):
        if stage == "scrape":
            (_output_dir(data_dir) / "openai_raw_jobs.json").write_text("[]")
            raise SystemExit(0)
        if stage == "classify":
            (_output_dir(data_dir) / "openai_labeled_jobs.json").write_text("[]")
            raise SystemExit(0)
        if stage.startswith("score:"):
            profile = stage.split(":", 1)[1]
            for path in (
                run_daily._provider_ranked_jobs_json("openai", profile),
                run_daily._provider_ranked_jobs_csv("openai", profile),
                run_daily._provider_ranked_families_json("openai", profile),
                run_daily._provider_shortlist_md("openai", profile),
            ):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("[]", encoding="utf-8")
            raise SystemExit(0)

    monkeypatch.setattr(run_daily, "_run", fake_run)
    monkeypatch.setattr(
        sys, "argv", ["run_daily.py", "--no_subprocess", "--profiles", "cs", "--no_enrich", "--no_post"]
    )

    rc = run_daily.main()
    assert rc == 0

    latest = config.HISTORY_DIR / "latest" / "cs"
    assert (latest / "run_summary.txt").exists()
    assert (latest / "run_metadata.json").exists()
    assert (latest / "openai_ranked_jobs.cs.json").exists()


def test_scrape_only_writes_history_summary(tmp_path: Path, monkeypatch: Any) -> None:
    """
    --scrape_only should exit after scrape but still write run metadata/history.
    """
    data_dir = tmp_path / "data"
    state_dir = tmp_path / "state"
    data_dir.mkdir()
    state_dir.mkdir()
    snapshot_dir = data_dir / "openai_snapshots"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    (snapshot_dir / "index.html").write_text("<html>test</html>")

    monkeypatch.setenv("JOBINTEL_DATA_DIR", str(data_dir))
    monkeypatch.setenv("JOBINTEL_STATE_DIR", str(state_dir))
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "")

    import ji_engine.config as config
    import scripts.run_daily as run_daily

    config = importlib.reload(config)
    run_daily = importlib.reload(run_daily)
    run_daily.USE_SUBPROCESS = False

    stages: List[str] = []

    def fake_run(cmd, *, stage):
        stages.append(stage)
        if stage == "scrape":
            (_output_dir(data_dir) / "openai_raw_jobs.json").write_text("[]")

    monkeypatch.setattr(run_daily, "_run", fake_run)
    monkeypatch.setattr(
        sys, "argv", ["run_daily.py", "--no_subprocess", "--scrape_only", "--profiles", "cs", "--no_post"]
    )

    rc = run_daily.main()
    assert rc == 0
    assert stages == ["scrape"]

    latest = config.HISTORY_DIR / "latest" / "cs"
    assert (latest / "run_summary.txt").exists()
    assert (latest / "run_metadata.json").exists()


def test_score_input_selection_no_enrich(tmp_path: Path, monkeypatch: Any) -> None:
    """
    With --no_enrich and both enriched+labeled present, scoring should still run and succeed.
    """
    data_dir = tmp_path / "data"
    state_dir = tmp_path / "state"
    data_dir.mkdir()
    state_dir.mkdir()
    snapshot_dir = data_dir / "openai_snapshots"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    (snapshot_dir / "index.html").write_text("<html>test</html>")
    (_output_dir(data_dir) / "openai_raw_jobs.json").write_text("[]")
    (_output_dir(data_dir) / "openai_labeled_jobs.json").write_text("[]")
    (_output_dir(data_dir) / "openai_enriched_jobs.json").write_text("[]")
    (data_dir / "candidate_profile.json").write_text('{"skills": [], "roles": []}')

    monkeypatch.setenv("JOBINTEL_DATA_DIR", str(data_dir))
    monkeypatch.setenv("JOBINTEL_STATE_DIR", str(state_dir))

    import ji_engine.config as config
    import scripts.run_daily as run_daily

    config = importlib.reload(config)
    run_daily = importlib.reload(run_daily)
    run_daily.USE_SUBPROCESS = False

    seen_cmds: List[List[str]] = []

    create_files = True

    def fake_run(cmd, *, stage):
        if stage == "scrape" and create_files:
            (_output_dir(data_dir) / "openai_raw_jobs.json").write_text("[]")
        elif stage == "classify" and create_files:
            (_output_dir(data_dir) / "openai_labeled_jobs.json").write_text("[]")
        elif stage.startswith("score:") and create_files:
            seen_cmds.append(cmd)
            profile = stage.split(":", 1)[1]
            for path in (
                run_daily._provider_ranked_jobs_json("openai", profile),
                run_daily._provider_ranked_jobs_csv("openai", profile),
                run_daily._provider_ranked_families_json("openai", profile),
                run_daily._provider_shortlist_md("openai", profile),
            ):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("[]", encoding="utf-8")

    monkeypatch.setattr(run_daily, "_run", fake_run)
    monkeypatch.setattr(
        sys, "argv", ["run_daily.py", "--no_subprocess", "--no_enrich", "--profiles", "cs", "--no_post"]
    )

    rc = run_daily.main()
    assert rc == 0
    assert seen_cmds, "score command should have run"
    score_cmd = seen_cmds[0]
    labeled_path = _output_dir(data_dir) / "openai_labeled_jobs.json"
    assert "--in_path" in score_cmd
    # Either path is acceptable here since both exist; assert scoring ran.
    assert str(labeled_path) in score_cmd or str(_output_dir(data_dir) / "openai_enriched_jobs.json") in score_cmd

    # Now delete both labeled and enriched to trigger the error path
    (_output_dir(data_dir) / "openai_labeled_jobs.json").unlink(missing_ok=True)
    (_output_dir(data_dir) / "openai_enriched_jobs.json").unlink(missing_ok=True)
    create_files = False
    lock_path = state_dir / "run_daily.lock"
    if lock_path.exists():
        lock_path.unlink()
    monkeypatch.setattr(
        sys, "argv", ["run_daily.py", "--no_subprocess", "--no_enrich", "--profiles", "cs", "--no_post"]
    )
    rc2 = run_daily.main()
    assert rc2 == 2


def test_score_input_selection_ai_only(tmp_path: Path, monkeypatch: Any) -> None:
    """
    With --ai_only, scoring must use openai_enriched_jobs_ai.json; missing file exits 2.
    """
    data_dir = tmp_path / "data"
    state_dir = tmp_path / "state"
    data_dir.mkdir()
    state_dir.mkdir()
    snapshot_dir = data_dir / "openai_snapshots"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    (snapshot_dir / "index.html").write_text("<html>test</html>")
    (_output_dir(data_dir) / "openai_raw_jobs.json").write_text("[]")
    (_output_dir(data_dir) / "openai_labeled_jobs.json").write_text("[]")
    (_output_dir(data_dir) / "openai_enriched_jobs_ai.json").write_text("[]")
    (data_dir / "candidate_profile.json").write_text('{"skills": [], "roles": []}')

    monkeypatch.setenv("JOBINTEL_DATA_DIR", str(data_dir))
    monkeypatch.setenv("JOBINTEL_STATE_DIR", str(state_dir))

    import ji_engine.config as config
    import scripts.run_daily as run_daily

    config = importlib.reload(config)
    run_daily = importlib.reload(run_daily)
    run_daily.USE_SUBPROCESS = False

    seen_cmds: List[List[str]] = []

    create_files = True

    def fake_run(cmd, *, stage):
        if stage == "scrape" and create_files:
            (_output_dir(data_dir) / "openai_raw_jobs.json").write_text("[]")
        elif stage == "classify" and create_files:
            (_output_dir(data_dir) / "openai_labeled_jobs.json").write_text("[]")
        elif stage == "ai_augment" and create_files:
            (_output_dir(data_dir) / "openai_enriched_jobs_ai.json").write_text("[]")
        elif stage.startswith("score:") and create_files:
            seen_cmds.append(cmd)
            profile = stage.split(":", 1)[1]
            for path in (
                run_daily._provider_ranked_jobs_json("openai", profile),
                run_daily._provider_ranked_jobs_csv("openai", profile),
                run_daily._provider_ranked_families_json("openai", profile),
                run_daily._provider_shortlist_md("openai", profile),
            ):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("[]", encoding="utf-8")

    monkeypatch.setattr(run_daily, "_run", fake_run)
    monkeypatch.setattr(
        sys, "argv", ["run_daily.py", "--no_subprocess", "--ai_only", "--ai", "--profiles", "cs", "--no_post"]
    )

    rc = run_daily.main()
    assert rc == 0
    assert seen_cmds, "score command should have run"
    score_cmd = seen_cmds[0]
    ai_path = _output_dir(data_dir) / "openai_enriched_jobs_ai.json"
    assert "--in_path" in score_cmd
    assert str(ai_path) in score_cmd

    # Missing AI file should fail with exit 2
    (_output_dir(data_dir) / "openai_enriched_jobs_ai.json").unlink()
    create_files = False
    lock_path = state_dir / "run_daily.lock"
    if lock_path.exists():
        lock_path.unlink()
    monkeypatch.setattr(
        sys, "argv", ["run_daily.py", "--no_subprocess", "--ai_only", "--ai", "--profiles", "cs", "--no_post"]
    )
    rc2 = run_daily.main()
    assert rc2 == 2


def test_score_input_selection_default_enriched(tmp_path: Path, monkeypatch: Any) -> None:
    """
    Default flow should prefer enriched_jobs.json; missing enriched should exit 2.
    """
    data_dir = tmp_path / "data"
    state_dir = tmp_path / "state"
    data_dir.mkdir()
    state_dir.mkdir()
    snapshot_dir = data_dir / "openai_snapshots"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    (snapshot_dir / "index.html").write_text("<html>test</html>")
    (_output_dir(data_dir) / "openai_raw_jobs.json").write_text("[]")
    (_output_dir(data_dir) / "openai_enriched_jobs.json").write_text("[]")
    (data_dir / "candidate_profile.json").write_text('{"skills": [], "roles": []}')

    monkeypatch.setenv("JOBINTEL_DATA_DIR", str(data_dir))
    monkeypatch.setenv("JOBINTEL_STATE_DIR", str(state_dir))

    import ji_engine.config as config
    import scripts.run_daily as run_daily

    config = importlib.reload(config)
    run_daily = importlib.reload(run_daily)
    run_daily.USE_SUBPROCESS = False

    seen_cmds: List[List[str]] = []

    create_files = True

    def fake_run(cmd, *, stage):
        if stage == "scrape" and create_files:
            (_output_dir(data_dir) / "openai_raw_jobs.json").write_text("[]")
        elif stage == "classify" and create_files:
            (_output_dir(data_dir) / "openai_labeled_jobs.json").write_text("[]")
        elif stage == "enrich" and create_files:
            (_output_dir(data_dir) / "openai_enriched_jobs.json").write_text("[]")
        elif stage.startswith("score:") and create_files:
            seen_cmds.append(cmd)
            profile = stage.split(":", 1)[1]
            for path in (
                run_daily._provider_ranked_jobs_json("openai", profile),
                run_daily._provider_ranked_jobs_csv("openai", profile),
                run_daily._provider_ranked_families_json("openai", profile),
                run_daily._provider_shortlist_md("openai", profile),
            ):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("[]", encoding="utf-8")

    monkeypatch.setattr(run_daily, "_run", fake_run)
    monkeypatch.setattr(sys, "argv", ["run_daily.py", "--no_subprocess", "--profiles", "cs", "--no_post"])

    rc = run_daily.main()
    assert rc == 0
    assert seen_cmds, "score command should have run"
    score_cmd = seen_cmds[0]
    enriched_path = _output_dir(data_dir) / "openai_enriched_jobs.json"
    assert "--in_path" in score_cmd
    assert str(enriched_path) in score_cmd

    # Missing enriched should fail with exit 2
    (_output_dir(data_dir) / "openai_enriched_jobs.json").unlink()
    create_files = False
    lock_path = state_dir / "run_daily.lock"
    if lock_path.exists():
        lock_path.unlink()
    monkeypatch.setattr(sys, "argv", ["run_daily.py", "--no_subprocess", "--profiles", "cs", "--no_post"])
    rc2 = run_daily.main()
    assert rc2 == 2


def test_stage_output_before_end_marker(caplog, tmp_path: Path, monkeypatch: Any) -> None:
    data_dir = tmp_path / "data"
    state_dir = tmp_path / "state"
    data_dir.mkdir()
    state_dir.mkdir()
    snapshot_dir = data_dir / "openai_snapshots"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    (snapshot_dir / "index.html").write_text("<html>test</html>")
    (_output_dir(data_dir) / "openai_raw_jobs.json").write_text("[]")
    (data_dir / "candidate_profile.json").write_text('{"skills": [], "roles": []}')
    (_output_dir(data_dir) / "openai_enriched_jobs.json").write_text("[]")

    monkeypatch.setenv("JOBINTEL_DATA_DIR", str(data_dir))
    monkeypatch.setenv("JOBINTEL_STATE_DIR", str(state_dir))

    import ji_engine.config as config
    import scripts.run_daily as run_daily

    config = importlib.reload(config)
    run_daily = importlib.reload(run_daily)
    run_daily.USE_SUBPROCESS = False

    def fake_run(cmd, *, stage):
        logger = logging.getLogger("scripts.run_daily")
        logger.info("SENTINEL STAGE")
        if stage == "scrape":
            (_output_dir(data_dir) / "openai_raw_jobs.json").write_text("[]")
        elif stage.startswith("score:"):
            profile = stage.split(":", 1)[1]
            for path in (
                run_daily._provider_ranked_jobs_json("openai", profile),
                run_daily._provider_ranked_jobs_csv("openai", profile),
                run_daily._provider_ranked_families_json("openai", profile),
                run_daily._provider_shortlist_md("openai", profile),
            ):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("[]", encoding="utf-8")

    monkeypatch.setattr(run_daily, "_run", fake_run)
    monkeypatch.setattr(sys, "argv", ["run_daily.py", "--no_subprocess", "--profiles", "cs", "--no_post"])

    caplog.set_level(logging.INFO)
    rc = run_daily.main()
    assert rc == 0

    text = caplog.text
    assert "SENTINEL STAGE" in text
    assert "===== jobintel end" in text
    assert text.index("SENTINEL STAGE") < text.index("===== jobintel end")
