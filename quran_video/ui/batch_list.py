"""The batches of the Manual mode tab, one card each in a scrolling list.

A card shows the batch's first words (so it can be recognised at a glance), its reference, its times, and buttons
that act on that batch alone. Clicking a card selects it: the next clicks on the mushaf change its words."""

from dataclasses import dataclass, field

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from ..core.render import has_rtl
from ..i18n import tr


@dataclass
class CardInfo:
    """What one card shows. `buttons` lists the actions it offers, from TRANSLATION, BACKGROUND, MOVE, REMOVE."""
    number: str
    preview: str  # its first words; "" until they are known
    lines: list[str]  # reference and times, then its translation and background, each on a line
    selected: bool = False
    buttons: set[str] = field(default_factory=set)
    can_up: bool = False
    can_down: bool = False


TRANSLATION, BACKGROUND, MOVE, REMOVE = "translation", "background", "move", "remove"


class BatchCard(QFrame):
    chosen = Signal()
    translation = Signal()
    background = Signal()
    moved = Signal(int)  # -1 up, +1 down
    removed = Signal()

    def __init__(self, info: CardInfo, family: str):
        super().__init__()
        self.setObjectName("batchCard")
        self.setProperty("selected", info.selected)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(4)
        top = QHBoxLayout()
        badge = QLabel(info.number)
        badge.setObjectName("badge")
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setFixedSize(24, 24)
        top.addWidget(badge, 0, Qt.AlignmentFlag.AlignTop)
        preview = QLabel(info.preview)
        preview.setWordWrap(True)
        preview.setMinimumWidth(10)
        if has_rtl(info.preview):  # the Arabic (or a translation in a right-to-left script)
            preview.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
            preview.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignAbsolute
                                 | Qt.AlignmentFlag.AlignVCenter)
        else:
            preview.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
            preview.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignAbsolute
                                 | Qt.AlignmentFlag.AlignVCenter)
        if family:
            preview.setStyleSheet(f'font-family: "{family}"; font-size: 22px;')
        top.addWidget(preview, 1)
        lay.addLayout(top)
        for line in info.lines:
            label = QLabel(line)
            label.setObjectName("muted")
            label.setWordWrap(True)
            lay.addWidget(label)
        if info.buttons:
            row = QHBoxLayout()
            row.setSpacing(6)
            for key, signal, show in ((tr("Translation"), self.translation, TRANSLATION in info.buttons),
                                      (tr("Background"), self.background, BACKGROUND in info.buttons)):
                if show:
                    row.addWidget(self._button(key, signal.emit))
            row.addStretch()
            if MOVE in info.buttons:
                for text, tip, step, ok in (("▲", "Move up", -1, info.can_up), ("▼", "Move down", 1, info.can_down)):
                    b = self._button(text, lambda _=False, step=step: self.moved.emit(step))
                    b.setToolTip(tr(tip))
                    b.setEnabled(ok)
                    row.addWidget(b)
            if REMOVE in info.buttons:
                row.addWidget(self._button(tr("Remove"), self.removed.emit))
            lay.addLayout(row)

    @staticmethod
    def _button(text: str, slot) -> QPushButton:
        b = QPushButton(text)
        b.setObjectName("small")
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.clicked.connect(slot)
        return b

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self.chosen.emit()


class BatchList(QScrollArea):
    """The cards, in playback order. The tab rebuilds them whenever a batch changes."""

    chosen = Signal(int)
    translation = Signal(int)
    background = Signal(int)
    moved = Signal(int, int)
    removed = Signal(int)

    def __init__(self):
        super().__init__()
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        self.column = QVBoxLayout(inner)
        self.column.setContentsMargins(0, 0, 10, 0)
        self.column.setSpacing(8)
        self.column.addStretch()
        self.setWidget(inner)
        self.cards: list[BatchCard] = []

    def set_cards(self, infos: list[CardInfo], family: str) -> None:
        for card in self.cards:
            card.setParent(None)
            card.deleteLater()
        self.cards = []
        for k, info in enumerate(infos):
            card = BatchCard(info, family)
            card.chosen.connect(lambda k=k: self.chosen.emit(k))
            card.translation.connect(lambda k=k: self.translation.emit(k))
            card.background.connect(lambda k=k: self.background.emit(k))
            card.moved.connect(lambda step, k=k: self.moved.emit(k, step))
            card.removed.connect(lambda k=k: self.removed.emit(k))
            self.column.insertWidget(k, card)
            self.cards.append(card)

    def count(self) -> int:
        return len(self.cards)

    def show_card(self, k: int) -> None:
        if 0 <= k < len(self.cards):
            self.ensureWidgetVisible(self.cards[k], 0, 40)
