"""Platform icons: Bootstrap Icons (MIT, assets/ui/icons), tinted to the current theme."""

from pathlib import Path

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtSvg import QSvgRenderer

ICON_DIR = Path(__file__).resolve().parents[2] / "assets" / "ui" / "icons"


def pixmap(name: str, color: str, size: int = 18, dpr: float = 2.0) -> QPixmap:
    svg = (ICON_DIR / f"{name}.svg").read_text("utf-8").replace("currentColor", color)
    px = QPixmap(int(size * dpr), int(size * dpr))
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    QSvgRenderer(QByteArray(svg.encode())).render(p)
    p.end()
    px.setDevicePixelRatio(dpr)
    return px


def theme_swatch(background: str, highlight: str, width: int = 36, height: int = 18, dpr: float = 2.0) -> QPixmap:
    """A theme's two colours as two solid squares side by side (no blend), in a thin outline."""
    px = QPixmap(int(width * dpr), int(height * dpr))
    px.fill(Qt.GlobalColor.transparent)
    px.setDevicePixelRatio(dpr)
    p = QPainter(px)
    half = width / 2
    p.fillRect(0, 0, int(half), height, QColor(background))
    p.fillRect(int(half), 0, width - int(half), height, QColor(highlight))
    outline = QColor(128, 128, 128, 200)
    p.setPen(QPen(outline, 1))
    p.drawRect(0, 0, width - 1, height - 1)
    p.drawLine(int(half), 0, int(half), height)
    p.end()
    return px
