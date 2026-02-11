from pathlib import Path

from jobintel.snapshots.validate import validate_snapshot_bytes, validate_snapshot_file, validate_snapshots


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


def test_validate_snapshot_json_ok() -> None:
    ok, reason = validate_snapshot_bytes(
        "alpha",
        b'[{"title": "Role", "apply_url": "https://example.com/jobs/1"}]',
        extraction_mode="snapshot_json",
    )
    assert ok is True
    assert reason == "ok"


def test_validate_snapshot_file_accepts_type_alias(tmp_path: Path) -> None:
    path = tmp_path / "index.json"
    path.write_text(
        '[{"title": "Role", "apply_url": "https://example.com/jobs/1"}]',
        encoding="utf-8",
    )
    ok, reason = validate_snapshot_file("alpha", path, type="snapshot_json")
    assert ok is True
    assert reason == "ok"


def test_validate_snapshot_file_rejects_unknown_kwargs(tmp_path: Path) -> None:
    path = tmp_path / "index.json"
    path.write_text(
        '[{"title": "Role", "apply_url": "https://example.com/jobs/1"}]',
        encoding="utf-8",
    )
    try:
        validate_snapshot_file("alpha", path, bogus="value")
    except TypeError as exc:
        assert "unexpected keyword argument" in str(exc)
    else:
        raise AssertionError("expected TypeError for unknown keyword args")


def test_validate_snapshots_all_skips_missing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("JOBINTEL_SNAPSHOT_MIN_BYTES", "0")
    providers_cfg = [
        {
            "provider_id": "alpha",
            "careers_urls": ["https://alpha.example/jobs"],
            "extraction_mode": "jsonld",
            "snapshot_path": "data/alpha_snapshots/index.html",
            "snapshot_enabled": True,
        },
        {
            "provider_id": "beta",
            "careers_urls": ["https://beta.example/jobs"],
            "extraction_mode": "jsonld",
            "snapshot_path": "data/beta_snapshots/index.html",
            "snapshot_enabled": True,
        },
    ]
    alpha_dir = tmp_path / "alpha_snapshots"
    alpha_dir.mkdir(parents=True, exist_ok=True)
    (alpha_dir / "index.html").write_text(
        "<html><script type='application/ld+json'>[]</script>ok</html>",
        encoding="utf-8",
    )

    results = validate_snapshots(
        providers_cfg,
        validate_all=True,
        data_dir=tmp_path,
    )

    status_map = {result.provider: result for result in results}
    assert status_map["alpha"].ok is True
    assert status_map["alpha"].skipped is False
    assert status_map["beta"].skipped is True


def test_validate_snapshots_skips_disabled_provider(tmp_path: Path) -> None:
    providers_cfg = [
        {
            "provider_id": "alpha",
            "careers_urls": ["https://alpha.example/jobs"],
            "extraction_mode": "jsonld",
            "snapshot_path": "data/alpha_snapshots/index.html",
            "snapshot_enabled": False,
        }
    ]
    results = validate_snapshots(
        providers_cfg,
        provider_ids=["alpha"],
        data_dir=tmp_path,
    )
    assert results[0].skipped is True
    assert results[0].reason == "skipped: snapshot_disabled"
