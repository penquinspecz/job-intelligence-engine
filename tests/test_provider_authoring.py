from __future__ import annotations

import json
from pathlib import Path

import pytest

from ji_engine.providers.registry import load_providers_config
from ji_engine.utils.verification import compute_sha256_file
from scripts import provider_authoring


def _provider_entry(
    provider_id: str, snapshot_path: Path, *, enabled: bool = True, extraction_mode: str = "jsonld"
) -> dict[str, object]:
    return {
        "provider_id": provider_id,
        "display_name": provider_id.upper(),
        "enabled": enabled,
        "careers_urls": [f"https://{provider_id}.example.com/careers"],
        "allowed_domains": [f"{provider_id}.example.com"],
        "extraction_mode": extraction_mode,
        "mode": "snapshot",
        "snapshot_enabled": True,
        "live_enabled": False,
        "snapshot_path": str(snapshot_path),
        "snapshot_dir": str(snapshot_path.parent),
        "update_cadence": {"min_interval_hours": 24, "priority": "normal"},
        "politeness": {"min_delay_s": 1.0, "max_attempts": 2},
    }


def _write_providers_config(path: Path, providers: list[dict[str, object]]) -> None:
    payload = {"schema_version": 1, "providers": providers}
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _manifest_entry(path: Path) -> dict[str, object]:
    return {"sha256": compute_sha256_file(path), "bytes": path.stat().st_size}


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
    _write_providers_config(
        providers_path,
        [_provider_entry("alpha", alpha_snapshot), _provider_entry("beta", beta_snapshot)],
    )

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
    _write_providers_config(providers_path, [_provider_entry("alpha", snapshot)])

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
    _write_providers_config(providers_path, [_provider_entry("alpha", missing_snapshot)])

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


