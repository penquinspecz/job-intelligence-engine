from __future__ import annotations

import hashlib
from pathlib import Path

from ji_engine.providers.ashby_provider import AshbyProvider, parse_ashby_snapshot_html


def _job_id_set_hash(job_ids: list[str]) -> str:
    payload = "\n".join(job_ids).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def test_openai_snapshot_parse_deterministic(capsys, monkeypatch, tmp_path) -> None:
    snapshot_path = Path(__file__).resolve().parents[1] / "data" / "openai_snapshots" / "index.html"
    html = snapshot_path.read_text(encoding="utf-8")

    first = parse_ashby_snapshot_html(html, strict=True)
    second = parse_ashby_snapshot_html(html, strict=True)

    first_ids = sorted([str(job.get("job_id") or "").strip() for job in first if job.get("job_id")])
    second_ids = sorted([str(job.get("job_id") or "").strip() for job in second if job.get("job_id")])

    assert len(first) == len(second)
    assert len(first) >= 100
    assert first_ids == second_ids
    assert _job_id_set_hash(first_ids) == _job_id_set_hash(second_ids)

    monkeypatch.setenv("JOBINTEL_ALLOW_HTML_FALLBACK", "0")
    provider = AshbyProvider("openai", "https://jobs.ashbyhq.com/openai", tmp_path)
    provider._parse_html(html)
    captured = capsys.readouterr().out
    assert "Falling back to HTML parsing" not in captured
