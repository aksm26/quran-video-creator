<div align="center">

# Quran Video Creator

**Make Quran recitation videos for Reels, Shorts, TikTok and YouTube in a few clicks.**<br>
For any suggestions, bugs found, and other, please e-mail the following address: simplelogin-newsletter.equinox919@simplelogin.com
The Arabic lights up word by word with the reciter, with a translation under it. Free, no account, no watermark.

<a href="https://github.com/aksm26/quran-video-creator/releases/latest/download/QuranVideoCreator-windows-x64.zip"><img alt="Download for Windows" src="https://img.shields.io/badge/Download-Windows-0078D4?style=for-the-badge&logo=windows&logoColor=white" height="44"></a>
<a href="https://github.com/aksm26/quran-video-creator/releases/latest/download/QuranVideoCreator-macos-arm64.dmg"><img alt="Download for macOS" src="https://img.shields.io/badge/Download-macOS-111111?style=for-the-badge&logo=apple&logoColor=white" height="44"></a>
<a href="https://github.com/aksm26/quran-video-creator/releases/latest/download/QuranVideoCreator-x86_64.AppImage"><img alt="Download for Linux" src="https://img.shields.io/badge/Download-Linux-E95420?style=for-the-badge&logo=linux&logoColor=white" height="44"></a>

<img src="docs/examples/al-ikhlas-9x16.gif" height="300" alt="Al-Ikhlas, 9:16 video with word-by-word highlight">&nbsp;
<img src="docs/examples/al-kawthar-1x1-french.gif" height="300" alt="Al-Kawthar, square video with a French translation">

</div>

## Get started in 3 steps

1. **Download** the file for your computer with a button above.
2. **Open it** (first time only, because the app is free and not code-signed):
   - **Windows:** unzip the file, then open `QuranVideoCreator.exe`. If a blue "Windows protected your PC" box
     appears, click **More info**, then **Run anyway**.
   - **macOS** (Apple Silicon: M1 or newer): open the `.dmg` and drag the app onto **Applications**. Open it once;
     when macOS refuses, go to **System Settings** > **Privacy & Security**, scroll down and click **Open Anyway**.
   - **Linux:** right-click the file > **Properties** > allow running as a program (or
     `chmod +x QuranVideoCreator-x86_64.AppImage`), then double-click it.
3. **Make a video:** pick a reciter, a surah and the verses, then click **Export**. The video lands in your
   **Videos** folder, ready to upload.

