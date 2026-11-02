# Maintainer: YOUR_NAME <you@example.com>
pkgname=ytblocks
pkgver=0.1.0
pkgrel=1
pkgdesc="Terminal-styled Qt YouTube browser/player; ads omitted by construction (yt-dlp + libmpv)"
arch=('any')
url="https://github.com/YOUR_USERNAME/ytblocks"
license=('MIT')
# python        : interpreter (>=3.11)
# pyside6       : Qt6 GUI toolkit (widgets, OpenGL widget) with native platform-theme integration
# mpv           : ships libmpv.so, embedded through the render API for in-window playback
# yt-dlp        : ytfzf's own extractor; resolves direct googlevideo stream URLs, channel/playlist
#                 paging and metadata/comments, so the YouTube web player (ad injector) is never used
depends=('python' 'pyside6' 'mpv' 'yt-dlp')
makedepends=('python-build' 'python-installer' 'python-setuptools' 'python-wheel')
optdepends=('plasma-integration: KDE platform theme (Dolphin/Konsole-identical look)'
            'qt6ct: platform theme for Hyprland/other WMs (QT_QPA_PLATFORMTHEME=qt6ct)'
            'breeze: Breeze Qt style, matches KDE apps'
            'kvantum: alternative Qt theme engine (via qt6ct)'
            'ffmpeg: extra codecs for yt-dlp muxing (mpv already depends on it)')
source=("$pkgname-$pkgver.tar.gz::$url/archive/refs/tags/v$pkgver.tar.gz")
sha256sums=('SKIP')   # after tagging v$pkgver on GitHub run `updpkgsums` to fill this in

check() {
  cd "$pkgname-$pkgver"
  python -m unittest discover -s tests     # Qt-free unit tests (ad policy, parsers, filters, config)
}

build() {
  cd "$pkgname-$pkgver"
  python -m build --wheel --no-isolation
}

package() {
  cd "$pkgname-$pkgver"
  python -m installer --destdir="$pkgdir" dist/*.whl
  install -Dm644 data/ytblocks.desktop "$pkgdir/usr/share/applications/ytblocks.desktop"
  install -Dm644 data/ytblocks.svg "$pkgdir/usr/share/icons/hicolor/scalable/apps/ytblocks.svg"
  install -Dm644 LICENSE "$pkgdir/usr/share/licenses/$pkgname/LICENSE"
}
