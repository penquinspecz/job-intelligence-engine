#!/usr/bin/env python3
from __future__ import annotations

import argparse
import difflib
import importlib.metadata
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REQUIRED_PYTHON = "3.12"
REQUIRED_PIP = os.environ.get("JIE_PIP_VERSION", "25.0.1")
REQUIRED_PIPTOOLS = os.environ.get("JIE_PIPTOOLS_VERSION", "7.4.1")


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
    try:
        importlib.metadata.version("pip-tools")
    except importlib.metadata.PackageNotFoundError:
        return False
    return True


def _is_writable_dir(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False
    return os.access(path, os.W_OK)


def _select_pip_tools_cache_dir(repo_root: Path) -> Path:
    env_cache = os.environ.get("PIP_TOOLS_CACHE_DIR")
    if env_cache:
        env_path = Path(env_cache).expanduser()
        if _is_writable_dir(env_path):
            return env_path
        print(f"Warning: PIP_TOOLS_CACHE_DIR not writable: {env_path}", file=sys.stderr)
    repo_cache = repo_root / ".cache" / "pip-tools"
    if _is_writable_dir(repo_cache):
        return repo_cache
    fallback = Path("/tmp/pip-tools-cache")
    if _is_writable_dir(fallback):
        return fallback
    raise SystemExit("No writable pip-tools cache dir found.")


def _is_ci() -> bool:
    return os.environ.get("GITHUB_ACTIONS") == "true"


def _ensure_ci_cache_dir() -> None:
    if _is_ci() and not os.environ.get("PIP_TOOLS_CACHE_DIR"):
        os.environ["PIP_TOOLS_CACHE_DIR"] = "/tmp/pip-tools-cache"
    cache_dir = os.environ.get("PIP_TOOLS_CACHE_DIR")
    if cache_dir:
        Path(cache_dir).mkdir(parents=True, exist_ok=True)


def _tooling_self_check(*, repo_root: Path, check_mode: bool) -> None:
    verbose = os.environ.get("JIE_TOOLING_VERBOSE") == "1"
    venv_path = repo_root / ".venv"

    def _fail(detail: str) -> None:
        if check_mode:
            raise SystemExit("deps-check tooling mismatch; run make tooling-sync")
        raise SystemExit(detail)

    if venv_path.exists():
        expected = venv_path / "bin" / "python"
        if expected != Path(sys.executable):
            msg = (
                f"export_requirements must run under {expected} (got {sys.executable}). "
                "Activate the repo venv or run: make tooling-sync"
            )
            if not check_mode and verbose:
                print(msg, file=sys.stderr)
            _fail(msg)

    if not sys.version.startswith(REQUIRED_PYTHON):
        msg = f"python {REQUIRED_PYTHON}.x required; found {sys.version.split()[0]}"
        if not check_mode and verbose:
            print(msg, file=sys.stderr)
        _fail(msg)

    pip_version = importlib.metadata.version("pip")
    if not pip_version.startswith(REQUIRED_PIP):
        msg = f"pip {REQUIRED_PIP} required; found {pip_version}"
        if not check_mode and verbose:
            print(msg, file=sys.stderr)
        _fail(msg)

    try:
        piptools_version = importlib.metadata.version("pip-tools")
    except importlib.metadata.PackageNotFoundError as exc:
        msg = f"pip-tools {REQUIRED_PIPTOOLS} required; not installed (run: make tooling-sync)"
        if not check_mode and verbose:
            print(msg, file=sys.stderr)
        _fail(msg)
        raise SystemExit(msg) from exc

    if not piptools_version.startswith(REQUIRED_PIPTOOLS):
        msg = f"pip-tools {REQUIRED_PIPTOOLS} required; found {piptools_version}"
        if not check_mode and verbose:
            print(msg, file=sys.stderr)
        _fail(msg)


def _pip_args_for_ci() -> list[str]:
    if not _is_ci() and os.environ.get("JIE_DEPS_TARGET") != "ci":
        return []
    return [
        "--pip-args=--platform manylinux_2_17_x86_64 --implementation cp --python-version 3.12 --abi cp312",
    ]


def _run_pip_compile(requirements_in: Path, output_path: Path, cache_dir: Path) -> None:
    cmd = [
        sys.executable,
        "-m",
        "piptools",
        "compile",
        "--no-header",
        "--no-annotate",
        "--quiet",
        "--resolver=backtracking",
        "--cache-dir",
        str(cache_dir),
        *_pip_args_for_ci(),
        "--output-file",
        str(output_path),
        str(requirements_in),
    ]
    print(f"piptools: {' '.join(cmd)}", file=sys.stderr)
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


def _render_requirements(deps: list[str], repo_root: Path) -> str:
    if _pip_compile_available():
        with tempfile.TemporaryDirectory(prefix="req-export-") as tmpdir:
            req_in = Path(tmpdir) / "requirements.in"
            req_out = Path(tmpdir) / "requirements.txt"
            req_in.write_text("\n".join(sorted(deps)) + "\n", encoding="utf-8")
            _ensure_ci_cache_dir()
            if _is_ci():
                print("export_requirements: CI mode enabled (linux cp312 target)", file=sys.stderr)
            cache_dir = _select_pip_tools_cache_dir(repo_root)
            _run_pip_compile(req_in, req_out, cache_dir)
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
    repo_root = Path(__file__).resolve().parents[1]

    _tooling_self_check(repo_root=repo_root, check_mode=args.check)

    pyproject = _load_pyproject(pyproject_path)
    deps = _collect_deps(pyproject, extras)

    if not deps:
        raise SystemExit("No dependencies found in pyproject.")

    content = _render_requirements(deps, repo_root)

    if args.check:
        _check_matches(output_path, content)
    else:
        _write_if_changed(output_path, content)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
