from __future__ import annotations

import re
from typing import Optional

_JOB_ID_PATTERN = re.compile(r"/openai/([0-9a-f-]{36})/application", re.IGNORECASE)


def extract_job_id_from_url(url: str) -> Optional[str]:
    if not url:
        return None
    match = _JOB_ID_PATTERN.search(url)
    return match.group(1) if match else None
