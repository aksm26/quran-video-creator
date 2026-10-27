"""Set times: the recording plays, and checkpoints are dropped on its progress bar as it goes. S starts the next
batch (which ends the one before), E ends the batch on screen, W lights its next word. The preview shows the
video as it will be at that moment.

Only the recording's sound is played (Qt Multimedia, from PySide6-Addons). When it can't play, a silent clock
stands in, so times can still be set by moving along the bar."""

from dataclasses import replace

from PySide6.QtCore import QElapsedTimer, Qt, QTimer, QUrl
from PySide6.QtGui import QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (QButtonGroup, QDialog, QDialogButtonBox, QFrame, QHBoxLayout, QLabel, QPushButton,
                               QRadioButton, QSizePolicy, QVBoxLayout, QWidget)

from ..config.fonts import FONTS
from ..config.translations import TRANSLATIONS
from ..core.ffmpeg import envelope
from ..core.manual import (END, START, TRANS_TRACK, ManualJob, file_end, label, limits, mark, set_time, tap,
                           trans_text, windows, words_of)
from ..core.manual_export import ManualPreview
from ..core.render import load_font
from ..i18n import tr
from .form import clock, ltr
from .timeline import ARABIC, TRANSLATION, TRIM, Block, Timeline
from .widgets import NoWheelCombo

try:
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
except ImportError:  # PySide6-Addons is not installed: no sound, the silent clock is used
    QMediaPlayer = QAudioOutput = None

TAP_LAG_MS = 100  # a key pressed while listening lands a little after the moment heard
PREVIEW_WIDTH = 300
STEP_MS, BIG_STEP_MS = 1000, 5000


class SilentClock:
    """Keeps time like a player that makes no sound."""

    def __init__(self, length: int):
        self.length, self.pos, self.rate, self.playing = length, 0, 1.0, False
        self.timer = QElapsedTimer()

    def position(self) -> int:
        moved = self.timer.elapsed() * self.rate if self.playing else 0
        return int(min(self.pos + moved, self.length))

    def play(self) -> None:
        self.timer.start()
        self.playing = True

    def pause(self) -> None:
        self.pos = self.position()
        self.playing = False

    def set_position(self, ms: int) -> None:
        self.pos = min(max(ms, 0), self.length)
        self.timer.start()

    def set_rate(self, rate: float) -> None:
        self.pos = self.position()
        self.rate = rate
        self.timer.start()

    def stop(self) -> None:
        self.pause()


class PlayerClock:
    """The recording, played (only its sound, even from a video file)."""

    def __init__(self, path, length: int, parent):
        self.length = length
        self.player, self.output = QMediaPlayer(parent), QAudioOutput(parent)
        self.player.setAudioOutput(self.output)
        self.player.setSource(QUrl.fromLocalFile(str(path)))
        self.failed = False
        self.player.errorOccurred.connect(lambda *_: setattr(self, "failed", True))

    @property
    def playing(self) -> bool:
        return self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState

    def position(self) -> int:
        return self.player.position()

    def play(self) -> None:
        self.player.play()

    def pause(self) -> None:
        self.player.pause()

    def set_position(self, ms: int) -> None:
        self.player.setPosition(min(max(ms, 0), self.length))

    def set_rate(self, rate: float) -> None:
        self.player.setPlaybackRate(rate)

    def stop(self) -> None:
        self.player.stop()


