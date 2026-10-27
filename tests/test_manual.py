"""Manual mode: batches picked by hand, the user's own recording, times set while it plays. Offline."""

import json
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest
from PySide6.QtGui import QColor

from quran_video.api.models import Chapter, Verse, Word
from quran_video.config.fonts import FONTS
from quran_video.config.themes import THEMES, remove_custom
from quran_video.config.translations import DEFAULT_TRANSLATION
from quran_video.core.ffmpeg import Layer, build_manual_cmd, ffmpeg_exe, has_audio, media_seconds
from quran_video.core.layout import wrap
from quran_video.core.manual import (END, LINE_BASMALA, LINE_EMPTY, LINE_SURAH, LINE_WORDS, START, TRANS_TRACK,
                                     Batch, ManualJob, TokenRange, TokenRef, TransBatch, WordRef, background_layers,
                                     check, compile_scenes, fit_pieces, from_json, label, limits, mark,
                                     mushaf_page, out_of_order, set_time, tap, to_json, trans_text, windows,
                                     word_times, words_of)
from quran_video.core.manual_export import manual_credits, prepare_manual
from quran_video.core.render import HIGHLIGHT_KEEP, RenderOptions, TextRenderer
from quran_video.core.timing import ALL, Clip, DataError, State, state_at

# A small mushaf: Al-Masad on page 603 (its name and Basmala on lines 1-2, a verse per line from line 3), Al-Ikhlas
# on page 604 with its name and Basmala at the foot of page 603. Words have 1 to 4 letters, so their weights differ.
CHAPTERS = [Chapter(1, "الفاتحة", "Al-Fatihah", 7, False, (1, 1)),
            Chapter(111, "المسد", "Al-Masad", 5, True, (603, 603)),
            Chapter(112, "الإخلاص", "Al-Ikhlas", 4, True, (604, 604))]
LETTERS = ["ب", "بت", "بتث", "بتثج"]


def _verse(ch: int, n: int, page: int, line: int) -> Verse:
    words = tuple(Word(i + 1, LETTERS[i] + "ٌ", False, page, line) for i in range(4))
    end = Word(5, "٠١٢٣٤٥٦٧٨٩"[n], True, page, line)
    return Verse(f"{ch}:{n}", n, (*words, end), " ".join(f"t{ch}-{n}{c}" for c in "abcde") + ".")


VERSES = {1: [Verse("1:1", 1, tuple(Word(i + 1, w, False, 1, 2) for i, w in enumerate(["بِسۡمِ", "ٱللَّهِ"])), "")],
          111: [_verse(111, n, 603, n + 2) for n in range(1, 6)],
          112: [_verse(112, n, 604, n) for n in range(1, 5)]}


def verses_of(chapter: int) -> list[Verse]:
    return VERSES.get(chapter, [])


def job(**kw) -> ManualJob:
    batches = kw.pop("batches", [Batch(WordRef(112, 1, 1), WordRef(112, 1, 4), 1000, 2000),
                                 Batch(WordRef(111, 1, 1), WordRef(111, 1, 2), 3000)])
    return ManualJob(Path("a.mp3"), batches, "9:16", Path("."), **kw)


# ---- picking words
def test_a_batch_keeps_every_word_and_the_sign_of_each_verse_that_ends_inside_it():
    cells = words_of(WordRef(111, 4, 3), WordRef(111, 5, 2), verses_of)
    assert [(str(c.ref), c.text, c.sign) for c in cells] == [
        ("111:4:3", "بتثٌ", False), ("111:4:4", "بتثجٌ", False), ("111:4:4", "٤", True),
        ("111:5:1", "بٌ", False), ("111:5:2", "بتٌ", False)]  # 111:5 isn't finished: no sign
    assert words_of(WordRef(111, 5, 2), WordRef(111, 4, 3), verses_of) == cells  # picked backwards
    across = words_of(WordRef(111, 5, 4), WordRef(112, 1, 1), verses_of)
    assert [(str(c.ref), c.sign) for c in across] == [("111:5:4", False), ("111:5:4", True), ("112:1:1", False)]
    assert label(WordRef(2, 255, 3), WordRef(2, 256, 5)) == "2:255:3-256:5"
    assert label(WordRef(2, 255, 3), WordRef(2, 255, 5)) == "2:255:3-5"


