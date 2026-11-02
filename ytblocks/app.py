"""Entry point."""
from __future__ import annotations

import locale
import os
import sys

from PySide6.QtWidgets import QApplication, QMessageBox

from .config import SETTINGS_DEFAULT, PLAYBACK_DEFAULT, JsonStore, Library, SeenStore


def main() -> int:
    app = QApplication(sys.argv)
    locale.setlocale(locale.LC_NUMERIC, "C")        # required by libmpv; Qt may reset it
    app.setApplicationName("ytblocks")
    app.setDesktopFileName("ytblocks")
    # NB: no setStyle()/setPalette()/style sheets - the platform theme (KDE
    # plasma-integration, qt6ct, Kvantum, ...) is used as-is and tracked live.
    from . import theme
    from .ui_main import MainWindow
    watcher = theme.ThemeWatcher()          # live re-theming when the platform palette changes
    app.installEventFilter(watcher)
    try:
        win = MainWindow(JsonStore("settings.json", SETTINGS_DEFAULT),
                         JsonStore("playback.json", PLAYBACK_DEFAULT), Library(), SeenStore())
    except OSError as e:
        QMessageBox.critical(None, "ytblocks", f"Cannot start: {e}\n\nIs mpv (libmpv) installed?")
        return 1
    win.show()
    rc = app.exec()
    # Everything is saved in closeEvent; skip waiting for in-flight yt-dlp workers.
    sys.stdout.flush()
    os._exit(rc)


if __name__ == "__main__":
    sys.exit(main())
