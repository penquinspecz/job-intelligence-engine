from __future__ import annotations

import sys
from pathlib import Path


def _ensure_src_on_path() -> None:
    root = Path(__file__).resolve().parents[1]
    src_path = root / "src"
    if src_path.exists():
        src_str = str(src_path)
        if src_str not in sys.path:
            sys.path.insert(0, src_str)


_ensure_src_on_path()


def pytest_addoption(parser) -> None:
    parser.addoption(
        "--update-golden",
        action="store_true",
        default=False,
        help="Update golden test fixtures.",
    )
