"""Render the transparent text layer for one state with QPainter (HarfBuzz shaping)."""

from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QFontMetricsF, QImage, QPainter

from ..api.models import Verse
from ..config.fonts import SURAH_NAME_FONT, TRANSLATION_FONT, FontSpec
from ..config.stops import DEFAULT_STOPS, MADANI, chars_for
from ..config.themes import Theme
from .layout import Layout, fit, make_font
from .timing import ALL, State
from .translation import letter_weight, split_translation

DEFAULT_TEXT_WIDTH = 0.84

SPLIT_VERSE, SPLIT_PARTS = "verse", "parts"
HIGHLIGHT_NONE, HIGHLIGHT_WORD, HIGHLIGHT_KEEP = "none", "word", "keep"
# all words shown / words appear as recited and stay / only the word being recited
REVEAL_OFF, REVEAL_BUILD, REVEAL_SINGLE = "off", "build", "single"

_families: dict[str, str] = {}


def load_font(path) -> str:
    """Register a font file with Qt (once) and return its family name."""
    key = str(path)
    if key not in _families:
        fid = QFontDatabase.addApplicationFont(key)
        if fid < 0:
            raise RuntimeError(f"Could not load font {path}")
        _families[key] = QFontDatabase.applicationFontFamilies(fid)[0]
    return _families[key]


@dataclass
class RenderOptions:
    theme: Theme
    split: str = SPLIT_PARTS  # SPLIT_PARTS (cut at the chosen stop signs) or SPLIT_VERSE (whole verse)
    stops: tuple[str, ...] = DEFAULT_STOPS  # keys of config.stops.STOPS to cut at (parts mode only)
    highlight: str = HIGHLIGHT_WORD  # none, the word being recited, or every word recited so far
    reveal: str = REVEAL_OFF  # REVEAL_BUILD: words appear as recited; REVEAL_SINGLE: only the current word
    line_spacing: float = 0.8
    verse_marker: bool = True  # the verse-end sign is always shown by the app; tests switch it off
    show_arabic: bool = True  # False: only the translation (and the surah name) is drawn
    chapter: int = 0  # >0 draws the surah name on top
    translation: bool = False  # draw each verse's translation under the Arabic
    overlay: float = 0.0  # 0..1 black veil over the background, for readability
    text_width: float = DEFAULT_TEXT_WIDTH  # share of the frame width the Arabic may use
    translation_width: float = DEFAULT_TEXT_WIDTH  # the same for the translation
    name_scale: float = 1.0  # size of the surah name
    fill: str | None = None  # colour painted under the text; None leaves it transparent, to lay over a picture


@dataclass
class Page:
    words: frozenset[int]  # verse-level word indices shown together (the verse-end sign is index len(words))
    lines: list[list[int]]  # verse-level word indices per line, reading order
    widths: dict[int, float]
    fonts: dict[int, QFont]
    lay: Layout  # shared spacing and line metrics
    translation: str = ""
    trans_font: QFont | None = None
    trans_h: float = 0.0


def split_parts(words: list[str], chars: str = chars_for(DEFAULT_STOPS, MADANI)) -> list[list[int]]:
    """Chunks of word indices, cut after every word that carries one of the stop signs `chars`."""
    chunks, cur = [], []
    for i, w in enumerate(words):
        cur.append(i)
        if any(c in w for c in chars):
            chunks.append(cur)
            cur = []
    if cur:
        chunks.append(cur)
    return chunks


def is_lit(highlight: str, state: State, pos: int) -> bool:
    """Is word number `pos` highlighted? Untimed verses (ALL) light up whole."""
    if highlight == HIGHLIGHT_NONE:
        return False
    if highlight == HIGHLIGHT_WORD:
        return state.active == ALL or state.active == pos
    return state.reveal == ALL or pos <= state.reveal


