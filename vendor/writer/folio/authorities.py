"""References > Table of Authorities: Mark Citation (Alt+Shift+I), Insert
Table of Authorities and Update Table."""
import json

from gi.repository import Gtk

from ._lazy import bridge, docapi
from .widgets import FDialog, combo, grid

CATEGORIES = ["Cases", "Statutes", "Other Authorities", "Rules", "Treatises", "Regulations",
              "Constitutional Provisions"]
SECTION = "FolioTOA"


def entries(m):
    try:
        v = json.loads(docapi._doc_setting(m, "Authorities", "") or "{}")
        return v if isinstance(v, dict) else {}
    except ValueError:
        return {}


def _save(m, e):
    docapi._set_doc_setting(m, "Authorities", json.dumps(e))


def _new_id(e):
    n = 1
    while "TA%d" % n in e:
        n += 1
    return "TA%d" % n


def _bookmark(m, rng, name):
    bm = m.createInstance("com.sun.star.text.Bookmark")
    bm.setName(name)
    rng.getText().insertTextContent(rng, bm, True)


def mark(m, rng, long_cite, short_cite, category, all_occurrences=False):
    e = entries(m)
    eid = next((k for k, v in e.items() if v["long"] == long_cite), None) or _new_id(e)
    e[eid] = {"long": long_cite, "short": short_cite or long_cite, "cat": category}
    marks = m.getBookmarks()
    um = m.getUndoManager()
    um.enterUndoContext("Mark Citation")
    try:
        k = 1
        while marks.hasByName("_%s_%d" % (eid, k)):
            k += 1
        _bookmark(m, rng, "_%s_%d" % (eid, k))
        count = 1
        if all_occurrences:
            for needle in {long_cite, short_cite} - {""}:
                sd = m.createSearchDescriptor()
                sd.SearchString = needle
                sd.SearchCaseSensitive = True
                found = m.findAll(sd)
                for i in range(found.getCount()):
                    f = found.getByIndex(i)
                    if _marked(m, f):
                        continue
                    k += 1
                    while marks.hasByName("_%s_%d" % (eid, k)):
                        k += 1
                    _bookmark(m, f, "_%s_%d" % (eid, k))
                    count += 1
        _save(m, e)
        return count
    finally:
        um.leaveUndoContext()


def _marked(m, rng):
    marks = m.getBookmarks()
    text = rng.getText()
    for n in marks.getElementNames():
        if not n.startswith("_TA"):
            continue
        a = marks.getByName(n).getAnchor()
        try:
            if a.getText() == text and text.compareRegionStarts(a.getStart(),
                                                                rng.getStart()) == 0:
                return True
        except Exception:
            pass
    return False


def _pages(m):
    """{entry id: sorted pages}."""
    marks = m.getBookmarks()
    vc = docapi.view_cursor(m)
    keep = vc.getText().createTextCursorByRange(vc.getStart())
    out = {}
    try:
        for n in marks.getElementNames():
            if not n.startswith("_TA"):
                continue
            eid = n[1:].split("_")[0]
            try:
                vc.gotoRange(marks.getByName(n).getAnchor().getStart(), False)
                out.setdefault(eid, set()).add(vc.getPage())
            except Exception:
                pass
    finally:
        try:
            vc.gotoRange(keep, False)
        except Exception:
            pass
    return {k: sorted(v) for k, v in out.items()}


