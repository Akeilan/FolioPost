# Run inside Folio Post (FOLIO_TEST_SCRIPT): X2-04, the same text height on Ubuntu 22.04 and 24.04
# (24.04's Carlito has Calibri's tall line metrics; fontfix keeps labels one em tall).
import os
import sys
import time

from gi.repository import Gtk

FAILS = []


def pump(t=0.3):
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


from folio_post import fontfix  # noqa: E402
pump(0.5)
h = win.ribbon.get_allocated_height()
print("ribbon height", h, "tall Carlito:", fontfix.needed())
check(h <= int(os.environ.get("RIBBON_MAX", "133")), "the ribbon keeps its 22.04 height of 132 px (%d px)" % h)
c = app.compose(to="a@example.org", subject="x")
pump(0.6)
hc = c.ribbon.get_allocated_height()
print("compose ribbon height", hc)
check(hc <= int(os.environ.get("COMPOSE_RIBBON_MAX", "133")), "the message window's ribbon too (%d px)" % hc)
c.modified = False
c.close()
print("UI FAILS: %d" % len(FAILS) if FAILS else "UI all passed")
sys.stdout.flush()
os._exit(1 if FAILS else 0)
