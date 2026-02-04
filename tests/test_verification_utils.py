from __future__ import annotations

from pathlib import Path

from ji_engine.utils import verification


def test_compute_sha256_bytes_stable() -> None:
    assert (
        verification.compute_sha256_bytes(b"abc") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )


def test_compute_sha256_file_stable(tmp_path: Path) -> None:
    path = tmp_path / "data.txt"
    path.write_text("hello", encoding="utf-8")
    first = verification.compute_sha256_file(path)
    second = verification.compute_sha256_file(path)
    assert first == second


def test_verify_verifiable_artifacts_reports_mismatch(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir(parents=True)
    artifact = run_dir / "artifact.json"
    artifact.write_text("[]", encoding="utf-8")
    verifiable = {
        "openai:cs:ranked_json": {
            "path": "artifact.json",
            "sha256": "0" * 64,
            "bytes": 2,
            "hash_algo": "sha256",
        }
    }
    ok, mismatches = verification.verify_verifiable_artifacts(run_dir, verifiable)
    assert ok is False
    assert mismatches
    assert mismatches[0]["label"] == "openai:cs:ranked_json"
