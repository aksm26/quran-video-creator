"""Manual mode's video: the scenes of core.manual drawn by auto mode's renderer, encoded by the same loop.

Each scene becomes one made-up Verse (the same trick as the Basmala in export.prepare) and one Clip, so
state_at, frame_plan and TextRenderer work on it unchanged."""

import math
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtGui import QColor, QImage, QPainter

from ..api.client import QuranClient
from ..api.models import Verse, Word
from ..config.fonts import FONTS
from ..config.presets import FORMATS
from ..config.quality import QUALITIES, scaled_size
from ..config.themes import THEMES
from ..config.translations import TRANSLATIONS
from .export import (QF_CREDIT, Frame, Prepared, background_image, credits_path, encode, frame_plan,
                     scaled_background, screens)
from .ffmpeg import Layer, build_manual_cmd, ffmpeg_exe, has_audio, media_seconds
from .manual import (ManualJob, Scene, VersesOf, background_layers, check, compile_scenes, file_end,
                     verse_list)
from .render import HIGHLIGHT_NONE, SPLIT_VERSE, RenderOptions, TextRenderer
from .timing import Clip, DataError


def verse_source(client: QuranClient, font: str, translation: str) -> VersesOf:
    """client.verses for each surah asked for, with the font's text and the translation (cached by the client
    on disk, and here for this job)."""
    field, translation_id, seen = FONTS[font].text_field, TRANSLATIONS.get(translation), {}

    def verses_of(chapter: int) -> list[Verse]:
        if chapter not in seen:
            seen[chapter] = client.verses(chapter, field, translation_id) if 1 <= chapter <= 114 else []
        return seen[chapter]
    return verses_of


def has_background(job: ManualJob) -> bool:
    return job.background is not None or any(b.background for b in job.batches)


def render_options(job: ManualJob, chapter: int) -> RenderOptions:
    """The batch is the screen: no cutting at stop signs, and a translation range is shown whole (a long one is
    already cut into timed pieces). Pictures are dimmed by ffmpeg, so the theme colour never is."""
    theme = THEMES[job.theme]
    return RenderOptions(theme, split=SPLIT_VERSE, highlight=job.highlight, reveal=job.reveal,
                         line_spacing=job.line_spacing, chapter=chapter if job.surah_name else 0,
                         translation=job.uses_translation, overlay=0.0, text_width=job.text_width,
                         translation_width=job.translation_width, name_scale=job.name_scale,
                         fill=None if has_background(job) else theme.bg, share_translation=False)


def prepare_manual(job: ManualJob, verses_of: VersesOf, audio_ms: int,
                   size: tuple[int, int] | None = None) -> tuple[Prepared, list[Scene]]:
    """Everything the frame loop needs, like export.prepare. `audio_ms` is the length of the recording;
    `size` overrides the output size (the live preview draws small)."""
    font = FONTS[job.font]
    w, h = size or scaled_size(*FORMATS[job.fmt], QUALITIES[job.quality].scale)
    probe = TextRenderer(w, h, [], font, render_options(job, 1))
    scenes = compile_scenes(job, verses_of, probe.translation_fits, audio_ms)
    verses = [Verse(f"manual{i}", 0, tuple(Word(n + 1, c.text, False) for n, c in enumerate(s.cells)),
                    s.translation) for i, s in enumerate(scenes)]
    signs = [frozenset(n for n, c in enumerate(s.cells) if c.sign) for s in scenes]
    chapter = next((s.chapter for s in scenes if s.chapter), 1)
    renderer = TextRenderer(w, h, verses, font, render_options(job, chapter), signs,
                            [s.chapter for s in scenes] if job.surah_name else None)
    clips = [Clip(i, s.start, s.end, s.segs) for i, s in enumerate(scenes)]
    warning = None
    if job.highlight != HIGHLIGHT_NONE and any(not b.word_ms or None in b.word_ms for b in job.batches):
        warning = DataError("Tap the words in Set times for exact highlighting.")
    return Prepared(renderer, clips, job.audio, job.trim_start_ms, file_end(job, audio_ms), (w, h),
                    warning=warning), scenes


def audio_length(job: ManualJob) -> int:
    """Checks the job (DataError if it can't be made) and returns the recording's length in ms."""
    ok = job.audio is not None and job.audio.is_file()
    seconds = media_seconds(job.audio) if ok else None
    check(job, seconds, ok and has_audio(job.audio))
    return int(seconds * 1000)


def manual_credits(job: ManualJob) -> str:
    """Caption credits: the Quran Foundation line is required, the reciter is named when the user gave a name."""
    lines = [f"Recitation: {job.reciter_name.strip()}"] if job.reciter_name.strip() else []
    if job.uses_translation:
        lines.append(f"Translation: {job.translation}")
    if job.batches:
        lines.append(f"Verses: {verse_list(job.batches)}")
    return "\n".join(lines + [QF_CREDIT]) + "\n"


