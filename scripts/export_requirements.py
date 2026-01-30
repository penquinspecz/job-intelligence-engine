#!/usr/bin/env python3
from __future__ import annotations

import argparse
import difflib
import importlib.metadata
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def _load_pyproject(path: Path) -> dict:
    data: dict
    try:
        import tomllib  # type: ignore
    except ModuleNotFoundError:  # pragma: no cover - only on <3.11 without tomli
        try:
            import tomli as tomllib  # type: ignore
        except ModuleNotFoundError as exc:  # pragma: no cover
            raise SystemExit("tomllib/tomli not available; install tomli or use Python 3.11+") from exc

    with path.open("rb") as handle:
        data = tomllib.load(handle)
    return data


def _normalize_name(req: str) -> str:
    name = req.split(";", 1)[0].strip()
    name = re.split(r"[<>=!~\s\[]", name, maxsplit=1)[0]
    return re.sub(r"[-_.]+", "-", name).lower()


def _collect_deps(pyproject: dict, extras: list[str]) -> list[str]:
    project = pyproject.get("project", {})
    deps = list(project.get("dependencies", []))
    optional = project.get("optional-dependencies", {}) or {}
    for extra in extras:
        if extra not in optional:
            raise SystemExit(f"Unknown extra '{extra}' in pyproject optional-dependencies.")
        deps.extend(optional[extra])
    return deps


def _pip_compile_available() -> bool:
    return shutil.which("pip-compile") is not None


def _run_pip_compile(requirements_in: Path, output_path: Path) -> None:
    cmd = [
        sys.executable,
        "-m",
        "piptools",
        "compile",
        "--no-header",
        "--no-annotate",
        "--quiet",
        "--resolver=backtracking",
        "--output-file",
        str(output_path),
        str(requirements_in),
    ]
    subprocess.run(cmd, check=True)


def _resolve_env_deps(deps: list[str]) -> list[str]:
    try:
        from packaging.requirements import Requirement
    except ModuleNotFoundError as exc:  # pragma: no cover
        raise SystemExit("packaging is required to resolve dependencies; install it or use pip-compile.") from exc

    pinned: dict[str, str] = {}
    to_process = {_normalize_name(dep) for dep in deps}

    while to_process:
        name = to_process.pop()
        if name in pinned:
            continue
        try:
            dist = importlib.metadata.distribution(name)
        except importlib.metadata.PackageNotFoundError as exc:
            raise SystemExit(f"Dependency '{name}' not installed; cannot pin without pip-compile.") from exc

        pinned[name] = dist.version
        requires = dist.requires or []
        for requirement in requires:
            req = Requirement(requirement)
            if req.marker and not req.marker.evaluate():
                continue
            dep_name = _normalize_name(req.name)
            if dep_name not in pinned:
                to_process.add(dep_name)

    return [f"{name}=={version}" for name, version in sorted(pinned.items())]


def _render_requirements(deps: list[str]) -> str:
    if _pip_compile_available():
        with tempfile.TemporaryDirectory(prefix="req-export-") as tmpdir:
            req_in = Path(tmpdir) / "requirements.in"
            req_out = Path(tmpdir) / "requirements.txt"
            req_in.write_text("\n".join(sorted(deps)) + "\n", encoding="utf-8")
            _run_pip_compile(req_in, req_out)
            return req_out.read_text(encoding="utf-8")

    lines = _resolve_env_deps(deps)
    return "\n".join(lines) + "\n"


def _write_if_changed(output_path: Path, content: str) -> None:
    output_path.write_text(content, encoding="utf-8")


def _check_matches(output_path: Path, content: str) -> None:
    if not output_path.exists():
        raise SystemExit(f"{output_path} does not exist; run export to create it.")
    current = output_path.read_text(encoding="utf-8")
    if current == content:
        return
    diff = difflib.unified_diff(
        current.splitlines(),
        content.splitlines(),
        fromfile=str(output_path),
        tofile=f"{output_path} (generated)",
        lineterm="",
    )
    print("requirements.txt is out of date. Run: make deps-sync")
    print("\n".join(diff))
    raise SystemExit(1)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export pinned requirements.txt from pyproject.toml.")
    parser.add_argument(
        "--pyproject",
        default="pyproject.toml",
        help="Path to pyproject.toml",
    )
    parser.add_argument(
        "--output",
        default="requirements.txt",
        help="Output requirements file",
    )
    parser.add_argument(
        "--extra",
        action="append",
        default=[],
        help="Include optional dependency group (repeatable).",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail if requirements.txt is out of date.",
    )
    args = parser.parse_args(argv)

    pyproject_path = Path(args.pyproject)
    output_path = Path(args.output)
    extras = args.extra or []

    pyproject = _load_pyproject(pyproject_path)
    deps = _collect_deps(pyproject, extras)

    if not deps:
        raise SystemExit("No dependencies found in pyproject.")

    content = _render_requirements(deps)

    if args.check:
        _check_matches(output_path, content)
    else:
        _write_if_changed(output_path, content)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
