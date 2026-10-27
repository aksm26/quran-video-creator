"""Picking words on screen: a mushaf page (the Arabic) or the translations of its verses. Click a first word, then
a last word: that range is picked. Ranges already chosen are tinted and numbered."""

from typing import NamedTuple

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ..config.fonts import SURAH_NAME_FONT, TRANSLATION_FONT
from ..core.manual import LINE_BASMALA, LINE_SURAH, LINE_WORDS, MushafPage, TokenRef, normalise
from ..core.render import has_rtl, load_font
from .style import PALETTES


class Mark(NamedTuple):
    """A range already chosen: tinted, with its number on its first word."""
    first: object
    last: object
    label: str
    selected: bool = False


def _px_font(family: str, px: float) -> QFont:
    f = QFont(family)
    f.setPixelSize(max(6, int(px)))
    return f


class PickView(QWidget):
    """What both views share: hit boxes, the word under the pointer, the first word of a pick, and the marks."""

    picked = Signal(object, object)  # the first and last word, in reading order
    pending_changed = Signal(object)  # the first word clicked, waiting for the last one (None: no pick going on)

    def __init__(self):
        super().__init__()
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        # Words are placed by hand, each line in its own script's direction: the app's language never flips them.
        self.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.colors = PALETTES["Light"]
        self.message = ""  # shown instead of the words (while loading, or when there is nothing to show)
        self._items: list[tuple[QRectF, object]] = []
        self._hover = None
        self._pending = None
        self._marks: list[Mark] = []

    def set_colors(self, palette: dict) -> None:
        self.colors = palette
        self.update()

    def set_marks(self, marks: list[Mark]) -> None:
        self._marks = marks
        self.update()

    def set_message(self, text: str) -> None:
        self.message = text
        self.update()

    @property
    def pending(self):
        return self._pending

    def clear_pending(self) -> None:
        if self._pending is not None:
            self._pending = None
            self.pending_changed.emit(None)
            self.update()

    def hit(self, pos: QPointF):
        return next((ref for rect, ref in self._items if rect.contains(pos)), None)

    def click(self, ref) -> None:
        """A click on word `ref`: the first word of a pick, or its last."""
        if self._pending is None:
            self._pending = ref
            self.pending_changed.emit(ref)
        else:
            first, last = normalise(self._pending, ref)
            self._pending = None
            self.pending_changed.emit(None)
            self.picked.emit(first, last)
        self.update()

    def mouseMoveEvent(self, e) -> None:
        ref = self.hit(e.position())
        if ref != self._hover:
            self._hover = ref
            self.setCursor(Qt.CursorShape.PointingHandCursor if ref is not None else Qt.CursorShape.ArrowCursor)
            self.update()

    def leaveEvent(self, e) -> None:
        self._hover = None
        self.update()

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.RightButton:
            self.clear_pending()
            return
        ref = self.hit(e.position())
        if e.button() == Qt.MouseButton.LeftButton and ref is not None:
            self.click(ref)

    def keyPressEvent(self, e) -> None:
        if e.key() == Qt.Key.Key_Escape:
            self.clear_pending()
        else:
            super().keyPressEvent(e)

    def _mark_of(self, ref) -> Mark | None:
        inside = [m for m in self._marks if type(m.first) is type(ref) and m.first <= ref <= m.last]
        return next((m for m in inside if m.selected), inside[-1] if inside else None)

    def _paint_back(self, p: QPainter, rect: QRectF, ref) -> None:
        """The background of one word: its batch's tint, the range being picked, the pointer."""
        c = self.colors
        mark = self._mark_of(ref)
        if mark is not None:
            tint = QColor(c["accent"])
            tint.setAlpha(110 if mark.selected else 55)
            p.fillRect(rect, tint)
        if self._pending is not None and self._hover is not None and type(self._hover) is type(ref):
            a, b = normalise(self._pending, self._hover)
            if a <= ref <= b:
                p.fillRect(rect, QColor(c["accent_soft"]))
        if ref == self._hover:
            p.fillRect(rect, QColor(c["hover"]))
        if ref == self._pending:
            p.setPen(QPen(QColor(c["accent"]), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 4, 4)

    def _paint_badges(self, p: QPainter, rtl: bool) -> None:
        """Each range's number on its first word on screen."""
        c = self.colors
        p.setFont(_px_font(load_font(TRANSLATION_FONT), 11))
        done = set()
        for rect, ref in self._items:
            mark = self._mark_of(ref)
            if mark is None or mark.label in done:
                continue
            done.add(mark.label)
            size = 18
            x = rect.right() - size / 2 if rtl else rect.left() - size / 2
            badge = QRectF(x, rect.top() - size / 3, size, size)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(c["accent"]))
            p.drawEllipse(badge)
            p.setPen(QColor(c["on_accent"]))
            p.drawText(badge, Qt.AlignmentFlag.AlignCenter, mark.label)

    def _paint_frame(self, p: QPainter) -> None:
        c = self.colors
        p.setPen(QPen(QColor(c["border"]), 1))
        p.setBrush(QColor(c["card"]))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
        if self.message:
            p.setPen(QColor(c["muted"]))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, self.message)


