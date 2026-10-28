#!/bin/sh
# copy the source into the jammy chroot and run one UI script there: post_test.sh script.py
rsync -a --delete /home/claude/postcal/ /srv/jammy/src/postcal/ --exclude .git
chroot /srv/jammy bash -c "cd /src/postcal; DISPLAY=:99 UI_TIMEOUT=${UI_TIMEOUT:-120} sh tests/run_ui.sh $1" > /tmp/claude-0/postcal_$1.log 2>&1
echo rc=$?
grep -v "Warning\|from gi\|require_version" /tmp/claude-0/postcal_$1.log | tail -${2:-40}