def test_validate_provider_output_is_deterministic(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    snapshot = tmp_path / "data" / "alpha_snapshots" / "index.html"
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    snapshot.write_text("alpha fixture", encoding="utf-8")

    providers_path = tmp_path / "providers.json"
    _write_providers_config(providers_path, [_provider_entry("alpha", snapshot, enabled=False)])

    manifest_path = tmp_path / "snapshot_bytes.manifest.json"
    manifest_path.write_text(
        json.dumps({str(snapshot): _manifest_entry(snapshot)}, indent=2, sort_keys=True), encoding="utf-8"
    )

    args = [
        "validate-provider",
        "--provider",
        "alpha",
        "--providers-config",
        str(providers_path),
        "--manifest-path",
        str(manifest_path),
        "--providers-schema",
        str(Path("schemas/providers.schema.v1.json")),
    ]
    first_rc = provider_authoring.main(args)
    first_out = capsys.readouterr().out
    second_rc = provider_authoring.main(args)
    second_out = capsys.readouterr().out

    assert first_rc == 0
    assert second_rc == 0
    assert first_out == second_out
    assert "status=PASS" in first_out


def test_enable_refuses_without_i_mean_it(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    snapshot = tmp_path / "data" / "alpha_snapshots" / "index.html"
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    snapshot.write_text("alpha fixture", encoding="utf-8")

    providers_path = tmp_path / "providers.json"
    _write_providers_config(providers_path, [_provider_entry("alpha", snapshot, enabled=False)])

    manifest_path = tmp_path / "snapshot_bytes.manifest.json"
    manifest_path.write_text(
        json.dumps({str(snapshot): _manifest_entry(snapshot)}, indent=2, sort_keys=True), encoding="utf-8"
    )

    rc = provider_authoring.main(
        [
            "enable",
            "--provider",
            "alpha",
            "--why",
            "ready for controlled rollout",
            "--providers-config",
            str(providers_path),
            "--manifest-path",
            str(manifest_path),
            "--providers-schema",
            str(Path("schemas/providers.schema.v1.json")),
        ]
    )
    output = capsys.readouterr().out

    assert rc == 2
    assert "ENABLEMENT CHECKLIST" in output
    assert "refusing to edit providers config without --i-mean-it" in output

    payload = json.loads(providers_path.read_text(encoding="utf-8"))
    assert payload["providers"][0]["enabled"] is False


def test_enable_refuses_when_snapshot_manifest_missing_or_fixture_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing_snapshot = tmp_path / "data" / "alpha_snapshots" / "index.html"

    providers_path = tmp_path / "providers.json"
    _write_providers_config(providers_path, [_provider_entry("alpha", missing_snapshot, enabled=False)])

    manifest_path = tmp_path / "missing.manifest.json"

    rc = provider_authoring.main(
        [
            "enable",
            "--provider",
            "alpha",
            "--why",
            "missing fixture should block",
            "--providers-config",
            str(providers_path),
            "--manifest-path",
            str(manifest_path),
            "--providers-schema",
            str(Path("schemas/providers.schema.v1.json")),
            "--i-mean-it",
        ]
    )
    output = capsys.readouterr().out

    assert rc == 1
    assert "[FAIL] snapshot_fixture_exists" in output
    assert "[FAIL] snapshot_manifest_entry" in output

    payload = json.loads(providers_path.read_text(encoding="utf-8"))
    assert payload["providers"][0]["enabled"] is False


def test_enable_refuses_when_extraction_mode_invalid(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    snapshot = tmp_path / "data" / "alpha_snapshots" / "index.html"
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    snapshot.write_text("alpha fixture", encoding="utf-8")

    providers_path = tmp_path / "providers.json"
    _write_providers_config(
        providers_path, [_provider_entry("alpha", snapshot, enabled=False, extraction_mode="bogus")]
    )

    manifest_path = tmp_path / "snapshot_bytes.manifest.json"
    manifest_path.write_text(
        json.dumps({str(snapshot): _manifest_entry(snapshot)}, indent=2, sort_keys=True), encoding="utf-8"
    )

    rc = provider_authoring.main(
        [
            "enable",
            "--provider",
            "alpha",
            "--why",
            "invalid extraction mode should fail",
            "--providers-config",
            str(providers_path),
            "--manifest-path",
            str(manifest_path),
            "--providers-schema",
            str(Path("schemas/providers.schema.v1.json")),
            "--i-mean-it",
        ]
    )
    output = capsys.readouterr().out

    assert rc == 1
    assert "[FAIL] extraction_mode_valid" in output


def test_enable_sets_enabled_true_with_i_mean_it(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    snapshot = tmp_path / "data" / "alpha_snapshots" / "index.html"
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    snapshot.write_text("alpha fixture", encoding="utf-8")

    providers_path = tmp_path / "providers.json"
    _write_providers_config(providers_path, [_provider_entry("alpha", snapshot, enabled=False)])

    manifest_path = tmp_path / "snapshot_bytes.manifest.json"
    manifest_path.write_text(
        json.dumps({str(snapshot): _manifest_entry(snapshot)}, indent=2, sort_keys=True), encoding="utf-8"
    )

    rc = provider_authoring.main(
        [
            "enable",
            "--provider",
            "alpha",
            "--why",
            "all checks pass",
            "--providers-config",
            str(providers_path),
            "--manifest-path",
            str(manifest_path),
            "--providers-schema",
            str(Path("schemas/providers.schema.v1.json")),
            "--i-mean-it",
        ]
    )
    output = capsys.readouterr().out

    assert rc == 0
    assert "enabled provider 'alpha'" in output

    payload = json.loads(providers_path.read_text(encoding="utf-8"))
    assert payload["providers"][0]["enabled"] is True


def test_enable_output_is_deterministic_without_i_mean_it(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    snapshot = tmp_path / "data" / "alpha_snapshots" / "index.html"
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    snapshot.write_text("alpha fixture", encoding="utf-8")

    providers_path = tmp_path / "providers.json"
    _write_providers_config(providers_path, [_provider_entry("alpha", snapshot, enabled=False)])

    manifest_path = tmp_path / "snapshot_bytes.manifest.json"
    manifest_path.write_text(
        json.dumps({str(snapshot): _manifest_entry(snapshot)}, indent=2, sort_keys=True), encoding="utf-8"
    )

    args = [
        "enable",
        "--provider",
        "alpha",
        "--why",
        "dry run output determinism",
        "--providers-config",
        str(providers_path),
        "--manifest-path",
        str(manifest_path),
        "--providers-schema",
        str(Path("schemas/providers.schema.v1.json")),
    ]

    first_rc = provider_authoring.main(args)
    first_out = capsys.readouterr().out
    second_rc = provider_authoring.main(args)
    second_out = capsys.readouterr().out

    assert first_rc == 2
    assert second_rc == 2
    assert first_out == second_out


def test_append_template_refuses_without_i_mean_it(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config_path = tmp_path / "providers.json"
    _write_providers_config(config_path, [])

    rc = provider_authoring.main(
        [
            "append-template",
            "--provider",
            "acme",
            "--config",
            str(config_path),
            "--why",
            "initial template for review",
            "--careers-url",
            "https://acme.example.com/careers",
            "--allowed-domain",
            "acme.example.com",
        ]
    )
    output = capsys.readouterr().out
    assert rc == 2
    assert "refusing to edit providers config without --i-mean-it" in output
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    assert payload["providers"] == []


def test_append_template_refuses_if_provider_exists(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    snapshot = tmp_path / "data" / "alpha_snapshots" / "index.html"
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    snapshot.write_text("fixture", encoding="utf-8")
    config_path = tmp_path / "providers.json"
    _write_providers_config(config_path, [_provider_entry("alpha", snapshot)])

    rc = provider_authoring.main(
        [
            "append-template",
            "--provider",
            "alpha",
            "--config",
            str(config_path),
            "--why",
            "should fail duplicate",
            "--careers-url",
            "https://alpha.example.com/careers",
            "--allowed-domain",
            "alpha.example.com",
            "--i-mean-it",
        ]
    )
    output = capsys.readouterr().out
    assert rc == 1
    assert "already exists" in output


def test_append_template_refuses_without_required_domains_or_urls(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = tmp_path / "providers.json"
    _write_providers_config(config_path, [])

    rc = provider_authoring.main(
        [
            "append-template",
            "--provider",
            "acme",
            "--config",
            str(config_path),
            "--why",
            "missing lists should fail",
            "--i-mean-it",
        ]
    )
    output = capsys.readouterr().out
    assert rc == 1
    assert "careers_urls must be provided" in output


def test_append_template_appends_disabled_provider_deterministically(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    beta_snapshot = tmp_path / "data" / "beta_snapshots" / "index.html"
    beta_snapshot.parent.mkdir(parents=True, exist_ok=True)
    beta_snapshot.write_text("fixture", encoding="utf-8")
    config_path = tmp_path / "providers.json"
    _write_providers_config(config_path, [_provider_entry("beta", beta_snapshot, enabled=False)])

    rc = provider_authoring.main(
        [
            "append-template",
            "--provider",
            "alpha",
            "--config",
            str(config_path),
            "--why",
            "review gate",
            "--careers-url",
            "https://alpha.example.com/careers",
            "--allowed-domain",
            "alpha.example.com",
            "--i-mean-it",
        ]
    )
    assert rc == 0
    output = capsys.readouterr().out
    assert "enabled=false (hard guardrail)" in output
    assert "entry_enabled=False" in output

    payload = json.loads(config_path.read_text(encoding="utf-8"))
    providers = payload["providers"]
    assert [entry["provider_id"] for entry in providers] == ["alpha", "beta"]
    alpha = providers[0]
    assert alpha["enabled"] is False
    assert alpha["mode"] == "snapshot"
    assert alpha["snapshot_enabled"] is True
    assert alpha["live_enabled"] is False
    assert alpha["update_cadence"]["schedule_hint"] == "authoring_reason:review gate"

    first_bytes = config_path.read_bytes()

    second_config = tmp_path / "providers_2.json"
    _write_providers_config(second_config, [_provider_entry("beta", beta_snapshot, enabled=False)])
    rc2 = provider_authoring.main(
        [
            "append-template",
            "--provider",
            "alpha",
            "--config",
            str(second_config),
            "--why",
            "review gate",
            "--careers-url",
            "https://alpha.example.com/careers",
            "--allowed-domain",
            "alpha.example.com",
            "--i-mean-it",
        ]
    )
    assert rc2 == 0
    capsys.readouterr()
    second_bytes = second_config.read_bytes()
    assert first_bytes == second_bytes
