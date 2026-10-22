# Contributing

Thank you for helping. Bug reports, translations and code are all welcome. Please open an issue first for anything
larger than a small fix, so we can agree on it before you spend time.

## Set up

    git clone https://github.com/aksm26/quran-video-creator.git
    cd quran-video-creator
    python3 -m venv .venv
    .venv/bin/pip install -r requirements-dev.txt
    .venv/bin/python main.py

On Windows: `py -m venv .venv`, then `.venv\Scripts\pip` and `.venv\Scripts\python`. The README explains how the
code is organised ("How the code works").

## Check your change

    .venv/bin/python -m pytest -q tests
    QVC_API_BASE=https://qvc-proxy.quranvideocreator.workers.dev .venv/bin/python -m pytest -q tests
    node --test proxy/worker.test.mjs        # only if you touched proxy/

The second line also runs the live tests, which download real data through the proxy. Run it before you open a pull
request.

If your change should not alter the picture (a refactor, say), render stills before and after and compare them. The
files must be byte-identical:

    .venv/bin/python main.py cli 2 255 257 --png-only --surah-name --format all --out before
    # ...make the change...
    .venv/bin/python main.py cli 2 255 257 --png-only --surah-name --format all --out after
    diff -r before after

## Rules

- **The Quran text is shown exactly as the API returns it.** Never change, normalise, reorder or trim the Arabic.
  Only translations are cleaned (`clean_translation` in `api/client.py` removes footnote markers).
- **Credit Quran Foundation.** Every video gets a `.credits.txt` file and the credits go to the clipboard. Their
  terms require it, so keep it working.
- **Only redistributable assets.** A font, icon or data file must have a licence that allows redistribution (no
  "non-commercial only", no unknown licence). Put its licence file next to it and list it in `THIRD_PARTY.md`.
- **Every interface text is translated.** Write it in English, pass it through `tr()` (from `quran_video.i18n`),
  and add a translation to every file in `assets/locales/`. A test fails if one is missing or if a `{placeholder}`
  is lost. Keep interface texts short, and do not use em dashes in them.
- **No widgets in `core/`.** The command line uses `core/` without a window.
- **Generated files are not edited by hand.** `quran_video/config/translations.py` and `language_names.py` are
  rewritten by `tools/generate_language_data.py`.
- **Changed a default in the window?** Bump `SETTINGS_VERSION` in `ui/main_window.py`, so choices saved by an older
  version do not hide the new default.

## Common changes

**An interface language.** Add it to `LANGUAGES` in `quran_video/i18n.py`, with the Quran translation it should
pick by default and whether it is written right to left. Copy `assets/locales/fr.json` to `assets/locales/<code>.json`
and translate every value; the keys stay in English. Under `"reciters"` you may spell the reciters' names in the
language's own script (by reciter id). Then run `tools/generate_language_data.py` so every language name exists in
the new language, and update the language count in `tests/test_features.py`.

**A translation for an existing language.** Edit the value in `assets/locales/<code>.json`.

**A video theme.** One line in `BUILTIN` in `quran_video/config/themes.py`: a name, a background, a text and a
highlight colour. Add the name to every `assets/locales/*.json`; theme names are translated. A test checks that the
text is readable on the background.

**An output format.** One line in `FORMATS` and one in `FORMAT_NOTES` in `quran_video/config/presets.py`.

**A Quran font.** Put the file and its licence in `assets/fonts/`, add a `FontSpec` to `FONTS` in
`quran_video/config/fonts.py` with the API text field the font was made for, and list it in `THIRD_PARTY.md` and in
the About dialog (`quran_video/ui/about.py`).

**A stop sign.** Add a `Stop` to `STOPS` in `quran_video/config/stops.py`, with the character that marks it in each
mushaf style's text.

**The list of Quran translations.** `.venv/bin/pip install babel`, then `.venv/bin/python tools/generate_language_data.py`.
It rebuilds both generated files from live data, so review the diff. If the API has added a language, the tool stops
and names it: add its language code to `API_LANGUAGE_CODES` in the tool first.
