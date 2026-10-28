"""The References tab with the new engine: footnote and endnote settings and
navigation, tables of contents and figures, the index (XE and INDEX fields),
the table of authorities (TA and TOA fields), citations and the bibliography
(CITATION and BIBLIOGRAPHY fields, sources kept in the document's
bibliography part, as the original keeps them)."""
import os
import re
import uuid
from xml.sax.saxutils import escape

from gi.repository import Gtk

from ..widgets import FDialog, Preview, combo, grid, heading

LEADER_WORD = {"": "none", ".": "dot", "-": "hyphen", "_": "underscore"}
LEADER_CHAR = {v: k for k, v in LEADER_WORD.items()}
TOA_CATEGORIES = ["Cases", "Statutes", "Other Authorities", "Rules", "Treatises", "Regulations",
                  "Constitutional Provisions"] + [str(i) for i in range(8, 17)]
# the dialog's number formats (old engine codes) -> Word's
NUMFMT = {4: "decimal", 1: "lowerLetter", 0: "upperLetter", 3: "lowerRoman", 2: "upperRoman"}
FMTCODE = {v: k for k, v in NUMFMT.items()}
RESTART = {2: "continuous", 1: "eachSect", 0: "eachPage"}
RESTARTCODE = {v: k for k, v in RESTART.items()}


def _ed(win):
    return win.engine.ed


def _after(win):
    win.engine.view.after_edit()


def q(s):
    """A field argument in quotes."""
    return '"%s"' % (s or "").replace('"', "'")


def parse(instr):
    """A field instruction: (kind, args, {switch: value or True})."""
    toks = re.findall(r'"((?:[^"\\]|\\.)*)"|(\\\S)|(\S+)', instr)
    kind, args, sw = "", [], {}
    last = None
    for quoted, switch, word in toks:
        if switch:
            last = switch[1]
            sw[last] = True
            continue
        val = quoted if quoted or (not word) else word
        if not kind and not quoted:
            kind = word.upper()
            continue
        if last is not None and sw.get(last) is True:
            sw[last] = val
            last = None
        else:
            args.append(val)
    return kind, args, sw


def fields(win, kind=None):
    """Top-level body fields [(index, kind, args, switches, result)]."""
    out = []
    for i, (instr, res, _p, _a, _b) in enumerate(_ed(win).body_fields()):
        k, args, sw = parse(instr)
        if kind is None or k == kind:
            out.append((i, k, args, sw, res))
    return out


# ================================================================ notes
class NotesBackend:
    """notes.dialog's operations, with the new engine."""

    def __init__(self, win):
        self.win = win

    def current(self, endnote):
        fmt, start, restart, pos = _ed(self.win).note_settings(endnote)
        return {"type": FMTCODE.get(fmt, 4), "start": start, "counting": RESTARTCODE.get(restart, 2),
                "pos": pos}

    def apply(self, endnote, num_type, start, counting, pos):
        _ed(self.win).set_note_settings(endnote, NUMFMT.get(num_type, "decimal"), start,
                                        RESTART.get(counting, "continuous"), pos)

    def insert(self, endnote, mark):
        ed = _ed(self.win)
        if mark:
            ed.insert_note_mark(endnote, mark)
        else:
            ed.insert_note(endnote)

    def count(self, endnote):
        return _ed(self.win).note_count(endnote)

    def convert(self, which):
        how = {True: "fe", False: "ef", None: "swap"}[which]
        n = _ed(self.win).convert_notes(how)
        _after(self.win)
        return n

    def sync(self, fn):
        fn()
        _after(self.win)


def goto_note(win, endnote, forward):
    ed = _ed(win)
    ok = ed.goto("Endnote" if endnote else "Footnote", "" if forward else "-1")
    if not ok and not endnote:
        ok = ed.goto("Endnote", "" if forward else "-1")
    win.engine.view.after_move()
    win.engine.view.scroll_to_caret()
    return ok


def show_notes(win):
    ed = _ed(win)
    if not (ed.note_count(False) or ed.note_count(True)):
        win.dialogs.message("There are no footnotes or endnotes in this document.")
        return
    ed.show_notes(False)
    win.engine.view.after_move()
    win.engine.view.queue_draw()
    win.engine.view.scroll_to_caret()


# ================================================================ table of contents
def _toc_fields(win, figures=False):
    out = []
    for i, k, args, sw, _r in fields(win, "TOC"):
        if bool("c" in sw or "a" in sw) == figures:
            out.append((i, sw))
    return out


def toc_instr(levels, pages=True, right=True, links=True, outline=True, styles=None, entries=False):
    s = "TOC"
    if outline:
        s += ' \\o "1-%d"' % levels
    if links:
        s += " \\h"
    s += " \\z"
    if entries:
        s += " \\f"
    if outline:
        s += " \\u"
    if not pages:
        s += " \\n"
    elif not right:
        s += ' \\p " "'
    if styles:
        s += " \\t " + q(",".join("%s,%d" % (n, l) for n, l in sorted(styles.items(), key=lambda x: x[1])))
    return s


def _styles_in_use(win):
    """Paragraph style names for the Options list."""
    out = []
    for st in _ed(win).style_list():
        sid, name, kind = st[0], st[1], st[2]
        if kind == "paragraph" and (st[7] or name.lower().startswith("heading") or not st[5]):
            out.append(name)
    return sorted(set(out), key=str.lower)


