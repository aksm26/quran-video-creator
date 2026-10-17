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
OUT=dist/QuranVideoCreator-x86_64.AppImage
# Update information: AppImageUpdate, AppImageLauncher and Gear Lever find newer releases here and download only the
# changed blocks, using the .zsync file attached next to it (appimagetool needs zsyncmake, from the zsync package).
UPDATE="gh-releases-zsync|aksm26|quran-video-creator|latest|QuranVideoCreator-x86_64.AppImage.zsync"
ARCH=x86_64 "$TOOL" --appimage-extract-and-run -u "$UPDATE" "$APPDIR" "$OUT"
# appimagetool writes the .zsync into the current folder; fail here rather than ship an AppImage that can't update
mv QuranVideoCreator-x86_64.AppImage.zsync dist/ || { echo "no .zsync: install zsync (zsyncmake)" >&2; exit 1; }
