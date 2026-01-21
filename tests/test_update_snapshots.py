import json
from pathlib import Path

from scripts import update_snapshots


def test_sha256_file(tmp_path: Path) -> None:
    path = tmp_path / "index.html"
    path.write_text("hello", encoding="utf-8")
    assert update_snapshots._sha256_file(path) == update_snapshots._sha256_bytes(b"hello")


def test_meta_write_and_atomic_overwrite(tmp_path: Path) -> None:
    out_dir = tmp_path / "snapshots"
    html_path = out_dir / "index.html"
    update_snapshots._atomic_write(html_path, b"first")
    update_snapshots._atomic_write(html_path, b"second")
    assert html_path.read_text(encoding="utf-8") == "second"

    payload = update_snapshots._build_meta(
        provider="openai",
        url="https://example.com",
        http_status=200,
        bytes_count=6,
        sha256=update_snapshots._sha256_bytes(b"second"),
        note=None,
    )
    update_snapshots._write_meta(out_dir, payload)
    meta = json.loads((out_dir / "index.meta.json").read_text(encoding="utf-8"))
    assert meta["provider"] == "openai"
    assert meta["url"] == "https://example.com"
    assert meta["http_status"] == 200
    assert meta["bytes"] == 6
    assert meta["sha256"] == update_snapshots._sha256_bytes(b"second")