def toc_dialog(win):
    from .. import tocdlg as T
    ex = _toc_fields(win)
    sw = ex[0][1] if ex else {}
    levels0 = 3
    if isinstance(sw.get("o"), str) and "-" in sw["o"]:
        try:
            levels0 = int(sw["o"].split("-")[1])
        except ValueError:
            pass
    show0 = "n" not in sw
    right0 = "p" not in sw
    links0 = "h" in sw or not ex
    d = FDialog(win, "Table of Contents")
    page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    page.set_border_width(10)
    pages, ralign, lead, hl = T._common_controls(show0, right0, ".", links0)
    fmt = combo(T.FORMATS, 0)
    levels = Gtk.SpinButton.new_with_range(1, 9, 1)
    levels.set_value(levels0)
    state = {"levels": lambda: int(levels.get_value()), "pages": pages.get_active,
             "right": ralign.get_active, "leader": lambda: T.LEADERS[max(0, lead.get_active())][1],
             "links": hl.get_active, "format": lambda: fmt.get_active_text() or ""}
    pv, previews = T._previews(state, T._sample_headings())
    page.pack_start(pv, False, False, 0)
    left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    for w in (pages, ralign):
        left.pack_start(w, False, False, 0)
    left.pack_start(grid([["Ta_b leader:", lead]]), False, False, 0)
    cols = Gtk.Box(spacing=12, homogeneous=True)
    cols.pack_start(left, True, True, 0)
    cols.pack_start(hl, True, True, 0)
    hl.set_valign(Gtk.Align.START)
    page.pack_start(cols, False, False, 0)
    page.pack_start(heading("General"), False, False, 0)
    page.pack_start(grid([["For_mats:", fmt], ["Show _levels:", levels]]), False, False, 0)
    bb = Gtk.Box(spacing=6)
    bb.set_halign(Gtk.Align.END)
    opt = Gtk.Button(label="_Options...", use_underline=True)
    mod = Gtk.Button(label="_Modify...", use_underline=True)
    bb.pack_start(opt, False, False, 0)
    bb.pack_start(mod, False, False, 0)
    page.pack_start(bb, False, False, 0)
    nb = Gtk.Notebook()
    nb.append_page(page, Gtk.Label(label="Table of Contents"))
    d.add(nb)
    styles0 = {}
    if isinstance(sw.get("t"), str):
        parts = [p.strip() for p in re.split(r"[,;]", sw["t"])]
        for k in range(0, len(parts) - 1, 2):
            if parts[k + 1].isdigit():
                styles0[parts[k]] = int(parts[k + 1])
    opts = {"outline": "o" in sw or not ex, "marks": "f" in sw, "styles": styles0 or None}
    T._wire([pages, ralign, lead, hl, fmt, levels], previews, pages, ralign, lead)
    fmt.connect("changed", lambda *_: mod.set_sensitive(fmt.get_active() == 0))
    opt.connect("clicked", lambda *_: _toc_options(win, opts))
    mod.connect("clicked", lambda *_: T._modify_styles(win, ["TOC %d" % i for i in range(1, 10)]))
    d.show_all()
    ok = d.ask() == Gtk.ResponseType.OK
    if ok and ex and not win.dialogs.confirm("Do you want to replace the selected table of contents?"):
        ok = False
    if ok:
        instr = toc_instr(int(levels.get_value()), pages.get_active(), ralign.get_active(),
                          hl.get_active(), opts["outline"], opts["styles"], opts["marks"])
        leader = LEADER_WORD.get(T.LEADERS[max(0, lead.get_active())][1], "dot")
        _toc_format(win, fmt.get_active_text())
        ed = _ed(win)
        if ex:
            ed.set_table_instr(ex[0][0], instr, leader)
        else:
            ed.insert_table_field(instr, title="Contents", title_style="TOCHeading",
                                  gallery="Table of Contents", leader=leader)
        _after(win)
    d.destroy()
    win.focus_document()


def _toc_format(win, name):
    """The dialog's Formats change the TOC styles a little, as the original's do."""
    from .. import tocdlg as T
    f = T.FORMAT_STYLE.get(name or "")
    if not f:
        return
    bold1, caps1, ital2, _ld = f
    ed = _ed(win)
    rpr1 = ("<w:b/><w:bCs/>" if bold1 else "") + ("<w:caps/>" if caps1 else "")
    rpr2 = "<w:i/><w:iCs/>" if ital2 else ""
    for lvl, rpr in ((1, rpr1), (2, rpr2)):
        ind = "" if lvl == 1 else '<w:ind w:left="%d"/>' % (220 * (lvl - 1))
        ed.add_style_xml('<w:style w:type="paragraph" w:styleId="TOC%d"><w:name w:val="toc %d"/>'
                         '<w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:autoRedefine/>'
                         '<w:uiPriority w:val="39"/><w:unhideWhenUsed/><w:pPr><w:spacing w:after="100"/>%s'
                         '</w:pPr><w:rPr>%s</w:rPr></w:style>' % (lvl, lvl, ind, rpr))


def _toc_options(win, opts):
    d = FDialog(win, "Table of Contents Options")
    d.add(Gtk.Label(label="Build table of contents from:", xalign=0))
    use_styles = Gtk.CheckButton.new_with_mnemonic("_Styles")
    use_styles.set_active(bool(opts["styles"]))
    d.add(use_styles)
    store = Gtk.ListStore(str, str)
    cur = opts["styles"] or {}
    for n in _styles_in_use(win):
        lvl = cur.get(n)
        store.append([n, str(lvl) if lvl else ""])
    tv = Gtk.TreeView(model=store)
    tv.append_column(Gtk.TreeViewColumn("Available styles:", Gtk.CellRendererText(), text=0))
    cell = Gtk.CellRendererText(editable=True)

    def edited(_c, path, text):
        text = text.strip()
        store[path][1] = text if text.isdigit() and 1 <= int(text) <= 9 else ""
        use_styles.set_active(True)
    cell.connect("edited", edited)
    tv.append_column(Gtk.TreeViewColumn("TOC level:", cell, text=1))
    sw = Gtk.ScrolledWindow()
    sw.set_size_request(320, 200)
    sw.add(tv)
    d.add(sw, expand=True)
    outline = Gtk.CheckButton.new_with_mnemonic("_Outline levels")
    outline.set_active(opts["outline"])
    marks = Gtk.CheckButton.new_with_mnemonic("Table _entry fields")
    marks.set_active(opts["marks"])
    d.add(outline)
    d.add(marks)
    reset = d.add_button("_Reset", 1)
    reset.set_use_underline(True)
    while True:
        r = d.ask()
        if r == 1:
            for row in store:
                row[1] = ""
            outline.set_active(True)
            marks.set_active(False)
            use_styles.set_active(False)
            continue
        break
    if r == Gtk.ResponseType.OK:
        opts["outline"] = outline.get_active()
        opts["marks"] = marks.get_active()
        opts["styles"] = {row[0]: int(row[1]) for row in store if row[1]} if use_styles.get_active() else None
    d.destroy()


