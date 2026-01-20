from pathlib import Path

import scripts.add_snapshot as add_snapshot


def test_add_snapshot_copies_html(tmp_path: Path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    monkeypatch.setattr(add_snapshot, "DATA_DIR", data_dir)

    src = tmp_path / "source.html"
    src.write_text("<html>ok</html>", encoding="utf-8")

    rc = add_snapshot.main(["--provider", "openai", "--from-file", str(src)])
    assert rc == 0

    dest = data_dir / "openai_snapshots" / "index.html"
    assert dest.exists()
    assert dest.read_text(encoding="utf-8") == "<html>ok</html>"
    assert not (data_dir / "openai_snapshots" / "metadata.json").exists()


def test_add_snapshot_writes_metadata(tmp_path: Path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    monkeypatch.setattr(add_snapshot, "DATA_DIR", data_dir)

    src = tmp_path / "source.html"
    src.write_text("<html>meta</html>", encoding="utf-8")

    rc = add_snapshot.main(
        ["--provider", "openai", "--from-file", str(src), "--write-metadata"]
    )
    assert rc == 0
    meta = data_dir / "openai_snapshots" / "metadata.json"
    assert meta.exists()
