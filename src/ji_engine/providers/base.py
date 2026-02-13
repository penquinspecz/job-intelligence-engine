"""
SignalCraft
Copyright (c) 2026 Chris Menendez.
All Rights Reserved.
See LICENSE for permitted use.
"""

# src/ji_engine/providers/base.py

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import List

from ji_engine.models import RawJobPosting


class BaseJobProvider(ABC):
    """
    Base provider that handles mode selection and snapshot fallback.

    Modes:
      - SNAPSHOT: only load from local HTML/JSON
      - LIVE: try HTTP scrape, on error fall back to snapshot
    """

    def __init__(self, mode: str = "SNAPSHOT", data_dir: str = "data"):
        self.mode = mode.upper()
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def fetch_jobs(self) -> List[RawJobPosting]:
        """Top-level orchestrator for fetching jobs."""
        if self.mode == "SNAPSHOT":
            print(f"[{self.__class__.__name__}] Mode=SNAPSHOT → loading from snapshot")
            return self.load_from_snapshot()
        else:
            print(f"[{self.__class__.__name__}] Mode=LIVE → attempting live scrape")
            try:
                return self.scrape_live()
            except Exception as e:
                print(f"[{self.__class__.__name__}] Live scrape failed: {e}")
                print(f"[{self.__class__.__name__}] Falling back to snapshot...")
                return self.load_from_snapshot()

    @abstractmethod
    def scrape_live(self) -> List[RawJobPosting]:
        """Implement HTTP-based scraping here."""
        raise NotImplementedError

    @abstractmethod
    def load_from_snapshot(self) -> List[RawJobPosting]:
        """Implement snapshot-based parsing here."""
        raise NotImplementedError
