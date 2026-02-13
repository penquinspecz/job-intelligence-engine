"""
SignalCraft
Copyright (c) 2026 Chris Menendez.
All Rights Reserved.
See LICENSE for permitted use.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import List

from ji_engine.embeddings.simple import hash_embed


class EmbeddingProvider:
    def embed(self, text: str) -> List[float]:
        raise NotImplementedError


class StubEmbeddingProvider(EmbeddingProvider):
    """Hash-based embedding; deterministic and offline."""

    def __init__(self, dim: int = 256):
        self.dim = dim

    def embed(self, text: str) -> List[float]:
        return hash_embed(text, dim=self.dim)


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """
    Calls OpenAI embeddings endpoint with simple backoff.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "text-embedding-3-small",
        timeout: int = 30,
        max_retries: int = 3,
        min_interval: float = 0.2,
    ):
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries
        self.min_interval = min_interval
        self._last_call_ts = 0.0

    def _throttle(self) -> None:
        elapsed = time.time() - self._last_call_ts
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)

    def embed(self, text: str) -> List[float]:
        payload = {"input": text, "model": self.model}
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        url = "https://api.openai.com/v1/embeddings"

        for attempt in range(self.max_retries):
            self._throttle()
            req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    emb = data.get("data", [{}])[0].get("embedding")
                    if isinstance(emb, list):
                        self._last_call_ts = time.time()
                        return [float(x) for x in emb]
                    raise RuntimeError("Invalid embedding response")
            except urllib.error.HTTPError as e:
                if e.code in (429, 500, 502, 503, 504) and attempt + 1 < self.max_retries:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                raise
            except Exception:
                if attempt + 1 >= self.max_retries:
                    raise
                time.sleep(1.5 * (attempt + 1))
        raise RuntimeError("Unreachable")


__all__ = ["EmbeddingProvider", "StubEmbeddingProvider", "OpenAIEmbeddingProvider"]
