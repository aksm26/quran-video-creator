"""The About dialog: version, where the data comes from, and the licences."""

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QCheckBox, QDialog, QDialogButtonBox, QLabel, QVBoxLayout

from .. import __version__
from ..i18n import ABOUT_DATA, tr


def about_html() -> str:
    return (
        f"<h3>Quran Video Creator {__version__}</h3>"
        f"<p>{tr('Recitation videos with the Arabic synced to the reciter.')}</p>"
        f"<p><b>{tr('Data and audio')}</b><br>{tr(ABOUT_DATA)}<br>"
        '<a href="https://quran.com">Quran.com</a> · <a href="https://api-docs.quran.foundation">API</a> · '
        '<a href="https://quranicaudio.com">quranicaudio.com</a><br>'
        'Quran data provided by <a href="https://quran.foundation">Quran.Foundation</a>.</p>'
        f"<p><b>{tr('Fonts')}</b><br>"  # font and licence names are not translated
        "QPC Hafs (KFGQPC licence), Amiri Quran, Amiri, Digital Khatt, Figtree (SIL OFL 1.1), "
        "Surah Name V2 (quranfonts.com)</p>"
        f"<p><b>{tr('Icons')}</b><br>"
        '<a href="https://icons.getbootstrap.com">Bootstrap Icons</a> (MIT)</p>'
        f"<p><b>{tr('Video')}</b><br>{tr('FFmpeg, bundled through imageio-ffmpeg.')}</p>"
        '<p><a href="https://www.gnu.org/licenses/gpl-3.0.html">GPL-3.0</a> · '
        '<a href="https://www.qt.io/qt-for-python">Qt / PySide6</a> (LGPL-3.0)</p>'
    )


class AboutDialog(QDialog):
    def __init__(self, settings: QSettings, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("About"))
        self.setMinimumWidth(520)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 16)
        label = QLabel(about_html())
        label.setWordWrap(True)
        label.setOpenExternalLinks(True)
        lay.addWidget(label)
        check = QCheckBox(tr("Check for updates when the app starts"))
        check.setChecked(settings.value("check_updates", True, type=bool))
        check.toggled.connect(lambda on: settings.setValue("check_updates", on))
        lay.addWidget(check)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText(tr("Close"))
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
