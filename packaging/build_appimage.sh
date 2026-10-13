#!/usr/bin/env bash
# Wraps dist/QuranVideoCreator (from pyinstaller) into dist/QuranVideoCreator-x86_64.AppImage. Run from the repo root.
set -euo pipefail
APPDIR=build/AppDir
rm -rf "$APPDIR" && mkdir -p "$APPDIR"
cp -r dist/QuranVideoCreator "$APPDIR/"
cp packaging/quran-video-creator.desktop "$APPDIR/"
cp assets/ui/app.png "$APPDIR/quran-video-creator.png"
printf '#!/bin/sh\nexec "$(dirname "$(readlink -f "$0")")/QuranVideoCreator/QuranVideoCreator" "$@"\n' > "$APPDIR/AppRun"
chmod +x "$APPDIR/AppRun"
TOOL=build/appimagetool
[ -x "$TOOL" ] || { curl -sfL -o "$TOOL" https://github.com/AppImage/appimagetool/releases/download/1.9.0/appimagetool-x86_64.AppImage; chmod +x "$TOOL"; }
ARCH=x86_64 "$TOOL" --appimage-extract-and-run "$APPDIR" dist/QuranVideoCreator-x86_64.AppImage
