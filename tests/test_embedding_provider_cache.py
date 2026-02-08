from __future__ import annotations

from pathlib import Path
from typing import List

from ji_engine.embeddings.provider import EmbeddingProvider
from ji_engine.models import JobSource, RawJobPosting
from ji_engine.utils.time import utc_now_naive
from scripts.run_classify import _reclassify_maybe


class FakeEmbeddingProvider(EmbeddingProvider):
    def __init__(self):
        self.calls: List[str] = []

    def embed(self, text: str) -> List[float]:
        self.calls.append(text)
        # simple deterministic vector
        return [float(len(text))]


def test_reclassify_uses_cache(monkeypatch, tmp_path: Path) -> None:
    cache_path = tmp_path / "embed_cache.json"
    provider = FakeEmbeddingProvider()
    profile_text = "foo bar"
    profile_vec = provider.embed(profile_text)

    job = RawJobPosting(
        source=JobSource.OPENAI,
        title="Maybe role",
        location="Remote",
        team=None,
        apply_url="u1",
        detail_url="d1",
        raw_text="Some description",
        scraped_at=utc_now_naive(),
    )
    labeled = [{"relevance": "MAYBE"}]

    # first run should call provider for job
    _reclassify_maybe([job], labeled, profile_vec, provider, cache_path, threshold=0.0)
    assert len(provider.calls) == 2  # profile + job

    # second run should hit cache (no new embeds)
    _reclassify_maybe([job], labeled, profile_vec, provider, cache_path, threshold=0.0)
    assert len(provider.calls) == 2
