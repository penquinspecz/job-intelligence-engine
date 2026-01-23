from datetime import datetime, timezone

from scripts.aws_schedule_status import _latest_invocation_time


def test_latest_invocation_time() -> None:
    t1 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    t2 = datetime(2024, 1, 2, tzinfo=timezone.utc)
    out = _latest_invocation_time([{"Timestamp": t1}, {"Timestamp": t2}])
    assert out == t2.isoformat()
