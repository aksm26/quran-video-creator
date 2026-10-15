"""The app's look: flat, neutral surfaces, one accent colour, thin borders, consistent control sizes.

Two palettes, Light and Dark; "System" picks between them. Colours are written once, in PALETTES, and the
stylesheet refers to them as @name."""

from pathlib import Path

PALETTES = {
    "Light": dict(bg="#F3F4F6", card="#FFFFFF", text="#111827", muted="#5B6472", border="#E3E6EB", line="#CBD1D9",
                  field="#FFFFFF", hover="#F1F3F6", accent="#1B7F86", accent_hover="#14666C", accent_soft="#E3F2F3",
                  on_accent="#FFFFFF", warn="#8A4B00", error="#B42318", on_error="#FFFFFF", disabled="#A3ABB7",
                  check_icon="check.svg"),
    "Dark": dict(bg="#0E1116", card="#161A21", text="#E7EAF0", muted="#98A2B3", border="#262C36", line="#363E4B",
                 field="#1C212A", hover="#212732", accent="#3BB5BC", accent_hover="#57C9D0", accent_soft="#173A3D",
                 on_accent="#06201F", warn="#F5B544", error="#F28B82", on_error="#2B0A07", disabled="#4A525E",
                 check_icon="check-dark.svg"),
}

ASSETS = (Path(__file__).resolve().parents[2] / "assets" / "ui").as_posix()