# ================================================================ table of figures
def figures_dialog(win, labels):
    from .. import tocdlg as T
    ex = _toc_fields(win, figures=True)
    sw = ex[0][1] if ex else {}
    d = FDialog(win, "Table of Figures")
    page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    page.set_border_width(10)
    pages, ralign, lead, hl = T._common_controls("n" not in sw, "p" not in sw, ".", "h" in sw or not ex)
    fmt = combo(T.FORMATS, 0)
    cur = sw.get("c") if isinstance(sw.get("c"), str) else sw.get("a") if isinstance(sw.get("a"), str) else "Figure"
    label = combo(labels + ["(none)"], cur if cur in labels else "Figure")
    incl = Gtk.CheckButton.new_with_mnemonic("Include label and _number")
    incl.set_active("a" not in sw)
    state = {"levels": lambda: 1, "pages": pages.get_active, "right": ralign.get_active,
             "leader": lambda: T.LEADERS[max(0, lead.get_active())][1], "links": hl.get_active,
             "format": lambda: fmt.get_active_text() or ""}

    def entries():
        lab = label.get_active_text() or "Figure"
        pre = (lab + " %d: ") if incl.get_active() and lab != "(none)" else ""
        return [(1, (pre % i if pre else "") + t, p) for i, (t, p) in
                enumerate((("Text", 1), ("Text", 3), ("Text", 5), ("Text", 7)), 1)]
    ent = entries()
    pv, previews = T._previews(state, ent)

    def regen(*_):
        ent[:] = entries()
        for p in previews:
            p.queue_draw()
    page.pack_start(pv, False, False, 0)
    left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    for w in (pages, ralign):
        left.pack_start(w, False, False, 0)
    left.pack_start(grid([["Ta_b leader:", lead]]), False, False, 0)
    cols = Gtk.Box(spacing=12, homogeneous=True)
    cols.pack_start(left, True, True, 0)
    cols.pack_start(hl, True, True, 0)
    hl.set_valign(Gtk.Align.START)
    page.pack_start(cols, False, False, 0)
    page.pack_start(heading("General"), False, False, 0)
    page.pack_start(grid([["For_mats:", fmt], ["Caption _label:", label], [incl, None]]), False, False, 0)
    bb = Gtk.Box(spacing=6)
    bb.set_halign(Gtk.Align.END)
    opt = Gtk.Button(label="_Options...", use_underline=True)
    mod = Gtk.Button(label="_Modify...", use_underline=True)
    bb.pack_start(opt, False, False, 0)
    bb.pack_start(mod, False, False, 0)
    page.pack_start(bb, False, False, 0)
    nb = Gtk.Notebook()
    nb.append_page(page, Gtk.Label(label="Table of Figures"))
    d.add(nb)
    opts = {"style": sw.get("t").split(",")[0] if isinstance(sw.get("t"), str) else None}
    T._wire([pages, ralign, lead, hl, fmt], previews, pages, ralign, lead)
    label.connect("changed", regen)
    incl.connect("toggled", regen)
    opt.connect("clicked", lambda *_: _tof_options(win, opts))
    mod.connect("clicked", lambda *_: T._modify_styles(win, ["Table of Figures"]))
    d.show_all()
    ok = d.ask() == Gtk.ResponseType.OK
    lab = label.get_active_text() or "Figure"
    if ok and ex and not win.dialogs.confirm("Do you want to replace the selected table of figures?"):
        ok = False
    if ok:
        s = "TOC"
        if hl.get_active():
            s += " \\h"
        s += " \\z"
        if opts["style"]:
            s += " \\t " + q(opts["style"] + ",1")
        elif lab != "(none)":
            s += (" \\c " if incl.get_active() else " \\a ") + q(lab)
        if not pages.get_active():
            s += " \\n"
        elif not ralign.get_active():
            s += ' \\p " "'
        leader = LEADER_WORD.get(T.LEADERS[max(0, lead.get_active())][1], "dot")
        ed = _ed(win)
        if ex:
            ed.set_table_instr(ex[0][0], s, leader)
        else:
            ed.insert_table_field(s, leader=leader)
        _after(win)
    d.destroy()
    win.focus_document()


def _tof_options(win, opts):
    d = FDialog(win, "Table of Figures Options")
    d.add(heading("Build table of figures from"))
    use = Gtk.CheckButton.new_with_mnemonic("_Style:")
    names = _styles_in_use(win) or ["Caption"]
    st = combo(names, opts["style"] if opts["style"] in names else ("Caption" if "Caption" in names else names[0]))
    use.set_active(bool(opts["style"]))
    d.add(grid([[use, st]]))
    d.show_all()
    if d.ask() == Gtk.ResponseType.OK:
        opts["style"] = st.get_active_text() if use.get_active() else None
    d.destroy()


# ================================================================ index
def xe_instr(main, sub="", see="", bookmark="", bold=False, italic=False):
    t = main
    if sub:
        t += ":" + sub
    s = "XE " + q(t)
    if see:
        s += " \\t " + q(see)
    if bookmark:
        s += " \\r " + q(bookmark)
    if bold:
        s += " \\b"
    if italic:
        s += " \\i"
    return s


def index_instr(cols=2, runin=False, right=False, headings=False):
    s = "INDEX"
    if right:
        s += ' \\e "\t"'
    if headings:
        s += ' \\h "A"'
    if runin:
        s += " \\r"
    s += ' \\c "%d" \\z "1033"' % cols
    return s


