"""Manual mode: the user's own recording, words picked on the mushaf, and times set by hand. No drawing and no
network here: core.manual_export turns a ManualJob into a video with auto mode's renderer and ffmpeg.

A batch is one stretch of the Quran, from a first word to a last word in mushaf order. Batches play in list order
and never overlap, but each can come from anywhere (a reciter going back to repeat is normal). A translation
batch is a stretch of one translation, cut at its words. Either is shown exactly as the API returns it: the
Quran Foundation terms allow snippets only when they keep their context, so nothing inside a batch is ever left
out, moved or changed. Project files keep only references and times, never the text (nothing from the API may
be kept longer than a week)."""

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

from ..api.models import Chapter, Verse
from ..config.fonts import DEFAULT_FONT, FONTS
from ..config.presets import FORMATS
from ..config.quality import DEFAULT_QUALITY, QUALITIES
from ..config.themes import DEFAULT_THEME, THEMES, add_custom, is_builtin, make_custom
from ..config.translations import TRANSLATIONS
from .ffmpeg import is_video
from .render import DEFAULT_TEXT_WIDTH, HIGHLIGHT_NONE, REVEAL_OFF
from .timing import DataError, Seg
from .translation import is_spaced, letter_weight, split_translation, tokens

PROJECT_VERSION = 1
PROJECT_SUFFIX = ".qvc"
TRANS_ATTACHED, TRANS_TRACK = "attached", "track"  # translations go with the batches, or have their own times
START, END = "start", "end"
MAX_BG_VIDEOS = 6  # ffmpeg decodes every background video at once: each costs 100-150 MB
PAGES = 604  # pages of the Madani mushaf

VersesOf = Callable[[int], list[Verse]]  # every verse of a surah, words and translation (QuranClient.verses)


@dataclass(frozen=True, order=True)
class WordRef:
    """A word of the Quran: surah, verse, and its place among the verse's words (from 1; the sign not counted)."""
    chapter: int
    verse: int
    word: int

    def __str__(self) -> str:
        return f"{self.chapter}:{self.verse}:{self.word}"

    @classmethod
    def parse(cls, text: str) -> "WordRef":
        return cls(*map(int, text.split(":")))


@dataclass(frozen=True, order=True)
class TokenRef:
    """A word of a verse's translation (from 0), as translation.tokens cuts it."""
    chapter: int
    verse: int
    token: int

    def __str__(self) -> str:
        return f"{self.chapter}:{self.verse}:{self.token}"

    @classmethod
    def parse(cls, text: str) -> "TokenRef":
        return cls(*map(int, text.split(":")))


@dataclass(frozen=True)
class TokenRange:
    first: TokenRef
    last: TokenRef


Slot = tuple[int | None, int | None]  # start and end, ms in the audio file; None: not set


@dataclass
class Batch:
    first: WordRef
    last: WordRef
    start_ms: int | None = None  # ms in the audio file, so trimming it never moves them
    end_ms: int | None = None  # None: until the next batch starts
    word_ms: tuple[int | None, ...] = ()  # tapped start of each word, for highlighting; None: shared out
    translation: TokenRange | None = None  # its translation, when translations go with the batches
    background: Path | None = None  # a picture or video for this batch alone

    @property
    def slot(self) -> Slot:
        return self.start_ms, self.end_ms


@dataclass
class TransBatch:
    range: TokenRange
    start_ms: int | None = None
    end_ms: int | None = None

    @property
    def slot(self) -> Slot:
        return self.start_ms, self.end_ms


