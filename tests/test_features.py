"""Tests for the round of features: custom themes, highlight fade, widths, name size, video end, languages."""

import os
import re
import subprocess

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor

from quran_video import i18n
from quran_video.api.models import Verse, Word
from quran_video.config.fonts import FONTS
from quran_video.config.themes import (THEMES, add_custom, contrast, custom_themes, is_builtin, make_custom,
                                       readable_text, remove_custom)
from quran_video.config.translations import TRANSLATIONS
from quran_video.core.export import Prepared, frame_plan
from quran_video.core.ffmpeg import build_cmd, ffmpeg_exe, media_seconds
from quran_video.core.render import RenderOptions, TextRenderer
from quran_video.core.timing import Clip, Seg, State


def verse(text="a b c d", translation="", n=1):
    words = tuple(Word(i + 1, t, False) for i, t in enumerate(text.split()))
    return Verse(f"x:{n}", n, words, translation)


def renderer(opts, v=None, size=(1080, 1920)):
    return TextRenderer(*size, [v or verse()], FONTS["QPC Hafs"], opts)


# ---- custom themes
def test_custom_theme_picks_readable_text_and_can_be_removed():
    assert readable_text("#000000") == "#FFFFFF" and readable_text("#FFFFFF") == "#111111"
    t = make_custom("  Sea  ", "#123456", "#ffcc00")
    assert (t.name, t.bg, t.highlight) == ("Sea", "#123456", "#FFCC00") and contrast(t.bg, t.text) >= 7
    add_custom(t)
    try:
        assert "Sea" in THEMES and [x.name for x in custom_themes()] == ["Sea"] and not is_builtin("Sea")
        with pytest.raises(ValueError):
            add_custom(make_custom("Classic", "#000000", "#FFFFFF"))  # built-in names are taken
    finally:
        remove_custom("Sea")
        remove_custom("Classic")  # built-ins can never be removed
    assert "Sea" not in THEMES and "Classic" in THEMES


# ---- highlight fade
def test_highlight_fade_eases_in_the_new_word_and_out_the_old_one():
    class R:
        def page_key(self, s):
            return (s.verse, 0)
    clips = [Clip(0, 0, 2000, (Seg(1, 0, 500), Seg(2, 500, 1000), Seg(3, 1000, 1900)))]
    prep = Prepared(R(), clips, None, 0, 2000, (1080, 1920))
    plan = frame_plan(prep, 30, fade=False, hl_fade=True)
    at = lambda ms: plan[round(ms * 30 / 1000)]
    assert at(100)[2] < 1 and at(100)[3] is None  # word 1 is fading in
    state, alpha, hl, prev = at(520)  # just after word 2 starts
    assert state.active == 2 and 0 < hl < 1 and prev == 1  # word 2 in, word 1 out
    assert at(750)[2] == 1.0 and at(750)[3] is None  # settled
    ramp = [plan[i][2] for i in range(15, 21)]
    assert ramp == sorted(ramp)  # rises smoothly
    assert all(f[2] == 1.0 for f in frame_plan(prep, 30, fade=False, hl_fade=False))


def test_highlight_colour_blends_between_text_and_highlight(app):
    th = THEMES["Classic"]
    r = renderer(RenderOptions(th, highlight="word"))
    s = State(0, 2, 2)
    text, high = QColor(th.text), QColor(th.highlight)
    assert r._word_color(s, 2, 1.0, None) == high and r._word_color(s, 3, 1.0, None) == text
    mid = r._word_color(s, 2, 0.5, 1)
    assert text.red() > mid.red() > high.red() and mid != text and mid != high  # halfway between white and the blue
    assert r._word_color(s, 1, 0.5, 1) not in (text, high)  # the replaced word is fading out
    keep = renderer(RenderOptions(th, highlight="keep"))
    assert keep._word_color(State(0, 2, 2), 1, 0.5, None) == high  # kept words stay lit


def test_fade_at_zero_progress_looks_like_no_highlight(app):
    th = THEMES["Classic"]
    s = State(0, 2, 2)
    lit = renderer(RenderOptions(th, highlight="word")).render(s, 1.0, 0.0, None)
    none = renderer(RenderOptions(th, highlight="none")).render(s)
    assert bytes(lit.constBits()) == bytes(none.constBits())


# ---- widths and name size
def test_translation_width_changes_how_the_translation_wraps(app):
    v = verse(translation="In the name of Allah, the Entirely Merciful, the Especially Merciful, who guides all.")
    narrow = renderer(RenderOptions(THEMES["Classic"], translation=True, translation_width=0.5), v).pages(0)[0]
    wide = renderer(RenderOptions(THEMES["Classic"], translation=True, translation_width=0.98), v).pages(0)[0]
    assert narrow.trans_h >= wide.trans_h


