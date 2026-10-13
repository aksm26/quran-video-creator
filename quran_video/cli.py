"""Headless export: python -m quran_video.cli 112 1 4 --reciter 7 --format 9:16 --out out"""

import argparse
import logging
import os
import sys
from dataclasses import replace
from pathlib import Path

from .api.client import ApiError, QuranClient
from .config.fonts import DEFAULT_FONT, FONTS
from .config.presets import FORMATS
from .config.quality import DEFAULT_QUALITY, QUALITIES
from .config.themes import DEFAULT_THEME, THEMES
from .config.translations import DEFAULT_TRANSLATION, TRANSLATIONS
from .core.export import ExportJob, credits_path, export, export_pngs
from .core.ffmpeg import FFmpegError
from .config.stops import DEFAULT_STOPS, STOPS
from .core.timing import DataError


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("chapter", type=int)
    ap.add_argument("v_from", type=int)
    ap.add_argument("v_to", type=int)
    ap.add_argument("--reciter", type=int, default=7, help="chapter-reciter id")
    ap.add_argument("--format", default="9:16", choices=[*FORMATS, "all"])
    ap.add_argument("--out", type=Path, default=Path("out"))
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--font", default=DEFAULT_FONT, choices=list(FONTS))
    ap.add_argument("--theme", default=DEFAULT_THEME, choices=list(THEMES))
    ap.add_argument("--split", default="parts", choices=["parts", "verse"],
                    help="one part at a time, cut at the stop signs chosen by --stops, or the full verse")
    ap.add_argument("--stops", default=",".join(DEFAULT_STOPS),
                    help="comma-separated stop signs to cut at: lazim, mutlaq, qif, qila, jaiz (only those the font supports apply)")
    ap.add_argument("--highlight", default="word", choices=["none", "word", "keep"],
                    help="none, word by word, or keep every recited word highlighted")
    ap.add_argument("--reveal", default="off", choices=["off", "build", "single"],
                    help="off: all words shown; build: words appear as recited; single: one word at a time")
    ap.add_argument("--line-spacing", type=float, default=0.8, help="fraction of the font's natural line height")
    ap.add_argument("--no-arabic", action="store_true", help="leave out the Arabic text (needs a translation)")
    ap.add_argument("--surah-name", action="store_true", help="show the surah name on top")
    ap.add_argument("--translation", default=DEFAULT_TRANSLATION, choices=list(TRANSLATIONS))
    ap.add_argument("--overlay", type=float, default=0.0, help="dark overlay strength 0..1")
    ap.add_argument("--quality", default=DEFAULT_QUALITY, choices=list(QUALITIES), help="resolution, sharpness and audio bitrate")
    ap.add_argument("--text-width", type=float, default=0.84, help="share of the frame width the text may use (0.5 to 0.98)")
    ap.add_argument("--bg", type=Path, help="background image or video (scaled and cropped to cover)")
    ap.add_argument("--basmala", action="store_true",
                    help="keep the recording's introduction before verse 1 and show the Basmala over it "
                         "(only for ranges starting at verse 1; the introduction may also contain the isti'adha)")
    ap.add_argument("--no-highlight-fade", action="store_true", help="light each word at once instead of easing it in")
    ap.add_argument("--translation-width", type=float, default=0.84, help="share of the frame width for the translation")
    ap.add_argument("--name-size", type=float, default=1.0, help="surah name size, 1.0 = normal (0.5 to 2.0)")
    ap.add_argument("--bg-end", default="loop", choices=["loop", "freeze"],
                    help="a background video shorter than the recitation: loop it or freeze its last frame")
    ap.add_argument("--png-only", action="store_true", help="write one still per page instead of a video")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QGuiApplication
    app = QGuiApplication(sys.argv[:1])  # noqa: F841 - needed for fonts

    stops = tuple(x for x in a.stops.split(",") if x)
    if any(x not in STOPS for x in stops):
        ap.error(f"--stops must be a comma-separated list of: {', '.join(STOPS)}")
    client = QuranClient()
    chapters = {c.id: c for c in client.chapters()}
    if a.chapter not in chapters:
        ap.error("chapter must be 1..114")
    n = chapters[a.chapter].verses_count
    if not 1 <= a.v_from <= a.v_to <= n:
        ap.error(f"verse range must be within 1..{n}")
    reciter = next((r for r in client.reciters() if r.id == a.reciter), None)
    if reciter is None:
        ap.error(f"unknown reciter {a.reciter}")

    base = ExportJob(
        chapter=a.chapter, v_from=a.v_from, v_to=a.v_to, reciter=reciter, fmt="", out_dir=a.out, fps=a.fps,
        font=a.font, theme=a.theme, split=a.split, highlight=a.highlight, reveal=a.reveal,
        line_spacing=a.line_spacing, show_arabic=not a.no_arabic, surah_name=a.surah_name,
        translation=a.translation, overlay=a.overlay, quality=a.quality, text_width=a.text_width, translation_width=a.translation_width,
        name_scale=a.name_size, bg_end=a.bg_end, highlight_fade=not a.no_highlight_fade, background=a.bg, basmala=a.basmala, stops=stops)
    try:
        for fmt in (FORMATS if a.format == "all" else [a.format]):
            job = replace(base, fmt=fmt)
            if a.png_only:
                print(*export_pngs(job, client), sep="\n")
            else:
                path = export(job, client, progress=lambda f: print(f"\r{f:6.1%}", end="", flush=True))
                print(f"\n{path}\nCredits for the caption (required by the Quran Foundation terms): {credits_path(path)}")
    except (DataError, ApiError, FFmpegError) as e:
        print(f"\nError: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