@dataclass
class ManualJob:
    audio: Path | None  # the recitation: an audio file, or a video whose sound is used
    batches: list[Batch]
    fmt: str
    out_dir: Path
    trans_mode: str = TRANS_ATTACHED
    trans_batches: list[TransBatch] = field(default_factory=list)  # TRANS_TRACK only
    translation: str = "None"  # key of config.translations.TRANSLATIONS
    reciter_name: str = ""  # for the credits; left out when empty
    name: str = ""  # names the video file
    trim_start_ms: int = 0  # the part of the recording the video uses
    trim_end_ms: int | None = None  # None: to its end
    fps: int = 30
    font: str = DEFAULT_FONT
    theme: str = DEFAULT_THEME
    highlight: str = HIGHLIGHT_NONE  # words are only lit when the user asks for it (and taps them)
    highlight_fade: bool = True
    reveal: str = REVEAL_OFF
    line_spacing: float = 0.8
    surah_name: bool = False
    name_scale: float = 1.0
    overlay: float = 0.0  # dims the pictures, never the theme colour
    quality: str = DEFAULT_QUALITY
    text_width: float = DEFAULT_TEXT_WIDTH
    translation_width: float = DEFAULT_TEXT_WIDTH
    background: Path | None = None  # behind every batch that has none of its own
    bg_end: str = "loop"

    @property
    def filename(self) -> str:
        stem = self.name or (self.audio.stem if self.audio else "")
        slug = re.sub(r"[^\w]+", "-", stem.lower()).strip("-") or "recitation"
        return f"{slug}_manual_{self.fmt.replace(':', 'x')}.mp4"

    @property
    def uses_translation(self) -> bool:
        if TRANSLATIONS.get(self.translation) is None:
            return False
        if self.trans_mode == TRANS_TRACK:
            return bool(self.trans_batches)
        return any(b.translation for b in self.batches)


# Times. Starts and ends always run s1 <= e1 <= s2 <= e2 ... (unset ones are skipped).

def _flat(slots: list[Slot]) -> list[int | None]:
    return [v for slot in slots for v in slot]


def _slots(seq: list[int | None]) -> list[Slot]:
    return [(seq[i], seq[i + 1]) for i in range(0, len(seq), 2)]


def limits(slots: list[Slot], k: int, which: str, lo: int, hi: int) -> tuple[int, int]:
    """How early and how late batch k's start or end can go without passing a time before or after it."""
    seq, i = _flat(slots), 2 * k + (which == END)
    return (max([lo, *(v for v in seq[:i] if v is not None)]),
            min([hi, *(v for v in seq[i + 1:] if v is not None)]))


def set_time(slots: list[Slot], k: int, which: str, t: int | None, lo: int, hi: int) -> list[Slot]:
    """Move (or with None, clear) a start or end, kept between its neighbours. For dragging and typing."""
    seq, i = _flat(slots), 2 * k + (which == END)
    if t is not None:
        a, b = limits(slots, k, which, lo, hi)
        t = min(max(t, a), b)
    seq[i] = t
    return _slots(seq)


def mark(slots: list[Slot], k: int, which: str, t: int, lo: int, hi: int) -> list[Slot]:
    """Put a start or end at t while the recording plays. It never goes before an earlier start; later times
    that are now earlier than it (set on an earlier pass) are cleared, and so are earlier ends after it."""
    seq, i = _flat(slots), 2 * k + (which == END)
    t = min(max([lo, t, *(v for n, v in enumerate(seq[:i]) if v is not None and n % 2 == 0)]), hi)
    seq = [None if v is not None and (n < i and v > t or n > i and v < t) else v for n, v in enumerate(seq)]
    seq[i] = t
    return _slots(seq)


def windows(slots: list[Slot], file_end: int) -> list[tuple[int, int] | None]:
    """When each batch is on screen (ms in the file): from its start until its end, or until the next batch
    starts. None for a batch with no start yet, or no time on screen."""
    out: list[tuple[int, int] | None] = []
    for k, (s, e) in enumerate(slots):
        if s is None:
            out.append(None)
            continue
        nxt = next((x for x, _ in slots[k + 1:] if x is not None), file_end)
        end = min(e if e is not None else nxt, nxt, file_end)
        out.append((s, end) if end > s else None)
    return out


def out_of_order(slots: list[Slot]) -> int | None:
    """The first batch (from 0) whose times run backwards, if any."""
    last = None
    for i, v in enumerate(_flat(slots)):
        if v is not None:
            if last is not None and v < last:
                return i // 2
            last = v
    return None


def tap(word_ms: tuple[int | None, ...], n_words: int, i: int, t: int) -> tuple[tuple[int | None, ...], int]:
    """Word i starts at t (the user tapped it while it was recited). Later taps that are now earlier are
    cleared. Returns the new taps and the next word to tap."""
    taps = list(word_ms[:n_words]) + [None] * (n_words - len(word_ms))
    taps = [None if j > i and v is not None and v <= t else v for j, v in enumerate(taps)]
    taps[i] = t
    return tuple(taps), min(i + 1, n_words - 1)


