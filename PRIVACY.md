# Privacy policy and terms of use

## Privacy

Quran Video Creator collects no personal data. It has no account, no analytics and no tracking.

- The app downloads Quran text, translations, reciter lists and word timings from the Quran Foundation Content API
  through a small proxy run by the app's maintainer on Cloudflare Workers (`proxy/` in the source). The proxy only
  adds the app's API credentials and forwards the request; it stores and logs nothing. Recitation audio comes
  straight from the Quran Foundation audio servers (quranicaudio.com). These requests carry your IP address and
  the User-Agent `QuranVideoCreator/<version>`, like any web request. See the
  [Quran Foundation privacy policy](https://api-docs.quran.foundation/legal/developer-privacy/) and the
  [Cloudflare privacy policy](https://www.cloudflare.com/privacypolicy/).
- Downloads are cached on your computer for at most 7 days (in `.cache/quran-video` in your home folder) and are then
  fetched again.
- Your settings and custom themes are stored only on your computer.
- Videos, background images and background videos you choose never leave your computer.

## Terms of use

- The app is free software under the GNU GPL v3 (see `LICENSE`). It comes with no warranty.
- The Quran text is shown exactly as the API returns it. Do not edit it.
- Every exported video comes with a `.credits.txt` file. Put those credits in your video's caption or description.
  Quran Foundation confirmed (October 2026) that sharing these videos on social media, including monetised channels,
  is permitted end-user use under section 2.2 of their
  [Developer Terms](https://api-docs.quran.foundation/legal/developer-terms/), as long as Quran Foundation is
  credited in the video, caption or credits.
- Selling or redistributing the Quran data itself (text, translations, timings, audio files) needs a separate
  commercial licence from Quran Foundation.
