"""The Manual mode tab: the user's own recording, batches picked on the mushaf, and times set while it plays.

The tab only builds widgets and keeps the batches; core.manual does the work, and the window around it runs the
export. What it needs from the window comes in as functions (start a task, open the theme editor, save the
custom themes), so it never reaches into the window itself."""

import json
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QTimer, Signal
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QMessageBox, QPushButton, QRadioButton, QScrollArea, QStackedWidget,
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
                           TransBatch, check, file_end, first_page, from_json, label, mushaf_page,
                           spaced_translation, to_json, verse_tokens)
from ..core.manual_export import verse_source
from ..core.render import load_font
from ..core.timing import DataError
from ..i18n import tr
from .form import (GROUP_GAP, MEDIA_FILTER, PANEL_WIDTH, SLIDERS, Form, clock, fill_themes, fill_translations,
                   fmt_duration, relabel_themes, set_item_enabled)
from .mushaf import Mark, MushafView, TokenView
from .widgets import NoWheelCombo, VerseCombo

MANUAL_VERSION = 1  # of what is kept in the settings; a mismatch starts the tab empty
AUDIO_FILTER = ("Audio and video (*.mp3 *.m4a *.aac *.wav *.ogg *.opus *.flac *.mp4 *.mov *.mkv *.webm *.avi);;"
                "All files (*)")