def word_times(weights: list[int], known: Iterable[int | None], start: int, end: int) -> list[int]:
    """When each word starts. Tapped times are kept when they fall inside the batch and after the taps before
    them; the words in between share the time left by their letter weight. Without any taps this still gives
    every word its share, so a long batch turns its pages."""
    n = len(weights)
    known = list(known)[:n]
    known += [None] * (n - len(known))
    anchors = [(-1, start)]
    for i, t in enumerate(known):
        if t is not None and start <= t < end and (t > anchors[-1][1] or anchors[-1][0] < 0):
            anchors.append((i, t))
    anchors.append((n, end))
    times = [start] * n
    for (ia, ta), (ib, tb) in zip(anchors, anchors[1:]):
        run = range(max(ia, 0), ib)
        total = sum(weights[j] for j in run) or 1
        acc = 0
        for j in run:
            times[j] = ta + (tb - ta) * acc // total
            acc += weights[j]
    return times


# Words.

@dataclass(frozen=True)
class Cell:
    """One word on screen, its text exactly as the API returns it. A verse-end sign holds the bare verse number
    (the renderer draws the sign around it) and points at the verse's last word."""
    ref: WordRef | None  # None: not part of the selectable text (the Basmala line of a mushaf page)
    text: str
    sign: bool = False


def normalise(a, b):
    """A range picked backwards (last word first) put the right way round."""
    return (a, b) if a <= b else (b, a)


def words_of(first: WordRef, last: WordRef, verses_of: VersesOf) -> list[Cell]:
    """Every word from `first` to `last` in mushaf order, with the sign of every verse that ends inside."""
    first, last = normalise(first, last)
    out, ch, v = [], first.chapter, first.verse
    while (ch, v) <= (last.chapter, last.verse):
        verses = verses_of(ch)
        if v > len(verses):
            ch, v = ch + 1, 1
            continue
        verse = verses[v - 1]
        words = verse.text_words
        a = first.word if (ch, v) == (first.chapter, first.verse) else 1
        b = last.word if (ch, v) == (last.chapter, last.verse) else len(words)
        a, b = max(a, 1), min(b, len(words))
        out += [Cell(WordRef(ch, v, i), words[i - 1].text) for i in range(a, b + 1)]
        if b == len(words) and verse.end_text:
            out.append(Cell(WordRef(ch, v, len(words)), verse.end_text, sign=True))
        v += 1
    return out


def label(first, last) -> str:
    """'2:255:3-256:5' style reference of a range of words (or translation words)."""
    first, last = normalise(first, last)
    if first.chapter != last.chapter:
        return f"{first}-{last}"
    if first.verse != last.verse:
        return f"{first}-{str(last).split(':', 1)[1]}"
    return f"{first}" if first == last else f"{first}-{str(last).rsplit(':', 1)[1]}"


def verse_list(batches: Iterable[Batch]) -> str:
    """'2:255-257, 3:1' for the credits: the verses the batches come from, in the order they are shown."""
    out: list[str] = []
    for b in batches:
        first, last = normalise(b.first, b.last)
        if first.chapter != last.chapter:
            text = f"{first.chapter}:{first.verse}-{last.chapter}:{last.verse}"
        elif first.verse != last.verse:
            text = f"{first.chapter}:{first.verse}-{last.verse}"
        else:
            text = f"{first.chapter}:{first.verse}"
        if text not in out:
            out.append(text)
    return ", ".join(out)


# Translations.

def spaced_translation(verses_of: VersesOf, chapter: int) -> bool:
    """Does this translation separate its words with spaces? Decided once per surah, so that a one-word verse
    of a spaced language is not cut into letters."""
    return is_spaced([v.translation for v in verses_of(chapter)])


def verse_tokens(verse: Verse, spaced: bool) -> tuple[list[str], str]:
    return tokens(verse.translation, spaced) if verse.translation else ([], " " if spaced else "")


def trans_text(rng: TokenRange, verses_of: VersesOf) -> str:
    """The translation from the first to the last chosen word, joined as it was written."""
    first, last = normalise(rng.first, rng.last)
    spaced = spaced_translation(verses_of, first.chapter)
    parts, sep, ch, v = [], " " if spaced else "", first.chapter, first.verse
    while (ch, v) <= (last.chapter, last.verse):
        verses = verses_of(ch)
        if v > len(verses):
            ch, v = ch + 1, 1
            continue
        toks, sep = verse_tokens(verses[v - 1], spaced)
        a = first.token if (ch, v) == (first.chapter, first.verse) else 0
        b = last.token if (ch, v) == (last.chapter, last.verse) else len(toks) - 1
        parts += toks[max(a, 0):b + 1]
        v += 1
    return sep.join(parts)


