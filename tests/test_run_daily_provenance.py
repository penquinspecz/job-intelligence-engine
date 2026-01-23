import importlib
import json
import sys
from pathlib import Path

import ji_engine.config as config
import scripts.run_daily as run_daily_module
import scripts.run_scrape as run_scrape_module


def test_run_daily_metadata_includes_provenance(tmp_path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    state_dir = tmp_path / "state"
    monkeypatch.setenv("JOBINTEL_DATA_DIR", str(data_dir))
    monkeypatch.setenv("JOBINTEL_STATE_DIR", str(state_dir))
    monkeypatch.setenv("CAREERS_MODE", "SNAPSHOT")
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "")
    importlib.reload(config)
    run_daily = importlib.reload(run_daily_module)
    run_scrape = importlib.reload(run_scrape_module)

    snapshot_src = Path("data/openai_snapshots/index.html")
    snapshot_dest = data_dir / "openai_snapshots" / "index.html"
    snapshot_dest.parent.mkdir(parents=True, exist_ok=True)
    snapshot_dest.write_text(snapshot_src.read_text(encoding="utf-8"), encoding="utf-8")

    def fake_scrape_live(self):
        raise RuntimeError("Live scrape failed with status 403 at https://openai.com/careers/search/")

    monkeypatch.setattr(run_scrape.OpenAICareersProvider, "scrape_live", fake_scrape_live)

    def fake_run(cmd, *, stage: str):
        argv = cmd[1:] if cmd and cmd[0] == sys.executable else cmd
        script_path = Path(argv[0]).name if argv else ""
        if script_path == "run_scrape.py":
            sys.argv = [script_path, *argv[1:]]
            rc = run_scrape.main()
            if rc not in (None, 0):
                raise SystemExit(rc)
            return
        raise RuntimeError(f"Unexpected stage {stage}")

    monkeypatch.setattr(run_daily, "_run", fake_run)
    monkeypatch.setattr(
        sys,
        "argv",
        ["run_daily.py", "--no_subprocess", "--scrape_only", "--providers", "openai", "--profiles", "cs"],
    )
    rc = run_daily.main()
    assert rc == 0

    metadata_files = sorted(run_daily.RUN_METADATA_DIR.glob("*.json"))
    assert metadata_files
    data = json.loads(metadata_files[-1].read_text(encoding="utf-8"))
    provenance = data["provenance_by_provider"]["openai"]
    assert provenance["provider"] == "openai"
    assert provenance["scrape_mode"] == "snapshot"
    assert provenance["availability"] == "available"
    assert provenance["attempts_made"] >= 1
    assert provenance["snapshot_path"]
    assert provenance["snapshot_sha256"]
    assert provenance["parsed_job_count"] > 0
