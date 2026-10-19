import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox, QToolButton

from quran_video import i18n
from quran_video.config.themes import THEMES, custom_themes, remove_custom
from quran_video.ui.main_window import MainWindow, fmt_duration

pytestmark = pytest.mark.slow_network


def isolate_settings(tmp_path):
    from PySide6.QtCore import QSettings
    QSettings.setPath(QSettings.Format.NativeFormat, QSettings.Scope.UserScope, str(tmp_path / "cfg"))


@pytest.fixture
def win(tmp_path, monkeypatch):
    isolate_settings(tmp_path)  # keep the user's saved settings out of tests, and tests out of each other
    monkeypatch.setattr(QMessageBox, "exec", lambda self: 0)  # never block on a dialog
    app = QApplication.instance() or QApplication([])
    w = MainWindow()
    w.show()
    pump(app, lambda: w.ready)
    pump(app, lambda: not w._tasks and not w._timer.isActive(), settle=0.6)
    yield w
    pump(app, lambda: not w._tasks and not w._timer.isActive(), timeout=60)  # let workers finish before closing
    for t in custom_themes():
        remove_custom(t.name)
    i18n.set_language("en")
    w._install_qt_translation("en")  # remove any Qt translator the test left behind
    w.close()


def pump(app, cond, timeout=120, settle=0.0):
    end = time.time() + timeout
    time.sleep(settle) if settle else None
    while time.time() < end:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.02)
    return False


def idle(win):
    return pump(QApplication.instance(), lambda: not win._tasks and not win._timer.isActive(), settle=0.6)


def choose(combo, data):
    combo.setCurrentIndex(combo.findData(data))


def visible_stops(win):
    return [n for n, r in win.stop_rows.items() if not r.isHidden()]


def test_defaults_and_validation(win):
    assert win.reciter.currentData() == 7 and win.in_parts.isChecked()
    assert [n for n, c in win.stop_boxes.items() if c.isChecked()] == ["lazim", "qila"]  # default stops
    assert visible_stops(win) == ["lazim", "qila", "jaiz", "sila"]  # Madani font
    assert win.translation.currentData().startswith("English") and win.arabic.isChecked()
    assert win.font.currentText() == "QPC Hafs" and win.highlight.currentData() == "word"
    assert win.reveal.currentData() == "off" and win.hl_fade.isChecked()
    sliders = (win.text_width.value(), win.translation_width.value(), win.name_size.value(), win.overlay.value())
    assert sliders == (84, 84, 100, 35)
    assert win.video_theme.currentData() == "Classic"
    choose(win.surah, 112)
    assert win.from_v.maximum() == win.to_v.maximum() == 4  # validated against the surah's verse count
    win.from_v.setValue(4)
    win.to_v.setValue(2)
    assert win.from_v.value() <= win.to_v.value()


def test_boxes_are_in_a_sensible_order_with_dependents_under_their_controls(win):
    y = lambda w: w.mapTo(win, QPoint(0, 0)).y()
    x = lambda w: w.mapTo(win, QPoint(0, 0)).x()

    def order(widgets):
        ys = [y(w) for w in widgets]
        return ys == sorted(ys) and len(set(ys)) == len(ys)
    assert order([win.reciter, win.surah, win.from_v, win.basmala])  # what is recited; Basmala depends on the range
    assert order([win.arabic, win.font, win.text_width, win.reveal, win.highlight, win.hl_fade])
    assert order([win.translation, win.translation_width])
    assert order([win.full_verse, win.in_parts, win.stop_boxes["lazim"], win.surah_name, win.name_size])
    assert order([win.video_theme, win.bg, win.overlay, win.bg_end])
    assert order([*win.fmt_boxes.values(), win.quality, win.out_dir])
    assert order([win.reciter, win.arabic, win.translation, win.full_verse, win.video_theme, win.fmt_boxes["9:16"]])
    # a dependent control is indented under the one it depends on
    assert x(win.basmala) > x(win.from_v) + 10 and x(win.hl_fade) > x(win.highlight) + 10
    assert x(win.translation_width) > x(win.translation) + 10 and x(win.name_size) > x(win.surah_name) + 10
    assert x(win.overlay) > x(win.bg) + 10 and x(win.stop_boxes["lazim"]) > x(win.in_parts) + 10
    assert [c.text() for c in win.fmt_boxes.values()] == ["9:16", "16:9", "1:1", "4:5"]  # ratios only, no resolutions
    assert not hasattr(win, "verse_marker")  # the verse number sign is always on, so there is no option


