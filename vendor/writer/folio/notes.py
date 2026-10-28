"""Footnote and Endnote dialog: location, number format, custom marks,
numbering, conversion between footnotes and endnotes."""
from gi.repository import Gtk

from ._lazy import bridge, docapi
from .widgets import FDialog

FORMATS = [("1, 2, 3, ...", 4), ("a, b, c, ...", 1), ("A, B, C, ...", 0),
           ("i, ii, iii, ...", 3), ("I, II, III, ...", 2)]
SYMBOLS = ["*", "†", "‡", "§"]
NUMBERING = [("Continuous", 2), ("Restart each section", 1), ("Restart each page", 0)]


def _settings(m, endnote):
    return m.getEndnoteSettings() if endnote else m.getFootnoteSettings()


def current(m, endnote=False):
    s = _settings(m, endnote)
    out = {"type": s.NumberingType, "start": s.StartAt + 1}
    try:
        out["counting"] = s.FootnoteCounting if not endnote else 2
    except Exception:
        out["counting"] = 2
    return out


def apply_settings(m, endnote, num_type, start, counting):
    s = _settings(m, endnote)
    s.NumberingType = num_type
    s.StartAt = max(0, start - 1)
    if not endnote:
        try:
            s.FootnoteCounting = counting
        except Exception:
            pass


def insert_note(m, endnote=False, mark=""):
    vc = docapi.view_cursor(m)
    note = m.createInstance("com.sun.star.text.Endnote" if endnote else
                            "com.sun.star.text.Footnote")
    if mark:
        note.setLabel(mark)
    vc.getText().insertTextContent(vc, note, False)
    vc.gotoRange(note.getText().getEnd(), False)
    return note


def notes(m, endnote):
    c = m.getEndnotes() if endnote else m.getFootnotes()
    return [c.getByIndex(i) for i in range(c.getCount())]


def convert(m, to_endnote=None):
    """to_endnote True: footnotes -> endnotes; False: endnotes -> footnotes;
    None: swap both."""
    jobs = []
    if to_endnote in (True, None):
        jobs += [(n, True) for n in notes(m, False)]
    if to_endnote in (False, None):
        jobs += [(n, False) for n in notes(m, True)]
    if not jobs:
        return 0
    ctl = docapi.controller(m)
    vc = docapi.view_cursor(m)
    um = m.getUndoManager()
    um.enterUndoContext("Convert Notes")
    try:
        for old, endnote in jobs:
            anchor = old.getAnchor()
            text = anchor.getText()
            cur = text.createTextCursorByRange(anchor.getStart())
            label = old.getLabel()
            # copy the note's content with its formatting
            body = old.getText()
            vc.gotoRange(body.getStart(), False)
            vc.gotoRange(body.getEnd(), True)
            data = ctl.getTransferable() if body.getString() else None
            new = m.createInstance("com.sun.star.text.Endnote" if endnote else
                                   "com.sun.star.text.Footnote")
            if label:
                new.setLabel(label)
            text.insertTextContent(cur, new, False)
            if data is not None:
                vc.gotoRange(new.getText().getStart(), False)
                ctl.insertTransferable(data)
            text.removeTextContent(old)
    finally:
        um.leaveUndoContext()
    return len(jobs)


class _Classic:
    """The dialog's operations with the old engine."""

    def __init__(self, win, m):
        self.win, self.m = win, m

    def current(self, endnote):
        c = current(self.m, endnote)
        c["pos"] = "docEnd" if endnote else "pageBottom"
        return c

    def apply(self, endnote, num_type, start, counting, pos):
        apply_settings(self.m, endnote, num_type, start, counting)
        if endnote:
            _endnotes_at_section(self.m, pos == "sectEnd")

    def insert(self, endnote, mark):
        insert_note(self.m, endnote, mark)

    def count(self, endnote):
        return len(notes(self.m, endnote))

    def convert(self, which):
        return convert(self.m, which)

    def sync(self, fn):
        m = self.m

        def go():
            um = m.getUndoManager()
            um.enterUndoContext("Footnote and Endnote")
            try:
                fn()
            finally:
                um.leaveUndoContext()
        self.win.engine.sync(go)


