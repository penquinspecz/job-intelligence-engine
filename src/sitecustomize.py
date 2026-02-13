"""SignalCraft
Copyright (c) 2026 Chris Menendez.
All Rights Reserved.
See LICENSE for permitted use.


sitecustomize is imported automatically by Python at startup (if on sys.path).

We use it to silence urllib3's LibreSSL warning on macOS builds where Python's
ssl module is compiled against LibreSSL (< OpenSSL 1.1.1).
"""

import warnings

# IMPORTANT:
# Do NOT import urllib3 here. Importing it can trigger the warning before we filter it.
warnings.filterwarnings(
    "ignore",
    message=r"urllib3 v2 only supports OpenSSL 1\.1\.1\+.*",
)
