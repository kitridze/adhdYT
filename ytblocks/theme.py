"""Theming.  Two modes (setting ``theme_mode``):

* system  - nothing is hard-coded: every colour is derived from the live QPalette
            (KDE colour scheme, qt6ct, Kvantum ... - dark, light, Breeze, Dracula ...),
            and re-derived when the platform palette changes.
* custom  - the user picks text / background / controls / per-block outline colours;
            anything left on "auto" falls back to the system-derived value.

Outlines are always a single thin line, blended between text and background colour
(``outline_strength``, default 45 %) so they stay soft rather than vivid."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPalette, QPen
from PySide6.QtWidgets import QApplication, QCheckBox, QFrame, QLabel

_cfg = {"mode": "system", "colors": {}, "strength": 45}


def configure(settings: dict) -> None:
    _cfg["mode"] = settings.get("theme_mode", "system")
    _cfg["colors"] = dict(settings.get("colors") or {})
    _cfg["strength"] = max(10, min(100, int(settings.get("outline_strength", 45))))


def _custom(key: str):
    if _cfg["mode"] != "custom":
        return None
    c = QColor(_cfg["colors"].get(key) or "")
    return c if c.isValid() else None


def _blend(bg: QColor, fg: QColor, t: float) -> QColor:
    return QColor(*(round(b + (f - b) * t) for b, f in
                    ((bg.red(), fg.red()), (bg.green(), fg.green()), (bg.blue(), fg.blue()))))


def text_color(pal: QPalette) -> QColor:
    return _custom("text") or pal.color(QPalette.ColorRole.WindowText)


def bg_color(pal: QPalette) -> QColor:
    return _custom("background") or pal.color(QPalette.ColorRole.Window)


def outline_color(role: str, pal: QPalette) -> QColor:
    """role: a block role (red..purple) or 'controls'."""
    return _custom(role) or _blend(bg_color(pal), text_color(pal), _cfg["strength"] / 100)


def build_qss(pal: QPalette) -> str:
    o = outline_color("controls", pal).name()
    t = text_color(pal).name()
    b = bg_color(pal).name()
    dim = _blend(bg_color(pal), text_color(pal), 0.3).name()
    q = ""
    if _cfg["mode"] == "custom":
        q += f"""
QWidget {{ background-color: {b}; color: {t}; }}
QLabel {{ background: transparent; }}
QLineEdit, QComboBox, QSpinBox, QAbstractItemView {{ background-color: {b}; color: {t};
    border: 1px solid {o}; selection-background-color: {b}; selection-color: {t}; }}
QMenu {{ background-color: {b}; color: {t}; border: 1px solid {o}; }}
QMenu::item:selected {{ background: transparent; border: 1px solid {o}; }}
QToolTip {{ background-color: {b}; color: {t}; border: 1px solid {o}; }}
QScrollBar:vertical {{ background: {b}; width: 10px; margin: 0; }}
QScrollBar:horizontal {{ background: {b}; height: 10px; margin: 0; }}
QScrollBar::handle {{ background: {b}; border: 1px solid {o}; min-height: 20px; min-width: 20px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: {b}; }}
"""
    q += f"""
QPushButton, QToolButton {{ background: transparent; color: {t}; border: 1px solid {o}; padding: 1px 6px; }}
QPushButton:hover, QToolButton:hover, QToolButton:checked {{ border: 1px solid {t}; }}
QPushButton:disabled, QToolButton:disabled {{ border: 1px dashed {dim}; color: {dim}; }}
QToolButton::menu-indicator {{ image: none; }}
QSlider::groove:horizontal {{ border: 1px solid {o}; height: 3px; background: transparent; }}
QSlider::sub-page:horizontal, QSlider::add-page:horizontal {{ background: transparent; }}
QSlider::handle:horizontal {{ border: 1px solid {o}; background: {b}; width: 8px; margin: -6px 0; }}
QTreeWidget::item:selected, QTreeWidget::item:hover {{ background: transparent;
    border: 1px solid {o}; color: {t}; }}
