from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Callable


def atomic_write_text(path: Path, content: str, encoding: str = "utf-8") -> None:
    """
    Write text to a temp file in the same directory, then atomically replace.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding=encoding, dir=path.parent, delete=False) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)
    os.replace(tmp_path, path)


def atomic_write_with(path: Path, writer: Callable[[Path], None]) -> None:
    """
    Write using a provided writer(path) to a temp file, then atomically replace.
    The writer must write to the given temp path.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        writer(tmp_path)
        os.replace(tmp_path, path)
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except Exception:
                pass

