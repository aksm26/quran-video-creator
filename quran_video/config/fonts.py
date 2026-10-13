"""Quran fonts that may be redistributed (licences in THIRD_PARTY.md). The first entry is the default.

Each font is paired with the API text field it was designed for. The text is drawn exactly as the API returns it."""

from dataclasses import dataclass
from pathlib import Path

from .stops import MADANI

FONT_DIR = Path(__file__).resolve().parents[2] / "assets" / "fonts"
SURAH_NAME_FONT = FONT_DIR / "SurahNameV2.ttf"  # glyph font: the text "surah002" draws the name of surah 2
SYMBOL_FONT = FONT_DIR / "Amiri-Regular.ttf"  # draws the stop-sign symbols in the app (SIL OFL)
TRANSLATION_FONT = FONT_DIR / "Figtree-Regular.ttf"  # the font Quran.com uses for translations (OFL)


@dataclass(frozen=True)
class FontSpec:
    name: str
    file: str
    text_field: str  # Quran.com word field to render with this font
    marker_fmt: str = "۝{n}"  # verse-end sign; {n} is the verse number exactly as the API returns it
    marker_file: str = ""  # font that draws the sign when this font can't ("" = same font)
    style: str = MADANI  # mushaf style: decides which stop signs the text can show

    @property
    def path(self) -> Path:
        return FONT_DIR / self.file

    @property
    def marker_path(self) -> Path:
        return FONT_DIR / (self.marker_file or self.file)


FONTS: dict[str, FontSpec] = {f.name: f for f in (
    FontSpec("QPC Hafs", "QPCHafs.ttf", "text_qpc_hafs", marker_fmt="{n}"),  # this font turns bare digits into the sign
    FontSpec("Amiri Quran", "AmiriQuran.ttf", "text_uthmani"),
    FontSpec("Digital Khatt V1", "DigitalKhattV1.otf", "text_uthmani"),
    FontSpec("Digital Khatt V2", "DigitalKhattV2.otf", "text_uthmani"),
)}
DEFAULT_FONT = next(iter(FONTS))
