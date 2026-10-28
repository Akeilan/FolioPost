# Run inside Folio Post (FOLIO_TEST_SCRIPT): M-12, Send as attachment from the other Folio apps
# (folio-post --attach FILE...) and Post as the desktop's mail app (mailto: links).
import os
import sys
import tempfile
import time
import traceback

from gi.repository import Gio, Gtk

FAILS = []


def pump(t=0.2):
    end = time.time() + t
    while time.time() < end:
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)
        time.sleep(0.003)


def check(cond, what):
    print(("ok   " if cond else "FAIL ") + what)
    sys.stdout.flush()
    if not cond:
        FAILS.append(what)


try:
    from folio_post import app as A
    app._maybe_script = lambda *a: None   # do_open would start this script again
    d = tempfile.mkdtemp(prefix="post-attach-")
    a, b = os.path.join(d, "Plan.docx"), os.path.join(d, "Budget sheet.xlsx")
    for p, data in ((a, b"PK\x03\x04plan"), (b, b"PK\x03\x04numbers")):
        with open(p, "wb") as f:
            f.write(data)
    argv = A.attach_argv(["folio-post", "--attach", a, b])
    check(len(argv) == 2 and argv[1].startswith("mailto:?attach="), "--attach becomes one mailto: link: %s" % argv)
    n0 = len(app.composers)
    # what Gio hands a running Post when another process opens the link
    app.do_open([Gio.File.new_for_uri(argv[1])], 1, "")
    pump(0.8)
    check(len(app.composers) == n0 + 1, "a new message opens")
    c = app.composers[-1]
    names = [x[0] for x in c.attachments]
    check(names == ["Plan.docx", "Budget sheet.xlsx"], "both files are attached, names kept: %s" % names)
    check([x[2] for x in c.attachments] == [b"PK\x03\x04plan", b"PK\x03\x04numbers"], "with their contents")
    check(c.subject.get_text() == "" and c.fields["to"].get_text() == "", "nothing else filled in")
    c.modified = False
    c.close()
    pump(0.3)
    # a mailto: link from a web page or another program
    app.do_open([Gio.File.new_for_uri("mailto:ann@example.org?subject=Hello%20there&cc=bob@example.org&body=Hi%20Ann")], 1, "")
    pump(0.8)
    c = app.composers[-1]
    check(c.fields["to"].get_text() == "ann@example.org" and c.fields["cc"].get_text() == "bob@example.org"
          and c.subject.get_text() == "Hello there" and "Hi Ann" in c.editor.text(), "mailto: fields fill the message")
    c.modified = False
    c.close()
    pump(0.3)
    # the default mail app
    calls = []
    real = A.subprocess.run
    A.subprocess.run = lambda cmd, **k: calls.append(cmd)
    A.make_default()
    A.subprocess.run = real
    check(["xdg-mime", "default", "org.folio.Post.desktop", "x-scheme-handler/mailto"] in calls,
          "Make default registers Post for mailto: links: %s" % calls)
    desk = None
    here = os.path.dirname(os.environ["FOLIO_TEST_SCRIPT"])
    for p in (os.path.join(here, "..", "packaging", "root", "usr", "share", "applications", "org.folio.Post.desktop"),
              "/usr/share/applications/org.folio.Post.desktop"):
        if os.path.exists(p):
            desk = open(p).read()
            break
    check(desk is not None and "x-scheme-handler/mailto" in desk and "%U" in desk, "the desktop entry offers Post for mailto: links")
except Exception:
    traceback.print_exc()
    FAILS.append("exception")
print("UI FAILS: %d" % len(FAILS) if FAILS else "UI all passed")
sys.stdout.flush()
os._exit(1 if FAILS else 0)
