"""Pure timing math: segment cleaning, verse-range cut, offsets, and what to show at time t."""

import itertools
import logging
import statistics
from collections.abc import Callable
from dataclasses import dataclass, replace

from ..api.models import VerseTiming

log = logging.getLogger(__name__)

ALL = -1  # active-word value meaning "highlight the whole verse" (no usable segments)


@dataclass(frozen=True)
class Seg:
    pos: int  # 1-based word position within the verse
    start: int  # ms
    end: int


@dataclass(frozen=True)
class Clip:
    """One verse placed on the output timeline (ms from the start of the cut audio)."""
    index: int  # index into the selected verses
    start: int
    end: int
    segs: tuple[Seg, ...]  # in recitation order; positions may repeat


@dataclass(frozen=True)
class State:
    verse: int  # index into the selected verses
    active: int | None  # word position, ALL, or None (nothing lit yet)
    reveal: int = 0  # highest word position recited so far in this verse (ALL when untimed)
    page: int | None = None  # force this page of the verse (used to swap text in before it is recited)


def clean_segments(t: VerseTiming, n_words: int) -> list[Seg]:
    """Drop malformed/out-of-range entries, clamp to the verse window. Times stay absolute."""
    out = []
    for raw in t.segments:
        if len(raw) != 3:
            continue  # API returns truncated entries like [1] or [5, 5205]
        pos, a, b = int(raw[0]), round(raw[1]), round(raw[2])
        if not 1 <= pos <= n_words:
            log.warning("%s: segment word %d outside 1..%d, ignored", t.key, pos, n_words)
            continue
        a, b = max(a, t.start), min(b, t.end)
        if b > a:
            out.append(Seg(pos, a, b))
    if not out:
        log.warning("%s: no usable word timing, highlighting whole verse", t.key)
    return out


ENV_RATE = 50  # envelope frames per second (20 ms each), see ffmpeg.envelope


def _rise(env: list[float]) -> Callable[[float], float]:
    """rise(ms): loudness in the 200 ms after `ms` minus the 200 ms before. High where speech starts, low where it ends."""
    half = ENV_RATE // 5
    running = [0.0, *itertools.accumulate(env)]  # running[i] = sum of env[:i], so any window sum is one subtraction

    def rise(ms: float) -> float:
        i = round(ms) * ENV_RATE // 1000
        return running[i + half] - 2 * running[i] + running[i - half] if half <= i <= len(env) - half else 0.0
    return rise


def _first_starts(timings: list[VerseTiming]) -> list[int]:
    """Each verse's first word start. It follows a pause, so it gives one clear onset; with every word the syllable
    rhythm gives several peaks ~300 ms apart and the wrong one can win (Dussary, surah 4)."""
    return [round(min((s[1] for s in t.segments if len(s) == 3), default=t.start)) for t in timings]


