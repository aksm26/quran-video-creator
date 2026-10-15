"""Quran Foundation Content API (v4) client, through the project proxy, with an on-disk cache. Nothing is kept longer than a week (Quran Foundation Developer Terms)."""

import hashlib
import json
import os
import re
import threading
import time
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


# Kept in the list on purpose (user decision); the note explains what each one is.
RECITER_NOTES = {
    173: "alternate copy",
}
# QF serves Saad al-Ghamdi's word timings for Abdullah Ali Jabir on every surah (checked 2026-10-14; user chose to hide him).
HIDDEN_RECITERS = {158}


def clean_translation(html: str) -> str:
    """Translations carry <sup foot_note=..>n</sup> markers; drop them (and any other tags). Quran text is never touched."""
    text = re.sub(r"<sup[^>]*>.*?</sup>", "", html, flags=re.S)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", text)).strip()


def _style(r: dict) -> str:
    """Recitation style ("Murattal"...), sent as a name or as {"name": ...}; empty when the API leaves it out."""
    st = r.get("style") or ""
    return st.get("name", "") if isinstance(st, dict) else st


def _fresh(f: Path) -> bool:
    return f.exists() and time.time() - f.stat().st_mtime < MAX_AGE


class ApiError(Exception):
    pass


class QuranClient:
    def __init__(self, cache_dir: Path = DEFAULT_CACHE, base: str = BASE):
        self.cache = Path(cache_dir)
        self.base = base
        self.s = requests.Session()
        self._lock = threading.Lock()  # the UI fetches from several threads; keep cache writes apart
        self.s.headers["User-Agent"] = f"QuranVideoCreator/{__version__}"
        retry = Retry(total=4, backoff_factor=1, status_forcelist=(429, 500, 502, 503, 504),
                      allowed_methods=["GET"], respect_retry_after_header=True)
        self.s.mount("https://", HTTPAdapter(max_retries=retry))

    def _json(self, path: str, **params) -> dict:
        """Cached GET. A copy older than MAX_AGE is fetched again, and never used once expired."""
        if not self.base:
            raise ApiError("No API proxy configured: set QVC_API_BASE (see README, 'Run your own API proxy')")
        url = requests.Request("GET", f"{self.base}/{path}", params=params).prepare().url
        f = self.cache / "api" / (hashlib.sha1(url.encode()).hexdigest() + ".json")
        def fresh() -> bool:
            return _fresh(f)
        if fresh():
            return json.loads(f.read_text("utf-8"))
        with self._lock:
            if fresh():  # another thread may have fetched it while we waited
                return json.loads(f.read_text("utf-8"))
            return self._fetch(url, f)

    def _fetch(self, url: str, f: Path) -> dict:
        try:
            r = self.s.get(url, timeout=(10, 60))
            r.raise_for_status()
            data = r.json()
        except (requests.RequestException, ValueError) as e:
            raise ApiError(f"Could not fetch {url}: {e}") from e
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_suffix(".part")
        tmp.write_text(json.dumps(data, ensure_ascii=False), "utf-8")
        tmp.replace(f)
        return data

    def chapters(self) -> list[Chapter]:
        return [Chapter(c["id"], c["name_arabic"], c["name_simple"], c["verses_count"], c["bismillah_pre"])
                for c in self._json("v4/chapters", language="en")["chapters"]]

    def reciters(self) -> list[Reciter]:
        rs = self._json("v4/resources/chapter_reciters", language="en")["reciters"]
        return [Reciter(r["id"], r["name"], _style(r), RECITER_NOTES.get(r["id"], "")) for r in rs
                if r["id"] not in HIDDEN_RECITERS]

    def verses(self, chapter: int, text_field: str = "text_uthmani", translation: int | None = None) -> list[Verse]:
        out, page = [], 1
        while page:
            extra = {"translations": translation} if translation else {}
            d = self._json(f"v4/verses/by_chapter/{chapter}", words="true", word_fields=text_field,
                           per_page=50, page=page, **extra)
            for v in d["verses"]:
                words = tuple(Word(w["position"], w[text_field], w["char_type_name"] == "end") for w in v["words"])
                tr = clean_translation(v["translations"][0]["text"]) if translation and v.get("translations") else ""
                out.append(Verse(v["verse_key"], v["verse_number"], words, tr))
            page = d["pagination"]["next_page"]
        return out

    def recitation(self, reciter_id: int, chapter: int) -> tuple[str, list[VerseTiming]]:
        af = self._json(f"v4/chapter_recitations/{reciter_id}/{chapter}", segments="true")["audio_file"]
        timings = [VerseTiming(t["verse_key"], int(t["timestamp_from"]), int(t["timestamp_to"]),
                               tuple(tuple(s) for s in (t.get("segments") or [])))
                   for t in af.get("timestamps") or []]
        if not timings:
            raise ApiError(f"No timing data for reciter {reciter_id}, surah {chapter}")
        return af["audio_url"], timings

    def audio(self, reciter_id: int, chapter: int, url: str) -> Path:
        f = self.cache / "audio" / f"{reciter_id}_{chapter}.mp3"
        if _fresh(f):
            return f
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_suffix(".part")
        try:
            with self.s.get(url, stream=True, timeout=(10, 60)) as r:
                r.raise_for_status()
                with open(tmp, "wb") as out:
                    for chunk in r.iter_content(1 << 16):
                        out.write(chunk)
        except requests.RequestException as e:
            tmp.unlink(missing_ok=True)
            raise ApiError(f"Could not download audio {url}: {e}") from e
        except OSError:  # disk full and the like: do not leave a partial file behind
            tmp.unlink(missing_ok=True)
            raise
        tmp.replace(f)
        return f