def mix(a: QColor, b: QColor, t: float) -> QColor:
    """The colour t of the way from a to b."""
    pairs = ((a.red(), b.red()), (a.green(), b.green()), (a.blue(), b.blue()))
    return QColor(*(round(x + (y - x) * t) for x, y in pairs))


def has_rtl(text: str) -> bool:
    return any("؀" <= c <= "ۿ" for c in text)


TRANS_FLAGS = int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap)


class TextRenderer:
    """Draws the text layer of a video frame: the verse (or part of it) on screen, its translation and the
    surah name, on a transparent image that ffmpeg lays over the background."""

    def __init__(self, width: int, height: int, verses: list[Verse], font: FontSpec, opts: RenderOptions):
        self.w, self.h, self.opts = width, height, opts
        self.verses = verses
        self.style = font.style
        self.family = load_font(font.path)
        self.marker_family = load_font(font.marker_path)
        self.trans_family = load_font(TRANSLATION_FONT)
        self.words = [[w.text for w in v.text_words] for v in verses]
        self.markers = [font.marker_fmt.format(n=v.end_text) if opts.verse_marker and v.end_text else ""
                        for v in verses]
        self.short = min(width, height)
        self.header_px = int(self.short * 0.13 * opts.name_scale)
        self.header_h = self.header_px * 1.3 + height * 0.02 if opts.chapter else 0.0  # the band the name occupies
        self.top, self.bottom = height * 0.03, height * 0.97
        # The text is centred on the frame exactly as it is without a surah name: the name never moves it. It only
        # limits how tall the text may grow, so a long verse shrinks a little instead of touching the name.
        avail = min(self.bottom - self.top, height - 2 * self.header_h)
        self.max_h = min(height * 0.7, avail)
        self.trans_max_h = (height * 0.18 if opts.show_arabic else avail * 0.8) if opts.translation else 0
        self.gap = self.short * 0.05  # space between the Arabic and its translation
        self._pages: dict[int, list[Page]] = {}
        self._header = (load_font(SURAH_NAME_FONT), f"surah{opts.chapter:03d}") if opts.chapter else None

    def _fit_translation(self, text: str) -> tuple[QFont, float]:
        box = QRectF(0, 0, self.w * self.opts.translation_width, 100000)
        px = int(self.short * (0.036 if self.opts.show_arabic else 0.058))  # larger when it stands alone
        while True:
            f = make_font(self.trans_family, px)
            h = QFontMetricsF(f).boundingRect(box, TRANS_FLAGS, text).height()
            if h <= self.trans_max_h or px <= int(self.short * 0.02):
                return f, h
            px = int(px * 0.92)

    def pages(self, verse: int) -> list[Page]:
        """Pages for a verse: the whole verse, or its parts; any page still too tall is split by lines."""
        if verse in self._pages:
            return self._pages[verse]
        words, marker = self.words[verse], self.markers[verse]
        chosen = chars_for(self.opts.stops, self.style) if self.opts.split == SPLIT_PARTS else ""
        chunks = split_parts(words, chosen) if chosen else [list(range(len(words)))]
        pieces = [""] * len(chunks)
        if self.opts.translation and self.verses[verse].translation:
            pieces = split_translation(self.verses[verse].translation,
                                       [letter_weight("".join(words[i] for i in c)) for c in chunks])
        if marker and chunks:
            chunks[-1] = chunks[-1] + [len(words)]  # the sign closes the last part
        shown = words + [marker]
        box_w = self.w * self.opts.text_width
        box_h = self.max_h - (self.trans_max_h + self.gap if self.opts.translation else 0)
        if not self.opts.show_arabic:
            box_h = 1e9  # no Arabic on screen, so it never needs paginating
        out = []
        for chunk, piece in zip(chunks, pieces):
            lay = fit([shown[i] for i in chunk],
                      [self.marker_family if i == len(words) else self.family for i in chunk],
                      box_w, box_h, int(self.short * 0.075 * self.opts.text_width / DEFAULT_TEXT_WIDTH),
                      int(self.short * 0.035), self.opts.line_spacing)
            widths = {g: lay.widths[n] for n, g in enumerate(chunk)}
            fonts = {g: lay.fonts[n] for n, g in enumerate(chunk)}
            lines = [[chunk[n] for n in line] for line in lay.lines]
            tf, th = self._fit_translation(piece) if piece else (None, 0.0)
            # still too tall at the minimum size: paginate by lines
            per = len(lines) if lay.fits else max(1, int(box_h // lay.line_h))
            for k in range(0, len(lines), per):
                part = lines[k:k + per]
                out.append(Page(frozenset(g for line in part for g in line), part, widths, fonts, lay,
                                piece, tf, th))
        self._pages[verse] = out
        return out

    def page_index(self, state: State) -> int:
        pages = self.pages(state.verse)
        if state.page is not None:
            return min(state.page, len(pages) - 1)
        if state.active in (None, ALL):
            return 0
        for n, p in enumerate(pages):
            if state.active - 1 in p.words:
                return n
        return 0

    def page_key(self, state: State) -> tuple[int, int]:
        """Identifies what is on screen; fades happen when it changes."""
        return state.verse, self.page_index(state)

    def render(self, state: State, alpha: float = 1.0, highlight_progress: float = 1.0,
               fading_word: int | None = None) -> QImage:
        """highlight_progress is how far the newest highlight has eased in (0..1); fading_word is the word it
        replaces, whose highlight eases out meanwhile. See export.Frame."""
        opts, theme = self.opts, self.opts.theme
        img = QImage(self.w, self.h, QImage.Format.Format_RGBA8888)
        img.fill(QColor(opts.fill) if opts.fill else Qt.GlobalColor.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        if opts.overlay > 0:
            p.fillRect(img.rect(), QColor(0, 0, 0, int(255 * opts.overlay)))
        if self._header:
            family, glyphs = self._header
            p.setFont(make_font(family, self.header_px))
            p.setPen(QColor(theme.text))
            p.drawText(QRectF(0, self.h * 0.02, self.w, self.header_px * 1.3), Qt.AlignmentFlag.AlignCenter, glyphs)
        p.setOpacity(alpha)  # only the verse fades; header and overlay stay put
        self._draw_verse(p, state, highlight_progress, fading_word)
        p.end()
        return img

    def _word_color(self, state: State, pos: int, progress: float, fading_word: int | None) -> QColor:
        theme = self.opts.theme
        text, high = QColor(theme.text), QColor(theme.highlight)
        lit = is_lit(self.opts.highlight, state, pos)
        if lit and state.active == pos and progress < 1:
            return mix(text, high, progress)  # the newly lit word fades in
        if not lit and fading_word == pos and progress < 1 and self.opts.highlight == HIGHLIGHT_WORD:
            return mix(high, text, progress)  # and the word it replaces fades out
        return high if lit else text

    def _single_word(self, state: State, shown: list[str], n: int) -> list[tuple[str, str]]:
        """(text, family) pieces of the one word on screen; the verse-end sign joins the last word."""
        if state.active is None:  # nothing recited yet
            return []
        pieces = [(shown[state.active - 1], self.family)]
        if state.active == n and shown[n]:
            pieces.append((shown[n], self.marker_family))
        return pieces

    def _single_font_px(self, pieces: list[tuple[str, str]]) -> int:
        px, limit = int(self.short * 0.10), self.w * min(0.98, self.opts.text_width + 0.06)
        while px > int(self.short * 0.05):
            width = sum(QFontMetricsF(make_font(f, px)).horizontalAdvance(t) for t, f in pieces)
            if width + px * 0.25 * (len(pieces) - 1) <= limit:
                break
            px = int(px * 0.92)
        return px

    def _single_height(self, state: State, shown: list[str], n: int) -> float:
        pieces = self._single_word(state, shown, n)
        if not pieces:
            return 0.0
        font = make_font(self.family, self._single_font_px(pieces))
        return QFontMetricsF(font).lineSpacing() * 1.2  # a full line, so the marks above and below fit

    def _draw_single(self, p: QPainter, state: State, shown: list[str], n: int, top: float, height: float,
                     colour: QColor) -> None:
        pieces = self._single_word(state, shown, n)
        if not pieces:
            return
        px = self._single_font_px(pieces)
        fonts = [make_font(f, px) for _, f in pieces]
        widths = [QFontMetricsF(f).horizontalAdvance(t) for f, (t, _) in zip(fonts, pieces)]
        space = px * 0.25
        x = (self.w + sum(widths) + space * (len(pieces) - 1)) / 2  # RTL: the word first, its sign on the left
        ascent = QFontMetricsF(fonts[0]).ascent()
        baseline = top + (height - ascent) / 2 + ascent * 0.8
        for i, (font, (text, _), w) in enumerate(zip(fonts, pieces, widths)):
            x -= w
            p.setFont(font)
            p.setPen(colour if i == 0 else QColor(self.opts.theme.text))
            p.drawText(QPointF(x, baseline), text)
            x -= space

    def _draw_verse(self, p: QPainter, state: State, progress: float, fading_word: int | None) -> None:
        theme, words, n = self.opts.theme, self.words[state.verse], len(self.words[state.verse])
        shown = words + [self.markers[state.verse]]
        page = self.pages(state.verse)[self.page_index(state)]
        lay = page.lay
        reveal = self.opts.reveal
        arabic = self.opts.show_arabic
        single = arabic and reveal == REVEAL_SINGLE and state.active != ALL
        if not arabic:
            arabic_h = gap = 0.0
        elif single:
            arabic_h, gap = self._single_height(state, shown, n), self.gap * 1.5  # one big word needs more room
        else:
            arabic_h, gap = len(page.lines) * lay.line_h, self.gap
        block_h = arabic_h + (gap + page.trans_h if page.translation else 0)
        top = self.top + (self.bottom - self.top - block_h) / 2  # Arabic and translation centred as one block
        if arabic and single:
            if state.active is not None:
                colour = self._word_color(state, state.active, progress, fading_word)
                self._draw_single(p, state, shown, n, top, arabic_h, colour)
        elif arabic:
            for row, line in enumerate(page.lines):
                line_w = sum(page.widths[word] for word in line) + lay.space * (len(line) - 1)
                x = (self.w + line_w) / 2  # RTL: first word at the right edge
                baseline = top + row * lay.line_h + (lay.line_h - lay.ascent) / 2 + lay.ascent * 0.8
                for word in line:  # index into `shown`; word n is the verse-end sign
                    x -= page.widths[word]
                    hidden = reveal == REVEAL_BUILD and state.reveal != ALL and word < n and word + 1 > state.reveal
                    if word == n:  # verse-end sign appears once the last word has been recited
                        hidden = reveal == REVEAL_BUILD and state.reveal != ALL and state.reveal < n
                    if not hidden:
                        p.setFont(page.fonts[word])
                        p.setPen(self._word_color(state, word + 1, progress, fading_word) if word < n
                                 else QColor(theme.text))
                        p.drawText(QPointF(x, baseline), shown[word])
                    x -= lay.space
        if page.translation:
            p.setFont(page.trans_font)
            c = QColor(theme.text)
            c.setAlphaF(0.85)
            p.setPen(c)
            p.setLayoutDirection(Qt.LayoutDirection.RightToLeft if has_rtl(page.translation)
                                 else Qt.LayoutDirection.LeftToRight)
            tw = self.opts.translation_width
            p.drawText(QRectF(self.w * (1 - tw) / 2, top + arabic_h + gap, self.w * tw, page.trans_h),
                       TRANS_FLAGS, page.translation)
