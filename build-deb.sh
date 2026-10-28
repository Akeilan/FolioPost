#!/bin/sh
# Builds folio-post_<version>_amd64.deb from this tree: the Python app (app/), the icon set (share/) and Writer's editor (vendor/writer).
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
# M-04: Folio Writer's editor (vendored by tools/sync_writer.sh); its engine is built on the oldest
# supported release (Ubuntu 22.04) and passed in as FOLIO_CORE_SO, or found next to the vendored code
SO="${FOLIO_CORE_SO:-$HERE/vendor/writer/folio_core.so}"
[ -f "$SO" ] || { echo "no folio_core.so: build vendor/writer/core first (see release_post.sh)"; exit 1; }
mkdir -p "$STAGE/usr/lib/folio-post/writer"
cp -a "$HERE/vendor/writer/folio" "$HERE/vendor/writer/templates" "$HERE/vendor/writer/WRITER_VERSION" \
      "$HERE/vendor/writer/WRITER_COMMIT" "$STAGE/usr/lib/folio-post/writer/"
install -m644 "$SO" "$STAGE/usr/lib/folio-post/writer/folio_core.so"
strip --strip-unneeded "$STAGE/usr/lib/folio-post/writer/folio_core.so" 2>/dev/null || true
mkdir -p "$STAGE/DEBIAN"
cp "$HERE/packaging/DEBIAN/"* "$STAGE/DEBIAN/"
chmod 755 "$STAGE/DEBIAN/postinst" "$STAGE/DEBIAN/prerm" "$STAGE/DEBIAN/postrm"
SIZE="$(du -sk "$STAGE" | cut -f1)"
sed -i "s/^Installed-Size: .*/Installed-Size: $SIZE/" "$STAGE/DEBIAN/control"
dpkg-deb --root-owner-group --build -Zxz "$STAGE" "$OUT/folio-post_${VERSION}_amd64.deb"
echo "Built $OUT/folio-post_${VERSION}_amd64.deb"
