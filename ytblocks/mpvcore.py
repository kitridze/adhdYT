"""libmpv embedded through its OpenGL *render API* (works on X11 and native
Wayland/Hyprland alike; Qt keeps all mouse/keyboard input).  Thin ctypes
binding, so no python-mpv dependency.

Ad policy: mpv runs with ytdl=no (it never re-resolves anything itself),
load-scripts=no, and every URL is re-validated by adguard before loadfile."""
from __future__ import annotations

import ctypes
import ctypes.util
import locale
from ctypes import (CFUNCTYPE, POINTER, Structure, byref, c_char_p, c_double, c_int,
                    c_uint64, c_void_p, cast, pointer)

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QOpenGLContext
from PySide6.QtOpenGLWidgets import QOpenGLWidget

from .adguard import assert_clean

_GETPROC = CFUNCTYPE(c_void_p, c_void_p, c_char_p)
_UPDATE = CFUNCTYPE(None, c_void_p)

MPV_EVENT_END_FILE, MPV_EVENT_FILE_LOADED = 7, 8
RENDER_API_TYPE, RENDER_GL_INIT, RENDER_FBO, RENDER_FLIP_Y = 1, 2, 3, 4


class _Event(Structure):
    _fields_ = [("event_id", c_int), ("error", c_int), ("reply_userdata", c_uint64), ("data", c_void_p)]


class _Param(Structure):
    _fields_ = [("type", c_int), ("data", c_void_p)]


class _GLInit(Structure):
    _fields_ = [("get_proc_address", _GETPROC), ("ctx", c_void_p)]


class _FBO(Structure):
    _fields_ = [("fbo", c_int), ("w", c_int), ("h", c_int), ("internal_format", c_int)]


def _get_proc(_ctx, name):
    gl = QOpenGLContext.currentContext()
    if gl is None:
        return None
    addr = gl.getProcAddress(name)
    return int(addr) or None if addr is not None else None


_GETPROC_CB = _GETPROC(_get_proc)      # module-level: must outlive every render context
_lib = None


def _mpv():
    global _lib
    if _lib:
        return _lib
    locale.setlocale(locale.LC_NUMERIC, "C")           # libmpv refuses to run otherwise
    L = ctypes.CDLL(ctypes.util.find_library("mpv") or "libmpv.so.2")
    L.mpv_create.restype = c_void_p
    L.mpv_initialize.argtypes = [c_void_p]
    L.mpv_set_option_string.argtypes = [c_void_p, c_char_p, c_char_p]
    L.mpv_set_property_string.argtypes = [c_void_p, c_char_p, c_char_p]
    L.mpv_get_property_string.argtypes = [c_void_p, c_char_p]
    L.mpv_get_property_string.restype = c_void_p
    L.mpv_free.argtypes = [c_void_p]
    L.mpv_command.argtypes = [c_void_p, POINTER(c_char_p)]
    L.mpv_terminate_destroy.argtypes = [c_void_p]
    L.mpv_wait_event.argtypes = [c_void_p, c_double]
    L.mpv_wait_event.restype = POINTER(_Event)
    L.mpv_error_string.argtypes = [c_int]
    L.mpv_error_string.restype = c_char_p
    L.mpv_render_context_create.argtypes = [POINTER(c_void_p), c_void_p, POINTER(_Param)]
    L.mpv_render_context_set_update_callback.argtypes = [c_void_p, _UPDATE, c_void_p]
    L.mpv_render_context_render.argtypes = [c_void_p, POINTER(_Param)]
    L.mpv_render_context_free.argtypes = [c_void_p]
    _lib = L
    return L


OPTIONS = {
    "vo": "libmpv", "config": "no", "ytdl": "no", "load-scripts": "no", "osc": "no",
    "input-default-bindings": "no", "input-vo-keyboard": "no", "input-cursor": "no",
    "cursor-autohide": "no", "terminal": "no", "hwdec": "auto-safe",
    "audio-client-name": "ytblocks", "sub-auto": "no", "load-unsafe-playlists": "no",
}


def _lenval(s: str) -> str:
    return f"%{len(s.encode())}%{s}"        # mpv option-list length-escape syntax


