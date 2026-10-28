#!/bin/sh
# Folio Post composes mail with Folio Writer's editor (M-04): Writer's own document engine
# (folio_core, Rust) and its document view. This copies them in from a commit of the Writer repo
# (WRITER_REF, default HEAD), which is the place to change them. build-deb.sh builds the engine.
set -e
HERE="$(cd "$(dirname "$0")/.." && pwd)"
W="${WRITER_TREE:-$HERE/../folio-writer}"
REF="${WRITER_REF:-HEAD}"
V="$HERE/vendor/writer"
T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT
(cd "$W" && git archive "$REF" app/folio core/src core/Cargo.toml core/Cargo.lock core/build-jammy.sh \
   share/templates/Normal-A4.docx share/templates/Normal-Letter.docx) | tar -x -C "$T"
rm -rf "$V"
mkdir -p "$V"
mv "$T/app/folio" "$V/folio"
mv "$T/core" "$V/core"
mv "$T/share/templates" "$V/templates"
(cd "$W" && git rev-parse --short "$REF") > "$V/WRITER_COMMIT"
sed -n 's/^VERSION = "\(.*\)"/\1/p;s/^__version__ = "\(.*\)"/\1/p' "$V/folio/__init__.py" | head -1 > "$V/WRITER_VERSION"
echo "vendored Folio Writer $(cat "$V/WRITER_VERSION") ($(cat "$V/WRITER_COMMIT")) into $V"
