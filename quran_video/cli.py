"""Headless export: python -m quran_video.cli 112 1 4 --reciter 7 --format 9:16 --out out"""

import argparse
import logging
import os
import sys
from dataclasses import replace
from pathlib import Path

from .api.client import DEFAULT_RECITER, ApiError, QuranClient
from .config.fonts import FONTS
from .config.presets import DEFAULT_FORMAT, FORMATS
from .config.quality import QUALITIES
from .config.stops import STOPS
from .config.themes import THEMES
from .config.translations import TRANSLATIONS
from .core.export import ExportJob, credits_path, export, export_pngs
from .core.ffmpeg import FFmpegError
from .core.timing import DataError

def main(argv=None) -> int:
    # The defaults are ExportJob's own (ExportJob.fps and so on), so the command line and the code always agree.
    parser = argparse.ArgumentParser(description=__doc__)
    add = parser.add_argument
    add("chapter", type=int)
    add("v_from", type=int)
    add("v_to", type=int)
    add("--reciter", type=int, default=DEFAULT_RECITER, help="chapter-reciter id")
    add("--format", default=DEFAULT_FORMAT, choices=[*FORMATS, "all"])
    add("--out", type=Path, default=Path("out"))
    add("--fps", type=int, default=ExportJob.fps)
    add("--font", default=ExportJob.font, choices=list(FONTS))
    add("--theme", default=ExportJob.theme, choices=list(THEMES))
    add("--split", default=ExportJob.split, choices=["parts", "verse"],
        help="one part at a time, cut at the stop signs chosen by --stops, or the full verse")
    add("--stops", default=",".join(ExportJob.stops),
        help="comma-separated stop signs to cut at: lazim, mutlaq, qif, qila, jaiz, mujawwaz, sila "
             "(only those the font supports apply)")
    add("--highlight", default=ExportJob.highlight, choices=["none", "word", "keep"],
        help="none, word by word, or keep every recited word highlighted")
    add("--reveal", default=ExportJob.reveal, choices=["off", "build", "single"],
        help="off: all words shown; build: words appear as recited; single: one word at a time")
    add("--line-spacing", type=float, default=ExportJob.line_spacing, help="fraction of the font's natural line height")
    add("--no-arabic", action="store_true", help="leave out the Arabic text (needs a translation)")
    add("--surah-name", action="store_true", help="show the surah name on top")
    add("--translation", default=ExportJob.translation, choices=list(TRANSLATIONS), metavar="NAME",
        help='a name from quran_video/config/translations.py, e.g. "French (Muhammad Hamidullah)", or None')
    add("--overlay", type=float, default=ExportJob.overlay, help="dark overlay strength 0..1")
    add("--quality", default=ExportJob.quality, choices=list(QUALITIES), help="resolution, sharpness and audio bitrate")
    add("--text-width", type=float, default=ExportJob.text_width,
        help="share of the frame width the text may use (0.5 to 0.98)")
    add("--bg", type=Path, help="background image or video (scaled and cropped to cover)")
    add("--basmala", action="store_true",
        help="open with the Basmala in the reciter's own voice (only for ranges starting at verse 1, "
             "not in Al-Fatihah or At-Tawbah)")
    add("--no-highlight-fade", action="store_true", help="light each word at once instead of easing it in")
    add("--translation-width", type=float, default=ExportJob.translation_width,
        help="share of the frame width for the translation")
    add("--name-size", type=float, default=ExportJob.name_scale, help="surah name size, 1.0 = normal (0.5 to 2.0)")
    add("--bg-end", default=ExportJob.bg_end, choices=["loop", "freeze"],
        help="a background video shorter than the recitation: loop it or freeze its last frame")
    add("--png-only", action="store_true", help="write one still per page instead of a video")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QGuiApplication
    app = QGuiApplication(sys.argv[:1])  # noqa: F841 - fonts need an application object

    stops = tuple(x for x in args.stops.split(",") if x)
    if any(x not in STOPS for x in stops):
        parser.error(f"--stops must be a comma-separated list of: {', '.join(STOPS)}")
    client = QuranClient()
    chapters = {c.id: c for c in client.chapters()}
    if args.chapter not in chapters:
        parser.error("chapter must be 1..114")
    n = chapters[args.chapter].verses_count
    if not 1 <= args.v_from <= args.v_to <= n:
        parser.error(f"verse range must be within 1..{n}")
    reciter = next((r for r in client.reciters() if r.id == args.reciter), None)
    if reciter is None:
        parser.error(f"unknown reciter {args.reciter}")

    base = ExportJob(
        chapter=args.chapter, v_from=args.v_from, v_to=args.v_to, reciter=reciter, fmt="", out_dir=args.out,
        fps=args.fps, font=args.font, theme=args.theme, split=args.split, highlight=args.highlight,
        reveal=args.reveal, line_spacing=args.line_spacing, show_arabic=not args.no_arabic,
        surah_name=args.surah_name, translation=args.translation, overlay=args.overlay, quality=args.quality,
        text_width=args.text_width, translation_width=args.translation_width, name_scale=args.name_size,
        bg_end=args.bg_end, highlight_fade=not args.no_highlight_fade, background=args.bg, basmala=args.basmala,
        stops=stops)
    def show_download(done: int, total: int) -> None:
        amount = f"{done / total:.0%}" if total else f"{done // 1_000_000} MB"
        print(f"\rDownloading the recitation: {amount}", end="", flush=True)

    try:
        for fmt in (FORMATS if args.format == "all" else [args.format]):
            job = replace(base, fmt=fmt)
            if args.png_only:
                print(*export_pngs(job, client), sep="\n")
            else:
                # the spaces wipe out the longer download line
                path = export(job, client, progress=lambda f: print(f"\r{f:6.1%}" + " " * 30, end="", flush=True),
                              download=show_download, warn=lambda e: print(f"\nWarning: {e}", file=sys.stderr))
                print(f"\n{path}\nCredits for the caption (required by the Quran Foundation terms): "
                      f"{credits_path(path)}")
    except (DataError, ApiError, FFmpegError) as e:
        print(f"\nError: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
