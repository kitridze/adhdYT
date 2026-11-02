"""Run blocking work (yt-dlp, HTTP) off the GUI thread; callbacks run on it."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QObject, Signal, Slot

_ex = ThreadPoolExecutor(max_workers=8, thread_name_prefix="ytblocks")
_bus = None


class _Bus(QObject):
    dispatch = Signal(object)

    def __init__(self):
        super().__init__()
        self.dispatch.connect(self._run)

    @Slot(object)
    def _run(self, thunk):
        thunk()


def submit(fn, *args, done=None, fail=None) -> None:
    """Call from the GUI thread.  done(result) / fail(message) run on the GUI thread."""
    global _bus
    if _bus is None:
        _bus = _Bus()          # created on the GUI thread -> slot runs there
    bus = _bus

    def job():
        try:
            r = fn(*args)
        except Exception as e:                      # noqa: BLE001 - surfaced to the UI
            msg = f"{type(e).__name__}: {e}"
            if fail:
                bus.dispatch.emit(lambda: fail(msg))
            return
        if done:
            bus.dispatch.emit(lambda: done(r))

    _ex.submit(job)