def audio_offset(timings: list[VerseTiming], env: list[float]) -> int | None:
    """Shift (ms) that puts the verse starts on speech onsets in the audio envelope, or None when no clear one.
    Only call it once a mismatch is proven: on short surahs a stray onset can win."""
    starts, rise = _first_starts(timings), _rise(env)

    def score(ms: int) -> float:
        return sum(rise(start + ms) for start in starts)

    best = max(range(-15000, 15001, 1000 // ENV_RATE), key=score)
    # the last verse must start inside the audio; its end may run past it (the file's tail is trimmed too: surah 2)
    fits = starts[-1] + best < len(env) * 1000 // ENV_RATE
    return best if abs(best) >= 500 and fits and score(best) > 2 * max(score(0), 0) else None


def shifted(timings: list[VerseTiming], ms: int) -> list[VerseTiming]:
    """The same timings, every time moved by `ms`."""
    return [VerseTiming(t.key, t.start + ms, t.end + ms,
                        tuple((s[0], s[1] + ms, s[2] + ms) if len(s) == 3 else s for s in t.segments))
            for t in timings]


ONSET_LAG = 140  # rise() reads correctly timed verse starts ~140 ms late (Alafasy, Sudais, Ghamdi... all 100-260)


def local_offsets(timings: list[VerseTiming], env: list[float]) -> list[int]:
    """Per-verse correction (ms, 0 = none) where part of a surah is off: a step (Hani ar-Rifai 36: +1.4 s from verse
    33) or a drift (Abdul Basit Mujawwad 36: up to -0.8 s). For a verse, its neighbours' starts are matched to the
    onsets and their ends to the falls. A correction needs both to move by the same amount, compared with the verses
    that are in place, and its neighbours to agree: the onset measure alone is fooled by some recitation styles."""
    rise, window, step = _rise(env), 7, 1000 // ENV_RATE
    starts = _first_starts(timings)
    ends = [round(max((s[2] for s in t.segments if len(s) == 3), default=t.end)) for t in timings]
    shifts = sorted(range(-3000, 3001, step), key=abs)  # ties (silence) go to the smallest shift

    def best(points: list[int], sign: int) -> int:
        return max(shifts, key=lambda d: sum(sign * rise(p + d) for p in points))

    near = [slice(max(0, i - window), i + window + 1) for i in range(len(timings))]
    on = [best(starts[s], 1) for s in near]
    off = [best(ends[s], -1) for s in near]
    in_place = [o for s, o in zip(on, off) if abs(s - ONSET_LAG) < 300]
    if not in_place:
        return [0] * len(timings)
    end_lag = statistics.median(in_place)  # where the falls sit for this reciter: it depends on how the verses end
    out = []
    for i, (s, o) in enumerate(zip(on, off)):
        # the first and last two verses have half a window and too few neighbours to agree: never corrected
        c, around = s - ONSET_LAG, on[i - 2:i + 3] if i >= 2 else []
        steady = len(around) == 5 and max(around) - min(around) <= 200
        out.append(c if abs(c) >= 400 and abs(o - end_lag - c) <= 300 and steady else 0)
    return out


QUIET = 0.1  # loudness below this share of the median is silence (speech sits near 1, pauses under 0.07)
PAUSE_MS = 200  # a silence this long is a pause; shorter ones are stops inside a word
EDGE_MS = 1500  # how far a verse's first or last word may be moved


def snap_edges(timings: list[VerseTiming], env: list[float]) -> list[VerseTiming]:
    """Put each verse's first word start and last word end where the voice starts and stops. QF often starts
    the first word in the silence before it (Minshawi, Husary, Abdul Basit: 0.5-0.9 s early) and ends the last
    word while it is still being held (Dussary, Abdul Basit). Verses that need nothing stay the same objects."""
    if not env:
        return timings
    frame, thr = 1000 // ENV_RATE, QUIET * statistics.median(env)

    def quiet(ms: int) -> bool:
        i = ms // frame
        return 0 <= i < len(env) and env[i] < thr  # outside the audio counts as sound: nothing is moved there

    out = []
    for t in timings:
        segs = [list(s) for s in t.segments]
        timed = [s for s in segs if len(s) == 3]
        if not timed:
            out.append(t)
            continue
        first, last = min(timed, key=lambda s: s[1]), max(timed, key=lambda s: s[2])
        a = round(first[1])
        if quiet(a):
            onset = next((ms for ms in range(a, min(round(first[2]) - 3 * frame, a + EDGE_MS), frame)
                          if not quiet(ms)), None)
            first[1] = onset if onset is not None else first[1]
        b = round(last[2])
        if not quiet(b):
            limit, run = min(t.end, b + EDGE_MS), PAUSE_MS // frame
            pause = next((ms for ms in range(b, limit - PAUSE_MS, frame)
                          if all(quiet(ms + k * frame) for k in range(run))), None)
            last[2] = pause if pause is not None else last[2]
        new = tuple(tuple(s) for s in segs)
        out.append(t if new == t.segments else VerseTiming(t.key, t.start, t.end, new))
    return out


def change_at_last_word(clips: list[Clip]) -> list[Clip]:
    """Each verse comes on screen once the last word of the one before has been recited, instead of when its own
    timing starts. Never later than that start."""
    out = clips[:1]
    for c in clips[1:]:
        prev = out[-1]
        end = max((s.end for s in prev.segs), default=c.start)
        out.append(replace(c, start=max(prev.start + 1, min(c.start, end))))
    return out


def cut_range(timings: list[VerseTiming]) -> tuple[int, int]:
    """Audio [start, end) ms in the chapter file for the selected verses (timings already sliced)."""
    return timings[0].start, timings[-1].end


class DataError(Exception):
    """The API data can't be used for the requested range. `key` is the English message, with {names} for the
    parts that vary; the app translates the key and fills `params` in."""

    def __init__(self, key: str, **params):
        super().__init__(key.format(**params))
        self.key, self.params = key, params


def basmala_available(chapter: int, v_from: int) -> bool:
    """The Basmala opens every surah except Al-Fatihah (where it is verse 1) and At-Tawbah (which has none).
    It is taken from the reciter's own recitation of 1:1, so it only applies when the range starts at verse 1."""
    return chapter not in (1, 9) and v_from == 1


def check_timings(timings: list[VerseTiming], reciter: str) -> None:
    """Reject ranges whose timing is unusable (e.g. a zero-length verse), so the user can pick another reciter."""
    for t in timings:
        if t.end <= t.start:
            raise DataError("{reciter} has no timing for verse {verse}. Pick another reciter.",
                            reciter=reciter, verse=t.key)


def build_clips(timings: list[VerseTiming], word_counts: list[int], audio_start: int,
                index_offset: int = 0) -> list[Clip]:
    """Place each verse on the output timeline, where `audio_start` (ms in the chapter audio) becomes 0."""
    clips = []
    for i, (t, n) in enumerate(zip(timings, word_counts)):
        segs = tuple(Seg(s.pos, s.start - audio_start, s.end - audio_start) for s in clean_segments(t, n))
        clips.append(Clip(i + index_offset, t.start - audio_start, t.end - audio_start, segs))
    return clips


def state_at(clips: list[Clip], t: float) -> State:
    """Highlight state at t ms. The current verse is the last one that has started;
    within it, the last word that has started stays lit through gaps."""
    clip = clips[0]
    for c in clips:
        if c.start <= t:
            clip = c
        else:
            break
    if not clip.segs:
        return State(clip.index, ALL, ALL)
    active, reveal = None, 0
    for s in clip.segs:
        if s.start <= t:
            active, reveal = s.pos, max(reveal, s.pos)  # repeats must not hide words again
        else:
            break
    return State(clip.index, active, reveal)
