import json
from datetime import datetime, timezone

from jobintel.aws_runs import (
    get_most_recent_run_id_before,
    get_most_recent_successful_run_id_before,
    parse_run_id_from_key,
    read_last_success_state,
)


class DummyS3:
    def __init__(self, keys, reports=None):
        self.keys = keys
        self.reports = reports or {}

    def list_objects_v2(self, **kwargs):
        prefix = kwargs.get("Prefix", "")
        contents = [{"Key": key} for key in self.keys if key.startswith(prefix)]
        return {"Contents": contents, "IsTruncated": False}

    def get_object(self, Bucket, Key):
        if Key not in self.reports:
            raise Exception("missing")
        payload = json.dumps(self.reports[Key]).encode("utf-8")

        class Body:
            def __init__(self, data):
                self._data = data

            def read(self):
                return self._data

        return {"Body": Body(payload)}


def test_parse_run_id_from_key():
    key = "jobintel/runs/2026-01-02T00:00:00Z/openai/cs/file.json"
    run_id = parse_run_id_from_key(key, "jobintel")
    assert run_id == "2026-01-02T00:00:00Z"


def test_get_most_recent_run_id_before():
    keys = [
        "jobintel/runs/2026-01-01T00:00:00Z/openai/cs/x.json",
        "jobintel/runs/2026-01-02T00:00:00Z/openai/cs/x.json",
        "jobintel/runs/2026-01-03T00:00:00Z/openai/cs/x.json",
    ]
    client = DummyS3(keys)
    current = datetime(2026, 1, 3, tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
    run_id = get_most_recent_run_id_before("bucket", "jobintel", current, client=client)
    assert run_id == "2026-01-02T00:00:00Z"


def test_get_most_recent_successful_run_id_before():
    keys = [
        "jobintel/runs/2026-01-01T00:00:00Z/openai/cs/x.json",
        "jobintel/runs/2026-01-02T00:00:00Z/openai/cs/x.json",
        "jobintel/runs/2026-01-03T00:00:00Z/openai/cs/x.json",
    ]
    reports = {
        "jobintel/runs/2026-01-02T00:00:00Z/run_report.json": {"success": False},
        "jobintel/runs/2026-01-01T00:00:00Z/run_report.json": {"success": True},
    }
    client = DummyS3(keys, reports=reports)
    current = datetime(2026, 1, 3, tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
    run_id = get_most_recent_successful_run_id_before("bucket", "jobintel", current, client=client)
    assert run_id == "2026-01-01T00:00:00Z"


def test_read_last_success_state_not_found():
    from botocore.exceptions import ClientError

    class MissingClient:
        def get_object(self, Bucket, Key):
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")

    payload, status, key = read_last_success_state("bucket", "jobintel", client=MissingClient())
    assert payload is None
    assert status == "not_found"
    assert key.endswith("state/last_success.json")
