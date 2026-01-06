#!/usr/bin/env python3
"""
Run OpenAI pipeline end-to-end:
1) scrape (snapshot)
2) parse + classify (existing run scripts)
3) enrich (Ashby GraphQL)
4) score (CS-fit ranking)

Assumes existing scripts:
- scripts/run_scrape.py
- scripts/run_classify.py
- scripts/enrich_jobs.py
- scripts/score_jobs.py
"""

import sys
import textwrap


def main() -> int:
    msg = textwrap.dedent(
        """
        DEPRECATED: Use scripts/run_daily.py instead.
        Example:
          python scripts/run_daily.py --profiles cs --us_only --no_post
        """
    ).strip()
    print(msg)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
