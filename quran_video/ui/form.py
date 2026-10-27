"""Building blocks shared by the window's two tabs: controls whose text follows the interface language, cards,
and the theme and translation lists."""

import unicodedata

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QComboBox, QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QMessageBox,
                               QToolButton, QVBoxLayout, QWidget)

from .. import i18n
from ..config.language_names import language_name
from ..config.themes import DEFAULT_THEME, THEMES, is_builtin
from ..config.translations import BY_KEY, TRANSLATIONS
from ..core.render import DEFAULT_TEXT_WIDTH
from ..i18n import tr
from .icons import theme_swatch
from .widgets import NoWheelCombo, NoWheelSlider

MEDIA_FILTER = "Images and videos (*.png *.jpg *.jpeg *.webp *.bmp *.mp4 *.mov *.mkv *.webm *.avi);;All files (*)"
PANEL_WIDTH = 560
SLIDERS = {  # name: (minimum %, maximum %, default %)
    "text_width": (60, 98, round(DEFAULT_TEXT_WIDTH * 100)),
    "translation_width": (50, 98, round(DEFAULT_TEXT_WIDTH * 100)),
    "name_size": (50, 200, 100),
    # A chosen background is usually a busy photo or video, so the window dims it a little from the start
    # (the command line's --overlay starts at 0).
    "dim": (0, 80, 35),
}
INDENT = 22  # how far a dependent control is indented under the one it depends on
FADED = 0.35  # opacity of a control that does not apply right now
ITEM_GAP, GROUP_GAP = 12, 8  # space between controls, and the extra space between groups in a card


def fmt_duration(seconds: float) -> str:
    """'1 hour 2 minutes 5 seconds', leaving out any part that is zero."""
    s = max(1, round(seconds))
    h, rest = divmod(s, 3600)
    m, sec = divmod(rest, 60)
    parts = ((h, "hour"), (m, "minute"), (sec, "second"))
    return " ".join(f"{n} {tr(unit if n == 1 else unit + 's')}" for n, unit in parts if n)


def fmt_size(n: int) -> str:
    if n >= 1e9:
        return f"{n / 1e9:.2f} GB"
    return f"{n / 1e6:.1f} MB" if n >= 1e6 else f"{max(1, round(n / 1e3))} KB"


def clock(ms: int | None) -> str:
    """A moment in a recording: '1:03.2' (minutes, seconds and tenths)."""
    if ms is None:
        return "-:--"
    m, s = divmod(max(ms, 0) / 1000, 60)
    return f"{int(m)}:{s:04.1f}"


def ltr(text: str) -> str:
    """Text that always reads left to right, even inside a right-to-left sentence: verse references and times
    ('2:255:3-5', '0:03.2 - 0:07.9'), whose order the Unicode bidi rules would otherwise flip."""
    return f"\u2066{text}\u2069"


def set_item_enabled(combo: QComboBox, data, enabled: bool) -> None:
    item = combo.model().item(combo.findData(data))
    if item is not None:
        item.setEnabled(enabled)


