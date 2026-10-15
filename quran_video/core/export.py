"""One export job: fetch data, cut the range, stream text frames into ffmpeg. No widgets."""

import logging
import math
import queue
import re
import subprocess
import tempfile
import threading
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import NamedTuple

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter

from ..api.client import ApiError, QuranClient
from ..api.models import Reciter, Verse, VerseTiming
from ..config.fonts import DEFAULT_FONT, FONTS
from ..config.presets import FORMATS
from ..config.quality import DEFAULT_QUALITY, QUALITIES, scaled_size
from ..config.stops import DEFAULT_STOPS
from ..config.themes import DEFAULT_THEME, THEMES
from ..config.translations import DEFAULT_TRANSLATION, TRANSLATIONS
from .ffmpeg import (IMAGE_EXTS, NO_WINDOW, FFmpegError, LeadAudio, build_cmd, envelope, ffmpeg_exe, is_video,
                     media_seconds)
from .render import (DEFAULT_TEXT_WIDTH, HIGHLIGHT_NONE, HIGHLIGHT_WORD, REVEAL_OFF, SPLIT_PARTS, RenderOptions,
                     TextRenderer)
from .timing import (Clip, DataError, State, audio_offset, basmala_available, build_clips, check_timings, cut_range,
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
    overlay: float = 0.0  # 0..1 black veil over a background image or video, for readability
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
    """Everything the frame loop needs, fetched and cut once."""
    renderer: TextRenderer
    clips: list[Clip]
    audio: Path | None  # the chapter's recitation (None for a preview, which needs no sound)
    audio_start_ms: int  # where the selected verses start and end in that file
    audio_end_ms: int
    size: tuple[int, int]  # output width and height, after the quality's scale
    lead_ms: int = 0  # length of the Basmala placed before verse 1 (0 = none)
    lead_audio: LeadAudio | None = None  # where that Basmala comes from


class Frame(NamedTuple):
    """What one video frame shows. TextRenderer.render(*frame) draws it."""
    state: State
    alpha: float  # opacity of the verse text: below 1 while fading between pages
    highlight_progress: float  # how far the newest highlight has eased in, 0..1
    fading_word: int | None  # the word whose highlight is easing out at the same time


def fit_to_audio(timings: list[VerseTiming], audio_file: Path, reciter: str) -> list[VerseTiming]:
    """QF sometimes pairs timings with a re-cut audio file (Dussary, surah 35: intro cut, words 7 s late).
    Timings that run past the end of the audio prove it; then find the shift from the audio itself."""
    secs = media_seconds(audio_file)
    if secs is None or timings[-1].end <= secs * 1000 + 1000:
        return timings
    ms = audio_offset(timings, envelope(audio_file))
    if ms is None:
        raise DataError("{reciter}'s timing doesn't match the audio for this surah. Pick another reciter.",
                        reciter=reciter)
    log.info("%s: timings shifted %+d ms to match the audio", reciter, ms)
    return shifted(timings, ms)


def check_translation(verses: list[Verse], translation: str) -> None:
    """Quran.com answers a translation it no longer serves with empty text: refuse rather than export without it."""
    if TRANSLATIONS[translation] is not None and not any(v.translation for v in verses):
        raise DataError("This translation is not available for these verses. Choose another one.")


def prepare(job: ExportJob, client: QuranClient, audio: bool = True,
            on_download: Callable[[int, int], None] | None = None) -> Prepared:
    """Fetch and cut everything the frame loop needs. Requires a QGuiApplication (fonts).

    `on_download(done, total)` follows the recitation download, when it is not cached yet."""
    font, theme = FONTS[job.font], THEMES[job.theme]
    translation_id = TRANSLATIONS[job.translation]
    if not job.show_arabic and translation_id is None:
        raise DataError("Nothing to show: turn on the Arabic text or choose a translation.")
    verses = client.verses(job.chapter, font.text_field, translation_id)[job.v_from - 1:job.v_to]
    check_translation(verses, job.translation)
    url, timings = client.recitation(job.reciter.id, job.chapter)
    audio_file = client.audio(job.reciter.id, job.chapter, url, on_download) if audio else None
    if audio_file:
        timings = fit_to_audio(timings, audio_file, job.reciter.name)
    timings = timings[job.v_from - 1:job.v_to]
    if [t.key for t in timings] != [v.key for v in verses]:
        raise ValueError("Verse timings do not line up with verse text")
    check_timings(timings, job.reciter.name)
    start_ms, end_ms = cut_range(timings)
    counts = [len(v.text_words) for v in verses]
    lead_ms, lead_audio = 0, None
    if job.basmala:
        if not basmala_available(job.chapter, job.v_from):
            raise DataError("Needs verse 1 of a surah other than Al-Fatihah and At-Tawbah.")
        # The Basmala is verse 1:1, taken from the same reciter's Al-Fatihah recording: same voice, timed words.
        basmala_url, fatihah_timings = client.recitation(job.reciter.id, 1)
        basmala_file = client.audio(job.reciter.id, 1, basmala_url, on_download) if audio else None
        if basmala_file:
            fatihah_timings = fit_to_audio(fatihah_timings, basmala_file, job.reciter.name)
        basmala = fatihah_timings[0]
        check_timings([basmala], job.reciter.name)
        first = client.verses(1, font.text_field, translation_id)[0]  # text exactly as returned
        basmala_words = tuple(w for w in first.words if not w.is_end)  # without its verse-number sign
        lead_ms = basmala.end - basmala.start
        lead_audio = LeadAudio(basmala_file, basmala.start, lead_ms)
        clips = (build_clips([basmala], [len(basmala_words)], basmala.start)
                 + build_clips(timings, counts, start_ms - lead_ms, index_offset=1))
        verses = [Verse("basmala", 0, basmala_words, first.translation), *verses]
    else:
        clips = build_clips(timings, counts, start_ms)
    w, h = scaled_size(*FORMATS[job.fmt], QUALITIES[job.quality].scale)
    opts = RenderOptions(theme, split=job.split, stops=job.stops, highlight=job.highlight, reveal=job.reveal,
                         line_spacing=job.line_spacing, show_arabic=job.show_arabic,
                         chapter=job.chapter if job.surah_name else 0, translation=translation_id is not None,
                         overlay=job.overlay if job.background else 0.0, text_width=job.text_width,
                         translation_width=job.translation_width, name_scale=job.name_scale,
                         fill=None if job.background else theme.bg)
    renderer = TextRenderer(w, h, verses, font, opts)
    return Prepared(renderer, clips, audio_file, start_ms, end_ms, (w, h), lead_ms, lead_audio)


def ease(t: float) -> float:
    t = min(1.0, max(0.0, t))
    return t * t * (3 - 2 * t)  # smoothstep: gentle start and end


def frame_plan(prep: Prepared, fps: int, fade: bool = True, hl_fade: bool = False) -> list[Frame]:
    """One Frame per video frame.

    At every page change the old text eases out, the new text is swapped in a moment before its first word
    while invisible, and eases in. The first page appears at once and the last one eases out at the end.
    With hl_fade, a newly lit word eases in (highlight_progress runs 0 to 1) while the word it replaces
    (fading_word) eases out."""
    total = math.ceil((prep.lead_ms + prep.audio_end_ms - prep.audio_start_ms) * fps / 1000)

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
        keys = [prep.renderer.page_key(s) for s in states]
        cuts = [i for i in range(1, total) if keys[i] != keys[i - 1]]  # first frame of each new page
        fade_out, fade_in, lead = (round(ms * fps / 1000) for ms in (FADE_OUT_MS, FADE_IN_MS, LEAD_MS))
        swaps = [max(cut - lead, 1) for cut in cuts]  # where each new page replaces the old one
        for n, swap in enumerate(swaps):
            verse, page = keys[cuts[n]]
            for k in range(swap, cuts[n]):  # show the next page, unlit, before it is recited
                states[k] = State(verse, None, 0, page)  # nothing recited yet, so a reveal style shows no words
            prev_swap = swaps[n - 1] if n else 0
            next_swap = swaps[n + 1] if n + 1 < len(swaps) else total
            # A short page gets shorter fades, so it is fully visible for at least half its time.
            out_frames = min(fade_out, (swap - prev_swap) // 2)
            in_frames = min(fade_in, (next_swap - swap) // 2)
            for k in range(swap - out_frames, swap):
                alpha[k] = min(alpha[k], ease((swap - k) / (out_frames + 1)))
            for k in range(swap, swap + in_frames):
                alpha[k] = min(alpha[k], ease((k - swap) / in_frames))
        last = min(fade_out, (total - (swaps[-1] if swaps else 0)) // 2)
        for k in range(total - last, total):
            alpha[k] = min(alpha[k], ease((total - k) / (last + 1)))
    progress, fading = [1.0] * total, [None] * total
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
                progress[i], fading[i] = ease((since + 1) / (frames + 1)), before  # smooth start and finish
    return [Frame(*row) for row in zip(states, alpha, progress, fading)]


def _feed(stdin, frames: queue.Queue, failed: list[BaseException]) -> None:
    """Writer thread: hands the drawn frames to ffmpeg until it gets None, so drawing the next frame overlaps
    encoding the last one."""
    try:
        while (pixels := frames.get()) is not None:
            stdin.write(pixels)
    except OSError as e:  # ffmpeg stopped or was stopped
        failed.append(e)
        while frames.get() is not None:  # keep emptying the queue, so the drawing loop never waits on it
            pass


def export(job: ExportJob, client: QuranClient, progress: Callable[[float], None] = lambda f: None,
           cancelled: Callable[[], bool] = lambda: False,
           download: Callable[[int, int], None] = lambda done, total: None) -> Path:
    """Write the video (and its .credits.txt) and return its path. `progress` gets 0..1, `download` follows the
    recitation download (bytes done, total), and `cancelled` can stop either."""
    def downloading(done: int, total: int) -> None:
        if cancelled():
            raise Cancelled()
        download(done, total)

    prep = prepare(job, client, on_download=downloading)
    w, h = prep.size
    q = QUALITIES[job.quality]
    job.out_dir.mkdir(parents=True, exist_ok=True)
    out = job.out_dir / job.filename
    part = out.with_name(out.name + ".part")
    hl_fade = job.highlight_fade and job.highlight != HIGHLIGHT_NONE and job.show_arabic
    plan = frame_plan(prep, job.fps, hl_fade=hl_fade)

    with tempfile.TemporaryFile() as err, tempfile.TemporaryDirectory() as tmpdir:
        bg = job.background
        if bg is not None and bg.suffix.lower() in IMAGE_EXTS:
            bg = Path(tmpdir) / "bg.png"  # sized once here, so ffmpeg doesn't resize a huge photo on every frame
            background_image(job.background, w, h).save(str(bg))
        cmd = build_cmd(ffmpeg_exe(), w, h, job.fps, prep.audio, prep.audio_start_ms,
                        prep.audio_end_ms - prep.audio_start_ms, part, background=bg, crf=q.crf,
                        audio_kbps=q.audio_kbps, lead=prep.lead_audio, freeze=job.bg_end == "freeze")
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=err, creationflags=NO_WINDOW)
        frames: queue.Queue[bytes | None] = queue.Queue(maxsize=3)  # drawn frames waiting for ffmpeg (8 MB each)
        failed: list[BaseException] = []
        writer = threading.Thread(target=_feed, args=(proc.stdin, frames, failed), daemon=True)
        writer.start()

        def stop_writer() -> None:
            frames.put(None)
            writer.join()

        last, pixels = None, b""  # a repeated frame is not drawn again
        try:
            for i, frame in enumerate(plan):
                if cancelled():
                    raise Cancelled()
                if failed:
                    raise BrokenPipeError
                if frame != last:
                    img = prep.renderer.render(*frame)  # keep img alive: constBits() is a view into it
                    last, pixels = frame, img.constBits().tobytes()
                frames.put(pixels)
                if i % job.fps == 0:
                    progress(i / len(plan))
            stop_writer()
            proc.stdin.close()
            if failed or proc.wait() != 0:
                raise BrokenPipeError
        except (BrokenPipeError, OSError):  # Windows raises OSError(EINVAL), not BrokenPipeError, when ffmpeg has died
            stop_writer()
            proc.wait()
            err.seek(0)
            part.unlink(missing_ok=True)
            raise FFmpegError(err.read().decode(errors="replace")[-2000:] or "ffmpeg failed")
        except BaseException:
            proc.kill()  # unblocks the writer if it is waiting on ffmpeg
            stop_writer()
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


def screens(prep: Prepared, at: float) -> list[State]:
    """One state per screen (each page of text, in the order they appear), `at` (0..1) of the way through the
    time it is shown. What is on screen only changes when a verse or a word starts, so only those moments are
    looked at: this stays quick for a whole surah."""
    end = prep.lead_ms + prep.audio_end_ms - prep.audio_start_ms
    moments = sorted({0, *(c.start for c in prep.clips), *(s.start for c in prep.clips for s in c.segs)})
    moments = [t for t in moments if 0 <= t < end]
    keys = [prep.renderer.page_key(state_at(prep.clips, t)) for t in moments]
    starts = [t for n, t in enumerate(moments) if n == 0 or keys[n] != keys[n - 1]]
    bounds = [*starts, end]
    return [state_at(prep.clips, a + at * (b - a)) for a, b in zip(bounds, bounds[1:])]


def export_pngs(job: ExportJob, client: QuranClient) -> list[Path]:
    """One still per screen (taken near the end of its time), on the theme background. For quick checks."""
    prep = prepare(job, client)
    bg = QColor(THEMES[job.theme].bg)
    job.out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for n, state in enumerate(screens(prep, at=0.9), 1):
        w, h = prep.size
        img = QImage(w, h, QImage.Format.Format_RGBA8888)
        img.fill(bg)
        p = QPainter(img)
        p.drawImage(0, 0, prep.renderer.render(state))
        p.end()
        path = job.out_dir / f"{Path(job.filename).stem}_p{n:03d}.png"
        img.save(str(path))
        paths.append(path)
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


def preview_image(job: ExportJob, client: QuranClient, screen: int = 0) -> tuple[QImage, int, int]:
    """Screen number `screen` (from 0, kept within range) as it will look in the video, a little before the
    middle of its time. Returns the image, the screen number shown, and how many screens there are.
    No audio download."""
    prep = prepare(replace(job, quality=DEFAULT_QUALITY), client, audio=False)  # always full size
    states = screens(prep, at=0.45)
    screen = min(max(screen, 0), len(states) - 1)
    state = states[screen]
    w, h = prep.size
    img = QImage(w, h, QImage.Format.Format_RGBA8888)
    img.fill(QColor(THEMES[job.theme].bg))
    p = QPainter(img)
    if job.background:
        p.drawImage(0, 0, background_image(job.background, w, h))
    p.drawImage(0, 0, prep.renderer.render(state))
    p.end()
    return img, screen, len(states)


# Average video bitrate (kb/s) by background and quality. High was measured on a 52 s export; the others follow
# the ratios measured on 13 s exports. Audio is separate. A background video depends on its footage, so its
# figures are only a rough guide.
VIDEO_KBPS = {
    "solid": {"Very high": 87, "High": 85, "Medium": 53, "Low": 33, "Very low": 19},
    "image": {"Very high": 283, "High": 230, "Medium": 118, "Low": 57, "Very low": 24},
    "video": {"Very high": 6600, "High": 4500, "Medium": 2100, "Low": 660, "Very low": 90},
}


# Seconds of work per second of video, measured on one machine (2:255-257, October 2026): a part that grows with
# the number of pixels (at full size), and for a background video, a fixed part for decoding it.
EXPORT_COST = {"solid": (0.0, 0.11), "image": (0.0, 0.155), "video": (0.04, 0.27)}


def _background_kind(background: Path | None) -> str:
    return "solid" if background is None else "image" if background.suffix.lower() in IMAGE_EXTS else "video"


def estimate_bytes(seconds: float, background: Path | None, quality: str = DEFAULT_QUALITY) -> int:
    kbps = QUALITIES[quality].audio_kbps + VIDEO_KBPS[_background_kind(background)][quality]
    return int(seconds * kbps * 1000 / 8)


def estimate_seconds(seconds: float, background: Path | None, quality: str = DEFAULT_QUALITY) -> float:
    """Rough export time, once the recitation is downloaded."""
    fixed, per_pixel = EXPORT_COST[_background_kind(background)]
    return 1 + seconds * (fixed + per_pixel * QUALITIES[quality].scale ** 2)


@dataclass
class VideoInfo:
    seconds: float  # length of the video
    basmala_ok: bool  # the Basmala option can be used with this reciter and range
    problem: DataError | None  # why this reciter can't be used for this range, if it can't
    bg_seconds: float | None  # length of the background video (None without one, or for an image)


def video_info(job: ExportJob, client: QuranClient) -> VideoInfo:
    """What the window shows before an export: length, Basmala availability, problems. Needs no audio."""
    _, timings = client.recitation(job.reciter.id, job.chapter)
    timings = timings[job.v_from - 1:job.v_to]
    problem = None
    try:
        check_timings(timings, job.reciter.name)
        verses = client.verses(job.chapter, FONTS[job.font].text_field, TRANSLATIONS[job.translation])
        check_translation(verses[job.v_from - 1:job.v_to], job.translation)
    except DataError as e:
        problem = e
    basmala_ok, lead_ms = False, 0
    if basmala_available(job.chapter, job.v_from):
        try:
            basmala = client.recitation(job.reciter.id, 1)[1][0]
            check_timings([basmala], job.reciter.name)
            basmala_ok, lead_ms = True, basmala.end - basmala.start
        except (DataError, ApiError):
            pass  # this reciter has no usable Basmala timing
    start_ms, end_ms = cut_range(timings)
    seconds = (end_ms - start_ms + (lead_ms if job.basmala and basmala_ok else 0)) / 1000
    bg_seconds = media_seconds(job.background) if is_video(job.background) else None
    return VideoInfo(seconds, basmala_ok, problem, bg_seconds)
