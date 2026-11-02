"""Purple block: details page (thumbnail, stats, comments) -> video page (libmpv)."""
from __future__ import annotations

import html
import time

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QKeySequence, QPalette, QPixmap, QShortcut
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QPushButton, QScrollArea,
                               QSlider, QStackedWidget, QToolButton, QVBoxLayout, QWidget)

from . import yt
from .adguard import AdBlocked
from .config import JsonStore
from .mpvcore import MpvVideo
from .theme import Block, MonoLabel
from .workers import submit

INFO_MAX_AGE = 3 * 3600          # googlevideo URLs expire after ~6 h; refresh well before
SPEEDS = (0.5, 0.75, 1.0, 1.25, 1.5, 2.0)


def _t(s: float) -> str:
    s = int(max(0, s))
    h, r = divmod(s, 3600)
    m, s = divmod(r, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _n(v) -> str:
    return f"{v:,}" if isinstance(v, int) else "n/a"


class DetailsPage(QScrollArea):
    playClicked = Signal()
    channelClicked = Signal(str, str)
    navClicked = Signal(int)
    libClicked = Signal(object)

    def __init__(self):
        super().__init__()
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.Shape.NoFrame)
        w = QWidget()
        v = QVBoxLayout(w)
        self._pix = None
        self.thumb = QLabel(alignment=Qt.AlignmentFlag.AlignCenter)
        self.thumb.setMinimumHeight(90)
        self.play = QPushButton("▶  play")
        self.play.clicked.connect(self.playClicked)
        self.prev_btn = QPushButton("‹ prev")
        self.prev_btn.setToolTip("Previous video in the list (←)")
        self.prev_btn.clicked.connect(lambda: self.navClicked.emit(-1))
        self.next_btn = QPushButton("next ›")
        self.next_btn.setToolTip("Next video in the list (→)")
        self.next_btn.clicked.connect(lambda: self.navClicked.emit(+1))
        self.lib_btn = QPushButton("＋ library")
        self.lib_btn.setToolTip("Add this video to a playlist, or save its channel")
        self.lib_btn.clicked.connect(lambda: self.libClicked.emit(self.lib_btn.mapToGlobal(self.lib_btn.rect().bottomLeft())))
        row = QHBoxLayout()
        row.addWidget(self.prev_btn)
        row.addWidget(self.play, 1)
        row.addWidget(self.next_btn)
        row.addWidget(self.lib_btn)
        self.title = QLabel(wordWrap=True)
        f = self.title.font()
        f.setBold(True)
        f.setPointSize(f.pointSize() + 2)
        self.title.setFont(f)
        self.channel = MonoLabel()
        self.channel.linkActivated.connect(lambda _=None: self.channelClicked.emit(*self._chan))
        self._chan = ("", "")
        self.stats = QLabel(wordWrap=True)
        self.desc = QLabel(wordWrap=True)
        self.desc.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.comments = QLabel(wordWrap=True, textFormat=Qt.TextFormat.RichText)
        self.comments.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        v.addWidget(self.thumb)
        v.addLayout(row)
        for x in (self.title, self.channel, self.stats, self.desc, self.comments):
            v.addWidget(x)
        v.addStretch(1)
        self.setWidget(w)

    def show_item(self, it: yt.Item):
        self.title.setText(it.title)
        self._chan = (it.channel_id, it.channel)
        self.channel.setText(f'<a href="#">{html.escape(it.channel)}</a>' if it.channel_id else html.escape(it.channel))
        self.stats.setText(f"views {it.views_text or 'n/a'}  │  likes …  │  dislikes n/a  │  {it.date_text}")
        self.desc.setText("loading details…")
        self.comments.setText("")
        self.thumb.clear()
        self._pix = None
        self.play.setEnabled(True)

    def set_thumb(self, data: bytes):
        pm = QPixmap()
        if pm.loadFromData(data):
            self._pix = pm
            self._rescale()

    def _rescale(self):
        if self._pix:
            self.thumb.setPixmap(self._pix.scaledToWidth(max(80, self.width() - 40),
                                                         Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._rescale()

    def set_info(self, info: dict):
        d = info.get("upload_date") or ""
        date = f"{d[:4]}-{d[4:6]}-{d[6:]}" if len(d) == 8 else ""
        dur = info.get("duration")
        self.stats.setText("  │  ".join([
            f"views {_n(info.get('view_count'))}", f"likes {_n(info.get('like_count'))}",
            "dislikes n/a (hidden by YouTube)", f"comments {_n(info.get('comment_count'))}",
            date, f"length {_t(dur)}" if dur else ""]).strip(" │"))
        self.desc.setText((info.get("description") or "")[:1500])

    def set_comments(self, comments: list):
        if not comments:
            self.comments.setText("<i>no comments</i>")
            return
        out = ["<b>comments</b><br>"]
        for c in comments[:30]:
            out.append(f"<b>{html.escape(str(c.get('author', '')))}</b> "
                       f"(+{c.get('like_count') or 0})<br>{html.escape(str(c.get('text', ''))[:400])}<br><br>")
        self.comments.setText("".join(out))


class AspectBox(QWidget):
    """Sizes its video child to the native aspect ratio: full width when it fits,
    otherwise full height; never cropped, never overflowing."""

    def __init__(self, video):
        super().__init__()
        self.video, self.ratio = video, 16 / 9
        video.setParent(self)

    def set_aspect(self, r: float):
        if r > 0:
            self.ratio = r
            self._fit()

    def _fit(self):
        w, h = self.width(), self.height()
        vw, vh = w, int(w / self.ratio)
        if vh > h:
            vh, vw = h, int(h * self.ratio)
        self.video.setGeometry((w - vw) // 2, (h - vh) // 2, max(vw, 1), max(vh, 1))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit()


class FloatingPlayer(QWidget):
    closed = Signal()

    def __init__(self, parent, title: str):
        super().__init__(parent, Qt.WindowType.Dialog | Qt.WindowType.WindowCloseButtonHint
                         | Qt.WindowType.WindowMinMaxButtonsHint)
        self.setWindowTitle(f"ytblocks — {title}")
        self.setObjectName("ytblocks-floating")
        self.resize(640, 360)
        self.box = QVBoxLayout(self)
        self.box.setContentsMargins(0, 0, 0, 0)
        self.video = self.abox = None
        pal = self.palette()
        pal.setColor(QPalette.ColorRole.Window, QColor("black"))     # letterbox bars
        self.setPalette(pal)
        self.setAutoFillBackground(True)
        for key, fn in (("F", self.toggle_fullscreen), ("Esc", self._leave_fullscreen)):
            QShortcut(QKeySequence(key), self).activated.connect(fn)

    def toggle_fullscreen(self):
        self.showNormal() if self.isFullScreen() else self.showFullScreen()

    def _leave_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()

    def closeEvent(self, e):
        self.closed.emit()
        e.accept()


class PlayerBlock(Block):
    channelRequested = Signal(str, str)
    playbackStarted = Signal(str)
    navigate = Signal(int)
    libraryRequested = Signal(object, object)

    def __init__(self, playback: JsonStore):
        super().__init__("purple", "player")
        self.pb = playback
        self.item = self.info = self.streams = self.float = self.video = None
        self.info_ts = 0.0
        self.started = self.ended = self.popped = self._docking = self._dragging = False
        self._gen = 0
        self._info_pending = self._want_play = False
        self.vbox = None

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        self.pages = QStackedWidget()
        self.details = DetailsPage()
        self.details.playClicked.connect(self.start)
        self.details.channelClicked.connect(self.channelRequested)
        self.details.navClicked.connect(self.navigate)
        self.details.libClicked.connect(lambda pos: self.item and self.libraryRequested.emit(self.item, pos))
        self.video_page = QStackedWidget()
        self.placeholder = QLabel("playing in the floating window\nclose it to dock the video back",
                                  alignment=Qt.AlignmentFlag.AlignCenter)
        self.video_page.addWidget(self.placeholder)
        self.info_bar = QLabel(wordWrap=True, textFormat=Qt.TextFormat.RichText)    # title + info under the video
        self.video_pane = QWidget()
        vp = QVBoxLayout(self.video_pane)
        vp.setContentsMargins(0, 0, 0, 0)
        vp.addWidget(self.video_page, 1)
        vp.addWidget(self.info_bar)
        self.pages.addWidget(self.details)
        self.pages.addWidget(self.video_pane)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.controls = self._build_controls()
        self.controls.hide()
        v.addWidget(self.pages, 1)
        v.addWidget(self.status)
        v.addWidget(self.controls)

        self._save = QTimer(self)
        self._save.setSingleShot(True)
        self._save.setInterval(500)
        self._save.timeout.connect(self.pb.save)
        self._sc = self._install_keys(self)
        self._sc_vol = self._sc[2:]          # Up/Down only while a video is playing;
        for s in self._sc_vol:               # Left/Right always: seek when playing, else prev/next video
            s.setEnabled(False)

    # ------------------------------------------------------------ UI parts
    def _build_controls(self) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)

        def btn(text, tip, fn):
            b = QToolButton(text=text, toolTip=tip)
            b.setAutoRaise(True)
            b.clicked.connect(fn)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            h.addWidget(b)
            return b

        self.b_play = btn("⏸", "Play / pause (Space)", self.toggle_pause)
        btn("«", "Rewind (←, or double-click left side)", lambda: self._seek_dir(-1))
        btn("»", "Forward (→, or double-click right side)", lambda: self._seek_dir(+1))
        self.seek = QSlider(Qt.Orientation.Horizontal, maximum=1000)
        self.seek.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.seek.sliderPressed.connect(lambda: setattr(self, "_dragging", True))
        self.seek.sliderReleased.connect(self._seek_released)
        h.addWidget(self.seek, 1)
        self.time = QLabel("0:00 / 0:00")
        h.addWidget(self.time)
        self.b_mute = btn("🔊", "Mute", self._toggle_mute)
        self.vol = QSlider(Qt.Orientation.Horizontal, maximum=100)
        self.vol.setFixedWidth(80)
        self.vol.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.vol.setValue(self.pb.data["volume"])
        self.vol.valueChanged.connect(self._set_volume)
        h.addWidget(self.vol)
        self.quality = QComboBox(toolTip="Quality")
        self.quality.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.quality.activated.connect(self._quality_picked)
        h.addWidget(self.quality)
        self.speed = QComboBox(toolTip="Speed")
        self.speed.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        for s in SPEEDS:
            self.speed.addItem(f"{s:g}x", s)
        self.speed.setCurrentIndex(max(0, self.speed.findData(self.pb.data["speed"])))
        self.speed.activated.connect(self._speed_picked)
        h.addWidget(self.speed)
        btn("ⓘ", "Toggle details / video", self._toggle_page)
        btn("⛶", "Fullscreen (video only; F / Esc in the video window)", self._toggle_fullscreen)
        self.b_pop = btn("⇱", "Pop out / dock", self._toggle_popout)
        return w

    def _install_keys(self, widget) -> list:
        out = []
        for key, fn in (("Left", lambda: self._seek_dir(-1)), ("Right", lambda: self._seek_dir(+1)),
                        ("Up", lambda: self._bump_volume(+5)), ("Down", lambda: self._bump_volume(-5))):
            sc = QShortcut(QKeySequence(key), widget)
            sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc.activated.connect(fn)
            out.append(sc)
        return out

    def _make_video(self) -> MpvVideo:
        v = MpvVideo()
        v.tick.connect(self._on_tick)
        v.ended.connect(self._on_ended)
        v.seek_gesture.connect(self._seek_dir)
        v.toggle_request.connect(self.toggle_pause)
        v.wheel_volume.connect(self._bump_volume)
        return v

    def active_video(self):
        return self.float.video if self.popped and self.float else self.video

    # ------------------------------------------------------------ item / info
    def show_item(self, it: yt.Item):
        self.stop_playback()
        self._gen += 1
        gen = self._gen
        self.item, self.info, self.streams, self.info_ts = it, None, None, 0.0
        self.details.show_item(it)
        self.pages.setCurrentWidget(self.details)
        self._status("")
        self._info_pending, self._want_play = True, False
        self._update_info_bar()
        # metadata only - no media is requested until the user presses play
        submit(yt.fetch_info, it.url, done=lambda i: self._on_info(gen, i),
               fail=lambda m: self._on_info_fail(gen, m))
        submit(yt.http_get, it.thumb_url, None, None, 20, True,
               done=lambda b: gen == self._gen and self.details.set_thumb(b))
        submit(yt.fetch_comments, it.url,
               done=lambda c: gen == self._gen and self.details.set_comments(c),
               fail=lambda m: gen == self._gen and self.details.comments.setText(f"<i>comments unavailable</i>"))

    def _on_info(self, gen, info):
        if gen != self._gen:
            return
        self.info, self.info_ts = info, time.time()
        self._info_pending = False
        self.details.set_info(info)
        self._update_info_bar()
        if self._want_play:                 # Play was pressed while details were still loading
            self._want_play = False
            self._begin(0.0)

    def _on_info_fail(self, gen, msg):
        if gen == self._gen:
            self._info_pending = False
            self.details.desc.setText(f"could not load details: {msg}")
            if self._want_play:
                self._want_play = False
                self._fail(gen, msg)

    def _update_info_bar(self):
        d = self.details
        chan = html.escape(self.item.channel) if self.item else ""
        self.info_bar.setText(f"<b>{html.escape(d.title.text())}</b><br>{chan}  │  {html.escape(d.stats.text())}")

    def _status(self, t: str):
        self.status.setText(t)

    # ------------------------------------------------------------ playback
    def start(self):
        if not self.item:
            return
        if self.info and time.time() - self.info_ts < INFO_MAX_AGE:
            self._begin(0.0)
            return
        gen = self._gen
        self.details.play.setEnabled(False)
        self._status("starting…")
        if self._info_pending:              # reuse the metadata request already in flight
            self._want_play = True
            return
        submit(yt.fetch_info, self.item.url, done=lambda i: self._resolved(gen, i),
               fail=lambda m: self._fail(gen, m))

    def _resolved(self, gen, info):
        if gen != self._gen:
            return
        self.info, self.info_ts = info, time.time()
        self._begin(0.0)

    def _fail(self, gen, msg):
        if gen == self._gen:
            self.details.play.setEnabled(True)
            self._status(f"error: {msg}")

    def _begin(self, start_at: float):
        self.details.play.setEnabled(True)
        try:
            self.streams = yt.pick_streams(self.info, int(self.pb.data["quality"]))
        except AdBlocked as e:
            self._status(f"refused (ad policy): {e}")
            return
        except Exception as e:                      # noqa: BLE001
            self._status(f"error: {e}")
            return
        if self.video is None:
            self.video = self._make_video()
            self.vbox = AspectBox(self.video)
            self.video_page.addWidget(self.vbox)
        self._set_aspect()
        self._fill_quality()
        v = self.active_video()
        self._apply_prefs(v)
        v.load(self.streams, start_at, self.item.title)
        self.started, self.ended = True, False
        for s in self._sc_vol:
            s.setEnabled(True)
        self.controls.show()
        if not self.popped:
            self.video_page.setCurrentWidget(self.vbox)
            self.pages.setCurrentWidget(self.video_pane)
        self._status("")
        self.playbackStarted.emit(self.item.id)

    def _set_aspect(self):
        st = self.streams
        r = st.width / st.height if st and st.width and st.height else 16 / 9
        for box in (self.vbox, self.float.abox if self.float else None):
            if box:
                box.set_aspect(r)

    def _apply_prefs(self, v: MpvVideo):
        v.set_volume(self.pb.data["volume"])
        v.set_mute(self.pb.data["muted"])
        v.set_speed(self.pb.data["speed"])
        self.b_mute.setText("🔇" if self.pb.data["muted"] else "🔊")

    def _fill_quality(self):
        self.quality.blockSignals(True)
        self.quality.clear()
        self.quality.addItem("best", 0)
        for h in yt.heights(self.info):
            self.quality.addItem(f"{h}p", h)
        self.quality.setCurrentIndex(max(0, self.quality.findData(self.pb.data["quality"])))
        self.quality.blockSignals(False)

    def _quality_picked(self, _idx):
        self.pb.data["quality"] = int(self.quality.currentData())
        self._save.start()
        v = self.active_video()
        if self.started and v and self.info:
            pos, paused = v.position(), v.paused()
            try:
                self.streams = yt.pick_streams(self.info, self.pb.data["quality"])
            except Exception as e:                  # noqa: BLE001
                self._status(f"error: {e}")
                return
            self._set_aspect()
            v.load(self.streams, pos, self.item.title, paused)

    def _speed_picked(self, _idx):
        self.pb.data["speed"] = float(self.speed.currentData())
        self._save.start()
        v = self.active_video()
        if v:
            v.set_speed(self.pb.data["speed"])

    def toggle_pause(self):
        v = self.active_video()
        if not (self.started and v):
            return
        if self.ended:
            self._begin(0.0)
        else:
            v.toggle_pause()

    def _seek_dir(self, sign: int):
        v = self.active_video()
        if self.started and v:
            v.seek_rel(sign * int(self.pb.data["seek_step"]))
        elif not self.started:
            self.navigate.emit(sign)        # browsing: arrows move through the video list

    def _seek_released(self):
        self._dragging = False
        v = self.active_video()
        if v and v.duration():
            v.seek_abs(self.seek.value() / 1000 * v.duration())

    def _bump_volume(self, d: int):
        self._set_volume(self.pb.data["volume"] + d)

    def _set_volume(self, val: int):
        val = max(0, min(100, int(val)))
        self.pb.data["volume"] = val
        self.vol.blockSignals(True)
        self.vol.setValue(val)
        self.vol.blockSignals(False)
        v = self.active_video()
        if v:
            v.set_volume(val)
        self._save.start()

    def _toggle_mute(self):
        self.pb.data["muted"] = not self.pb.data["muted"]
        self.b_mute.setText("🔇" if self.pb.data["muted"] else "🔊")
        v = self.active_video()
        if v:
            v.set_mute(self.pb.data["muted"])
        self._save.start()

    def _toggle_page(self):
        cur = self.pages.currentWidget()
        self.pages.setCurrentWidget(self.details if cur is self.video_pane else self.video_pane)

    def _on_tick(self, pos: float, dur: float, paused: bool):
        self.b_play.setText("▶" if paused else "⏸")
        self.time.setText(f"{_t(pos)} / {_t(dur)}")
        if not self._dragging and dur > 0:
            self.seek.blockSignals(True)
            self.seek.setValue(int(pos / dur * 1000))
            self.seek.blockSignals(False)

    def _on_ended(self, reason: int, msg: str):
        if reason == 0:
            self.ended = True
            self.b_play.setText("▶")
            self._status("ended — press ▶ to replay")
        elif reason == 4:
            self._status(f"playback error: {msg}")

    # ------------------------------------------------------------ pop-out
    def _toggle_popout(self):
        self._dock() if self.popped else self._pop()

    def _pop(self):
        if not (self.started and self.streams and self.video):
            return
        pos, paused = self.video.position(), self.video.paused()
        self.video.stop()
        f = FloatingPlayer(self.window(), self.item.title)
        f.video = self._make_video()
        f.abox = AspectBox(f.video)
        f.box.addWidget(f.abox)
        self._install_keys(f)
        f.closed.connect(self._dock)
        self.float, self.popped = f, True
        self._set_aspect()
        self.video_page.setCurrentWidget(self.placeholder)
        f.show()
        self._apply_prefs(f.video)
        f.video.load(self.streams, pos, self.item.title, paused)

    def _dock(self):
        if not self.popped or self._docking:
            return
        self._docking = True
        f = self.float
        pos, paused = f.video.position(), f.video.paused()
        f.closed.disconnect(self._dock)
        f.video.shutdown()
        f.hide()
        f.deleteLater()
        self.float, self.popped = None, False
        self.video_page.setCurrentWidget(self.vbox)
        self._apply_prefs(self.video)
        self.video.load(self.streams, pos, self.item.title, paused)
        self._docking = False

    def _toggle_fullscreen(self):
        """Fullscreen = only the video: it is shown in its own fullscreen window."""
        if not self.started:
            return
        if not self.popped:
            self._pop()
        if self.float:
            self.float.toggle_fullscreen()

    # ------------------------------------------------------------ teardown
    def stop_playback(self):
        if self.popped and self.float:
            f = self.float
            f.closed.disconnect(self._dock)
            f.video.shutdown()
            f.hide()
            f.deleteLater()
            self.float, self.popped = None, False
        if self.video:
            self.video.stop()
        self.started = self.ended = False
        self._want_play = False
        for s in self._sc_vol:
            s.setEnabled(False)
        self.controls.hide()
        self.pages.setCurrentWidget(self.details)

    def shutdown(self):
        self.pb.save()
        if self.popped and self.float:
            self.float.video.shutdown()
        if self.video:
            self.video.shutdown()
