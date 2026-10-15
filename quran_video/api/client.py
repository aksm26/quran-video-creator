"""Quran Foundation Content API (v4) client. It goes through the project's proxy and keeps an on-disk cache.

Nothing is cached longer than a week (Quran Foundation Developer Terms)."""

import hashlib
import json
import os
import re
import threading
import time
from collections.abc import Callable
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .. import __version__
from .models import Chapter, Reciter, Verse, VerseTiming, Word

# The proxy (proxy/worker.js) holds the Quran Foundation client secret; the app never does (QF requirement).
# QVC_API_BASE points a fork or self-hoster at their own proxy.
BASE = os.environ.get("QVC_API_BASE", "https://qvc-proxy.quranvideocreator.workers.dev").rstrip("/")
MAX_AGE = 7 * 86400  # QF terms: no API content or audio may be cached longer than one week
DEFAULT_CACHE = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "quran-video"


DEFAULT_RECITER = 7  # Mishary Rashid Alafasy

# A second recording of a reciter who is already listed. It stays selectable, so the note tells the two apart.
RECITER_NOTES = {
    173: "alternate copy",
}
# QF serves Saad al-Ghamdi's word timings for Abdullah Ali Jabir on every surah (checked 2026-10-14), so his videos
# would be out of sync. Hidden until QF fixes the data.
HIDDEN_RECITERS = {158}


def clean_translation(html: str) -> str:
    """Translations carry <sup foot_note=..>n</sup> markers; drop them (and any other tags).

    Only translations pass through here: the Quran text is never touched."""
    text = re.sub(r"<sup[^>]*>.*?</sup>", "", html, flags=re.S)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", text)).strip()


def _style(reciter: dict) -> str:
    """Recitation style ("Murattal"...), sent as a name or as {"name": ...}; empty when the API leaves it out."""
    style = reciter.get("style") or ""
    return style.get("name", "") if isinstance(style, dict) else style


def _fresh(cache_file: Path) -> bool:
    return cache_file.exists() and time.time() - cache_file.stat().st_mtime < MAX_AGE


def prune(cache: Path) -> None:
    """Delete every cached file older than MAX_AGE: the terms forbid keeping them, not only using them."""
    if not cache.is_dir():
        return
    cutoff = time.time() - MAX_AGE
    for f in cache.rglob("*"):
        try:
            if f.is_file() and f.stat().st_mtime < cutoff:
                f.unlink()
        except OSError:  # in use or read-only: try again next start; cleanup must never stop the app
            pass


class ApiError(Exception):
    pass


class QuranClient:
    def __init__(self, cache_dir: Path = DEFAULT_CACHE, base: str = BASE):
        self.cache = Path(cache_dir)
        prune(self.cache)
        self.base = base
        self.session = requests.Session()
        self._lock = threading.Lock()  # the UI fetches from several threads; keep cache writes apart
        self.session.headers["User-Agent"] = f"QuranVideoCreator/{__version__}"
        retry = Retry(total=4, backoff_factor=1, status_forcelist=(429, 500, 502, 503, 504),
                      allowed_methods=["GET"], respect_retry_after_header=True)
        self.session.mount("https://", HTTPAdapter(max_retries=retry))

    def _json(self, path: str, **params) -> dict:
        """Cached GET. A copy older than MAX_AGE is fetched again, and never used once expired."""
        if not self.base:
            raise ApiError("No API proxy configured: set QVC_API_BASE (see README, 'Run your own API proxy')")
        url = requests.Request("GET", f"{self.base}/{path}", params=params).prepare().url
        cache_file = self.cache / "api" / (hashlib.sha1(url.encode()).hexdigest() + ".json")
        if _fresh(cache_file):
            return json.loads(cache_file.read_text("utf-8"))
        with self._lock:
            if _fresh(cache_file):  # another thread may have fetched it while we waited
                return json.loads(cache_file.read_text("utf-8"))
            return self._fetch(url, cache_file)

    def _fetch(self, url: str, cache_file: Path) -> dict:
        try:
            response = self.session.get(url, timeout=(10, 60))
            response.raise_for_status()
            data = response.json()
        except (requests.RequestException, ValueError) as e:
            raise ApiError(f"Could not fetch {url}: {e}") from e
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = cache_file.with_suffix(".part")
        tmp.write_text(json.dumps(data, ensure_ascii=False), "utf-8")
        tmp.replace(cache_file)
        return data

    def chapters(self) -> list[Chapter]:
        return [Chapter(c["id"], c["name_arabic"], c["name_simple"], c["verses_count"], c["bismillah_pre"])
                for c in self._json("v4/chapters", language="en")["chapters"]]

    def reciters(self) -> list[Reciter]:
        reciters = self._json("v4/resources/chapter_reciters", language="en")["reciters"]
        return [Reciter(r["id"], r["name"], _style(r), RECITER_NOTES.get(r["id"], "")) for r in reciters
                if r["id"] not in HIDDEN_RECITERS]

    def verses(self, chapter: int, text_field: str = "text_uthmani", translation: int | None = None) -> list[Verse]:
        """Every verse of a chapter, its words in `text_field`, and the translation with this id (if any)."""
        out, page = [], 1
        while page:
            extra = {"translations": translation} if translation else {}
            page_data = self._json(f"v4/verses/by_chapter/{chapter}", words="true", word_fields=text_field,
                                   per_page=50, page=page, **extra)
            for v in page_data["verses"]:
                words = tuple(Word(w["position"], w[text_field], w["char_type_name"] == "end") for w in v["words"])
                text = ""
                if translation and v.get("translations"):
                    text = clean_translation(v["translations"][0]["text"])
                out.append(Verse(v["verse_key"], v["verse_number"], words, text))
            page = page_data["pagination"]["next_page"]
        return out

    def recitation(self, reciter_id: int, chapter: int) -> tuple[str, list[VerseTiming]]:
        """The chapter's audio URL and the word timing of each verse."""
        audio_file = self._json(f"v4/chapter_recitations/{reciter_id}/{chapter}", segments="true")["audio_file"]
        timings = [VerseTiming(t["verse_key"], int(t["timestamp_from"]), int(t["timestamp_to"]),
                               tuple(tuple(s) for s in (t.get("segments") or [])))
                   for t in audio_file.get("timestamps") or []]
        if not timings:
            raise ApiError(f"No timing data for reciter {reciter_id}, surah {chapter}")
        return audio_file["audio_url"], timings

    def audio(self, reciter_id: int, chapter: int, url: str,
              on_chunk: Callable[[int, int], None] | None = None) -> Path:
        """The chapter's recitation as a cached MP3 file. While downloading, `on_chunk(done, total)` gets the bytes
        so far and the file size (0 if unknown); an exception it raises stops the download."""
        cache_file = self.cache / "audio" / f"{reciter_id}_{chapter}.mp3"
        if _fresh(cache_file):
            return cache_file
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = cache_file.with_suffix(".part")
        try:
            with self.session.get(url, stream=True, timeout=(10, 60)) as response:
                response.raise_for_status()
                total, done = int(response.headers.get("Content-Length") or 0), 0
                with open(tmp, "wb") as out:
                    for chunk in response.iter_content(1 << 16):
                        out.write(chunk)
                        done += len(chunk)
                        if on_chunk:
                            on_chunk(done, total)
        except requests.RequestException as e:
            tmp.unlink(missing_ok=True)
            raise ApiError(f"Could not download audio {url}: {e}") from e
        except BaseException:  # disk full, cancelled and the like: do not leave a partial file behind
            tmp.unlink(missing_ok=True)
            raise
        tmp.replace(cache_file)
        return cache_file
