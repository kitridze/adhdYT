#!/bin/sh
# Creates ytblocks-<pkgver>.tar.gz (the PKGBUILD's source) from this tree.
set -eu
cd "$(dirname "$0")"
ver=$(sed -n 's/^pkgver=//p' PKGBUILD)
tmp=$(mktemp)
tar --transform "s,^\.,ytblocks-$ver," \
    --exclude=src --exclude=pkg --exclude=build --exclude=dist --exclude=.git \
    --exclude=__pycache__ --exclude='*.egg-info' --exclude='*.tar.gz' --exclude='*.pkg.tar.*' \
    -czf "$tmp" .
mv "$tmp" "ytblocks-$ver.tar.gz"
echo "created ytblocks-$ver.tar.gz"
