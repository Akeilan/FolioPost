#!/bin/sh
# Run a UI test script inside the installed Folio Post: run_installed.sh /path/to/script.py
HERE="$(cd "$(dirname "$0")" && pwd)"
export FOLIO_TEST_SCRIPT="$1" XDG_CONFIG_HOME="$(mktemp -d)" FOLIO_POST_DATA="$(mktemp -d)" FOLIO_TEST_DELAY=1500
export UI_OUT="${UI_OUT:-/tmp/ui_out_installed}" FOLIO_POST_NON_UNIQUE=1 FOLIO_POST_FILE_SECRETS=1 FOLIO_POST_NO_WELCOME=1
export TZ="${TZ:-Europe/Amsterdam}" FOLIO_POST_NO_REMINDERS=1 FOLIO_POST_NO_AUTOSYNC=1 FOLIO_POST_PUSH_DELAY=1 FOLIO_TESTS="$HERE"
cd /
exec timeout ${UI_TIMEOUT:-400} /usr/bin/folio-post
