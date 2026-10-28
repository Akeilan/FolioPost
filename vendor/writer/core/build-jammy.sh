#!/bin/bash
# Build folio_core on Ubuntu 22.04 / Zorin 17. freetype-sys 0.21 asks pkg-config for
# FreeType >= 2.13 ("24.3.18"), but 22.04 ships 2.11 ("24.1.18"); the functions the engine
# uses are all in 2.11, so a .pc that reports the newer version lets it link to the system
# library (the module is loaded with RTLD_NOW, so a missing symbol would fail at once).
set -e
PC=$(mktemp -d)
sed 's/^Version:.*/Version: 24.3.18/' "$(pkg-config --variable=pcfiledir freetype2)/freetype2.pc" > "$PC/freetype2.pc"
cd "$(dirname "$0")"
PKG_CONFIG_PATH="$PC" cargo build --release --features python "$@"
