"""App language. The interface is written in English. Every other language has a file, assets/locales/<code>.json:
"strings" maps each English text to its translation, and "reciters" spells the reciters' names in that language's
own script (by Quran.com reciter id).

A text with no translation falls back to English and is recorded in MISSING (a test keeps that empty)."""

import json
from dataclasses import dataclass
from pathlib import Path

LOCALE_DIR = Path(__file__).resolve().parents[1] / "assets" / "locales"


@dataclass(frozen=True)
class Language:
    translation_id: int | None  # the Quran.com translation selected by default for it (None: no translation)
    rtl: bool = False


# The app's languages, in menu order, each with the Quran translation it picks by default. Their names are not
# stored here: they come from config/language_names.py, in the language the app is currently using.
LANGUAGES: dict[str, Language] = {
    "en": Language(20),  # Saheeh International
    "ar": Language(None, True),  # the Arabic text itself needs no translation
    "ur": Language(234, True),
    "fr": Language(31),
    "es": Language(83),
    "id": Language(33),
    "tr": Language(77),
    "pt": Language(103),
    "de": Language(27),
    "ru": Language(45),
    "it": Language(153),
    "nl": Language(235),
    "fa": Language(29, True),
    "ms": Language(39),
    "hi": Language(122),
    "bn": Language(161),
    "zh": Language(56),
    "ja": Language(35),
}

ABOUT_DATA = ("Text, translations, reciters and word timing come from Quran.com / Quran.Foundation (Content API v4). "
              "Audio comes from quranicaudio.com. The Arabic is shown exactly as the API returns it.")
NEUTRAL = {"", "Reels, Shorts, TikTok", "YouTube"}  # names that are not translated
current = "en"
MISSING: set[str] = set()


def _load(code: str) -> dict:
    return json.loads((LOCALE_DIR / f"{code}.json").read_text("utf-8"))


_LOCALES = {code: _load(code) for code in LANGUAGES if code != "en"}
TABLE: dict[str, dict[str, str]] = {code: data["strings"] for code, data in _LOCALES.items()}
RECITER_NAMES: dict[str, dict[int, str]] = {
    code: {int(reciter_id): name for reciter_id, name in data.get("reciters", {}).items()}
    for code, data in _LOCALES.items()}


def set_language(code: str) -> None:
    global current
    current = code if code in LANGUAGES else "en"


def is_rtl() -> bool:
    return LANGUAGES[current].rtl


def tr(key: str) -> str:
    """`key` (an English text) in the current language."""
    if current == "en" or key in NEUTRAL:
        return key
    text = TABLE[current].get(key)
    if text is None:
        MISSING.add(key)
        return key
    return text


def reciter_name(reciter_id: int, name: str) -> str:
    """The reciter's name in the script used by the current language, where we have it; else the API's spelling."""
    return RECITER_NAMES.get(current, {}).get(reciter_id, name)