def index_dialog(win):
    from .. import tocdlg as T
    ex = fields(win, "INDEX")
    sw = ex[0][3] if ex else {}
    d = FDialog(win, "Index")
    page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    page.set_border_width(10)
    indented = Gtk.RadioButton.new_with_mnemonic(None, "In_dented")
    runin = Gtk.RadioButton.new_with_mnemonic_from_widget(indented, "Ru_n-in")
    runin.set_active("r" in sw)
    cols = Gtk.SpinButton.new_with_range(1, 4, 1)
    try:
        cols.set_value(int(sw.get("c")) if isinstance(sw.get("c"), str) else 2)
    except ValueError:
        cols.set_value(2)
    lang = combo(["English (United States)"], 0)
    ralign = Gtk.CheckButton.new_with_mnemonic("_Right align page numbers")
    ralign.set_active(sw.get("e") == "\t")
    lead = combo([n for n, _c in T.LEADERS], 1)
    fmt = combo(T.FORMATS, 0)

    def draw(cr, W, H):
        cr.set_source_rgb(1, 1, 1)
        cr.paint()
        cr.select_font_face("Sans")
        cr.set_font_size(9)
        n = int(cols.get_value())
        cw = (W - 10) / n
        items = [(0, "Aristotle, 2"), (0, "Asteroid belt. See Jupiter"), (0, "Atmosphere"),
                 (1, "Earth"), (2, "exosphere, 4"), (2, "ionosphere, 3"), (1, "Mars, 7")]
        if runin.get_active():
            items = [(0, "Aristotle, 2"), (0, "Asteroid belt. See Jupiter"),
                     (0, "Atmosphere: Earth: exosphere, 4; ionosphere, 3; Mars, 7")]
        x0, y, col = 6, 16, 0
        for lvl, t in items:
            if y > H - 6:
                col += 1
                if col >= n:
                    break
                x0, y = 6 + col * cw, 16
            x = x0 + 8 * lvl
            parts = t.rsplit(", ", 1) if "," in t and not runin.get_active() else [t]
            cr.set_source_rgb(0.1, 0.1, 0.1)
            cr.move_to(x, y)
            cr.show_text(parts[0])
            if len(parts) == 2:
                if ralign.get_active():
                    pw = cr.text_extents(parts[1]).x_advance
                    tx = x + cr.text_extents(parts[0]).x_advance + 3
                    px = x0 + cw - 6 - pw
                    ld = T.LEADERS[max(0, lead.get_active())][1]
                    if ld:
                        lw = cr.text_extents(ld).x_advance or 3
                        while tx + lw < px - 2:
                            cr.move_to(tx, y)
                            cr.show_text(ld)
                            tx += lw
                    cr.move_to(px, y)
                    cr.show_text(parts[1])
                else:
                    cr.show_text(", " + parts[1])
            y += 13
    page.pack_start(Gtk.Label(label="Print Pre_view", xalign=0, use_underline=True), False, False, 0)
    prev = Preview(draw, 300, 110)
    fr = Gtk.Frame()
    fr.add(prev)
    page.pack_start(fr, False, False, 0)
    tb = Gtk.Box(spacing=12)
    tb.pack_start(Gtk.Label(label="Type:"), False, False, 0)
    tb.pack_start(indented, False, False, 0)
    tb.pack_start(runin, False, False, 0)
    page.pack_start(tb, False, False, 0)
    page.pack_start(grid([["Colu_mns:", cols], ["_Language:", lang]]), False, False, 0)
    page.pack_start(ralign, False, False, 0)
    page.pack_start(grid([["Ta_b leader:", lead], ["For_mats:", fmt]]), False, False, 0)
    bb = Gtk.Box(spacing=6)
    bb.set_halign(Gtk.Align.END)
    mark = Gtk.Button(label="Mar_k Entry...", use_underline=True)
    auto = Gtk.Button(label="A_utoMark...", use_underline=True)
    mod = Gtk.Button(label="_Modify...", use_underline=True)
    for b in (mark, auto, mod):
        bb.pack_start(b, False, False, 0)
    page.pack_start(bb, False, False, 0)
    nb = Gtk.Notebook()
    nb.append_page(page, Gtk.Label(label="Index"))
    d.add(nb)

    def refresh(*_):
        lead.set_sensitive(ralign.get_active())
        prev.queue_draw()
    for w, sig in ((cols, "value-changed"), (ralign, "toggled"), (lead, "changed"),
                   (runin, "toggled"), (fmt, "changed")):
        w.connect(sig, refresh)
    refresh()
    mark.connect("clicked", lambda *_: (d.response(Gtk.ResponseType.CANCEL), mark_entry(win)))

    def pick_auto(*_):
        fc = Gtk.FileChooserDialog(title="Open Index AutoMark File", transient_for=d,
                                   action=Gtk.FileChooserAction.OPEN)
        fc.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Open", Gtk.ResponseType.OK)
        if fc.run() == Gtk.ResponseType.OK:
            n = automark(win, fc.get_filename())
            win.status.flash("Marked %d index entr%s." % (n, "y" if n == 1 else "ies"))
        fc.destroy()
    auto.connect("clicked", pick_auto)
    mod.connect("clicked", lambda *_: T._modify_styles(
        win, ["Index %d" % i for i in range(1, 4)] + ["Index Heading"]))
    d.show_all()
    ok = d.ask() == Gtk.ResponseType.OK
    if ok and ex and not win.dialogs.confirm("Do you want to replace the selected index?"):
        ok = False
    if ok:
        headings = (fmt.get_active_text() or "") in ("Classic", "Fancy", "Modern", "Formal")
        instr = index_instr(int(cols.get_value()), runin.get_active(), ralign.get_active(), headings)
        leader = LEADER_WORD.get(T.LEADERS[max(0, lead.get_active())][1], "dot")
        ed = _ed(win)
        if ex:
            ed.set_table_instr(ex[0][0], instr, leader)
        else:
            ed.insert_table_field(instr, leader=leader, columns=int(cols.get_value()))
        _after(win)
    d.destroy()
    win.focus_document()


