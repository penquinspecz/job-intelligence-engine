#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
BASE_DIR = REPO_ROOT / "ops" / "k8s" / "jobintel"
OVERLAY_DIRS = {
    "eks": REPO_ROOT / "ops" / "k8s" / "overlays" / "aws-eks",
    "aws-eks": REPO_ROOT / "ops" / "k8s" / "overlays" / "aws-eks",
    "eks-wrapper": REPO_ROOT / "ops" / "k8s" / "overlays" / "eks",
    "live": REPO_ROOT / "ops" / "k8s" / "overlays" / "live",
    "onprem": REPO_ROOT / "ops" / "k8s" / "jobintel" / "overlays" / "onprem",
    "onprem-wrapper": REPO_ROOT / "ops" / "k8s" / "overlays" / "onprem",
    "onprem-pi": REPO_ROOT / "ops" / "k8s" / "overlays" / "onprem-pi",
}

REQUIRED_SECRET_KEYS = ["JOBINTEL_S3_BUCKET"]
OPTIONAL_SECRET_KEYS = [
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "AWS_PROFILE",
    "DISCORD_WEBHOOK_URL",
    "OPENAI_API_KEY",
]


def _render_manifest(path: Path) -> str:
    kubectl = shutil.which("kubectl")
    kustomize = shutil.which("kustomize")
    if kubectl:
        result = subprocess.run(
            [kubectl, "kustomize", str(path)],
            check=False,
            capture_output=True,
            text=True,
        )
    elif kustomize:
        result = subprocess.run(
            [kustomize, "build", str(path)],
            check=False,
            capture_output=True,
            text=True,
        )
    else:
        return _render_manifest_fallback(path)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "kustomize render failed")
    return result.stdout


def _load_kustomization(path: Path) -> dict[str, object]:
    kustomization = path / "kustomization.yaml"
    if not kustomization.exists():
        raise RuntimeError(f"kustomization.yaml not found: {path}")
    payload = yaml.safe_load(kustomization.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"invalid kustomization payload: {kustomization}")
    return payload


def _iter_resource_files(kustomization_dir: Path, seen: set[Path]) -> list[Path]:
    if kustomization_dir in seen:
        return []
    seen.add(kustomization_dir)

    payload = _load_kustomization(kustomization_dir)
    resource_files: list[Path] = []
    resources = payload.get("resources", [])
    if resources is None:
        resources = []
    if not isinstance(resources, list):
        raise RuntimeError(f"resources must be a list: {kustomization_dir / 'kustomization.yaml'}")
    for entry in resources:
        if not isinstance(entry, str):
            raise RuntimeError(f"resource entry must be string: {entry!r}")
        resolved = (kustomization_dir / entry).resolve()
        if resolved.is_dir():
            resource_files.extend(_iter_resource_files(resolved, seen))
            continue
        if not resolved.exists():
            raise RuntimeError(f"resource path not found: {resolved}")
        resource_files.append(resolved)

    patches = payload.get("patchesStrategicMerge", [])
    if patches is None:
        patches = []
    if not isinstance(patches, list):
        raise RuntimeError(f"patchesStrategicMerge must be a list: {kustomization_dir / 'kustomization.yaml'}")
    for entry in patches:
        if not isinstance(entry, str):
            raise RuntimeError(f"patch entry must be string: {entry!r}")
        resolved = (kustomization_dir / entry).resolve()
        if not resolved.exists():
            raise RuntimeError(f"patch path not found: {resolved}")
        resource_files.append(resolved)
    return resource_files


def _render_manifest_fallback(path: Path) -> str:
    """
    Minimal local renderer for doctor/preflight: resolve kustomization resources
    and concatenate valid YAML docs in deterministic path order.
    """
    files = sorted(set(_iter_resource_files(path.resolve(), set())), key=lambda p: p.as_posix())
    rendered_docs: list[str] = []
    for file_path in files:
        text = file_path.read_text(encoding="utf-8")
        # Validate YAML shape early so doctor catches broken overlays.
        list(yaml.safe_load_all(text))
        rendered_docs.append(text.rstrip() + "\n")
    return "---\n".join(rendered_docs).strip() + "\n"


def _collect_patch_paths(overlay_dir: Path) -> list[Path]:
    kustomization = overlay_dir / "kustomization.yaml"
    if not kustomization.exists():
        raise RuntimeError(f"overlay missing kustomization.yaml: {overlay_dir}")
    patches: list[Path] = []
    in_patches = False
    for line in kustomization.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("patchesStrategicMerge:"):
            in_patches = True
            continue
        if in_patches:
            if stripped.startswith("- "):
                patch = stripped[2:].strip()
                patches.append(overlay_dir / patch)
                continue
            if stripped and not line.startswith(" "):
                in_patches = False
    return patches


_PLACEHOLDER_RE = re.compile(r"\$\{([A-Z0-9_]+)\}")