def test_stop_choices(win):
    win.full_verse.setChecked(True)
    assert not win.stops_box.isEnabled() and win._job("9:16").split == "verse"
    win.in_parts.setChecked(True)
    win.stop_boxes["jaiz"].setChecked(True)
    assert set(win._job("9:16").stops) == {"lazim", "qila", "jaiz"}
    win.stop_boxes["lazim"].setChecked(False)
    assert "lazim" not in win._job("9:16").stops



def test_stop_rows_show_only_the_name_and_symbol(win):
    row = win.stop_rows["mutlaq"]
    assert win.stop_boxes["mutlaq"].text() == "Waqf Muṭlaq"
    assert [w.text() for w in row.findChildren(QLabel)] == ["ط"]
    assert not win.findChildren(QToolButton, "info")  # the circled info icons are gone


def test_options_grey_out_when_they_do_not_apply(win, tmp_path):
    assert not win.name_row.isEnabled()  # no surah name chosen
    win.surah_name.setChecked(True)
    assert win.name_row.isEnabled()
    assert not win.dim_row.isEnabled() and not win.bg_end_row.isEnabled()  # no background chosen
    assert win.dim_dep.graphicsEffect().opacity() < 1 and win.basmala_dep.graphicsEffect().opacity() < 1  # faded too
    from PySide6.QtGui import QColor, QImage
    png = tmp_path / "bg.png"
    image = QImage(64, 64, QImage.Format.Format_RGB32)
    image.fill(QColor("navy"))
    image.save(str(png))
    win.bg.setText(str(png))
    win._changed()
    assert win.dim_row.isEnabled() and not win.bg_end_row.isEnabled()  # a background, but not a video
    win.highlight.setCurrentIndex(win.highlight.findData("none"))
    assert not win.hl_fade.isEnabled()
    win.highlight.setCurrentIndex(win.highlight.findData("word"))
    assert win.hl_fade.isEnabled()
    win.translation.setCurrentIndex(win.translation.findData("None"))
    assert not win.tw_row.isEnabled()
    assert win.highlight.model().item(win.highlight.findData("keep")).isEnabled()  # no combination is ruled out


def test_unavailable_options_are_clearly_faded_and_return_to_full_strength(win):
    effect = lambda box: box.graphicsEffect().opacity()
    win.highlight.setCurrentIndex(win.highlight.findData("none"))
    assert effect(win.fade_dep) < 0.5
    win.highlight.setCurrentIndex(win.highlight.findData("word"))
    assert effect(win.fade_dep) == 1.0
    win.surah_name.setChecked(True)
    assert effect(win.name_dep) == 1.0
    win.surah_name.setChecked(False)
    assert effect(win.name_dep) < 0.5


def test_turning_arabic_off_fades_its_options_and_needs_a_translation(win):
    win.arabic.setChecked(False)
    for w in (win.font, win.text_width, win.reveal, win.highlight, win.hl_fade):
        assert not w.isEnabled()
    assert win.arabic_dep.graphicsEffect().opacity() < 0.5 and win._job("9:16").show_arabic is False
    assert not win.translation.model().item(win.translation.findData("None")).isEnabled()  # something must show
    assert win.stops_box.isEnabled()  # stop signs still cut the translation into parts
    win.arabic.setChecked(True)
    win.translation.setCurrentIndex(win.translation.findData("None"))
    assert win.arabic.isChecked() and not win.arabic.isEnabled()  # with no translation, Arabic is all there is
    assert win._job("9:16").show_arabic is True


