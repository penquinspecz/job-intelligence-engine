#!/usr/bin/env python3
from __future__ import annotations

try:
    import _bootstrap  # type: ignore  # noqa: F401
except ModuleNotFoundError:
    from scripts import _bootstrap  # noqa: F401

import argparse
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from ji_engine.providers.registry import load_providers_config
from ji_engine.utils.verification import compute_sha256_file

PLACEHOLDER_TEMPLATE = """<!doctype html>
<html lang=\"en\">
  <head>
    <meta charset=\"utf-8\" />
    <title>{provider_id} snapshot placeholder</title>
  </head>
  <body>
    <h1>{provider_id} snapshot placeholder</h1>
    <p>
      Replace this file with a real captured fixture before enabling live mode.
    </p>
    <p>
      Recommended:
      scripts/update_snapshots.py --provider {provider_id} --out_dir data/{provider_id}_snapshots --apply
    </p>
  </body>
</html>
"""

_WARNING_BANNER = "THIS IS A DETERMINISM BASELINE CHANGE; REVIEW REQUIRED"
_DEFAULT_PROVIDERS_CONFIG = Path("config") / "providers.json"
_DEFAULT_MANIFEST_PATH = Path("tests") / "fixtures" / "golden" / "snapshot_bytes.manifest.json"
_DEFAULT_SCHEMA_PATH = Path("schemas") / "providers.schema.v1.json"
_DEFAULT_ENABLEMENT_MODE = "snapshot"


@dataclass(frozen=True)
class ValidationCheck:
    name: str
    ok: bool
    detail: str


@dataclass(frozen=True)
class ProviderValidationResult:
    provider_id: str
    checks: tuple[ValidationCheck, ...]

    @property
    def errors(self) -> tuple[str, ...]:
        return tuple(check.detail for check in self.checks if not check.ok)

    @property
    def ok(self) -> bool:
        return all(check.ok for check in self.checks)


