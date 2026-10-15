# Quran Video Creator

Makes Quran recitation videos (9:16, 16:9, 1:1, 4:5) with the Arabic synced word by word to the reciter.
Free and open source (GPL-3.0).

## Download

Get the latest version from the **Releases** page of this repository:

| System | File | First start |
|---|---|---|
| Windows 10/11 (64-bit) | `QuranVideoCreator-windows-x64.zip` | Unzip, open `QuranVideoCreator.exe`. If Windows SmartScreen warns, click **More info** > **Run anyway** (the app is not code-signed). |
| macOS (Apple Silicon) | `QuranVideoCreator-macos-arm64.dmg` | Drag the app to Applications. The first time, right-click it > **Open** > **Open** (the app is not notarized). |
| Linux (x86-64) | `QuranVideoCreator-x86_64.AppImage` | `chmod +x QuranVideoCreator-x86_64.AppImage` and run it. |

The app needs internet: it downloads the text, translations and recitations from the Quran Foundation API.

## Credits and rights (please read)

- Every video is saved with a `.credits.txt` file next to it, and the credits are copied to your clipboard.
  **Put them in your video's caption or description.** Quran Foundation allows sharing the videos on social media,
  monetised channels included, when Quran Foundation is credited (Developer Terms 2.2).
- Selling or redistributing the Quran data itself needs a commercial licence from Quran Foundation.
- The Quran text is shown exactly as the API returns it.
- Privacy: the app collects nothing. See [PRIVACY.md](PRIVACY.md).
- Fonts, icons and FFmpeg keep their own licences: see [THIRD_PARTY.md](THIRD_PARTY.md).

## Run from source

    ./run.sh

The first run creates `.venv` and installs what it needs (Python 3.10+ and internet required).
On Linux, to add a menu entry, edit `Exec=` in `packaging/quran-video-creator.desktop` to point at `run.sh`, then
copy it to `~/.local/share/applications/`.

Command line, without the window:

    .venv/bin/python -m quran_video.cli 112 1 4 --reciter 7 --format 9:16 --out out
    .venv/bin/python -m quran_video.cli --help

The built app has the same command line: `QuranVideoCreator cli 112 1 4 ...`.

Videos are saved to the folder chosen in the app (default `~/Videos`). Downloads are cached for up to 7 days in
`~/.cache/quran-video`.

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

Proxy tests: `node --test proxy/worker.test.mjs`. Local run: put `QF_CLIENT_ID=...` and `QF_CLIENT_SECRET=...` in
`proxy/.dev.vars` (git-ignored) and run `npx wrangler dev`, then `QVC_API_BASE=http://localhost:8787`.

## Develop

    .venv/bin/pip install -r requirements-dev.txt
    .venv/bin/python -m pytest -q tests                     # tests (live ones run only when QVC_API_BASE is set)
    .venv/bin/pyinstaller packaging/quran_video.spec        # build dist/QuranVideoCreator for this OS
    packaging/build_appimage.sh                             # Linux: wrap it into an AppImage

## Release

Push a version tag. GitHub Actions runs the tests, builds Windows, macOS and Linux, and attaches them to a Release:

    git tag v1.0.0
    git push origin v1.0.0

Bump `__version__` in `quran_video/__init__.py` first.