def translation_spans(job: ManualJob, file_end: int) -> list[tuple[TokenRange, int, int]]:
    """Each translation range and when it is on screen (ms in the file), whichever way they are timed."""
    if TRANSLATIONS.get(job.translation) is None:
        return []
    if job.trans_mode == TRANS_TRACK:
        wins = windows([t.slot for t in job.trans_batches], file_end)
        return [(t.range, *w) for t, w in zip(job.trans_batches, wins) if w]
    wins = windows([b.slot for b in job.batches], file_end)
    return [(b.translation, *w) for b, w in zip(job.batches, wins) if w and b.translation]


def fit_pieces(text: str, start: int, end: int, fits: Callable[[str], bool]) -> list[tuple[str, int, int]]:
    """A translation too long for its box is shown in pieces, one after another, the time shared by length."""
    if not text or fits(text):
        return [(text, start, end)]
    pieces = [text]
    for n in range(2, 40):
        pieces = [p for p in split_translation(text, [1] * n) if p]
        if all(fits(p) for p in pieces):
            break
    weights = [len(p) for p in pieces]
    total, acc, out = sum(weights), 0, []
    for p, w in zip(pieces, weights):
        a = start + (end - start) * acc // total
        acc += w
        out.append((p, a, start + (end - start) * acc // total))
    return out


# What is on screen, and when.

@dataclass(frozen=True)
class Scene:
    """One stretch of the video with the same text on screen. Times are ms on the video's own timeline."""
    start: int
    end: int
    cells: tuple[Cell, ...]  # the Arabic on screen; none: a pause, or a translation alone
    translation: str
    chapter: int  # the surah whose name goes on top (0: none)
    segs: tuple[Seg, ...]  # when each word is recited; positions count the cells, signs included
    batch: int | None  # the batch (from 0) the Arabic comes from


@dataclass(frozen=True)
class _Unit:
    start: int
    end: int
    cells: tuple[Cell, ...]
    chapter: int
    segs: tuple[Seg, ...]
    batch: int


def file_end(job: ManualJob, audio_ms: int) -> int:
    """Where the video ends in the recording (ms)."""
    end = audio_ms if job.trim_end_ms is None else min(job.trim_end_ms, audio_ms)
    return max(end, job.trim_start_ms)


def _units(k: int, batch: Batch, start: int, end: int, verses_of: VersesOf) -> list[_Unit]:
    """A batch on the file's timeline, cut where it crosses into the next surah: one surah name per screen."""
    cells = words_of(batch.first, batch.last, verses_of)
    text = [i for i, c in enumerate(cells) if not c.sign]
    if not text:
        return []
    times = word_times([letter_weight(cells[i].text) for i in text], batch.word_ms, start, end)
    word_of = {i: n for n, i in enumerate(text)}
    groups, out = [], []
    for i, c in enumerate(cells):
        if groups and cells[groups[-1][0]].ref.chapter == c.ref.chapter:
            groups[-1].append(i)
        else:
            groups.append([i])
    for g, group in enumerate(groups):
        words = [word_of[i] for i in group if i in word_of]
        a = start if g == 0 else times[words[0]]
        z = times[word_of[next(i for i in groups[g + 1] if i in word_of)]] if g + 1 < len(groups) else end
        segs = tuple(Seg(i - group[0] + 1, times[word_of[i]],
                         times[word_of[i] + 1] if word_of[i] + 1 < len(times) else end)
                     for i in group if i in word_of)
        out.append(_Unit(a, z, tuple(cells[i] for i in group), cells[group[0]].ref.chapter, segs, k))
    return out


def compile_scenes(job: ManualJob, verses_of: VersesOf, fits: Callable[[str], bool],
                   audio_ms: int) -> list[Scene]:
    """The whole video as scenes from 0 to its end, with no holes: a pause is a scene with nothing in it.
    `fits(text)` tells whether a translation fits on screen; a longer one is shown in pieces."""
    off, end = job.trim_start_ms, file_end(job, audio_ms)
    total = end - off
    units = [u for k, (b, w) in enumerate(zip(job.batches, windows([b.slot for b in job.batches], end))) if w
             for u in _units(k, b, *w, verses_of)]
    pieces = [piece for rng, a, z in translation_spans(job, end)
              for piece in fit_pieces(trans_text(rng, verses_of), a, z, fits)]

    def clamp(t: int) -> int:
        return min(max(t - off, 0), total)

    units = [_Unit(clamp(u.start), clamp(u.end), u.cells, u.chapter,
                   tuple(Seg(s.pos, s.start - off, s.end - off) for s in u.segs), u.batch) for u in units]
    pieces = [(text, clamp(a), clamp(z)) for text, a, z in pieces]
    cuts = sorted({0, total, *(t for u in units for t in (u.start, u.end)), *(t for p in pieces for t in p[1:])})
    scenes: list[Scene] = []
    keys: list[tuple] = []
    for a, z in zip(cuts, cuts[1:]):
        unit = next((u for u in units if u.start <= a < u.end), None)
        piece = next((p for p in pieces if p[1] <= a < p[2]), None)
        key = (id(unit) if unit else None, id(piece) if piece else None)
        if keys and keys[-1] == key:
            scenes[-1] = Scene(scenes[-1].start, z, *[getattr(scenes[-1], f) for f in
                                                      ("cells", "translation", "chapter", "segs", "batch")])
            continue
        keys.append(key)
        scenes.append(Scene(a, z, unit.cells if unit else (), piece[0] if piece else "",
                            unit.chapter if unit else 0, unit.segs if unit else (), unit.batch if unit else None))
    if not scenes:  # a recording with no length: one empty scene keeps the frame loop simple
        scenes = [Scene(0, max(total, 1), (), "", 0, (), None)]
    # a pause keeps the surah name of the batch before it (or the first one after), so the name doesn't flash
    named = [s.chapter for s in scenes if s.chapter]
    last = named[0] if named else 0
    out = []
    for s in scenes:
        last = s.chapter or last
        out.append(s if s.chapter else Scene(s.start, s.end, s.cells, s.translation, last, s.segs, s.batch))
    return out


def background_layers(job: ManualJob, audio_ms: int) -> list[tuple[Path, int, int]]:
    """Each batch's own picture or video and when it shows (ms on the video): from the batch's start until the
    next batch starts, so a short pause doesn't flash the colour behind. Neighbours with the same file are one
    layer, so a video carries on instead of starting again."""
    off, end = job.trim_start_ms, file_end(job, audio_ms)
    slots = [b.slot for b in job.batches]
    layers: list[tuple[Path, int, int]] = []
    for k, (b, w) in enumerate(zip(job.batches, windows(slots, end))):
        if not w or b.background is None:
            continue
        nxt = next((s for s, _ in slots[k + 1:] if s is not None), end)
        a, z = max(w[0] - off, 0), min(nxt, end) - off
        if z <= a:
            continue
        if layers and layers[-1][0] == b.background and layers[-1][2] == a:
            layers[-1] = (b.background, layers[-1][1], z)
        else:
            layers.append((b.background, a, z))
    return layers


def check(job: ManualJob, audio_seconds: float | None, has_sound: bool) -> None:
    """Refuse a job that can't make a video, saying why (DataError: the window translates it)."""
    if job.audio is None:
        raise DataError("Choose an audio or video file.")
    if not job.audio.is_file():
        raise DataError("The audio file was not found.")
    if not has_sound or not audio_seconds:
        raise DataError("This file has no sound.")
    if not job.batches:
        raise DataError("Add at least one batch.")
    for n, b in enumerate(job.batches, 1):
        if b.start_ms is None:
            raise DataError("Set the start time of batch {n}.", n=n)
    k = out_of_order([b.slot for b in job.batches])
    if k is not None:
        raise DataError("The times are out of order at batch {n}.", n=k + 1)
    if job.trans_mode == TRANS_TRACK:
        k = out_of_order([t.slot for t in job.trans_batches])
        if k is not None:
            raise DataError("The times are out of order at translation {n}.", n=k + 1)
    videos = {p for p in [job.background, *(b.background for b in job.batches)] if is_video(p)}
    if len(videos) > MAX_BG_VIDEOS:
        raise DataError("Use at most {n} background videos.", n=MAX_BG_VIDEOS)


# The mushaf page on screen.

LINE_WORDS, LINE_SURAH, LINE_BASMALA, LINE_EMPTY = "words", "surah", "basmala", "empty"


@dataclass(frozen=True)
class MushafLine:
    number: int
    kind: str
    chapter: int = 0  # for a surah name or Basmala line
    cells: tuple[Cell, ...] = ()


@dataclass(frozen=True)
class MushafPage:
    number: int
    lines: tuple[MushafLine, ...]


def chapters_on(page: int, chapters: list[Chapter]) -> list[Chapter]:
    return [c for c in chapters if c.pages[0] <= page <= c.pages[1]]


def page_of(chapter: int, verse: int, verses_of: VersesOf) -> int:
    """The mushaf page a verse starts on (0 when unknown)."""
    verses = verses_of(chapter)
    if not 1 <= verse <= len(verses):
        return 0
    return next((w.page for w in verses[verse - 1].words if w.page), 0)


def first_page(chapter: int, chapters: list[Chapter]) -> int:
    return next((c.pages[0] for c in chapters if c.id == chapter and c.pages[0]), 1)


def mushaf_page(page: int, chapters: list[Chapter], verses_of: VersesOf) -> MushafPage:
    """One page of the Madani mushaf, line by line, from the page and line the API gives every word. The lines
    with no words before a surah's first verse hold its name and the Basmala."""
    on = chapters_on(page, chapters)
    by_line: dict[int, list[Cell]] = {}
    starts: dict[int, int] = {}  # surah -> line of its first word, for the surahs that start on this page
    for ch in on:
        for verse in verses_of(ch.id):
            n, k = len(verse.text_words), 0
            for w in verse.words:
                k += not w.is_end
                if w.page != page:
                    continue
                by_line.setdefault(w.line, []).append(Cell(WordRef(ch.id, verse.number, n if w.is_end else k),
                                                           w.text, w.is_end))
                if verse.number == 1 and k == 1 and not w.is_end:
                    starts.setdefault(ch.id, w.line)
    count = max(15, max(by_line, default=0))
    heads: dict[int, tuple[str, int]] = {}

    def basmala(ch: Chapter) -> bool:
        return ch.bismillah_pre and ch.id not in (1, 9)

    for ch in on:
        if ch.id in starts:
            line = starts[ch.id] - 1
            if basmala(ch) and line >= 1 and line not in by_line:
                heads[line] = (LINE_BASMALA, ch.id)
                line -= 1
            if line >= 1 and line not in by_line:
                heads[line] = (LINE_SURAH, ch.id)
    nxt = next((c for c in chapters if on and c.id == on[-1].id + 1), None)
    if nxt and nxt.pages[0] == page + 1 and by_line:  # its name sits at the foot of this page
        free = [n for n in range(max(by_line) + 1, count + 1)]
        for n, kind in zip(free, [LINE_SURAH] + ([LINE_BASMALA] if basmala(nxt) else [])):
            heads[n] = (kind, nxt.id)
    opening = tuple(Cell(None, w.text) for w in verses_of(1)[0].text_words) \
        if any(kind == LINE_BASMALA for kind, _ in heads.values()) else ()
    lines = []
    for n in range(1, count + 1):
        if n in by_line:
            lines.append(MushafLine(n, LINE_WORDS, 0, tuple(by_line[n])))
        elif n in heads:
            kind, ch = heads[n]
            lines.append(MushafLine(n, kind, ch, opening if kind == LINE_BASMALA else ()))
        else:
            lines.append(MushafLine(n, LINE_EMPTY))
    return MushafPage(page, tuple(lines))


# Project files: references, times, files and choices. Never the Quran or translation text.

def _path(value, base_dir: Path) -> Path | None:
    """A file named in a project. One that has moved is looked for next to the project file."""
    if not value:
        return None
    p = Path(value)
    if not p.is_absolute():
        p = base_dir / p
    if not p.exists() and (base_dir / p.name).exists():
        p = base_dir / p.name
    return p


def _range(r: TokenRange | None) -> list[str] | None:
    return [str(r.first), str(r.last)] if r else None


def _parse_range(value) -> TokenRange | None:
    return TokenRange(TokenRef.parse(value[0]), TokenRef.parse(value[1])) if value else None


def to_json(job: ManualJob, formats: list[str]) -> dict:
    theme = THEMES.get(job.theme)
    return {
        "app": "Quran Video Creator", "kind": "manual", "version": PROJECT_VERSION,
        "audio": str(job.audio) if job.audio else None, "reciter_name": job.reciter_name, "name": job.name,
        "trim": [job.trim_start_ms, job.trim_end_ms],
        "batches": [{"first": str(b.first), "last": str(b.last), "start": b.start_ms, "end": b.end_ms,
                     "words": list(b.word_ms), "translation": _range(b.translation),
                     "background": str(b.background) if b.background else None} for b in job.batches],
        "translation": job.translation, "translation_mode": job.trans_mode,
        "translation_batches": [{"range": _range(t.range), "start": t.start_ms, "end": t.end_ms}
                                for t in job.trans_batches],
        "font": job.font, "theme": job.theme,
        "theme_colors": {"bg": theme.bg, "highlight": theme.highlight} if theme and not is_builtin(job.theme)
        else None,
        "highlight": job.highlight, "highlight_fade": job.highlight_fade, "reveal": job.reveal,
        "line_spacing": job.line_spacing, "surah_name": job.surah_name, "name_scale": job.name_scale,
        "overlay": job.overlay, "quality": job.quality, "text_width": job.text_width,
        "translation_width": job.translation_width, "fps": job.fps,
        "background": str(job.background) if job.background else None, "bg_end": job.bg_end,
        "formats": formats, "out_dir": str(job.out_dir),
    }


def from_json(d: dict, base_dir: Path) -> tuple[ManualJob, list[str]]:
    """The job (for the first format) and every format chosen. A custom theme the project names is added to
    the themes (for this run) when it is missing. Raises DataError when the file isn't a manual-mode project."""
    if not isinstance(d, dict) or d.get("kind") != "manual" or not isinstance(d.get("version"), int):
        raise DataError("Can't open this project.")
    try:
        name = d.get("theme") or DEFAULT_THEME
        colors = d.get("theme_colors")
        if name not in THEMES and colors and not is_builtin(name):
            add_custom(make_custom(name, colors["bg"], colors["highlight"]))
        formats = [f for f in d.get("formats") or [] if f in FORMATS] or [next(iter(FORMATS))]
        batches = [Batch(WordRef.parse(b["first"]), WordRef.parse(b["last"]), b.get("start"), b.get("end"),
                         tuple(b.get("words") or ()), _parse_range(b.get("translation")),
                         _path(b.get("background"), base_dir)) for b in d.get("batches") or []]
        trans = [TransBatch(_parse_range(t["range"]), t.get("start"), t.get("end"))
                 for t in d.get("translation_batches") or []]
        trim = list(d.get("trim") or [0, None]) + [None]
        defaults = ManualJob(None, [], formats[0], Path("out"))
        job = ManualJob(
            _path(d.get("audio"), base_dir), batches, formats[0], Path(d.get("out_dir") or base_dir),
            trans_mode=d.get("translation_mode") if d.get("translation_mode") in (TRANS_ATTACHED, TRANS_TRACK)
            else TRANS_ATTACHED,
            trans_batches=trans,
            translation=d.get("translation") if d.get("translation") in TRANSLATIONS else "None",
            reciter_name=str(d.get("reciter_name") or ""), name=str(d.get("name") or ""),
            trim_start_ms=int(trim[0] or 0), trim_end_ms=trim[1],
            fps=int(d.get("fps") or defaults.fps),
            font=d.get("font") if d.get("font") in FONTS else defaults.font,
            theme=name if name in THEMES else defaults.theme,
            highlight=d.get("highlight", defaults.highlight), highlight_fade=bool(d.get("highlight_fade", True)),
            reveal=d.get("reveal", defaults.reveal), line_spacing=float(d.get("line_spacing", 0.8)),
            surah_name=bool(d.get("surah_name")), name_scale=float(d.get("name_scale", 1.0)),
            overlay=float(d.get("overlay", 0.0)),
            quality=d.get("quality") if d.get("quality") in QUALITIES else defaults.quality,
            text_width=float(d.get("text_width", defaults.text_width)),
            translation_width=float(d.get("translation_width", defaults.translation_width)),
            background=_path(d.get("background"), base_dir),
            bg_end=d.get("bg_end") if d.get("bg_end") in ("loop", "freeze") else "loop")
    except (KeyError, TypeError, ValueError, IndexError) as e:
        raise DataError("Can't open this project.") from e
    return job, formats
