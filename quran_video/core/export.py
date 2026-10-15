"""One export job: fetch data, cut the range, stream text frames into ffmpeg. No widgets."""

import logging
import math
import re
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter

from ..api.client import ApiError, QuranClient
from ..api.models import Reciter, Verse, VerseTiming
from ..config.fonts import DEFAULT_FONT, FONTS
from ..config.presets import FORMATS
from ..config.quality import DEFAULT_QUALITY, QUALITIES, scaled_size
from ..config.themes import DEFAULT_THEME, THEMES
from ..config.translations import DEFAULT_TRANSLATION, TRANSLATIONS
from .ffmpeg import IMAGE_EXTS, NO_WINDOW, FFmpegError, build_cmd, envelope, ffmpeg_exe, is_video, media_seconds
from .render import DEFAULT_STOPS, DEFAULT_TEXT_WIDTH, HIGHLIGHT_WORD, REVEAL_OFF, SPLIT_PARTS, RenderOptions, TextRenderer
from .timing import (DataError, State, audio_offset, basmala_available, build_clips, check_timings, cut_range,
                     shifted, state_at)

log = logging.getLogger(__name__)


FADE_OUT_MS = 250  # every verse/part fades out, then the next fades in (always on)
FADE_IN_MS = 350
LEAD_MS = 120  # the next text is swapped in this long before its first word, while invisible
HIGHLIGHT_FADE_MS = 240  # a newly lit word eases from the text colour to the highlight colour
HIGHLIGHT_LEAD_MS = 70  # and starts turning this early, so the colour has arrived when the word is heard


@dataclass
class ExportJob:
    chapter: int
    v_from: int
    v_to: int
    reciter: Reciter
    fmt: str
    out_dir: Path
    fps: int = 30
    font: str = DEFAULT_FONT
    theme: str = DEFAULT_THEME
    split: str = SPLIT_PARTS  # 'parts' (cut at the chosen stop signs) or 'verse'
    highlight: str = HIGHLIGHT_WORD  # 'none', 'word' (current word) or 'keep' (every recited word)
    highlight_fade: bool = True  # a word's highlight eases in instead of popping
    reveal: str = REVEAL_OFF  # 'off', 'build' (words appear as recited) or 'single' (one word at a time)
    line_spacing: float = 0.8
    show_arabic: bool = True  # False: only the translation (and surah name) is shown
    surah_name: bool = False
    translation: str = DEFAULT_TRANSLATION  # key of config.translations.TRANSLATIONS
    overlay: float = 0.0
    quality: str = DEFAULT_QUALITY  # key of config.quality.QUALITIES: resolution scale, CRF, audio bitrate
    text_width: float = DEFAULT_TEXT_WIDTH  # share of the frame width the Arabic may use
    translation_width: float = DEFAULT_TEXT_WIDTH  # the same for the translation
    name_scale: float = 1.0  # size of the surah name
    bg_end: str = "loop"  # a background video shorter than the recitation: 'loop' it or 'freeze' on its last frame
    background: Path | None = None  # image or video; None = the theme's solid colour
    stops: tuple[str, ...] = DEFAULT_STOPS  # which stop signs cut a verse into parts
    basmala: bool = False  # open with the Basmala: the reciter's own 1:1 recitation, word timing included

    @property
    def filename(self) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", self.reciter.name.lower()).strip("-")
        return f"surah-{self.chapter}_{self.v_from}-{self.v_to}_{slug}_{self.fmt.replace(':', 'x')}.mp4"


class Cancelled(Exception):
    pass


@dataclass
class Prepared:
    renderer: TextRenderer
    clips: list
    audio: Path
    a_start: int
    a_end: int
    size: tuple[int, int]  # output width and height, after the quality's scale
    lead_ms: int = 0  # length of the Basmala placed before verse 1 (0 = none)
    lead_audio: tuple | None = None  # (audio file, start ms, length ms) of that Basmala


def fit_to_audio(timings: list[VerseTiming], audio_file: Path, reciter: str) -> list[VerseTiming]:
    """QF sometimes pairs timings with a re-cut audio file (Dussary, surah 35: intro cut, words 7 s late).
    Timings that run past the end of the audio prove it; then find the shift from the audio itself."""
    secs = media_seconds(audio_file)
    if secs is None or timings[-1].end <= secs * 1000 + 1000:
        return timings
    ms = audio_offset(timings, envelope(audio_file))
    if ms is None:
        raise DataError("{reciter}'s timing doesn't match the audio for this surah. Pick another reciter.", reciter=reciter)
    log.info("%s: timings shifted %+d ms to match the audio", reciter, ms)
    return shifted(timings, ms)