def automark(win, path):
    """A concordance file: each row the text to find and (optionally) its entry. A
    .docx table, or text with a tab between the two."""
    rows = []
    try:
        if path.lower().endswith(".docx"):
            import zipfile
            x = zipfile.ZipFile(path).read("word/document.xml").decode("utf-8", "replace")
            for tr in re.findall(r"<w:tr[ >].*?</w:tr>", x, re.S):
                cells = ["".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", tc)) for tc in
                         re.findall(r"<w:tc[ >].*?</w:tc>", tr, re.S)]
                if cells and cells[0].strip():
                    rows.append((cells[0].strip(), (cells[1] if len(cells) > 1 else "").strip()))
        else:
            with open(path, encoding="utf-8", errors="replace") as f:
                for line in f:
                    a, _t, b = line.rstrip("\n").partition("\t")
                    if a.strip():
                        rows.append((a.strip(), b.strip()))
    except Exception as e:
        win.dialogs.message("The AutoMark file couldn't be read: %s" % e)
        return 0
    n = 0
    ed = _ed(win)
    for find, entry in rows:
        n += ed.mark_all(find, xe_instr(entry or find), True)
    _after(win)
    return n


_MARK = {}


def mark_entry(win):
    """Mark Index Entry: stays open, like the original, so several entries can be
    marked in a row."""
    dlg = _MARK.get(id(win))
    if dlg is not None:
        dlg.present()
        dlg.fill()
        return
    w = Gtk.Window(title="Mark Index Entry", transient_for=win)
    w.set_type_hint(1)
    w.set_position(Gtk.WindowPosition.CENTER_ON_PARENT)
    w.get_style_context().add_class("folio-dialog")
    w.set_resizable(False)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    box.set_border_width(12)
    w.add(box)
    main = Gtk.Entry()
    main.set_width_chars(36)
    sub = Gtk.Entry()
    box.pack_start(heading("Index"), False, False, 0)
    box.pack_start(grid([["_Main entry:", main], ["_Subentry:", sub]]), False, False, 0)
    box.pack_start(heading("Options"), False, False, 0)
    r_see = Gtk.RadioButton.new_with_mnemonic(None, "_Cross-reference:")
    see = Gtk.Entry(text="See ")
    r_page = Gtk.RadioButton.new_with_mnemonic_from_widget(r_see, "Current _page")
    r_range = Gtk.RadioButton.new_with_mnemonic_from_widget(r_see, "Page _range")
    marks = combo(_ed(win).bookmark_names() or [""], 0)
    r_page.set_active(True)
    box.pack_start(grid([[r_see, see], [r_page, None], [r_range, None], ["    Bookmark:", marks]]), False, False, 0)
    box.pack_start(heading("Page number format"), False, False, 0)
    bold = Gtk.CheckButton.new_with_mnemonic("_Bold")
    ital = Gtk.CheckButton.new_with_mnemonic("_Italic")
    fb = Gtk.Box(spacing=12)
    fb.pack_start(bold, False, False, 0)
    fb.pack_start(ital, False, False, 0)
    box.pack_start(fb, False, False, 0)
    note = Gtk.Label(label="This dialog box stays open so that you can mark multiple index entries.", xalign=0)
    note.set_line_wrap(True)
    note.set_max_width_chars(44)
    box.pack_start(note, False, False, 0)
    btns = Gtk.Box(spacing=6)
    btns.set_halign(Gtk.Align.END)
    mark = Gtk.Button(label="_Mark", use_underline=True)
    mark_all = Gtk.Button(label="Mark _All", use_underline=True)
    close = Gtk.Button(label="Close")
    for b in (mark, mark_all, close):
        btns.pack_start(b, False, False, 0)
    box.pack_start(btns, False, False, 0)

    def instr():
        return xe_instr(main.get_text().strip(), sub.get_text().strip(),
                        see.get_text().strip() if r_see.get_active() else "",
                        (marks.get_active_text() or "") if r_range.get_active() else "",
                        bold.get_active(), ital.get_active())

    def do_mark(*_):
        if not main.get_text().strip():
            return
        _ed(win).insert_code_field(instr())
        _after(win)

    def do_mark_all(*_):
        word = _ed(win).selected_text().strip()
        if not word or not main.get_text().strip():
            return
        n = _ed(win).mark_all(word, instr(), True)
        _after(win)
        win.status.flash("Marked %d index entr%s." % (n, "y" if n == 1 else "ies"))

    def fill():
        main.set_text(_ed(win).selected_text().strip()[:200])
        sub.set_text("")
        mark_all.set_sensitive(bool(main.get_text()))
    w.fill = fill
    mark.connect("clicked", do_mark)
    mark_all.connect("clicked", do_mark_all)

    def on_close(*_):
        _MARK.pop(id(win), None)
        w.destroy()
        return True
    close.connect("clicked", on_close)
    w.connect("delete-event", on_close)
    _MARK[id(win)] = w
    fill()
    w.show_all()


# ================================================================ table of authorities
def ta_entries(win):
    """Marked citations: [(long, short, category number)]."""
    out = []
    for _i, _k, _a, sw, _r in fields(win, "TA"):
        if isinstance(sw.get("l"), str):
            c = sw.get("c")
            out.append((sw["l"], sw.get("s") if isinstance(sw.get("s"), str) else sw["l"],
                        int(c) if isinstance(c, str) and c.isdigit() else 1))
    return out


