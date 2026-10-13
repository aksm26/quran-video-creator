"""The custom themes page: pick a background and a highlight colour, name the theme, save it, delete it later."""

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (QColorDialog, QDialog, QDialogButtonBox, QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QVBoxLayout)

from ..config.fonts import DEFAULT_FONT, FONTS
from ..config.themes import THEMES, add_custom, custom_themes, is_builtin, make_custom, readable_text, remove_custom
from ..core.render import load_font
from .icons import theme_swatch
from ..i18n import tr


def swatch(color: str, size: int = 18) -> QIcon:
    px = QPixmap(size, size)
    px.fill(QColor(color))
    return QIcon(px)


class ThemesDialog(QDialog):
    """`on_change(name)` is called after a theme is saved (its name) or deleted (None) so the app can persist it."""

    def __init__(self, parent, on_change: Callable[[str | None], None]):
        super().__init__(parent)
        self.on_change = on_change
        self.bg, self.hl = "#000000", "#3BB5BC"
        self.setWindowTitle(tr("Custom themes"))
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 20, 20, 16)
        lay.setSpacing(12)

        self.name = QLineEdit()
        self.name.setPlaceholderText(tr("Name"))
        lay.addWidget(self.name)
        row = QHBoxLayout()
        self.bg_btn, self.hl_btn = QPushButton(), QPushButton()
        self.bg_btn.clicked.connect(lambda: self._pick("bg"))
        self.hl_btn.clicked.connect(lambda: self._pick("hl"))
        row.addWidget(self.bg_btn)
        row.addWidget(self.hl_btn)
        lay.addLayout(row)
        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumHeight(90)
        self.preview.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        lay.addWidget(self.preview)
        self.error = QLabel("")
        self.error.setObjectName("error")
        lay.addWidget(self.error)
        save = QPushButton(tr("Save theme"))
        save.setObjectName("primary")
        save.clicked.connect(self._save)
        lay.addWidget(save)

        self.list = QVBoxLayout()
        self.list.setSpacing(6)
        lay.addLayout(self.list)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText(tr("Close"))
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        self._refresh()
        self._fill_list()

    def _refresh(self) -> None:
        self.bg_btn.setText(f"{tr('Background')}  {self.bg}")
        self.bg_btn.setIcon(swatch(self.bg))
        self.hl_btn.setText(f"{tr('Highlight')}  {self.hl}")
        self.hl_btn.setIcon(swatch(self.hl))
        family = load_font(FONTS[DEFAULT_FONT].path)
        text = readable_text(self.bg)
        self.preview.setStyleSheet(f'background: {self.bg}; border-radius: 10px; font-family: "{family}"; font-size: 38px;')
        self.preview.setText(f'<span style="color:{text}">ٱللَّهُ</span> <span style="color:{self.hl}">أَحَدٌ</span>')

    def _pick(self, which: str) -> None:
        current = QColor(self.bg if which == "bg" else self.hl)
        color = QColorDialog.getColor(current, self, tr("Background") if which == "bg" else tr("Highlight"))
        if color.isValid():
            setattr(self, which, color.name().upper())
            self._refresh()

    def _save(self) -> None:
        name = self.name.text().strip()
        if not name:
            self.error.setText(tr("Enter a name."))
            return
        if is_builtin(name):
            self.error.setText(tr("That name is taken."))
            return
        self.error.setText("")
        add_custom(make_custom(name, self.bg, self.hl))
        self.name.clear()
        self._fill_list()
        self.on_change(name)

    def _delete(self, name: str) -> None:
        remove_custom(name)
        self._fill_list()
        self.on_change(None)

    def _fill_list(self) -> None:
        while self.list.count():
            item = self.list.takeAt(0)
            if item.widget():
                item.widget().hide()  # out of sight at once; its own click handler may still be running
                item.widget().deleteLater()
        for theme in custom_themes():
            frame = QFrame()
            row = QHBoxLayout(frame)
            row.setContentsMargins(0, 0, 0, 0)
            chip = QLabel()
            chip.setPixmap(theme_swatch(theme.bg, theme.highlight))  # the two colours side by side
            delete = QPushButton(tr("Delete"))
            delete.setObjectName("danger")
            delete.clicked.connect(lambda _=False, n=theme.name: self._delete(n))
            row.addWidget(chip)
            row.addWidget(QLabel(theme.name), 1)
            row.addWidget(delete)
            self.list.addWidget(frame)
