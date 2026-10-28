"""Hyphenation Options and Manual Hyphenation, as in the original."""
from gi.repository import Gtk

from . import bridge, docapi
from .widgets import FDialog, LengthSpin, grid

SOFT = "­"


def options_dialog(win):
    m = win.engine.model
    if m is None:
        return
    st = docapi.para_styles(m).getByName("Standard")
    d = FDialog(win, "Hyphenation")
    auto = Gtk.CheckButton.new_with_mnemonic("_Automatically hyphenate document")
    auto.set_active(bool(st.ParaIsHyphenation))
    caps = Gtk.CheckButton.new_with_mnemonic("Hyphenate words in _CAPS")
    try:
        caps.set_active(not st.ParaHyphenationNoCaps)
    except Exception:
        caps.set_active(True)
        caps.set_sensitive(False)
    zone = LengthSpin(int(getattr(st, "ParaHyphenationZone", 635) or 635), 0, 25400)
    limit = Gtk.ComboBoxText.new_with_entry()
    for x in ("No limit", "1", "2", "3", "4", "5"):
        limit.append_text(x)
    mx = int(getattr(st, "ParaHyphenationMaxHyphens", 0) or 0)
    limit.get_child().set_text(str(mx) if mx else "No limit")
    d.add(auto)
    d.add(caps)
    d.add(grid([["Hyphenation _zone:", zone], ["_Limit consecutive hyphens to:", limit]]))
    manual = d.add_button("_Manual...", 2)
    manual.set_use_underline(True)
    d.get_action_area().reorder_child(manual, 0)
    d.show_all()
    r = d.run()
    if r in (Gtk.ResponseType.OK, 2):
        um = m.getUndoManager()
        um.enterUndoContext("Hyphenation")
        try:
            st.ParaIsHyphenation = auto.get_active()
            for prop, val in (("ParaHyphenationNoCaps", not caps.get_active()),
                              ("ParaHyphenationZone", int(zone.mm100))):
                try:
                    st.setPropertyValue(prop, val)
                except Exception:
                    pass
            t = limit.get_child().get_text().strip()
            try:
                st.ParaHyphenationMaxHyphens = int(t) if t.isdigit() else 0
            except Exception:
                pass
        finally:
            um.leaveUndoContext()
    d.destroy()
    if r == 2:
        manual_dialog(win)


def _hyphenator():
    lsm = bridge.create("com.sun.star.linguistic2.LinguServiceManager")
    return lsm.getHyphenator()


def candidates(m):
    """Long words that begin a line (they could be split onto the line
    above), in order: [(word cursor, word)]."""
    ctl = docapi.controller(m)
    vc = ctl.getViewCursor()
    keep = vc.getStart()
    out = []
    m.lockControllers()
    try:
        vc.gotoStart(False)
        for _i in range(20000):
            if not vc.goDown(1, False):
                break
            vc.gotoStartOfLine(False)
            c = vc.getText().createTextCursorByRange(vc.getStart())
            if not c.isStartOfWord():
                continue
            c.gotoEndOfWord(True)
            w = c.getString()
            if len(w) >= 6 and w.isalpha() and SOFT not in w:
                out.append((c, w))
    except Exception as e:
        print("hyphenation:", e)
    finally:
        try:
            vc.gotoRange(keep, False)
        except Exception:
            pass
        m.unlockControllers()
    return out


def manual_dialog(win):
    m = win.engine.model
    if m is None:
        return
    try:
        hy = _hyphenator()
    except Exception:
        hy = None
    loc = docapi.view_cursor(m).CharLocale
    items = candidates(m)
    lang = docapi.language_name("%s-%s" % (loc.Language, loc.Country)) or "English"
    done = 0
    for cur, word in items:
        options = []
        try:
            ph = hy.createPossibleHyphens(word, loc, ()) if hy is not None else None
            if ph is not None:
                options = list(ph.getHyphenationPositions())
        except Exception:
            options = []
        if not options:
            continue
        docapi.controller(m).select(cur)
        shown = "".join(ch + ("-" if i in options else "") for i, ch in enumerate(word))
        d = FDialog(win, "Manual Hyphenation: %s" % lang,
                    buttons=(("Yes", Gtk.ResponseType.YES), ("No", Gtk.ResponseType.NO),
                             ("Cancel", Gtk.ResponseType.CANCEL)))
        e = Gtk.Entry(text=shown)
        e.set_width_chars(30)
        d.add(grid([["Hyphenate _at:", e]]))
        d.show_all()
        r = d.run()
        text = e.get_text()
        d.destroy()
        if r == Gtk.ResponseType.CANCEL or r == Gtk.ResponseType.DELETE_EVENT:
            break
        if r != Gtk.ResponseType.YES:
            continue
        # one hyphen: the last one the user left (the original's caret)
        pos = text.rfind("-")
        if pos <= 0:
            continue
        idx = len(text[:pos].replace("-", ""))
        if 0 < idx < len(word):
            c = cur.getText().createTextCursorByRange(cur.getStart())
            c.goRight(idx, False)
            c.getText().insertString(c, SOFT, False)
            done += 1
    win.dialogs.message("Hyphenation is complete." if items else
                        "There are no words to hyphenate.", title="Folio Writer")
    return done
