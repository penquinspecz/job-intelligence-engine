import importlib
import json
import sys
from pathlib import Path


def test_run_daily_error_skips_publish(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("JOBINTEL_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("JOBINTEL_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("CAREERS_MODE", "SNAPSHOT")
    monkeypatch.setenv("PUBLISH_S3", "1")
    monkeypatch.setenv("JOBINTEL_S3_BUCKET", "bucket")
    monkeypatch.setenv("JOBINTEL_S3_PREFIX", "jobintel")

    import ji_engine.config as config
    import scripts.run_daily as run_daily

    importlib.reload(config)
    run_daily = importlib.reload(run_daily)
    run_daily.USE_SUBPROCESS = False
    run_daily.LOCK_PATH = Path(tmp_path / "state" / "run_daily.lock")

    snapshot_path = Path(tmp_path / "data" / "openai_snapshots" / "index.html")
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_path.write_text("<html></html>", encoding="utf-8")

    publish_called = {"value": False}

    def fake_publish_run(**_kwargs):
        publish_called["value"] = True
        raise AssertionError("publish_run should not be called on error")

    monkeypatch.setattr(run_daily.publish_s3, "publish_run", fake_publish_run)

    def fake_run(*_args, **_kwargs):
        raise SystemExit(2)

    monkeypatch.setattr(run_daily, "_run", fake_run)
    monkeypatch.setattr(
        sys,
        "argv",
        ["run_daily.py", "--no_subprocess", "--profiles", "cs", "--providers", "openai", "--no_post"],
    )

    rc = run_daily.main()
    assert rc == 2
    assert publish_called["value"] is False

    metadata_files = sorted(run_daily.RUN_METADATA_DIR.glob("*.json"))
    assert metadata_files
    data = json.loads(metadata_files[-1].read_text(encoding="utf-8"))
    publish_section = data.get("publish") or {}
    assert publish_section.get("enabled") is False
    assert publish_section.get("skip_reason") == "skipped_status_error"
