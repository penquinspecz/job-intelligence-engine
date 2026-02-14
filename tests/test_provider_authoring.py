from __future__ import annotations

import json
from pathlib import Path

import pytest

from ji_engine.providers.registry import load_providers_config
from ji_engine.utils.verification import compute_sha256_file
from scripts import provider_authoring


def _provider_entry(provider_id: str, snapshot_path: Path) -> dict[str, object]:
    return {
        "provider_id": provider_id,
        "display_name": provider_id.upper(),
        "enabled": True,
        "careers_urls": [f"https://{provider_id}.example.com/careers"],
        "allowed_domains": [f"{provider_id}.example.com"],
        "extraction_mode": "jsonld",
        "mode": "snapshot",
        "snapshot_enabled": True,
        "live_enabled": False,
        "snapshot_path": str(snapshot_path),
        "snapshot_dir": str(snapshot_path.parent),
        "update_cadence": {"min_interval_hours": 24, "priority": "normal"},
        "politeness": {"min_delay_s": 1.0, "max_attempts": 2},
    }


def test_template_command_outputs_schema_valid_entry(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = provider_authoring.main(["template", "--provider-id", "exampleco"])
    assert rc == 0
    rendered = capsys.readouterr().out
    entry = json.loads(rendered)
    assert entry["provider_id"] == "exampleco"
    assert entry["live_enabled"] is False
    assert entry["mode"] == "snapshot"
    payload = {"schema_version": 1, "providers": [entry]}
    temp = tmp_path / "providers.json"
    try:
        temp.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        loaded = load_providers_config(temp)
    finally:
        temp.unlink(missing_ok=True)
    assert loaded[0]["provider_id"] == "exampleco"


def test_scaffold_creates_snapshot_placeholder(tmp_path: Path) -> None:
    rc = provider_authoring.main(
        [
            "scaffold",
            "--provider-id",
            "acme",
            "--data-dir",
            str(tmp_path),
        ]
    )
    assert rc == 0
    expected = tmp_path / "acme_snapshots" / "index.html"
    assert expected.exists()
    body = expected.read_text(encoding="utf-8")
    assert "acme snapshot placeholder" in body
    assert "update_snapshots.py --provider acme" in body


def test_scaffold_refuses_overwrite_without_force(tmp_path: Path) -> None:
    target = tmp_path / "acme_snapshots" / "index.html"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("original", encoding="utf-8")
    with pytest.raises(FileExistsError, match="Refusing to overwrite existing fixture"):
        provider_authoring.main(
            [
                "scaffold",
                "--provider-id",
                "acme",
                "--data-dir",
                str(tmp_path),
            ]
        )


def test_update_snapshot_manifest_is_provider_scoped(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    alpha_snapshot = tmp_path / "data" / "alpha_snapshots" / "index.html"
    beta_snapshot = tmp_path / "data" / "beta_snapshots" / "index.html"
    alpha_snapshot.parent.mkdir(parents=True, exist_ok=True)
    beta_snapshot.parent.mkdir(parents=True, exist_ok=True)
    alpha_snapshot.write_text("alpha v2", encoding="utf-8")
    beta_snapshot.write_text("beta v1", encoding="utf-8")

    providers_path = tmp_path / "providers.json"
    providers_payload = {
        "schema_version": 1,
        "providers": [
            _provider_entry("alpha", alpha_snapshot),
            _provider_entry("beta", beta_snapshot),
        ],
    }
    providers_path.write_text(json.dumps(providers_payload, indent=2, sort_keys=True), encoding="utf-8")

    manifest_path = tmp_path / "snapshot_bytes.manifest.json"
    baseline_manifest = {
        str(alpha_snapshot): {"sha256": "old-alpha", "bytes": 123},
        str(beta_snapshot): {"sha256": "old-beta", "bytes": 456},
    }
    manifest_path.write_text(json.dumps(baseline_manifest, indent=2, sort_keys=True), encoding="utf-8")

    rc = provider_authoring.main(
        [
            "update-snapshot-manifest",
            "--provider",
            "alpha",
            "--providers-config",
            str(providers_path),
            "--manifest-path",
            str(manifest_path),
        ]
    )
    assert rc == 0

    output = capsys.readouterr().out
    assert "THIS IS A DETERMINISM BASELINE CHANGE; REVIEW REQUIRED" in output

    updated = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert set(updated.keys()) == {str(alpha_snapshot), str(beta_snapshot)}
    assert updated[str(alpha_snapshot)]["sha256"] == compute_sha256_file(alpha_snapshot)
    assert updated[str(alpha_snapshot)]["bytes"] == alpha_snapshot.stat().st_size
    assert updated[str(beta_snapshot)] == baseline_manifest[str(beta_snapshot)]


def test_update_snapshot_manifest_is_deterministic_for_repeated_runs(tmp_path: Path) -> None:
    snapshot = tmp_path / "data" / "alpha_snapshots" / "index.html"
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    snapshot.write_text("same bytes every run", encoding="utf-8")

    providers_path = tmp_path / "providers.json"
    providers_payload = {"schema_version": 1, "providers": [_provider_entry("alpha", snapshot)]}
    providers_path.write_text(json.dumps(providers_payload, indent=2, sort_keys=True), encoding="utf-8")

    manifest_path = tmp_path / "snapshot_bytes.manifest.json"
    manifest_path.write_text("{}\n", encoding="utf-8")

    first_rc = provider_authoring.main(
        [
            "update-snapshot-manifest",
            "--provider",
            "alpha",
            "--providers-config",
            str(providers_path),
            "--manifest-path",
            str(manifest_path),
        ]
    )
    assert first_rc == 0
    first_bytes = manifest_path.read_bytes()

    second_rc = provider_authoring.main(
        [
            "update-snapshot-manifest",
            "--provider",
            "alpha",
            "--providers-config",
            str(providers_path),
            "--manifest-path",
            str(manifest_path),
        ]
    )
    assert second_rc == 0
    second_bytes = manifest_path.read_bytes()

    assert second_bytes == first_bytes


def test_update_snapshot_manifest_fails_when_snapshot_missing(tmp_path: Path) -> None:
    missing_snapshot = tmp_path / "data" / "alpha_snapshots" / "index.html"

    providers_path = tmp_path / "providers.json"
    providers_payload = {"schema_version": 1, "providers": [_provider_entry("alpha", missing_snapshot)]}
    providers_path.write_text(json.dumps(providers_payload, indent=2, sort_keys=True), encoding="utf-8")

    manifest_path = tmp_path / "snapshot_bytes.manifest.json"
    manifest_path.write_text("{}\n", encoding="utf-8")

    with pytest.raises(FileNotFoundError, match="snapshot fixture not found"):
        provider_authoring.main(
            [
                "update-snapshot-manifest",
                "--provider",
                "alpha",
                "--providers-config",
                str(providers_path),
                "--manifest-path",
                str(manifest_path),
            ]
        )