def test_tapped_word_times_are_kept_and_the_rest_share_the_time_by_their_letters():
    assert word_times([1, 1, 2], [], 0, 400) == [0, 100, 200]
    assert word_times([1, 1, 2], [None, 300], 0, 400) == [0, 300, 333]
    assert word_times([1, 1, 2], [50, 20, 999], 0, 400) == [50, 137, 225]  # a tap out of order or after the end
    taps, nxt = tap((), 3, 0, 100)
    taps, nxt = tap(taps, 3, nxt, 200)
    assert (taps, nxt) == ((100, 200, None), 2)
    assert tap(taps, 3, 0, 250) == ((250, None, None), 1)  # tapping again from the start clears later taps


# ---- times
def test_marks_made_while_playing_keep_the_batches_in_order():
    slots = [(None, None)] * 3
    for k, which, t in [(0, START, 1000), (1, START, 3000), (1, END, 4000), (2, START, 5000)]:
        slots = mark(slots, k, which, t, 0, 9000)
    assert slots == [(1000, None), (3000, 4000), (5000, None)]
    assert mark(slots, 0, START, 4500, 0, 9000) == [(4500, None), (None, None), (5000, None)]  # a second pass
    assert mark(slots, 1, END, 2500, 0, 9000)[1] == (3000, 3000)  # never before its own start
    assert windows(slots, 9000) == [(1000, 3000), (3000, 4000), (5000, 9000)]  # until the next one starts
    assert windows([(None, None), (2000, None)], 9000) == [None, (2000, 9000)]
    assert out_of_order(slots) is None and out_of_order([(1000, 5000), (3000, None)]) == 1


def test_a_dragged_time_stays_between_its_neighbours():
    slots = [(1000, None), (3000, 4000), (5000, None)]
    assert limits(slots, 1, START, 0, 9000) == (1000, 4000)
    assert set_time(slots, 1, START, 500, 0, 9000)[1] == (1000, 4000)
    assert set_time(slots, 1, START, 4800, 0, 9000)[1] == (4000, 4000)
    assert set_time(slots, 1, END, None, 0, 9000)[1] == (3000, None)


# ---- what is on screen
def test_scenes_cover_the_whole_video_with_pauses_where_no_batch_is_shown():
    j = job(trim_start_ms=500, trim_end_ms=5500)
    scenes = compile_scenes(j, verses_of, lambda t: True, 10000)
    assert [(s.start, s.end, s.batch) for s in scenes] == [(0, 500, None), (500, 1500, 0), (1500, 2500, None),
                                                          (2500, 5000, 1)]
    assert [s.chapter for s in scenes] == [112, 112, 112, 111]  # a pause keeps the name around it
    assert [s.pos for s in scenes[1].segs] == [1, 2, 3, 4] and scenes[1].cells[-1].sign
    assert [s.start for s in scenes[1].segs] == [500, 600, 800, 1100] and scenes[1].segs[-1].end == 1500  # 1:2:3:4
    clips = [Clip(i, s.start, s.end, s.segs) for i, s in enumerate(scenes)]
    assert state_at(clips, 250).verse == 0 and state_at(clips, 1600) == State(2, ALL, ALL)  # blank, not batch 1


def test_attached_translations_and_a_translation_track_with_the_same_times_look_the_same():
    rng = TokenRange(TokenRef(112, 1, 0), TokenRef(112, 1, 2))
    attached = job(translation=DEFAULT_TRANSLATION)
    attached.batches[0] = replace(attached.batches[0], translation=rng)
    track = job(translation=DEFAULT_TRANSLATION, trans_mode=TRANS_TRACK, trans_batches=[TransBatch(rng, 1000, 2000)])
    a, t = (compile_scenes(x, verses_of, lambda s: True, 9000) for x in (attached, track))
    assert a == t and a[1].translation == "t112-1a t112-1b t112-1c"
    assert compile_scenes(job(), verses_of, lambda s: True, 9000)[1].translation == ""  # no translation chosen


