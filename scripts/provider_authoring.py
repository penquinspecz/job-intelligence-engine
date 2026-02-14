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


def _print_warning_header() -> None:
    border = "#" * len(_WARNING_BANNER)
    print(border)
    print(_WARNING_BANNER)
    print(border)


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
    update_parser.add_argument("--providers-config", default=str(Path("config") / "providers.json"))
    update_parser.add_argument(
        "--manifest-path",
        default=str(Path("tests") / "fixtures" / "golden" / "snapshot_bytes.manifest.json"),
    )

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

    raise SystemExit(f"unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
