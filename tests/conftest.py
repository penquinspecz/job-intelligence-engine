import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--update-golden",
        action="store_true",
        default=False,
        help="Rewrite golden fixtures for snapshot-based tests",
    )