Nothing else to install. The app needs internet to download the Quran text, translations and recitations.
All downloads: [Releases page](https://github.com/aksm26/quran-video-creator/releases/latest).

## What's new in 1.1

- **Update notice.** The app tells you when a new version is out, with a button to the download page. It never
  installs anything by itself, and you can turn the check off under **About**. On Linux, AppImage tools such as
  AppImageLauncher or Gear Lever can now update the app in place.
- **More reciters work with word-by-word highlight.** When a reciter's word timing doesn't match their audio for a
  surah, the video is still made, with a warning that the highlight may be out of step (no warning when highlight
  is off). Before, the export stopped.

All changes: [CHANGELOG](CHANGELOG.md).

## What it makes

Every video below was exported by the app as is (click for the full video with sound).

| [Al-Ikhlas, 9:16](docs/examples/al-ikhlas-9x16.mp4) | [Al-Fatihah, 16:9](docs/examples/al-fatihah-16x9.mp4) | [Al-Kawthar, 1:1, French](docs/examples/al-kawthar-1x1-french.mp4) |
|---|---|---|
| [<img src="docs/examples/al-ikhlas-9x16.gif" width="160" alt="Al-Ikhlas">](docs/examples/al-ikhlas-9x16.mp4) | [<img src="docs/examples/al-fatihah-16x9.gif" width="320" alt="Al-Fatihah">](docs/examples/al-fatihah-16x9.mp4) | [<img src="docs/examples/al-kawthar-1x1-french.gif" width="220" alt="Al-Kawthar">](docs/examples/al-kawthar-1x1-french.mp4) |

<sub>Recitation: Mishari Rashid al-`Afasy. Translations: English (Saheeh International), French (Muhammad Hamidullah).
Quran data provided by Quran.Foundation (https://quran.foundation).</sub>

- Formats: 9:16 (Reels, Shorts, TikTok), 16:9 (YouTube), 1:1 and 4:5 (feed posts), or all at once
- 20 reciters and 144 translations in 80 languages, or Arabic only
- Highlight word by word, or let the words appear as they are recited
- Several Quran fonts, colour themes, your own image or video as background
- Cuts long verses at the stop signs, so each screen stays readable
- The interface speaks 18 languages, Arabic and Urdu right to left

<img src="docs/screenshot.png" alt="The app window: settings on the left, live preview on the right" width="820">

## Credits and rights (please read)

- Every video is saved with a `.credits.txt` file next to it, and the credits are copied to your clipboard.
  **Put them in your video's caption or description.** Quran Foundation allows sharing the videos on social media,
  monetised channels included, when Quran Foundation is credited (Developer Terms 2.2).
- Selling or redistributing the Quran data itself needs a commercial licence from Quran Foundation.
- The Quran text is shown exactly as the API returns it.
- Privacy: the app collects nothing. See the [privacy policy](PRIVACY.md) and the [terms of service](TERMS.md).
- Fonts, icons and FFmpeg keep their own licences: see [THIRD_PARTY.md](THIRD_PARTY.md).

## Run from source

You need [Python](https://www.python.org/downloads/) 3.10 or newer, [Git](https://git-scm.com/downloads) and
internet. FFmpeg comes with the Python packages, so there is nothing else to install.

    git clone https://github.com/aksm26/quran-video-creator.git
    cd quran-video-creator

Then start it:

| System | Command |
|---|---|
| Linux, macOS | `./run.sh` |
| Windows | `run.bat` (or double-click it) |

The first start creates a virtual environment in `.venv` and installs the packages from `requirements.txt`, which
takes a minute. Later starts are quick.

On Linux, if the window does not open and the error mentions the Qt "xcb" plugin, install one system library:
`sudo apt install libxcb-cursor0` (Debian, Ubuntu) or `sudo dnf install xcb-util-cursor` (Fedora).

To add a Linux menu entry, edit `Exec=` in `packaging/quran-video-creator.desktop` to point at `run.sh`, then copy
it to `~/.local/share/applications/`.

Videos are saved to the folder chosen in the app (default `~/Videos`). Downloads are cached for up to 7 days in
`~/.cache/quran-video`.

### Command line

The same exports work without the window:

    .venv/bin/python main.py cli 112 1 4 --reciter 7 --format 9:16 --out out
    .venv/bin/python main.py cli --help

On Windows, use `.venv\Scripts\python` instead of `.venv/bin/python`. The built app has the same command line:
`QuranVideoCreator cli 112 1 4 ...` (on macOS: `QuranVideoCreator.app/Contents/MacOS/QuranVideoCreator cli ...`).
The Windows build exports but prints nothing, so use the source install there to see help and progress.

## How the code works

A video is made in four steps. Each step lives in its own module, and nothing under `core/` knows about the window:

    api/client.py      1. download the verses, translation, word timings and audio (cached for 7 days)
    core/timing.py     2. clean the word timings, and say which word is being recited at any moment
    core/layout.py     3. fit the words into lines, and draw the text of one frame
    core/render.py        (the Arabic, its translation and the surah name)
    core/export.py     4. plan every frame (fades, highlights), stream the frames into ffmpeg with the audio
    core/ffmpeg.py        and write the MP4 and its .credits.txt

The window (`ui/main_window.py`) and the command line (`cli.py`) both turn the user's choices into an `ExportJob`
(in `core/export.py`) and hand it to `export()`.

    main.py              starts the window, or the command line with `main.py cli ...`
    quran_video/
      api/               the Quran Foundation API client and the records it returns
      core/              everything that makes the video: timing, layout, drawing, ffmpeg
      config/            fixed choices: fonts, themes, formats, quality presets, stop signs, translation list
      ui/                the PySide6 window, its dialogs, widgets and stylesheet
      i18n.py            interface languages (the texts are in assets/locales/<language>.json)
      cli.py             the command line
    assets/              fonts, icons and interface translations
    proxy/               the Cloudflare Worker that holds the API secret (see below)
    packaging/           PyInstaller spec, AppImage script, Linux menu entry
    tools/               regenerates the translation list and the language names
    tests/               pytest

## Develop

    .venv/bin/pip install -r requirements-dev.txt
    .venv/bin/python -m pytest -q tests                     # offline tests
    QVC_API_BASE=https://qvc-proxy.quranvideocreator.workers.dev .venv/bin/python -m pytest -q tests   # all tests
    node --test proxy/worker.test.mjs                       # proxy tests (Node.js 18+)
    .venv/bin/pyinstaller packaging/quran_video.spec        # build dist/QuranVideoCreator for this OS
    packaging/build_appimage.sh                             # Linux: wrap it into an AppImage

The live tests (marked `slow_network`) talk to the real API through the proxy, so they only run when `QVC_API_BASE`
is set. See [CONTRIBUTING.md](CONTRIBUTING.md) for the project's rules and how to add a language, theme, font or
format.

## Run your own API proxy

Quran Foundation requires API credentials, and the client secret must not ship inside the app. So the app talks to a
tiny proxy (`proxy/worker.js`, a Cloudflare Worker) that holds the secret and forwards only the calls the app makes.
Release builds point at the maintainer's proxy. To run your own (for a fork, or to develop):

1. Register a **Backend/server** app at https://dev-console.quran.foundation/projects/new and note its client id and
   secret (pre-production credentials only see surahs 1 and 2; request production access for the rest).
2. In `proxy/` (needs Node.js and a free Cloudflare account):

       npx wrangler login
       npx wrangler secret put QF_CLIENT_ID
       npx wrangler secret put QF_CLIENT_SECRET
       npx wrangler deploy

   For pre-production credentials, switch the two URLs in `proxy/wrangler.toml` first.
3. Point the app at it: `export QVC_API_BASE=https://qvc-proxy.<your-subdomain>.workers.dev`.

Local run: put `QF_CLIENT_ID=...` and `QF_CLIENT_SECRET=...` in `proxy/.dev.vars` (git-ignored) and run
`npx wrangler dev`, then `QVC_API_BASE=http://localhost:8787`.

## Release

Bump `__version__` in `quran_video/__init__.py`, then push a version tag. GitHub Actions runs the tests, builds
Windows, macOS and Linux, and attaches them to a Release:

    git tag v1.0.0
    git push origin v1.0.0
