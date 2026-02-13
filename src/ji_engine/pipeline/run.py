"""
SignalCraft
Copyright (c) 2026 Chris Menendez.
All Rights Reserved.
See LICENSE for permitted use.
"""

from __future__ import annotations

import subprocess
import sys
from typing import List, Optional

from ji_engine.config import REPO_ROOT


def run_pipeline(argv: Optional[List[str]] = None, *, use_subprocess: bool = True) -> int:
    """
    Execute the daily pipeline in library mode or via subprocess.

    Args:
        argv: Arguments to forward to scripts/run_daily.py (e.g., ["--profiles", "cs,tam"]).
        use_subprocess: If True (default), spawn a subprocess for isolation.
                        If False, invoke run_daily.main() directly in-process.
    """
    argv = argv or []
    if use_subprocess:
        cmd = [sys.executable, str(REPO_ROOT / "scripts" / "run_daily.py"), *argv]
        subprocess.run(cmd, cwd=REPO_ROOT, check=True)
        return 0

    # In-process execution (library mode)
    from scripts import run_daily  # imported lazily to avoid circulars

    old_argv = sys.argv
    sys.argv = [str(REPO_ROOT / "scripts" / "run_daily.py"), "--no_subprocess", *argv]
    try:
        return run_daily.main()
    finally:
        sys.argv = old_argv


__all__ = ["run_pipeline"]
