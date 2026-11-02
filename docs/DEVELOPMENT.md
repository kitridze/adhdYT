# Development notes

Project: **ytblocks** — terminal-styled PySide6 YouTube browser, libmpv playback,
ads omitted by construction. Target: Arch Linux package.

## Status
| Area | State |
|---|---|
| `ytblocks/adguard.py` (ad policy) | written, unit-tested |
| `ytblocks/yt.py` (ytfzf-style scrape + yt-dlp) | written, parsers unit-tested with fabricated JSON |
| `ytblocks/config.py`, `filters.py` | written, unit-tested |
| `ytblocks/mpvcore.py` (ctypes libmpv render API in QOpenGLWidget) | written, **untested** (no Qt/mpv in authoring sandbox) |
| `ytblocks/ui_*.py`, `app.py` | written, **untested at runtime** (byte-compiled only) |
| `PKGBUILD`, `mkdist.sh`, `pyproject.toml`, desktop entry, icon, LICENSE | written, **makepkg not run** |

## First things to do on a real Arch box
1. `./mkdist.sh && makepkg -si` (or `python -m ytblocks` from the repo root for a dev run).
2. Smoke test order: launch -> search -> select result (details page, nothing plays)
   -> Play -> pop-out -> dock -> quality change -> arrows/double-click -> restart (prefs reapplied).
3. Likely fix-ups: YouTube JSON drift in `yt.py` parsers (`_video`, `_lockup`),
   `mpv_render_context` param structs in `mpvcore.py`, PySide6 enum spellings.

## Architecture in one paragraph
`yt.SearchFeed` scrapes `ytInitialData` (as ytfzf does) and pages via innertube
continuation; `yt.YtdlpFeed` pages channels/playlists via `yt-dlp --flat-playlist`.
Every payload passes `adguard.strip_ads` before parsing. Playback: `yt.fetch_info`
(yt-dlp -J) -> `yt.pick_streams` (only progressive https googlevideo formats,
live refused) -> `MpvVideo.load` (re-asserts `adguard.assert_clean`; mpv runs with
`ytdl=no`, `load-scripts=no`). Pop-out = second mpv instance resumed at same position.

## Conventions
- Qt-free modules (`adguard`, `yt`, `config`, `filters`) must stay importable without PySide6 (tests + `check()` rely on it).
- Version lives in `PKGBUILD` (`pkgver`), `pyproject.toml`, `ytblocks/__init__.py` — keep in sync.
- Config: `$XDG_CONFIG_HOME/ytblocks/{settings,playback,library,seen}.json`.

## Round 2 (follow-up fixes) — all untested at runtime
Mix playlists (`RD*`) open via watch URL + seed (`yt.playlist_url`); monochrome UI (`theme.MONO_QSS`,
palette text colour only, colour settings removed); prev/next (results header, details page, Left/Right
when not playing, Ctrl+Left/Right always); info bar under video; `AspectBox` fits video to native
ratio; fullscreen = video-only fullscreen window (second mpv instance, F/Esc); Play reuses in-flight
metadata fetch; "＋ library" buttons on rows/details, saved YouTube playlists (`yt_id` in library.json).