"""
    return q


def refresh() -> None:
    """Re-apply the style sheet and repaint everything (call after any theme change)."""
    app = QApplication.instance()
    if app is None:
        return
    app.setStyleSheet(build_qss(app.palette()))
    for w in app.allWidgets():
        if isinstance(w, MonoLabel):
            w._fix()
        w.update()


class ThemeWatcher(QObject):
    """Re-derives colours when the platform palette changes (live dark/light switch)."""

    def __init__(self):
        super().__init__()
        self._busy = False

    def eventFilter(self, obj, e):
        if e.type() == QEvent.Type.ApplicationPaletteChange and not self._busy:
            self._busy = True
            try:
                refresh()
            finally:
                self._busy = False
        return False


class Block(QFrame):
    """A thin bordered block; the title sits in the top border."""

    def __init__(self, role: str, title: str = "", parent=None):
        super().__init__(parent)
        self.role, self.title, self.override = role, title, ""
        self._margins()

    def _margins(self):
        top = QFontMetrics(self.font()).height() + 3 if self.title else 4
        self.setContentsMargins(5, top, 5, 5)

    def set_accent(self, color: str) -> None:      # kept for API compatibility; colours come from theme
        self.update()

    def accent(self) -> QColor:
        return outline_color(self.role, self.palette())

    def changeEvent(self, e):
        if e.type() == QEvent.Type.FontChange:
            self._margins()
        super().changeEvent(e)

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self)
        pal = self.palette()
        fm = p.fontMetrics()
        top = fm.height() // 2 if self.title else 0
        p.setPen(QPen(self.accent(), 1))
        p.drawRect(QRectF(0.5, top + 0.5, self.width() - 1, self.height() - top - 1))
        if self.title:
            txt = f" {self.title} "
            w = fm.horizontalAdvance(txt)
            p.fillRect(10, 0, w, fm.height(), bg_color(pal))
            p.setPen(_blend(bg_color(pal), text_color(pal), 0.75))
            p.drawText(10, fm.ascent(), txt)


class RadioCheck(QCheckBox):
    """Multi-select checkbox drawn with a radio-style round indicator."""

    def sizeHint(self) -> QSize:
        fm = self.fontMetrics()
        return QSize(fm.horizontalAdvance(self.text()) + fm.height() + 12, fm.height() + 8)

    minimumSizeHint = sizeHint

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pal = self.palette()
        fg = text_color(pal)
        ring = outline_color("controls", pal)
        if not self.isEnabled():
            fg = ring
        d = self.fontMetrics().height() - 2
        r = QRectF(2.5, (self.height() - d) / 2, d, d)
        p.setPen(QPen(ring, 1.2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(r)
        if self.isChecked():
            p.setPen(QPen(fg, 1.2))
            p.drawEllipse(r.adjusted(3.5, 3.5, -3.5, -3.5))     # inner ring = checked (outline only)
        p.setPen(fg)
        p.drawText(QRectF(d + 8, 0, self.width() - d - 8, self.height()),
                   int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), self.text())
        if self.hasFocus():
            p.setPen(QPen(ring, 1, Qt.PenStyle.DotLine))
            p.drawLine(d + 8, self.height() - 3, self.width() - 2, self.height() - 3)


class MonoLabel(QLabel):
    """QLabel whose rich-text links use the plain text colour (no accent colour)."""

    def __init__(self, *a):
        super().__init__(*a)
        self._fix()

    def _fix(self):
        pal = self.palette()
        c = text_color(QApplication.palette())
        if pal.color(QPalette.ColorRole.Link) != c:
            pal.setColor(QPalette.ColorRole.Link, c)
            pal.setColor(QPalette.ColorRole.LinkVisited, c)
            self.setPalette(pal)

    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() == QEvent.Type.PaletteChange:
            self._fix()
