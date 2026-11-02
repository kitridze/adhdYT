"""YouTube access, modelled on ytfzf (Qt-free).

* Search = ytfzf's scraper: fetch ``results?search_query=..&sp=..``, pull
  ``ytInitialData`` out of the HTML, walk it for *Renderer objects (ytfzf does
  the same with jq ``..|.videoRenderer?``), page with innertube continuations.
* Channels / playlists / metadata / stream URLs = yt-dlp, the extractor ytfzf
  hands playback to.
Every payload goes through ``adguard.strip_ads`` before parsing.
"""
from __future__ import annotations

import base64
import json
import re
import shutil
import subprocess
import time
import urllib.request
from dataclasses import asdict, dataclass, fields
from urllib.parse import quote, urlencode

from . import adguard

UA = "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"
COOKIE = "SOCS=CAI"   # skips the EU consent interstitial (same trick yt-dlp uses)


# ----------------------------------------------------------------- model
@dataclass
class Item:
    kind: str                 # video | short | channel | playlist
    id: str
    title: str
    channel: str = ""
    channel_id: str = ""
    views: int | None = None
    views_text: str = ""
    date_text: str = ""
    duration: int | None = None
    thumb: str = ""
    live: bool = False
    count_text: str = ""
    seed: str = ""          # a video inside a Mix (RD*) playlist

    @property
    def url(self) -> str:
        return {
            "video": f"https://www.youtube.com/watch?v={self.id}",
            "short": f"https://www.youtube.com/shorts/{self.id}",
            "playlist": f"https://www.youtube.com/playlist?list={self.id}",
            "channel": f"https://www.youtube.com/channel/{self.id}",
        }[self.kind]

    @property
    def thumb_url(self) -> str:
        if self.kind in ("video", "short"):
            return f"https://i.ytimg.com/vi/{self.id}/hqdefault.jpg"
        return self.thumb

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Item":
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in names})


# --------------------------------------------------------------- helpers
def http_get(url: str, data: bytes | None = None, headers: dict | None = None,
             timeout: int = 20, raw: bool = False):
    h = {"User-Agent": UA, "Cookie": COOKIE, "Accept-Language": "en-US,en;q=0.9"}
    h.update(headers or {})
    with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=h), timeout=timeout) as r:
        body = r.read()
    return body if raw else body.decode("utf-8", "replace")


def _txt(o) -> str:
    if not isinstance(o, dict):
        return ""
    return o.get("simpleText") or "".join(r.get("text", "") for r in o.get("runs", []))


def parse_count(s: str):
    if not s:
        return None
    m = re.search(r"([\d][\d,]*\.?\d*)\s*([KMB])?", s, re.I)
    if not m:
        return 0 if re.search(r"\bno\b", s, re.I) else None
    n = float(m.group(1).replace(",", ""))
    n *= {"K": 1e3, "M": 1e6, "B": 1e9}.get((m.group(2) or "").upper(), 1)
    return int(n)


def parse_duration(s: str):
    if not s or not re.fullmatch(r"\d+(:\d\d)+", s.strip()):
        return None
    secs = 0
    for part in s.strip().split(":"):
        secs = secs * 60 + int(part)
    return secs


def parse_rel_date(s: str):
    """'3 years ago' -> approximate seconds ago (for ordering only)."""
    m = re.search(r"(\d+)\s+(second|minute|hour|day|week|month|year)", s or "")
    if not m:
        return None
    mult = dict(second=1, minute=60, hour=3600, day=86400, week=604800, month=2592000, year=31536000)
    return int(m.group(1)) * mult[m.group(2)]


def _thumb(r: dict, last=True) -> str:
    ts = (r.get("thumbnail") or {}).get("thumbnails") or [{}]
    u = (ts[-1] if last else ts[0]).get("url", "")
    return "https:" + u if u.startswith("//") else u


# ---------------------------------------------------------------- parsers
def _video(r: dict):
    vid = r.get("videoId")
    if not vid:
        return None
    byl = r.get("longBylineText") or r.get("ownerText") or r.get("shortBylineText") or {}
    run = (byl.get("runs") or [{}])[0]
    cid = ((run.get("navigationEndpoint") or {}).get("browseEndpoint") or {}).get("browseId", "")
    path = (((r.get("navigationEndpoint") or {}).get("commandMetadata") or {})
            .get("webCommandMetadata") or {}).get("url", "")
    vt = _txt(r.get("viewCountText"))
    live = "watching" in vt.lower() or any(
        (o.get("thumbnailOverlayTimeStatusRenderer") or {}).get("style") == "LIVE"
        for o in r.get("thumbnailOverlays") or [])
    return Item("short" if path.startswith("/shorts/") else "video", vid, _txt(r.get("title")),
                run.get("text", ""), cid, parse_count(vt), vt, _txt(r.get("publishedTimeText")),
                parse_duration(_txt(r.get("lengthText"))), _thumb(r), live)


