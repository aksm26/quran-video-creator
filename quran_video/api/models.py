"""What the API returns, as plain read-only records."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Chapter:
    id: int
    name_arabic: str
    name_simple: str
    verses_count: int
    bismillah_pre: bool


@dataclass(frozen=True)
class Reciter:
    id: int  # chapter-reciter id, as used by /chapter_recitations
    name: str
    style: str
    note: str = ""  # shown next to the name in the reciter list

    @property
    def label(self) -> str:
        extra = ", ".join(x for x in (self.style, self.note) if x)
        return f"{self.name} ({extra})" if extra else self.name


@dataclass(frozen=True)
class Word:
    position: int
    text: str  # text_uthmani, exactly as returned by the API
    is_end: bool  # the ayah-number glyph


@dataclass(frozen=True)
class Verse:
    key: str
    number: int
    words: tuple[Word, ...]
    translation: str = ""  # plain text, footnote markup removed

    @property
    def end_text(self) -> str:
        """The verse-number text exactly as the API returns it (empty if absent)."""
        return next((w.text for w in self.words if w.is_end), "")

    @property
    def text_words(self) -> list[Word]:
        return [w for w in self.words if not w.is_end]


@dataclass(frozen=True)
class VerseTiming:
    key: str
    start: int  # ms in the chapter audio
    end: int
    segments: tuple[tuple, ...]  # raw API entries, may be malformed; cleaned in core.timing
