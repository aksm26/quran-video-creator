import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session", autouse=True)
def qapp():
    """One QApplication for every test (a QGuiApplication made first would make widget tests abort)."""
    return QApplication.instance() or QApplication([])


@pytest.fixture
def app(qapp):
    return qapp


def pytest_collection_modifyitems(config, items):
    """Live tests go through the API proxy, so they need its URL (QVC_API_BASE)."""
    if os.environ.get("QVC_API_BASE"):
        return
    skip = pytest.mark.skip(reason="set QVC_API_BASE to the API proxy URL to run live tests")
    for item in items:
        if "slow_network" in item.keywords:
            item.add_marker(skip)