QSS = """
* { font-family: "Figtree", "Segoe UI", sans-serif; font-size: 13px; color: @text; }
QMainWindow, QWidget#root, QScrollArea, QScrollArea > QWidget > QWidget { background: @bg; }
QDialog { background: @bg; }
QToolTip { background: @card; color: @text; border: 1px solid @line; padding: 5px 8px; }

/* surfaces and text */
QFrame#header { background: @card; border-bottom: 1px solid @border; }
QLabel#brand { font-size: 15px; font-weight: 700; color: @text; }
QFrame#card { background: @card; border: 1px solid @border; border-radius: 8px; }
QLabel#cardTitle { font-size: 14px; font-weight: 700; }
QLabel#muted, QLabel#note { color: @muted; font-size: 12px; }
QLabel#warn { color: @warn; }
QLabel#error { color: @error; }
QLabel#preview { background: @card; border: 1px solid @border; border-radius: 8px; }

/* text boxes and dropdowns */
QComboBox, QLineEdit { background: @field; border: 1px solid @line; border-radius: 6px; padding: 7px 10px;
                       min-height: 20px; selection-background-color: @accent_soft; selection-color: @text; }
QComboBox:hover, QLineEdit:hover { border-color: @muted; }
QComboBox:focus, QComboBox:on, QLineEdit:focus { border: 1px solid @accent; }
QComboBox { combobox-popup: 0; }
QComboBox::drop-down { border: none; width: 28px; }
QComboBox::down-arrow { image: url("@ASSETS/down.svg"); width: 12px; height: 12px; }
QComboBox QAbstractItemView { background: @card; border: 1px solid @line; border-radius: 6px; padding: 4px; outline: 0;
                              selection-background-color: @accent_soft; selection-color: @text; }
QComboBox QAbstractItemView::item { min-height: 28px; padding: 0 8px; border-radius: 4px; }
QComboBox QAbstractItemView::item:hover { background: @hover; }
QComboBox QAbstractItemView::item:selected { background: @accent_soft; color: @text; }
QComboBox QAbstractItemView::item:disabled { color: @disabled; }
QComboBox:disabled, QLineEdit:disabled { color: @disabled; background: @bg; border-color: @border; }

/* buttons */
QPushButton { background: @card; border: 1px solid @line; border-radius: 6px; padding: 7px 14px; min-height: 20px;
              font-weight: 600; }
QPushButton:hover { background: @hover; }
QPushButton:pressed { background: @border; }
QPushButton:focus { border-color: @accent; }
QPushButton:disabled { color: @disabled; background: @bg; border-color: @border; }
QPushButton#primary { background: @accent; border: 1px solid @accent; color: @on_accent; padding: 8px 22px; }
QPushButton#primary:hover { background: @accent_hover; border-color: @accent_hover; }
QPushButton#primary:pressed { background: @accent_hover; }
QPushButton#primary:disabled { background: @border; border-color: @border; color: @disabled; }
QPushButton#danger { background: @error; border: 1px solid @error; color: @on_error; }
QPushButton#danger:hover { background: @error; border-color: @text; }
QToolButton#lang { background: @card; border: 1px solid @line; border-radius: 6px; padding: 7px 10px; }
QToolButton#lang:hover { background: @hover; }

/* the language list */
QFrame#listpopup { background: @card; border: 1px solid @line; border-radius: 6px; }
QListWidget { background: transparent; border: none; outline: 0; padding: 4px; }
QListWidget::item { min-height: 28px; padding: 0 8px; border-radius: 4px; }
QListWidget::item:hover { background: @hover; }
QListWidget::item:selected { background: @accent_soft; color: @text; }

/* checkboxes and radio buttons */
QCheckBox, QRadioButton { spacing: 9px; }
QCheckBox::indicator, QRadioButton::indicator { width: 16px; height: 16px; border: 1px solid @line;
                                                background: @field; }
QCheckBox::indicator { border-radius: 4px; }
QRadioButton::indicator { border-radius: 9px; }
QCheckBox::indicator:hover, QRadioButton::indicator:hover { border-color: @accent; }
QCheckBox::indicator:checked { background: @accent; border-color: @accent; image: url("@ASSETS/@check_icon"); }
QRadioButton::indicator:checked { border: 1px solid @accent;
    background: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5,
                                stop:0 @accent, stop:0.45 @accent, stop:0.5 @field, stop:1 @field); }
QCheckBox::indicator:disabled, QRadioButton::indicator:disabled { background: @bg; border-color: @border; }
QCheckBox::indicator:checked:disabled { background: @border; border-color: @border; }
QRadioButton::indicator:checked:disabled { border-color: @border;
    background: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5,
                                stop:0 @border, stop:0.45 @border, stop:0.5 @bg, stop:1 @bg); }
QLabel:disabled, QCheckBox:disabled, QRadioButton:disabled { color: @disabled; }

/* sliders and progress */
QSlider::groove:horizontal { height: 4px; background: @border; border-radius: 2px; }
QSlider::sub-page:horizontal { background: @accent; border-radius: 2px; }
QSlider::handle:horizontal { background: @card; border: 2px solid @accent; width: 12px; height: 12px; margin: -6px 0;
                             border-radius: 8px; }
QSlider::handle:horizontal:hover { background: @accent_soft; }
QSlider::sub-page:horizontal:disabled { background: @border; }
QSlider::handle:horizontal:disabled { background: @bg; border-color: @line; }
QProgressBar { background: @border; border: none; border-radius: 3px; max-height: 6px; min-height: 6px;
               text-align: center; }
QProgressBar::chunk { background: @accent; border-radius: 3px; }

/* scroll bars */
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: @line; border-radius: 3px; min-height: 32px; }
QScrollBar::handle:vertical:hover { background: @muted; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle:horizontal { background: @line; border-radius: 3px; min-width: 32px; }
QScrollBar::handle:horizontal:hover { background: @muted; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: none; }
"""


def resolve(mode: str) -> str:
    """The palette to use: Light or Dark. System asks the OS (Qt 6.5+)."""
    if mode in PALETTES:
        return mode
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication
    return "Dark" if QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark else "Light"


def stylesheet(mode: str) -> str:
    out = QSS.replace("@ASSETS", ASSETS)
    for key, value in sorted(PALETTES[resolve(mode)].items(), key=lambda kv: -len(kv[0])):  # longest first
        out = out.replace("@" + key, value)
    return out
