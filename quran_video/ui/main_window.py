"""Main window. All blocking work runs in Task (QThreadPool); this file only builds widgets and wires them up."""

import json
import sys
import threading
import time
from pathlib import Path

from PySide6.QtCore import (QEvent, QLibraryInfo, QLocale, QRect, QSettings, QSize, Qt, QThreadPool, QTimer,
                            QTranslator, QUrl)
from PySide6.QtGui import QDesktopServices, QGuiApplication, QIcon, QPixmap
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QComboBox, QFileDialog, QFrame,
                               QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox,
                               QProgressBar, QPushButton, QRadioButton, QScrollArea, QSizePolicy, QStackedWidget,
                               QTabBar, QToolButton, QToolTip, QVBoxLayout, QWidget)

from .. import __version__, i18n
from ..api.client import DEFAULT_RECITER, ApiError, QuranClient
from ..api.updates import newer_release
from ..config.fonts import DEFAULT_FONT, FONTS, SURAH_NAME_FONT, SYMBOL_FONT, TRANSLATION_FONT
from ..config.language_names import language_name
from ..config.presets import DEFAULT_FORMAT, FORMAT_NOTES, FORMATS
from ..config.quality import DEFAULT_QUALITY, QUALITIES
from ..config.stops import DEFAULT_STOPS, STOPS, supported
from ..config.themes import DEFAULT_THEME, add_custom, custom_themes, make_custom
from ..config.translations import key_for_id
from ..core.export import (VERSE_CHANGE_LAST_WORD, VERSE_CHANGE_TIMING, Cancelled, ExportJob, VideoInfo, credits,
                           estimate_bytes, estimate_seconds, export, preview_image, video_info)
from ..core.ffmpeg import FFmpegError, is_video
from ..core.manual_export import export_manual, manual_credits
from ..core.render import SPLIT_PARTS, SPLIT_VERSE, load_font
from ..core.timing import DataError, basmala_available
from ..i18n import tr
from .about import AboutDialog
from .form import (GROUP_GAP, ITEM_GAP, MEDIA_FILTER, PANEL_WIDTH, SLIDERS, Form, fill_themes, fill_translations,
                   fmt_duration, fmt_size, relabel_themes, set_item_enabled)
from .icons import pixmap
from .manual_tab import ManualTab
from .style import ASSETS, PALETTES, resolve, stylesheet
from .themes_dialog import ThemesDialog
from .widgets import FAMILY_ROLE, SAMPLE_ROLE, FontDelegate, ListPopup, NoWheelCombo, NoWheelSlider, VerseCombo
from .workers import Task

TOAST_MS = 3000  # a warning flashes in the footer this long
TIP_MS = 2500  # a tooltip stays this long
CREDITS_HINT = ("Required: paste the credits from the .credits.txt file saved next to each video into your post's "
                "description. They credit the Quran Foundation for the text, translation and recitation, as its "
                "terms require. The app's name does not need to be mentioned.")
VERSE_CHANGE_HINT = ("The recitation timings come from Quran.com and some contain errors, so a verse can change "
                     "too early or too late. If the text changes at the wrong moment, try the other choice.")
SETTINGS_VERSION = 8  # bump when defaults change so older saved choices don't override them
# Shown in the font list until the API's own text for each font arrives.
FALLBACK_SAMPLE = "بِسْمِ ٱللَّهِ ٱلرَّحْمَٰنِ ٱلرَّحِيمِ"


def friendly(e: Exception) -> str:
    if isinstance(e, ApiError):
        return tr("Can't reach Quran.com. Check your connection.") + f"\n\n{e}"
    if isinstance(e, FFmpegError):
        return tr("Encoding failed.") + f"\n\n{e}"
    if isinstance(e, DataError):
        return tr(e.key).format(**e.params)
    return tr("Unexpected error.") + f"\n\n{type(e).__name__}: {e}"


def layout_direction() -> Qt.LayoutDirection:
    return Qt.LayoutDirection.RightToLeft if i18n.is_rtl() else Qt.LayoutDirection.LeftToRight


