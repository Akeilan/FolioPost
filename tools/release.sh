#!/bin/bash
# Folio Post release checks: engine tests, UI tests and command walk (source), deb, installed tests (jammy + nolo), suite.
set -u
R=/home/claude/foliopost
V=$(sed -n 's/^Version: //p' $R/packaging/DEBIAN/control)
for m in /srv/jammy /srv/nolo; do
  mount | grep -q "$m/proc " || mount -t proc proc $m/proc
  mount | grep -q "$m/tmp/.X11-unix " || { mkdir -p $m/tmp/.X11-unix; mount --bind /tmp/.X11-unix $m/tmp/.X11-unix; }
  mount | grep -q "$m/dev " || mount --bind /dev $m/dev
done
pgrep -f "Xvfb :97" >/dev/null || { rm -f /tmp/.X97-lock /tmp/.X11-unix/X97; (setsid Xvfb :97 -screen 0 1600x1000x24 -nolisten tcp >/dev/null 2>&1 &); sleep 1; }
echo "== Writer's engine (M-04), built on 22.04"
mkdir -p /srv/jammy/src/postcore && rsync -a --delete --exclude target $R/vendor/writer/core/ /srv/jammy/src/postcore/
chroot /srv/jammy bash -c ". /root/cargoenv.sh 2>/dev/null; cd /src/postcore && bash build-jammy.sh 2>&1 | grep -E '^error|Finished'" || exit 1
cp /srv/jammy/src/postcore/target/release/libfolio_core.so $R/vendor/writer/folio_core.so
rsync -a --delete --exclude .git $R/ /srv/jammy/src/post/
echo "== engine"
chroot /srv/jammy bash -c "cd /src/post; { FOLIO_POST_FILE_SECRETS=1 python3 tests/test_engine.py; TZ=Europe/Amsterdam python3 tests/test_calendar.py; python3 tests/test_people.py; python3 tests/test_ews.py; python3 tests/test_b3.py; DISPLAY=:${XD:-97} python3 tests/test_b3b.py; } | grep -E '^FAIL|passed|FAILED'"
echo "== ui (source)"
chroot /srv/jammy bash -c "cd /src/post; for u in ${UI_TESTS:-ui_mail.py ui_editor.py ui_writered.py ui_attach.py ui_calendar.py ui_people.py ui_tasks.py ui_folders.py ui_pgp.py ui_smime.py ui_b3.py ui_google.py}; do echo \$u; DISPLAY=:${XD:-97} UI_TIMEOUT=300 sh tests/run_ui.sh \$u 2>&1 | grep -E '^FAIL|UI all|UI FAILS|Traceback'; done"
echo "== X2-01 desktop themes"
chroot /srv/jammy bash -c "cd /src/post; DISPLAY=:${XD:-97} UI_TIMEOUT=600 sh tests/theme_run.sh 2>&1 | grep -E '^--|^FAIL|checks|Traceback'"
echo "== walk"
chroot /srv/jammy bash -c "cd /src/post; DISPLAY=:${XD:-97} UI_TIMEOUT=900 WALK_OUT=/tmp/post-command-walk.tsv sh tests/run_ui.sh command_walk.py 2>&1 | grep -E 'WALK|ERROR|Traceback|not available|commands'"
mkdir -p $R/docs; cp /srv/jammy/tmp/post-command-walk.tsv $R/docs/command-walk.tsv 2>/dev/null
echo "not available: $(grep -c NOT_YET $R/docs/command-walk.tsv)"
echo "== deb"
FOLIO_CORE_SO=$R/vendor/writer/folio_core.so sh $R/build-deb.sh /home/claude/out >/dev/null && ls -la /home/claude/out/folio-post_${V}_amd64.deb
for m in /srv/jammy /srv/nolo /srv/noble; do
  cp /home/claude/out/folio-post_${V}_amd64.deb $m/tmp/
  flock /home/claude/.dpkg.lock chroot $m bash -c "dpkg -i /tmp/folio-post_${V}_amd64.deb >/dev/null 2>&1 || apt-get -y -f install >/dev/null 2>&1; dpkg -l folio-post | tail -1 | awk '{print \$1, \$3}'; folio-post --version"
  rm -rf $m/tmp/posttests; mkdir -p $m/tmp/posttests; cp -r $R/tests/* $m/tmp/posttests/
  echo "== installed in $m"
  for u in ${INST_TESTS:-ui_mail.py ui_editor.py ui_writered.py ui_attach.py ui_calendar.py ui_people.py ui_tasks.py ui_folders.py ui_pgp.py ui_smime.py ui_b3.py ui_google.py}; do
    chroot $m bash -c "cd /tmp/posttests; DISPLAY=:${XD:-97} UI_TIMEOUT=300 sh run_installed.sh /tmp/posttests/$u 2>&1 | grep -E '^FAIL|UI all|UI FAILS|Traceback'"
  done
  chroot $m bash -c "cd /tmp/posttests; DISPLAY=:${XD:-97} UI_TIMEOUT=600 sh theme_run.sh run_installed.sh 2>&1 | grep -E '^--|^FAIL|checks|Traceback'"
done
echo "== Wayland (Weston) on 24.04: desktop themes"
cp /home/claude/folio-suite/tests/wl.sh /srv/noble/tmp/wl.sh
chroot /srv/noble bash -c "cd /tmp/posttests; DISPLAY=:${XD:-97} UI_TIMEOUT=1200 /tmp/wl.sh sh theme_run.sh run_installed.sh 2>&1 | grep -E '^-- |^FAIL|UI all|UI FAILED|checks|Traceback'"
echo "(suite step skipped: built by the coordinator)"
exit 0
echo "== suite"
bash /home/claude/folio-suite/packaging/build-suite.sh /home/claude/out /home/claude/out/suite 2>&1 | tail -3