def _substitute_placeholders(content: str, source_path: Path) -> str:
    missing: set[str] = set()

    def _replace(match: re.Match[str]) -> str:
        key = match.group(1)
        value = os.getenv(key)
        if value is None or value.strip() == "":
            missing.add(key)
            return match.group(0)
        return value

    rendered = _PLACEHOLDER_RE.sub(_replace, content)
    if missing:
        missing_list = ", ".join(sorted(missing))
        raise RuntimeError(f"missing env vars for {source_path}: {missing_list}")
    return rendered


def _render_with_overlays(overlays: list[str], image_override_arg: str | None = None) -> str:
    if len(overlays) == 1 and overlays[0] == "onprem-pi":
        return _render_manifest(OVERLAY_DIRS["onprem-pi"])

    overlay_dirs = [OVERLAY_DIRS[name] for name in overlays]
    patch_paths: list[Path] = []
    for overlay_dir in overlay_dirs:
        patch_paths.extend(_collect_patch_paths(overlay_dir))
    patch_paths = sorted(patch_paths, key=lambda path: path.as_posix())
    if not patch_paths:
        return _render_manifest(BASE_DIR)

    require_image = any(name in {"aws-eks", "eks"} for name in overlays)
    image_override = image_override_arg or (os.getenv("JOBINTEL_IMAGE") if require_image else None)
    if require_image and not image_override:
        raise RuntimeError("JOBINTEL_IMAGE is required when rendering aws-eks overlay")

    import tempfile

    with tempfile.TemporaryDirectory(dir=REPO_ROOT / "ops" / "k8s") as tmp_dir:
        tmp_path = Path(tmp_dir)
        rel_base = Path(os.path.relpath(BASE_DIR, tmp_path))
        rel_patches: list[Path] = []
        for patch in patch_paths:
            content = patch.read_text(encoding="utf-8")
            content = _substitute_placeholders(content, patch)
            patch_name = f"{patch.parent.name}__{patch.name}"
            tmp_patch = tmp_path / patch_name
            tmp_patch.write_text(content, encoding="utf-8")
            rel_patches.append(Path(os.path.relpath(tmp_patch, tmp_path)))

        kustomization = [
            "apiVersion: kustomize.config.k8s.io/v1beta1",
            "kind: Kustomization",
            "resources:",
            f"  - {rel_base.as_posix()}",
            "patchesStrategicMerge:",
        ]
        for patch in rel_patches:
            kustomization.append(f"  - {patch.as_posix()}")
        if image_override:
            if ":" not in image_override:
                raise RuntimeError("JOBINTEL_IMAGE must include a tag (e.g. repo:tag)")
            image_repo, image_tag = image_override.rsplit(":", 1)
            kustomization.extend(
                [
                    "images:",
                    "  - name: ghcr.io/yourorg/jobintel",
                    f"    newName: {image_repo}",
                    f"    newTag: {image_tag}",
                ]
            )
        (tmp_path / "kustomization.yaml").write_text("\n".join(kustomization) + "\n", encoding="utf-8")
        return _render_manifest(tmp_path)


def _validate(manifest: str) -> int:
    kubectl = shutil.which("kubectl")
    if not kubectl:
        print("kubectl not found; skipping validation", file=sys.stderr)
        return 0
    result = subprocess.run(
        [kubectl, "apply", "--dry-run=client", "-f", "-"],
        input=manifest,
        text=True,
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        sys.stderr.write(result.stderr)
        return result.returncode
    print(result.stdout.strip())
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render JobIntel kustomize manifests")
    parser.add_argument(
        "--overlay",
        action="append",
        choices=sorted(OVERLAY_DIRS.keys()),
        help="Render one or more overlays (default: base). Repeat to stack.",
    )
    parser.add_argument(
        "--image",
        default=None,
        help="Override container image URI (e.g., <acct>.dkr.ecr.<region>.amazonaws.com/jobintel:<tag>).",
    )
    parser.add_argument("--validate", action="store_true", help="kubectl apply --dry-run=client")
    parser.add_argument("--secrets", action="store_true", help="Print required secret keys")
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="Explicitly print rendered manifest to stdout (default behavior).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Print only the first N lines of rendered output (0 = full).",
    )
    args = parser.parse_args(argv)

    overlays = args.overlay or []
    if overlays:
        manifest = _render_with_overlays(overlays, image_override_arg=args.image)
    else:
        manifest = _render_manifest(BASE_DIR)
    output = manifest
    if args.limit and args.limit > 0:
        output = "\n".join(manifest.splitlines()[: args.limit]) + "\n"
    print(output, end="" if output.endswith("\n") else "\n")

    if args.secrets:
        payload = {
            "required": REQUIRED_SECRET_KEYS,
            "optional": OPTIONAL_SECRET_KEYS,
        }
        print("---")
        print(json.dumps(payload, sort_keys=True))

    if args.validate:
        return _validate(manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
