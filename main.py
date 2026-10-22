"""Starts Quran Video Creator: the window, or with `cli` as the first argument, the command line."""

import sys

if __name__ == "__main__":
    if sys.argv[1:2] == ["cli"]:  # the built app has no python: `QVC cli 112 1 4` runs the command line
        from quran_video.cli import main
        sys.exit(main(sys.argv[2:]))
    from quran_video.ui.main_window import run
    sys.exit(run())
