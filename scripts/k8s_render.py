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

REPO_ROOT = Path(__file__).resolve().parents[1]
BASE_DIR = REPO_ROOT / "ops" / "k8s" / "jobintel"
OVERLAY_DIRS = {
    "aws-eks": REPO_ROOT / "ops" / "k8s" / "overlays" / "aws-eks",
    "live": REPO_ROOT / "ops" / "k8s" / "overlays" / "live",
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
        raise RuntimeError("kubectl or kustomize is required to render manifests")
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "kustomize render failed")
    return result.stdout


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
        if value is None:
            missing.add(key)
            return match.group(0)
        return value

    rendered = _PLACEHOLDER_RE.sub(_replace, content)
    if missing:
        missing_list = ", ".join(sorted(missing))
        raise RuntimeError(f"missing env vars for {source_path}: {missing_list}")
    return rendered


def _render_with_overlays(overlays: list[str], image_override_arg: str | None = None) -> str:
    overlay_dirs = [OVERLAY_DIRS[name] for name in overlays]
    patch_paths: list[Path] = []
    for overlay_dir in overlay_dirs:
        patch_paths.extend(_collect_patch_paths(overlay_dir))
    patch_paths = sorted(patch_paths, key=lambda path: path.as_posix())
    if not patch_paths:
        return _render_manifest(BASE_DIR)

    require_image = "aws-eks" in overlays
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
    args = parser.parse_args(argv)

    overlays = args.overlay or []
    if overlays:
        manifest = _render_with_overlays(overlays, image_override_arg=args.image)
    else:
        manifest = _render_manifest(BASE_DIR)
    print(manifest)

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