def test_translation_words_are_joined_exactly_as_written_across_verses():
    rng = TokenRange(TokenRef(112, 2, 1), TokenRef(112, 1, 3))  # picked backwards
    assert trans_text(rng, verses_of) == "t112-1d t112-1e. t112-2a t112-2b"


def test_a_translation_too_long_for_the_screen_is_shown_in_pieces_in_order():
    text = "one two three four five six seven, eight nine ten"
    pieces = fit_pieces(text, 0, 1000, lambda t: len(t) <= 20)
    assert " ".join(p for p, _, _ in pieces) == text and all(len(p) <= 20 for p, _, _ in pieces)
    assert pieces[0][1] == 0 and pieces[-1][2] == 1000
    assert all(a[2] == b[1] for a, b in zip(pieces, pieces[1:]))


def test_a_batch_crossing_into_the_next_surah_changes_the_name_at_its_first_word():
    b = Batch(WordRef(111, 5, 3), WordRef(112, 1, 2), 1000, 3000, word_ms=(1000, 1500, 2000, 2500))
    scenes = compile_scenes(job(batches=[b]), verses_of, lambda t: True, 3000)
    shown = [s for s in scenes if s.cells]
    assert [(s.start, s.end, s.chapter) for s in shown] == [(1000, 2000, 111), (2000, 3000, 112)]
    assert [c.sign for c in shown[0].cells] == [False, False, True] and [s.pos for s in shown[1].segs] == [1, 2]


def test_each_batch_background_shows_until_the_next_batch_and_repeats_join_up():
    bg = Path("sea.mp4")
    batches = [Batch(WordRef(112, 1, 1), WordRef(112, 1, 1), 1000, 2000, background=bg),
               Batch(WordRef(112, 2, 1), WordRef(112, 2, 1), 2500, 3000, background=bg),
               Batch(WordRef(112, 3, 1), WordRef(112, 3, 1), 4000, None),
               Batch(WordRef(112, 4, 1), WordRef(112, 4, 1), 5000, None, background=Path("sky.png"))]
    assert background_layers(job(batches=batches, trim_start_ms=500), 8000) == [
        (bg, 500, 3500), (Path("sky.png"), 4500, 7500)]


def test_a_job_that_cannot_be_made_says_why(tmp_path):
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"x")
    ok = replace(job(), audio=audio)
    check(ok, 10.0, True)
    with pytest.raises(DataError, match="no sound"):
        check(ok, 10.0, False)
    with pytest.raises(DataError) as e:
        check(replace(ok, batches=[Batch(WordRef(112, 1, 1), WordRef(112, 1, 1))]), 10.0, True)
    assert e.value.key == "Set the start time of batch {n}." and e.value.params == {"n": 1}
    with pytest.raises(DataError, match="out of order at batch 2"):
        check(replace(ok, batches=[Batch(WordRef(112, 1, 1), WordRef(112, 1, 1), 2000, 5000),
                                   Batch(WordRef(112, 1, 1), WordRef(112, 1, 1), 3000)]), 10.0, True)
    many = [Batch(WordRef(112, 1, 1), WordRef(112, 1, 1), n * 1000, background=Path(f"{n}.mp4")) for n in range(7)]
    with pytest.raises(DataError, match="at most 6"):
        check(replace(ok, batches=many), 10.0, True)