class MainWindow(QMainWindow):
    def __init__(self, client: QuranClient | None = None):
        super().__init__()
        self.setWindowTitle("Quran Video Creator")
        self.resize(1440, 900)
        self.setMinimumSize(1200, 700)
        self.client = client or QuranClient()
        self.settings = QSettings("QuranVideoCreator", "QuranVideoCreator")
        self.chapters, self.reciters = [], []
        self.ready = False
        self._loading = True
        self._seq = 0  # length/size requests; older answers are ignored
        self._preview_seq = 0  # the same for preview pictures, which the screen arrows also ask for
        self._screen = 0  # which screen of the selected verses the preview shows
        self._tasks: set[Task] = set()
        self._cancel = threading.Event()
        self._pixmap: QPixmap | None = None
        self._busy = False
        self._info: VideoInfo | None = None  # the last answer, so a language change can redraw the footer
        self._icons: list[tuple[QWidget, str]] = []  # icons re-tinted when the theme changes
        self._relabels: list = []  # functions that redraw translated text when the language changes
        self._info_line = ("", "muted")  # what the footer line says when no warning is flashing
        self._toast_timer = QTimer(self, singleShot=True, interval=TOAST_MS)
        self._toast_timer.timeout.connect(lambda: self._set_info(*self._info_line))
        self.kit = Form(self, self._relabels, self._icons)  # the building blocks below, shared with the manual tab

        self._load_custom_themes()
        i18n.set_language(str(self.settings.value("language", "en")))
        self._qt_translator: QTranslator | None = None
        self._install_qt_translation(i18n.current)
        QApplication.setLayoutDirection(layout_direction())
        for path in (*(f.path for f in FONTS.values()), *(f.marker_path for f in FONTS.values()),
                     SURAH_NAME_FONT, SYMBOL_FONT, TRANSLATION_FONT):
            load_font(path)  # register fonts on the UI thread once; workers then reuse them
        self._build()
        self._timer = QTimer(self, singleShot=True, interval=350)
        self._timer.timeout.connect(self._refresh)
        saved = self.settings.value("ui_theme", "System")
        self.ui_theme.setCurrentIndex(max(0, self.ui_theme.findData(saved)))
        self._apply_ui_theme()
        QGuiApplication.styleHints().colorSchemeChanged.connect(lambda *_: self._apply_ui_theme())
        QApplication.instance().installEventFilter(self)  # to keep tooltips brief
        self._start(lambda: (self.client.chapters(), self.client.reciters()), self._loaded, tr("Loading…"))
        # only the downloaded app: someone running the source updates it with git
        if getattr(sys, "frozen", False) and self.settings.value("check_updates", True, type=bool):
            self._start(self._newer_release, self._got_release)

    def _newer_release(self):
        try:
            return newer_release(self.client.session)
        except Exception:  # offline, rate-limited, GitHub changed: the app works the same without it
            return None

    def _got_release(self, found) -> None:
        if not found:
            return
        version, url = found
        self._reg(lambda: self.update_btn.setText(tr("Update available: {version}").format(version=version)))
        self.update_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(url)))
        self.update_btn.show()

    # ---------------------------------------------------------------- translated building blocks (ui/form.py)
    def _reg(self, fn) -> None:
        self.kit.reg(fn)

    def _text(self, widget, key: str, setter: str = "setText"):
        return self.kit.text(widget, key, setter)

    def _field(self, key: str, widget: QWidget) -> QWidget:
        return self.kit.field(key, widget)

    def _hint(self, key: str, beside: QWidget) -> QToolButton:
        return self.kit.hint(key, beside)

    def _combo(self, items: list[tuple[str, object]]) -> NoWheelCombo:
        return self.kit.combo(items)

    def _slider(self, key: str, name: str) -> tuple[QWidget, NoWheelSlider]:
        return self.kit.slider(key, *SLIDERS[name], self._changed)

    def _card(self, key: str) -> tuple[QFrame, QVBoxLayout]:
        return self.kit.card(key)

    # ---------------------------------------------------------------- building
    def _build(self) -> None:
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header = QFrame()
        header.setObjectName("header")
        h = QHBoxLayout(header)
        h.setContentsMargins(24, 10, 24, 10)
        brand = QLabel("Quran Video Creator")
        brand.setObjectName("brand")
        self.lang_btn = QToolButton()
        self.lang_btn.setObjectName("lang")
        self.lang_btn.setIconSize(QSize(18, 18))
        self._icons.append((self.lang_btn, "translate"))
        self.lang_popup = ListPopup(self)  # a list that scrolls, unlike a menu
        self.lang_popup.chosen.connect(self._set_language)
        self.lang_btn.clicked.connect(self._show_languages)
        self._text(self.lang_btn, "Language", "setToolTip")
        self.ui_theme = self._combo([("System", "System"), ("Light", "Light"), ("Dark", "Dark")])
        self.ui_theme.currentIndexChanged.connect(self._apply_ui_theme)
        about = QPushButton()
        about.clicked.connect(lambda: AboutDialog(self.settings, self).exec())
        self.update_btn = QPushButton()  # shown once a newer release is found
        self.update_btn.setObjectName("primary")
        self.update_btn.hide()
        self.mode_bar = QTabBar()  # Auto mode: the app's recitations and timings; Manual mode: your own recording
        self.mode_bar.setObjectName("modes")
        self.mode_bar.setDrawBase(False)
        self.mode_bar.setExpanding(False)
        self.mode_bar.addTab("")
        self.mode_bar.addTab("")
        self._reg(lambda: (self.mode_bar.setTabText(0, tr("Auto mode")), self.mode_bar.setTabText(1, tr("Manual mode"))))
        h.addWidget(brand)
        h.addSpacing(24)
        h.addWidget(self.mode_bar, 0, Qt.AlignmentFlag.AlignBottom)
        h.addStretch()
        h.addWidget(self.update_btn)
        h.addWidget(self.lang_btn)
        h.addWidget(self.ui_theme)
        h.addWidget(self._text(about, "About"))
        outer.addWidget(header)

        auto_page = QWidget()
        body = QHBoxLayout(auto_page)
        body.setContentsMargins(24, 20, 24, 12)
        body.setSpacing(20)
        self.manual = ManualTab(self.kit, self.client, self._start,
                                lambda: ThemesDialog(self, self._manual_themes_changed).exec(),
                                self._manual_themes_changed, self.settings)
        self.manual.changed.connect(self._apply_info)
        self.pages = QStackedWidget()
        self.pages.addWidget(auto_page)
        self.pages.addWidget(self.manual)
        outer.addWidget(self.pages, 1)
        self.mode_bar.currentChanged.connect(self._mode_changed)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setFixedWidth(PANEL_WIDTH)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.form = QWidget()
        form = QVBoxLayout(self.form)
        form.setContentsMargins(0, 0, 12, 0)
        form.setSpacing(14)
        scroll.setWidget(self.form)
        body.addWidget(scroll)

        self._build_recitation(form)
        self._build_arabic(form)
        self._build_translation(form)
        self._build_layout(form)
        self._build_look(form)
        self._build_output(form)
        form.addStretch()
        self._update_stops()

        right = QVBoxLayout()
        top = QHBoxLayout()
        self.preview_title = QLabel()
        self._relabels.append(self._apply_info)  # the title carries the video length, in the current language
        top.addWidget(self.preview_title)
        self.preview_fmt = NoWheelCombo()
        self.preview_fmt.addItems(FORMATS)
        self.preview_fmt.currentTextChanged.connect(self._changed)
        top.addStretch()
        # Step through every screen of the selected verses: "2 / 7" between two arrows.
        self.prev_screen, self.next_screen = QPushButton(), QPushButton()
        self.screen_label = QLabel()
        self.screen_label.setObjectName("muted")
        for button, key, step in ((self.prev_screen, "Previous screen", -1), (self.next_screen, "Next screen", 1)):
            button.setFixedWidth(36)
            button.clicked.connect(lambda _=False, step=step: self._step_screen(step))
            self._text(button, key, "setToolTip")
        # The arrows point the way the text reads, so they swap in right-to-left languages.
        self._reg(lambda: (self.prev_screen.setText("›" if i18n.is_rtl() else "‹"),
                           self.next_screen.setText("‹" if i18n.is_rtl() else "›")))
        self.screen_nav = QWidget()
        nav = QHBoxLayout(self.screen_nav)
        nav.setContentsMargins(0, 0, 8, 0)
        nav.addWidget(self.prev_screen)
        nav.addWidget(self.screen_label)
        nav.addWidget(self.next_screen)
        self.screen_nav.setVisible(False)
        top.addWidget(self.screen_nav)
        top.addWidget(self.preview_fmt)
        right.addLayout(top)
        self.preview = QLabel()
        self._reg(lambda: None if self._pixmap else self.preview.setText(tr("Loading…")))
        self.preview.setObjectName("preview")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.preview.setMinimumSize(300, 300)
        right.addWidget(self.preview, 1)
        body.addLayout(right, 1)

        footer = QFrame()
        footer.setObjectName("header")
        f = QVBoxLayout(footer)
        f.setContentsMargins(24, 10, 24, 10)
        self.info = QLabel("")
        self.info.setWordWrap(True)
        f.addWidget(self.info)
        row = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setTextVisible(False)
        self.status = QLabel("")
        self.status.setObjectName("muted")
        self.cancel_btn = QPushButton()
        self.cancel_btn.setVisible(False)
        self.cancel_btn.clicked.connect(self._cancel.set)
        self.export_btn = QPushButton()
        self.export_btn.setObjectName("primary")
        self.export_btn.clicked.connect(self._export)
        row.addWidget(self.progress, 1)
        row.addWidget(self.status)
        row.addWidget(self._text(self.cancel_btn, "Cancel"))
        row.addWidget(self.export_btn)
        row.addWidget(self._hint(CREDITS_HINT, self.export_btn))
        f.addLayout(row)
        outer.addWidget(footer)
        self._apply_info()

    # Panel order, top to bottom, follows how a video is made: what is recited, what is shown (Arabic, translation,
    # layout), how it looks, and how it is saved. A control that only matters when another one is set sits
    # directly under that one, indented, and fades when it does not apply (see _dep and _sync_enabled).
    _dep = staticmethod(Form.dep)
    _set_on = staticmethod(Form.set_on)

    def _build_recitation(self, form: QVBoxLayout) -> None:
        frame, lay = self._card("Recitation")
        self.reciter = NoWheelCombo()
        self.surah = NoWheelCombo()
        self.from_v, self.to_v = VerseCombo(), VerseCombo()
        lay.addWidget(self._field("Reciter", self.reciter))
        lay.addWidget(self._field("Surah", self.surah))
        verses = QHBoxLayout()
        verses.setSpacing(12)
        verses.addWidget(self._field("From verse", self.from_v))
        verses.addWidget(self._field("To verse", self.to_v))
        lay.addLayout(verses)
        self.basmala = self._text(QCheckBox(), "Opening Basmala")  # depends on the surah and the first verse
        self._text(self.basmala, "Needs verse 1 of a surah other than Al-Fatihah and At-Tawbah.", "setToolTip")
        self.basmala_dep = self._dep(self.basmala)
        self._set_on(self.basmala_dep, False)
        lay.addWidget(self.basmala_dep)
        self.verse_change = self._combo([("When the verse ends", VERSE_CHANGE_TIMING),
                                         ("When the last word ends", VERSE_CHANGE_LAST_WORD)])
        hint = self._hint(VERSE_CHANGE_HINT, self.verse_change)  # hover for why: the timings can be wrong
        row = QHBoxLayout()
        row.addWidget(self._field("Next verse appears", self.verse_change), 1)
        row.addWidget(hint, 0, Qt.AlignmentFlag.AlignBottom)
        lay.addLayout(row)
        self.surah.currentIndexChanged.connect(self._surah_changed)
        self.from_v.valueChanged.connect(lambda v: self.to_v.setValue(max(v, self.to_v.value())))
        self.to_v.valueChanged.connect(lambda v: self.from_v.setValue(min(v, self.from_v.value())))
        for verse in (self.from_v, self.to_v):  # other verses: the preview starts again at their first screen
            verse.valueChanged.connect(self._first_screen)
            verse.valueChanged.connect(self._changed)
        self.reciter.currentIndexChanged.connect(self._changed)
        self.basmala.toggled.connect(self._changed)
        self.verse_change.currentIndexChanged.connect(self._changed)
        form.addWidget(frame)

    def _build_arabic(self, form: QVBoxLayout) -> None:
        frame, lay = self._card("Arabic")
        self.arabic = self._text(QCheckBox(), "Include Arabic text")
        self.arabic.setChecked(True)
        lay.addWidget(self.arabic)

        inner = QVBoxLayout()
        inner.setContentsMargins(0, 0, 0, 0)
        inner.setSpacing(ITEM_GAP)
        self.font = NoWheelCombo()
        self.font.setItemDelegate(FontDelegate(self.font))
        self.font.view().setMinimumWidth(480)
        for i, (name, spec) in enumerate(FONTS.items()):
            self.font.addItem(name)
            self.font.setItemData(i, load_font(spec.path), FAMILY_ROLE)
            self.font.setItemData(i, FALLBACK_SAMPLE, SAMPLE_ROLE)
        self.font_sample = QLabel("")
        font_col = QWidget()
        col = QVBoxLayout(font_col)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(6)
        col.addWidget(self._field("Quran font", self.font))
        col.addWidget(self.font_sample)  # the sample belongs to the font, so it sits right under it
        inner.addWidget(font_col)
        text_row, self.text_width = self._slider("Text width", "text_width")
        inner.addWidget(text_row)
        self.reveal = self._combo([("All words shown", "off"), ("Words appear as recited", "build"),
                                   ("One word at a time", "single")])
        inner.addWidget(self._field("Words", self.reveal))
        self.highlight = self._combo([("None", "none"), ("Word by word", "word"), ("Keep recited words", "keep")])
        self.highlight.setCurrentIndex(self.highlight.findData("word"))
        inner.addWidget(self._field("Highlight", self.highlight))
        self.hl_fade = self._text(QCheckBox(), "Highlight fade")  # depends on a highlight being on
        self.hl_fade.setChecked(True)
        holder = QWidget()
        holder.setLayout(inner)
        self.arabic_dep = self._dep(holder)
        lay.addWidget(self.arabic_dep)
        # Not inside `holder`: a fade effect nested in another one paints badly in Qt. Two levels deep keeps it
        # visibly under Highlight.
        self.fade_dep = self._dep(self.hl_fade, level=2)
        lay.addWidget(self.fade_dep)

        self.font.currentIndexChanged.connect(self._show_font_sample)
        self.font.currentIndexChanged.connect(self._update_stops)
        for w in (self.font, self.highlight, self.reveal):
            w.currentIndexChanged.connect(self._changed)
        for w in (self.arabic, self.hl_fade):
            w.toggled.connect(self._changed)
        form.addWidget(frame)

    def _build_translation(self, form: QVBoxLayout) -> None:
        frame, lay = self._card("Translation")
        self.translation = NoWheelCombo()
        self._fill_translations(self._default_translation())
        self._relabels.append(self._fill_translations)
        lay.addWidget(self.translation)  # the card's title already names it
        self.tw_row, self.translation_width = self._slider("Translation width", "translation_width")
        self.tw_dep = self._dep(self.tw_row)
        lay.addWidget(self.tw_dep)
        self.translation.currentIndexChanged.connect(self._changed)
        form.addWidget(frame)

    def _build_layout(self, form: QVBoxLayout) -> None:
        frame, lay = self._card("Layout")
        self.full_verse = self._text(QRadioButton(), "Full verse")
        self.in_parts = self._text(QRadioButton(), "Cut at stop signs")
        group = QButtonGroup(self)
        group.addButton(self.full_verse)
        group.addButton(self.in_parts)
        self.in_parts.setChecked(True)
        lay.addWidget(self.full_verse)
        lay.addWidget(self.in_parts)

        self.stop_boxes: dict[str, QCheckBox] = {}
        self.stop_rows: dict[str, QWidget] = {}
        symbol_family = load_font(SYMBOL_FONT)
        stops = QVBoxLayout()
        stops.setContentsMargins(0, 0, 0, 0)
        stops.setSpacing(0)
        for key, stop in STOPS.items():
            cb = QCheckBox(stop.name)  # the names and symbols are the signs' own, so they are not translated
            cb.setMinimumWidth(165)
            cb.setChecked(key in DEFAULT_STOPS)
            cb.toggled.connect(self._changed)
            symbol = QLabel(stop.symbol)
            symbol.setStyleSheet(f'font-family: "{symbol_family}"; font-size: 24px;')
            row = QWidget()
            r = QHBoxLayout(row)
            r.setContentsMargins(0, 0, 0, 0)
            r.addWidget(cb)
            r.addWidget(symbol)
            r.addStretch()
            stops.addWidget(row)
            self.stop_boxes[key], self.stop_rows[key] = cb, row
        self.stops_box = QWidget()
        self.stops_box.setLayout(stops)
        self.stops_dep = self._dep(self.stops_box)
        lay.addWidget(self.stops_dep)
        self.in_parts.toggled.connect(self._changed)

        lay.addSpacing(GROUP_GAP)
        self.surah_name = self._text(QCheckBox(), "Surah name")
        lay.addWidget(self.surah_name)
        self.name_row, self.name_size = self._slider("Surah name size", "name_size")
        self.name_dep = self._dep(self.name_row)
        lay.addWidget(self.name_dep)
        self.surah_name.toggled.connect(self._changed)
        form.addWidget(frame)

    def _build_look(self, form: QVBoxLayout) -> None:
        frame, lay = self._card("Look")
        self.video_theme = NoWheelCombo()
        self.video_theme.setIconSize(QSize(36, 18))
        self._fill_themes(DEFAULT_THEME)
        self._relabels.append(self._relabel_themes)
        custom = self._text(QPushButton(), "Custom")
        custom.clicked.connect(self._open_themes)
        theme_row = QHBoxLayout()
        theme_row.setContentsMargins(0, 0, 0, 0)
        theme_row.addWidget(self.video_theme, 1)
        theme_row.addWidget(custom)
        wrap = QWidget()
        wrap.setLayout(theme_row)
        lay.addWidget(self._field("Themes", wrap))

        lay.addSpacing(GROUP_GAP)
        self.bg = QLineEdit()
        self.bg.setReadOnly(True)
        self._text(self.bg, "None", "setPlaceholderText")
        pick, clear = self._text(QPushButton(), "Choose"), self._text(QPushButton(), "Clear")
        pick.clicked.connect(self._pick_bg)
        clear.clicked.connect(lambda: (self.bg.clear(), self._changed()))
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.bg, 1)
        row.addWidget(pick)
        row.addWidget(clear)
        wrap = QWidget()
        wrap.setLayout(row)
        lay.addWidget(self._field("Background image or video", wrap))
        self.dim_row, self.overlay = self._slider("Background dim", "dim")  # both depend on a background
        self.dim_dep = self._dep(self.dim_row)
        lay.addWidget(self.dim_dep)
        self.bg_end = self._combo([("Loop", "loop"), ("Freeze", "freeze")])
        self.bg_end_row = self._field("If the video is shorter", self.bg_end)
        self.bg_end_dep = self._dep(self.bg_end_row)
        lay.addWidget(self.bg_end_dep)
        self.video_theme.currentIndexChanged.connect(self._changed)
        self.bg_end.currentIndexChanged.connect(self._changed)
        form.addWidget(frame)

    def _build_output(self, form: QVBoxLayout) -> None:
        frame, lay = self._card("Output")
        self.fmt_boxes: dict[str, QCheckBox] = {}
        for name in FORMATS:
            cb = QCheckBox(name)  # the ratio only
            cb.toggled.connect(self._changed)
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.addWidget(cb)
            row.addStretch()
            wrap = QWidget()
            wrap.setLayout(row)
            note = QLabel()
            note.setObjectName("note")
            note.setContentsMargins(26, 0, 0, 0)
            self._text(note, FORMAT_NOTES.get(name, ""))
            item = QVBoxLayout()
            item.setSpacing(0)
            item.addWidget(wrap)
            item.addWidget(note)
            lay.addLayout(item)
            self.fmt_boxes[name] = cb
        self.fmt_boxes[DEFAULT_FORMAT].setChecked(True)
        lay.addSpacing(GROUP_GAP)
        self.quality = self._combo([(q, q) for q in QUALITIES])
        self.quality.setCurrentIndex(self.quality.findData(DEFAULT_QUALITY))
        self.quality.currentIndexChanged.connect(self._changed)
        lay.addWidget(self._field("Quality", self.quality))
        self.out_dir = QLineEdit(str(Path.home() / "Videos"))
        browse = self._text(QPushButton(), "Browse")
        browse.clicked.connect(self._pick_out)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.out_dir, 1)
        row.addWidget(browse)
        wrap = QWidget()
        wrap.setLayout(row)
        lay.addWidget(self._field("Save to", wrap))
        form.addWidget(frame)

    # ---------------------------------------------------------------- data
    def _start(self, fn, on_done, status: str = "", progress: bool = False, on_progress=None) -> Task:
        task = Task(fn, progress)
        self._tasks.add(task)
        task.signals.done.connect(lambda r, t=task: (self._tasks.discard(t), on_done(r)))
        task.signals.failed.connect(lambda e, t=task: (self._tasks.discard(t), self._failed(e)))
        if on_progress:
            task.signals.progress.connect(on_progress)
        if status:
            self.status.setText(status)
        QThreadPool.globalInstance().start(task)
        return task

    def _surah_label(self, c) -> str:
        return f"{c.id}. {c.name_simple} · {tr('{n} verses').format(n=c.verses_count)} · {c.name_arabic}"

    def _loaded(self, data) -> None:
        self.chapters, self.reciters = data
        self.status.setText("")
        for c in self.chapters:
            self.surah.addItem(self._surah_label(c), c.id)
        self._relabels.append(self._relabel_surahs)
        for r in self.reciters:
            self.reciter.addItem(self._reciter_label(r), r.id)
        self._relabels.append(self._relabel_reciters)
        self._restore()
        self.manual.set_chapters(self.chapters)
        self.manual.restore()
        self.mode_bar.setCurrentIndex(int(self.settings.value("mode", 0) or 0))
        self._loading = False
        self.ready = True
        self._surah_changed()
        self._refresh()
        self._start(self._fetch_samples, self._got_samples)

    def _relabel_surahs(self) -> None:
        for i, c in enumerate(self.chapters):
            self.surah.setItemText(i, self._surah_label(c))

    def _relabel_reciters(self) -> None:
        for i, r in enumerate(self.reciters):
            self.reciter.setItemText(i, self._reciter_label(r))

    def _fetch_samples(self) -> dict[str, str]:
        """The whole Basmala (1:1) in each text field, exactly as the API returns it."""
        out = {}
        for field in {f.text_field for f in FONTS.values()}:
            first = self.client.verses(1, field)[0]
            out[field] = " ".join(w.text for w in first.text_words)
        return out

    def _got_samples(self, samples: dict[str, str]) -> None:
        for i, spec in enumerate(FONTS.values()):
            self.font.setItemData(i, samples.get(spec.text_field, FALLBACK_SAMPLE), SAMPLE_ROLE)
        self._show_font_sample()

    def _show_font_sample(self, *_) -> None:
        i = self.font.currentIndex()
        family, sample = self.font.itemData(i, FAMILY_ROLE), self.font.itemData(i, SAMPLE_ROLE)
        self.font_sample.setStyleSheet(f'font-family: "{family}"; font-size: 26px;')
        self.font_sample.setText(sample or "")
        self.font_sample.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.font_sample.setAlignment(Qt.AlignmentFlag.AlignRight)

    def _failed(self, e: Exception) -> None:
        if self._busy:  # an export was running
            self._failed_export(e)
            return
        self.status.setText("")
        if not self.ready and not self.chapters:
            box = QMessageBox(QMessageBox.Icon.Warning, tr("Can't load"), friendly(e),
                              QMessageBox.StandardButton.Retry | QMessageBox.StandardButton.Close, self)
            box.button(QMessageBox.StandardButton.Retry).setText(tr("Retry"))
            box.button(QMessageBox.StandardButton.Close).setText(tr("Close"))
            if box.exec() == QMessageBox.StandardButton.Retry:
                self._start(lambda: (self.client.chapters(), self.client.reciters()), self._loaded, tr("Loading…"))
            return
        self._set_info(friendly(e).split("\n")[0], "error")

    # ---------------------------------------------------------------- themes and language
    def _load_custom_themes(self) -> None:
        try:
            items = json.loads(self.settings.value("custom_themes", "[]"))
        except ValueError:
            items = []
        for d in items:
            try:
                add_custom(make_custom(d["name"], d["bg"], d["highlight"]))
            except (KeyError, ValueError, TypeError):
                pass

    def _fill_themes(self, select: str | None = None) -> None:
        fill_themes(self.video_theme, select)

    def _relabel_themes(self) -> None:
        relabel_themes(self.video_theme)

    def _install_qt_translation(self, code: str) -> None:
        """Qt's own dialogs (colour picker, file chooser, OK/Cancel) in the app's language, where Qt has it."""
        app = QApplication.instance()
        if self._qt_translator is not None:
            app.removeTranslator(self._qt_translator)
            self._qt_translator = None
        translator = QTranslator(app)
        path = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
        if code != "en" and translator.load(QLocale({"zh": "zh_CN"}.get(code, code)), "qtbase", "_", path):
            app.installTranslator(translator)
            self._qt_translator = translator

    def _show_languages(self) -> None:
        self.lang_popup.setLayoutDirection(self.layoutDirection())
        self.lang_popup.show_below(self.lang_btn, [(self._language_label(c), c) for c in i18n.LANGUAGES], i18n.current)

    def _language_label(self, code: str) -> str:
        """A language's name in the app's language, with its own name beside it so it can always be found."""
        here, own = language_name(code, i18n.current), language_name(code, code)
        return here if here == own else f"{here} \u00b7 {own}"

    @staticmethod
    def _reciter_label(r) -> str:
        extra = ", ".join(tr(x) for x in (r.style, r.note) if x)
        name = i18n.reciter_name(r.id, r.name)
        return f"{name} ({extra})" if extra else name

    def _fill_translations(self, select: str | None = None) -> None:
        fill_translations(self.translation, select)

    @staticmethod
    def _default_translation() -> str:
        return key_for_id(i18n.LANGUAGES[i18n.current].translation_id)

    def _open_themes(self) -> None:
        ThemesDialog(self, self._themes_changed).exec()

    def _save_custom_themes(self) -> None:
        self.settings.setValue("custom_themes", json.dumps(
            [{"name": t.name, "bg": t.bg, "highlight": t.highlight} for t in custom_themes()]))

    def _themes_changed(self, name: str | None) -> None:
        """A theme was saved (its name, selected in this tab) or deleted (None)."""
        self._save_custom_themes()
        self._fill_themes(name)
        self.manual.refill_themes()
        self._changed()

    def _manual_themes_changed(self, name: str | None) -> None:
        self._save_custom_themes()
        self._fill_themes()
        self.manual.refill_themes(name)
        self.manual._changed()

    def _set_language(self, code: str) -> None:
        """Translate the whole window, flip it for right-to-left languages, and pick that language's Quran
        translation as the default."""
        i18n.set_language(code)
        self._install_qt_translation(code)
        QApplication.setLayoutDirection(layout_direction())
        for redraw in self._relabels:
            redraw()
        self.translation.setCurrentIndex(self.translation.findData(self._default_translation()))
        self.settings.setValue("language", code)
        self._changed()

    # ---------------------------------------------------------------- state
    def _manual_mode(self) -> bool:
        return self.mode_bar.currentIndex() == 1

    def _mode_changed(self, i: int) -> None:
        self.pages.setCurrentIndex(i)
        if not self._loading:
            self.settings.setValue("mode", i)
        self._apply_info()

    def _chapter(self):
        return next((c for c in self.chapters if c.id == self.surah.currentData()), None)

    def _first_screen(self, *_) -> None:
        self._screen = 0

    def _surah_changed(self) -> None:
        c = self._chapter()
        if not c:
            return
        self._first_screen()
        for s in (self.from_v, self.to_v):
            s.blockSignals(True)
            s.setMaximum(c.verses_count)
        self.from_v.setValue(min(self.from_v.value(), c.verses_count))
        self.to_v.setValue(min(max(self.to_v.value(), self.from_v.value()), c.verses_count))
        for s in (self.from_v, self.to_v):
            s.blockSignals(False)
        self._changed()

    def _update_stops(self, *_) -> None:
        """Show only the stop signs the selected font's mushaf style supports."""
        ok = set(supported(FONTS[self.font.currentText()].style))
        for key, row in self.stop_rows.items():
            row.setVisible(key in ok)

    def _sync_enabled(self, toast: bool = True) -> None:
        """Fade out the options that make no sense with the current choices."""
        chapter = self.surah.currentData()
        if chapter is not None and self.basmala.isChecked() and not basmala_available(chapter, self.from_v.value()):
            self.basmala.blockSignals(True)  # the range moved away from verse 1: switch it off at once, say why
            self.basmala.setChecked(False)
            self.basmala.blockSignals(False)
            if toast:
                self._toast(tr("Needs verse 1 of a surah other than Al-Fatihah and At-Tawbah."))
        no_translation = self.translation.currentData() == "None"
        if no_translation and not self.arabic.isChecked():  # something has to be on screen
            self.arabic.blockSignals(True)
            self.arabic.setChecked(True)
            self.arabic.blockSignals(False)
        arabic = self.arabic.isChecked()
        self.arabic.setEnabled(not no_translation)  # with no translation, the Arabic is all there is
        set_item_enabled(self.translation, "None", arabic)  # and with no Arabic, the translation is
        self._set_on(self.arabic_dep, arabic)
        self._set_on(self.fade_dep, arabic and self.highlight.currentData() != "none")
        self._set_on(self.tw_dep, not no_translation)
        self._set_on(self.stops_dep, self.in_parts.isChecked())
        self._set_on(self.name_dep, self.surah_name.isChecked())
        bg = Path(self.bg.text()) if self.bg.text() else None
        self._set_on(self.dim_dep, bg is not None)
        if not is_video(bg):
            self._set_on(self.bg_end_dep, False)  # for a video, the length check in _got_info decides
        # a single word on screen has no recited words to keep lit, and vice versa
        set_item_enabled(self.highlight, "keep", self.reveal.currentData() != "single")
        set_item_enabled(self.reveal, "single", self.highlight.currentData() != "keep")

    def _job(self, fmt: str) -> ExportJob:
        reciter = next(r for r in self.reciters if r.id == self.reciter.currentData())
        stops = tuple(k for k in supported(FONTS[self.font.currentText()].style) if self.stop_boxes[k].isChecked())
        return ExportJob(
            chapter=self.surah.currentData(), v_from=self.from_v.value(), v_to=self.to_v.value(), reciter=reciter,
            fmt=fmt, out_dir=Path(self.out_dir.text()), font=self.font.currentText(),
            theme=self.video_theme.currentData(), split=SPLIT_PARTS if self.in_parts.isChecked() else SPLIT_VERSE,
            highlight=self.highlight.currentData(), highlight_fade=self.hl_fade.isChecked(),
            reveal=self.reveal.currentData(), show_arabic=self.arabic.isChecked(),
            surah_name=self.surah_name.isChecked(), translation=self.translation.currentData(),
            overlay=self.overlay.value() / 100, quality=self.quality.currentData(),
            text_width=self.text_width.value() / 100, translation_width=self.translation_width.value() / 100,
            name_scale=self.name_size.value() / 100, bg_end=self.bg_end.currentData(),
            background=Path(self.bg.text()) if self.bg.text() else None,
            basmala=self.basmala.isChecked() and self.basmala.isEnabled(), stops=stops,
            verse_change=self.verse_change.currentData())

    def _save(self) -> None:
        self.settings.setValue("state", json.dumps({
            "surah": self.surah.currentData(), "from": self.from_v.value(), "to": self.to_v.value(),
            "reciter": self.reciter.currentData(), "formats": [f for f, c in self.fmt_boxes.items() if c.isChecked()],
            "preview": self.preview_fmt.currentText(), "font": self.font.currentText(),
            "highlight": self.highlight.currentData(), "hl_fade": self.hl_fade.isChecked(),
            "reveal": self.reveal.currentData(), "parts": self.in_parts.isChecked(),
            "stops": [n for n, c in self.stop_boxes.items() if c.isChecked()],
            "arabic": self.arabic.isChecked(), "name": self.surah_name.isChecked(),
            "name_size": self.name_size.value(), "basmala": self.basmala.isChecked(),
            "verse_change": self.verse_change.currentData(),
            "translation": self.translation.currentData(), "translation_width": self.translation_width.value(),
            "theme": self.video_theme.currentData(), "text_width": self.text_width.value(),
            "dim": self.overlay.value(), "bg": self.bg.text(), "bg_end": self.bg_end.currentData(),
            "quality": self.quality.currentData(), "out": self.out_dir.text()}))
        self.settings.setValue("ui_theme", self.ui_theme.currentData())
        self.settings.setValue("version", SETTINGS_VERSION)

    def _restore(self) -> None:
        try:
            s = json.loads(self.settings.value("state", "{}"))
        except ValueError:
            s = {}
        if int(self.settings.value("version", 0)) != SETTINGS_VERSION:
            s = {}  # defaults changed since these were saved: start from the new defaults

        def pick(combo: QComboBox, value, by_data=True) -> None:
            i = combo.findData(value) if by_data else combo.findText(value)
            if i >= 0:
                combo.setCurrentIndex(i)
        pick(self.surah, s.get("surah"))
        c = self._chapter()
        if c:
            for sp in (self.from_v, self.to_v):
                sp.setMaximum(c.verses_count)
            self.from_v.setValue(s.get("from", 1))
            self.to_v.setValue(s.get("to", min(7, c.verses_count)))
        pick(self.reciter, s.get("reciter", DEFAULT_RECITER))
        for f, cb in self.fmt_boxes.items():
            cb.setChecked(f in s.get("formats", [DEFAULT_FORMAT]))
        pick(self.preview_fmt, s.get("preview", DEFAULT_FORMAT), False)
        pick(self.font, s.get("font", DEFAULT_FONT), False)
        self._update_stops()
        pick(self.highlight, s.get("highlight", "word"))
        self.hl_fade.setChecked(s.get("hl_fade", True))
        pick(self.reveal, s.get("reveal", "off"))
        if self.reveal.currentData() == "single" and self.highlight.currentData() == "keep":
            pick(self.highlight, "word")
        (self.in_parts if s.get("parts", True) else self.full_verse).setChecked(True)
        for n, cb in self.stop_boxes.items():
            cb.setChecked(n in s.get("stops", DEFAULT_STOPS))
        self.arabic.setChecked(s.get("arabic", True))
        self.surah_name.setChecked(s.get("name", False))
        self.name_size.setValue(s.get("name_size", SLIDERS["name_size"][2]))
        self.basmala.setChecked(s.get("basmala", False))
        pick(self.verse_change, s.get("verse_change", VERSE_CHANGE_TIMING))
        pick(self.translation, s.get("translation", self._default_translation()))
        self.translation_width.setValue(s.get("translation_width", SLIDERS["translation_width"][2]))
        self._fill_themes(s.get("theme", DEFAULT_THEME))
        self.text_width.setValue(s.get("text_width", SLIDERS["text_width"][2]))
        self.overlay.setValue(s.get("dim", SLIDERS["dim"][2]))
        self.bg.setText(s.get("bg", "") if Path(s.get("bg", "")).is_file() else "")
        pick(self.bg_end, s.get("bg_end", "loop"))
        pick(self.quality, s.get("quality", DEFAULT_QUALITY))
        if s.get("out"):
            self.out_dir.setText(s["out"])
        self._sync_enabled(toast=False)

    def _changed(self, *_) -> None:
        if self._loading:
            return
        self._sync_enabled()
        self._save()
        self._timer.start()

    # ---------------------------------------------------------------- preview and info
    def _refresh(self) -> None:
        if not self.ready or self._busy:
            return
        self._seq += 1
        seq = self._seq
        job = self._job(self.preview_fmt.currentText())
        self._start(lambda: video_info(job, self.client), lambda r: self._got_info(seq, r))
        self._refresh_preview()

    def _refresh_preview(self) -> None:
        if not self.ready or self._busy:
            return
        self._preview_seq += 1
        seq, screen = self._preview_seq, self._screen
        job = self._job(self.preview_fmt.currentText())
        self._start(lambda: preview_image(job, self.client, screen), lambda r: self._got_preview(seq, r))

    def _step_screen(self, step: int) -> None:
        self._screen += step  # the core keeps it within the screens there are
        self._refresh_preview()

    def _got_info(self, seq: int, info: VideoInfo) -> None:
        if seq != self._seq:
            return
        self._info = info
        self._set_on(self.basmala_dep, info.basmala_ok)
        if not info.basmala_ok and self.basmala.isChecked():
            self.basmala.blockSignals(True)
            self.basmala.setChecked(False)
            self.basmala.blockSignals(False)
            self._toast(tr("Needs verse 1 of a surah other than Al-Fatihah and At-Tawbah."))  # why it switched off
        # The loop/freeze choice only matters when the background video is shorter than the recitation.
        self._set_on(self.bg_end_dep, info.bg_seconds is not None and info.bg_seconds < info.seconds - 0.05)
        self._apply_info()

    def _apply_info(self) -> None:
        if self._manual_mode():
            self._apply_manual_info()
            return
        info = self._info
        self.preview_title.setText(f"{tr('Preview')} · {fmt_duration(info.seconds)}" if info else tr("Preview"))
        if not info:
            self.export_btn.setText(tr("Export"))
            return
        if self._busy:  # the footer line shows the time left while exporting
            return
        formats = sum(1 for c in self.fmt_boxes.values() if c.isChecked())
        bg = Path(self.bg.text()) if self.bg.text() else None
        size = estimate_bytes(info.seconds, bg, self.quality.currentData()) * max(1, formats)
        wait = estimate_seconds(info.seconds, bg, self.quality.currentData()) * max(1, formats)
        text, kind = tr("Estimated time: {t}").format(t=fmt_duration(wait)), "muted"
        if info.problem:
            text, kind = friendly(info.problem), "error"
        self._info_line = (text, kind)
        if not self._toast_timer.isActive():  # a flashing warning is not overwritten
            self._set_info(text, kind)
        self.export_btn.setEnabled(info.problem is None)
        self.export_btn.setText(tr("Export") if info.problem else f"{tr('Export')} · {fmt_size(size)}")

    def _apply_manual_info(self) -> None:
        """The footer for the manual tab: its length, how long the export takes, or why it can't be made yet."""
        if self._busy:
            return
        seconds, problem = self.manual.seconds(), self.manual.problem()
        job = self.manual.job()
        formats = max(1, len(self.manual.formats()))
        bg = job.background or next((b.background for b in job.batches if b.background), None)
        if problem is not None or not seconds:
            text, kind = (friendly(problem), "warn") if problem else ("", "muted")
            self.export_btn.setEnabled(False)
            self.export_btn.setText(tr("Export"))
        else:
            wait = estimate_seconds(seconds, bg, job.quality) * formats
            text, kind = tr("Estimated time: {t}").format(t=fmt_duration(wait)), "muted"
            self.export_btn.setEnabled(True)
            size = estimate_bytes(seconds, bg, job.quality) * formats
            self.export_btn.setText(f"{tr('Export')} · {fmt_size(size)}")
        self._info_line = (text, kind)
        if not self._toast_timer.isActive():
            self._set_info(text, kind)

    def _toast(self, text: str) -> None:
        """A warning that shows in the footer for a few seconds, then gives way to the normal line."""
        self._set_info(text, "warn")
        self._toast_timer.start()

    def eventFilter(self, obj, event) -> bool:
        """Tooltips disappear after TIP_MS instead of lingering while the pointer rests on the control."""
        if event.type() == QEvent.Type.ToolTip and isinstance(obj, QWidget) and obj.toolTip():
            tip = obj.toolTip()  # a long one stays long enough to read
            QToolTip.showText(event.globalPos(), tip, obj, QRect(), max(TIP_MS, 60 * len(tip)))
            return True
        return super().eventFilter(obj, event)

    def _set_info(self, text: str, kind: str) -> None:
        self.info.setObjectName(kind)
        self.info.style().unpolish(self.info)  # the object name drives the colour in the stylesheet
        self.info.style().polish(self.info)
        self.info.setText(text)

    def _got_preview(self, seq: int, result) -> None:
        if seq != self._preview_seq:
            return
        img, self._screen, count = result
        self._pixmap = QPixmap.fromImage(img)
        self._show_pixmap()
        self.screen_nav.setVisible(count > 1)
        self.screen_label.setText(f"{self._screen + 1} / {count}")
        self.prev_screen.setEnabled(self._screen > 0)
        self.next_screen.setEnabled(self._screen < count - 1)

    def _show_pixmap(self) -> None:
        if self._pixmap:
            self.preview.setPixmap(self._pixmap.scaled(self.preview.size() - QSize(6, 6),
                                                       Qt.AspectRatioMode.KeepAspectRatio,
                                                       Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self._show_pixmap()

    # ---------------------------------------------------------------- actions
    def _pick_bg(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, tr("Background image or video"), str(Path.home()), MEDIA_FILTER)
        if path:
            self.bg.setText(path)
            self._changed()

    def _pick_out(self) -> None:
        path = QFileDialog.getExistingDirectory(self, tr("Save to"), self.out_dir.text())
        if path:
            self.out_dir.setText(path)
            self._changed()

    def _apply_ui_theme(self, *_) -> None:
        mode = self.ui_theme.currentData() or "System"
        self.setStyleSheet(stylesheet(mode))
        self.manual.set_colors(PALETTES[resolve(mode)])
        color = PALETTES[resolve(mode)]["muted"]
        for widget, name in self._icons:
            px = pixmap(name, color)
            if isinstance(widget, QToolButton):
                widget.setIcon(QIcon(px))
            else:
                widget.setPixmap(px)
        if not self._loading:
            self._save()

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.form.setEnabled(not busy)
        self.screen_nav.setEnabled(not busy)
        self.manual.set_busy(busy)
        self.mode_bar.setEnabled(not busy)
        self.export_btn.setVisible(not busy)
        self.cancel_btn.setVisible(busy)
        self.progress.setValue(0)

    def _export(self) -> None:
        if self._manual_mode():
            self._export_manual()
            return
        if not self._info:  # the length is not known yet, so there is no size or time to work with
            return
        formats = [f for f, c in self.fmt_boxes.items() if c.isChecked()]
        if not formats:
            QMessageBox.information(self, tr("Output"), tr("Tick at least one format."))
            return
        out = Path(self.out_dir.text())
        try:
            out.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            QMessageBox.warning(self, tr("Output"), tr("Can't use that folder.") + f"\n\n{e}")
            return
        jobs = [self._job(f) for f in formats]
        self._cancel.clear()
        self._set_busy(True)

        bg = Path(self.bg.text()) if self.bg.text() else None
        sizes = [estimate_bytes(self._info.seconds, bg, job.quality) for job in jobs]
        started = time.monotonic()

        def run(progress):
            paths, done, warnings = [], 0, []
            for i, job in enumerate(jobs):
                part = job.out_dir / (job.filename + ".part")

                def report(f, i=i, part=part, done=done):
                    total_f = (i + f) / len(jobs)
                    try:
                        written = done + part.stat().st_size
                    except OSError:
                        written = done
                    status = f"{fmt_size(written)} / {fmt_size(max(sum(sizes), written))}"
                    left = (time.monotonic() - started) * (1 - total_f) / total_f if total_f > 0.02 else None
                    eta = tr("{t} left").format(t=fmt_duration(left)) if left is not None else ""
                    progress(total_f, status + "\n" + eta)

                def downloading(got, total, i=i):  # the first export of a surah downloads its recitation
                    text = tr("Downloading the recitation: {done} of {total}")
                    progress(i / len(jobs), "\n" + text.format(done=fmt_size(got), total=fmt_size(max(total, got))))

                # also writes the credits file
                paths.append(export(job, self.client, report, self._cancel.is_set, downloading, warnings.append))
                done += paths[-1].stat().st_size
            return paths, warnings[:1], credits(jobs[0])  # each format hits the same problem: say it once

        self._start(run, self._export_done, tr("Exporting…"), True, self._on_export_progress)

    def _export_manual(self) -> None:
        jobs, seconds = self.manual.jobs(), self.manual.seconds()
        if not jobs:
            QMessageBox.information(self, tr("Output"), tr("Tick at least one format."))
            return
        if self.manual.problem() is not None or not seconds:
            return
        try:
            jobs[0].out_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            QMessageBox.warning(self, tr("Output"), tr("Can't use that folder.") + f"\n\n{e}")
            return
        self._cancel.clear()
        self._set_busy(True)
        bg = jobs[0].background or next((b.background for b in jobs[0].batches if b.background), None)
        total = sum(estimate_bytes(seconds, bg, job.quality) for job in jobs)
        started = time.monotonic()

        def run(progress):
            paths, done, warnings = [], 0, []
            for i, job in enumerate(jobs):
                part = job.out_dir / (job.filename + ".part")

                def report(f, i=i, part=part, done=done):
                    total_f = (i + f) / len(jobs)
                    try:
                        written = done + part.stat().st_size
                    except OSError:
                        written = done
                    left = (time.monotonic() - started) * (1 - total_f) / total_f if total_f > 0.02 else None
                    eta = tr("{t} left").format(t=fmt_duration(left)) if left is not None else ""
                    progress(total_f, f"{fmt_size(written)} / {fmt_size(max(total, written))}\n{eta}")

                paths.append(export_manual(job, self.client, report, self._cancel.is_set, warnings.append))
                done += paths[-1].stat().st_size
            return paths, warnings[:1], manual_credits(jobs[0])

        self._start(run, self._export_done, tr("Exporting…"), True, self._on_export_progress)

    def _on_export_progress(self, f: float, text: str) -> None:
        status, eta = text.split("\n", 1)
        self.progress.setValue(int(f * 1000))
        self.status.setText(status)
        self._info_line = (eta, "muted")
        if not self._toast_timer.isActive():
            self._set_info(*self._info_line)

    def _export_done(self, result) -> None:
        paths, warnings, caption = result
        folder = str(paths[0].parent) if paths else self.out_dir.text()
        self._set_busy(False)
        if paths:
            QApplication.clipboard().setText(caption)  # the credits only: a timing note stays in the file
        self.status.setText("")
        self._apply_info()
        box = QMessageBox(QMessageBox.Icon.Warning if warnings else QMessageBox.Icon.Information, tr("Done"),
                          tr("Saved {n} video(s) to").format(n=len(paths)) + f"\n{folder}\n\n"
                          + tr("Credits for the caption were saved next to each video and copied to the clipboard.")
                          + "".join(f"\n\n{friendly(w)}" for w in warnings),
                          QMessageBox.StandardButton.Ok, self)
        open_btn = box.addButton(tr("Open folder"), QMessageBox.ButtonRole.ActionRole)
        box.exec()
        if box.clickedButton() is open_btn:
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def _failed_export(self, e: Exception) -> None:
        self._set_busy(False)
        self.status.setText("")
        self._apply_info()
        if isinstance(e, Cancelled):
            self.status.setText(tr("Cancelled"))
            return
        QMessageBox.critical(self, tr("Export failed"), friendly(e))


def run() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Quran Video Creator")
    app.setApplicationVersion(__version__)
    # Match the Linux menu entry (packaging/quran-video-creator.desktop) so Wayland desktops show its icon
    app.setDesktopFileName("quran-video-creator")
    app.setWindowIcon(QIcon(f"{ASSETS}/app.png"))
    win = MainWindow()
    win.show()
    return app.exec()
