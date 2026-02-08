from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from ji_engine.utils import time as time_utils


def test_utc_now_z_seconds_precision_default(monkeypatch) -> None:
    fixed = datetime(2026, 2, 7, 12, 34, 56, 123456, tzinfo=timezone.utc)
    monkeypatch.setattr(time_utils, "utc_now", lambda: fixed)
    assert time_utils.utc_now_z() == "2026-02-07T12:34:56Z"


def test_utc_now_z_microseconds_when_disabled(monkeypatch) -> None:
    fixed = datetime(2026, 2, 7, 12, 34, 56, 123456, tzinfo=timezone.utc)
    monkeypatch.setattr(time_utils, "utc_now", lambda: fixed)
    assert time_utils.utc_now_z(seconds_precision=False) == "2026-02-07T12:34:56.123456Z"


def test_utc_now_naive(monkeypatch) -> None:
    fixed = datetime(2026, 2, 7, 12, 34, 56, 123456, tzinfo=timezone.utc)
    monkeypatch.setattr(time_utils, "utc_now", lambda: fixed)
    value = time_utils.utc_now_naive()
    assert value.tzinfo is None
    assert value.isoformat() == "2026-02-07T12:34:56.123456"


def test_no_datetime_utcnow_usage() -> None:
    root = Path(__file__).resolve().parents[1]
    needle = "datetime" + ".utcnow("
    offenders: list[str] = []
    for scan_root in (root / "src", root / "scripts", root / "tests"):
        for path in sorted(scan_root.rglob("*.py")):
            if path == Path(__file__).resolve():
                continue
            text = path.read_text(encoding="utf-8")
            if needle in text:
                offenders.append(str(path.relative_to(root)))
    assert not offenders, f"datetime.utcnow() found in: {', '.join(offenders)}"