class MpvVideo(QOpenGLWidget):
    _frame = Signal()
    tick = Signal(float, float, bool)       # position, duration, paused
    ended = Signal(int, str)                # reason (0=eof, 4=error), message
    seek_gesture = Signal(int)              # -1 / +1 from double-click
    toggle_request = Signal()
    wheel_volume = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._L = L = _mpv()
        self._h = L.mpv_create()
        if not self._h:
            raise RuntimeError("mpv_create failed")
        for k, v in OPTIONS.items():
            L.mpv_set_option_string(self._h, k.encode(), v.encode())
        if L.mpv_initialize(self._h) < 0:
            raise RuntimeError("mpv_initialize failed")
        self._rctx = None
        self._loaded = False
        self._alive = True
        self._swallow_release = False
        self._upd = _UPDATE(lambda _d: self._frame.emit())
        self._frame.connect(self.update)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.setMinimumSize(160, 90)
        self._timer = QTimer(self)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._poll)
        self._timer.start()
        self._click = QTimer(self)
        self._click.setSingleShot(True)
        self._click.timeout.connect(self.toggle_request)

    # ---- GL / render
    def initializeGL(self):
        api = c_char_p(b"opengl")
        init = _GLInit(_GETPROC_CB, None)
        params = (_Param * 3)(_Param(RENDER_API_TYPE, cast(api, c_void_p)),
                              _Param(RENDER_GL_INIT, cast(pointer(init), c_void_p)),
                              _Param(0, None))
        ctx = c_void_p()
        if self._L.mpv_render_context_create(byref(ctx), self._h, params) < 0:
            raise RuntimeError("mpv_render_context_create failed")
        self._rctx, self._keep = ctx, (api, init, params)
        self._L.mpv_render_context_set_update_callback(ctx, self._upd, None)

    def paintGL(self):
        if not self._rctx:
            f = self.context().functions()
            f.glClearColor(0, 0, 0, 1)
            f.glClear(0x4000)
            return
        dpr = self.devicePixelRatioF()
        fbo = _FBO(self.defaultFramebufferObject(), int(self.width() * dpr), int(self.height() * dpr), 0)
        flip = c_int(1)
        params = (_Param * 3)(_Param(RENDER_FBO, cast(pointer(fbo), c_void_p)),
                              _Param(RENDER_FLIP_Y, cast(pointer(flip), c_void_p)),
                              _Param(0, None))
        self._L.mpv_render_context_render(self._rctx, params)

    # ---- low level
    def _cmd(self, *args):
        arr = (c_char_p * (len(args) + 1))(*[str(a).encode() for a in args], None)
        return self._L.mpv_command(self._h, arr)

    def _set(self, name, val):
        self._L.mpv_set_property_string(self._h, name.encode(), str(val).encode())

    def _get(self, name):
        p = self._L.mpv_get_property_string(self._h, name.encode())
        if not p:
            return None
        s = ctypes.string_at(p).decode(errors="replace")
        self._L.mpv_free(p)
        return s

    def _poll(self):
        if not self._alive:
            return
        L = self._L
        while True:
            ev = L.mpv_wait_event(self._h, 0).contents
            eid = ev.event_id
            if eid == 0:
                break
            if eid == MPV_EVENT_FILE_LOADED:
                self._loaded = True
            elif eid == MPV_EVENT_END_FILE and ev.data:
                self._loaded = False
                d = cast(ev.data, POINTER(c_int))
                reason, err = d[0], d[1]
                msg = L.mpv_error_string(err).decode() if reason == 4 else ""
                self.ended.emit(reason, msg)
        if self._loaded:
            self.tick.emit(self.position(), self.duration(), self.paused())

    # ---- public API
    def load(self, streams, start: float = 0.0, title: str = "", paused: bool = False):
        assert_clean(streams.video_url)
        if streams.audio_url:
            assert_clean(streams.audio_url)
        opts = [f"start={max(0.0, start):.2f}", f"pause={'yes' if paused else 'no'}",
                f"force-media-title={_lenval(title or 'ytblocks')}",
                f"user-agent={_lenval(streams.user_agent)}"]
        if streams.audio_url:
            opts.append(f"audio-file={_lenval(streams.audio_url)}")
        self._loaded = False
        self._cmd("loadfile", streams.video_url, "replace", "-1", ",".join(opts))

    def stop(self):
        self._loaded = False
        self._cmd("stop")

    def position(self) -> float:
        return float(self._get("time-pos") or 0)

    def duration(self) -> float:
        return float(self._get("duration") or 0)

    def paused(self) -> bool:
        return self._get("pause") == "yes"

    def set_volume(self, v: int):
        self._set("volume", v)

    def set_mute(self, m: bool):
        self._set("mute", "yes" if m else "no")

    def set_speed(self, s: float):
        self._set("speed", s)

    def toggle_pause(self):
        self._set("pause", "no" if self.paused() else "yes")

    def seek_rel(self, secs: float):
        self._cmd("seek", secs, "relative")

    def seek_abs(self, secs: float):
        self._cmd("seek", secs, "absolute")

    def shutdown(self):
        if not self._alive:
            return
        self._alive = False
        self._timer.stop()
        if self._rctx:
            self.makeCurrent()
            self._L.mpv_render_context_free(self._rctx)
            self._rctx = None
            self.doneCurrent()
        self._L.mpv_terminate_destroy(self._h)

    # ---- input (Qt owns all of it)
    def mousePressEvent(self, e):
        self.setFocus()

    def mouseReleaseEvent(self, e):
        if self._swallow_release:
            self._swallow_release = False
            return
        self._click.start(260)      # delayed so a double-click can cancel the pause toggle

    def mouseDoubleClickEvent(self, e):
        self._click.stop()
        self._swallow_release = True
        x, w = e.position().x(), max(1, self.width())
        if x < w / 3:
            self.seek_gesture.emit(-1)
        elif x > 2 * w / 3:
            self.seek_gesture.emit(+1)

    def wheelEvent(self, e):
        d = e.angleDelta().y()
        if d:
            self.wheel_volume.emit(5 if d > 0 else -5)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Space:
            self.toggle_request.emit()
        else:
            super().keyPressEvent(e)
