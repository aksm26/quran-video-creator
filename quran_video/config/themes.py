"""Video colour themes. Adding a built-in one is one line. The first entry is the default.

Custom themes (a name, a background and a highlight colour) are added at run time by the app and kept
in the user's settings; the text colour is chosen automatically for contrast."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Theme:
    name: str
    bg: str  # background colour used when no background image/video is chosen
    text: str
    highlight: str


BUILTIN: tuple[Theme, ...] = (  # the order shown: dark themes (the default first), then light ones
    Theme("Classic", "#000000", "#FFFFFF", "#3BB5BC"),  # black / white / the app's blue
    Theme("Classic Yellow", "#000000", "#FFFFFF", "#FFD60A"),
    Theme("Midnight", "#0B1026", "#EEF1FF", "#8BD3FF"),
    Theme("Emerald & Gold", "#052E26", "#F6F0DC", "#F2C14E"),
    Theme("Dusk", "#24172B", "#FBEFF4", "#FF9EB5"),
    Theme("Ivory & Blue", "#FAF6EC", "#1B2A41", "#0E6B8C"),
    Theme("Paper", "#F5ECD9", "#1B1B1B", "#B3261E"),
)
THEMES: dict[str, Theme] = {t.name: t for t in BUILTIN}  # built-ins first, then any custom themes
DEFAULT_THEME = BUILTIN[0].name


def luminance(color: str) -> float:
    r, g, b = (int(color.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4))
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def contrast(a: str, b: str) -> float:
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def readable_text(bg: str) -> str:
    """White or near-black, whichever reads better on `bg`."""
    return "#FFFFFF" if contrast(bg, "#FFFFFF") >= contrast(bg, "#111111") else "#111111"


def make_custom(name: str, bg: str, highlight: str) -> Theme:
    return Theme(name.strip(), bg.upper(), readable_text(bg), highlight.upper())


def is_builtin(name: str) -> bool:
    return name in {t.name for t in BUILTIN}


def add_custom(theme: Theme) -> None:
    """Register (or replace) a custom theme. Built-in names can't be taken."""
    if is_builtin(theme.name):
        raise ValueError("That name is taken.")
    THEMES[theme.name] = theme


def remove_custom(name: str) -> None:
    if not is_builtin(name):
        THEMES.pop(name, None)


def custom_themes() -> list[Theme]:
    return [t for t in THEMES.values() if not is_builtin(t.name)]