def dialog(win):
    if getattr(win.engine, "native", False):
        from .native.refs import NotesBackend
        B = NotesBackend(win)
    else:
        m = win.engine.model
        if m is None:
            return
        B = _Classic(win, m)
    d = FDialog(win, "Footnote and Endnote", buttons=(("Insert", 10),
                                                      ("Cancel", Gtk.ResponseType.CANCEL),
                                                      ("Apply", 11)))
    g = Gtk.Grid(row_spacing=6, column_spacing=10)
    hdr = Gtk.Label(xalign=0)
    hdr.set_markup("<b>Location</b>")
    g.attach(hdr, 0, 0, 3, 1)
    rb_foot = Gtk.RadioButton(label="Footnotes:")
    rb_end = Gtk.RadioButton(label="Endnotes:", group=rb_foot)
    foot_where = Gtk.ComboBoxText()
    for t in ("Bottom of page", "Below text"):
        foot_where.append_text(t)
    foot_where.set_active(0)
    end_where = Gtk.ComboBoxText()
    for t in ("End of document", "End of section"):
        end_where.append_text(t)
    end_where.set_active(0)
    conv = Gtk.Button(label="Convert...")
    g.attach(rb_foot, 0, 1, 1, 1)
    g.attach(foot_where, 1, 1, 1, 1)
    g.attach(rb_end, 0, 2, 1, 1)
    g.attach(end_where, 1, 2, 1, 1)
    g.attach(conv, 2, 2, 1, 1)
    hdr2 = Gtk.Label(xalign=0)
    hdr2.set_markup("<b>Format</b>")
    g.attach(hdr2, 0, 3, 3, 1)
    fmt = Gtk.ComboBoxText()
    for t, _v in FORMATS:
        fmt.append_text(t)
    custom = Gtk.Entry()
    custom.set_width_chars(6)
    sym = Gtk.MenuButton(label="Symbol...")
    sym_menu = Gtk.Menu()
    for s in SYMBOLS:
        it = Gtk.MenuItem(label=s)
        it.connect("activate", lambda _i, s=s: custom.set_text(custom.get_text() + s))
        sym_menu.append(it)
    sym_menu.show_all()
    sym.set_popup(sym_menu)
    start = Gtk.SpinButton.new_with_range(1, 9999, 1)
    numbering = Gtk.ComboBoxText()
    for t, _v in NUMBERING:
        numbering.append_text(t)
    g.attach(Gtk.Label(label="Number format:", xalign=0), 0, 4, 1, 1)
    g.attach(fmt, 1, 4, 2, 1)
    g.attach(Gtk.Label(label="Custom mark:", xalign=0), 0, 5, 1, 1)
    g.attach(custom, 1, 5, 1, 1)
    g.attach(sym, 2, 5, 1, 1)
    g.attach(Gtk.Label(label="Start at:", xalign=0), 0, 6, 1, 1)
    g.attach(start, 1, 6, 1, 1)
    g.attach(Gtk.Label(label="Numbering:", xalign=0), 0, 7, 1, 1)
    g.attach(numbering, 1, 7, 2, 1)
    hdr3 = Gtk.Label(xalign=0)
    hdr3.set_markup("<b>Apply changes</b>")
    g.attach(hdr3, 0, 8, 3, 1)
    scope = Gtk.ComboBoxText()
    scope.append_text("Whole document")
    scope.set_active(0)
    g.attach(Gtk.Label(label="Apply changes to:", xalign=0), 0, 9, 1, 1)
    g.attach(scope, 1, 9, 2, 1)

    def load(*_):
        endnote = rb_end.get_active()
        cur = B.current(endnote)
        codes = [v for _t, v in FORMATS]
        fmt.set_active(codes.index(cur["type"]) if cur["type"] in codes else 0)
        start.set_value(cur["start"])
        ncodes = [v for _t, v in NUMBERING]
        numbering.set_active(ncodes.index(cur["counting"]) if cur["counting"] in ncodes else 0)
        if endnote:
            end_where.set_active(1 if cur.get("pos") == "sectEnd" else 0)
        else:
            foot_where.set_active(1 if cur.get("pos") == "beneathText" else 0)
        foot_where.set_sensitive(not endnote)
        end_where.set_sensitive(endnote)
    rb_foot.connect("toggled", load)
    load()

    def do_convert(*_):
        sub = FDialog(d, "Convert Notes")
        r1 = Gtk.RadioButton(label="Convert all footnotes to endnotes")
        r2 = Gtk.RadioButton(label="Convert all endnotes to footnotes", group=r1)
        r3 = Gtk.RadioButton(label="Swap footnotes and endnotes", group=r1)
        nf, ne = B.count(False), B.count(True)
        r1.set_sensitive(nf > 0)
        r2.set_sensitive(ne > 0)
        r3.set_sensitive(nf > 0 and ne > 0)
        if not nf and ne:
            r2.set_active(True)
        for r in (r1, r2, r3):
            sub.add(r)
        res = sub.ask()
        which = True if r1.get_active() else (False if r2.get_active() else None)
        sub.done()
        if res == Gtk.ResponseType.OK and (nf or ne):
            B.convert(which)
    conv.connect("clicked", do_convert)
    d.add(g)
    r = d.ask()
    endnote = rb_end.get_active()
    num_type = FORMATS[max(0, fmt.get_active())][1]
    st = int(start.get_value())
    counting = NUMBERING[max(0, numbering.get_active())][1]
    mark = custom.get_text().strip()
    if endnote:
        pos = "sectEnd" if end_where.get_active() == 1 else "docEnd"
    else:
        pos = "beneathText" if foot_where.get_active() == 1 else "pageBottom"
    d.done()
    if r not in (10, 11, Gtk.ResponseType.OK):
        return

    def go():
        B.apply(endnote, num_type, st, counting, pos)
        if r in (10, Gtk.ResponseType.OK):
            B.insert(endnote, mark)
    B.sync(go)


def _endnotes_at_section(m, on):
    """End of section: collect endnotes at the end of the current section."""
    try:
        sec = docapi.read_cursor(m).TextSection
    except Exception:
        sec = None
    if sec is None:
        return
    try:
        sec.EndnoteIsCollectAtTextEnd = on
    except Exception:
        pass
