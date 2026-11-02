"""Main window: red | (green + blue / purple + light-blue), matching the mockup."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QFontDatabase, QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QInputDialog, QLineEdit, QMainWindow, QMenu,
                               QSplitter, QToolButton, QVBoxLayout, QWidget)

from . import yt
from .config import JsonStore, Library, SeenStore
from .filters import Filters
from . import theme
from .theme import Block
from .ui_filters import FilterStrip
from .ui_player import PlayerBlock
from .ui_results import ResultsView
from .ui_settings import SettingsDialog
from .ui_sidebar import Sidebar
from .workers import submit

MIN_VISIBLE = 8          # keep fetching pages while fewer rows than this pass the filters
MAX_CHAIN = 6


class MainWindow(QMainWindow):
    def __init__(self, settings: JsonStore, playback: JsonStore, library: Library, seen: SeenStore):
        super().__init__()
        self.st, self.lib, self.seen = settings, library, seen
        self.setWindowTitle("ytblocks")
        d = settings.data

        # ---- blocks
        self.sidebar = Sidebar(library)
        self.search_block = Block("green")
        sb = QHBoxLayout(self.search_block)
        sb.setContentsMargins(4, 0, 4, 0)
        self.search = QLineEdit(placeholderText="search youtube…  (enter)")
        self.search.setFrame(False)
        self.search.setClearButtonEnabled(True)
        sb.addWidget(self.search)
        self.filter_block = Block("blue")
        fb = QHBoxLayout(self.filter_block)
        fb.setContentsMargins(0, 0, 0, 0)
        self.filter_btn = QToolButton(text="≡", checkable=True, toolTip="Filter / sort")
        self.filter_btn.setAutoRaise(True)
        fb.addWidget(self.filter_btn)
        self.filters_ui = FilterStrip()
        self.filters_ui.set_filters(Filters.from_dict(d["filters"]))
        self.filters_ui.setVisible(d["filters_visible"])
        self.filter_btn.setChecked(d["filters_visible"])
        self.player = PlayerBlock(playback)
        self.results = ResultsView()
        self.results_block = Block("lightblue", "results")
        rl = QVBoxLayout(self.results_block)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(self.results)

        # ---- layout
        top = QHBoxLayout()
        top.setSpacing(4)
        top.addWidget(self.search_block, 1)
        top.addWidget(self.filter_block)
        self.content = QSplitter(Qt.Orientation.Horizontal)
        self.content.setChildrenCollapsible(False)
        self.content.addWidget(self.player)
        self.content.addWidget(self.results_block)
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(4)
        rv.addLayout(top)
        rv.addWidget(self.filters_ui)
        rv.addWidget(self.content, 1)
        self.split = QSplitter(Qt.Orientation.Horizontal)
        self.split.setChildrenCollapsible(False)
        self.split.addWidget(self.sidebar)
        self.split.addWidget(right)
        self.setCentralWidget(self.split)

        # ---- feed state
        self.feed = None
        self.query = ""
        self.mode = "search"
        self.channel_ctx = ("", "")       # (id, name) while viewing a channel
        self.playlist_ctx = ""
        self.all_items: list[yt.Item] = []
        self.loading = False
        self.chain = 0
        self._gen = 0

        # ---- signals
        self.search.returnPressed.connect(self.run_search)
        self.filter_btn.toggled.connect(self._toggle_filters)
        self.filters_ui.changed.connect(self._filters_changed)
        self.results.itemActivated.connect(self._item_activated)
        self.results.channelRequested.connect(lambda it: self.open_channel(it.channel_id, it.channel))
        self.results.needMore.connect(self._user_more)
        self.results.contextRequested.connect(self._row_menu)
        self.results.backRequested.connect(self._back)
        self.results.saveChannelRequested.connect(self._save_channel)
        self.sidebar.channelOpen.connect(self.open_channel)
        self.sidebar.playlistOpen.connect(self.open_playlist)
        self.sidebar.settingsRequested.connect(self._open_settings)
        self.sidebar.collapseToggled.connect(self._collapse)
        self.player.channelRequested.connect(self.open_channel)
        self.player.playbackStarted.connect(self._played)
        self.player.navigate.connect(self.results.step)
        self.player.libraryRequested.connect(self._row_menu)
        for key, delta in (("Ctrl+Left", -1), ("Ctrl+Right", +1)):      # also while a video is playing
            QShortcut(QKeySequence(key), self, activated=lambda delta=delta: self.results.step(delta))
        try:                                  # live light/dark switching (Qt >= 6.5)
            QGuiApplication.styleHints().colorSchemeChanged.connect(self._repaint_all)
        except AttributeError:
            pass

        self.resize(d["window"]["w"], d["window"]["h"])
        self._search_back = None
        self._configured = False
        self.apply_settings()
        QTimer.singleShot(0, self._apply_sizes)

    # ------------------------------------------------------------ settings
    def apply_settings(self, resize: bool = False):
        d = self.st.data
        fam = d["ui_font"] or QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont).family()
        f = QFont(fam)
        f.setPointSize(d["ui_font_size"])
        QApplication.setFont(f)
        self.results.set_font_size(d["results_font_size"])
        h = d["topbar_height"]
        self.search_block.setFixedHeight(h)
        self.filter_block.setFixedSize(d["filter_btn_width"], h)
        s = d["settings_btn_size"]
        self.sidebar.settings_block.setFixedSize(s, s)
        for blk in (self.sidebar, self.sidebar.settings_block, self.search_block,
                    self.filter_block, self.filters_ui, self.results_block, self.player):
            blk.set_accent("")
        theme.configure(d)
        theme.refresh()
        if not self._configured:
            self._configured = True
            self.sidebar.set_collapsed(d["sidebar_collapsed"])
        if resize:
            self._apply_sizes()

    def _apply_sizes(self):
        d = self.st.data
        if self.sidebar.collapsed:
            self._collapse(True)
        else:
            self._collapse(False)
        cw = max(self.content.width(), 1000)
        pw = int(cw * d["player_pct"] / 100)
        self.content.setSizes([pw, cw - pw])

    def _collapse(self, c: bool):
        self.st.data["sidebar_collapsed"] = c
        hw = self.sidebar.header_width()
        total = max(self.split.width(), 1000)
        if c:
            self.sidebar.setMinimumWidth(hw)
            self.sidebar.setMaximumWidth(hw)
            self.split.setSizes([hw, total - hw])
        else:
            self.sidebar.setMinimumWidth(80)
            self.sidebar.setMaximumWidth(16777215)
            w = self.st.data["sidebar_width"]
            self.split.setSizes([w, total - w])

    def _open_settings(self):
        SettingsDialog(self.st, self.apply_settings, self).exec()

    def _repaint_all(self, *_):
        theme.refresh()
        for w in self.findChildren(QWidget):
            w.update()

    def _toggle_filters(self, on: bool):
        self.filters_ui.setVisible(on)
        self.st.data["filters_visible"] = on
        self.st.save()

    # ------------------------------------------------------------ feeds
    def _filters(self) -> Filters:
        return self.filters_ui.filters()

    def run_search(self):
        q = self.search.text().strip()
        if not q:
            return
        self.query = q
        self._search_back = None
        self._start_search()

    def _start_search(self):
        f = self._filters()
        self.channel_ctx, self.playlist_ctx = ("", ""), ""
        self._start(yt.SearchFeed(self.query, f.server_sort(), f.server_type()),
                    f'search: "{self.query}"', back=False, save=False)

    def open_channel(self, cid: str, name: str):
        if not cid:
            return
        if self.mode == "search" and self.feed is not None and self.feed.mode == "search":
            self._search_back = (self.query,)
        self.channel_ctx, self.playlist_ctx = (cid, name), ""
        self._start(yt.YtdlpFeed(f"https://www.youtube.com/channel/{cid}/videos", "channel"),
                    f"channel: {name}", back=True, save=True)

    def open_playlist(self, name: str):
        p = self.lib.playlist(name)
        if p is None:
            return
        if p.get("yt_id"):
            self._open_yt_playlist(yt.Item("playlist", p["yt_id"], name, seed=p.get("seed", "")))
            return
        self.channel_ctx, self.playlist_ctx = ("", ""), name
        self._start(yt.LocalFeed([yt.Item.from_dict(i) for i in p["items"]]),
                    f"playlist: {name}", back=False, save=False)

    def _open_yt_playlist(self, it: yt.Item):
        try:
            url = yt.playlist_url(it)
        except RuntimeError as e:
            self.results.set_status(f"error: {e}")
            return
        self.channel_ctx, self.playlist_ctx = ("", ""), ""
        self._start(yt.YtdlpFeed(url, "playlist"), f"playlist: {it.title}", back=self._search_back is not None, save=False)

    def _back(self):
        if self._search_back:
            self.query = self._search_back[0]
            self._search_back = None
            self._start_search()

    def _start(self, feed, title: str, back: bool, save: bool):
        self._gen += 1
        self.feed, self.mode = feed, feed.mode
        self.all_items, self.chain, self.loading = [], 0, False
        self.results.clear()
        self.results.set_header(title, back and self._search_back is not None, save)
        self._refresh_save_btn()
        self._load_more()

    def _load_more(self):
        if self.loading or self.feed is None or self.feed.exhausted:
            return
        self.loading = True
        gen = self._gen
        self.results.set_status("loading…")
        submit(self.feed.fetch_more, done=lambda items: self._on_page(gen, items),
               fail=lambda m: self._on_fail(gen, m))

    def _user_more(self):
        self.chain = 0
        self._load_more()

    def _on_fail(self, gen, msg):
        if gen == self._gen:
            self.loading = False
            self.results.set_status(f"error: {msg}")

    def _on_page(self, gen, items):
        if gen != self._gen:
            return
        self.loading = False
        self.all_items += items
        f = self._filters()
        is_search = self.mode == "search"
        if f.client_sorts(is_search):
            self._rebuild()
        else:
            self.results.add_items([i for i in items if f.accept(i, self.seen.ids)], self.seen.ids)
        if self.feed.exhausted:
            self.results.set_status("— end of results —" if self.results.count()
                                    else "no results match the current filters")
            return
        self.results.set_status("")
        if self.results.count() < MIN_VISIBLE and self.chain < MAX_CHAIN:
            self.chain += 1
            self._load_more()

    def _rebuild(self):
        f = self._filters()
        keep = self.results.scroll.verticalScrollBar().value()
        vis = f.sort_items([i for i in self.all_items if f.accept(i, self.seen.ids)])
        self.results.clear()
        self.results.add_items(vis, self.seen.ids)
        QTimer.singleShot(0, lambda: self.results.scroll.verticalScrollBar().setValue(keep))

    def _filters_changed(self):
        f = self._filters()
        old = Filters.from_dict(self.st.data["filters"])
        self.st.data["filters"] = f.to_dict()
        self.st.save()
        if self.mode == "search" and self.query and f.server_sig() != old.server_sig():
            self._start_search()
            return
        self._rebuild()
        if self.feed is not None and not self.feed.exhausted and self.results.count() < MIN_VISIBLE:
            self._user_more()

    # ------------------------------------------------------------ rows
    def _item_activated(self, it: yt.Item):
        if it.kind in ("video", "short"):
            self.player.show_item(it)
        elif it.kind == "channel":
            self.open_channel(it.channel_id or it.id, it.title)
        elif it.kind == "playlist":
            self._open_yt_playlist(it)

    def _played(self, vid: str):
        self.seen.add(vid)
        self.results.mark_seen(vid)

    def _is_saved(self, cid: str) -> bool:
        return any(c["id"] == cid for c in self.lib.data["channels"])

    def _refresh_save_btn(self):
        cid = self.channel_ctx[0]
        self.results.save.setText("✓ saved (click to remove)" if cid and self._is_saved(cid) else "☆ save channel")

    def _toggle_channel(self, cid: str, name: str):
        if self._is_saved(cid):
            self.lib.remove_channel(cid)
            self.results.set_status(f"removed channel “{name}” from library")
        else:
            self.lib.save_channel(cid, name)
            self.results.set_status(f"saved channel “{name}” — see Channels in the sidebar")
        self.sidebar.refresh()
        self._refresh_save_btn()

    def _save_channel(self):
        cid, name = self.channel_ctx
        if cid:
            self._toggle_channel(cid, name)

    def _row_menu(self, it: yt.Item, pos):
        """One place for every 'add to library' action (＋ library buttons + right-click)."""
        m = QMenu(self)
        if it.kind in ("video", "short"):
            lists = m.addMenu("＋ Add to playlist")
            for p in self.lib.data["playlists"]:
                if p.get("yt_id"):
                    continue
                a = lists.addAction(p["name"])
                a.setCheckable(True)
                a.setChecked(any(i.get("id") == it.id for i in p["items"]))
                a.triggered.connect(lambda _=False, n=p["name"]: self._add_to(n, it))
            if lists.actions():
                lists.addSeparator()
            lists.addAction("New playlist…", lambda: self._new_playlist_for(it))
        if it.kind == "playlist":
            m.addAction("＋ Save this playlist to library", lambda: self._save_yt_playlist(it))
        cid = it.id if it.kind == "channel" else it.channel_id
        name = it.title if it.kind == "channel" else it.channel
        if cid:
            saved = self._is_saved(cid)
            m.addAction(f"{'✓ Channel saved — remove' if saved else '＋ Save channel'}: {name}",
                        lambda: self._toggle_channel(cid, name))
        m.addSeparator()
        m.addAction("Copy link", lambda: QApplication.clipboard().setText(it.url))
        if self.playlist_ctx:
            m.addAction("Remove from this playlist", lambda: self._remove_from(it))
        m.exec(pos)

    def _save_yt_playlist(self, it: yt.Item):
        self.lib.save_yt_playlist(it.title, it.id, it.seed)
        self.sidebar.refresh()
        self.results.set_status(f"saved playlist “{it.title}” — see Playlists in the sidebar (↗)")

    def _add_to(self, name: str, it: yt.Item):
        self.lib.add_to_playlist(name, it.to_dict())
        self.sidebar.refresh()
        self.results.set_status(f"added to playlist “{name}”")

    def _new_playlist_for(self, it: yt.Item):
        name, ok = QInputDialog.getText(self, "New playlist", "Name:")
        if ok and name.strip():
            self.lib.add_playlist(name.strip())
            self._add_to(name.strip(), it)

    def _remove_from(self, it: yt.Item):
        self.lib.remove_from_playlist(self.playlist_ctx, it.id)
        self.sidebar.refresh()
        self.open_playlist(self.playlist_ctx)

    # ------------------------------------------------------------ lifecycle
    def closeEvent(self, e):
        d = self.st.data
        d["window"] = {"w": self.width(), "h": self.height()}
        sizes = self.split.sizes()
        if not self.sidebar.collapsed and sizes[0] > 0:
            d["sidebar_width"] = sizes[0]
        cs = self.content.sizes()
        if sum(cs) > 0:
            d["player_pct"] = max(15, min(85, round(100 * cs[0] / sum(cs))))
        d["filters"] = self._filters().to_dict()
        self.st.save()
        self.player.shutdown()
        super().closeEvent(e)