def test_surah_name_size_scales_the_header_without_moving_the_text(app):
    small = renderer(RenderOptions(THEMES["Classic"], chapter=2, name_scale=0.5))
    big = renderer(RenderOptions(THEMES["Classic"], chapter=2, name_scale=2.0))
    assert big.header_px == 4 * small.header_px and big.header_h > small.header_h
    assert big.top == small.top  # the verse region starts in the same place whatever the name's size
    assert big.max_h <= small.max_h  # a big name only limits how tall the text may grow


def test_surah_name_does_not_move_the_text(app):
    v = verse(translation="Say, He is Allah, [who is] One.")
    plain = renderer(RenderOptions(THEMES["Classic"], translation=True), v)
    s = State(0, 2, 2)
    a = plain.render(s)
    for scale in (0.5, 1.0, 2.0):
        named = renderer(RenderOptions(THEMES["Classic"], translation=True, chapter=112, name_scale=scale), v)
        b = named.render(s)
        band = int(named.header_h) + 2
        middle = lambda im: im.copy(0, band, im.width(), im.height() - 2 * band)
        assert bytes(middle(a).constBits()) == bytes(middle(b).constBits()), scale  # same pixels below the name band
        assert bytes(a.constBits()) != bytes(b.constBits())  # and the name is drawn above them


def test_the_themes_are_ordered_darks_first_then_lights():
    from quran_video.config.themes import BUILTIN, luminance
    assert [t.name for t in BUILTIN] == ["Classic", "Classic Yellow", "Midnight", "Emerald & Gold", "Dusk",
                                         "Ivory & Blue", "Paper"]
    dark = [luminance(t.bg) < 0.2 for t in BUILTIN]
    assert dark == sorted(dark, reverse=True)  # every dark theme comes before every light one




# ---- background video that ends early
def test_video_background_loops_or_freezes(tmp_path):
    clip = tmp_path / "c.mp4"
    clip.write_bytes(b"x")
    cmd = lambda **k: " ".join(build_cmd("ff", 1080, 1920, 30, tmp_path / "a.mp3", 0, 5000, tmp_path / "o.mp4",
                                         background=clip, **k))
    assert "-stream_loop -1" in cmd() and "tpad" not in cmd()
    assert "-stream_loop" not in cmd(freeze=True) and "tpad=stop_mode=clone:stop=-1" in cmd(freeze=True)
    png = tmp_path / "p.png"
    png.write_bytes(b"x")
    assert "tpad" not in " ".join(build_cmd("ff", 10, 10, 30, tmp_path / "a.mp3", 0, 5000, tmp_path / "o.mp4",
                                            background=png, freeze=True))  # an image has no end


def test_media_seconds_and_freeze_really_encode(tmp_path):
    ff = ffmpeg_exe()
    clip, img = tmp_path / "c.mp4", tmp_path / "p.png"
    subprocess.run([ff, "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=s=320x240:r=24:d=2", str(clip)], check=True)
    subprocess.run([ff, "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=s=64x64", "-frames:v", "1", str(img)], check=True)
    assert abs(media_seconds(clip) - 2.0) < 0.1 and media_seconds(img) is None
    out = tmp_path / "o.mp4"
    audio = tmp_path / "a.wav"
    subprocess.run([ff, "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=d=4", str(audio)], check=True)
    cmd = build_cmd(ff, 320, 240, 24, audio, 0, 4000, out, background=clip, freeze=True)
    proc = subprocess.run(cmd, input=bytes(320 * 240 * 4 * 96), capture_output=True)  # 4 s of empty text frames
    assert proc.returncode == 0, proc.stderr[-300:]
    assert abs(media_seconds(out) - 4.0) < 0.2  # a 2 s video held to the full 4 s


# ---- languages
def test_every_language_covers_every_string_and_placeholders_survive():
    keys = set(i18n.TABLE["ar"])
    assert len(i18n.LANGUAGES) == 18 and set(i18n.TABLE) == set(i18n.LANGUAGES) - {"en"}
    for code, table in i18n.TABLE.items():
        assert set(table) == keys, code
        for key, text in table.items():
            assert text.strip(), (code, key)
            assert sorted(re.findall(r"\{\w+\}", key)) == sorted(re.findall(r"\{\w+\}", text)), (code, key)
    from quran_video.config.translations import LIST
    ids = {t.id for t in LIST}
    for lang in i18n.LANGUAGES.values():
        assert lang.translation_id is None or lang.translation_id in ids


