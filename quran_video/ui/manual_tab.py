"""The Manual mode tab: the user's own recording, batches picked on the mushaf, and times set while it plays.

The left side is a row of steps (Recording, Batches, Translation, Look, Output). The Batches step lists every batch
as a card. A click on a card chooses that batch, and only then do clicks on the mushaf change its words: Add new
batch chooses a new, empty one. With nothing chosen, clicking the mushaf does nothing.

The tab only builds widgets and keeps the batches; core.manual does the work, and the window around it runs the
export. What it needs from the window comes in as functions (start a task, open the theme editor, save the
custom themes), so it never reaches into the window itself."""

import json
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QTimer, Signal
from PySide6.QtGui import QCursor, QKeySequence, QShortcut
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QMenu,
                               QMessageBox, QPushButton, QRadioButton, QScrollArea, QStackedWidget, QTabBar,
                               QVBoxLayout, QWidget)

from .. import i18n
from ..api.models import Chapter
from ..config.fonts import DEFAULT_FONT, FONTS
from ..config.presets import DEFAULT_FORMAT, FORMAT_NOTES, FORMATS
from ..config.quality import DEFAULT_QUALITY, QUALITIES
from ..config.themes import DEFAULT_THEME, is_builtin
from ..config.translations import key_for_id
from ..core.ffmpeg import has_audio, is_video, media_seconds
from ..core.manual import (PAGES, PROJECT_SUFFIX, TRANS_ATTACHED, TRANS_TRACK, Batch, ManualJob, TokenRange,
                           TransBatch, check, file_end, first_page, from_json, label, mushaf_page, page_of,
                           spaced_translation, to_json, trans_text, verse_tokens, words_of)
from ..core.manual_export import verse_source
from ..core.render import load_font
from ..core.timing import DataError
from ..i18n import tr
from .batch_list import BACKGROUND, MOVE, REMOVE, TRANSLATION, BatchList, CardInfo
from .form import (GROUP_GAP, MEDIA_FILTER, PANEL_WIDTH, SLIDERS, Form, clock, fill_themes, fill_translations,
                   fmt_duration, ltr, relabel_themes, set_item_enabled)
from .mushaf import Mark, MushafView, TokenView
from .widgets import NoWheelCombo, VerseCombo

MANUAL_VERSION = 1  # of what is kept in the settings; a mismatch starts the tab empty
AUDIO_FILTER = ("Audio and video (*.mp3 *.m4a *.aac *.wav *.ogg *.opus *.flac *.mp4 *.mov *.mkv *.webm *.avi);;"
                "All files (*)")
STEPS = ("Recording", "Batches", "Translation", "Look", "Output")
ARABIC, ATTACHED, TRACK = "arabic", "attached", "track"  # what the chosen card changes: its words, its translation
PREVIEW_WORDS = 7  # how many words a card shows


