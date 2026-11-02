# ytblocks

A terminal-styled desktop app for browsing YouTube and watching videos **without ads**, built with
Qt (PySide6), `yt-dlp` and an embedded `mpv`. Packaged for Arch Linux.

> **Status: early release (v0.1.0).** It works for the author's setup, but expect rough edges.
> YouTube changes its pages often, so search parsing may need updates from time to time. Bug reports welcome.

<!-- Add a screenshot: docs/screenshot.png
![ytblocks](docs/screenshot.png)
-->

## Features

- **Search** YouTube; results show title, views, channel and date, with infinite scroll.
- **Click a channel name** to browse that channel's videos (infinite scroll); save it to your library.
- **Filter and sort:** by date, popularity, rating or length; min/max length; minimum views;
  content type (videos, channels, playlists, shorts, with shorts off by default); seen / not seen / both.
- **Player block:** shows thumbnail, description, comments, likes and metadata first. **Nothing loads or plays until you press Play.**
  Then: seek, volume, quality, speed, mute, pop-out window, and video-only fullscreen.
- **Playback preferences persist** (volume, quality, speed...) and apply to every following video.
- **Library:** playlists of videos, saved channels, saved YouTube playlists, through the **＋ library** buttons.
- **Browse with arrows:** ◀ ▶ buttons or the arrow keys move through the result list.
- **Theming:** outline-only, monochrome and soft. Follows your system theme live (dark/light, Breeze, Dracula...
  via KDE, qt6ct or Kvantum), or pick your own colors per element in settings.
- **Resizable blocks, custom fonts, collapsible sidebar;** everything is remembered between runs.

## Layout

```
+-----+-------------------------------+----+
|     |  search                       | ≡  |   ≡ = filter / sort
| ⚙ ☰ +-------------------------------+----+
|     |  player          |  results        |
| lib |                  |                 |
+-----+------------------+-----------------+
```
Sidebar (playlists, saved channels, settings) · search bar · filter/sort · player · results list.

## Install (Arch Linux)

```bash
git clone https://github.com/YOUR_USERNAME/ytblocks.git
cd ytblocks
makepkg -si
```
`PKGBUILD` downloads the tagged release (`v0.1.0`) from GitHub. To build the checked-out files instead:
```bash
./mkdist.sh
makepkg -si -p PKGBUILD.local
```
Run it with `ytblocks` or from your application launcher. Without installing: `python -m ytblocks` from the repo root
(needs the runtime dependencies below).

### Runtime dependencies

| Package | Why |
|---|---|
| `python` (3.11+) | interpreter |
| `pyside6` | Qt6 GUI toolkit with native theme integration |
| `mpv` | provides `libmpv`, embedded for in-window playback |
| `yt-dlp` | resolves direct video streams, channel/playlist paging, metadata, comments |

Optional: `plasma-integration`, `qt6ct`, `breeze`, `kvantum` (theming); `ffmpeg`.

Build-only: `python-build`, `python-installer`, `python-setuptools`, `python-wheel`.

## Usage

| Action | How |
|---|---|
| Search | type in the green bar, press Enter |
| Filter / sort | `≡` button |
| Show details | click a result (nothing plays) |
| Play | **▶ play** button |
| Previous / next video | `◀` `▶` in the results header, **‹ prev / next ›**, or Left / Right arrows when nothing is playing; Ctrl+Left / Ctrl+Right always |
| Seek | Left / Right arrows, or double-click the left / right third of the video |
| Volume | Up / Down arrows, mouse wheel on the video, or the slider |
| Pause | Space, click on the video, or the ⏸ button |
| Pop out / fullscreen | `⇱` / `⛶` buttons (F or Esc inside the video window) |
| Add to library | **＋ library** on a result or on the details page |
| Settings | `⚙` (sizes, fonts, theme) |

## How ads are omitted

Ad omission is part of the playback pipeline, not a filter added afterwards:

1. **Discovery:** promoted and ad items are stripped from every YouTube response before it is parsed.
2. **Resolution:** the YouTube web player (where ads are injected) is never loaded. `yt-dlp` returns raw media URLs, and only
   direct HTTPS `googlevideo.com` formats are accepted. HLS/DASH manifests and live streams are refused,
   because those carry server-side-inserted ads.
3. **Playback:** every URL is re-checked right before it reaches `libmpv`, which runs with `ytdl=no` and without scripts.

Search follows the approach of [ytfzf](https://github.com/pystardust/ytfzf) (scraping `ytInitialData` and the `sp=` filter parameter),
reimplemented in Python. `ytfzf` itself is not required.

**Limits:** live streams cannot be played; sponsor segments inside videos are not removed; YouTube may change
its responses at any time.

## Configuration

Stored in `$XDG_CONFIG_HOME/ytblocks/` (default `~/.config/ytblocks/`):

| File | Content |
|---|---|
| `settings.json` | sizes, fonts, theme, filters, window size |
| `playback.json` | volume, mute, quality, speed, seek step |
| `library.json` | playlists, saved channels |
| `seen.json` | watched video IDs |

Delete a file to reset it.

## Troubleshooting

- **Colors don't match my desktop (Hyprland / non-KDE):** set a Qt platform theme, e.g.
  `QT_QPA_PLATFORMTHEME=qt6ct ytblocks` (install `qt6ct`), or `kde` with `plasma-integration`.
- **Not in KRunner / launcher:** `kbuildsycoca6 --noincremental`, restart KRunner; make sure `/usr/share` is in `XDG_DATA_DIRS`.
- **Search returns nothing or errors:** update `yt-dlp` (`sudo pacman -Syu`); YouTube pages change often.
- **Video won't start:** check `yt-dlp -F <url>` works in a terminal, and that `mpv` is installed.

## Development

```bash
python -m unittest discover -s tests     # Qt-free tests: ad policy, parsers, filters, config
python -m ytblocks                       # run from the repo root
```
Code map and notes: [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md). The modules `adguard`, `yt`, `filters`, `config`
must stay importable without PySide6.

```
ytblocks/    application package        tests/   unit tests
data/        desktop entry and icon     docs/    development notes
PKGBUILD     Arch package (GitHub tag)  PKGBUILD.local + mkdist.sh   build from the working tree
```

## Disclaimer

Unofficial; not affiliated with YouTube or Google. Using third-party clients and skipping ads may go against
YouTube's Terms of Service in your region; you are responsible for how you use this software.

## License

[MIT](LICENSE)