class MushafView(PickView):
    """One page of the mushaf, fifteen lines, each justified right to left as in print."""

    def __init__(self):
        super().__init__()
        self.setMinimumSize(360, 480)
        self.page: MushafPage | None = None
        self.family, self.marker_fmt = "", "{n}"

    def set_page(self, page: MushafPage | None, family: str, marker_fmt: str) -> None:
        self.page, self.family, self.marker_fmt = page, family, marker_fmt
        self.message = ""
        self._hover = None
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(560, 760)

    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        self._paint_frame(p)
        self._items = []
        if self.page is None or self.message:
            return
        c = self.colors
        margin = 18
        lines = self.page.lines
        line_h = (self.height() - 2 * margin) / max(len(lines), 1)
        width = self.width() - 2 * margin
        # the page keeps a book's proportions: never wider than ~0.62 of its height
        width = min(width, (self.height() - 2 * margin) * 0.62)
        left = (self.width() - width) / 2
        px = line_h * 0.5
        for row, line in enumerate(lines):
            top = margin + row * line_h
            box = QRectF(left, top, width, line_h)
            if line.kind == LINE_SURAH:
                frame = box.adjusted(width * 0.08, line_h * 0.1, -width * 0.08, -line_h * 0.1)
                p.setPen(QPen(QColor(c["line"]), 1))
                p.setBrush(QColor(c["accent_soft"]))
                p.drawRoundedRect(frame, 6, 6)
                p.setPen(QColor(c["text"]))
                p.setFont(_px_font(load_font(SURAH_NAME_FONT), line_h * 0.62))
                p.drawText(frame, Qt.AlignmentFlag.AlignCenter, f"surah{line.chapter:03d}")
            elif line.kind == LINE_BASMALA:
                p.setPen(QColor(c["muted"]))
                p.setFont(_px_font(self.family, px))
                p.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
                p.drawText(box, Qt.AlignmentFlag.AlignCenter, " ".join(cell.text for cell in line.cells))
            elif line.kind == LINE_WORDS:
                self._paint_words(p, line.cells, box, px)
        self._paint_badges(p, rtl=True)

    def _paint_words(self, p: QPainter, cells, box: QRectF, px: float) -> None:
        c = self.colors
        texts = [self.marker_fmt.format(n=cell.text) if cell.sign else cell.text for cell in cells]
        font = _px_font(self.family, px)
        fm = QFontMetricsF(font)
        widths = [fm.horizontalAdvance(t) for t in texts]
        gap = px * 0.3
        total = sum(widths) + gap * (len(texts) - 1)
        if total > box.width():  # a long line: smaller, so it still fits
            font = _px_font(self.family, px * box.width() / total)
            fm = QFontMetricsF(font)
            widths = [fm.horizontalAdvance(t) for t in texts]
            gap *= box.width() / total
            total = sum(widths) + gap * (len(texts) - 1)
        if len(texts) > 1 and total >= box.width() * 0.75:  # a full line is justified, a short one centred
            gap = (box.width() - sum(widths)) / (len(texts) - 1)
            x = box.right()
        else:
            x = box.left() + (box.width() + total) / 2
        baseline = box.top() + box.height() * 0.62
        p.setFont(font)
        for cell, text, w in zip(cells, texts, widths):
            x -= w
            hit = QRectF(x - gap / 2, box.top() + 2, w + gap, box.height() - 4)
            self._paint_back(p, hit, cell.ref)
            p.setPen(QColor(c["accent"] if cell.sign else c["text"]))
            p.drawText(QPointF(x, baseline), text)
            self._items.append((hit, cell.ref))
            x -= gap