def prepare(job: ExportJob, client: QuranClient, audio: bool = True) -> Prepared:
    """Fetch and cut everything the frame loop needs. Requires a QGuiApplication (fonts)."""
    font, theme = FONTS[job.font], THEMES[job.theme]
    tr_id = TRANSLATIONS[job.translation]
    if not job.show_arabic and tr_id is None:
        raise DataError("Nothing to show: turn on the Arabic text or choose a translation.")
    verses = client.verses(job.chapter, font.text_field, tr_id)[job.v_from - 1:job.v_to]
    url, timings = client.recitation(job.reciter.id, job.chapter)
    audio_file = client.audio(job.reciter.id, job.chapter, url) if audio else None
    if audio_file:
        timings = fit_to_audio(timings, audio_file, job.reciter.name)
    timings = timings[job.v_from - 1:job.v_to]
    if [t.key for t in timings] != [v.key for v in verses]:
        raise ValueError("Verse timings do not line up with verse text")
    check_timings(timings, job.reciter.name)
    a_start, a_end = cut_range(timings)
    counts = [len(v.text_words) for v in verses]
    lead_ms, lead_audio = 0, None
    if job.basmala:
        if not basmala_available(job.chapter, job.v_from):
            raise DataError("Needs verse 1 of a surah other than Al-Fatihah and At-Tawbah.")
        # The Basmala is verse 1:1, taken from the same reciter's Al-Fatihah recording: same voice, timed words.
        b_url, b_timings = client.recitation(job.reciter.id, 1)
        b_file = client.audio(job.reciter.id, 1, b_url) if audio else None
        b = (fit_to_audio(b_timings, b_file, job.reciter.name) if b_file else b_timings)[0]
        check_timings([b], job.reciter.name)
        first = client.verses(1, font.text_field, tr_id)[0]  # text exactly as returned, without its verse sign
        b_words = tuple(w for w in first.words if not w.is_end)
        lead_ms = b.end - b.start
        lead_audio = (b_file, b.start, lead_ms)
        clips = build_clips([b], [len(b_words)], b.start) + build_clips(timings, counts, a_start - lead_ms, 1)
        verses = [Verse("basmala", 0, b_words, first.translation), *verses]
    else:
        clips = build_clips(timings, counts, a_start)
    w, h = scaled_size(*FORMATS[job.fmt], QUALITIES[job.quality].scale)
    opts = RenderOptions(theme, split=job.split, stops=job.stops, highlight=job.highlight, reveal=job.reveal,
                         line_spacing=job.line_spacing, show_arabic=job.show_arabic,
                         chapter=job.chapter if job.surah_name else 0, translation=tr_id is not None,
                         overlay=job.overlay if job.background else 0.0, text_width=job.text_width,
                         translation_width=job.translation_width, name_scale=job.name_scale)
    return Prepared(TextRenderer(w, h, verses, font, opts), clips, audio_file, a_start, a_end, (w, h), lead_ms, lead_audio)


def ease(t: float) -> float:
    t = min(1.0, max(0.0, t))
    return t * t * (3 - 2 * t)  # smoothstep: gentle start and end