def _channel(r: dict):
    cid = r.get("channelId")
    if not cid:
        return None
    a, b = _txt(r.get("subscriberCountText")), _txt(r.get("videoCountText"))
    subs, handle = (a, b) if "subscriber" in a.lower() else (b, a)
    title = _txt(r.get("title"))
    return Item("channel", cid, title, title, cid, None, subs, handle,
                None, _thumb(r, last=False))


def _playlist(r: dict):
    pid = r.get("playlistId")
    if not pid:
        return None
    run = (_txt(r.get("shortBylineText")) or "", )
    byl = (r.get("shortBylineText") or {}).get("runs") or [{}]
    cid = ((byl[0].get("navigationEndpoint") or {}).get("browseEndpoint") or {}).get("browseId", "")
    n = r.get("videoCount", "")
    seed = ((r.get("navigationEndpoint") or {}).get("watchEndpoint") or {}).get("videoId", "")
    return Item("playlist", pid, _txt(r.get("title")), run[0], cid,
                count_text=f"{n} videos" if n else "", thumb=_thumb(r, last=False), seed=seed)


def _reel(r: dict):
    vid = r.get("videoId")
    if not vid:
        return None
    vt = _txt(r.get("viewCountText"))
    return Item("short", vid, _txt(r.get("headline")), views=parse_count(vt), views_text=vt)


def _shorts_lockup(r: dict):
    vid = (((r.get("onTap") or {}).get("innertubeCommand") or {}).get("reelWatchEndpoint") or {}).get("videoId")
    if not vid:
        return None
    om = r.get("overlayMetadata") or {}
    vt = (om.get("secondaryText") or {}).get("content", "")
    return Item("short", vid, (om.get("primaryText") or {}).get("content", ""),
                views=parse_count(vt), views_text=vt)


def _find_duration(o):
    if isinstance(o, dict):
        for v in o.values():
            d = _find_duration(v)
            if d is not None:
                return d
    elif isinstance(o, list):
        for v in o:
            d = _find_duration(v)
            if d is not None:
                return d
    elif isinstance(o, str):
        return parse_duration(o)
    return None


def _lockup(r: dict):
    """Newer YouTube layout; best effort (videos and playlists only)."""
    ctype, cid = r.get("contentType", ""), r.get("contentId")
    if not cid or not ("VIDEO" in ctype or "PLAYLIST" in ctype):
        return None
    meta = (r.get("metadata") or {}).get("lockupMetadataViewModel") or {}
    title = (meta.get("title") or {}).get("content", "")
    rows = ((meta.get("metadata") or {}).get("contentMetadataViewModel") or {}).get("metadataRows") or []
    parts = [p.get("text", {}).get("content", "") for row in rows for p in row.get("metadataParts", [])]
    views = next((p for p in parts if "view" in p.lower()), "")
    date = next((p for p in parts if "ago" in p.lower()), "")
    chan = next((p for p in parts if p and p not in (views, date)), "")
    if "PLAYLIST" in ctype:
        return Item("playlist", cid, title, chan, count_text=views)
    dur = _find_duration((r.get("contentImage") or {}).get("thumbnailViewModel") or {})
    return Item("video", cid, title, chan, "", parse_count(views), views, date, dur)


PARSERS = {"videoRenderer": _video, "channelRenderer": _channel, "playlistRenderer": _playlist,
           "reelItemRenderer": _reel, "shortsLockupViewModel": _shorts_lockup, "lockupViewModel": _lockup}


def parse_items(data) -> list[Item]:
    out: list[Item] = []

    def walk(n):
        if isinstance(n, dict):
            for k, v in n.items():
                p = PARSERS.get(k)
                if p and isinstance(v, dict):
                    it = p(v)
                    if it and it.title:
                        out.append(it)
                else:
                    walk(v)
        elif isinstance(n, list):
            for x in n:
                walk(x)
    walk(data)
    return out