def mark_citation(win):
    ed = _ed(win)
    sel = ed.selected_text().strip()
    d = FDialog(win, "Mark Citation", buttons=(("Mark", 10), ("Mark All", 11), ("Close", Gtk.ResponseType.CANCEL)))
    long_tv = Gtk.TextView()
    long_tv.set_wrap_mode(Gtk.WrapMode.WORD)
    long_tv.set_size_request(380, 60)
    long_tv.get_buffer().set_text(sel)
    fr = Gtk.Frame()
    fr.add(long_tv)
    d.add(Gtk.Label(label="Selected text:", xalign=0))
    d.add(fr)
    cat = combo(TOA_CATEGORIES, 0)
    short = Gtk.Entry(text=sel)
    d.add(grid([["_Category:", cat], ["_Short citation:", short]]))
    while True:
        r = d.ask()
        if r not in (10, 11):
            break
        b = long_tv.get_buffer()
        long_cite = b.get_text(*b.get_bounds(), False).strip()
        if not long_cite or not ed.has_selection():
            win.dialogs.message("Select the citation in the document first.")
            continue
        sh = short.get_text().strip() or long_cite
        c = max(0, cat.get_active()) + 1
        n = 1
        if r == 11:
            n = ed.mark_all(sel, "TA \\s " + q(sh), True)
        ed.insert_code_field("TA \\l %s \\s %s \\c %d" % (q(long_cite), q(sh), c))
        _after(win)
        win.status.flash("Marked %d citation%s." % (max(1, n), "" if n == 1 else "s"))
        if r == 11:
            break
    d.done()


def toa_dialog(win):
    from .. import tocdlg as T
    ents = ta_entries(win)
    if not ents:
        win.dialogs.message("No table of authorities entries found. Select a citation and click "
                            "Mark Citation first.")
        return
    d = FDialog(win, "Table of Authorities")
    cat = combo(["All"] + TOA_CATEGORIES, 0)
    passim = Gtk.CheckButton.new_with_mnemonic("Use _passim")
    passim.set_active(True)
    keep = Gtk.CheckButton.new_with_mnemonic("_Keep original formatting")
    keep.set_active(True)
    lead = combo([n for n, _c in T.LEADERS], 1)
    fmt = combo(T.FORMATS, 0)
    d.add(grid([["Category:", cat]]))
    d.add(passim)
    d.add(keep)
    d.add(grid([["Ta_b leader:", lead], ["For_mats:", fmt]]))
    bb = Gtk.Box(spacing=6)
    bb.set_halign(Gtk.Align.END)
    mc = Gtk.Button(label="Mar_k Citation...", use_underline=True)
    mod = Gtk.Button(label="_Modify...", use_underline=True)
    bb.pack_start(mc, False, False, 0)
    bb.pack_start(mod, False, False, 0)
    d.add(bb)
    mc.connect("clicked", lambda *_: (d.response(Gtk.ResponseType.CANCEL), mark_citation(win)))
    mod.connect("clicked", lambda *_: T._modify_styles(win, ["Table of Authorities", "TOA Heading"]))
    d.show_all()
    if d.ask() == Gtk.ResponseType.OK:
        sel = cat.get_active()
        cats = sorted({c for _l, _s, c in ents}) if sel <= 0 else [sel]
        leader = LEADER_WORD.get(T.LEADERS[max(0, lead.get_active())][1], "dot")
        ed = _ed(win)
        for c in cats:
            s = "TOA \\h \\c %s" % q(str(c))
            if passim.get_active():
                s += " \\p"
            if not keep.get_active():
                s += " \\f"
            ed.insert_table_field(s, leader=leader)
        _after(win)
    d.done()
    win.focus_document()


def update_tables(win):
    n = _ed(win).update_toc()
    refresh_citations(win)
    _after(win)
    return n


# ================================================================ citations
BIB_NS = "http://schemas.openxmlformats.org/officeDocument/2006/bibliography"
STYLE_XSL = {"APA": "\\APASixthEditionOfficeOnline.xsl", "Chicago": "\\CHICAGO.XSL",
             "Harvard": "\\HarvardAnglia2008OfficeOnline.xsl", "IEEE": "\\IEEE2006OfficeOnline.xsl",
             "ISO 690": "\\ISO690Nmerical.XSL", "MLA": "\\MLASeventhEditionOfficeOnline.xsl",
             "Turabian": "\\TURABIAN.XSL"}
SOURCE_TYPE = {"Book": "Book", "Book Section": "BookSection", "Journal Article": "JournalArticle",
               "Article in a Periodical": "ArticleInAPeriodical",
               "Conference Proceedings": "ConferenceProceedings", "Report": "Report",
               "Web site": "InternetSite", "Document From Web site": "DocumentFromInternetSite",
               "Miscellaneous": "Misc"}
TYPE_OF = {v: k for k, v in SOURCE_TYPE.items()}
# dict key -> element (journal depends on the type)
ELEMS = {"title": "Title", "year": "Year", "city": "City", "publisher": "Publisher",
         "booktitle": "BookTitle", "month": "Month", "issue": "Issue", "pages": "Pages",
         "volume": "Volume", "url": "URL"}


def _journal_elem(t):
    return {"Article in a Periodical": "PeriodicalTitle", "Web site": "InternetSiteTitle",
            "Document From Web site": "InternetSiteTitle"}.get(t, "JournalName")


def _persons(text):
    out = []
    for a in re.split(r"\s*;\s*", (text or "").strip()):
        if not a:
            continue
        if "," in a:
            last, first = [x.strip() for x in a.split(",", 1)]
        else:
            parts = a.split()
            last, first = parts[-1], " ".join(parts[:-1])
        out.append((last, first))
    return out


def _names_xml(text):
    ps = "".join("<b:Person><b:Last>%s</b:Last>%s</b:Person>" % (
        escape(l), "<b:First>%s</b:First>" % escape(f) if f else "") for l, f in _persons(text))
    return "<b:NameList>%s</b:NameList>" % ps


