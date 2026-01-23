import shutil
import subprocess
from pathlib import Path

import pytest


def test_shell_scripts_syntax() -> None:
    bash = shutil.which("bash")
    if not bash:
        pytest.skip("bash not available")
    repo_root = Path(__file__).resolve().parents[1]
    scripts_dir = repo_root / "scripts"
    script_paths = sorted(p for p in scripts_dir.glob("*.sh") if p.is_file())
    assert script_paths, "no shell scripts found"
    for path in script_paths:
        result = subprocess.run([bash, "-n", str(path)], capture_output=True, text=True)
        assert result.returncode == 0, f"bash -n failed for {path}: {result.stderr}"
