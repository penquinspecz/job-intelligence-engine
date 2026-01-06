"""Unit tests for OpenAI provider snapshot parser."""

from pathlib import Path
import sys
import pytest

# Add src to path
ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from ji_engine.providers.openai_provider import OpenAICareersProvider


def test_titles_not_concatenated_with_metadata():
    """
    Regression test for historical bug where titles were concatenated with
    department/location without separators (e.g., '...SalesSan Francisco').
    """
    provider = OpenAICareersProvider(mode="SNAPSHOT", data_dir="data")

    snapshot_file = Path("data") / "openai_snapshots" / "index.html"
    if not snapshot_file.exists():
        pytest.skip(f"Snapshot file not found: {snapshot_file}")

    html = snapshot_file.read_text(encoding="utf-8")
    jobs = provider._parse_html(html)

    bad_substrings = {
        "SalesSan Francisco",
        "MarketingRemote",
        "CommunicationsSan Francisco",
        "Product OperationsSan Francisco",
        "Customer SuccessSan Francisco",
        "Human DataSan Francisco",
    }

    for job in jobs:
        assert job.title, "Title should not be empty"
        assert job.apply_url, "apply_url should not be empty"

        for bad in bad_substrings:
            assert bad not in job.title, f"Title '{job.title}' contains concatenated metadata substring '{bad}'"


def test_sanitize_title_removes_concatenated_dept_location():
    """
    Ensure title sanitization strips concatenated department/location with no separator.
    """
    provider = OpenAICareersProvider(mode="SNAPSHOT", data_dir="data")
    raw = "Field EngineerRoboticsSan Francisco"
    sanitized = provider._sanitize_title(raw, team="Robotics", location="San Francisco")
    assert sanitized == "Field Engineer", f"Expected 'Field Engineer', got '{sanitized}'"


if __name__ == "__main__":
    test_titles_do_not_contain_department_or_location()
