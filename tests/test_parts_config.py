from quran_video.config.fonts import DEFAULT_FONT, FONTS
from quran_video.config.themes import DEFAULT_THEME, THEMES
from quran_video.config.stops import INDOPAK, MADANI, STOPS, chars_for, supported
from quran_video.core.render import split_parts


def test_split_parts_default_cuts_after_lazim_and_qila_only():
    # default: Lāzim (06D8) and Qilā (06D7); Jā'iz (06DA), sala (06D6) and lam-alef (06D9) do not cut
    words = ["a", "b\u06da", "c\u06d6", "d", "e\u06d7", "f\u06d9", "g\u06d8", "h"]
    assert split_parts(words) == [[0, 1, 2, 3, 4], [5, 6], [7]]


def test_split_parts_no_stop_is_one_chunk():
    assert split_parts(["a", "b", "c"]) == [[0, 1, 2]]


def test_defaults():
    t = THEMES[DEFAULT_THEME]
    assert (t.bg, t.text, t.highlight) == ("#000000", "#FFFFFF", "#3BB5BC")  # black / white / the app blue
    assert DEFAULT_FONT == "QPC Hafs" and FONTS[DEFAULT_FONT].path.exists()
    assert all(f.path.exists() for f in FONTS.values())


def test_split_parts_user_chosen_stops():
    words = ["a", "b\u06da", "c\u06d6", "d", "e\u06d7", "g\u06d8", "h"]
    assert split_parts(words, "\u06d6\u06d8") == [[0, 1, 2], [3, 4, 5], [6]]  # sala + meem only
    assert split_parts(words, "\u06da") == [[0, 1], [2, 3, 4, 5, 6]]  # jeem only


def test_every_stop_sign_is_optional():
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from dataclasses import replace
    from quran_video.api.models import Verse, Word
    from quran_video.core.render import RenderOptions, TextRenderer
    words = tuple(Word(i + 1, t, False) for i, t in enumerate(["a", "b\u06da", "c\u06d8", "d"]))
    v = [Verse("x:1", 1, words)]

    def pages(split, stops):
        r = TextRenderer(1080, 1920, v, FONTS["QPC Hafs"],
                         RenderOptions(THEMES["Classic"], split=split, stops=stops, verse_marker=False))
        return len(r.pages(0))
    assert pages("verse", ("lazim", "qila", "jaiz")) == 1  # full verse never cuts
    assert pages("parts", ("jaiz", "lazim")) == 3
    assert pages("parts", ("jaiz",)) == 2
    assert pages("parts", ("lazim",)) == 2
    assert pages("parts", ()) == 1  # nothing chosen: nothing cut


def test_stop_signs_follow_the_mushaf_style():
    assert supported(MADANI) == ["lazim", "qila", "jaiz", "sila"]
    assert supported(INDOPAK) == ["lazim", "mutlaq", "qif", "qila", "jaiz", "mujawwaz", "sila"]
    assert chars_for(("mutlaq", "qif", "mujawwaz"), MADANI) == ""  # not supported in the Madani style: adds nothing
    assert chars_for(("mutlaq", "qif"), INDOPAK) == "\u0615\ue01e"
    assert chars_for(("qila",), MADANI) == "\u06d7" and chars_for(("qila",), INDOPAK) == "\ue01c"
    assert [s.symbol for s in STOPS.values()] == ["مـ", "ط", "قف", "قلى", "ج", "ز", "صلى"]  # the order and symbols given
    assert [s.name for s in STOPS.values()] == ["Waqf Lāzim", "Waqf Muṭlaq", "Qif", "Qilā", "Waqf Jā’iz",
                                                "Waqf Mujawwaz", "Ṣilā"]


def test_indopak_font_cuts_at_its_own_signs():
    from dataclasses import replace
    from quran_video.api.models import Verse, Word
    from quran_video.core.render import RenderOptions, TextRenderer
    words = tuple(Word(i + 1, t, False) for i, t in enumerate(["a", "b\u0615", "c", "d\ue01e", "e"]))
    r = TextRenderer(1080, 1920, [Verse("x:1", 1, words)], replace(FONTS["Amiri Quran"], style=INDOPAK),  # no Indo-Pak font ships; the cut logic stays
                     RenderOptions(THEMES["Classic"], stops=("mutlaq", "qif", "qila"), verse_marker=False))
    assert len(r.pages(0)) == 3  # cut after the Muṭlaq word and the Qif word; no word here carries a Qilā sign


def test_default_highlight_is_word_by_word_and_classic_is_the_blue_one():
    from quran_video.config.themes import BUILTIN
    from quran_video.core.render import RenderOptions
    assert RenderOptions(THEMES["Classic"]).highlight == "word"
    assert [t.name for t in BUILTIN[:2]] == ["Classic", "Classic Yellow"]
    assert THEMES["Classic Yellow"].highlight == "#FFD60A" and THEMES["Classic"].highlight == "#3BB5BC"


def test_highlight_styles():
    from quran_video.core.render import is_lit
    from quran_video.core.timing import ALL, State
    s = State(0, 2, 3)  # word 2 is being recited; words up to 3 have been reached (a repeat)
    assert [is_lit("none", s, p) for p in (1, 2, 3, 4)] == [False] * 4  # default: no highlight
    assert [is_lit("word", s, p) for p in (1, 2, 3, 4)] == [False, True, False, False]
    assert [is_lit("keep", s, p) for p in (1, 2, 3, 4)] == [True, True, True, False]
    assert is_lit("word", State(0, ALL, ALL), 5) and is_lit("keep", State(0, ALL, ALL), 5)  # untimed verse


def test_every_theme_is_readable():
    def lum(h):
        r, g, b = (int(h.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4))
        f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
        return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)

    def contrast(a, b):
        hi, lo = sorted((lum(a), lum(b)), reverse=True)
        return (hi + 0.05) / (lo + 0.05)
    for th in THEMES.values():
        assert contrast(th.bg, th.text) >= 7, th.name  # WCAG AAA for the text
        assert contrast(th.bg, th.highlight) >= 4.5, th.name  # WCAG AA for the highlight