class ManualTab(QWidget):
    changed = Signal()  # the footer (length, problems, size) needs drawing again

    def __init__(self, kit: Form, client, start, open_themes, themes_changed, settings: QSettings):
        super().__init__()
        self.kit, self.client, self.start = kit, client, start
        self.open_themes, self.themes_changed, self.settings = open_themes, themes_changed, settings
        self.chapters: list[Chapter] = []
        self.batches: list[Batch] = []
        self.trans_batches: list[TransBatch] = []
        self.trim: tuple[int, int | None] = (0, None)  # the part of the recording the video uses
        self.audio_ms: int | None = None  # the recording's length, once read
        self.has_sound = True
        self._translation = ""  # the translation the ranges were picked in
        self._page_seq = self._probe_seq = 0
        self._sources: dict = {}
        self._loading = True
        self._save_timer = QTimer(self, singleShot=True, interval=400)
        self._save_timer.timeout.connect(self.save)
        self._build()

    # ---------------------------------------------------------------- building
    def _build(self) -> None:
        kit = self.kit
        outer = QHBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 12)
        outer.setSpacing(20)
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
        outer.addWidget(scroll)
        self._build_recording(form)
        self._build_batches(form)
        self._build_translation(form)
        self._build_look(form)
        self._build_output(form)
        form.addStretch()
        outer.addLayout(self._build_picker(), 1)
        kit.relabels.append(self._relabel)

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

    def _build_recording(self, form: QVBoxLayout) -> None:
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
        form.addWidget(frame)

    def _build_batches(self, form: QVBoxLayout) -> None:
        kit = self.kit
        frame, lay = kit.card("Batches")
        self.pick_hint = QLabel()
        self.pick_hint.setObjectName("muted")
        self.pick_hint.setWordWrap(True)
        lay.addWidget(self.pick_hint)
        self.batch_list = QListWidget()
        self.batch_list.setObjectName("batches")
        self.batch_list.setMinimumHeight(170)
        self.batch_list.currentRowChanged.connect(self._batch_selected)
        lay.addWidget(self.batch_list)
        row, (self.up, self.down, self.remove, self.clear_all) = self._buttons(
            ("Move up", lambda: self._move(-1)), ("Move down", lambda: self._move(1)), ("Remove", self._remove),
            ("Clear all", self._clear_all))
        lay.addWidget(row)
        self.batch_bg = QLineEdit()
        self.batch_bg_box = kit.field("Background for this batch", self._file_row(
            self.batch_bg, self._pick_batch_bg, lambda: self._set_batch_bg(None)))
        lay.addWidget(self.batch_bg_box)
        lay.addSpacing(GROUP_GAP)
        self.times_btn = kit.text(QPushButton(), "Set times")
        self.times_btn.setObjectName("primary")
        self.times_btn.clicked.connect(self._open_timing)
        lay.addWidget(self.times_btn)
        form.addWidget(frame)

    def _build_translation(self, form: QVBoxLayout) -> None:
        kit = self.kit
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
        inner = QVBoxLayout()
        inner.setContentsMargins(0, 0, 0, 0)
        self.trans_list = QListWidget()
        self.trans_list.setObjectName("batches")
        self.trans_list.setMinimumHeight(110)
        self.trans_list.currentRowChanged.connect(lambda _: (self._show_marks(), self._sync_enabled()))
        inner.addWidget(self.trans_list)
        row, (self.t_up, self.t_down, self.t_remove) = self._buttons(
            ("Move up", lambda: self._move_trans(-1)), ("Move down", lambda: self._move_trans(1)),
            ("Remove", self._remove_trans))
        inner.addWidget(row)
        holder = QWidget()
        holder.setLayout(inner)
        self.track_dep = kit.dep(holder)
        lay.addWidget(self.track_dep)
        self.tw_row, self.translation_width = kit.slider("Translation width", *SLIDERS["translation_width"],
                                                         self._changed)
        self.tw_dep = kit.dep(self.tw_row)
        lay.addWidget(self.tw_dep)
        form.addWidget(frame)

    def _build_look(self, form: QVBoxLayout) -> None:
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
        form.addWidget(frame)

    def _build_output(self, form: QVBoxLayout) -> None:
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
        form.addWidget(frame)

    def _build_picker(self) -> QVBoxLayout:
        """The right side: the mushaf page (or its translation) to pick words on, and the page controls."""
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
        if view.pending is not None:
            text = tr("Click the last word.")
        elif self.view_tr.isChecked() and not self.track.isChecked():
            text = tr("Choose a batch, then click the first and last word of its translation.")
        else:
            text = tr("Click the first word, then the last word.")
        self.pick_hint.setText(text)

    def _show_length(self) -> None:
        if not self.audio.text():
            self.length.setText("")
        elif not self.has_sound:
            self.length.setText(tr("This file has no sound."))
        elif self.audio_ms:
            self.length.setText(tr("Length: {t}").format(t=fmt_duration(self.audio_ms / 1000)))
        else:
            self.length.setText(tr("Reading the audio…"))

    def _batch_text(self, n: int, b: Batch) -> str:
        times = clock(b.start_ms) if b.start_ms is not None else tr("No time yet")
        if b.start_ms is not None and b.end_ms is not None:
            times += f" - {clock(b.end_ms)}"
        lines = [f"{n}.  {label(b.first, b.last)}    {times}"]
        if b.translation and not self.track.isChecked():
            lines.append(f"     {tr('Translation')}: {label(b.translation.first, b.translation.last)}")
        if b.background:
            lines.append(f"     {tr('Background')}: {b.background.name}")
        return "\n".join(lines)

    def _fill_lists(self, select: int | None = None, select_trans: int | None = None) -> None:
        for lst, items, text, chosen in (
                (self.batch_list, self.batches, self._batch_text, select),
                (self.trans_list, self.trans_batches, self._trans_text, select_trans)):
            row = lst.currentRow() if chosen is None else chosen
            lst.blockSignals(True)
            lst.clear()
            lst.addItems([text(n, x) for n, x in enumerate(items, 1)])
            lst.setCurrentRow(min(row, len(items) - 1))
            lst.blockSignals(False)
        self._batch_selected()

    @staticmethod
    def _trans_text(n: int, t: TransBatch) -> str:
        times = clock(t.start_ms) if t.start_ms is not None else tr("No time yet")
        return f"{n}.  {label(t.range.first, t.range.last)}    {times}"

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

    def _show_marks(self) -> None:
        k = self.batch_list.currentRow()
        self.mushaf.set_marks([Mark(b.first, b.last, str(n), n - 1 == k) for n, b in enumerate(self.batches, 1)])
        if self.track.isChecked():
            t = self.trans_list.currentRow()
            marks = [Mark(x.range.first, x.range.last, str(n), n - 1 == t) for n, x in enumerate(self.trans_batches, 1)]
        else:
            marks = [Mark(b.translation.first, b.translation.last, str(n), n - 1 == k)
                     for n, b in enumerate(self.batches, 1) if b.translation]
        self.tokens.set_marks(marks)

    def _picked_words(self, first, last) -> None:
        self.batches.append(Batch(first, last))
        self._fill_lists(select=len(self.batches) - 1)
        self._changed()

    def _picked_tokens(self, first, last) -> None:
        rng = TokenRange(first, last)
        if self.track.isChecked():
            self.trans_batches.append(TransBatch(rng))
            self._fill_lists(select_trans=len(self.trans_batches) - 1)
        else:
            k = self.batch_list.currentRow()
            if k < 0:
                QMessageBox.information(self, tr("Translation"), tr("Choose a batch in the list first."))
                return
            self.batches[k] = replace(self.batches[k], translation=rng)
            self._fill_lists()
        self._changed()

    def _view_changed(self) -> None:
        self.stack.setCurrentIndex(1 if self.view_tr.isChecked() else 0)
        self.mushaf.clear_pending()
        self.tokens.clear_pending()
        self._show_hint()
        self._schedule_save()

    # ---------------------------------------------------------------- the lists
    def _batch_selected(self, *_) -> None:
        k = self.batch_list.currentRow()
        bg = self.batches[k].background if 0 <= k < len(self.batches) else None
        self.batch_bg.setText(str(bg) if bg else "")
        self._show_marks()
        self._sync_enabled()

    def _move(self, step: int) -> None:
        """Swap a batch with its neighbour. The times stay where they are in the recording: only what is shown
        in them moves (word taps belong to the words, so they are cleared)."""
        k = self.batch_list.currentRow()
        j = k + step
        if not (0 <= k < len(self.batches) and 0 <= j < len(self.batches)):
            return
        a, b = self.batches[k], self.batches[j]
        self.batches[k] = replace(b, start_ms=a.start_ms, end_ms=a.end_ms, word_ms=())
        self.batches[j] = replace(a, start_ms=b.start_ms, end_ms=b.end_ms, word_ms=())
        self._fill_lists(select=j)
        self._changed()

    def _remove(self) -> None:
        k = self.batch_list.currentRow()
        if 0 <= k < len(self.batches):
            del self.batches[k]
            self._fill_lists(select=min(k, len(self.batches) - 1))
            self._changed()

    def _clear_all(self) -> None:
        if not self.batches:
            return
        ask = QMessageBox.question(self, tr("Clear all"), tr("Remove every batch?"))
        if ask == QMessageBox.StandardButton.Yes:
            self.batches.clear()
            self._fill_lists()
            self._changed()

    def _move_trans(self, step: int) -> None:
        k = self.trans_list.currentRow()
        j = k + step
        if 0 <= k < len(self.trans_batches) and 0 <= j < len(self.trans_batches):
            a, b = self.trans_batches[k], self.trans_batches[j]
            self.trans_batches[k] = replace(b, start_ms=a.start_ms, end_ms=a.end_ms)
            self.trans_batches[j] = replace(a, start_ms=b.start_ms, end_ms=b.end_ms)
            self._fill_lists(select_trans=j)
            self._changed()

    def _remove_trans(self) -> None:
        k = self.trans_list.currentRow()
        if 0 <= k < len(self.trans_batches):
            del self.trans_batches[k]
            self._fill_lists(select_trans=min(k, len(self.trans_batches) - 1))
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

    def _pick_batch_bg(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, tr("Background for this batch"), str(Path.home()), MEDIA_FILTER)
        if path:
            self._set_batch_bg(Path(path))

    def _set_batch_bg(self, path: Path | None) -> None:
        k = self.batch_list.currentRow()
        if 0 <= k < len(self.batches):
            self.batches[k] = replace(self.batches[k], background=path)
            self._fill_lists()
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
            self._fill_lists()
        self._translation = new
        self._load_page()
        self._changed()

    def _mode_changed(self) -> None:
        self.tokens.clear_pending()
        self._fill_lists()
        self._show_hint()
        self._changed()

    def _font_changed(self) -> None:
        self._load_page()
        self._changed()

    def _sync_enabled(self) -> None:
        set_on = Form.set_on
        k = self.batch_list.currentRow()
        chosen = 0 <= k < len(self.batches)
        for button, ok in ((self.up, chosen and k > 0), (self.down, chosen and k < len(self.batches) - 1),
                           (self.remove, chosen), (self.clear_all, bool(self.batches))):
            button.setEnabled(ok)
        self.batch_bg_box.setEnabled(chosen)
        t = self.trans_list.currentRow()
        tchosen = 0 <= t < len(self.trans_batches)
        for button, ok in ((self.t_up, tchosen and t > 0), (self.t_down, tchosen and t < len(self.trans_batches) - 1),
                           (self.t_remove, tchosen)):
            button.setEnabled(ok)
        translation = self.translation.currentData() != "None"
        set_on(self.track_dep, translation and self.track.isChecked())
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
        self._sync_enabled()
        self._show_marks()
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
        from .timing_window import TimingWindow  # it loads Qt Multimedia, which only this window needs
        window = TimingWindow(self, job, self.audio_ms, self._source(job.font, job.translation), self.start,
                              self.mushaf.colors)
        if window.exec():
            self.batches, self.trans_batches, self.trim = window.batches, window.trans_batches, window.trim
            self._fill_lists()
            self._changed()

    # ---------------------------------------------------------------- saved between runs
    def save(self) -> None:
        if self._loading:
            return
        self.settings.setValue("manual", json.dumps({
            "version": MANUAL_VERSION, "project": to_json(self.job(), self.formats()),
            "view": "translation" if self.view_tr.isChecked() else "arabic", "page": self.page_box.value()},
            ensure_ascii=False))

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
        self._translation = self.translation.currentData()
        self._loading = False
        self._fill_lists()
        self._sync_enabled()
        self._show_hint()
        self._probe_audio()
        self._load_page()

    def _apply(self, job: ManualJob, formats: list[str]) -> None:
        """Show a job (from the settings or a project file) in the controls."""
        def pick(combo, value, by_data=True):
            i = combo.findData(value) if by_data else combo.findText(value)
            if i >= 0:
                combo.setCurrentIndex(i)
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
        self._fill_lists(select=0 if self.batches else -1)

    def refill_themes(self, select: str | None = None) -> None:
        fill_themes(self.video_theme, select)
