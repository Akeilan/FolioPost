#!/bin/sh
# Builds folio-post_<version>_all.deb from this tree: the Python app (app/) and the icon set (share/).
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
VERSION="$(sed -n 's/^Version: //p' "$HERE/packaging/DEBIAN/control")"
APPV="$(sed -n 's/^VERSION = "\(.*\)"/\1/p' "$HERE/app/folio_post/__init__.py")"
[ "$VERSION" = "$APPV" ] || { echo "version mismatch: control $VERSION, app $APPV"; exit 1; }
OUT="${1:-$HERE}"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
cp -a "$HERE/packaging/root/." "$STAGE/"
mkdir -p "$STAGE/usr/lib/folio-post" "$STAGE/usr/share/folio-post"
cp -a "$HERE/app/folio_post" "$STAGE/usr/lib/folio-post/"
find "$STAGE/usr/lib/folio-post" -name '__pycache__' -prune -exec rm -rf {} +
cp -a "$HERE/share/iconset" "$STAGE/usr/share/folio-post/"
mkdir -p "$STAGE/DEBIAN"
cp "$HERE/packaging/DEBIAN/"* "$STAGE/DEBIAN/"
chmod 755 "$STAGE/DEBIAN/postinst" "$STAGE/DEBIAN/prerm" "$STAGE/DEBIAN/postrm"
SIZE="$(du -sk "$STAGE" | cut -f1)"
sed -i "s/^Installed-Size: .*/Installed-Size: $SIZE/" "$STAGE/DEBIAN/control"
dpkg-deb --root-owner-group --build -Zxz "$STAGE" "$OUT/folio-post_${VERSION}_all.deb"
echo "Built $OUT/folio-post_${VERSION}_all.deb"