def sources_xml(sources, style):
    out = ['<b:Sources xmlns:b="%s" xmlns="%s" SelectedStyle="%s" StyleName="%s" Version="6">'
           % (BIB_NS, BIB_NS, escape(STYLE_XSL.get(style, STYLE_XSL["APA"])), escape(style))]
    for s in sources:
        t = s.get("type", "Book")
        parts = ["<b:Tag>%s</b:Tag>" % escape(s.get("tag", "")),
                 "<b:SourceType>%s</b:SourceType>" % SOURCE_TYPE.get(t, "Book"),
                 "<b:Guid>{%s}</b:Guid>" % s.get("_guid", str(uuid.uuid4()).upper())]
        who = ""
        if s.get("author"):
            who += "<b:Author>%s</b:Author>" % _names_xml(s["author"])
        if s.get("editor"):
            who += "<b:Editor>%s</b:Editor>" % _names_xml(s["editor"])
        if who:
            parts.append("<b:Author>%s</b:Author>" % who)
        for k, el in ELEMS.items():
            if s.get(k):
                if k == "booktitle" and t == "Conference Proceedings":
                    el = "ConferenceName"
                parts.append("<b:%s>%s</b:%s>" % (el, escape(s[k]), el))
        if s.get("journal"):
            el = _journal_elem(t)
            parts.append("<b:%s>%s</b:%s>" % (el, escape(s["journal"]), el))
        out.append("<b:Source>%s</b:Source>" % "".join(parts))
    out.append("</b:Sources>")
    return "".join(out)


def _text(x, name):
    m = re.search(r"<(?:b:)?%s>(.*?)</(?:b:)?%s>" % (name, name), x, re.S)
    if not m:
        return ""
    from xml.sax.saxutils import unescape
    return unescape(m.group(1)).strip()


def _names(x):
    out = []
    for p in re.findall(r"<(?:b:)?Person>(.*?)</(?:b:)?Person>", x, re.S):
        last, first = _text(p, "Last"), " ".join(t for t in (_text(p, "First"), _text(p, "Middle")) if t)
        out.append("%s, %s" % (last, first) if first else last)
    if not out:
        corp = _text(x, "Corporate")
        if corp:
            out.append(corp)
    return "; ".join(out)


def parse_sources(xml):
    """(sources, style) from a bibliography part."""
    style = "APA"
    m = re.search(r'StyleName="([^"]*)"', xml or "")
    if m and m.group(1) in STYLE_XSL:
        style = m.group(1)
    else:
        m = re.search(r'SelectedStyle="([^"]*)"', xml or "")
        if m:
            for k, v in STYLE_XSL.items():
                if v.lower().strip("\\").split(".")[0][:4] in m.group(1).lower():
                    style = k
                    break
    out = []
    for body in re.findall(r"<(?:b:)?Source>(.*?)</(?:b:)?Source>", xml or "", re.S):
        t = TYPE_OF.get(_text(body, "SourceType"), "Miscellaneous")
        s = {"tag": _text(body, "Tag"), "type": t}
        g = _text(body, "Guid")
        if g:
            s["_guid"] = g.strip("{}")
        auth = re.search(r"<(?:b:)?Author>\s*<(?:b:)?Author>(.*?)</(?:b:)?Author>", body, re.S)
        if auth:
            s["author"] = _names(auth.group(1))
        ed = re.search(r"<(?:b:)?Editor>(.*?)</(?:b:)?Editor>", body, re.S)
        if ed:
            s["editor"] = _names(ed.group(1))
        for k, el in ELEMS.items():
            v = _text(body, el)
            if v:
                s[k] = v
        if t == "Conference Proceedings" and not s.get("booktitle"):
            v = _text(body, "ConferenceName")
            if v:
                s["booktitle"] = v
        v = _text(body, _journal_elem(t)) or _text(body, "JournalName")
        if v:
            s["journal"] = v
        if s["tag"]:
            out.append(s)
    return out, style


