# Changelog

## 1.1.2 (18 October 2026)

- Word highlighting follows the voice for reciters whose word timing doesn't match their audio file:
  - Yasser ad-Dussary: on many surahs every word was highlighted 3 to 7 seconds late. On some (Al-Baqarah,
    Ghafir) the app could not line it up at all and warned that the highlight may be out of step.
  - Hani ar-Rifai and Abdul Basit Abdul Samad: on some surahs, part of the surah was up to 1.5 seconds off.
- The app now checks the timing against the audio for every export, and moves a verse only when the audio clearly
  shows where it is. Reciters whose timing already matches are left exactly as they were.

## 1.1.1 (17 October 2026)

- When the word highlight may be out of step (see 1.1.0), the video's `.credits.txt` ends with a note saying so.
  The caption copied to the clipboard stays the credits only.

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