def find_continuation(data):
    tokens: list[str] = []

    def walk(n):
        if isinstance(n, dict):
            c = n.get("continuationCommand")
            if isinstance(c, dict) and c.get("token"):
                tokens.append(c["token"])
            for v in n.values():
                walk(v)
        elif isinstance(n, list):
            for x in n:
                walk(x)
    walk(data)
    return tokens[-1] if tokens else None


def parse_payload(data):
    """strip ads -> parse.  Returns (items, continuation_token)."""
    data = adguard.strip_ads(data)
    return parse_items(data), find_continuation(data)


def extract_initial_data(html: str) -> dict:
    m = re.search(r"ytInitialData\s*=\s*", html)
    if not m:
        raise RuntimeError("ytInitialData not found (YouTube layout changed or consent page)")
    obj, _ = json.JSONDecoder().raw_decode(html[m.end():])
    return obj


# ----------------------------------------------------------------- search
SORT_SP = {"rating": 1, "date": 2, "popularity": 3}
TYPE_SP = {"video": 1, "channel": 2, "playlist": 3}


def build_sp(sort: str = "relevance", type_: str | None = None) -> str:
    """ytfzf's `sp=` filter parameter (a tiny protobuf, base64)."""
    b = bytearray()
    if sort in SORT_SP:
        b += bytes([0x08, SORT_SP[sort]])
    if type_ in TYPE_SP:
        b += bytes([0x12, 0x02, 0x10, TYPE_SP[type_]])
    return base64.b64encode(bytes(b)).decode() if b else ""


class SearchFeed:
    mode = "search"

    def __init__(self, query: str, sort: str = "relevance", type_: str | None = None):
        self.query, self.sp = query, build_sp(sort, type_)
        self.token = None
        self.started = False
        self.exhausted = False
        self.key = None
        self.version = "2.20240101.00.00"
        self._seen: set = set()

    def fetch_more(self) -> list[Item]:
        if not self.started:
            q = {"search_query": self.query, "hl": "en", "gl": "US"}
            if self.sp:
                q["sp"] = quote(self.sp, safe="")     # double-encoded, exactly as ytfzf sends it
            html = http_get("https://www.youtube.com/results?" + urlencode(q))
            data = extract_initial_data(html)
            if m := re.search(r'"INNERTUBE_API_KEY":"([^"]+)"', html):
                self.key = m.group(1)
            if m := re.search(r'"INNERTUBE_CONTEXT_CLIENT_VERSION":"([^"]+)"', html):
                self.version = m.group(1)
            self.started = True
        else:
            if not self.token or not self.key:
                self.exhausted = True
                return []
            body = json.dumps({"context": {"client": {"clientName": "WEB", "clientVersion": self.version,
                                                      "hl": "en", "gl": "US"}},
                               "continuation": self.token}).encode()
            data = json.loads(http_get(
                f"https://www.youtube.com/youtubei/v1/search?key={self.key}&prettyPrint=false",
                data=body, headers={"Content-Type": "application/json"}))
        items, self.token = parse_payload(data)
        self.exhausted = self.token is None
        fresh = [i for i in items if (i.kind, i.id) not in self._seen]
        self._seen.update((i.kind, i.id) for i in fresh)
        return fresh


