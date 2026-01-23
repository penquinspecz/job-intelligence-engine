from datetime import datetime, timezone

from scripts.aws_debug_latest import RunObject, _select_latest_run_id


def test_select_latest_run_id():
    objs = [
        RunObject(run_id="2026-01-01T00:00:00Z", last_modified=None),
        RunObject(run_id="2026-01-03T00:00:00Z", last_modified=None),
        RunObject(run_id="2026-01-02T00:00:00Z", last_modified=None),
    ]
    assert _select_latest_run_id(objs) == "2026-01-03T00:00:00Z"


def test_select_latest_run_id_fallback_last_modified():
    objs = [
        RunObject(run_id="not-a-date", last_modified=datetime(2026, 1, 2, tzinfo=timezone.utc)),
        RunObject(run_id="still-bad", last_modified=datetime(2026, 1, 3, tzinfo=timezone.utc)),
    ]
    assert _select_latest_run_id(objs) == "still-bad"
