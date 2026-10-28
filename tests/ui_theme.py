# X2-01: run inside Folio Post (FOLIO_TEST_SCRIPT) started under GTK_THEME=Adwaita:dark or
# FolioTestColour: Mail, Calendar, People and Tasks with every ribbon tab, the File view, a compose
# window with Writer's editor, and the dialogs the ribbon opens keep Post's own colours.
import os
import sys
import time
import traceback

sys.path.insert(0, os.path.dirname(os.environ["FOLIO_TEST_SCRIPT"]))
import themecheck  # noqa: E402
from gi.repository import Gtk  # noqa: E402

OUT = os.environ.get("UI_OUT", "/tmp/ui_out")
os.makedirs(OUT, exist_ok=True)
FAILS = []
LOOKED = []


def pump(t=0.2):
    end = time.time() + t
    while time.time() < end:
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)
        time.sleep(0.003)


def look(w, where):
    pump(0.3)
    probs = themecheck.audit(w, where)
    if probs:
        # a busy machine can grab a window before it has finished drawing: look again
        pump(1.5)
        probs = themecheck.audit(w, where)
    for p in probs:
        print("FAIL " + p)
    if probs or os.environ.get("THEME_SHOTS"):
        themecheck.save(w, os.path.join(OUT, "theme_%s%s_%s.png" % (themecheck.mode(), os.environ.get("FOLIO_THEME", ""),
                                                                    where.replace(" ", "_").replace("/", "-"))))
    FAILS.extend(probs)
    LOOKED.append(where)
    if not probs:
        print("ok   %s (%s)" % (where, themecheck.mode()))


try:
    print("theme", os.environ.get("GTK_THEME"), "mode", themecheck.mode(), "app", os.environ.get("FOLIO_THEME", "desktop"))
    seen = set()

    def look_run(d):
        t = d.get_title() or type(d).__name__
        if t not in seen:
            seen.add(t)
            d.show_all()
            pump(0.3)
            look(d, "dialog " + t)
        return Gtk.ResponseType.CANCEL
    Gtk.Dialog.run = look_run
    Gtk.MessageDialog.run = look_run
    Gtk.NativeDialog.run = lambda d: Gtk.ResponseType.CANCEL
    Gtk.PrintOperation.run = lambda *a: Gtk.PrintOperationResult.CANCEL
    for module in ("mail", "calendar", "people", "tasks"):
        win.run("go:" + module)
        pump(0.4)
        for tab in list(win.ribbon.tabs):
            if tab.button is None or not tab.button.get_visible():
                continue
            win.ribbon.select(tab)
            look(win, "%s tab %s" % (module, tab.name))
    win.run("go:mail")
    pump(0.3)
    win.show_backstage()
    from folio_post.backstage import NAV
    for e in NAV:
        if isinstance(e, tuple) and e[0] not in ("back", "exit"):
            win.backstage.nav(e[0])
            look(win, "file " + e[0])
    win.backstage.close()
    pump()
    c = app.compose(to="you@example.org", subject="Theme")
    pump(0.6)
    c.editor.insert_text("Some text in the message")
    for tab in list(c.ribbon.tabs):
        if tab.button is None or not tab.button.get_visible():
            continue
        c.ribbon.select(tab)
        look(c, "compose tab " + tab.name)
    for cmd in ("insert-table", "insert-link", "font-dialog", "spelling", "word-count"):
        try:
            c.run(cmd)
        except Exception:
            pass
        pump(0.2)
    c.modified = False
    c.close()
    pump(0.3)
except Exception:
    traceback.print_exc()
    FAILS.append("exception")
print("%d checks, %d failed" % (len(LOOKED), len(FAILS)))
print("UI FAILS: %d" % len(FAILS) if FAILS else "UI all passed")
sys.stdout.flush()
os._exit(1 if FAILS or len(LOOKED) < 10 else 0)
