from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_security_required_reason_table_order_and_counts(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]

    # 2 jobs with reason A, 1 with reason B, 1 empty (ignored).
    jobs = [
        {"apply_url": "a", "title": "A", "ai": {"security_required_reason": "security clearance"}},
        {"apply_url": "b", "title": "B", "ai": {"security_required_reason": "security clearance"}},
        {"apply_url": "c", "title": "C", "ai": {"security_required_reason": "fedramp required"}},
        {"apply_url": "d", "title": "D", "ai": {"security_required_reason": ""}},
    ]
    current_path = tmp_path / "current.json"
    current_path.write_text(json.dumps(jobs), encoding="utf-8")

    cmd = [
        sys.executable,
        "scripts/audit_ai_payloads.py",
        "--current",
        str(current_path),
        "--top_k",
        "5",
    ]
    proc = subprocess.run(cmd, cwd=repo_root, check=True, capture_output=True, text=True)

    lines = [ln.rstrip("\n") for ln in proc.stdout.splitlines()]
    # Find the section start
    idx = lines.index("== security_required_reason counts (current) ==")
    assert lines[idx + 1] == "security_required_reason\tcount"
    assert lines[idx + 2] == "security clearance\t2"
    assert lines[idx + 3] == "fedramp required\t1"

