"""Red block (hideable burger bar) with the yellow settings button inside it."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QHBoxLayout, QInputDialog, QMenu, QToolButton, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout)

from .config import Library
from .theme import Block


class Sidebar(Block):
    channelOpen = Signal(str, str)
    playlistOpen = Signal(str)
    settingsRequested = Signal()
    collapseToggled = Signal(bool)

    def __init__(self, library: Library):
        super().__init__("red")
        self.library = library
        self.collapsed = False
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        self.settings_block = Block("yellow")
        sl = QHBoxLayout(self.settings_block)
        sl.setContentsMargins(0, 0, 0, 0)
        self.settings_btn = QToolButton(text="⚙", toolTip="Settings")
        self.settings_btn.setAutoRaise(True)
        self.settings_btn.clicked.connect(self.settingsRequested)
        sl.addWidget(self.settings_btn)
        self.burger = QToolButton(text="☰", toolTip="Show / hide playlists and channels")
        self.burger.setAutoRaise(True)
        self.burger.clicked.connect(lambda: self.set_collapsed(not self.collapsed))
        head.addWidget(self.settings_block)
        head.addWidget(self.burger)
        head.addStretch(1)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setFrameShape(QTreeWidget.Shape.NoFrame)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._menu)
        self.tree.itemClicked.connect(self._clicked)
        v.addLayout(head)
        v.addWidget(self.tree, 1)
        self.refresh()

    def header_width(self) -> int:
        return self.settings_block.width() + self.burger.sizeHint().width() + 14

    def set_collapsed(self, c: bool) -> None:
        self.collapsed = c
        self.tree.setVisible(not c)
        self.collapseToggled.emit(c)

    def refresh(self) -> None:
        self.tree.clear()
        pl = QTreeWidgetItem(["Playlists"])
        ch = QTreeWidgetItem(["Channels"])
        for g in (pl, ch):
            g.setFlags(Qt.ItemFlag.ItemIsEnabled)
        for p in self.library.data["playlists"]:
            it = QTreeWidgetItem([f"{p['name']} ↗" if p.get("yt_id") else f"{p['name']} ({len(p['items'])})"])
            it.setData(0, Qt.ItemDataRole.UserRole, ("playlist", p["name"]))
            pl.addChild(it)
        new = QTreeWidgetItem(["+ new playlist"])
        new.setData(0, Qt.ItemDataRole.UserRole, ("new", ""))
        pl.addChild(new)
        if not self.library.data["channels"]:
            hint = QTreeWidgetItem(["(use “＋ library” on any result)"])
            hint.setFlags(Qt.ItemFlag.NoItemFlags)
            ch.addChild(hint)
        for c in self.library.data["channels"]:
            it = QTreeWidgetItem([c["name"]])
            it.setData(0, Qt.ItemDataRole.UserRole, ("channel", c["id"], c["name"]))
            ch.addChild(it)
        self.tree.addTopLevelItems([pl, ch])
        self.tree.expandAll()

    def _clicked(self, it, _col):
        d = it.data(0, Qt.ItemDataRole.UserRole)
        if not d:
            return
        if d[0] == "channel":
            self.channelOpen.emit(d[1], d[2])
        elif d[0] == "playlist":
            self.playlistOpen.emit(d[1])
        elif d[0] == "new":
            name, ok = QInputDialog.getText(self, "New playlist", "Name:")
            if ok and name.strip():
                self.library.add_playlist(name.strip())
                self.refresh()

    def _menu(self, pos):
        it = self.tree.itemAt(pos)
        d = it.data(0, Qt.ItemDataRole.UserRole) if it else None
        if not d or d[0] not in ("playlist", "channel"):
            return
        m = QMenu(self)
        act = m.addAction("Delete playlist" if d[0] == "playlist" else "Remove channel")
        if m.exec(self.tree.viewport().mapToGlobal(pos)) is act:
            (self.library.remove_playlist if d[0] == "playlist" else self.library.remove_channel)(d[1])
            self.refresh()