def frame_plan(prep: Prepared, fps: int, fade: bool = True, hl_fade: bool = False) -> list[tuple]:
    """(state, alpha, hl, prev) per frame.

    At every page change the old text eases out, the new text is swapped in a moment before its first word
    while invisible, and eases in. The first page appears at once and the last one eases out at the end.
    With hl_fade, a newly lit word eases in (hl runs 0 to 1) while the word it replaces (prev) eases out."""
    total = math.ceil((prep.lead_ms + prep.a_end - prep.a_start) * fps / 1000)
    def state(i: int) -> State:
        t = i * 1000 / fps
        s = state_at(prep.clips, t)
        if hl_fade:  # the word lights a moment early, but never across a verse boundary
            early = state_at(prep.clips, t + HIGHLIGHT_LEAD_MS)
            if early.verse == s.verse:
                return early
        return s

    states = [state(i) for i in range(total)]
    alpha = [1.0] * total
    if fade:
        r = prep.renderer
        keys = [r.page_key(s) for s in states]
        cuts = [i for i in range(1, total) if keys[i] != keys[i - 1]]  # first frame of each new page
        fo, fi, lead = (round(ms * fps / 1000) for ms in (FADE_OUT_MS, FADE_IN_MS, LEAD_MS))
        swaps = [max(c - lead, 1) for c in cuts]
        for n, sw in enumerate(swaps):
            for k in range(sw, cuts[n]):  # show the next page, unlit, before it is recited
                v, pg = keys[cuts[n]]
                states[k] = State(v, None, 0, pg)  # nothing recited yet, so a reveal style shows no words
            prev = swaps[n - 1] if n else 0
            nxt = swaps[n + 1] if n + 1 < len(swaps) else total
            out, inn = min(fo, (sw - prev) // 2), min(fi, (nxt - sw) // 2)
            for k in range(sw - out, sw):
                alpha[k] = min(alpha[k], ease((sw - k) / (out + 1)))
            for k in range(sw, sw + inn):
                alpha[k] = min(alpha[k], ease((k - sw) / inn))
        last = min(fo, (total - (swaps[-1] if swaps else 0)) // 2)
        for k in range(total - last, total):
            alpha[k] = min(alpha[k], ease((total - k) / (last + 1)))
    hl, prev_word = [1.0] * total, [None] * total
    if hl_fade:
        frames = max(1, round(HIGHLIGHT_FADE_MS * fps / 1000))
        since, before, last_key = frames, None, None  # frames since the lit word changed
        for i, s in enumerate(states):
            key = (s.verse, s.active)
            if key != last_key:
                same_verse = last_key is not None and last_key[0] == s.verse
                before = last_key[1] if same_verse and isinstance(last_key[1], int) and last_key[1] > 0 else None
                since = 0 if isinstance(s.active, int) and s.active > 0 else frames  # only real words fade
                last_key = key
            else:
                since = min(frames, since + 1)
            if since < frames:
                hl[i], prev_word[i] = ease((since + 1) / (frames + 1)), before  # smooth start and finish
    return [(s, a, h, p) for s, a, h, p in zip(states, alpha, hl, prev_word)]


def export(job: ExportJob, client: QuranClient, progress: Callable[[float], None] = lambda f: None,
           cancelled: Callable[[], bool] = lambda: False) -> Path:
    prep = prepare(job, client)
    w, h = prep.size
    q = QUALITIES[job.quality]
    job.out_dir.mkdir(parents=True, exist_ok=True)
    out = job.out_dir / job.filename
    part = out.with_name(out.name + ".part")
    plan = frame_plan(prep, job.fps, hl_fade=job.highlight_fade and job.highlight != "none" and job.show_arabic)

    with tempfile.TemporaryFile() as err, tempfile.TemporaryDirectory() as tmpdir:
        bg = job.background
        if bg is not None and bg.suffix.lower() in IMAGE_EXTS:
            bg = Path(tmpdir) / "bg.png"  # sized once here, so ffmpeg doesn't resize a huge photo on every frame
            background_image(job.background, w, h).save(str(bg))
        cmd = build_cmd(ffmpeg_exe(), w, h, job.fps, prep.audio, prep.a_start, prep.a_end - prep.a_start, part,
                        THEMES[job.theme].bg, bg, q.crf, q.audio_kbps, prep.lead_audio, job.bg_end == "freeze")
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=err, creationflags=NO_WINDOW)
        last, frame = None, b""  # only the current frame is kept in memory
        try:
            for i, frame_key in enumerate(plan):
                if cancelled():
                    raise Cancelled()
                if frame_key != last:
                    img = prep.renderer.render(*frame_key)  # keep img alive: constBits() is a view into it
                    last, frame = frame_key, img.constBits().tobytes()
                proc.stdin.write(frame)
                if i % job.fps == 0:
                    progress(i / len(plan))
            proc.stdin.close()
            if proc.wait() != 0:
                raise BrokenPipeError
        except BrokenPipeError:
            proc.wait()
            err.seek(0)
            part.unlink(missing_ok=True)
            raise FFmpegError(err.read().decode(errors="replace")[-2000:] or "ffmpeg failed")
        except BaseException:
            proc.kill()
            proc.wait()
            part.unlink(missing_ok=True)
            raise
    part.replace(out)
    credits_path(out).write_text(credits(job), "utf-8")
    progress(1.0)
    return out


def credits(job: ExportJob) -> str:
    """Caption credits. The Quran Foundation terms allow social-media videos only when these are given."""
    lines = [f"Recitation: {job.reciter.name}"]
    if TRANSLATIONS[job.translation] is not None:
        lines.append(f"Translation: {job.translation}")
    return "\n".join(lines + ["Quran data provided by Quran.Foundation (https://quran.foundation)"]) + "\n"


def credits_path(video: Path) -> Path:
    return video.with_suffix(".credits.txt")


def export_pngs(job: ExportJob, client: QuranClient) -> list[Path]:
    """One still per on-screen page (taken near the end of its time), on the theme background. For quick checks."""
    prep = prepare(job, client)
    plan = frame_plan(prep, job.fps, fade=False)
    keys = [prep.renderer.page_key(f[0]) for f in plan]
    bg = QColor(THEMES[job.theme].bg)
    job.out_dir.mkdir(parents=True, exist_ok=True)
    paths, i = [], 0
    while i < len(plan):
        j = i
        while j < len(plan) and keys[j] == keys[i]:
            j += 1
        state = plan[i + int((j - i) * 0.9)][0]
        w, h = prep.size
        img = QImage(w, h, QImage.Format.Format_RGBA8888)
        img.fill(bg)
        p = QPainter(img)
        p.drawImage(0, 0, prep.renderer.render(state))
        p.end()
        path = job.out_dir / f"{Path(job.filename).stem}_p{len(paths) + 1:03d}.png"
        img.save(str(path))
        paths.append(path)
        i = j
    return paths


def background_image(path: Path, w: int, h: int) -> QImage:
    """The background (an image, or a video's first frame) scaled and cropped to cover w x h."""
    if path.suffix.lower() in IMAGE_EXTS:
        src = QImage(str(path))
    else:
        with tempfile.TemporaryDirectory() as d:
            png = Path(d) / "frame.png"
            subprocess.run([ffmpeg_exe(), "-y", "-loglevel", "error", "-i", str(path), "-frames:v", "1", str(png)],
                           check=False, capture_output=True, creationflags=NO_WINDOW)
            src = QImage(str(png))
    if src.isNull():
        raise FFmpegError(f"Could not read the background file: {path}")
    img = src.scaled(w, h, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
    return img.copy((img.width() - w) // 2, (img.height() - h) // 2, w, h)


def preview_image(job: ExportJob, client: QuranClient) -> QImage:
    """One representative frame (mid-way through the first verse) as it will look in the video. No audio download."""
    prep = prepare(replace(job, quality=DEFAULT_QUALITY), client, audio=False)  # always full size
    first = prep.clips[0]
    state = state_at(prep.clips, first.start + 0.45 * (first.end - first.start))
    w, h = prep.size
    img = QImage(w, h, QImage.Format.Format_RGBA8888)
    img.fill(QColor(THEMES[job.theme].bg))
    p = QPainter(img)
    if job.background:
        p.drawImage(0, 0, background_image(job.background, w, h))
    p.drawImage(0, 0, prep.renderer.render(state))
    p.end()
    return img


# Average video bitrate (kb/s) by background and quality. High was measured on a 52 s export; the others follow
# the ratios measured on 13 s exports. Audio is separate. A background video depends on its footage, so its
# figures are only a rough guide.
VIDEO_KBPS = {
    "solid": {"Very high": 87, "High": 85, "Medium": 53, "Low": 33, "Very low": 19},
    "image": {"Very high": 283, "High": 230, "Medium": 118, "Low": 57, "Very low": 24},
    "video": {"Very high": 6600, "High": 4500, "Medium": 2100, "Low": 660, "Very low": 90},
}


def estimate_bytes(seconds: float, background: Path | None, quality: str = DEFAULT_QUALITY) -> int:
    kind = "solid" if background is None else "image" if background.suffix.lower() in IMAGE_EXTS else "video"
    kbps = QUALITIES[quality].audio_kbps + VIDEO_KBPS[kind][quality]
    return int(seconds * kbps * 1000 / 8)


def estimate_seconds(seconds: float, quality: str = DEFAULT_QUALITY) -> float:
    """Rough export time. Measured on one machine: about 0.15 s per video second at full size, and it falls with the pixels."""
    return 2 + seconds * (0.03 + 0.12 * QUALITIES[quality].scale ** 2)


def video_info(job: ExportJob, client: QuranClient) -> dict:
    """Length (s), whether the Basmala option applies, and any reason the reciter can't be used. Cached data only."""
    url, timings = client.recitation(job.reciter.id, job.chapter)
    timings = timings[job.v_from - 1:job.v_to]
    problem, problem_error = "", None
    try:
        check_timings(timings, job.reciter.name)
    except DataError as e:
        problem, problem_error = str(e), e
    can_basmala, lead_ms = False, 0
    if basmala_available(job.chapter, job.v_from):
        try:
            b = client.recitation(job.reciter.id, 1)[1][0]
            check_timings([b], job.reciter.name)
            can_basmala, lead_ms = True, b.end - b.start
        except (DataError, ApiError):
            pass  # this reciter has no usable Basmala timing
    a_start, a_end = cut_range(timings)
    seconds = (a_end - a_start + (lead_ms if job.basmala and can_basmala else 0)) / 1000
    bg_seconds = media_seconds(job.background) if is_video(job.background) else None
    return {"seconds": seconds, "basmala_ok": can_basmala, "problem": problem, "problem_error": problem_error, "bg_seconds": bg_seconds}
