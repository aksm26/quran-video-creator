# PyInstaller spec: one folder per OS (keeps the LGPL Qt libraries swappable). Build from the repo root:
#     pyinstaller packaging/quran_video.spec
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

ROOT = Path(SPECPATH).parent
sys.path.insert(0, str(ROOT))
from quran_video import __version__  # noqa: E402
NAME = "QuranVideoCreator"
ICON = str(ROOT / "assets/ui/app.png")  # Pillow converts it to .ico / .icns

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    # assets/ sits next to quran_video/ in the bundle, so the Path(__file__).parents[2] / "assets" lookups work as is
    datas=[(str(ROOT / "assets"), "assets"), (str(ROOT / "LICENSE"), "."), (str(ROOT / "THIRD_PARTY.md"), "."),
           (str(ROOT / "PRIVACY.md"), "."), (str(ROOT / "TERMS.md"), "."),(str(ROOT / "quran_video/config/LICENSE-CLDR.txt"), "quran_video/config")]
          + collect_data_files("imageio_ffmpeg", subdir="binaries"),  # the ffmpeg executable
    excludes=["tkinter", "pytest"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name=NAME, console=False, icon=ICON)
coll = COLLECT(exe, a.binaries, a.datas, name=NAME)
if sys.platform == "darwin":
    app = BUNDLE(coll, name=f"{NAME}.app", icon=ICON, bundle_identifier="io.github.quranvideocreator",
                 version=__version__, info_plist={"NSHighResolutionCapable": True})