class TokenView(PickView):
    """The translation of every verse on the page, each word clickable. It grows as tall as its text; the tab puts
    it in a scroll area."""

    def __init__(self):
        super().__init__()
        self.rows: list[tuple[int, int, list[str]]] = []  # surah, verse, its translation's words
        self.setMinimumWidth(360)

    def set_rows(self, rows: list[tuple[int, int, list[str]]]) -> None:
        self.rows = rows
        self.message = ""
        self._hover = None
        self.setMinimumHeight(self._layout(self.width())[1])
        self.update()

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self.setMinimumHeight(self._layout(self.width())[1])

    def _layout(self, width: float) -> tuple[list[tuple[QRectF, TokenRef, str, bool]], float]:
        """Where each word goes: (box, ref, text, right to left), and the height it all takes."""
        font = _px_font(load_font(TRANSLATION_FONT), 15)
        fm = QFontMetricsF(font)
        margin, line_h, space = 18, fm.lineSpacing() * 1.35, fm.horizontalAdvance(" ")
        out, y = [], margin
        for ch, v, words in self.rows:
            rtl = has_rtl(" ".join(words))
            y += line_h * 0.25
            out.append((QRectF(margin, y, width - 2 * margin, line_h), None, f"{ch}:{v}", rtl))
            y += line_h
            x0, x1 = margin + 12, width - margin - 12
            x = x1 if rtl else x0
            for i, word in enumerate(words):
                w = fm.horizontalAdvance(word)
                if (x - w < x0 if rtl else x + w > x1) and x != (x1 if rtl else x0):
                    y += line_h
                    x = x1 if rtl else x0
                rect = QRectF(x - w if rtl else x, y, w, line_h)
                out.append((rect, TokenRef(ch, v, i), word, rtl))
                x = x - w - space if rtl else x + w + space
            y += line_h
        return out, y + margin

    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        self._paint_frame(p)
        self._items = []
        if self.message:
            return
        c = self.colors
        font = _px_font(load_font(TRANSLATION_FONT), 15)
        p.setFont(font)
        half = QFontMetricsF(font).horizontalAdvance(" ") / 2  # neighbouring words' boxes meet, never overlap
        rtl_page = False
        for rect, ref, text, rtl in self._layout(self.width())[0]:
            if ref is None:  # the verse number above its translation
                p.setPen(QColor(c["muted"]))
                p.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
                align = Qt.AlignmentFlag.AlignRight if rtl else Qt.AlignmentFlag.AlignLeft
                p.drawText(rect, align | Qt.AlignmentFlag.AlignAbsolute | Qt.AlignmentFlag.AlignVCenter, text)
                continue
            rtl_page = rtl_page or rtl
            hit = rect.adjusted(-half, 1, half, -1)
            self._paint_back(p, hit, ref)
            p.setPen(QColor(c["text"]))
            p.setLayoutDirection(Qt.LayoutDirection.RightToLeft if rtl else Qt.LayoutDirection.LeftToRight)
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
            self._items.append((hit, ref))
        self._paint_badges(p, rtl=rtl_page)
