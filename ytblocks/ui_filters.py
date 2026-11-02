"""Blue block: sort + filter strip (shown/hidden by the blue toggle button)."""
from __future__ import annotations

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QGridLayout, QLabel, QRadioButton,
                               QSpinBox)

from .filters import SORTS, Filters
from .theme import Block, RadioCheck


def _spin(maxv, step, tip):
    s = QSpinBox()
    s.setRange(0, maxv)
    s.setSingleStep(step)
    s.setSpecialValueText("off")
    s.setToolTip(tip)
    return s


class FilterStrip(Block):
    changed = Signal()

    def __init__(self):
        super().__init__("blue", "filter / sort")
        self.sort = QComboBox()
        for key, label in SORTS:
            self.sort.addItem(label, key)
        self.min_len = _spin(1000, 1, "minimum length, minutes")
        self.max_len = _spin(1000, 5, "maximum length, minutes")
        self.min_views = _spin(2_000_000_000, 1000, "minimum view count")
        self.min_len.setSuffix(" min")
        self.max_len.setSuffix(" min")
        self.types = {k: RadioCheck(label) for k, label in
                      (("video", "videos"), ("channel", "channels"),
                       ("playlist", "playlists"), ("short", "shorts"))}
        self.seen = {"both": QRadioButton("both"), "seen": QRadioButton("seen only"),
                     "unseen": QRadioButton("not seen only")}
        grp = QButtonGroup(self)
        for b in self.seen.values():
            grp.addButton(b)

        g = QGridLayout(self)
        g.setContentsMargins(0, 0, 0, 0)
        g.addWidget(QLabel("sort"), 0, 0)
        g.addWidget(self.sort, 0, 1)
        g.addWidget(QLabel("length ≥"), 0, 2)
        g.addWidget(self.min_len, 0, 3)
        g.addWidget(QLabel("≤"), 0, 4)
        g.addWidget(self.max_len, 0, 5)
        g.addWidget(QLabel("views ≥"), 0, 6)
        g.addWidget(self.min_views, 0, 7)
        g.addWidget(QLabel("type"), 1, 0)
        for i, cb in enumerate(self.types.values()):
            g.addWidget(cb, 1, 1 + i)
        g.addWidget(QLabel("seen"), 1, 5)
        for i, rb in enumerate(self.seen.values()):
            g.addWidget(rb, 1, 6 + i)
        g.setColumnStretch(9, 1)

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(400)
        self._debounce.timeout.connect(self.changed)
        for w in (self.min_len, self.max_len, self.min_views):
            w.valueChanged.connect(lambda _=None: self._debounce.start())
        self.sort.currentIndexChanged.connect(lambda _=None: self._debounce.start())
        for w in (*self.types.values(), *self.seen.values()):
            w.toggled.connect(lambda _=None: self._debounce.start())

    def filters(self) -> Filters:
        return Filters(sort=self.sort.currentData(), min_len=self.min_len.value(),
                       max_len=self.max_len.value(), min_views=self.min_views.value(),
                       types={k: cb.isChecked() for k, cb in self.types.items()},
                       seen=next(k for k, b in self.seen.items() if b.isChecked()))

    def set_filters(self, f: Filters) -> None:
        for w in (self.sort, self.min_len, self.max_len, self.min_views,
                  *self.types.values(), *self.seen.values()):
            w.blockSignals(True)
        self.sort.setCurrentIndex(max(0, self.sort.findData(f.sort)))
        self.min_len.setValue(f.min_len)
        self.max_len.setValue(f.max_len)
        self.min_views.setValue(f.min_views)
        for k, cb in self.types.items():
            cb.setChecked(f.types.get(k, False))
        self.seen.get(f.seen, self.seen["both"]).setChecked(True)
        for w in (self.sort, self.min_len, self.max_len, self.min_views,
                  *self.types.values(), *self.seen.values()):
            w.blockSignals(False)
