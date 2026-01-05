"""
sitecustomize is imported automatically by Python at startup (if on sys.path).

We use it to silence urllib3's LibreSSL warning on macOS builds where Python's
ssl module is compiled against LibreSSL (< OpenSSL 1.1.1).
"""
import warnings

# Primary: filter by warning category if available
try:
    from urllib3.exceptions import NotOpenSSLWarning  # type: ignore
    warnings.filterwarnings("ignore", category=NotOpenSSLWarning)
except Exception:
    # Fallback: filter by message pattern (works even if urllib3 isn't importable yet)
    warnings.filterwarnings(
        "ignore",
        message=r"urllib3 v2 only supports OpenSSL 1\.1\.1\+.*",
    )