class TimingWindow(QDialog):
    """After exec(): `batches`, `trans_batches` and `trim` hold the times (whatever button closed it, the owner
    only reads them when it returns true)."""

    def __init__(self, parent, job: ManualJob, audio_ms: int, verses_of, start, colors: dict):
        super().__init__(parent)
        self.setWindowTitle(tr("Set times"))
        self.resize(1180, 780)
        self.job, self.audio_ms, self.verses_of, self.start_task = job, audio_ms, verses_of, start
        self.batches, self.trans_batches = list(job.batches), list(job.trans_batches)
        self.trim = (job.trim_start_ms, job.trim_end_ms)
        self.track_mode = job.trans_mode == TRANS_TRACK and TRANSLATIONS.get(job.translation) is not None
        self.history: list[tuple] = []
        self.cursor = next((k for k, b in enumerate(self.batches) if b.start_ms is None), 0)  # the next S starts it
        self.t_cursor = next((k for k, t in enumerate(self.trans_batches) if t.start_ms is None), 0)
        self.word = (-1, 0)  # (batch, word) the next W lights
        self.preview: ManualPreview | None = None
        self._preview_seq = 0
        self._closed = False  # answers from workers that come after closing are dropped
        self._cells: dict[int, tuple] = {}
        self._build(colors)
        self.clock = self._make_clock()
        self._rebuild = QTimer(self, singleShot=True, interval=250)
        self._rebuild.timeout.connect(self._build_preview)
        self._tick = QTimer(self, interval=40)
        self._tick.timeout.connect(self._update)
        self._tick.start()
        self._refresh()
        self._build_preview()
        path = job.audio
        self.start_task(lambda: envelope(path), self._got_envelope)

    # ---------------------------------------------------------------- building
    def _build(self, colors: dict) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 14)
        lay.setSpacing(10)
        top = QHBoxLayout()
        self.picture = QLabel()
        self.picture.setObjectName("preview")
        self.picture.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.picture.setFixedWidth(PREVIEW_WIDTH + 12)
        self.picture.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Ignored)
        top.addWidget(self.picture)
        info = QVBoxLayout()
        self.now_title, self.now_text, self.now_trans = QLabel(), QLabel(), QLabel()
        self.next_title, self.next_text = QLabel(), QLabel()
        family = load_font(FONTS[self.job.font].path)
        for title in (self.now_title, self.next_title):
            title.setObjectName("cardTitle")
        for text in (self.now_text, self.next_text):
            text.setWordWrap(True)
            text.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
            text.setAlignment(Qt.AlignmentFlag.AlignRight)
            text.setStyleSheet(f'font-family: "{family}"; font-size: 28px;')
        self.next_text.setStyleSheet(f'font-family: "{family}"; font-size: 20px;')
        self.now_trans.setWordWrap(True)
        self.now_trans.setObjectName("muted")
        for w in (self.now_title, self.now_text, self.now_trans):
            info.addWidget(w)
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        info.addSpacing(8)
        info.addWidget(line)
        info.addWidget(self.next_title)
        info.addWidget(self.next_text)
        info.addStretch()
        self.keys = QLabel(tr("Space: play or pause. S: start the next batch. E: end this batch. "
                              "W: light the next word. Arrows: move 1 s (Shift: 5 s). Ctrl+Z: undo."))
        self.keys.setObjectName("muted")
        self.keys.setWordWrap(True)
        info.addWidget(self.keys)
        self.sound_note = QLabel()
        self.sound_note.setObjectName("warn")
        self.sound_note.setWordWrap(True)
        info.addWidget(self.sound_note)
        holder = QWidget()
        holder.setLayout(info)
        top.addWidget(holder, 1)
        lay.addLayout(top, 1)

        self.overview, self.detail = Timeline(), Timeline(follow=True)
        for t in (self.overview, self.detail):
            t.colors = colors
            t.set_length(self.audio_ms)
            t.seek.connect(self._seek)
            t.grabbed.connect(self._remember)  # one drag is one step to undo
            t.moved.connect(self._moved)
            t.selected.connect(self._select)
            lay.addWidget(t)

        row = QHBoxLayout()
        self.play_btn = QPushButton()
        self.play_btn.setObjectName("primary")
        self.play_btn.clicked.connect(self._toggle)
        row.addWidget(self.play_btn)
        self.time = QLabel()
        self.time.setMinimumWidth(130)
        row.addWidget(self.time)
        self.speed = NoWheelCombo()
        for rate in (0.5, 0.75, 1.0):
            self.speed.addItem(f"{rate:g}x", rate)
        self.speed.setCurrentIndex(2)
        self.speed.currentIndexChanged.connect(lambda _: self.clock.set_rate(self.speed.currentData()))
        row.addWidget(self.speed)
        self.on_arabic, self.on_translation = QRadioButton(tr("Arabic")), QRadioButton(tr("Translation"))
        group = QButtonGroup(self)
        group.addButton(self.on_arabic)
        group.addButton(self.on_translation)
        self.on_arabic.setChecked(True)
        self.on_arabic.toggled.connect(lambda _: self._refresh())
        for b in (self.on_arabic, self.on_translation):
            b.setVisible(self.track_mode)
            row.addWidget(b)
        row.addSpacing(12)
        for key, slot, shortcut in (("Mark start", self._mark_start, "S"), ("Mark end", self._mark_end, "E"),
                                    ("Tap word", self._tap_word, "W"), ("Undo", self._undo, "Ctrl+Z"),
                                    ("Clear times", self._clear_selected, "Delete"),
                                    ("Trim start", lambda: self._set_trim(START), ""),
                                    ("Trim end", lambda: self._set_trim(END), "")):
            b = QPushButton(tr(key))
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.clicked.connect(slot)
            if shortcut:
                keys = QKeySequence(shortcut)
                b.setToolTip(keys.toString(QKeySequence.SequenceFormat.NativeText))  # the key's name in the language
                QShortcut(keys, self, activated=slot)
            if key == "Tap word" and self.job.highlight == "none":
                b.setEnabled(False)
                b.setToolTip(tr("Turn on Highlight to set each word's time."))
            row.addWidget(b)
        row.addStretch()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr("Done"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("Cancel"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        row.addWidget(buttons)
        lay.addLayout(row)
        for key, step in (("Space", None), ("Left", -STEP_MS), ("Right", STEP_MS), ("Shift+Left", -BIG_STEP_MS),
                          ("Shift+Right", BIG_STEP_MS)):
            QShortcut(QKeySequence(key), self, activated=self._toggle if step is None
                      else lambda step=step: self._seek(self.clock.position() + step))
        for w in self.findChildren(QPushButton) + [self.speed, self.on_arabic, self.on_translation]:
            w.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # keys go to the shortcuts, never press a button

    def _make_clock(self):
        if QMediaPlayer is not None:
            clock_ = PlayerClock(self.job.audio, self.audio_ms, self)
            clock_.player.errorOccurred.connect(lambda *_: self._no_sound())
            return clock_
        self._no_sound(switch=False)
        return SilentClock(self.audio_ms)

    def _no_sound(self, switch: bool = True) -> None:
        self.sound_note.setText(tr("Sound is not available. Times can still be set."))
        if switch:
            pos = self.clock.position()
            self.clock.stop()
            self.clock = SilentClock(self.audio_ms)
            self.clock.set_position(pos)

    # ---------------------------------------------------------------- what the window shows
    def _end(self) -> int:
        return file_end(replace(self.job, trim_start_ms=self.trim[0], trim_end_ms=self.trim[1]), self.audio_ms)

    def _job(self) -> ManualJob:
        return replace(self.job, batches=list(self.batches), trans_batches=list(self.trans_batches),
                       trim_start_ms=self.trim[0], trim_end_ms=self.trim[1])

    def _cells_of(self, k: int) -> tuple:
        b = self.batches[k]
        key = (b.first, b.last)
        if self._cells.get(k, (None,))[0] != key:
            self._cells[k] = (key, words_of(b.first, b.last, self.verses_of))
        return self._cells[k][1]

    @staticmethod
    def _blocks(items, wins, describe) -> list[Block]:
        """One block per batch that has a start (a batch squeezed to nothing still gets one, to drag it out)."""
        out = []
        for k, (item, win) in enumerate(zip(items, wins)):
            if item.start_ms is None:
                continue
            a, z = win or (item.start_ms, item.start_ms)
            ticks = tuple(t for t in getattr(item, "word_ms", ()) if t is not None)
            out.append(Block(a, z, item.end_ms, str(k + 1), describe(item), ticks))
        return out

    def _refresh(self) -> None:
        """Draw the batches on both bars again (after any change of time)."""
        end = self._end()
        a_wins = windows([b.slot for b in self.batches], end)
        arabic = self._blocks(self.batches, a_wins, lambda b: label(b.first, b.last))
        trans = None
        if self.track_mode:
            t_wins = windows([t.slot for t in self.trans_batches], end)
            trans = self._blocks(self.trans_batches, t_wins, lambda t: label(t.range.first, t.range.last))
        # the bars show only the batches with a start: find the selected one among them
        items, cur, track = self._items()
        timed = [n for n, x in enumerate(items) if x.start_ms is not None]
        current = (track, timed.index(cur) if cur in timed else -1)
        for t in (self.overview, self.detail):
            t.set_tracks(arabic, trans, (self.trim[0], end), current)
        self._rebuild.start()

    def _build_preview(self) -> None:
        if self._closed:
            return
        self._preview_seq += 1
        seq, job, verses_of, audio_ms = self._preview_seq, self._job(), self.verses_of, self.audio_ms
        self.start_task(lambda: ManualPreview.build(job, verses_of, audio_ms, PREVIEW_WIDTH),
                        lambda p: self._got_preview(seq, p))

    def _got_preview(self, seq: int, preview: ManualPreview) -> None:
        if seq == self._preview_seq and not self._closed:
            self.preview = preview

    def _got_envelope(self, env: list[float]) -> None:
        if self._closed:
            return
        for t in (self.overview, self.detail):
            t.set_envelope(env)

    def _update(self) -> None:
        """40 times a second: the playhead, the time, the picture and the batch on screen."""
        t = self.clock.position()
        for line in (self.overview, self.detail):
            line.set_playhead(t)
        self.play_btn.setText(tr("Pause") if self.clock.playing else tr("Play"))
        self.time.setText(ltr(f"{clock(t)} / {clock(self.audio_ms)}"))
        if self.preview is not None:
            self.picture.setPixmap(QPixmap.fromImage(self.preview.frame(t)))
        self._show_batches(t)

    def _on_screen(self, t: int) -> int | None:
        return next((k for k, w in enumerate(windows([b.slot for b in self.batches], self._end()))
                     if w and w[0] <= t < w[1]), None)

    def _show_batches(self, t: int) -> None:
        k = self._on_screen(t)
        if k is None:
            self.now_title.setText(tr("Nothing on screen"))
            self.now_text.setText("")
            self.now_trans.setText("")
        else:
            b = self.batches[k]
            self.now_title.setText(f"{tr('Batch {n}').format(n=k + 1)} · {ltr(label(b.first, b.last))}")
            cells = [c for c in self._cells_of(k) if not c.sign]
            nxt = self.word[1] if self.job.highlight != "none" and self.word[0] == k else None  # W lights it
            self.now_text.setText(" ".join(f"<u>{c.text}</u>" if i == nxt else c.text for i, c in enumerate(cells)))
            rng = b.translation if not self.track_mode else None
            self.now_trans.setText(trans_text(rng, self.verses_of) if rng else "")
        n = self.cursor if self.on_arabic.isChecked() else None
        if n is not None and 0 <= n < len(self.batches):
            nb = self.batches[n]
            self.next_title.setText(f"{tr('Press S to start batch {n}').format(n=n + 1)} · "
                                    f"{ltr(label(nb.first, nb.last))}")
            self.next_text.setText(" ".join(c.text for c in self._cells_of(n) if not c.sign))
        elif self.on_translation.isChecked() and 0 <= self.t_cursor < len(self.trans_batches):
            tb = self.trans_batches[self.t_cursor]
            self.next_title.setText(tr("Press S to start translation {n}").format(n=self.t_cursor + 1))
            self.next_text.setText(trans_text(tb.range, self.verses_of))
        else:
            self.next_title.setText(tr("Every batch has a start time."))
            self.next_text.setText("")

    # ---------------------------------------------------------------- changes
    def _remember(self) -> None:
        self.history.append((list(self.batches), list(self.trans_batches), self.trim, self.cursor, self.t_cursor))
        del self.history[:-100]

    def _undo(self) -> None:
        if self.history:
            self.batches, self.trans_batches, self.trim, self.cursor, self.t_cursor = self.history.pop()
            self._refresh()

    def _now(self) -> int:
        """The moment for a mark: a little earlier while playing, as a key comes just after what was heard."""
        t = self.clock.position()
        return max(t - TAP_LAG_MS, 0) if self.clock.playing else t

    def _items(self) -> tuple[list, int, str]:
        if self.on_translation.isChecked():
            return self.trans_batches, self.t_cursor, TRANSLATION
        return self.batches, self.cursor, ARABIC

    def _put(self, track: str, slots) -> None:
        items = self.trans_batches if track == TRANSLATION else self.batches
        new = [replace(x, start_ms=s, end_ms=e) for x, (s, e) in zip(items, slots)]
        if track == TRANSLATION:
            self.trans_batches = new
        else:
            self.batches = new

    def _mark_start(self) -> None:
        items, k, track = self._items()
        if not 0 <= k < len(items):
            return
        self._remember()
        self._put(track, mark([x.slot for x in items], k, START, self._now(), 0, self.audio_ms))
        if track == TRANSLATION:
            self.t_cursor = k + 1
        else:
            self.cursor = k + 1
            self.word = (k, 0)
        self._refresh()

    def _mark_end(self) -> None:
        items, _, track = self._items()
        t = self._now()
        wins = windows([x.slot for x in items], self._end())
        k = next((n for n in range(len(items) - 1, -1, -1) if wins[n] and wins[n][0] <= t), None)
        if k is None:
            return
        self._remember()
        self._put(track, mark([x.slot for x in items], k, END, t, 0, self.audio_ms))
        self._refresh()

    def _tap_word(self) -> None:
        if self.job.highlight == "none":
            return
        t = self._now()
        k = self._on_screen(t)
        if k is None:
            return
        n_words = sum(1 for c in self._cells_of(k) if not c.sign)
        i = self.word[1] if self.word[0] == k else 0
        self._remember()
        taps, nxt = tap(self.batches[k].word_ms, n_words, i, t)
        self.batches[k] = replace(self.batches[k], word_ms=taps)
        self.word = (k, nxt)
        self._refresh()

    def _clear_selected(self) -> None:
        items, k, track = self._items()
        k = k - 1 if k >= len(items) else k  # after the last batch: clear the last one
        if not 0 <= k < len(items):
            return
        self._remember()
        if track == TRANSLATION:
            self.trans_batches[k] = replace(items[k], start_ms=None, end_ms=None)
        else:
            self.batches[k] = replace(items[k], start_ms=None, end_ms=None, word_ms=())
        self._refresh()

    def _set_trim(self, which: str) -> None:
        t = self.clock.position()
        self._remember()
        a, b = self.trim
        if which == START:
            self.trim = (min(t, (b if b is not None else self.audio_ms) - 1000), b)
        else:
            self.trim = (a, max(t, a + 1000))
        self._refresh()

    def _moved(self, track: str, k: int, which: str, ms: int) -> None:
        """A checkpoint dragged on the bar. `k` counts the blocks shown, i.e. the batches that have a start."""
        if track == TRIM:
            a, b = self.trim
            self.trim = (min(ms, self._end() - 1000), b) if which == START else (a, max(ms, a + 1000))
            self._refresh()
            return
        items = self.trans_batches if track == TRANSLATION else self.batches
        timed = [n for n, x in enumerate(items) if x.start_ms is not None]
        if not 0 <= k < len(timed):
            return
        n = timed[k]
        slots = [x.slot for x in items]
        lo, hi = limits(slots, n, which, 0, self.audio_ms)
        self._put(track, set_time(slots, n, which, min(max(ms, lo), hi), 0, self.audio_ms))
        self._refresh()

    def _select(self, track: str, k: int) -> None:
        items = self.trans_batches if track == TRANSLATION else self.batches
        timed = [n for n, x in enumerate(items) if x.start_ms is not None]
        if 0 <= k < len(timed):
            if track == TRANSLATION:
                self.on_translation.setChecked(True)
                self.t_cursor = timed[k]
            else:
                self.on_arabic.setChecked(True)
                self.cursor = timed[k]
            self._refresh()

    def _seek(self, ms: int) -> None:
        self.clock.set_position(min(max(ms, 0), self.audio_ms))

    def _toggle(self) -> None:
        if self.clock.playing:
            self.clock.pause()
        else:
            self.clock.play()

    def done(self, result: int) -> None:
        self._closed = True
        self._rebuild.stop()
        self._tick.stop()
        self.clock.stop()
        super().done(result)
