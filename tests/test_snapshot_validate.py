from pathlib import Path

from jobintel.snapshots.validate import validate_snapshot_bytes, validate_snapshot_file


def test_validate_snapshot_missing_file(tmp_path: Path) -> None:
    path = tmp_path / "index.html"
    ok, reason = validate_snapshot_file("openai", path)
    assert ok is False
    assert reason == "missing file"


def test_validate_snapshot_too_small(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("JOBINTEL_SNAPSHOT_MIN_BYTES_OPENAI", "500")
    path = tmp_path / "index.html"
    path.write_text("<html></html>", encoding="utf-8")
    ok, reason = validate_snapshot_file("openai", path)
    assert ok is False
    assert "too small" in reason


def test_validate_snapshot_blocked_marker(tmp_path: Path) -> None:
    path = tmp_path / "index.html"
    blocked_html = "<html>Access denied " + ("x" * 600) + "</html>"
    path.write_text(blocked_html, encoding="utf-8")
    ok, reason = validate_snapshot_file("openai", path)
    assert ok is False
    assert "blocked marker" in reason


def test_validate_snapshot_bytes_ok(monkeypatch) -> None:
    monkeypatch.setenv("JOBINTEL_SNAPSHOT_MIN_BYTES_OPENAI", "0")
    ok, reason = validate_snapshot_bytes(
        "openai",
        b"<!doctype html><html>jobs.ashbyhq.com</html>",
    )
    assert ok is True
    assert reason == "ok"


def test_validate_snapshot_marker_small_ok(monkeypatch) -> None:
    monkeypatch.setenv("JOBINTEL_SNAPSHOT_MIN_BYTES_OPENAI", "500")
    payload = "<html>jobs.ashbyhq.com</html>".encode("utf-8")
    payload = payload + (b" " * 600)
    ok, reason = validate_snapshot_bytes("openai", payload)
    assert ok is True
    assert reason == "ok"


def test_validate_snapshot_marker_missing_fails(monkeypatch) -> None:
    monkeypatch.setenv("JOBINTEL_SNAPSHOT_MIN_BYTES_ASHBY", "500")
    payload = "<html>no markers here</html>".encode("utf-8")
    payload = payload + (b"x" * 7000)
    ok, reason = validate_snapshot_bytes("ashby", payload)
    assert ok is False
    assert "missing ashby markers" in reason


def test_validate_snapshot_cloudflare_rejected(monkeypatch) -> None:
    monkeypatch.setenv("JOBINTEL_SNAPSHOT_MIN_BYTES_OPENAI", "500")
    payload = "<html><title>Just a moment...</title>cf_chl_opt</html>".encode("utf-8")
    payload = payload + (b" " * 2000)
    ok, reason = validate_snapshot_bytes("openai", payload)
    assert ok is False
    assert "cloudflare" in reason