# ---- the mushaf page
def test_a_mushaf_page_puts_the_surah_names_and_basmala_on_the_empty_lines():
    page = mushaf_page(603, CHAPTERS, verses_of)
    kinds = [(line.number, line.kind, line.chapter) for line in page.lines if line.kind != LINE_EMPTY]
    assert kinds == [(1, LINE_SURAH, 111), (2, LINE_BASMALA, 111), *((n, LINE_WORDS, 0) for n in range(3, 8)),
                     (8, LINE_SURAH, 112), (9, LINE_BASMALA, 112)]  # Al-Ikhlas starts on the next page
    assert len(page.lines) == 15 and [c.text for c in page.lines[1].cells] == ["بِسۡمِ", "ٱللَّهِ"]
    third = page.lines[2].cells
    assert [str(c.ref) for c in third] == ["111:1:1", "111:1:2", "111:1:3", "111:1:4", "111:1:4"] and third[-1].sign
    assert [line.kind for line in mushaf_page(604, CHAPTERS, verses_of).lines[:4]] == [LINE_WORDS] * 4


# ---- project files
def test_a_project_file_keeps_references_and_times_but_never_the_text(tmp_path):
    (tmp_path / "rec.mp3").write_bytes(b"x")
    theme = "Test Sea"
    from quran_video.config.themes import add_custom, make_custom
    add_custom(make_custom(theme, "#123456", "#FFCC00"))
    rng = TokenRange(TokenRef(112, 1, 0), TokenRef(112, 1, 2))
    j = replace(job(translation=DEFAULT_TRANSLATION, theme=theme, highlight="word", surah_name=True,
                    trans_mode=TRANS_TRACK, trans_batches=[TransBatch(rng, 1000, 2000)]),
                audio=tmp_path / "rec.mp3", out_dir=tmp_path)
    j.batches[0] = replace(j.batches[0], word_ms=(1000, None, 1500, None), background=tmp_path / "rec.mp3")
    text = json.dumps(to_json(j, ["9:16", "1:1"]), ensure_ascii=False)
    assert not any("؀" <= c <= "ۿ" for c in text) and "t112" not in text  # no Arabic, no translation
    remove_custom(theme)
    moved = tmp_path / "moved"
    moved.mkdir()
    (tmp_path / "rec.mp3").rename(moved / "rec.mp3")
    back, formats = from_json(json.loads(text), moved)  # the recording moved next to the project
    try:
        assert formats == ["9:16", "1:1"] and theme in THEMES and back.audio == moved / "rec.mp3"
        assert back == replace(j, audio=moved / "rec.mp3",
                               batches=[replace(j.batches[0], background=moved / "rec.mp3"), j.batches[1]])
    finally:
        remove_custom(theme)
    with pytest.raises(DataError, match="Can't open"):
        from_json({"kind": "auto"}, tmp_path)


def test_credits_name_the_reciter_only_when_given_and_always_quran_foundation():
    rng = TokenRange(TokenRef(112, 1, 0), TokenRef(112, 1, 2))
    assert manual_credits(job()) == ("Verses: 112:1, 111:1\n"
                                     "Quran data provided by Quran.Foundation (https://quran.foundation)\n")
    j = job(reciter_name=" Me ", translation=DEFAULT_TRANSLATION, trans_mode=TRANS_TRACK,
            trans_batches=[TransBatch(rng, 0, 1)])
    assert manual_credits(j).splitlines()[:2] == ["Recitation: Me", f"Translation: {DEFAULT_TRANSLATION}"]


# ---- drawing
def test_wrapping_keeps_a_verse_end_sign_inside_the_text_with_the_word_before_it():
    assert wrap([40, 40, 10, 40], 5, 90, glue=frozenset({2})) == [[0], [1, 2], [3]]
    assert wrap([40, 40, 10, 40], 5, 90) == [[0, 1], [2, 3]]  # without glue the sign would start a line


def test_a_verse_end_sign_inside_a_batch_is_never_highlighted(app):
    words = (Word(1, "بِسۡمِ", False), Word(2, "١", False), Word(3, "ٱللَّهِ", False))
    opts = RenderOptions(THEMES["Classic"], highlight=HIGHLIGHT_KEEP, split="verse")
    r = TextRenderer(540, 960, [Verse("m", 0, words)], FONTS["QPC Hafs"], opts, [frozenset({1})])
    before, after = (r.render(State(0, 1, reveal)) for reveal in (1, 2))  # reveal 2 would light the sign
    assert before == after


