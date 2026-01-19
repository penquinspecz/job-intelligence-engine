import os
from pathlib import Path

import scripts.prune_state as prune_state


def _touch(path: Path, content: str = "{}") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_prune_state_dry_run_is_deterministic(tmp_path: Path, capsys, monkeypatch) -> None:
    state_dir = tmp_path / "state"
    runs_dir = state_dir / "runs"
    history_dir = state_dir / "history"
    (history_dir / "latest" / "cs").mkdir(parents=True, exist_ok=True)

    # 3 run reports, keep 2 -> prune oldest, but never newest
    _touch(runs_dir / "20260101T000000Z.json")
    _touch(runs_dir / "20260102T000000Z.json")
    _touch(runs_dir / "20260103T000000Z.json")

    # 3 history snapshots, keep 2 -> prune oldest, but never newest
    (history_dir / "2026-01-01" / "20260101T000000Z" / "cs").mkdir(parents=True, exist_ok=True)
    (history_dir / "2026-01-02" / "20260102T000000Z" / "cs").mkdir(parents=True, exist_ok=True)
    (history_dir / "2026-01-03" / "20260103T000000Z" / "cs").mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("JOBINTEL_STATE_DIR", str(state_dir))
    rc = prune_state.main(["--dry-run", "--keep-runs", "2", "--keep-history", "2", "--max-age-days", "0"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "20260101T000000Z.json" in out
    assert str(history_dir / "2026-01-01" / "20260101T000000Z" / "cs") in out


def test_prune_state_apply_deletes_expected(tmp_path: Path, monkeypatch) -> None:
    state_dir = tmp_path / "state"
    runs_dir = state_dir / "runs"
    history_dir = state_dir / "history"
    (history_dir / "latest" / "cs").mkdir(parents=True, exist_ok=True)

    _touch(runs_dir / "20260101T000000Z.json")
    _touch(runs_dir / "20260102T000000Z.json")
    _touch(runs_dir / "20260103T000000Z.json")

    old_hist = history_dir / "2026-01-01" / "20260101T000000Z" / "cs"
    new_hist = history_dir / "2026-01-03" / "20260103T000000Z" / "cs"
    old_hist.mkdir(parents=True, exist_ok=True)
    new_hist.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("JOBINTEL_STATE_DIR", str(state_dir))
    rc = prune_state.main(["--apply", "--keep-runs", "2", "--keep-history", "1", "--max-age-days", "0"])
    assert rc == 0

    assert not (runs_dir / "20260101T000000Z.json").exists()
    assert (runs_dir / "20260103T000000Z.json").exists()
    assert not old_hist.exists()
    assert new_hist.exists()


def test_prune_state_profile_limits_history(tmp_path: Path, monkeypatch) -> None:
    state_dir = tmp_path / "state"
    runs_dir = state_dir / "runs"
    history_dir = state_dir / "history"
    (history_dir / "latest" / "cs").mkdir(parents=True, exist_ok=True)
    (history_dir / "latest" / "tam").mkdir(parents=True, exist_ok=True)

    _touch(runs_dir / "20260101T000000Z.json")
    _touch(runs_dir / "20260102T000000Z.json")

    cs_old = history_dir / "2026-01-01" / "20260101T000000Z" / "cs"
    cs_new = history_dir / "2026-01-02" / "20260102T000000Z" / "cs"
    tam_old = history_dir / "2026-01-01" / "20260101T000000Z" / "tam"
    tam_new = history_dir / "2026-01-02" / "20260102T000000Z" / "tam"
    for p in (cs_old, cs_new, tam_old, tam_new):
        p.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("JOBINTEL_STATE_DIR", str(state_dir))
    rc = prune_state.main(["--apply", "--keep-history", "1", "--keep-runs", "1", "--max-age-days", "0", "--profile", "cs"])
    assert rc == 0

    assert not cs_old.exists()
    assert cs_new.exists()
    assert tam_old.exists()
    assert tam_new.exists()