class ManualTab(QWidget):
    changed = Signal()  # the footer (length, problems, size) needs drawing again

    def __init__(self, kit: Form, client, start, open_themes, themes_changed, settings: QSettings):
        super().__init__()
        self.kit, self.client, self.start = kit, client, start
        self.open_themes, self.themes_changed, self.settings = open_themes, themes_changed, settings
        self.chapters: list[Chapter] = []
        self.batches: list[Batch] = []
        self.trans_batches: list[TransBatch] = []
        # The batch the next clicks change: (ARABIC, k) its words, (ATTACHED, k) its translation, (TRACK, k) a
        # translation batch's words. k == len(...) is a new one, added once its last word is clicked. None: no
        # batch is chosen, and clicks on the page do nothing.
        self.target: tuple[str, int] | None = None
        self.trim: tuple[int, int | None] = (0, None)  # the part of the recording the video uses
        self.audio_ms: int | None = None  # the recording's length, once read
        self.has_sound = True
        self._translation = ""  # the translation the ranges were picked in
        self._previews: dict[tuple, str] = {}  # (font or translation, first, last) -> the first words
        self._previews_asked: set[tuple] = set()  # being worked out now
        self._page_seq = self._probe_seq = 0
        self._sources: dict = {}
        self._loading = True
        self._save_timer = QTimer(self, singleShot=True, interval=400)
        self._save_timer.timeout.connect(self.save)
        self._build()
        escape = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        escape.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        escape.activated.connect(self._deselect)

    # ---------------------------------------------------------------- building
    def _build(self) -> None:
        kit = self.kit
        outer = QHBoxLayout(self)
        outer.setContentsMargins(24, 14, 24, 12)
        outer.setSpacing(20)
        left = QVBoxLayout()
        left.setSpacing(12)
        self.steps = QTabBar()  # one step at a time, so the batches get the whole column
        self.steps.setObjectName("steps")
        self.steps.setDrawBase(False)
        self.steps.setExpanding(False)
        for _ in STEPS:
            self.steps.addTab("")
        kit.reg(lambda: [self.steps.setTabText(i, f"{i + 1}  {tr(key)}") for i, key in enumerate(STEPS)])
        left.addWidget(self.steps)
        self.pages = QStackedWidget()
        left.addWidget(self.pages, 1)
        self.steps.currentChanged.connect(self._step_changed)
        for build in (self._build_recording, self._build_batches, self._build_translation, self._build_look,
                      self._build_output):
            self.pages.addWidget(build())
        holder = QWidget()
        holder.setLayout(left)
        holder.setFixedWidth(PANEL_WIDTH)
        outer.addWidget(holder)
        outer.addLayout(self._build_picker(), 1)
        kit.relabels.append(self._relabel)

    @staticmethod
    def _scrolled(*widgets: QWidget) -> QScrollArea:
        """A step whose cards can be taller than the window."""
        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(0, 0, 12, 0)
        lay.setSpacing(14)
        for w in widgets:
            lay.addWidget(w)
        lay.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(inner)
        return scroll

    def _file_row(self, edit: QLineEdit, pick, clear) -> QWidget:
        """A read-only path with Choose and Clear beside it."""
        edit.setReadOnly(True)
        self.kit.text(edit, "None", "setPlaceholderText")
        choose, remove = self.kit.text(QPushButton(), "Choose"), self.kit.text(QPushButton(), "Clear")
        choose.clicked.connect(pick)
        remove.clicked.connect(clear)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(edit, 1)
        row.addWidget(choose)
        row.addWidget(remove)
        box = QWidget()
        box.setLayout(row)
        return box

    def _buttons(self, *buttons: tuple[str, object]) -> tuple[QWidget, list[QPushButton]]:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        made = []
        for key, slot in buttons:
            b = self.kit.text(QPushButton(), key)
            b.clicked.connect(slot)
            row.addWidget(b)
            made.append(b)
        row.addStretch()
        box = QWidget()
        box.setLayout(row)
        return box, made

    def _build_recording(self) -> QWidget:
        kit = self.kit
        frame, lay = kit.card("Recording")
        self.audio = QLineEdit()
        lay.addWidget(kit.field("Audio or video file", self._file_row(self.audio, self._pick_audio,
                                                                      lambda: self._set_audio(""))))
        self.length = QLabel()
        self.length.setObjectName("muted")
        lay.addWidget(self.length)
        self.reciter_name = QLineEdit()
        self.reciter_name.textChanged.connect(self._changed)
        lay.addWidget(kit.field("Reciter name (for the credits)", self.reciter_name))
        return self._scrolled(frame)

    def _build_batches(self) -> QWidget:
        """Add new batch on top, every batch as a card under it (scrolling), Set times at the foot."""
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        self.add_btn = self.kit.text(QPushButton(), "Add new batch")
        self.add_btn.clicked.connect(lambda: self._select(ARABIC, len(self.batches)))
        lay.addWidget(self.add_btn)
        self.cards = BatchList()
        self.cards.chosen.connect(lambda k: self._select(ARABIC, k))
        self.cards.translation.connect(lambda k: self._select(ATTACHED, k))
        self.cards.background.connect(self._card_background)
        self.cards.moved.connect(self._move)
        self.cards.removed.connect(self._remove)
        lay.addWidget(self.cards, 1)
        self.times_btn = self.kit.text(QPushButton(), "Set times")
        self.times_btn.setObjectName("primary")
        self.times_btn.clicked.connect(self._open_timing)
        lay.addWidget(self.times_btn)
        return page

    def _build_translation(self) -> QWidget:
        kit = self.kit
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(10)
        frame, lay = kit.card("Translation")
        self.translation = NoWheelCombo()
        fill_translations(self.translation, key_for_id(i18n.LANGUAGES[i18n.current].translation_id))
        kit.relabels.append(lambda: fill_translations(self.translation))
        self.translation.currentIndexChanged.connect(self._translation_changed)
        lay.addWidget(self.translation)
        self.attached = kit.text(QRadioButton(), "With each batch")
        self.track = kit.text(QRadioButton(), "On their own times")
        group = QButtonGroup(self)
        group.addButton(self.attached)
        group.addButton(self.track)
        self.attached.setChecked(True)
        self.track.toggled.connect(self._mode_changed)
        lay.addWidget(self.attached)
        lay.addWidget(self.track)
        self.tw_row, self.translation_width = kit.slider("Translation width", *SLIDERS["translation_width"],
                                                         self._changed)
        self.tw_dep = kit.dep(self.tw_row)
        lay.addWidget(self.tw_dep)
        outer.addWidget(frame)
        # "On their own times": the translation batches, listed the same way as the Arabic ones
        self.add_trans_btn = kit.text(QPushButton(), "Add translation batch")
        self.add_trans_btn.clicked.connect(lambda: self._select(TRACK, len(self.trans_batches)))
        outer.addWidget(self.add_trans_btn)
        self.trans_cards = BatchList()
        self.trans_cards.chosen.connect(lambda k: self._select(TRACK, k))
        self.trans_cards.moved.connect(self._move_trans)
        self.trans_cards.removed.connect(self._remove_trans)
        outer.addWidget(self.trans_cards, 1)
        self.track_spacer = QWidget()
        outer.addWidget(self.track_spacer, 1)
        return page

    def _build_look(self) -> QWidget:
        kit = self.kit
        frame, lay = kit.card("Look")
        self.font = NoWheelCombo()
        self.font.addItems(list(FONTS))
        self.font.currentIndexChanged.connect(self._font_changed)
        lay.addWidget(kit.field("Quran font", self.font))
        self.video_theme = NoWheelCombo()
        fill_themes(self.video_theme, DEFAULT_THEME)
        kit.relabels.append(lambda: relabel_themes(self.video_theme))
        self.video_theme.currentIndexChanged.connect(self._changed)
        custom = kit.text(QPushButton(), "Custom")
        custom.clicked.connect(self.open_themes)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.video_theme, 1)
        row.addWidget(custom)
        box = QWidget()
        box.setLayout(row)
        lay.addWidget(kit.field("Themes", box))
        self.reveal = kit.combo([("All words shown", "off"), ("Words appear as recited", "build"),
                                 ("One word at a time", "single")])
        lay.addWidget(kit.field("Words", self.reveal))
        self.highlight = kit.combo([("None", "none"), ("Word by word", "word"), ("Keep recited words", "keep")])
        lay.addWidget(kit.field("Highlight", self.highlight))
        self.hl_fade = kit.text(QCheckBox(), "Highlight fade")
        self.hl_fade.setChecked(True)
        self.fade_dep = kit.dep(self.hl_fade)
        lay.addWidget(self.fade_dep)
        for w in (self.reveal, self.highlight):
            w.currentIndexChanged.connect(self._changed)
        self.hl_fade.toggled.connect(self._changed)
        text_row, self.text_width = kit.slider("Text width", *SLIDERS["text_width"], self._changed)
        lay.addWidget(text_row)
        lay.addSpacing(GROUP_GAP)
        self.surah_name = kit.text(QCheckBox(), "Surah name")
        self.surah_name.toggled.connect(self._changed)
        lay.addWidget(self.surah_name)
        name_row, self.name_size = kit.slider("Surah name size", *SLIDERS["name_size"], self._changed)
        self.name_dep = kit.dep(name_row)
        lay.addWidget(self.name_dep)
        lay.addSpacing(GROUP_GAP)
        self.bg = QLineEdit()
        lay.addWidget(kit.field("Background image or video", self._file_row(
            self.bg, self._pick_bg, lambda: (self.bg.clear(), self._changed()))))
        dim_row, self.overlay = kit.slider("Background dim", *SLIDERS["dim"], self._changed)
        self.dim_dep = kit.dep(dim_row)
        lay.addWidget(self.dim_dep)
        self.bg_end = kit.combo([("Loop", "loop"), ("Freeze", "freeze")])
        self.bg_end.currentIndexChanged.connect(self._changed)
        self.bg_end_dep = kit.dep(kit.field("If the video is shorter", self.bg_end))
        lay.addWidget(self.bg_end_dep)
        return self._scrolled(frame)

    def _build_output(self) -> QWidget:
        kit = self.kit
        frame, lay = kit.card("Output")
        self.fmt_boxes: dict[str, QCheckBox] = {}
        for name in FORMATS:
            cb = QCheckBox(name)  # the ratio only
            cb.toggled.connect(self._changed)
            note = QLabel()
            note.setObjectName("note")
            note.setContentsMargins(26, 0, 0, 0)
            kit.text(note, FORMAT_NOTES.get(name, ""))
            item = QVBoxLayout()
            item.setSpacing(0)
            item.addWidget(cb)
            item.addWidget(note)
            lay.addLayout(item)
            self.fmt_boxes[name] = cb
        self.fmt_boxes[DEFAULT_FORMAT].setChecked(True)
        lay.addSpacing(GROUP_GAP)
        self.quality = kit.combo([(q, q) for q in QUALITIES])
        self.quality.setCurrentIndex(self.quality.findData(DEFAULT_QUALITY))
        self.quality.currentIndexChanged.connect(self._changed)
        lay.addWidget(kit.field("Quality", self.quality))
        self.out_dir = QLineEdit(str(Path.home() / "Videos"))
        self.out_dir.textChanged.connect(self._changed)
        browse = kit.text(QPushButton(), "Browse")
        browse.clicked.connect(self._pick_out)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.out_dir, 1)
        row.addWidget(browse)
        box = QWidget()
        box.setLayout(row)
        lay.addWidget(kit.field("Save to", box))
        self.file_name = QLineEdit()
        self.file_name.textChanged.connect(self._changed)
        lay.addWidget(kit.field("File name", self.file_name))
        lay.addSpacing(GROUP_GAP)
        row, _ = self._buttons(("Save project", self._save_project), ("Open project", self._open_project))
        lay.addWidget(row)
        return self._scrolled(frame)

    def _build_picker(self) -> QVBoxLayout:
        """The right side: the mushaf page (or its translation) to pick words on, the page controls, and a line
        that always says what a click will do."""
        kit = self.kit
        right = QVBoxLayout()
        top = QHBoxLayout()
        self.view_ar = kit.text(QPushButton(), "Arabic")
        self.view_tr = kit.text(QPushButton(), "Translation")
        group = QButtonGroup(self)
        for b in (self.view_ar, self.view_tr):
            b.setCheckable(True)
            group.addButton(b)
            top.addWidget(b)
        self.view_ar.setChecked(True)
        self.view_tr.toggled.connect(self._view_changed)
        top.addStretch()
        caption = kit.text(QLabel(), "Page")
        caption.setObjectName("muted")
        top.addWidget(caption)
        # A mushaf's next page is to the left of the one open, whatever the language of the app.
        self.next_page, self.prev_page = QPushButton("‹"), QPushButton("›")
        self.page_box = VerseCombo()
        self.page_box.setMaximum(PAGES)
        for button, key, step in ((self.next_page, "Next page", 1), (self.prev_page, "Previous page", -1)):
            button.setFixedWidth(36)
            button.clicked.connect(lambda _=False, step=step: self.page_box.setValue(self.page_box.value() + step))
            kit.text(button, key, "setToolTip")
        top.addWidget(self.next_page)
        top.addWidget(self.page_box)
        top.addWidget(self.prev_page)
        self.surah_jump = NoWheelCombo()
        self.surah_jump.setMinimumWidth(200)
        kit.text(self.surah_jump, "Go to surah", "setToolTip")
        self.surah_jump.activated.connect(self._jump)
        top.addWidget(self.surah_jump)
        self.page_box.valueChanged.connect(lambda _: (self._load_page(), self._schedule_save()))
        right.addLayout(top)
        self.pick_hint = QLabel()
        self.pick_hint.setObjectName("hintLine")
        self.pick_hint.setWordWrap(True)
        right.addWidget(self.pick_hint)
        self.mushaf, self.tokens = MushafView(), TokenView()
        self.mushaf.set_message(tr("Loading…"))
        for view in (self.mushaf, self.tokens):
            view.pending_changed.connect(lambda _: self._show_hint())
        self.mushaf.picked.connect(self._picked_words)
        self.tokens.picked.connect(self._picked_tokens)
        tokens_scroll = QScrollArea()
        tokens_scroll.setWidgetResizable(True)
        tokens_scroll.setFrameShape(QFrame.Shape.NoFrame)
        tokens_scroll.setWidget(self.tokens)
        self.stack = QStackedWidget()
        self.stack.addWidget(self.mushaf)
        self.stack.addWidget(tokens_scroll)
        right.addWidget(self.stack, 1)
        return right

    # ---------------------------------------------------------------- text that follows the language
    def _relabel(self) -> None:
        self._show_hint()
        self._show_length()
        self._fill_lists()
        if self.mushaf.message:
            self.mushaf.set_message(tr("Loading…"))

    def _show_hint(self) -> None:
        view = self.tokens if self.view_tr.isChecked() else self.mushaf
        if self.target is None:
            text = tr("Choose a batch or add a new one.")
        elif view.pending is not None:
            text = tr("Click the last word.")
        else:
            text = tr("Click the first word, then the last word.")
        self.pick_hint.setText(text)

    def _show_length(self) -> None:
        if not self.audio.text():
            self.length.setText("")
        elif not Path(self.audio.text()).is_file():
            self.length.setText(tr("The audio file was not found."))
        elif not self.has_sound:
            self.length.setText(tr("This file has no sound."))
        elif self.audio_ms:
            self.length.setText(tr("Length: {t}").format(t=fmt_duration(self.audio_ms / 1000)))
        else:
            self.length.setText(tr("Reading the audio…"))

    @staticmethod
    def _times(start: int | None, end: int | None) -> str:
        if start is None:
            return tr("No time yet")
        return ltr(f"{clock(start)} - {clock(end)}" if end is not None else clock(start))

    def _fill_lists(self) -> None:
        """Draw every card again (after any change, and in a new language)."""
        target = self.target or ("", -1)
        font, translation = self.font.currentText(), self.translation.currentData()
        attached = not self.track.isChecked() and translation != "None"
        infos = []
        for k, b in enumerate(self.batches):
            lines = [f"{ltr(label(b.first, b.last))}    {self._times(b.start_ms, b.end_ms)}"]
            if attached and b.translation:
                lines.append(f"{tr('Translation')}: {ltr(label(b.translation.first, b.translation.last))}")
            if b.background:
                lines.append(f"{tr('Background')}: {b.background.name}")
            infos.append(CardInfo(str(k + 1), self._previews.get((font, b.first, b.last), ""), lines,
                                  target[1] == k and target[0] in (ARABIC, ATTACHED),
                                  {BACKGROUND, MOVE, REMOVE} | ({TRANSLATION} if attached else set()),
                                  k > 0, k < len(self.batches) - 1))
        if target[0] == ARABIC and target[1] == len(self.batches):  # a new batch, waiting for its words
            infos.append(CardInfo(str(len(self.batches) + 1), "", [tr("Click the first word, then the last word.")],
                                  True, {REMOVE}))
        self.cards.set_cards(infos, load_font(FONTS[font].path))
        tinfos = []
        for k, t in enumerate(self.trans_batches):
            tinfos.append(CardInfo(str(k + 1), "", [f"{ltr(label(t.range.first, t.range.last))}    "
                                                    f"{self._times(t.start_ms, t.end_ms)}"],
                                   target == (TRACK, k), {MOVE, REMOVE}, k > 0, k < len(self.trans_batches) - 1))
            tinfos[-1].preview = self._previews.get((translation, t.range.first, t.range.last), "")
        if target == (TRACK, len(self.trans_batches)):
            tinfos.append(CardInfo(str(len(self.trans_batches) + 1), "",
                                   [tr("Click the first word, then the last word.")], True, {REMOVE}))
        self.trans_cards.set_cards(tinfos, "")
        self._load_previews()
        self._show_marks()
        self._sync_enabled()

    def _load_previews(self) -> None:
        """Work out the first words of the cards that don't show them yet, away from the window."""
        font, translation = self.font.currentText(), self.translation.currentData()
        known = self._previews.keys() | self._previews_asked
        arabic = [(b.first, b.last) for b in self.batches if (font, b.first, b.last) not in known]
        trans = [(t.range.first, t.range.last) for t in self.trans_batches
                 if (translation, t.range.first, t.range.last) not in known]
        if not arabic and not trans:
            return
        asked = {(font, *r) for r in arabic} | {(translation, *r) for r in trans}
        self._previews_asked |= asked
        verses_of = self._source(font, translation)

        def work():
            out = {}
            for first, last in arabic:
                words = [c.text for c in words_of(first, last, verses_of) if not c.sign]
                out[(font, first, last)] = " ".join(words[:PREVIEW_WORDS]) + (" …" if len(words) > PREVIEW_WORDS
                                                                              else "")
            for first, last in trans:
                text = trans_text(TokenRange(first, last), verses_of)
                words = text.split()
                out[(translation, first, last)] = " ".join(words[:PREVIEW_WORDS + 3]) + (
                    " …" if len(words) > PREVIEW_WORDS + 3 else "")
            return out

        def got(previews: dict) -> None:
            self._previews.update(previews)
            self._previews_asked -= asked
            self._fill_lists()
        self.start(work, got)

    # ---------------------------------------------------------------- the mushaf
    def set_chapters(self, chapters: list[Chapter]) -> None:
        self.chapters = chapters
        self.surah_jump.clear()
        for c in chapters:
            self.surah_jump.addItem(f"{c.id}. {c.name_simple} · {c.name_arabic}", c.id)

    def set_colors(self, palette: dict) -> None:
        self.mushaf.set_colors(palette)
        self.tokens.set_colors(palette)

    def _source(self, font: str, translation: str):
        key = (font, translation)
        if key not in self._sources:
            self._sources[key] = verse_source(self.client, font, translation)
        return self._sources[key]

    def _jump(self, _=None) -> None:
        self.page_box.setValue(first_page(self.surah_jump.currentData(), self.chapters))

    def _load_page(self) -> None:
        if not self.chapters:
            return
        self._page_seq += 1
        seq, page = self._page_seq, self.page_box.value()
        font, translation = self.font.currentText(), self.translation.currentData()
        verses_of, chapters = self._source(font, translation), self.chapters

        def work():
            shown = mushaf_page(page, chapters, verses_of)
            keys = list(dict.fromkeys((c.ref.chapter, c.ref.verse) for line in shown.lines for c in line.cells
                                      if c.ref is not None))
            rows = [(ch, v, verse_tokens(verses_of(ch)[v - 1], spaced_translation(verses_of, ch))[0])
                    for ch, v in keys]
            return shown, rows
        self.start(work, lambda r: self._got_page(seq, font, r))

    def _got_page(self, seq: int, font: str, result) -> None:
        if seq != self._page_seq:
            return
        shown, rows = result
        spec = FONTS[font]
        self.mushaf.set_page(shown, load_font(spec.path), spec.marker_fmt)
        self.tokens.set_rows(rows)
        on = [c for c in self.chapters if c.pages[0] <= shown.number <= c.pages[1]]
        if on:
            self.surah_jump.setCurrentIndex(self.surah_jump.findData(on[0].id))
        self._show_marks()

    def _go_to(self, chapter: int, verse: int) -> None:
        """Open the page a verse is on (found away from the window: its surah may not be loaded yet)."""
        verses_of = self._source(self.font.currentText(), self.translation.currentData())

        def got(page: int) -> None:
            if page and page != self.page_box.value():
                self.page_box.setValue(page)
        self.start(lambda: page_of(chapter, verse, verses_of), got)

    def _show_marks(self) -> None:
        kind, k = self.target or ("", -1)
        self.mushaf.set_marks([Mark(b.first, b.last, str(n + 1), kind in (ARABIC, ATTACHED) and n == k)
                               for n, b in enumerate(self.batches)])
        if self.track.isChecked():
            marks = [Mark(x.range.first, x.range.last, str(n + 1), kind == TRACK and n == k)
                     for n, x in enumerate(self.trans_batches)]
        else:
            marks = [Mark(b.translation.first, b.translation.last, str(n + 1), kind in (ARABIC, ATTACHED) and n == k)
                     for n, b in enumerate(self.batches) if b.translation]
        self.tokens.set_marks(marks)

    # ---------------------------------------------------------------- choosing a batch and its words
    def _select(self, kind: str, k: int) -> None:
        """Choose what the next clicks on the page change. Choosing the chosen card again lets it go."""
        if self.target == (kind, k):
            self._deselect()
            return
        self.target = (kind, k)
        self.mushaf.clear_pending()
        self.tokens.clear_pending()
        words = kind == ARABIC
        self.view_ar.blockSignals(True)
        self.view_tr.blockSignals(True)
        (self.view_ar if words else self.view_tr).setChecked(True)
        self.view_ar.blockSignals(False)
        self.view_tr.blockSignals(False)
        self.stack.setCurrentIndex(0 if words else 1)
        self.mushaf.set_active(words)
        self.tokens.set_active(not words)
        if kind == TRACK and self.steps.currentIndex() != 2:
            self.steps.setCurrentIndex(2)
        elif kind != TRACK and self.steps.currentIndex() != 1:
            self.steps.setCurrentIndex(1)
        self._fill_lists()
        cards = self.trans_cards if kind == TRACK else self.cards
        QTimer.singleShot(0, lambda: cards.show_card(k))  # once the new cards are laid out
        start = None  # the page to open: where the chosen batch starts
        if kind == ARABIC and k < len(self.batches):
            start = self.batches[k].first
        elif kind == ATTACHED and k < len(self.batches):
            b = self.batches[k]
            start = b.translation.first if b.translation else b.first
        elif kind == TRACK and k < len(self.trans_batches):
            start = self.trans_batches[k].range.first
        if start is not None:
            self._go_to(start.chapter, start.verse)
        self._show_hint()

    def _deselect(self) -> None:
        """Nothing chosen: clicks on the page do nothing (a new batch not finished yet is dropped)."""
        if self.target is None:
            return
        self.target = None
        self.mushaf.set_active(False)
        self.tokens.set_active(False)
        self._fill_lists()
        self._show_hint()

    def _picked_words(self, first, last) -> None:
        if self.target is None or self.target[0] != ARABIC:
            return
        k = self.target[1]
        if k < len(self.batches):  # new words for this batch: its times stay, its word taps were for the old ones
            self.batches[k] = replace(self.batches[k], first=first, last=last, word_ms=())
        else:
            self.batches.append(Batch(first, last))
        self._deselect()
        self._changed()

    def _picked_tokens(self, first, last) -> None:
        if self.target is None or self.target[0] == ARABIC:
            return
        kind, k = self.target
        rng = TokenRange(first, last)
        if kind == ATTACHED and k < len(self.batches):
            self.batches[k] = replace(self.batches[k], translation=rng)
        elif kind == TRACK and k < len(self.trans_batches):
            self.trans_batches[k] = replace(self.trans_batches[k], range=rng)
        elif kind == TRACK:
            self.trans_batches.append(TransBatch(rng))
        self._deselect()
        self._changed()

    def _view_changed(self) -> None:
        """Switching between the Arabic and the translation keeps the same batch chosen, for its words or for its
        translation; a translation batch has no Arabic to change."""
        translation = self.view_tr.isChecked()
        self.stack.setCurrentIndex(1 if translation else 0)
        kind, k = self.target or ("", -1)
        if kind == ARABIC and translation and k < len(self.batches) and not self.track.isChecked():
            self._select(ATTACHED, k)
        elif kind == ATTACHED and not translation:
            self._select(ARABIC, k)
        elif kind and (kind == ARABIC) == translation:
            self._deselect()
        self._show_hint()
        self._schedule_save()

    def _step_changed(self, i: int) -> None:
        self.pages.setCurrentIndex(i)
        self._schedule_save()

    # ---------------------------------------------------------------- the lists
    def _move(self, k: int, step: int) -> None:
        """Swap a batch with its neighbour. The times stay where they are in the recording: only what is shown
        in them moves (word taps belong to the words, so they are cleared)."""
        j = k + step
        if not (0 <= k < len(self.batches) and 0 <= j < len(self.batches)):
            return
        a, b = self.batches[k], self.batches[j]
        self.batches[k] = replace(b, start_ms=a.start_ms, end_ms=a.end_ms, word_ms=())
        self.batches[j] = replace(a, start_ms=b.start_ms, end_ms=b.end_ms, word_ms=())
        self.target = None
        self._changed()

    def _remove(self, k: int) -> None:
        if self.target == (ARABIC, k) and k == len(self.batches):  # a new batch: never added, just let it go
            self._deselect()
            return
        if 0 <= k < len(self.batches):
            del self.batches[k]
            self.target = None
            self._changed()

    def _move_trans(self, k: int, step: int) -> None:
        j = k + step
        if 0 <= k < len(self.trans_batches) and 0 <= j < len(self.trans_batches):
            a, b = self.trans_batches[k], self.trans_batches[j]
            self.trans_batches[k] = replace(b, start_ms=a.start_ms, end_ms=a.end_ms)
            self.trans_batches[j] = replace(a, start_ms=b.start_ms, end_ms=b.end_ms)
            self.target = None
            self._changed()

    def _remove_trans(self, k: int) -> None:
        if self.target == (TRACK, k) and k == len(self.trans_batches):
            self._deselect()
            return
        if 0 <= k < len(self.trans_batches):
            del self.trans_batches[k]
            self.target = None
            self._changed()

    def _card_background(self, k: int) -> None:
        """Choose a picture or video for one batch, or (when it has one) clear it."""
        if not 0 <= k < len(self.batches):
            return
        if self.batches[k].background is not None:
            menu = QMenu(self)
            choose, clear = menu.addAction(tr("Choose")), menu.addAction(tr("Clear"))
            picked = menu.exec(QCursor.pos())
            if picked is clear:
                self._set_batch_bg(k, None)
                return
            if picked is not choose:
                return
        path, _ = QFileDialog.getOpenFileName(self, tr("Background for this batch"), str(Path.home()), MEDIA_FILTER)
        if path:
            self._set_batch_bg(k, Path(path))

    def _set_batch_bg(self, k: int, path: Path | None) -> None:
        self.batches[k] = replace(self.batches[k], background=path)
        self._changed()

    # ---------------------------------------------------------------- files
    def _pick_audio(self) -> None:
        start = str(Path(self.audio.text()).parent) if self.audio.text() else str(Path.home())
        path, _ = QFileDialog.getOpenFileName(self, tr("Audio or video file"), start, AUDIO_FILTER)
        if path:
            self._set_audio(path)

    def _set_audio(self, path: str) -> None:
        self.audio.setText(path)
        self.trim = (0, None)  # a trim belongs to the recording it was made on
        self._probe_audio()
        self._changed()

    def _probe_audio(self) -> None:
        """Read the recording's length and whether it has sound, away from the window."""
        path = self.audio.text()
        self._probe_seq += 1
        self.audio_ms, self.has_sound = None, True
        self._show_length()
        if not path:
            self.changed.emit()
            return
        seq = self._probe_seq

        def work():
            p = Path(path)
            return (media_seconds(p), has_audio(p)) if p.is_file() else (None, False)
        self.start(work, lambda r: self._got_probe(seq, r))

    def _got_probe(self, seq: int, result) -> None:
        if seq != self._probe_seq:
            return
        seconds, self.has_sound = result
        self.audio_ms = int(seconds * 1000) if seconds else None
        self._show_length()
        self.changed.emit()

    def _pick_bg(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, tr("Background image or video"), str(Path.home()), MEDIA_FILTER)
        if path:
            self.bg.setText(path)
            self._changed()

    def _pick_out(self) -> None:
        path = QFileDialog.getExistingDirectory(self, tr("Save to"), self.out_dir.text())
        if path:
            self.out_dir.setText(path)

    def _project_filter(self) -> str:
        return f"{tr('Project files')} (*{PROJECT_SUFFIX})"

    def _save_project(self) -> None:
        name = self.file_name.text().strip() or (Path(self.audio.text()).stem if self.audio.text() else "project")
        path, _ = QFileDialog.getSaveFileName(self, tr("Save project"), str(Path(self.out_dir.text()) / name),
                                              self._project_filter())
        if not path:
            return
        p = Path(path) if path.endswith(PROJECT_SUFFIX) else Path(path + PROJECT_SUFFIX)
        try:
            p.write_text(json.dumps(to_json(self.job(), self.formats()), ensure_ascii=False, indent=1), "utf-8")
        except OSError as e:
            QMessageBox.warning(self, tr("Save project"), f"{e}")

    def _open_project(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, tr("Open project"), self.out_dir.text(), self._project_filter())
        if not path:
            return
        try:
            job, formats = from_json(json.loads(Path(path).read_text("utf-8")), Path(path).parent)
        except (OSError, ValueError, DataError):
            QMessageBox.warning(self, tr("Open project"), tr("Can't open this project."))
            return
        self._loading = True
        self._apply(job, formats)
        self._loading = False
        if not is_builtin(job.theme):
            self.themes_changed(job.theme)  # the project's own theme, if it was new, is kept with the others
        self._probe_audio()
        self._load_page()
        self._changed()

    # ---------------------------------------------------------------- choices
    def _translation_changed(self) -> None:
        """Translation ranges point at words of one translation: another one clears them, after asking."""
        new = self.translation.currentData()
        has_ranges = self.trans_batches or any(b.translation for b in self.batches)
        if has_ranges and new != self._translation and not self._loading:
            ask = QMessageBox.question(self, tr("Translation"), tr("Changing the translation clears the "
                                                                   "translation ranges."))
            if ask != QMessageBox.StandardButton.Yes:
                self.translation.blockSignals(True)
                self.translation.setCurrentIndex(self.translation.findData(self._translation))
                self.translation.blockSignals(False)
                return
            self.trans_batches.clear()
            self.batches = [replace(b, translation=None) for b in self.batches]
        self._translation = new
        self.target = None
        self._load_page()
        self._changed()

    def _mode_changed(self) -> None:
        self._deselect()
        self._changed()

    def _font_changed(self) -> None:
        self._load_page()
        self._changed()

    def _sync_enabled(self) -> None:
        set_on = Form.set_on
        translation = self.translation.currentData() != "None"
        track = translation and self.track.isChecked()
        for w in (self.add_trans_btn, self.trans_cards):
            w.setVisible(track)
        self.track_spacer.setVisible(not track)
        set_on(self.tw_dep, translation)
        self.view_tr.setEnabled(translation)
        if not translation and self.view_tr.isChecked():
            self.view_ar.setChecked(True)
        set_on(self.fade_dep, self.highlight.currentData() != "none")
        set_on(self.name_dep, self.surah_name.isChecked())
        bg = Path(self.bg.text()) if self.bg.text() else None
        set_on(self.dim_dep, bg is not None or any(b.background for b in self.batches))
        set_on(self.bg_end_dep, is_video(bg) or any(is_video(b.background) for b in self.batches))
        set_item_enabled(self.highlight, "keep", self.reveal.currentData() != "single")
        set_item_enabled(self.reveal, "single", self.highlight.currentData() != "keep")

    def _changed(self, *_) -> None:
        if self._loading:
            return
        self._fill_lists()
        self._schedule_save()
        self.changed.emit()

    def _schedule_save(self) -> None:
        if not self._loading:
            self._save_timer.start()

    def set_busy(self, busy: bool) -> None:
        self.setEnabled(not busy)

    # ---------------------------------------------------------------- the job
    def formats(self) -> list[str]:
        return [f for f, cb in self.fmt_boxes.items() if cb.isChecked()]

    def job(self, fmt: str | None = None) -> ManualJob:
        audio, bg = self.audio.text(), self.bg.text()
        return ManualJob(
            Path(audio) if audio else None, list(self.batches), fmt or (self.formats() or [DEFAULT_FORMAT])[0],
            Path(self.out_dir.text()), trans_mode=TRANS_TRACK if self.track.isChecked() else TRANS_ATTACHED,
            trans_batches=list(self.trans_batches), translation=self.translation.currentData(),
            reciter_name=self.reciter_name.text(), name=self.file_name.text().strip(),
            trim_start_ms=self.trim[0], trim_end_ms=self.trim[1], font=self.font.currentText(),
            theme=self.video_theme.currentData(), highlight=self.highlight.currentData(),
            highlight_fade=self.hl_fade.isChecked(), reveal=self.reveal.currentData(),
            surah_name=self.surah_name.isChecked(), name_scale=self.name_size.value() / 100,
            overlay=self.overlay.value() / 100, quality=self.quality.currentData(),
            text_width=self.text_width.value() / 100, translation_width=self.translation_width.value() / 100,
            background=Path(bg) if bg else None, bg_end=self.bg_end.currentData())

    def jobs(self) -> list[ManualJob]:
        return [self.job(f) for f in self.formats()]

    def seconds(self) -> float | None:
        """How long the video will be (None until the recording has been read)."""
        if not self.audio_ms:
            return None
        job = self.job()
        return (file_end(job, self.audio_ms) - job.trim_start_ms) / 1000

    def problem(self) -> DataError | None:
        """Why the video can't be made yet, if it can't (shown in the footer, Export stays off)."""
        if self.audio.text() and self.audio_ms is None and self.has_sound:
            return DataError("Reading the audio…")
        try:
            check(self.job(), self.audio_ms / 1000 if self.audio_ms else None, self.has_sound)
        except DataError as e:
            return e
        return None

    # ---------------------------------------------------------------- the timing window
    def _open_timing(self) -> None:
        job = self.job()
        for ok, key in ((job.audio is not None and job.audio.is_file(), "Choose an audio or video file."),
                        (self.has_sound and self.audio_ms, "This file has no sound."),
                        (job.batches, "Add at least one batch.")):
            if not ok:
                QMessageBox.information(self, tr("Set times"), tr(key))
                return
        self._deselect()
        from .timing_window import TimingWindow  # it loads Qt Multimedia, which only this window needs
        window = TimingWindow(self, job, self.audio_ms, self._source(job.font, job.translation), self.start,
                              self.mushaf.colors)
        if window.exec():
            self.batches, self.trans_batches, self.trim = window.batches, window.trans_batches, window.trim
            self._changed()
        window.deleteLater()  # it holds a player and a preview: free them now, not when the tab goes

    # ---------------------------------------------------------------- saved between runs
    def save(self) -> None:
        if self._loading:
            return
        self.settings.setValue("manual", json.dumps({
            "version": MANUAL_VERSION, "project": to_json(self.job(), self.formats()),
            "view": "translation" if self.view_tr.isChecked() else "arabic", "page": self.page_box.value(),
            "step": self.steps.currentIndex()}, ensure_ascii=False))

    def restore(self) -> None:
        """What the tab held last time (the window calls it once the surahs are loaded)."""
        try:
            data = json.loads(self.settings.value("manual", "{}"))
        except ValueError:
            data = {}
        if not isinstance(data, dict) or data.get("version") != MANUAL_VERSION:
            data = {}
        if data.get("project"):
            try:
                self._apply(*from_json(data["project"], Path.home()))
            except DataError:
                pass
        self.page_box.setValue(int(data.get("page") or 1))
        (self.view_tr if data.get("view") == "translation" else self.view_ar).setChecked(True)
        self.steps.setCurrentIndex(min(max(int(data.get("step") or 0), 0), len(STEPS) - 1))
        self._translation = self.translation.currentData()
        self._loading = False
        self._fill_lists()
        self._show_hint()
        self._probe_audio()
        self._load_page()

    def _apply(self, job: ManualJob, formats: list[str]) -> None:
        """Show a job (from the settings or a project file) in the controls."""
        def pick(combo, value, by_data=True):
            i = combo.findData(value) if by_data else combo.findText(value)
            if i >= 0:
                combo.setCurrentIndex(i)
        self.target = None
        self.audio.setText(str(job.audio) if job.audio else "")
        self.reciter_name.setText(job.reciter_name)
        self.batches, self.trans_batches = list(job.batches), list(job.trans_batches)
        self.trim = (job.trim_start_ms, job.trim_end_ms)
        fill_translations(self.translation, job.translation)
        self._translation = job.translation
        (self.track if job.trans_mode == TRANS_TRACK else self.attached).setChecked(True)
        self.translation_width.setValue(round(job.translation_width * 100))
        pick(self.font, job.font if job.font in FONTS else DEFAULT_FONT, by_data=False)
        fill_themes(self.video_theme, job.theme)
        pick(self.reveal, job.reveal)
        pick(self.highlight, job.highlight)
        self.hl_fade.setChecked(job.highlight_fade)
        self.text_width.setValue(round(job.text_width * 100))
        self.surah_name.setChecked(job.surah_name)
        self.name_size.setValue(round(job.name_scale * 100))
        self.bg.setText(str(job.background) if job.background else "")
        self.overlay.setValue(round(job.overlay * 100))
        pick(self.bg_end, job.bg_end)
        for f, cb in self.fmt_boxes.items():
            cb.setChecked(f in formats)
        pick(self.quality, job.quality)
        self.out_dir.setText(str(job.out_dir))
        self.file_name.setText(job.name)

    def refill_themes(self, select: str | None = None) -> None:
        fill_themes(self.video_theme, select)
