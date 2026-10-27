"""The progress bar of the timing window: the recording's loudness, every batch as a block between its start and
end checkpoints, the part of the recording that is used, and where it is playing.

Click to go to a moment; drag a checkpoint to move it (the window keeps the batches in order)."""

from typing import NamedTuple

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QToolTip, QWidget

from ..config.fonts import TRANSLATION_FONT
from ..core.manual import END, START
from ..core.render import load_font
from .form import clock
from .style import PALETTES

ARABIC, TRANSLATION, TRIM = "arabic", "translation", "trim"
GRAB_PX = 7  # how near a checkpoint the pointer must be to drag it


class Block(NamedTuple):
    """One batch on the bar: on screen from `start` to `end`; `marked_end` is its own end checkpoint, if set."""
    start: int
    end: int
    marked_end: int | None
    label: str  # its number
    tip: str  # what it shows, for the tooltip
    ticks: tuple[int, ...] = ()  # tapped word starts


def _font(px: int, bold: bool = False) -> QFont:
    f = QFont(load_font(TRANSLATION_FONT))
    f.setPixelSize(px)
    f.setBold(bold)
    return f


class Timeline(QWidget):
    seek = Signal(int)  # ms in the recording
    grabbed = Signal()  # a checkpoint is about to be dragged
    moved = Signal(str, int, str, int)  # track, block, START or END, ms (TRIM: block 0, START or END)
    selected = Signal(str, int)  # a block was clicked: track, batch

    def __init__(self, follow: bool = False):
        """With `follow`, it shows a few seconds around the playhead instead of the whole recording."""
        super().__init__()
        self.follow = follow
        self.setMouseTracking(True)
        self.setLayoutDirection(Qt.LayoutDirection.LeftToRight)  # time runs left to right in every language
        self.setMinimumHeight(132 if follow else 112)
        self.colors = PALETTES["Light"]
        self.length = 1  # ms
        self.env: list[float] = []  # loudness per 20 ms
        self.peak = 1.0
        self.tracks: dict[str, list[Block]] = {ARABIC: [], TRANSLATION: []}
        self.show_translation = False
        self.trim: tuple[int, int] = (0, 1)
        self.playhead = 0
        self.current: tuple[str, int] = (ARABIC, -1)
        self._drag: tuple[str, int, str] | None = None

    # ---------------------------------------------------------------- data
    def set_length(self, ms: int) -> None:
        self.length = max(ms, 1)
        self.update()

    def set_envelope(self, env: list[float]) -> None:
        self.env = env
        loud = sorted(env)
        self.peak = (loud[int(len(loud) * 0.98)] if loud else 1.0) or 1.0  # ignore the odd click
        self.update()

    def set_tracks(self, arabic: list[Block], translation: list[Block] | None, trim: tuple[int, int],
                   current: tuple[str, int]) -> None:
        self.tracks = {ARABIC: arabic, TRANSLATION: translation or []}
        self.show_translation = translation is not None
        self.trim, self.current = trim, current
        self.update()

    def set_playhead(self, ms: int) -> None:
        if ms != self.playhead:
            self.playhead = ms
            self.update()

    # ---------------------------------------------------------------- geometry
    def view(self) -> tuple[int, int]:
        if not self.follow:
            return 0, self.length
        span = min(20000, self.length)
        a = min(max(self.playhead - span // 4, 0), self.length - span)
        return a, a + span

    def x_of(self, ms: float) -> float:
        a, b = self.view()
        return 8 + (ms - a) / max(b - a, 1) * (self.width() - 16)

    def ms_of(self, x: float) -> int:
        a, b = self.view()
        return round(min(max(a + (x - 8) / max(self.width() - 16, 1) * (b - a), 0), self.length))

    def _rows(self) -> dict[str, QRectF]:
        """Where each part goes: the time scale, the loudness, and one row per track."""
        w, top = self.width(), 18.0
        row_h = 26.0
        tracks = 2 if self.show_translation else 1
        wave_h = max(self.height() - top - tracks * (row_h + 4) - 4, 20)
        rows = {"wave": QRectF(0, top, w, wave_h)}
        y = top + wave_h + 4
        for name in [ARABIC, TRANSLATION][:tracks]:
            rows[name] = QRectF(0, y, w, row_h)
            y += row_h + 4
        return rows

    def _handles(self) -> list[tuple[float, QRectF, str, int, str]]:
        """Every checkpoint that can be dragged: (x, the row, track, batch, START or END)."""
        rows, out = self._rows(), []
        for track in (ARABIC, TRANSLATION):
            if track not in rows:
                continue
            for k, b in enumerate(self.tracks[track]):
                out.append((self.x_of(b.start), rows[track], track, k, START))
                if b.marked_end is not None:
                    out.append((self.x_of(b.marked_end), rows[track], track, k, END))
        wave = rows["wave"]
        out += [(self.x_of(self.trim[0]), wave, TRIM, 0, START), (self.x_of(self.trim[1]), wave, TRIM, 0, END)]
        return out

    def _handle_at(self, pos: QPointF):
        near = [(abs(x - pos.x()), h) for h in self._handles() for x in [h[0]]
                if abs(x - pos.x()) <= GRAB_PX and h[1].top() - 4 <= pos.y() <= h[1].bottom() + 4]
        return min(near, key=lambda n: n[0])[1] if near else None

    def _block_at(self, pos: QPointF) -> tuple[str, int] | None:
        rows = self._rows()
        for track in (ARABIC, TRANSLATION):
            if track in rows and rows[track].top() <= pos.y() <= rows[track].bottom():
                ms = self.ms_of(pos.x())
                return next(((track, k) for k, b in enumerate(self.tracks[track]) if b.start <= ms < b.end), None)
        return None

    # ---------------------------------------------------------------- mouse
    def mousePressEvent(self, e) -> None:
        if e.button() != Qt.MouseButton.LeftButton:
            return
        handle = self._handle_at(e.position())
        if handle is not None:
            self._drag = handle[2:]
            self.grabbed.emit()
            return
        block = self._block_at(e.position())
        if block is not None:
            self.selected.emit(*block)
        self.seek.emit(self.ms_of(e.position().x()))

    def mouseMoveEvent(self, e) -> None:
        if self._drag is not None:
            self.moved.emit(*self._drag[:2], self._drag[2], self.ms_of(e.position().x()))
            return
        handle = self._handle_at(e.position())
        self.setCursor(Qt.CursorShape.SizeHorCursor if handle is not None else Qt.CursorShape.PointingHandCursor)
        block = self._block_at(e.position())
        if block is not None:
            b = self.tracks[block[0]][block[1]]
            end = clock(b.marked_end) if b.marked_end is not None else ""
            QToolTip.showText(e.globalPosition().toPoint(), f"{b.label}. {b.tip}\n{clock(b.start)} - {end}".rstrip(" -"),
                              self)
        else:
            QToolTip.hideText()

    def mouseReleaseEvent(self, e) -> None:
        self._drag = None

    # ---------------------------------------------------------------- drawing
    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = self.colors
        p.setPen(QPen(QColor(c["border"]), 1))
        p.setBrush(QColor(c["card"]))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 6, 6)
        rows = self._rows()
        a, b = self.view()
        self._paint_scale(p, a, b)
        self._paint_wave(p, rows["wave"], a, b)
        for track in (ARABIC, TRANSLATION):
            if track in rows:
                self._paint_track(p, rows[track], track)
        # the parts of the recording left out of the video
        shade = QColor(c["text"])
        shade.setAlpha(28)
        full = QRectF(0, rows["wave"].top(), self.width(), self.height() - rows["wave"].top())
        p.fillRect(QRectF(full.left(), full.top(), max(self.x_of(self.trim[0]) - full.left(), 0), full.height()), shade)
        right = self.x_of(self.trim[1])
        p.fillRect(QRectF(right, full.top(), max(full.right() - right, 0), full.height()), shade)
        for x in (self.x_of(self.trim[0]), right):
            p.setPen(QPen(QColor(c["muted"]), 2))
            p.drawLine(QPointF(x, full.top()), QPointF(x, full.bottom()))
        x = self.x_of(self.playhead)
        p.setPen(QPen(QColor(c["error"]), 2))
        p.drawLine(QPointF(x, 4), QPointF(x, self.height() - 4))

    def _paint_scale(self, p: QPainter, a: int, b: int) -> None:
        span = max(b - a, 1)
        step = next(s for s in (1000, 2000, 5000, 10000, 15000, 30000, 60000, 120000, 300000, 600000, 10 ** 9)
                    if span / s <= 12)
        p.setFont(_font(10))
        p.setPen(QColor(self.colors["muted"]))
        for t in range((a // step + 1) * step, b, step):
            x = self.x_of(t)
            p.drawLine(QPointF(x, 13), QPointF(x, 17))
            p.drawText(QRectF(x - 30, 0, 60, 13), Qt.AlignmentFlag.AlignCenter, clock(t).split(".")[0])

    def _paint_wave(self, p: QPainter, row: QRectF, a: int, b: int) -> None:
        if not self.env:
            return
        color = QColor(self.colors["accent"])
        color.setAlpha(150)
        p.setPen(QPen(color, 1))
        mid, half = row.center().y(), row.height() / 2 - 2
        width = int(row.width())
        per = (b - a) / max(width, 1) / 20  # loudness frames per pixel
        for px in range(8, width - 8):
            i = int((a + (px - 8) / max(width - 16, 1) * (b - a)) / 20)
            chunk = self.env[i:i + max(int(per), 1)]
            if chunk:
                h = min(max(chunk) / self.peak, 1.0) * half
                p.drawLine(QPointF(px, mid - h), QPointF(px, mid + h))

    def _paint_track(self, p: QPainter, row: QRectF, track: str) -> None:
        c = self.colors
        p.setFont(_font(11, bold=True))
        for k, block in enumerate(self.tracks[track]):
            x0, x1 = self.x_of(block.start), self.x_of(block.end)
            if x1 < 0 or x0 > self.width():
                continue
            current = self.current == (track, k)
            fill = QColor(c["accent"] if current else c["accent_soft"])
            if not current and track == TRANSLATION:
                fill.setAlpha(150)
            p.setPen(QPen(QColor(c["accent"]), 1))
            p.setBrush(fill)
            p.drawRoundedRect(QRectF(x0, row.top(), max(x1 - x0, 2), row.height()), 4, 4)
            p.setPen(QPen(QColor(c["on_accent"] if current else c["text"]), 1))
            for t in block.ticks:
                x = self.x_of(t)
                p.drawLine(QPointF(x, row.bottom() - 6), QPointF(x, row.bottom() - 2))
            # the checkpoints: a flag at the start, a bar at a marked end
            flag = QPainterPath()
            flag.moveTo(x0, row.top())
            flag.lineTo(x0, row.bottom())
            p.setPen(QPen(QColor(c["accent_hover"]), 2))
            p.drawPath(flag)
            p.setPen(QColor(c["on_accent"] if current else c["text"]))
            p.drawText(QRectF(x0 + 4, row.top(), max(x1 - x0 - 6, 0), row.height()),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, block.label)
            if block.marked_end is not None:
                xe = self.x_of(block.marked_end)
                p.setPen(QPen(QColor(c["accent_hover"]), 2, Qt.PenStyle.DashLine))
                p.drawLine(QPointF(xe, row.top()), QPointF(xe, row.bottom()))