def test_clicking_a_slider_moves_the_handle_there(win):
    s = win.text_width
    QTest.mouseClick(s, Qt.MouseButton.LeftButton, pos=QPoint(int(s.width() * 0.9), s.height() // 2))
    high = s.value()
    QTest.mouseClick(s, Qt.MouseButton.LeftButton, pos=QPoint(int(s.width() * 0.1), s.height() // 2))
    low = s.value()
    assert high > 90 and low < 68 and high - low > 25  # it jumped to where it was clicked, in both directions


def test_wheel_does_not_change_choices(win):
    for widget in (win.font, win.highlight, win.from_v, win.overlay, win.text_width, win.surah):
        before = widget.currentIndex() if hasattr(widget, "currentIndex") else widget.value()
        ev = QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(0, 0), QPoint(0, -120), Qt.MouseButton.NoButton,
                         Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
        QApplication.sendEvent(widget, ev)
        after = widget.currentIndex() if hasattr(widget, "currentIndex") else widget.value()
        assert before == after  # the value never moves
        if widget.isEnabled():
            assert not ev.isAccepted()  # ignored, so the panel scrolls instead (Qt does that itself for greyed ones)


def test_font_sample_is_the_whole_basmala(win):
    pump(QApplication.instance(), lambda: len(win.font_sample.text().split()) >= 4, timeout=30)
    assert len(win.font_sample.text().split()) == 4  # all four words, not the first three


def test_duration_and_size_wording(win):
    assert fmt_duration(46) == "46 seconds" and fmt_duration(1) == "1 second"
    assert fmt_duration(60) == "1 minute" and fmt_duration(65) == "1 minute 5 seconds"
    assert fmt_duration(3600) == "1 hour" and fmt_duration(3725) == "1 hour 2 minutes 5 seconds"
    assert "MB" in win.export_btn.text() or "KB" in win.export_btn.text()  # size lives on the button
    assert "second" in win.preview_title.text() and "Estimated time" in win.info.text()


def test_quality_and_widths_reach_the_job(win):
    win.quality.setCurrentIndex(win.quality.findData("Low"))
    win.text_width.setValue(95)
    win.translation_width.setValue(70)
    win.surah_name.setChecked(True)
    win.name_size.setValue(150)
    win.quality.setCurrentIndex(win.quality.findData("Very low"))
    win.highlight.setCurrentIndex(win.highlight.findData("keep"))
    win.hl_fade.setChecked(False)
    win.bg_end.setCurrentIndex(win.bg_end.findData("freeze"))
    win.verse_change.setCurrentIndex(win.verse_change.findData("last_word"))
    job = win._job("9:16")
    assert job.quality == "Very low" and abs(job.text_width - 0.95) < 1e-9 and abs(job.translation_width - 0.70) < 1e-9
    assert abs(job.name_scale - 1.5) < 1e-9 and job.highlight == "keep" and not job.highlight_fade
    assert job.bg_end == "freeze" and job.verse_change == "last_word"
    assert win.verse_change.toolTip()  # the hint says why the choice exists: the timings may have errors
    assert "credits" in win.export_btn.toolTip()  # posting the Quran Foundation credits is required


def test_info_buttons_explain_on_click(win, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    shown = []
    monkeypatch.setattr(QMessageBox, "information", lambda parent, title, text: shown.append(text))
    hints = [w for w, name in win._icons if name == "info-circle"]
    for hint in hints:
        hint.click()
    assert len(hints) == 2 and [t[:8] for t in shown] == [h.toolTip()[:8] for h in hints]
    assert any("Quran.com" in t for t in shown) and any("credits" in t for t in shown)


def test_custom_themes_can_be_saved_and_deleted(win):
    from PySide6.QtWidgets import QPushButton
    from quran_video.ui.themes_dialog import ThemesDialog
    dlg = ThemesDialog(win, win._themes_changed)
    dlg.bg, dlg.hl = "#102030", "#FFAA00"
    dlg.name.setText("Sunset")
    dlg._save()
    assert "Sunset" in THEMES and win.video_theme.currentData() == "Sunset"  # saved and selected
    assert win.video_theme.findData("Sunset") > win.video_theme.findData("Dusk")  # after the built-in ones
    assert '"Sunset"' in win.settings.value("custom_themes")  # persisted
    dlg.name.setText("Classic")
    dlg._save()
    assert dlg.error.text() == "That name is taken."
    danger = [b for b in dlg.findChildren(QPushButton) if b.objectName() == "danger"]
    assert len(danger) == 1  # one red delete button, beside the theme
    danger[0].click()
    assert "Sunset" not in THEMES and win.video_theme.findData("Sunset") < 0
    assert win.video_theme.currentData() == "Classic"
    assert "Sunset" not in win.settings.value("custom_themes")


def test_export_two_formats_and_cancel(win, tmp_path):
    app = QApplication.instance()
    choose(win.surah, 112)
    win.from_v.setValue(1)
    win.to_v.setValue(2)
    win.out_dir.setText(str(tmp_path / "out"))
    win.fmt_boxes["1:1"].setChecked(True)
    idle(win)
    win.export_btn.click()
    assert win._busy and not win.form.isEnabled()
    assert pump(app, lambda: not win._busy)
    names = [p.name for p in (tmp_path / "out").iterdir() if p.suffix == ".mp4"]
    assert len(names) == 2
    assert any(n.endswith("_1x1.mp4") for n in names) and any(n.endswith("_9x16.mp4") for n in names)
    for n in names:  # Quran Foundation terms: every video comes with its credits
        credits = (tmp_path / "out" / n).with_suffix(".credits.txt").read_text("utf-8")
        assert "Recitation: " in credits and "Quran.Foundation" in credits
    assert app.clipboard().text() == credits

    choose(win.surah, 2)
    win.from_v.setValue(255)
    win.to_v.setValue(255)
    idle(win)
    win.export_btn.click()
    pump(app, lambda: False, timeout=2)
    win.cancel_btn.click()
    assert pump(app, lambda: not win._busy)
    assert not [p for p in (tmp_path / "out").iterdir() if "2_255" in p.name]  # no partial file left


def test_verse_range_is_two_dropdowns(win):
    from quran_video.ui.widgets import VerseCombo
    assert isinstance(win.from_v, VerseCombo) and isinstance(win.to_v, VerseCombo)
    choose(win.surah, 2)
    assert win.from_v.count() == win.to_v.count() == 286 and win.from_v.itemText(285) == "286"
    win.from_v.setCurrentIndex(254)  # 255
    assert win.from_v.value() == 255 and win.to_v.value() == 255  # the end follows the start
    win.to_v.setCurrentIndex(260)
    win.from_v.setCurrentIndex(270)
    assert win.to_v.value() == 271  # and the start can't pass the end
    choose(win.surah, 112)
    assert win.from_v.count() == 4 and win.from_v.value() <= 4 and win.to_v.value() <= 4


def test_themes_show_their_two_colours_side_by_side(win):
    from quran_video.config.themes import THEMES as T
    for i in range(win.video_theme.count()):
        icon = win.video_theme.itemIcon(i)
        assert not icon.isNull()
        px = icon.pixmap(36, 18).toImage()
        theme = T[win.video_theme.itemData(i)]
        w = px.width()
        left, right = px.pixelColor(w // 4, px.height() // 2), px.pixelColor(3 * w // 4, px.height() // 2)
        assert left.name().upper() == theme.bg and right.name().upper() == theme.highlight  # solid halves, no blend


def test_menus_name_languages_in_the_apps_language_and_cover_every_translation(win):
    from quran_video.config.translations import TRANSLATIONS as TR
    assert win.translation.count() == len(TR) == 145  # all 144 of Quran.com's translations, plus none
    win._set_language("pt")
    labels = [win.translation.itemText(i) for i in range(win.translation.count())]
    assert any(l.startswith("Espanhol (") for l in labels) and any(l.startswith("Inglês (") for l in labels)
    assert not any(l.startswith(("Spanish", "Portuguese", "English")) for l in labels)
    assert win.translation.itemText(win.translation.findData("None")) == "Nenhum"
    win._show_languages()
    actions = win.lang_popup.labels()
    win.lang_popup.hide()
    assert "Espanhol · Español" in actions and "Português" in actions and "Inglês · English" in actions
    assert win.translation.currentData() == "Portuguese (Helmi Nasr)"  # Portuguese picks its own translation
    assert win.video_theme.itemText(win.video_theme.findData("Midnight")) == "Meia-noite"
    assert win.reciter.itemText(win.reciter.findData(7)) == "Mishari Rashid al-`Afasy (Murattal)"
    win._set_language("ar")
    assert win.reciter.itemText(win.reciter.findData(7)).startswith("مشاري راشد العفاسي (مرتل")
    assert win.reciter.itemText(win.reciter.findData(168)).endswith("(ترديد الأطفال)")


def test_every_dropdown_is_the_same_fixed_height_and_scrolls(win):
    from PySide6.QtWidgets import QComboBox
    from quran_video.ui.widgets import POPUP_ROWS
    combos = win.findChildren(QComboBox)
    assert len(combos) >= 12
    assert all(c.maxVisibleItems() == POPUP_ROWS for c in combos)  # none grows with its content
    assert win.translation.count() == 145 and win.from_v.count() >= 4  # even the longest lists
    assert "combobox-popup: 0" in win.styleSheet()  # a plain list with a scroll bar, not a stretched pop-over


def test_kids_repeat_reciter_has_only_that_label(win):
    label = win.reciter.itemText(win.reciter.findData(168))
    assert label.endswith("(Kids repeat)") and "each verse" not in label
    assert win.reciter.itemText(win.reciter.findData(173)).endswith("(Murattal, alternate copy)")  # others unchanged


def test_language_list_scrolls_with_the_wheel_and_picks_a_language(win):
    from PySide6.QtGui import QWheelEvent
    from quran_video.ui.widgets import POPUP_ROWS
    win._show_languages()
    pop = win.lang_popup
    assert pop.isVisible() and pop.list.count() == 18
    row = pop.list.sizeHintForRow(0)
    assert pop.height() <= POPUP_ROWS * row + 20  # same fixed height as the other lists
    bar = pop.list.verticalScrollBar()
    assert bar.maximum() > 0 and bar.value() == 0  # more entries than fit
    ev = QWheelEvent(QPointF(20, 20), QPointF(20, 20), QPoint(0, 0), QPoint(0, -360), Qt.MouseButton.NoButton,
                     Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(pop.list.viewport(), ev)
    assert bar.value() > 0  # the wheel scrolls it
    bar.setValue(bar.maximum())
    last = pop.list.item(pop.list.count() - 1)  # Japanese, only reachable by scrolling
    pop.list.itemClicked.emit(last)
    assert not pop.isVisible() and i18n.current == "ja" and win.in_parts.text() == i18n.TABLE["ja"]["Cut at stop signs"]


def _everything_shown(w):
    from PySide6.QtWidgets import QAbstractButton, QComboBox, QLabel, QLineEdit, QWidget
    out = [x.text() for x in w.findChildren(QLabel)] + [x.text() for x in w.findChildren(QAbstractButton)]
    out += [x.placeholderText() for x in w.findChildren(QLineEdit)] + [x.toolTip() for x in w.findChildren(QWidget)]
    for c in w.findChildren(QComboBox):
        out += [c.itemText(i) for i in range(c.count())]
    return out


def test_nothing_is_left_in_english_after_changing_language(win):
    from quran_video.ui.about import about_html
    choose(win.surah, 1)
    choose(win.reciter, 173)  # broken timing for Al-Fatihah: shows an error message too
    idle(win)
    for code in i18n.LANGUAGES:
        if code == "en":
            continue
        win._set_language(code)
        table = i18n.TABLE[code]
        stale = [t for t in _everything_shown(win) if t in table and table[t] != t]
        assert not stale, (code, stale)  # a text that has a translation is still in English
        assert any(t.startswith(table["Text width"]) for t in _everything_shown(win)), code  # slider captions too
        assert "Pick another reciter" not in win.info.text() and "has no timing" not in win.info.text(), code
        assert table["Data and audio"] in about_html(), code
    win._set_language("de")
    assert "keine Zeitangaben" in win.info.text() and "Nichts" not in win.info.text()
    win._set_language("fr")
    assert "n'a pas de minutage" in win.info.text()


def test_qt_dialogs_follow_the_language_and_reciters_use_each_scripts_name(win):
    from PySide6.QtCore import QCoreApplication
    ask = lambda: QCoreApplication.translate("QPlatformTheme", "Cancel")
    assert ask() == "Cancel"
    win._set_language("de")
    assert ask() == "Abbrechen"  # the colour picker and file chooser follow too
    win._set_language("en")
    assert ask() == "Cancel"
    starts = {"ru": "Машари Рашид", "hi": "मिशारी", "bn": "মিশারি", "zh": "米沙里", "ja": "ミシャリー",
              "fa": "مشاری", "ar": "مشاري"}
    for code, start in starts.items():
        win._set_language(code)
        assert win.reciter.itemText(win.reciter.findData(7)).startswith(start), code
    win._set_language("fr")
    assert win.reciter.itemText(win.reciter.findData(7)).startswith("Mishari Rashid")  # Latin script: as the API has it


def test_a_warning_flashes_briefly_then_the_normal_line_returns(win):
    choose(win.surah, 112)
    idle(win)
    win.basmala.setChecked(True)  # available for the start of surah 112
    assert win.basmala.isChecked()
    win._toast_timer.setInterval(800)  # short, so the test does not wait 3 seconds
    choose(win.surah, 1)  # Al-Fatihah: the Basmala no longer applies, so it switches itself off at once
    assert not win.basmala.isChecked()
    warning = i18n.tr("Needs verse 1 of a surah other than Al-Fatihah and At-Tawbah.")
    assert win.info.text() == warning and win.info.objectName() == "warn"  # the reason is shown
    assert win._job("9:16").basmala is False  # and no worker runs with it, so no error flashes up
    win._apply_info()  # refreshing the normal line does not wipe a flashing warning
    assert win.info.text() == warning
    assert pump(QApplication.instance(), lambda: win.info.text() != warning, timeout=5)  # it goes by itself
    assert win.info.objectName() == "muted" and "Estimated time" in win.info.text()
    idle(win)
    assert "Basmala" not in win.info.text() and win.info.objectName() == "muted"  # no error after the preview ran


def test_tooltips_are_brief(win, monkeypatch):
    from PySide6.QtCore import QEvent, QPoint
    from PySide6.QtGui import QHelpEvent
    from PySide6.QtWidgets import QToolTip
    from quran_video.ui.main_window import TIP_MS
    seen = []
    monkeypatch.setattr(QToolTip, "showText", lambda *a: seen.append(a))
    win.lang_btn.setToolTip("Language")
    handled = win.eventFilter(win.lang_btn, QHelpEvent(QEvent.Type.ToolTip, QPoint(3, 3), QPoint(30, 30)))
    assert handled and seen[0][1] == "Language" and seen[0][-1] == TIP_MS == 2500  # shown for 2.5 s, then gone


def test_the_preview_steps_through_every_screen(win):
    app = QApplication.instance()
    choose(win.surah, 2)
    win.from_v.setValue(282)
    win.to_v.setValue(282)  # the longest verse: shown as several screens
    idle(win)
    count = int(win.screen_label.text().split(" / ")[1])
    assert win.screen_nav.isVisible() and win.screen_label.text() == f"1 / {count}" and count > 1
    assert not win.prev_screen.isEnabled() and win.next_screen.isEnabled()
    first = win._pixmap.toImage()
    win.next_screen.click()
    assert pump(app, lambda: win.screen_label.text() == f"2 / {count}")
    assert win._pixmap.toImage() != first and win.prev_screen.isEnabled()
    win.prev_screen.click()
    assert pump(app, lambda: win.screen_label.text() == f"1 / {count}")
    win.next_screen.click()
    assert pump(app, lambda: win.screen_label.text() == f"2 / {count}")
    win.to_v.setValue(283)  # other verses: back to their first screen
    idle(win)
    assert win.screen_label.text().startswith("1 / ")
    win._set_language("ar")  # reads right to left
    assert win.prev_screen.text() == "›" and win.prev_screen.toolTip() == i18n.tr("Previous screen")