def test_every_quran_translation_is_listed_and_every_language_is_named():
    from quran_video.config.language_names import NAMES, language_name
    from quran_video.config.translations import LIST, TRANSLATIONS, key_for_id
    assert len(LIST) == 125 and len(TRANSLATIONS) == 126 and len({t.id for t in LIST}) == 125
    assert len({t.key for t in LIST}) == 125 and len({t.lang for t in LIST}) >= 65
    assert 57 not in {t.id for t in LIST} and not any("ransliteration" in t.key for t in LIST)  # no transliteration option
    for ui in i18n.LANGUAGES:
        for t in LIST:
            assert NAMES[ui][t.lang].strip(), (ui, t.lang)
    assert language_name("es", "pt") == "Espanhol" and language_name("pt", "pt") == "Português"
    assert language_name("es", "en") == "Spanish" and language_name("en", "ar") == "الإنجليزية"
    assert key_for_id(103) == "Portuguese (Helmi Nasr)" and key_for_id(None) == "None"


def test_reciter_names_and_styles_are_translated():
    i18n.set_language("ar")
    try:
        assert i18n.reciter_name(7, "Mishari Rashid al-`Afasy") == "مشاري راشد العفاسي" and i18n.tr("Murattal") == "مرتل"
        assert i18n.tr("alternate copy") and i18n.tr("Dusk") == "الغسق"
        i18n.set_language("fr")
        assert i18n.reciter_name(7, "Mishari") == "Mishari" and i18n.tr("Kids repeat") == "Répétition pour enfants"
        assert not i18n.MISSING or "Murattal" not in i18n.MISSING
    finally:
        i18n.set_language("en")


@pytest.mark.slow_network
def test_switching_language_translates_the_window_and_picks_its_translation(app, tmp_path, monkeypatch):
    from PySide6.QtCore import QSettings
    QSettings.setPath(QSettings.Format.NativeFormat, QSettings.Scope.UserScope, str(tmp_path / "cfg"))
    from quran_video.ui.main_window import MainWindow
    w = MainWindow()
    try:
        assert w.in_parts.text() == "Cut at stop signs" and w.translation.currentData().startswith("English")
        i18n.MISSING.clear()
        for code in i18n.LANGUAGES:
            w._set_language(code)
            from quran_video.config.translations import key_for_id
            assert w.translation.currentData() == key_for_id(i18n.LANGUAGES[code].translation_id), code
            want = Qt.LayoutDirection.RightToLeft if i18n.is_rtl() else Qt.LayoutDirection.LeftToRight
            assert w.layoutDirection() == want, code
            if code != "en":
                assert w.in_parts.text() == i18n.TABLE[code]["Cut at stop signs"]
        assert not i18n.MISSING, i18n.MISSING  # every text the window shows has a translation
    finally:
        w._set_language("en")
        w.close()


# ---- Arabic left out, very low quality
def test_arabic_can_be_left_out(app):
    v = verse(translation="Say, He is Allah, [who is] One.")
    on = renderer(RenderOptions(THEMES["Classic"], translation=True), v)
    off = renderer(RenderOptions(THEMES["Classic"], translation=True, show_arabic=False), v)
    s = State(0, 2, 2)
    assert bytes(on.render(s).constBits()) != bytes(off.render(s).constBits())
    other = renderer(RenderOptions(THEMES["Classic"], translation=True, show_arabic=False, highlight="keep",
                                   reveal="build", text_width=0.6), v)
    assert bytes(off.render(s).constBits()) == bytes(other.render(s).constBits())  # the Arabic options are ignored
    assert len(off.pages(0)) == 1
    assert off.pages(0)[0].trans_font.pixelSize() > on.pages(0)[0].trans_font.pixelSize()  # bigger when it stands alone


def test_arabic_off_without_a_translation_is_refused():
    from pathlib import Path
    from quran_video.api.models import Reciter
    from quran_video.core.export import ExportJob, prepare
    from quran_video.core.timing import DataError
    job = ExportJob(112, 1, 4, Reciter(7, "A", "Murattal"), "9:16", Path("."), show_arabic=False, translation="None")
    with pytest.raises(DataError):
        prepare(job, None)  # refused before anything is fetched


def test_very_low_quality_is_the_smallest():
    from pathlib import Path
    from quran_video.config.quality import QUALITIES, scaled_size
    from quran_video.core.export import estimate_bytes
    assert list(QUALITIES)[-1] == "Very low" and scaled_size(1080, 1920, QUALITIES["Very low"].scale) == (432, 768)
    for background in (None, Path("a.png"), Path("a.mp4")):
        sizes = [estimate_bytes(60, background, q) for q in QUALITIES]
        assert sizes == sorted(sizes, reverse=True)  # every step down is smaller


