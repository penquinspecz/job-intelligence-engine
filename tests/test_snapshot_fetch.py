from types import SimpleNamespace

import pytest

from jobintel.snapshots.fetch import fetch_html


def test_fetch_html_requests(monkeypatch):
    def fake_get(url, headers=None, timeout=None):
        return SimpleNamespace(
            text="<html>ok</html>",
            status_code=200,
            url="https://example.com/final",
        )

    monkeypatch.setattr("jobintel.snapshots.fetch.requests.get", fake_get)

    html, meta = fetch_html("https://example.com", method="requests", timeout_s=5)
    assert html == "<html>ok</html>"
    assert meta["status_code"] == 200
    assert meta["final_url"] == "https://example.com/final"
    assert meta["bytes_len"] > 0
    assert meta["error"] is None


def test_fetch_html_playwright_missing(monkeypatch):
    # Deleting sys.modules is not deterministic; site-packages can still be re-imported.
    real_import = __import__

    def blocked_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "playwright" or name.startswith("playwright."):
            raise ModuleNotFoundError("No module named 'playwright'")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr("builtins.__import__", blocked_import)
    with pytest.raises(RuntimeError, match="Playwright is not installed"):
        fetch_html("https://example.com", method="playwright")
