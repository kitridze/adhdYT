"""Yellow block: settings dialog.  Every change is applied live and persisted."""
from __future__ import annotations

import copy

from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDialog, QFontComboBox, QFormLayout,
                               QHBoxLayout, QLabel, QPushButton, QRadioButton, QSpinBox, QVBoxLayout, QWidget)

from .config import SETTINGS_DEFAULT, JsonStore

SIZE_ROWS = (
    ("sidebar_width", "Red: sidebar width (px)", 80, 600),
    ("topbar_height", "Green: search bar height (px)", 24, 120),
    ("filter_btn_width", "Blue: filter button width (px)", 24, 200),
    ("settings_btn_size", "Yellow: settings button size (px)", 16, 80),
    ("player_pct", "Purple: player share of width (%)", 15, 85),
)


THEME_ROWS = (
    ("text", "Text"), ("background", "Background"), ("controls", "Controls (buttons, sliders, selection)"),
    ("red", "Sidebar outline"), ("yellow", "Settings outline"), ("green", "Search outline"),
    ("blue", "Filter / sort outline"), ("lightblue", "Results outline"), ("purple", "Player outline"),
)
PRESETS = {      # text, background, outline
    "Dark": ("#d4d4d4", "#1e1e1e", "#5a5a5a"),
    "Light": ("#2b2b2b", "#fafafa", "#b5b5b5"),
    "Dracula": ("#f8f8f2", "#282a36", "#6272a4"),
    "Nord": ("#d8dee9", "#2e3440", "#4c566a"),
}


class SettingsDialog(QDialog):
    def __init__(self, store: JsonStore, on_change, parent=None):
        super().__init__(parent)
        self.store, self.on_change = store, on_change
        self.setWindowTitle("ytblocks — settings")
        d = store.data
        form = QFormLayout()

        self.spins = {}
        for key, label, lo, hi in SIZE_ROWS:
            s = QSpinBox(minimum=lo, maximum=hi, value=d[key])
            s.valueChanged.connect(lambda v, k=key: self._set(k, v))
            self.spins[key] = s
            form.addRow(label, s)
        form.addRow(QLabel("<i>Blocks can also be resized by dragging the splitters.</i>"))

        self.sys_font = QCheckBox("Use system monospace font", checked=not d["ui_font"])
        self.font_box = QFontComboBox()
        self.font_box.setCurrentFont(QFont(d["ui_font"] or "monospace"))
        self.font_box.setEnabled(bool(d["ui_font"]))
        self.sys_font.toggled.connect(self._font_mode)
        self.font_box.currentFontChanged.connect(lambda f: self._set("ui_font", f.family()))
        self.ui_size = QSpinBox(minimum=7, maximum=24, value=d["ui_font_size"])
        self.ui_size.valueChanged.connect(lambda v: self._set("ui_font_size", v))
        self.res_size = QSpinBox(minimum=7, maximum=28, value=d["results_font_size"])
        self.res_size.valueChanged.connect(lambda v: self._set("results_font_size", v))
        form.addRow(self.sys_font)
        form.addRow("Font family", self.font_box)
        form.addRow("Interface font size", self.ui_size)
        form.addRow("Results list font size", self.res_size)

        self.mode_sys = QRadioButton("Follow system theme (dark / light / Breeze / Dracula… as set in KDE, qt6ct, Kvantum)")
        self.mode_cus = QRadioButton("Custom colours")
        (self.mode_cus if d["theme_mode"] == "custom" else self.mode_sys).setChecked(True)
        self.mode_cus.toggled.connect(self._mode)
        self.strength = QSpinBox(minimum=10, maximum=100, value=d["outline_strength"], suffix=" %")
        self.strength.valueChanged.connect(lambda v: self._set("outline_strength", v))
        form.addRow(QLabel("<b>Theme</b>"))
        form.addRow(self.mode_sys)
        form.addRow(self.mode_cus)
        form.addRow("Outline strength (lower = softer)", self.strength)
        self.custom_box = QWidget()
        cf = QFormLayout(self.custom_box)
        cf.setContentsMargins(0, 0, 0, 0)
        self.preset = QComboBox()
        self.preset.addItem("Start from preset…")
        self.preset.addItems(list(PRESETS))
        self.preset.activated.connect(self._preset)
        cf.addRow(self.preset)
        self.color_btns = {}
        for key, label in THEME_ROWS:
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            b = QPushButton()
            b.clicked.connect(lambda _=False, k=key: self._pick(k))
            auto = QPushButton("auto")
            auto.setToolTip("Derive from the system theme")
            auto.clicked.connect(lambda _=False, k=key: self._color(k, ""))
            h.addWidget(b, 1)
            h.addWidget(auto)
            self.color_btns[key] = b
            cf.addRow(label, row)
            self._paint_btn(key)
        self.custom_box.setEnabled(d["theme_mode"] == "custom")
        form.addRow(self.custom_box)

        reset_all = QPushButton("Reset everything to defaults")
        reset_all.clicked.connect(self._reset_all)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        v = QVBoxLayout(self)
        v.addLayout(form)
        v.addWidget(reset_all)
        v.addWidget(close)

    def _set(self, key, val):
        self.store.data[key] = val
        self.store.save()
        self.on_change()

    def _font_mode(self, system: bool):
        self.font_box.setEnabled(not system)
        self._set("ui_font", "" if system else self.font_box.currentFont().family())

    def _mode(self, custom: bool):
        self.custom_box.setEnabled(custom)
        self._set("theme_mode", "custom" if custom else "system")

    def _paint_btn(self, key):
        c = self.store.data["colors"].get(key, "")
        b = self.color_btns[key]
        b.setText(c if c else "auto (system)")

    def _pick(self, key):
        cur = QColor(self.store.data["colors"].get(key) or "#808080")
        c = QColorDialog.getColor(cur, self, "Choose colour")
        if c.isValid():
            self._color(key, c.name())

    def _color(self, key, value):
        self.store.data["colors"][key] = value
        self.store.save()
        self._paint_btn(key)
        self.on_change()

    def _preset(self, idx):
        if idx <= 0:
            return
        text, bg, line = PRESETS[self.preset.currentText()]
        cols = self.store.data["colors"]
        cols.update({"text": text, "background": bg, "controls": line,
                     **{r: line for r in ("red", "yellow", "green", "blue", "lightblue", "purple")}})
        self.store.save()
        for k in self.color_btns:
            self._paint_btn(k)
        self.preset.setCurrentIndex(0)
        self.on_change()

    def _reset_all(self):
        keep = self.store.data.get("filters")
        self.store.data.clear()
        self.store.data.update(copy.deepcopy(SETTINGS_DEFAULT))
        if keep:
            self.store.data["filters"] = keep
        self.store.save()
        d = self.store.data
        for key, s in self.spins.items():
            s.blockSignals(True)
            s.setValue(d[key])
            s.blockSignals(False)
        self.sys_font.setChecked(True)
        self.strength.blockSignals(True)
        self.strength.setValue(d["outline_strength"])
        self.strength.blockSignals(False)
        self.mode_sys.setChecked(True)
        self.custom_box.setEnabled(False)
        for k in self.color_btns:
            self._paint_btn(k)
        self.ui_size.setValue(d["ui_font_size"])
        self.res_size.setValue(d["results_font_size"])
        self.on_change(True)