def test_one_word_at_a_time_is_moderate_and_clear_of_the_translation(app):
    v = verse(text="a bb ccc dddd", translation="Say, He is Allah, [who is] One.")
    opts = RenderOptions(THEMES["Classic"], translation=True, reveal="single")
    r = renderer(opts, v)
    assert r._single_font_px([("abc", r.family)]) <= 0.105 * r.short  # not much bigger than a normal verse
    img = r.render(State(0, 2, 2))
    data, w = bytes(img.constBits()), img.width()
    ink = [any(data[y * w * 4 + 3:(y + 1) * w * 4:4]) for y in range(img.height())]
    rows = [y for y, on in enumerate(ink) if on]
    gaps = [b - a for a, b in zip(rows, rows[1:]) if b - a > 1]
    assert gaps and max(gaps) >= 0.04 * r.short  # a clear blank band between the word and its translation


def test_highlight_fade_is_smooth_and_starts_a_moment_early():
    from quran_video.core.export import HIGHLIGHT_FADE_MS, HIGHLIGHT_LEAD_MS
    class R:
        def page_key(self, s):
            return (s.verse, 0)
    clips = [Clip(0, 0, 3000, (Seg(1, 500, 1000), Seg(2, 1000, 3000)))]
    prep = Prepared(R(), clips, None, 0, 3000, (1080, 1920))
    plan = frame_plan(prep, 30, fade=False, hl_fade=True)
    first = next(i for i, f in enumerate(plan) if f[0].active == 2)
    assert first * 1000 / 30 < 1000 and first * 1000 / 30 >= 1000 - HIGHLIGHT_LEAD_MS - 34  # lit just before it is heard
    ramp = [plan[i][2] for i in range(first, first + 8)]
    steps = [b - a for a, b in zip(ramp, ramp[1:])]
    assert ramp[0] < 1 / (round(HIGHLIGHT_FADE_MS * 30 / 1000) + 1)  # slower than a straight line at the start
    assert max(steps) > 1.4 * steps[0] and ramp[-1] == 1.0  # speeds up in the middle, settles at 1
    assert HIGHLIGHT_FADE_MS >= 200


def test_translation_sits_well_below_the_arabic(app):
    v = verse(translation="Say, He is Allah, [who is] One.")
    r = renderer(RenderOptions(THEMES["Classic"], translation=True), v)
    assert r.gap >= 0.045 * r.short


def _bursts(starts_ms, length_s):
    """Envelope that is silent except for 300 ms of speech at each start (timing.ENV_RATE frames per second)."""
    from quran_video.core.timing import ENV_RATE
    env = [0.0] * (length_s * ENV_RATE)
    for a in starts_ms:
        i = a * ENV_RATE // 1000
        env[i:i + 15] = [1000.0] * 15
    return env


def test_timings_for_a_recut_audio_file_are_shifted_back():
    from quran_video.api.models import VerseTiming
    from quran_video.core.timing import audio_offset, shifted
    # Words every 1.3 s from 8 s, but the audio had its 7 s intro cut (QF: Dussary, surah 35)
    starts = [8000 + 1300 * k + (k % 3) * 170 for k in range(120)]
    t = [VerseTiming(f"35:{v + 1}", starts[v * 10], starts[v * 10 + 9] + 900,
                     tuple((k + 1, starts[v * 10 + k], starts[v * 10 + k] + 900) for k in range(10))) for v in range(12)]
    env = _bursts([a - 7000 for a in starts], 170)
    ms = audio_offset(t, env)
    assert abs(ms + 7000) <= 50
    assert shifted(t, ms)[0].segments[0][1] == starts[0] + ms
    assert audio_offset(t, [0.0] * len(env)) is None  # silence: no clear shift


def test_timings_that_fit_the_audio_are_left_alone(monkeypatch, tmp_path):
    from quran_video.api.models import VerseTiming
    from quran_video.core import export
    t = [VerseTiming("1:1", 0, 5000, ())]
    monkeypatch.setattr(export, "media_seconds", lambda p: 5.2)
    monkeypatch.setattr(export, "envelope", lambda p: pytest.fail("decoded although the timings fit"))
    assert export.fit_to_audio(t, tmp_path / "a.mp3", "x") is t
    monkeypatch.setattr(export, "media_seconds", lambda p: 3.0)  # timings overrun, and the audio has no clear shift
    monkeypatch.setattr(export, "envelope", lambda p: [0.0] * 150)
    with pytest.raises(export.DataError, match="doesn't match the audio"):
        export.fit_to_audio(t, tmp_path / "a.mp3", "x")
