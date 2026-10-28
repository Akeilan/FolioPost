#!/bin/sh
# Run a UI test script inside Folio Post on an X display (Xvfb): run_ui.sh script.py
HERE="$(cd "$(dirname "$0")" && pwd)"
export FOLIO_TEST_SCRIPT="$HERE/$1" FOLIO_POST_SHARE="${FOLIO_POST_SHARE:-$HERE/../share}"
export XDG_CONFIG_HOME="$(mktemp -d)" FOLIO_POST_DATA="$(mktemp -d)" FOLIO_TEST_DELAY=1500 UI_OUT="${UI_OUT:-/tmp/ui_out}"
export TZ="${TZ:-Europe/Amsterdam}" FOLIO_POST_NO_REMINDERS=1 FOLIO_THEME="${FOLIO_THEME:-light}" FOLIO_POST_NON_UNIQUE=1 FOLIO_POST_FILE_SECRETS=1 FOLIO_POST_NO_WELCOME=1 FOLIO_POST_NO_AUTOSYNC=1 FOLIO_POST_PUSH_DELAY=1 FOLIO_TESTS="$HERE"
cd "$HERE/../app"
exec timeout ${UI_TIMEOUT:-180} python3 -m folio_post
