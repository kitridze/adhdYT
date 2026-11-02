"""XDG-compliant persistence: $XDG_CONFIG_HOME/ytblocks/*.json (Qt-free)."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path

APP_ID = "ytblocks"
ROLES = ("red", "yellow", "green", "blue", "lightblue", "purple")

SETTINGS_DEFAULT = {
    "window": {"w": 1280, "h": 720},
    "sidebar_collapsed": False,
    "sidebar_width": 200,
    "topbar_height": 30,
    "filter_btn_width": 40,
    "settings_btn_size": 24,
    "player_pct": 40,
    "ui_font": "",            # "" = system monospace (fixed) font
    "ui_font_size": 10,
    "results_font_size": 11,
    "theme_mode": "system",   # system | custom
    "outline_strength": 45,   # % blend of text colour over background (lower = softer)
    "colors": {r: "" for r in (*ROLES, "text", "background", "controls")},   # "" = auto
    "filters_visible": False,
    "filters": {
        "sort": "relevance", "min_len": 0, "max_len": 0, "min_views": 0,
        "types": {"video": True, "channel": True, "playlist": True, "short": False},
        "seen": "both",
    },
}
PLAYBACK_DEFAULT = {"volume": 80, "muted": False, "quality": 0, "speed": 1.0, "seek_step": 10}
LIBRARY_DEFAULT = {"playlists": [], "channels": []}


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    p = Path(base) / APP_ID
    p.mkdir(parents=True, exist_ok=True)
    return p


def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _merge(default, loaded):
    """Overlay a loaded file on the defaults; values of the wrong type are ignored
    so a corrupt or hand-edited file can never crash the app."""
    out = copy.deepcopy(default)
    if not isinstance(loaded, dict):
        return out
    for k, v in loaded.items():
        d = out.get(k)
        if isinstance(d, dict):
            if isinstance(v, dict):
                out[k] = _merge(d, v)
        elif k in out and type(d) is not type(v) and not (_num(d) and _num(v)):
            continue
        else:
            out[k] = v
    return out


class JsonStore:
    def __init__(self, name: str, default: dict):
        self.path = config_dir() / name
        self.default = default
        try:
            self.data = _merge(default, json.loads(self.path.read_text("utf-8")))
        except (OSError, ValueError):
            self.data = copy.deepcopy(default)

    def save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=2, ensure_ascii=False), "utf-8")
        os.replace(tmp, self.path)


class Library(JsonStore):
    def __init__(self):
        super().__init__("library.json", LIBRARY_DEFAULT)

    def playlist(self, name: str):
        return next((p for p in self.data["playlists"] if p["name"] == name), None)

    def add_playlist(self, name: str) -> None:
        if name and not self.playlist(name):
            self.data["playlists"].append({"name": name, "items": []})
            self.save()

    def remove_playlist(self, name: str) -> None:
        self.data["playlists"] = [p for p in self.data["playlists"] if p["name"] != name]
        self.save()

    def save_yt_playlist(self, name: str, yt_id: str, seed: str = "") -> None:
        if yt_id and not any(p.get("yt_id") == yt_id for p in self.data["playlists"]):
            self.data["playlists"].append({"name": name, "items": [], "yt_id": yt_id, "seed": seed})
            self.save()

    def add_to_playlist(self, name: str, item: dict) -> None:
        p = self.playlist(name)
        if p is not None and not p.get("yt_id") and not any(i.get("id") == item.get("id") for i in p["items"]):
            p["items"].append(item)
            self.save()

    def remove_from_playlist(self, name: str, item_id: str) -> None:
        p = self.playlist(name)
        if p is not None:
            p["items"] = [i for i in p["items"] if i.get("id") != item_id]
            self.save()

    def save_channel(self, cid: str, name: str) -> None:
        if cid and not any(c["id"] == cid for c in self.data["channels"]):
            self.data["channels"].append({"id": cid, "name": name})
            self.save()

    def remove_channel(self, cid: str) -> None:
        self.data["channels"] = [c for c in self.data["channels"] if c["id"] != cid]
        self.save()


class SeenStore:
    CAP = 20000

    def __init__(self):
        self.store = JsonStore("seen.json", {"ids": []})
        self.ids: set[str] = set(self.store.data["ids"])

    def add(self, vid: str) -> None:
        if vid and vid not in self.ids:
            self.ids.add(vid)
            self.store.data["ids"].append(vid)
            del self.store.data["ids"][:-self.CAP]
            self.store.save()
