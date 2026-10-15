"""Pure timing math: segment cleaning, verse-range cut, offsets, and what to show at time t."""

import itertools
import logging
from dataclasses import dataclass

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


def audio_offset(timings: list[VerseTiming], env: list[float]) -> int | None:
    """Shift (ms) that puts the word starts on speech onsets in the audio envelope, or None when no clear one.
    Only call it once a mismatch is proven: on short surahs a stray onset can win."""
    starts = [s[1] for t in timings for s in t.segments if len(s) == 3] or [t.start for t in timings]
    half = ENV_RATE // 5  # frames in 200 ms: the window either side of each start
    running = [0.0, *itertools.accumulate(env)]  # running[i] = sum of env[:i], so any window sum is one subtraction

    def score(ms: int) -> float:
        total = 0.0
        for start in starts:
            i = (start + ms) * ENV_RATE // 1000
            if half <= i <= len(env) - half:
                # loudness just after minus loudness just before: a word starts where the audio gets louder
                total += running[i + half] - 2 * running[i] + running[i - half]
        return total

    best = max(range(-15000, 15001, 50), key=score)
    fits = timings[-1].end + best <= len(env) * 1000 // ENV_RATE + 1000
    return best if abs(best) >= 500 and fits and score(best) > 2 * max(score(0), 0) else None


def shifted(timings: list[VerseTiming], ms: int) -> list[VerseTiming]:
    """The same timings, every time moved by `ms`."""
    return [VerseTiming(t.key, t.start + ms, t.end + ms,
                        tuple((s[0], s[1] + ms, s[2] + ms) if len(s) == 3 else s for s in t.segments))
            for t in timings]


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