def export_manual(job: ManualJob, client: QuranClient, progress: Callable[[float], None] = lambda f: None,
                  cancelled: Callable[[], bool] = lambda: False,
                  warn: Callable[[DataError], None] = lambda e: None) -> Path:
    """Write the video and its .credits.txt, and return its path. Like export.export."""
    audio_ms = audio_length(job)
    prep, _ = prepare_manual(job, verse_source(client, job.font, job.translation), audio_ms)
    if prep.warning:
        warn(prep.warning)
    w, h = prep.size
    q = QUALITIES[job.quality]
    job.out_dir.mkdir(parents=True, exist_ok=True)
    out = job.out_dir / job.filename
    plan = frame_plan(prep, job.fps, hl_fade=job.highlight_fade and job.highlight != HIGHLIGHT_NONE)
    layers = background_layers(job, audio_ms)

    def cmd_for(tmpdir: Path, part: Path) -> list[str]:
        base = scaled_background(job.background, w, h, tmpdir) if job.background is not None else None
        scaled: dict[Path, Path] = {}
        for n, (path, _, _) in enumerate(layers):
            if path not in scaled:
                scaled[path] = scaled_background(path, w, h, tmpdir, f"layer{n}.png")
        return build_manual_cmd(ffmpeg_exe(), w, h, job.fps, job.audio, prep.audio_start_ms,
                                prep.audio_end_ms - prep.audio_start_ms, part, base, THEMES[job.theme].bg,
                                [Layer(scaled[p], a, z) for p, a, z in layers], dim=job.overlay, crf=q.crf,
                                audio_kbps=q.audio_kbps, freeze=job.bg_end == "freeze")

    encode(cmd_for, plan, prep.renderer.render, out, job.fps, progress, cancelled)
    note = f"\nNote (not for the caption): {prep.warning}\n" if prep.warning else ""
    credits_path(out).write_text(manual_credits(job) + note, "utf-8")
    progress(1.0)
    return out


def manual_pngs(job: ManualJob, client: QuranClient) -> list[Path]:
    """One still per screen with text on it, on the theme colour, like export.export_pngs."""
    prep, scenes = prepare_manual(job, verse_source(client, job.font, job.translation), audio_length(job))
    job.out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for state in screens(prep, at=0.9):
        scene = scenes[state.verse]
        if not scene.cells and not scene.translation:
            continue
        w, h = prep.size
        img = QImage(w, h, QImage.Format.Format_RGBA8888)
        img.fill(QColor(THEMES[job.theme].bg))
        p = QPainter(img)
        p.drawImage(0, 0, prep.renderer.render(state))
        p.end()
        path = job.out_dir / f"{Path(job.filename).stem}_p{len(paths) + 1:03d}.png"
        img.save(str(path))
        paths.append(path)
    return paths


PREVIEW_FPS = 15


@dataclass
class ManualPreview:
    """What the timing window shows while the recording plays: a small frame for any moment, with the picture
    behind each scene (already dimmed), so it looks the way the video will."""
    prep: Prepared
    scenes: list[Scene]
    plan: list[Frame]
    pictures: list[QImage | None]  # per scene: the background behind it; None: the theme colour
    color: str

    @classmethod
    def build(cls, job: ManualJob, verses_of: VersesOf, audio_ms: int, width: int) -> "ManualPreview":
        fw, fh = FORMATS[job.fmt]
        size = (width, round(width * fh / fw))
        prep, scenes = prepare_manual(job, verses_of, audio_ms, size)
        layers = background_layers(job, audio_ms)
        stills: dict[Path, QImage] = {}

        def still(path: Path) -> QImage:
            if path not in stills:
                img = background_image(path, *size)
                if job.overlay > 0:
                    p = QPainter(img)
                    p.fillRect(img.rect(), QColor(0, 0, 0, int(255 * job.overlay)))
                    p.end()
                stills[path] = img
            return stills[path]

        pictures = []
        for s in scenes:
            path = next((p for p, a, z in layers if a <= s.start < z), job.background)
            try:
                pictures.append(still(path) if path is not None else None)
            except Exception:  # an unreadable picture is shown as the theme colour; the export says why
                pictures.append(None)
        plan = frame_plan(prep, PREVIEW_FPS, hl_fade=job.highlight_fade and job.highlight != HIGHLIGHT_NONE)
        return cls(prep, scenes, plan, pictures, THEMES[job.theme].bg)

    @property
    def start_ms(self) -> int:
        return self.prep.audio_start_ms

    def scene_at(self, file_ms: int) -> int:
        t = file_ms - self.start_ms
        return next((i for i, s in enumerate(self.scenes) if s.start <= t < s.end), len(self.scenes) - 1)

    def frame(self, file_ms: int) -> QImage:
        """The video as it looks at this moment of the recording (ms in the file)."""
        i = min(max(math.floor((file_ms - self.start_ms) * PREVIEW_FPS / 1000), 0), len(self.plan) - 1)
        w, h = self.prep.size
        img = QImage(w, h, QImage.Format.Format_RGBA8888)
        img.fill(QColor(self.color))
        p = QPainter(img)
        if self.plan:
            frame = self.plan[i]
            picture = self.pictures[frame.state.verse]
            if picture is not None:
                p.drawImage(0, 0, picture)
            p.drawImage(0, 0, self.prep.renderer.render(*frame))
        p.end()
        return img
