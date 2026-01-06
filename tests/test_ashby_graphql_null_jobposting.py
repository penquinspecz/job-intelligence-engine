import json
from pathlib import Path
from unittest import mock

from ji_engine.integrations.ashby_graphql import fetch_job_posting


class _Resp:
    def __init__(self, data):
        self.status_code = 200
        self._data = data
        self.text = json.dumps(data)

    def json(self):
        return self._data

    def raise_for_status(self):
        return None


def test_jobposting_null_not_cached(tmp_path):
    cache_dir = tmp_path
    job_id = "123"

    resp_data = {"data": {"jobPosting": None}}

    with mock.patch("requests.post", return_value=_Resp(resp_data)) as _mock_post:
        result = fetch_job_posting(org="openai", job_id=job_id, cache_dir=cache_dir, force=True)

    assert result is None
    cache_file = cache_dir / f"{job_id}.json"
    assert not cache_file.exists()