def test_an_empty_screen_draws_only_its_surah_name(app):
    opts = RenderOptions(THEMES["Classic"], chapter=112, split="verse")
    blank = [Verse("m0", 0, ()), Verse("m1", 0, ())]
    r = TextRenderer(540, 960, blank, FONTS["QPC Hafs"], opts, chapters=[112, 0])
    named, empty = r.render(State(0, ALL, ALL)), r.render(State(1, ALL, ALL))
    assert empty.pixelColor(270, 40).alpha() == 0 and empty == TextRenderer(
        540, 960, [Verse("x", 0, ())], FONTS["QPC Hafs"], RenderOptions(THEMES["Classic"])).render(State(0, ALL, ALL))
    assert named != empty


def test_a_verse_too_tall_for_the_screen_is_never_cut_short(app):
    words = tuple(Word(i + 1, "بتثج", False) for i in range(400))
    r = TextRenderer(300, 300, [Verse("m", 0, words)], FONTS["QPC Hafs"], RenderOptions(THEMES["Classic"],
                                                                                         split="verse"))
    pages = r.pages(0)
    assert len(pages) > 1 and set().union(*(p.words for p in pages)) == set(range(400))


def test_manual_scenes_render_through_the_auto_mode_renderer(app):
    rng = TokenRange(TokenRef(112, 1, 0), TokenRef(112, 1, 4))
    j = job(translation=DEFAULT_TRANSLATION, surah_name=True, highlight="word")
    j.batches[0] = replace(j.batches[0], translation=rng)
    prep, scenes = prepare_manual(j, verses_of, 6000, size=(270, 480))
    assert [c.start for c in prep.clips] == [s.start for s in scenes] and prep.clips[0].start == 0
    assert prep.audio_end_ms == 6000 and prep.warning is not None  # highlight on, words not tapped
    for c in prep.clips:
        img = prep.renderer.render(state_at(prep.clips, (c.start + c.end) / 2))
        assert img.size().width() == 270


# ---- ffmpeg
def test_has_audio_and_per_batch_backgrounds_show_at_their_own_times(tmp_path):
    exe = ffmpeg_exe()

    def make(*args):
        subprocess.run([exe, "-y", "-loglevel", "error", *args], check=True)
    make("-f", "lavfi", "-i", "color=c=red:s=64x64", "-frames:v", "1", str(tmp_path / "red.png"))
    make("-f", "lavfi", "-i", "color=c=blue:s=32x32:r=10:d=1", "-c:v", "libx264", "-pix_fmt", "yuv420p",
         str(tmp_path / "blue.mp4"))
    make("-f", "lavfi", "-i", "sine=f=440:d=6", str(tmp_path / "tone.wav"))
    assert has_audio(tmp_path / "tone.wav") and not has_audio(tmp_path / "red.png")
    out = tmp_path / "out.mp4"
    cmd = build_manual_cmd(exe, 64, 64, 10, tmp_path / "tone.wav", 1000, 4000, out, None, "#00FF00",
                           [Layer(tmp_path / "red.png", 1000, 2000), Layer(tmp_path / "blue.mp4", 2500, 3500)])
    subprocess.run(cmd, input=b"\0" * (64 * 64 * 4) * 40, check=True, capture_output=True)  # clear text frames
    assert media_seconds(out) == pytest.approx(4.0, abs=0.05)

    def colour(t):
        px = subprocess.run([exe, "-v", "error", "-ss", str(t), "-i", str(out), "-frames:v", "1", "-vf",
                             "crop=2:2:32:32", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
        return QColor(*px[:3]).name()
    assert [colour(t) for t in (0.5, 1.5, 2.2, 3.0, 3.8)] == ["#00fe00", "#fc0000", "#00fe00", "#0000fe", "#00fe00"]
