import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from quran_video.api.client import QuranClient
from quran_video.config.fonts import FONTS
from quran_video.config.presets import FORMATS
from quran_video.config.themes import THEMES
from quran_video.core.export import Prepared, frame_plan
from quran_video.core.render import RenderOptions, TextRenderer
from quran_video.core.timing import State


def test_frame_plan_eases_out_swaps_early_and_eases_in():
    class R:  # one page per verse
        def page_key(self, s):
            return (s.verse, 0)

    from quran_video.core.timing import Clip, Seg
    clips = [Clip(0, 0, 3000, (Seg(1, 0, 2800),)), Clip(1, 3000, 6000, (Seg(1, 3000, 5800),))]
    prep = Prepared(R(), clips, None, 0, 6000, (1080, 1920))
    plan = frame_plan(prep, 30)  # 180 frames; page change at frame 90, swapped in 4 frames earlier (120 ms)
    a = [f.alpha for f in plan]
    assert a[0] == 1.0 and plan[0].state.verse == 0  # first page appears at once
    assert a[85] == 0.0 or a[86] == 0.0  # fully invisible at the swap
    assert plan[85].state.verse == 0 and plan[86].state.verse == 1  # next verse swapped in before it is recited
    assert plan[86].state.active is None and plan[86].state.reveal == 0  # ...unlit, and no words revealed yet
    out = a[78:86]
    assert out == sorted(out, reverse=True) and out[0] > 0.5  # eases out
    inn = a[86:100]
    assert inn == sorted(inn) and inn[-1] == 1.0  # eases in to full
    # smoothstep: slower at the ends than a straight line
    assert inn[1] < 1 / 12 * 1.0 + 0.05
    assert a[-1] < 0.2  # the last page eases out at the end
    assert all(f.alpha == 1.0 for f in frame_plan(prep, 30, fade=False))


@pytest.mark.slow_network
@pytest.mark.parametrize("fmt", list(FORMATS))
def test_longest_verse_fits_every_format(app, fmt):
    c = QuranClient()
    font = FONTS["QPC Hafs"]
    verse = c.verses(2, font.text_field)[281:282]  # 2:282, the longest verse
    w, h = FORMATS[fmt]
    r = TextRenderer(w, h, verse, font, RenderOptions(THEMES["Classic"], split="verse"))
    pages = r.pages(0)
    box_h = min(h * 0.7, r.bottom - r.top)
    for p in pages:
        assert len(p.lines) * p.lay.line_h <= box_h + 1  # nothing overflows, even at minimum size
        for line in p.lines:
            assert sum(p.widths[g] for g in line) + p.lay.space * (len(line) - 1) <= w * 0.84 + 1
    img = r.render(State(0, 3, 3))
    assert img.width() == w and img.height() == h


@pytest.mark.slow_network
def test_a_huge_surah_name_shrinks_a_long_verse_instead_of_moving_it(app):
    c = QuranClient()
    font = FONTS["QPC Hafs"]
    verse = c.verses(2, font.text_field)[281:282]  # 2:282, the longest verse
    for fmt in ("9:16", "1:1", "16:9"):
        w, h = FORMATS[fmt]
        r = TextRenderer(w, h, verse, font, RenderOptions(THEMES["Classic"], split="verse", chapter=2, name_scale=2.0))
        assert r.max_h <= h - 2 * r.header_h + 1  # room is kept above and below, so the text is centred and clear
        for p in r.pages(0):
            block = len(p.lines) * p.lay.line_h
            assert block <= r.max_h + 1 and (h - block) / 2 >= r.header_h - 1, fmt  # never reaches the name


@pytest.mark.slow_network
def test_wider_text_uses_fewer_lines(app):
    c = QuranClient()
    font = FONTS["QPC Hafs"]
    verse = c.verses(2, font.text_field)[281:282]
    lines = {}
    for tw in (0.6, 0.95):
        r = TextRenderer(1080, 1920, verse, font,
                         RenderOptions(THEMES["Classic"], split="verse", stops=(), text_width=tw))
        lines[tw] = sum(len(p.lines) for p in r.pages(0))
    assert lines[0.95] <= lines[0.6]


def test_quality_scaling_keeps_even_sizes():
    from quran_video.config.quality import QUALITIES, scaled_size
    for q in QUALITIES.values():
        for w, h in FORMATS.values():
            sw, sh = scaled_size(w, h, q.scale)
            assert sw % 2 == 0 and sh % 2 == 0 and abs(sw / w - q.scale) < 0.01


@pytest.mark.slow_network
def test_reveal_style_shows_nothing_before_the_first_word(app):
    from PySide6.QtGui import QColor, QImage
    c = QuranClient()
    font = FONTS["QPC Hafs"]
    verse = c.verses(112, font.text_field)[:1]
    for style in ("build",):
        r = TextRenderer(1080, 1920, verse, font, RenderOptions(THEMES["Classic"], reveal=style))
        empty = QImage(1080, 1920, QImage.Format.Format_RGBA8888)
        empty.fill(QColor(0, 0, 0, 0))
        before = r.render(State(0, None, 0, 0))  # what the page shows while it fades in, before its first word
        assert bytes(before.constBits()) == bytes(empty.constBits()), style  # the whole verse must not flash
        assert bytes(r.render(State(0, 1, 1)).constBits()) != bytes(empty.constBits())


@pytest.mark.slow_network
def test_a_long_verse_keeps_its_sign_and_shares_its_translation_across_pages(app):
    c = QuranClient()
    font = FONTS["QPC Hafs"]
    verse = c.verses(2, font.text_field, 20)[281:282]  # 2:282, the longest verse, with Sahih International
    r = TextRenderer(1080, 1080, verse, font, RenderOptions(THEMES["Classic"], split="verse", translation=True))
    pages, n = r.pages(0), len(r.words[0])
    assert len(pages) > 1  # too tall for one page even at the minimum size
    texts = [p.translation for p in pages]
    assert all(texts) and len(set(texts)) == len(texts)  # each page has its own share, not a copy of the whole
    assert " ".join(texts) == verse[0].translation
    sign = [line for p in pages for line in p.lines if n in line]
    assert len(sign) == 1 and len(sign[0]) > 1  # the verse-end sign sits beside the last word
