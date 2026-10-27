# Changelog

## 2.0.0 (27 October 2026)

- New **Manual mode** tab: make a video from your own recitation (an audio file, or the sound of a video).
  - Five steps on the left: Recording, Batches, Translation, Look and Output.
  - Pick batches of words on a mushaf page: Add new batch, then a first word and a last word, across verses,
    from anywhere in the Quran and in any order. Each batch is a card in a scrolling list, showing its first words;
    the page only changes the batch whose card is chosen.
  - Translations go with each batch, or have their own times.
  - One background for the video, or a picture or video for each batch.
  - **Set times** plays the recording: S starts the next batch, E ends one, W lights each word (with Highlight
    on). Checkpoints can be dragged on the bar, Ctrl+Z undoes, the start and end of the recording can be
    trimmed, and the preview shows the video as it plays.
  - A **Preview** view next to the mushaf shows the video as it will look, one screen at a time, even before the
    times are set.
  - If the recording can't be found or has no sound, the Recording step says so.
  - Projects are kept between runs and can be saved as `.qvc` files, which `cli manual` exports headless.
- A verse too tall for the screen even at the smallest size now shows every line over several screens.
- New dependency: PySide6-Addons, for Qt Multimedia (playing the recording). Without it, times can still be set,
  without sound.

## 1.3.0 (22 October 2026)

- New app icon, with clean transparent corners.
- Cleaner file and bundle names on every system: `QVC.AppImage` on Linux, `QVC-Windows.zip` on Windows and
  `QVC-macOS.dmg` on macOS (the app inside is `QVC` / `QVC.exe` / `QVC.app`). Saved settings and custom themes are
  kept. If you already have the Linux AppImage, download the new `QVC.AppImage` once; the old file's built-in
  updater only knows the old name.

## 1.2.1 (19 October 2026)

- The ⓘ info icons now open their explanation when clicked (before, nothing happened on a click and the hover text
  disappeared after a few seconds). They can also be reached with the keyboard.
- The info icon (Bootstrap Icons, MIT) is listed in `THIRD_PARTY.md` with the other icons.

## 1.2.0 (19 October 2026)

- The first word of a verse no longer lights up in the silence before it is recited, and the last word stays lit
  until the reciter stops holding it. Most noticeable for Muhammad Siddiq al-Minshawi, Mahmoud Khaleel Al-Husary
  and Abdul Basit Abdul Samad, whose first words lit up about half a second early.
- New choice under Recitation: the next verse appears when the verse ends (as before) or as soon as the last word
  ends. The ⓘ next to it explains that the timings can contain errors. Also `--verse-change` on the command line.
  This choice (and the credits note below) is in English in every app language until it is translated.
- The verse number always stays on the line of the verse's last word; before, it sometimes wrapped onto a line of
  its own.
- When a verse is too long for one screen, each screen shows the translation of its own words, instead of the
  whole translation repeated. Translations are never cut inside a [bracketed] insertion.
- New app icon.
- An ⓘ next to Export says the Quran Foundation credits (the `.credits.txt` file saved with each video) must be
  put in the post's description.

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
