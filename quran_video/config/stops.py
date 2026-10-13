"""Waqf (stop) signs. Which ones a text can show depends on its mushaf style, so each sign lists, per style,
the character that marks it in Quran.com's text for that style. A style missing from `chars` does not support it."""

from dataclasses import dataclass

MADANI, INDOPAK = "madani", "indopak"


@dataclass(frozen=True)
class Stop:
    key: str
    name: str
    symbol: str
    chars: dict[str, str]  # mushaf style -> character(s) that mark this sign in the text


# Order is the order shown in the app. Checked against every verse of Quran.com's text_qpc_hafs, text_uthmani and
# text_indopak. Indo-Pak writes Qilā as a private-use glyph (U+E01C, a ق) and Mujawwaz as U+E01A (a ز).
STOPS: dict[str, Stop] = {s.key: s for s in (
    Stop("lazim", "Waqf Lāzim", "مـ", {MADANI: "ۘ", INDOPAK: "ۘ"}),
    Stop("mutlaq", "Waqf Muṭlaq", "ط", {INDOPAK: "ؕ"}),
    Stop("qif", "Qif", "قف", {INDOPAK: ""}),
    Stop("qila", "Qilā", "قلى", {MADANI: "ۗ", INDOPAK: ""}),
    Stop("jaiz", "Waqf Jā’iz", "ج", {MADANI: "ۚ", INDOPAK: "ۚ"}),
    Stop("mujawwaz", "Waqf Mujawwaz", "ز", {INDOPAK: ""}),
    Stop("sila", "Ṣilā", "صلى", {MADANI: "ۖ", INDOPAK: "ۖ"}),
)}
DEFAULT_STOPS = ("lazim", "qila")


def supported(style: str) -> list[str]:
    """Keys of the signs a mushaf style supports, in display order."""
    return [k for k, s in STOPS.items() if style in s.chars]


def chars_for(keys, style: str) -> str:
    """The characters to cut after, for the chosen signs; signs the style doesn't support add nothing."""
    return "".join(STOPS[k].chars.get(style, "") for k in keys if k in STOPS)
