# Privacy policy

Effective 15 October 2026. Applies to the Quran Video Creator desktop app and its API proxy.

## In short

Quran Video Creator collects no personal data. It has no account, no analytics, no ads and no tracking.

## What leaves your computer

- **Quran data.** The app downloads Quran text, translations, reciter lists and word timings from the Quran
  Foundation Content API, through a small proxy run by the app's maintainer on Cloudflare Workers (`proxy/` in the
  source). The proxy adds the app's API credentials and forwards the request. It keeps no logs.
  - It keeps a copy of Quran data answers for up to one day, so repeat requests are faster. These copies hold only
    Quran data, never who asked for it.
  - To stop abuse, it counts requests per IP address for one minute. The count is then discarded.
- **Recitation audio** comes straight from the Quran Foundation audio servers (quranicaudio.com).
- Like any web request, these requests carry your IP address and the User-Agent `QuranVideoCreator/<version>`.
  Cloudflare and Quran Foundation handle them under their own policies:
  [Quran Foundation privacy policy](https://api-docs.quran.foundation/legal/developer-privacy/),
  [Cloudflare privacy policy](https://www.cloudflare.com/privacypolicy/).

## What stays on your computer

- Downloads are cached for at most 7 days (in `.cache/quran-video` in your home folder), then deleted and fetched
  again when needed.
- Your settings and custom themes.
- Your videos, and the background images and videos you choose. They are never uploaded.

## Children

The app collects no data from anyone, children included.

## Changes

Changes to this policy are published in this file, with a new effective date. The history of this file shows every
change.

## Contact

Open an issue on the project's GitHub page: https://github.com/aksm26/quran-video-creator/issues