# --------------------------------------------------------------- yt-dlp
def _ytdlp(args: list[str], timeout: int = 90) -> dict:
    exe = shutil.which("yt-dlp")
    if not exe:
        raise RuntimeError("yt-dlp not found in PATH")
    p = subprocess.run([exe, "--ignore-config", "--no-warnings", *args],
                       capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0 or not p.stdout.strip():
        raise RuntimeError((p.stderr.strip().splitlines() or ["yt-dlp failed"])[-1])
    return json.loads(p.stdout)


def _date(e: dict) -> str:
    d = e.get("upload_date") or ""
    if len(d) == 8:
        return f"{d[:4]}-{d[4:6]}-{d[6:]}"
    ts = e.get("timestamp") or e.get("release_timestamp")
    return time.strftime("%Y-%m-%d", time.gmtime(ts)) if ts else ""


def item_from_entry(e: dict):
    vid = e.get("id") or ""
    if not vid:
        return None
    url = e.get("url") or e.get("webpage_url") or ""
    if "/shorts/" in url:
        kind = "short"
    elif e.get("ie_key") == "YoutubeTab" or e.get("_type") == "playlist" or \
            ("list=" in url and "watch?v=" not in url):
        kind = "playlist"
    else:
        kind = "video"
    views = e.get("view_count")
    ths = e.get("thumbnails") or [{}]
    dur = e.get("duration")
    return Item(kind, vid, e.get("title") or "", e.get("channel") or e.get("uploader") or "",
                e.get("channel_id") or "", views, f"{views:,} views" if views is not None else "",
                _date(e), int(dur) if dur else None, ths[-1].get("url", ""),
                e.get("live_status") == "is_live")


class YtdlpFeed:
    """Infinite-scroll paging of channel/playlist pages via yt-dlp --flat-playlist."""
    PAGE = 30

    def __init__(self, url: str, mode: str = "channel"):
        self.url, self.mode = url, mode
        self.start, self.exhausted = 1, False
        self._seen: set = set()

    def fetch_more(self) -> list[Item]:
        a, b = self.start, self.start + self.PAGE - 1
        try:
            data = _ytdlp(["-J", "--flat-playlist", "--playlist-items", f"{a}:{b}", self.url], timeout=120)
        except RuntimeError as e:
            if "unviewable" in str(e).lower():
                raise RuntimeError("YouTube cannot list this playlist type directly (auto-generated Mix)") from None
            raise
        entries = data.get("entries") or []
        self.start = b + 1
        if len(entries) < self.PAGE:
            self.exhausted = True
        out = []
        for e in entries:
            it = item_from_entry(e or {})
            if it and (it.kind, it.id) not in self._seen:
                self._seen.add((it.kind, it.id))
                out.append(it)
        return out


class LocalFeed:
    mode = "local"

    def __init__(self, items: list[Item]):
        self.items, self.exhausted = items, False

    def fetch_more(self) -> list[Item]:
        self.exhausted = True
        return self.items


def playlist_url(it: Item) -> str:
    """Mixes (list=RD*) are generated per seed video: yt-dlp's tab extractor reports
    them 'unviewable' via /playlist?list=..., but opens them through a watch URL."""
    if it.id.startswith("RD"):
        if not it.seed:
            raise RuntimeError("this Mix needs a seed video; open it from search results again")
        return f"https://www.youtube.com/watch?v={it.seed}&list={it.id}"
    return it.url


def fetch_info(url: str) -> dict:
    return _ytdlp(["-J", "--no-playlist", url])


def fetch_comments(url: str, n: int = 30) -> list[dict]:
    data = _ytdlp(["-J", "--no-playlist", "--skip-download", "--write-comments", "--extractor-args",
                   f"youtube:max_comments={n},{n},0,0,0;comment_sort=top", url], timeout=180)
    return data.get("comments") or []


# --------------------------------------------------------- stream picking
@dataclass
class Streams:
    video_url: str
    audio_url: str | None
    height: int
    user_agent: str
    width: int = 0


def _is_v(f):
    return f.get("vcodec") not in (None, "none")


def _is_a(f):
    return f.get("acodec") not in (None, "none")


def heights(info: dict) -> list[int]:
    fm = adguard.clean_formats(info.get("formats") or [])
    return sorted({f["height"] for f in fm if _is_v(f) and f.get("height")}, reverse=True)


def pick_streams(info: dict, max_height: int = 0) -> Streams:
    adguard.assert_info_ok(info)
    fm = adguard.clean_formats(info.get("formats") or [])
    vids = [f for f in fm if _is_v(f) and not _is_a(f)]
    auds = [f for f in fm if _is_a(f) and not _is_v(f)]
    muxed = [f for f in fm if _is_v(f) and _is_a(f)]

    def h(f):
        return f.get("height") or 0

    def vkey(f):   # prefer height, then non-AV1 (cheap to decode), then bitrate
        return (h(f), 0 if str(f.get("vcodec", "")).startswith("av01") else 1, f.get("tbr") or 0)

    def choose(pool):
        cands = [f for f in pool if not max_height or h(f) <= max_height]
        return max(cands, key=vkey) if cands else min(pool, key=h)

    def ua(f):
        return (f.get("http_headers") or {}).get("User-Agent") or UA

    if vids and auds:
        v = choose(vids)
        a = max(auds, key=lambda f: ("original" in str(f.get("format_note", "")).lower(),
                                     f.get("abr") or f.get("tbr") or 0))
        return Streams(v["url"], a["url"], h(v), ua(v), v.get("width") or 0)
    if muxed:
        m = choose(muxed)
        return Streams(m["url"], None, h(m), ua(m), m.get("width") or 0)
    raise adguard.AdBlocked("no clean progressive formats available for this video")
