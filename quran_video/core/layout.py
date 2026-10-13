"""Wrap Arabic words into lines that fit a box, shrinking the font until they do."""

from dataclasses import dataclass

from PySide6.QtGui import QFont, QFontMetricsF


@dataclass(frozen=True)
class Layout:
    fonts: list[QFont]  # one per word (the verse-end sign may use another family)
    lines: list[list[int]]  # word indices (into the words passed to fit) per line, reading order
    widths: list[float]
    space: float
    line_h: float
    ascent: float
    fits: bool


def wrap(widths: list[float], space: float, max_w: float) -> list[list[int]]:
    lines, cur, cur_w = [], [], 0.0
    for i, w in enumerate(widths):
        need = w if not cur else cur_w + space + w
        if cur and need > max_w:
            lines.append(cur)
            cur, need = [], w
        cur.append(i)
        cur_w = need
    if cur:
        lines.append(cur)
    return lines


def make_font(family: str, px: int) -> QFont:
    f = QFont(family)
    f.setPixelSize(px)
    return f


def fit(words: list[str], families: list[str], box_w: float, box_h: float, max_px: int, min_px: int,
        line_spacing: float) -> Layout:
    """families[0] sets the line metrics; each word is measured in its own family."""
    px = max_px
    while True:
        fonts = [make_font(f, px) for f in families]
        fm = QFontMetricsF(fonts[0])
        widths = [QFontMetricsF(f).horizontalAdvance(w) for f, w in zip(fonts, words)]
        space = max(fm.horizontalAdvance(" "), px * 0.25)  # some fonts have a very narrow space
        lines = wrap(widths, space, box_w)
        line_h = fm.lineSpacing() * line_spacing  # fraction of the font's own line height
        fits = len(lines) * line_h <= box_h
        if fits or px <= min_px:
            return Layout(fonts, lines, widths, space, line_h, fm.ascent(), fits)
        px = max(min_px, int(px * 0.9))
