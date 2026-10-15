# Third-party components

The app's own code is GPL-3.0 (`LICENSE`). The items below keep their own licences. Anything not listed here was
written for this project.

## Fonts (`assets/fonts/`)

| File | Font | Licence | Licence file |
|---|---|---|---|
| `QPCHafs.ttf` | KFGQPC HAFS Uthmanic Script, King Fahd Glorious Quran Printing Complex | KFGQPC EULA: free to use, copy and distribute; must not be sold or modified | `KFGQPC-EULA.txt` |
| `AmiriQuran.ttf`, `Amiri-Regular.ttf` | Amiri, The Amiri Project Authors | SIL OFL 1.1 | `OFL.txt` |
| `DigitalKhattV1.otf`, `DigitalKhattV2.otf` | DigitalKhatt, Amine Anane and Tarteel Inc. | SIL OFL 1.1 | `OFL-DigitalKhatt.txt` |
| `Figtree-Regular.ttf` | Figtree, The Figtree Project Authors | SIL OFL 1.1 | `OFL-Figtree.txt` |
| `SurahNameV2.ttf` | Surah Name V2 (QUL, qul.tarteel.ai), downloaded from [quranfonts.com](https://quranfonts.com/font/surah-name-v2/) | **No licence published.** quranfonts.com offers it as a free download and says "All fonts belong to their respective creators". Kept at the maintainer's choice; it will be removed if the owner asks | none |

The fonts are not covered by the GPL. Do not sell them or modify `QPCHafs.ttf`.

## Icons (`assets/ui/`)

| File | Source | Licence |
|---|---|---|
| `icons/translate.svg` | [Bootstrap Icons](https://icons.getbootstrap.com) | MIT (`icons/LICENSE-bootstrap-icons.txt`) |
| `app.svg`, `app.png`, `check*.svg`, `down.svg` | Made for this project | GPL-3.0 |

## Data

| What | Source | Licence |
|---|---|---|
| Language names in `quran_video/config/language_names.py` | [Unicode CLDR](https://cldr.unicode.org), generated with Babel | Unicode License v3 (`quran_video/config/LICENSE-CLDR.txt`) |
| Translation list in `quran_video/config/translations.py` | Names and ids of Quran.com translations (no translation text) | Facts listed for lookup |
| Quran text, translations, word timings, recitation audio | Downloaded at run time from the Quran Foundation Content API (through the app's proxy) and quranicaudio.com; never shipped with the app | [Quran Foundation Developer Terms](https://api-docs.quran.foundation/legal/developer-terms/). Videos must credit Quran Foundation (the app writes a `.credits.txt` per video); monetised social-media videos are allowed (QF confirmed, October 2026). Selling or redistributing the data itself needs a QF commercial licence |

## Libraries bundled in the built app

| Library | Licence | Notes |
|---|---|---|
| [PySide6 / Qt](https://www.qt.io/qt-for-python) | LGPL-3.0 (text in `assets/LICENSE-LGPL-3.0.txt`) | The app is built as a folder (not one file), so the Qt libraries can be swapped |
| [requests](https://requests.readthedocs.io) (+ urllib3, idna, certifi, charset-normalizer) | Apache-2.0 / MIT / BSD / MPL-2.0 | |
| [imageio-ffmpeg](https://github.com/imageio/imageio-ffmpeg) | BSD-2-Clause | |
| FFmpeg 7.0.2 static build by [John Van Sickle](https://johnvansickle.com/ffmpeg/) (Linux) and the imageio-ffmpeg builds for Windows and macOS | **GPL-3.0** (built with `--enable-gpl --enable-version3`, libx264, libx265) | Source: [ffmpeg.org/releases](https://ffmpeg.org/releases/) (the version shown by `ffmpeg -version` in the app folder). This is why the whole app is GPL-3.0 |
| Python | PSF License | |
