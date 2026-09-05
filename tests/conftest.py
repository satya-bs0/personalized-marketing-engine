import pytest


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "live: live integration test requiring real API credentials — run with -m live",
    )
