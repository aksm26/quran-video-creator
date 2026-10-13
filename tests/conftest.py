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