class Form:
    """Makes controls whose text is redrawn when the interface language changes: each registers a function in
    `relabels` that sets its text again. Info buttons are listed in `icons`, to be re-tinted with the theme."""

    def __init__(self, parent: QWidget, relabels: list, icons: list):
        self.parent, self.relabels, self.icons = parent, relabels, icons

    def reg(self, fn) -> None:
        fn()
        self.relabels.append(fn)

    def text(self, widget, key: str, setter: str = "setText"):
        self.reg(lambda: getattr(widget, setter)(tr(key)))
        return widget

    def field(self, key: str, widget: QWidget) -> QWidget:
        """A control with a small caption above it."""
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        caption = QLabel()
        caption.setObjectName("muted")
        lay.addWidget(self.text(caption, key))
        lay.addWidget(widget)
        return box

    def hint(self, key: str, beside: QWidget) -> QToolButton:
        """A small info button that explains `beside`: on hover, and in a message when clicked (a tooltip alone
        is easy to miss and gone in seconds). `beside` gets the same tooltip, for keyboard and screen reader users."""
        hint = QToolButton()
        hint.setObjectName("hint")
        hint.setIconSize(QSize(18, 18))
        hint.setCursor(Qt.CursorShape.PointingHandCursor)
        hint.setFixedHeight(beside.sizeHint().height())  # centred on the control beside it
        hint.clicked.connect(lambda: QMessageBox.information(self.parent, "", tr(key)))
        self.icons.append((hint, "info-circle"))
        for widget in (hint, beside):
            self.text(widget, key, "setToolTip")
        return hint

    def combo(self, items: list[tuple[str, object]]) -> NoWheelCombo:
        combo = NoWheelCombo()
        for key, data in items:
            combo.addItem(tr(key), data)
        self.relabels.append(lambda: [combo.setItemText(i, tr(k)) for i, (k, _) in enumerate(items)])
        return combo

    def slider(self, key: str, lo: int, hi: int, default: int, on_change) -> tuple[QWidget, NoWheelSlider]:
        """A percentage slider with its caption and value above it."""
        slider = NoWheelSlider(Qt.Orientation.Horizontal)
        slider.setRange(lo, hi)
        slider.setValue(default)
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        caption = QLabel()
        caption.setObjectName("muted")
        draw = lambda: caption.setText(f"{tr(key)}: {slider.value()}%")
        slider.valueChanged.connect(lambda _: draw())
        self.reg(draw)
        slider.valueChanged.connect(on_change)
        lay.addWidget(caption)
        lay.addWidget(slider)
        return box, slider

    def card(self, key: str) -> tuple[QFrame, QVBoxLayout]:
        frame = QFrame()
        frame.setObjectName("card")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(20, 18, 20, 20)
        lay.setSpacing(ITEM_GAP)
        title = QLabel()
        title.setObjectName("cardTitle")
        lay.addWidget(self.text(title, key))
        lay.addSpacing(2)
        return frame, lay

    @staticmethod
    def dep(widget: QWidget, level: int = 1) -> QWidget:
        """Put `widget` under the control it depends on: indented, and faded by set_on when it does not apply."""
        box = QWidget()
        lay = QHBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addSpacing(INDENT * level)  # a spacer, so right-to-left languages indent from the right
        lay.addWidget(widget, 1)
        box.setGraphicsEffect(QGraphicsOpacityEffect(box))
        return box

    @staticmethod
    def set_on(box: QWidget, on: bool) -> None:
        box.setEnabled(on)
        box.graphicsEffect().setOpacity(1.0 if on else FADED)


def theme_label(name: str) -> str:
    return name if not is_builtin(name) else tr(name)  # a custom theme keeps the name its owner gave it


def fill_themes(combo: QComboBox, select: str | None = None) -> None:
    """The theme list: each entry shows its two colours side by side and its name in the app's language."""
    current = select or combo.currentData()
    combo.blockSignals(True)
    combo.clear()
    for name, theme in THEMES.items():
        combo.addItem(QIcon(theme_swatch(theme.bg, theme.highlight)), theme_label(name), name)
    keep = current if current in THEMES else DEFAULT_THEME
    combo.setCurrentIndex(max(0, combo.findData(keep)))
    combo.blockSignals(False)


def relabel_themes(combo: QComboBox) -> None:
    for i in range(combo.count()):
        combo.setItemText(i, theme_label(combo.itemData(i)))


def translation_label(key: str) -> str:
    if key == "None":
        return tr("None")
    t = BY_KEY[key]
    return f"{language_name(t.lang, i18n.current)} ({t.translator})"


def fill_translations(combo: QComboBox, select: str | None = None) -> None:
    """Every translation Quran.com has, "None" first and then in the app language's alphabetical order."""
    current = select or combo.currentData()
    combo.blockSignals(True)
    combo.clear()

    def plain(text: str) -> str:  # sort "Éspañol" with "Espanol": no accents, no case
        return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)).casefold()
    keys = sorted((k for k in TRANSLATIONS if k != "None"), key=lambda k: plain(translation_label(k)))
    for key in ["None", *keys]:
        combo.addItem(translation_label(key), key)
    combo.setCurrentIndex(max(0, combo.findData(current)))
    combo.blockSignals(False)