class Cites:
    """The functions dlg_cite uses (as the old engine's citations module has
    them), with the window standing for the document."""

    def __init__(self):
        from .. import citations as C
        self.C = C
        for k in ("TYPES", "FIELDS", "STYLES", "authors", "author_list", "citation_text", "entry_parts",
                  "entry_text", "make_tag", "master_sources", "save_master", "add_to_master", "cite_label"):
            setattr(self, k, getattr(C, k))

    # -------------------------------------------------- storage
    def _load(self, win):
        return parse_sources(_ed(win).custom_xml(BIB_NS) or "")

    def _save(self, win, sources, style):
        _ed(win).set_custom_xml(BIB_NS, sources_xml(sources, style))

    def doc_sources(self, win):
        return self._load(win)[0]

    def current_style(self, win):
        return self._load(win)[1]

    def set_style(self, win, style):
        self._save(win, self.doc_sources(win), style)
        self.refresh(win)

    def add_source(self, win, src, master=True):
        sources, style = self._load(win)
        tags = {s.get("tag") for s in sources}
        if not src.get("tag") or src["tag"] in tags and not src.get("_editing"):
            src["tag"] = self.make_tag(src, tags)
        src.pop("_editing", None)
        old = next((s for s in sources if s.get("tag") == src["tag"]), None)
        if old and old.get("_guid"):
            src["_guid"] = old["_guid"]
        sources = [s for s in sources if s.get("tag") != src["tag"]] + [src]
        self._save(win, sources, style)
        if master:
            self.add_to_master({k: v for k, v in src.items() if not k.startswith("_")})
        self.refresh(win)
        return src

    def delete_source(self, win, tag):
        sources, style = self._load(win)
        self._save(win, [s for s in sources if s.get("tag") != tag], style)

    def is_cited(self, win, tag):
        return any(self._cite(sw, args)[0] == tag for _i, _k, args, sw, _r in fields(win, "CITATION"))

    def has_citations(self, win):
        return bool(fields(win, "CITATION"))

    # -------------------------------------------------- fields
    @staticmethod
    def _cite(sw, args):
        tag = args[0] if args else ""
        opts = {}
        if isinstance(sw.get("p"), str):
            opts["pages"] = sw["p"]
        sup = [k for k, s in (("author", "n"), ("year", "y"), ("title", "t")) if s in sw]
        if sup:
            opts["suppress"] = sup
        return tag, opts

    @staticmethod
    def instr(tag, opts):
        s = "CITATION %s" % tag
        if opts.get("pages"):
            s += " \\p " + q(opts["pages"])
        for k, c in (("author", "n"), ("year", "y"), ("title", "t")):
            if k in (opts.get("suppress") or ()):
                s += " \\" + c
        return s + " \\l 1033"

    def _labels(self, win, sources, style):
        if style == "IEEE":
            order = []
            for _i, _k, args, sw, _r in fields(win, "CITATION"):
                t = self._cite(sw, args)[0]
                if t not in order:
                    order.append(t)
            labels = {t: str(n) for n, t in enumerate(order, 1)}
            n = len(labels)
            for s in sources:
                if s["tag"] not in labels:
                    n += 1
                    labels[s["tag"]] = str(n)
            return labels
        return self.C._identifiers(None, sources, style)

    def label(self, src, style, labels, opts):
        lab = self.cite_label(src, style, labels.get(src["tag"], src["tag"]), opts)
        return ("[%s]" if style == "IEEE" else "(%s)") % lab

    def refresh(self, win):
        """Every citation and bibliography in the current style."""
        sources, style = self._load(win)
        by = {s["tag"]: s for s in sources}
        labels = self._labels(win, sources, style)
        ed = _ed(win)
        for i, _k, args, sw, res in fields(win, "CITATION"):
            tag, opts = self._cite(sw, args)
            src = by.get(tag)
            if src is not None:
                t = self.label(src, style, labels, opts)
                if t != res:
                    ed.set_field_text(i, t)
        for i, _k, _a, _sw, _r in fields(win, "BIBLIOGRAPHY"):
            ed.set_table_result(i, self.bibliography_xml(win, sources, style, labels))
        _after(win)

    def bibliography_xml(self, win, sources, style, labels):
        cited = []
        for _i, _k, args, sw, _r in fields(win, "CITATION"):
            t = self._cite(sw, args)[0]
            if t not in cited:
                cited.append(t)
        by = {s["tag"]: s for s in sources}
        srcs = [by[t] for t in cited if t in by]
        if style == "IEEE":
            srcs.sort(key=lambda s: int(labels.get(s["tag"], "999")))
        else:
            srcs.sort(key=self.C._sort_key)
        self._ensure_style(win, style)
        if not srcs:
            return ('<w:p><w:pPr><w:pStyle w:val="Bibliography"/></w:pPr><w:r><w:rPr><w:b/><w:bCs/>'
                    '<w:noProof/></w:rPr><w:t>There are no sources in the current document.</w:t></w:r></w:p>')
        out = []
        for s in srcs:
            runs = ""
            if style == "IEEE":
                runs += '<w:r><w:rPr><w:noProof/></w:rPr><w:t xml:space="preserve">[%s]</w:t></w:r>' \
                        '<w:r><w:rPr><w:noProof/></w:rPr><w:tab/></w:r>' % escape(labels.get(s["tag"], ""))
            for t, it in self.entry_parts(s, style):
                runs += '<w:r><w:rPr>%s<w:noProof/></w:rPr><w:t xml:space="preserve">%s</w:t></w:r>' % (
                    "<w:i/><w:iCs/>" if it else "", escape(t))
            out.append('<w:p><w:pPr><w:pStyle w:val="Bibliography"/></w:pPr>%s</w:p>' % runs)
        return "".join(out)

    def _ensure_style(self, win, style):
        ed = _ed(win)
        ind = '<w:ind w:left="720" w:hanging="720"/>'
        tabs = '<w:tabs><w:tab w:val="left" w:pos="720"/></w:tabs>' if style == "IEEE" else ""
        ed.add_style_xml('<w:style w:type="paragraph" w:styleId="Bibliography"><w:name w:val="Bibliography"/>'
                         '<w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:uiPriority w:val="37"/>'
                         '<w:unhideWhenUsed/><w:pPr>%s<w:spacing w:after="0"/>%s</w:pPr></w:style>' % (tabs, ind))

    def insert_citation(self, win, tag):
        sources, style = self._load(win)
        if not any(s["tag"] == tag for s in sources):
            for s in self.master_sources():
                if s.get("tag") == tag:
                    self.add_source(win, dict(s), master=False)
                    break
            else:
                return None
            sources, style = self._load(win)
        ed = _ed(win)
        by = {s["tag"]: s for s in sources}
        labels = self._labels(win, sources, style)
        ed.insert_field(self.instr(tag, {}), self.label(by[tag], style, labels, {}))
        self.refresh(win)
        return tag

    def insert_bibliography(self, win, title="Bibliography"):
        sources, style = self._load(win)
        labels = self._labels(win, sources, style)
        xml = self.bibliography_xml(win, sources, style, labels)
        ed = _ed(win)
        ed.insert_table_field("BIBLIOGRAPHY", title=title or None, title_style="Heading1",
                              gallery="Bibliographies", paras=xml)
        _after(win)

    def citation_at_cursor(self, win):
        return _ed(win).field_at_caret("CITATION")

    def citation_info(self, win, i):
        for j, _k, args, sw, _r in fields(win, "CITATION"):
            if j == i:
                return self._cite(sw, args)
        return "", {}

    def set_citation_options(self, win, i, opts):
        tag, _o = self.citation_info(win, i)
        if not tag:
            return
        sources, style = self._load(win)
        by = {s["tag"]: s for s in sources}
        _ed(win).set_field_instr(i, self.instr(tag, opts))
        self.refresh(win)


CITES = None


def cites():
    global CITES
    if CITES is None:
        CITES = Cites()
    return CITES


def refresh_citations(win):
    if fields(win, "CITATION") or fields(win, "BIBLIOGRAPHY"):
        cites().refresh(win)
