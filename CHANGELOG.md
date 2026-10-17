# Changelog

## 1.1.0 (17 October 2026)

- The app checks GitHub at start for a newer release and shows an **Update available** button that opens its
  download page. It never downloads or installs anything by itself. Turn it off under **About** (see
  [PRIVACY.md](PRIVACY.md)). Running from source never checks.
- The Linux AppImage carries update information, and each release has a `.zsync` file next to it, so
  AppImageUpdate, AppImageLauncher and Gear Lever can update it in place, downloading only what changed.
- A reciter whose word timing doesn't match the audio of a surah no longer stops the export. The app still tries
  to line the timing up with the audio; when it can't, the video is made with the timing as it is and, when word
  highlight is on, the app (and the command line) warns that the highlight may be out of step.

## 1.0.0 (15 October 2026)

First release.