def _atomic_write_text(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=f"{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
        os.replace(tmp_path, path)
    finally:
        try:
            os.unlink(tmp_path)
        except FileNotFoundError:
            pass


def _json_dump(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def template_entry(provider_id: str) -> dict[str, Any]:
    pid = provider_id.strip().lower()
    if not pid:
        raise ValueError("provider_id must be non-empty")
    snapshot_dir = f"data/{pid}_snapshots"
    return {
        "provider_id": pid,
        "display_name": "Example Provider",
        "enabled": True,
        "careers_urls": ["https://example.com/careers"],
        "allowed_domains": ["example.com"],
        "extraction_mode": "jsonld",
        "mode": "snapshot",
        "snapshot_enabled": True,
        "live_enabled": False,
        "snapshot_dir": snapshot_dir,
        "snapshot_path": f"{snapshot_dir}/index.html",
        "update_cadence": {
            "min_interval_hours": 24,
            "priority": "normal",
        },
        "politeness": {
            "min_delay_s": 1.0,
            "max_attempts": 2,
        },
    }


def _validate_template(entry: dict[str, Any]) -> None:
    payload = {"schema_version": 1, "providers": [entry]}
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", encoding="utf-8", delete=True) as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        handle.flush()
        load_providers_config(Path(handle.name))


def scaffold_snapshot(provider_id: str, data_dir: Path, *, force: bool = False) -> Path:
    pid = provider_id.strip().lower()
    if not pid:
        raise ValueError("provider_id must be non-empty")
    snapshot_dir = data_dir / f"{pid}_snapshots"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    index_path = snapshot_dir / "index.html"
    if index_path.exists() and not force:
        raise FileExistsError(f"Refusing to overwrite existing fixture: {index_path} (use --force)")
    index_path.write_text(PLACEHOLDER_TEMPLATE.format(provider_id=pid), encoding="utf-8")
    return index_path


def _providers_payload(path: Path) -> tuple[dict[str, Any] | list[Any], list[dict[str, Any]]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        providers = payload.get("providers")
    elif isinstance(payload, list):
        providers = payload
    else:
        raise ValueError(f"providers config must be object/list: {path}")
    if not isinstance(providers, list):
        raise ValueError(f"providers config missing providers list: {path}")
    typed = [entry for entry in providers if isinstance(entry, dict)]
    if len(typed) != len(providers):
        raise ValueError(f"providers config has non-object entries: {path}")
    return payload, typed


def _resolve_provider_entry_raw(
    provider_id: str, providers_config_path: Path
) -> tuple[dict[str, Any] | list[Any], list[dict[str, Any]], dict[str, Any]]:
    payload, providers = _providers_payload(providers_config_path)
    target_id = provider_id.strip().lower()
    for entry in providers:
        entry_id = str(entry.get("provider_id", "")).strip().lower()
        if entry_id == target_id:
            return payload, providers, entry
    known = ", ".join(sorted(str(p.get("provider_id", "")).strip() for p in providers if p.get("provider_id")))
    raise ValueError(f"unknown provider '{provider_id}'. known providers: {known}")


def _resolve_provider_entry(provider_id: str, providers_config_path: Path) -> dict[str, Any]:
    providers = load_providers_config(providers_config_path)
    target_id = provider_id.strip().lower()
    for entry in providers:
        if str(entry.get("provider_id", "")).strip().lower() == target_id:
            return entry
    known = ", ".join(sorted(str(p.get("provider_id", "")).strip() for p in providers if p.get("provider_id")))
    raise ValueError(f"unknown provider '{provider_id}'. known providers: {known}")


def _manifest_key(snapshot_path_raw: str, snapshot_path_resolved: Path) -> str:
    snapshot_cfg_path = Path(snapshot_path_raw)
    if not snapshot_cfg_path.is_absolute():
        return snapshot_cfg_path.as_posix()
    cwd = Path.cwd().resolve()
    try:
        return snapshot_path_resolved.resolve().relative_to(cwd).as_posix()
    except ValueError:
        return snapshot_path_resolved.as_posix()


def _print_warning_header() -> None:
    border = "#" * len(_WARNING_BANNER)
    print(border)
    print(_WARNING_BANNER)
    print(border)


def _allowed_extraction_modes(schema_path: Path) -> set[str]:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    raw = schema.get("$defs", {}).get("provider", {}).get("properties", {}).get("extraction_mode", {}).get("enum", [])
    if not isinstance(raw, list):
        return set()
    return {str(mode).strip().lower() for mode in raw if str(mode).strip()}


def _bool_default(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    return bool(value)


def validate_provider(
    *,
    provider_id: str,
    providers_config_path: Path,
    manifest_path: Path,
    providers_schema_path: Path,
    for_enable: bool,
) -> ProviderValidationResult:
    checks: list[ValidationCheck] = []
    target_id = provider_id.strip().lower()

    try:
        _, _, raw_entry = _resolve_provider_entry_raw(target_id, providers_config_path)
        checks.append(ValidationCheck("provider_exists", True, f"provider '{target_id}' found"))
    except Exception as exc:
        checks.append(ValidationCheck("provider_exists", False, str(exc)))
        return ProviderValidationResult(provider_id=target_id, checks=tuple(checks))

    careers_urls = raw_entry.get("careers_urls")
    if isinstance(careers_urls, list) and any(str(url).strip() for url in careers_urls):
        checks.append(ValidationCheck("careers_urls_present", True, f"careers_urls count={len(careers_urls)}"))
    else:
        checks.append(
            ValidationCheck(
                "careers_urls_present",
                False,
                "careers_urls must be a non-empty list for explicit provider enablement",
            )
        )

    allowed_domains = raw_entry.get("allowed_domains")
    if isinstance(allowed_domains, list) and any(str(host).strip() for host in allowed_domains):
        checks.append(ValidationCheck("allowed_domains_present", True, f"allowed_domains count={len(allowed_domains)}"))
    else:
        checks.append(
            ValidationCheck(
                "allowed_domains_present",
                False,
                "allowed_domains must be a non-empty list for explicit provider enablement",
            )
        )

    extraction_modes = sorted(_allowed_extraction_modes(providers_schema_path))
    extraction_mode = str(raw_entry.get("extraction_mode") or "").strip().lower()
    if extraction_mode and extraction_mode in extraction_modes:
        checks.append(ValidationCheck("extraction_mode_valid", True, f"extraction_mode={extraction_mode}"))
    elif extraction_mode:
        checks.append(
            ValidationCheck(
                "extraction_mode_valid",
                False,
                f"invalid extraction_mode '{extraction_mode}' (allowed: {', '.join(extraction_modes)})",
            )
        )
    else:
        checks.append(
            ValidationCheck(
                "extraction_mode_valid",
                False,
                "extraction_mode is required for explicit provider enablement",
            )
        )

    normalized_entry: dict[str, Any] | None = None
    try:
        normalized_entry = _resolve_provider_entry(target_id, providers_config_path)
        checks.append(ValidationCheck("provider_schema_valid", True, "providers config schema and invariants pass"))
    except Exception as exc:
        checks.append(ValidationCheck("provider_schema_valid", False, str(exc)))

    mode = str(raw_entry.get("mode") or _DEFAULT_ENABLEMENT_MODE).strip().lower()
    snapshot_enabled = _bool_default(raw_entry.get("snapshot_enabled"), default=True)
    target_enabled = True if for_enable else _bool_default(raw_entry.get("enabled"), default=True)
    requires_snapshot_contract = mode in {"snapshot", "auto"} and snapshot_enabled and target_enabled

    if not requires_snapshot_contract:
        checks.append(
            ValidationCheck(
                "snapshot_contract",
                True,
                f"snapshot checks not required (mode={mode}, snapshot_enabled={snapshot_enabled}, enabled={target_enabled})",
            )
        )
        return ProviderValidationResult(provider_id=target_id, checks=tuple(checks))

    snapshot_path_raw = str(raw_entry.get("snapshot_path") or "").strip()
    if not snapshot_path_raw and normalized_entry is not None:
        snapshot_path_raw = str(normalized_entry.get("snapshot_path") or "").strip()

    if not snapshot_path_raw:
        checks.append(
            ValidationCheck(
                "snapshot_fixture_exists",
                False,
                "snapshot_path missing for snapshot/auto provider",
            )
        )
        checks.append(
            ValidationCheck(
                "snapshot_manifest_entry",
                False,
                "cannot validate manifest without snapshot_path",
            )
        )
        return ProviderValidationResult(provider_id=target_id, checks=tuple(checks))

    snapshot_path = Path(snapshot_path_raw)
    if not snapshot_path.is_absolute():
        snapshot_path = (Path.cwd() / snapshot_path).resolve()

    fixture_exists = snapshot_path.exists()
    checks.append(
        ValidationCheck(
            "snapshot_fixture_exists",
            fixture_exists,
            f"snapshot_path={snapshot_path_raw}",
        )
    )

    if not manifest_path.exists():
        checks.append(
            ValidationCheck(
                "snapshot_manifest_entry",
                False,
                f"snapshot manifest not found: {manifest_path}",
            )
        )
        return ProviderValidationResult(provider_id=target_id, checks=tuple(checks))

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        checks.append(
            ValidationCheck(
                "snapshot_manifest_entry",
                False,
                f"snapshot manifest must be a JSON object: {manifest_path}",
            )
        )
        return ProviderValidationResult(provider_id=target_id, checks=tuple(checks))

    manifest_key = _manifest_key(snapshot_path_raw, snapshot_path)
    manifest_entry = manifest.get(manifest_key)
    if not isinstance(manifest_entry, dict):
        checks.append(
            ValidationCheck(
                "snapshot_manifest_entry",
                False,
                f"manifest missing entry for snapshot_path '{manifest_key}'",
            )
        )
        return ProviderValidationResult(provider_id=target_id, checks=tuple(checks))

    if not fixture_exists:
        checks.append(
            ValidationCheck(
                "snapshot_manifest_entry",
                False,
                f"snapshot fixture missing at '{snapshot_path_raw}'",
            )
        )
        return ProviderValidationResult(provider_id=target_id, checks=tuple(checks))

    actual_bytes = snapshot_path.stat().st_size
    actual_sha = compute_sha256_file(snapshot_path)
    expected_bytes = manifest_entry.get("bytes")
    expected_sha = manifest_entry.get("sha256")
    hash_ok = actual_bytes == expected_bytes and actual_sha == expected_sha
    checks.append(
        ValidationCheck(
            "snapshot_manifest_entry",
            hash_ok,
            (
                f"manifest_key={manifest_key} expected_bytes={expected_bytes} actual_bytes={actual_bytes} "
                f"expected_sha256={expected_sha} actual_sha256={actual_sha}"
            ),
        )
    )

    return ProviderValidationResult(provider_id=target_id, checks=tuple(checks))


def _print_validation_result(result: ProviderValidationResult) -> None:
    for check in result.checks:
        status = "OK" if check.ok else "FAIL"
        print(f"[{status}] {check.name}: {check.detail}")
    summary = "PASS" if result.ok else "FAIL"
    print(f"status={summary}")


def _print_enablement_checklist(provider_id: str) -> None:
    print("ENABLEMENT CHECKLIST")
    print(f"1) make provider-validate provider={provider_id}")
    print(f"2) if fixture bytes changed: make provider-manifest-update provider={provider_id}")
    print("3) make gate")
    print(f'4) make provider-enable provider={provider_id} WHY="<reason>" I_MEAN_IT=1')


def _write_payload(path: Path, payload: dict[str, Any] | list[Any]) -> None:
    _atomic_write_text(path, _json_dump(payload))


def _enable_provider_in_config(provider_id: str, providers_config_path: Path) -> bool:
    payload, providers, raw_entry = _resolve_provider_entry_raw(provider_id, providers_config_path)
    if bool(raw_entry.get("enabled", True)):
        return False
    raw_entry["enabled"] = True

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", encoding="utf-8", delete=True) as handle:
        handle.write(_json_dump(payload))
        handle.flush()
        load_providers_config(Path(handle.name))

    _write_payload(providers_config_path, payload)
    return True


def update_snapshot_manifest_for_provider(
    *,
    provider_id: str,
    providers_config_path: Path,
    manifest_path: Path,
) -> tuple[str, dict[str, Any], dict[str, Any] | None]:
    entry = _resolve_provider_entry(provider_id, providers_config_path)
    snapshot_path_raw = str(entry.get("snapshot_path") or "").strip()
    if not snapshot_path_raw:
        raise ValueError(f"provider '{provider_id}' has no snapshot_path configured")

    snapshot_path = Path(snapshot_path_raw)
    if not snapshot_path.is_absolute():
        snapshot_path = (Path.cwd() / snapshot_path).resolve()
    if not snapshot_path.exists():
        raise FileNotFoundError(f"snapshot fixture not found: {snapshot_path}")

    key = _manifest_key(snapshot_path_raw, snapshot_path)
    new_entry = {
        "bytes": snapshot_path.stat().st_size,
        "sha256": compute_sha256_file(snapshot_path),
    }

    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            raise ValueError(f"manifest must be a JSON object: {manifest_path}")
    else:
        manifest = {}

    old_entry = manifest.get(key)
    manifest[key] = new_entry
    rendered = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    _atomic_write_text(manifest_path, rendered)
    return key, new_entry, old_entry if isinstance(old_entry, dict) else None


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Provider authoring helpers")
    sub = parser.add_subparsers(dest="command", required=True)

    template_parser = sub.add_parser("template", help="Print a schema-valid provider entry template JSON")
    template_parser.add_argument("--provider-id", required=True)

    scaffold_parser = sub.add_parser("scaffold", help="Scaffold provider snapshot dir with placeholder index.html")
    scaffold_parser.add_argument("--provider-id", required=True)
    scaffold_parser.add_argument("--data-dir", default="data")
    scaffold_parser.add_argument("--force", action="store_true")

    update_parser = sub.add_parser(
        "update-snapshot-manifest",
        help="Update snapshot bytes manifest entry for one provider only",
    )
    update_parser.add_argument("--provider", required=True)
    update_parser.add_argument("--providers-config", default=str(_DEFAULT_PROVIDERS_CONFIG))
    update_parser.add_argument("--manifest-path", default=str(_DEFAULT_MANIFEST_PATH))

    validate_parser = sub.add_parser(
        "validate-provider",
        help="Run provider enablement contract checks without modifying config",
    )
    validate_parser.add_argument("--provider", required=True)
    validate_parser.add_argument("--providers-config", default=str(_DEFAULT_PROVIDERS_CONFIG))
    validate_parser.add_argument("--manifest-path", default=str(_DEFAULT_MANIFEST_PATH))
    validate_parser.add_argument("--providers-schema", default=str(_DEFAULT_SCHEMA_PATH))

    enable_parser = sub.add_parser(
        "enable",
        help="Enable provider after passing explicit guardrail checks",
    )
    enable_parser.add_argument("--provider", required=True)
    enable_parser.add_argument("--why", required=True)
    enable_parser.add_argument("--providers-config", default=str(_DEFAULT_PROVIDERS_CONFIG))
    enable_parser.add_argument("--manifest-path", default=str(_DEFAULT_MANIFEST_PATH))
    enable_parser.add_argument("--providers-schema", default=str(_DEFAULT_SCHEMA_PATH))
    enable_parser.add_argument("--i-mean-it", action="store_true")

    args = parser.parse_args(argv)
    if args.command == "template":
        entry = template_entry(args.provider_id)
        _validate_template(entry)
        print(json.dumps(entry, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    if args.command == "scaffold":
        path = scaffold_snapshot(args.provider_id, Path(args.data_dir), force=bool(args.force))
        print(f"Wrote provider snapshot placeholder: {path}")
        return 0

    if args.command == "update-snapshot-manifest":
        _print_warning_header()
        key, current, previous = update_snapshot_manifest_for_provider(
            provider_id=args.provider,
            providers_config_path=Path(args.providers_config),
            manifest_path=Path(args.manifest_path),
        )
        print(f"provider={args.provider.strip().lower()}")
        print(f"manifest_key={key}")
        print(f"bytes={current['bytes']}")
        print(f"sha256={current['sha256']}")
        if previous is not None:
            print(f"previous_bytes={previous.get('bytes')}")
            print(f"previous_sha256={previous.get('sha256')}")
        else:
            print("previous_entry=<none>")
        return 0

    if args.command == "validate-provider":
        result = validate_provider(
            provider_id=args.provider,
            providers_config_path=Path(args.providers_config),
            manifest_path=Path(args.manifest_path),
            providers_schema_path=Path(args.providers_schema),
            for_enable=True,
        )
        print(f"provider={result.provider_id}")
        _print_validation_result(result)
        return 0 if result.ok else 1

    if args.command == "enable":
        provider_id = args.provider.strip().lower()
        why = str(args.why).strip()
        if not why:
            raise ValueError("--why must be non-empty")

        print(f"provider={provider_id}")
        print(f"why={why}")
        result = validate_provider(
            provider_id=provider_id,
            providers_config_path=Path(args.providers_config),
            manifest_path=Path(args.manifest_path),
            providers_schema_path=Path(args.providers_schema),
            for_enable=True,
        )
        _print_validation_result(result)
        _print_enablement_checklist(provider_id)

        if not result.ok:
            return 1
        if not args.i_mean_it:
            print("refusing to edit providers config without --i-mean-it")
            return 2

        changed = _enable_provider_in_config(provider_id, Path(args.providers_config))
        if changed:
            print(f"enabled provider '{provider_id}' in {args.providers_config}")
        else:
            print(f"provider '{provider_id}' already enabled; no config changes made")
        return 0

    raise SystemExit(f"unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