def _write(m, sec, category="All", passim=True):
    e = entries(m)
    pages = _pages(m)
    text = sec.getAnchor().getText()
    cur = text.createTextCursorByRange(sec.getAnchor())
    cur.setString("")
    cur = text.createTextCursorByRange(sec.getAnchor().getStart())
    cats = CATEGORIES if category == "All" else [category]
    first = True
    tab = bridge.struct("com.sun.star.style.TabStop")
    ps = docapi.page_setup(m)
    tab.Position = ps["width"] - ps["left"] - ps["right"]
    tab.Alignment = bridge.enum("com.sun.star.style.TabAlign", "RIGHT")
    tab.FillChar = "."
    for cat in cats:
        items = sorted((v for k, v in e.items() if v["cat"] == cat and k in pages),
                       key=lambda v: v["long"].lower())
        if not items:
            continue
        if not first:
            text.insertControlCharacter(cur, 0, False)
        first = False
        cur.ParaStyleName = "Standard"
        text.insertString(cur, cat, False)
        p = text.createTextCursorByRange(cur)
        p.gotoStartOfParagraph(True)
        p.CharWeight = 150.0
        p.ParaTopMargin = docapi.pt(12)
        p.ParaBottomMargin = docapi.pt(6)
        for v in items:
            text.insertControlCharacter(cur, 0, False)
            pg = pages.get(next(k for k, x in e.items() if x is v), [])
            ref = "passim" if passim and len(pg) >= 5 else ", ".join(str(n) for n in pg)
            start = text.createTextCursorByRange(cur)
            text.insertString(cur, v["long"] + "\t" + ref, False)
            start.gotoRange(cur, True)
            start.CharWeight = 100.0
            start.ParaTabStops = (tab,)
            start.ParaTopMargin = 0
            start.ParaBottomMargin = docapi.pt(4)
    if first:
        text.insertString(cur, "No table of authorities entries found.", False)


def insert_table(m, category="All", passim=True):
    um = m.getUndoManager()
    um.enterUndoContext("Insert Table of Authorities")
    try:
        vc = docapi.view_cursor(m)
        text = vc.getText()
        text.insertControlCharacter(vc, 0, False)
        sec = m.createInstance("com.sun.star.text.TextSection")
        secs = m.getTextSections()
        n = 1
        while secs.hasByName("%s%d" % (SECTION, n)):
            n += 1
        sec.setName("%s%d" % (SECTION, n))
        text.insertTextContent(vc, sec, False)
        docapi._set_doc_setting(m, "TOAOptions:" + sec.getName(),
                                json.dumps({"cat": category, "passim": passim}))
        _write(m, sec, category, passim)
    finally:
        um.leaveUndoContext()


def update_tables(m):
    secs = m.getTextSections()
    n = 0
    for name in secs.getElementNames():
        if name.startswith(SECTION):
            try:
                o = json.loads(docapi._doc_setting(m, "TOAOptions:" + name, "") or "{}")
            except ValueError:
                o = {}
            _write(m, secs.getByName(name), o.get("cat", "All"), o.get("passim", True))
            n += 1
    return n


# ------------------------------------------------------------ dialogs
def mark_dialog(win):
    m = win.engine.model
    if m is None:
        return
    vc = docapi.view_cursor(m)
    sel = vc.getString().strip()
    d = FDialog(win, "Mark Citation", buttons=(("Mark", 10), ("Mark All", 11),
                                               ("Close", Gtk.ResponseType.CANCEL)))
    long_tv = Gtk.TextView()
    long_tv.set_wrap_mode(Gtk.WrapMode.WORD)
    long_tv.set_size_request(380, 60)
    long_tv.get_buffer().set_text(sel)
    fr = Gtk.Frame()
    fr.add(long_tv)
    d.add(Gtk.Label(label="Selected text:", xalign=0))
    d.add(fr)
    cat = combo(CATEGORIES, 0)
    short = Gtk.Entry(text=sel)
    d.add(grid([["_Category:", cat], ["_Short citation:", short]]))
    while True:
        r = d.ask()
        if r not in (10, 11):
            break
        b = long_tv.get_buffer()
        long_cite = b.get_text(*b.get_bounds(), False).strip()
        if not long_cite or vc.isCollapsed():
            win.dialogs.message("Select the citation in the document first.")
            continue
        n = mark(m, vc, long_cite, short.get_text().strip(), cat.get_active_text(),
                 all_occurrences=(r == 11))
        win.status.flash("Marked %d citation%s." % (n, "" if n == 1 else "s"))
        if r == 11:
            break
    d.done()


def insert_dialog(win):
    m = win.engine.model
    if m is None:
        return
    if not entries(m):
        win.dialogs.message("No table of authorities entries found. Select a citation "
                            "and click Mark Citation first.")
        return
    d = FDialog(win, "Table of Authorities")
    cat = combo(["All"] + CATEGORIES, 0)
    passim = Gtk.CheckButton(label="Use passim")
    passim.set_active(True)
    d.add(grid([["Category:", cat]]))
    d.add(passim)
    if d.ask() == Gtk.ResponseType.OK:
        c, p = cat.get_active_text(), passim.get_active()
        win.engine.sync(lambda: insert_table(m, c, p))
    d.done()
