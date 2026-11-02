"""Light-blue block: results list (titles, views, channel, date), infinite scroll."""
from __future__ import annotations

import html

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QPainter, QPalette, QPen, QShortcut
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QScrollArea, QToolButton,
                               QVBoxLayout, QWidget)

from .theme import MonoLabel, outline_color
from .yt import Item

TAGS = {"channel": "[channel] ", "playlist": "[playlist] ", "short": "[short] "}


def _dur(s):
    if s is None:
        return ""
    h, r = divmod(int(s), 3600)
    m, s = divmod(r, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


class ResultRow(QFrame):
    clicked = Signal(object)
    channelClicked = Signal(object)
    context = Signal(object, object)

    def __init__(self, item: Item, seen: bool):
        super().__init__()
        self.item, self.selected, self.seen = item, False, seen
        v = QVBoxLayout(self)
        v.setContentsMargins(8, 5, 8, 5)
        v.setSpacing(2)
        self.title = QLabel(wordWrap=True)
        f = self.title.font()
        f.setBold(True)
        self.title.setFont(f)
        meta = QHBoxLayout()
        meta.setSpacing(6)
        self.chan = MonoLabel()
        if item.channel and item.kind != "channel" and item.channel_id:
            self.chan.setText(f'<a href="#">{html.escape(item.channel)}</a>')
            self.chan.linkActivated.connect(lambda _=None: self.channelClicked.emit(item))
        else:
            self.chan.setText(html.escape(item.channel))
        bits = [item.views_text or item.count_text, item.date_text,
                "LIVE" if item.live else _dur(item.duration)]
        self.info = QLabel("  ·  ".join(b for b in bits if b))
        meta.addWidget(self.chan)
        meta.addWidget(self.info)
        meta.addStretch(1)
        self.add = QToolButton(text="＋ library", toolTip="Add to playlist / save channel…")
        self.add.clicked.connect(lambda: self.context.emit(item, self.add.mapToGlobal(self.add.rect().bottomLeft())))
        meta.addWidget(self.add)
        v.addWidget(self.title)
        v.addLayout(meta)
        self.refresh_title()

    def refresh_title(self):
        t = ("✓ " if self.seen else "") + TAGS.get(self.item.kind, "") + self.item.title
        self.title.setText(t)

    def set_selected(self, s: bool):
        self.selected = s
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.item)

    def contextMenuEvent(self, e):
        self.context.emit(self.item, e.globalPos())

    def paintEvent(self, e):
        p = QPainter(self)
        pal = self.palette()
        if self.selected:
            p.setPen(QPen(outline_color("controls", pal), 1.5))     # outline, no fill
            p.drawRect(self.rect().adjusted(1, 1, -2, -2))
        p.setPen(pal.color(QPalette.ColorRole.Mid))
        p.drawLine(0, self.height() - 1, self.width(), self.height() - 1)


class ResultsView(QWidget):
    itemActivated = Signal(object)
    channelRequested = Signal(object)
    needMore = Signal()
    contextRequested = Signal(object, object)
    backRequested = Signal()
    saveChannelRequested = Signal()

    def __init__(self):
        super().__init__()
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        head = QHBoxLayout()
        self.prev_btn = QToolButton(text="◀", toolTip="Previous video (←)")
        self.next_btn = QToolButton(text="▶", toolTip="Next video (→)")
        self.prev_btn.clicked.connect(lambda: self.step(-1))
        self.next_btn.clicked.connect(lambda: self.step(+1))
        head.addWidget(self.prev_btn)
        head.addWidget(self.next_btn)
        self.back = QToolButton(text="←", toolTip="Back to search results")
        self.back.clicked.connect(self.backRequested)
        self.header = QLabel()
        self.save = QToolButton(text="★ save channel")
        self.save.clicked.connect(self.saveChannelRequested)
        head.addWidget(self.back)
        head.addWidget(self.header, 1)
        head.addWidget(self.save)
        self.scroll = QScrollArea(widgetResizable=True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.holder = QWidget()
        self.box = QVBoxLayout(self.holder)
        self.box.setContentsMargins(0, 0, 0, 0)
        self.box.setSpacing(0)
        self.box.addStretch(1)
        self.scroll.setWidget(self.holder)
        self.status = QLabel()
        v.addLayout(head)
        v.addWidget(self.scroll, 1)
        v.addWidget(self.status)
        self.rows: list[ResultRow] = []
        self.selected_id = None
        self._font_size = 11
        self.scroll.verticalScrollBar().valueChanged.connect(self._scrolled)
        self.set_header("", False, False)
        for key, d in (("Left", -1), ("Right", +1)):
            sc = QShortcut(QKeySequence(key), self)
            sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc.activated.connect(lambda d=d: self.step(d))

    def set_header(self, text: str, back: bool, save: bool):
        self.header.setText(text)
        self.back.setVisible(back)
        self.save.setVisible(save)

    def set_status(self, t: str):
        self.status.setText(t)

    def count(self) -> int:
        return len(self.rows)

    def clear(self):
        for r in self.rows:
            r.setParent(None)
            r.deleteLater()
        self.rows.clear()
        self.scroll.verticalScrollBar().setValue(0)

    def set_font_size(self, n: int):
        self._font_size = n
        f = self.holder.font()
        f.setPointSize(n)
        self.holder.setFont(f)
        for r in self.rows:
            bf = r.title.font()
            bf.setPointSize(n)
            bf.setBold(True)
            r.title.setFont(bf)

    def add_items(self, items, seen_ids):
        for it in items:
            r = ResultRow(it, it.id in seen_ids)
            r.clicked.connect(self._select)
            r.channelClicked.connect(self.channelRequested)
            r.context.connect(self.contextRequested)
            bf = r.title.font()
            bf.setPointSize(self._font_size)
            bf.setBold(True)
            r.title.setFont(bf)
            r.set_selected(it.id == self.selected_id)
            self.box.insertWidget(self.box.count() - 1, r)
            self.rows.append(r)
        QTimer.singleShot(0, self._check_fill)

    def step(self, d: int):
        """Select the previous/next video row (details load; nothing plays)."""
        vids = [r for r in self.rows if r.item.kind in ("video", "short")]
        if not vids:
            return
        idx = next((i for i, r in enumerate(vids) if r.item.id == self.selected_id), -1)
        j = idx + d if idx >= 0 else (0 if d > 0 else len(vids) - 1)
        if j < 0:
            return
        if j >= len(vids):
            self.needMore.emit()
            return
        self.scroll.ensureWidgetVisible(vids[j])
        self._select(vids[j].item)
        if j >= len(vids) - 3:
            self.needMore.emit()

    def _select(self, item):
        self.selected_id = item.id
        for r in self.rows:
            r.set_selected(r.item.id == item.id)
        self.itemActivated.emit(item)

    def mark_seen(self, vid: str):
        for r in self.rows:
            if r.item.id == vid:
                r.seen = True
                r.refresh_title()

    def _scrolled(self, value):
        if self.scroll.verticalScrollBar().maximum() - value < 300:
            self.needMore.emit()

    def _check_fill(self):
        if self.scroll.verticalScrollBar().maximum() < 50:
            self.needMore.emit()
