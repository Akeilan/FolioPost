"""The Table of Contents, Index and Table of Figures dialogs, as in the
original: print and web previews, page numbers shown / right-aligned, tab
leader, formats, the Options and Modify buttons."""
from gi.repository import Gtk

from ._lazy import bridge, docapi, uno
from .widgets import FDialog, Preview, combo, grid, heading

LEADERS = [("(none)", ""), ("........", "."), ("--------", "-"), ("________", "_")]
FORMATS = ["From template", "Classic", "Distinctive", "Fancy", "Modern", "Formal", "Simple"]
# format: (level-1 bold, level-1 caps, level-2 italic, leader or None to keep)
FORMAT_STYLE = {"Classic": (True, True, False, ""), "Distinctive": (True, False, True, "."),
                "Fancy": (True, False, False, ""), "Modern": (True, False, False, ""),
                "Formal": (False, True, False, "."), "Simple": (False, False, False, "")}


def _tok(kind, **kw):
    return (bridge.prop("TokenType", kind),) + tuple(bridge.prop(k, v) for k, v in kw.items())


def level_tokens(show_pages=True, right=True, leader=".", links=True, number=True,
                 sep_text=" "):
    t = []
    if links:
        t.append(_tok("TokenHyperlinkStart"))
    if number:
        t.append(_tok("TokenEntryNumber"))
    t.append(_tok("TokenEntryText"))
    if show_pages:
        if right:
            t.append(_tok("TokenTabStop", TabStopRightAligned=True,
                          TabStopFillCharacter=leader or " "))
        else:
            t.append(_tok("TokenText", Text=sep_text))
        t.append(_tok("TokenPageNumber"))
    if links:
        t.append(_tok("TokenHyperlinkEnd"))
    return tuple(t)


def set_level_format(idx, first, tokens):
    lf = idx.LevelFormat
    for i in range(first, lf.getCount()):
        uno.invoke(lf, "replaceByIndex",
                   (i, uno.Any("[][]com.sun.star.beans.PropertyValue", tokens)))
    idx.LevelFormat = lf


def read_level_format(idx, level=1):
    """(show pages, right aligned, leader, links) from an existing index."""
    try:
        toks = idx.LevelFormat.getByIndex(level)
    except Exception:
        return True, True, ".", True
    kinds = []
    leader, right = ".", False
    for t in toks:
        d = {p.Name: p.Value for p in t}
        kinds.append(d.get("TokenType"))
        if d.get("TokenType") == "TokenTabStop":
            right = bool(d.get("TabStopRightAligned", True))
            leader = (d.get("TabStopFillCharacter") or "").strip()
    return ("TokenPageNumber" in kinds, right, leader, "TokenHyperlinkStart" in kinds)


def _style_format(m, prefix, fmt, levels):
    """Formats: the level styles' looks (as in the original, 'From template'
    keeps the styles)."""
    if fmt not in FORMAT_STYLE:
        return None
    bold, caps, ital, leader = FORMAT_STYLE[fmt]
    ps = m.getStyleFamilies().getByName("ParagraphStyles")
    for i in range(1, levels + 1):
        name = "%s %d" % (prefix, i)
        if not ps.hasByName(name):
            continue
        st = ps.getByName(name)
        try:
            st.CharWeight = 150.0 if (bold and i == 1) else 100.0
            st.CharCaseMap = 1 if (caps and i == 1) else 0
            st.CharPosture = bridge.enum("com.sun.star.awt.FontSlant",
                                         "ITALIC" if (ital and i == 2) else "NONE")
        except Exception as e:
            print("toc format:", e)
    return leader


# ---------------------------------------------------------------- previews
def _print_preview(state, entries):
    def draw(cr, W, H):
        cr.set_source_rgb(1, 1, 1)
        cr.paint()
        cr.select_font_face("Sans")
        y = 18
        for lvl, text, page in entries:
            if lvl > state["levels"]():
                continue
            size = 11 - lvl if lvl else 10
            cr.set_font_size(size)
            bold = state["format"]() in FORMAT_STYLE and FORMAT_STYLE[state["format"]()][0] \
                and lvl == 1
            cr.select_font_face("Sans", 0, 1 if bold else 0)
            x = 8 + 12 * max(0, lvl - 1)
            t = text.upper() if (lvl == 1 and state["format"]() in FORMAT_STYLE and
                                 FORMAT_STYLE[state["format"]()][1]) else text
            cr.set_source_rgb(0.1, 0.1, 0.1)
            cr.move_to(x, y)
            cr.show_text(t)
            tx = x + cr.text_extents(t).x_advance
            if state["pages"]():
                ps = str(page)
                pw = cr.text_extents(ps).x_advance
                if state["right"]():
                    px = W - 10 - pw
                    lead = state["leader"]()
                    if lead:
                        lw = cr.text_extents(lead).x_advance or 3
                        lx = tx + 4
                        while lx + lw < px - 3:
                            cr.move_to(lx, y)
                            cr.show_text(lead)
                            lx += lw
                else:
                    px = tx + 4
                cr.move_to(px, y)
                cr.show_text(ps)
            y += size + 9
    return draw


def _web_preview(state, entries):
    def draw(cr, W, H):
        cr.set_source_rgb(1, 1, 1)
        cr.paint()
        cr.select_font_face("Sans")
        y = 18
        for lvl, text, _page in entries:
            if lvl > state["levels"]():
                continue
            size = 11 - lvl if lvl else 10
            cr.set_font_size(size)
            x = 8 + 12 * max(0, lvl - 1)
            if state["links"]():
                cr.set_source_rgb(0.02, 0.39, 0.76)
            else:
                cr.set_source_rgb(0.1, 0.1, 0.1)
            cr.move_to(x, y)
            cr.show_text(text)
            if state["links"]():
                w = cr.text_extents(text).x_advance
                cr.rectangle(x, y + 1.5, w, 0.8)
                cr.fill()
            y += size + 9
    return draw


def _previews(state, entries, web=True):
    hb = Gtk.Box(spacing=12)
    out = []
    for title, fn in (("Print Pre_view", _print_preview),) + \
            ((("_Web Preview", _web_preview),) if web else ()):
        vb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        lab = Gtk.Label(label=title, xalign=0, use_underline=True)
        vb.pack_start(lab, False, False, 0)
        p = Preview(fn(state, entries), 230, 130)
        fr = Gtk.Frame()
        fr.add(p)
        vb.pack_start(fr, False, False, 0)
        hb.pack_start(vb, True, True, 0)
        out.append(p)
    return hb, out


def _common_controls(show_pages, right, leader, links, web=True):
    pages = Gtk.CheckButton.new_with_mnemonic("_Show page numbers")
    pages.set_active(show_pages)
    ralign = Gtk.CheckButton.new_with_mnemonic("_Right align page numbers")
    ralign.set_active(right)
    lead = combo([n for n, _c in LEADERS],
                 next((i for i, (_n, c) in enumerate(LEADERS) if c == leader), 1))
    hl = Gtk.CheckButton.new_with_mnemonic("_Use hyperlinks instead of page numbers")
    hl.set_active(links)
    return pages, ralign, lead, hl


def _wire(widgets, previews, pages, ralign, lead):
    def refresh(*_):
        ralign.set_sensitive(pages.get_active())
        lead.set_sensitive(pages.get_active() and ralign.get_active())
        for p in previews:
            p.queue_draw()
    for w in widgets:
        sig = "toggled" if isinstance(w, Gtk.ToggleButton) else \
            "value-changed" if isinstance(w, Gtk.SpinButton) else "changed"
        w.connect(sig, refresh)
    refresh()


def _modify_styles(win, names):
    """The Style list of the original's Modify button."""
    d = FDialog(win, "Style", buttons=(("OK", Gtk.ResponseType.OK),
                                       ("Cancel", Gtk.ResponseType.CANCEL)))
    lb = Gtk.ListBox()
    for n in names:
        lb.add(Gtk.Label(label=n, xalign=0, margin=3))
    lb.select_row(lb.get_row_at_index(0))
    sw = Gtk.ScrolledWindow()
    sw.set_size_request(240, 180)
    sw.add(lb)
    hb = Gtk.Box(spacing=8)
    hb.pack_start(sw, True, True, 0)
    mod = Gtk.Button(label="_Modify...", use_underline=True)
    mod.set_valign(Gtk.Align.START)
    hb.pack_start(mod, False, False, 0)
    d.add(Gtk.Label(label="Styles:", xalign=0))
    d.add(hb)

    def go(*_):
        row = lb.get_selected_row()
        if row is not None:
            win.dialogs.modify_style(row.get_child().get_text())
    mod.connect("clicked", go)
    lb.connect("row-activated", go)
    d.ask()
    d.destroy()


def _sample_headings(m=None):
    return [(1, "Heading 1", 1), (2, "Heading 2", 3), (3, "Heading 3", 5)]


# ================================================================ TOC
def toc_dialog(win, existing=None):
    m = win.engine.model
    if m is None:
        return
    if existing is None:
        cur = docapi.tocs(m)
        existing = cur[0] if cur else None
    show, right, leader, links = read_level_format(existing) if existing is not None \
        else (True, True, ".", True)
    d = FDialog(win, "Table of Contents")
    nb = Gtk.Notebook()
    page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    page.set_border_width(10)
    pages, ralign, lead, hl = _common_controls(show, right, leader, links)
    fmt = combo(FORMATS, 0)
    levels = Gtk.SpinButton.new_with_range(1, 9, 1)
    levels.set_value(existing.Level if existing is not None else 3)
    state = {"levels": lambda: int(levels.get_value()), "pages": pages.get_active,
             "right": ralign.get_active, "leader": lambda: LEADERS[max(0, lead.get_active())][1],
             "links": hl.get_active, "format": lambda: fmt.get_active_text() or ""}
    pv, previews = _previews(state, _sample_headings(m))
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
    nb.append_page(page, Gtk.Label(label="Table of Contents"))
    d.add(nb)
    opts = {"outline": existing.CreateFromOutline if existing is not None else True,
            "marks": existing.CreateFromMarks if existing is not None else False,
            "styles": None}
    _wire([pages, ralign, lead, hl, fmt, levels], previews, pages, ralign, lead)
    fmt.connect("changed", lambda *_: mod.set_sensitive(fmt.get_active() == 0))
    opt.connect("clicked", lambda *_: _toc_options(win, m, opts, existing))
    mod.connect("clicked", lambda *_: _modify_styles(win, ["TOC %d" % i for i in range(1, 10)]))
    d.show_all()
    if d.ask() == Gtk.ResponseType.OK:
        um = m.getUndoManager()
        um.enterUndoContext("Table of Contents")
        try:
            idx = existing
            if idx is None:
                idx = m.createInstance("com.sun.star.text.ContentIndex")
                idx.Title = "Contents"
                vc = docapi.view_cursor(m)
                vc.getText().insertTextContent(vc, idx, False)
            idx.Level = int(levels.get_value())
            idx.CreateFromOutline = opts["outline"]
            idx.CreateFromMarks = opts["marks"]
            if opts["styles"] is not None:
                _set_level_styles(idx, opts["styles"])
            ld = LEADERS[max(0, lead.get_active())][1]
            new_ld = _style_format(m, "Contents", fmt.get_active_text(), 9)
            if new_ld is not None and fmt.get_active() > 0:
                ld = new_ld or ld
            set_level_format(idx, 1, level_tokens(pages.get_active(), ralign.get_active(),
                                                  ld, hl.get_active(), True))
            idx.update()
        finally:
            um.leaveUndoContext()
    d.destroy()
    win.focus_document()


def _set_level_styles(idx, styles):
    """styles: {engine style name: level}."""
    idx.CreateFromLevelParagraphStyles = bool(styles)
    lps = idx.LevelParagraphStyles
    per = {i: [] for i in range(1, 11)}
    for name, lvl in styles.items():
        if 1 <= lvl <= 10:
            per[lvl].append(name)
    for i in range(1, min(11, lps.getCount())):
        uno.invoke(lps, "replaceByIndex", (i, uno.Any("[]string", tuple(per[i]))))
    idx.LevelParagraphStyles = lps


def _toc_options(win, m, opts, existing):
    from .actions import FROM_ENGINE
    d = FDialog(win, "Table of Contents Options")
    d.add(Gtk.Label(label="Build table of contents from:", xalign=0))
    use_styles = Gtk.CheckButton.new_with_mnemonic("_Styles")
    d.add(use_styles)
    store = Gtk.ListStore(str, str, str)     # word name, engine name, level text
    current = {}
    if existing is not None:
        try:
            lps = existing.LevelParagraphStyles
            for i in range(1, lps.getCount()):
                for n in lps.getByIndex(i):
                    current[n] = i
        except Exception:
            pass
        use_styles.set_active(bool(existing.CreateFromLevelParagraphStyles))
    ps = m.getStyleFamilies().getByName("ParagraphStyles")
    for n in sorted(ps.getElementNames(), key=lambda x: FROM_ENGINE.get(x, x).lower()):
        st = ps.getByName(n)
        if not st.isInUse() and n not in current and not n.startswith("Heading"):
            continue
        lvl = current.get(n)
        if lvl is None and n.startswith("Heading ") and n[8:].isdigit() and \
                not existing and int(n[8:]) <= 3:
            lvl = None
        store.append([FROM_ENGINE.get(n, n), n, str(lvl) if lvl else ""])
    tv = Gtk.TreeView(model=store)
    tv.append_column(Gtk.TreeViewColumn("Available styles:", Gtk.CellRendererText(), text=0))
    cell = Gtk.CellRendererText(editable=True)

    def edited(_c, path, text):
        text = text.strip()
        store[path][2] = text if text.isdigit() and 1 <= int(text) <= 9 else ""
        use_styles.set_active(True)
    cell.connect("edited", edited)
    tv.append_column(Gtk.TreeViewColumn("TOC level:", cell, text=2))
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
    d.get_action_area().reorder_child(reset, 0)
    while True:
        r = d.ask()
        if r == 1:
            for row in store:
                row[2] = ""
            outline.set_active(True)
            marks.set_active(False)
            use_styles.set_active(False)
            continue
        break
    if r == Gtk.ResponseType.OK:
        opts["outline"] = outline.get_active()
        opts["marks"] = marks.get_active()
        opts["styles"] = {row[1]: int(row[2]) for row in store if row[2]} \
            if use_styles.get_active() else {}
    d.destroy()


# ================================================================ figures
def figures_dialog(win, labels):
    m = win.engine.model
    if m is None:
        return
    existing = None
    ix = m.getDocumentIndexes()
    for i in range(ix.getCount()):
        x = ix.getByIndex(i)
        if x.supportsService("com.sun.star.text.IllustrationsIndex"):
            existing = x
            break
    show, right, leader, links = read_level_format(existing) if existing is not None \
        else (True, True, ".", True)
    d = FDialog(win, "Table of Figures")
    page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    page.set_border_width(10)
    pages, ralign, lead, hl = _common_controls(show, right, leader, links)
    fmt = combo(FORMATS, 0)
    label = combo(labels + ["(none)"], existing.LabelCategory if existing is not None and
                  existing.LabelCategory in labels else "Figure")
    incl = Gtk.CheckButton.new_with_mnemonic("Include label and _number")
    incl.set_active(existing is None or existing.LabelDisplayType != 6)
    state = {"levels": lambda: 1, "pages": pages.get_active, "right": ralign.get_active,
             "leader": lambda: LEADERS[max(0, lead.get_active())][1], "links": hl.get_active,
             "format": lambda: fmt.get_active_text() or ""}

    def entries():
        lab = label.get_active_text() or "Figure"
        pre = (lab + " %d: ") if incl.get_active() and lab != "(none)" else ""
        return [(1, (pre % i if pre else "") + t, p) for i, (t, p) in
                enumerate((("Text", 1), ("Text", 3), ("Text", 5), ("Text", 7)), 1)]
    ent = entries()
    pv, previews = _previews(state, ent)

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
    page.pack_start(grid([["For_mats:", fmt], ["Caption _label:", label], [incl, None]]),
                    False, False, 0)
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
    opts = {"style": None}
    _wire([pages, ralign, lead, hl, fmt], previews, pages, ralign, lead)
    label.connect("changed", regen)
    incl.connect("toggled", regen)
    fmt.connect("changed", lambda *_: mod.set_sensitive(fmt.get_active() == 0))
    opt.connect("clicked", lambda *_: _tof_options(win, m, opts))
    mod.connect("clicked", lambda *_: _modify_styles(win, ["Table of Figures"]))
    d.show_all()
    ok = d.ask() == Gtk.ResponseType.OK
    lab = label.get_active_text() or "Figure"
    d.destroy()
    if not ok:
        return
    if lab != "(none)" and not opts["style"] and not docapi.references(m).get(lab):
        win.dialogs.message("No table of figures entries found.")
    um = m.getUndoManager()
    um.enterUndoContext("Table of Figures")
    try:
        idx = existing
        if idx is None:
            idx = m.createInstance("com.sun.star.text.IllustrationsIndex")
            idx.Title = ""
            vc = docapi.view_cursor(m)
            vc.getText().insertTextContent(vc, idx, False)
        if opts["style"]:
            idx.CreateFromLabels = False
            try:
                idx.CreateFromParagraphStyle = opts["style"]
            except Exception as e:
                print("tof style:", e)
        else:
            idx.CreateFromLabels = True
            if lab != "(none)":
                idx.LabelCategory = lab
        idx.LabelDisplayType = 2 if incl.get_active() else 6
        set_level_format(idx, 1, level_tokens(pages.get_active(), ralign.get_active(),
                                              LEADERS[max(0, lead.get_active())][1],
                                              hl.get_active(), False))
        idx.update()
    finally:
        um.leaveUndoContext()
    win.focus_document()


def _tof_options(win, m, opts):
    from .actions import FROM_ENGINE, engine_style
    d = FDialog(win, "Table of Figures Options")
    d.add(heading("Build table of figures from"))
    use = Gtk.CheckButton.new_with_mnemonic("_Style:")
    ps = m.getStyleFamilies().getByName("ParagraphStyles")
    names = sorted({FROM_ENGINE.get(n, n) for n in ps.getElementNames()}, key=str.lower)
    st = combo(names, FROM_ENGINE.get(opts["style"] or "Caption", "Caption"))
    use.set_active(bool(opts["style"]))
    d.add(grid([[use, st]]))
    d.show_all()
    if d.ask() == Gtk.ResponseType.OK:
        opts["style"] = engine_style(st.get_active_text()) if use.get_active() else None
    d.destroy()


# ================================================================ index
def index_dialog(win):
    m = win.engine.model
    if m is None:
        return
    existing = None
    ix = m.getDocumentIndexes()
    for i in range(ix.getCount()):
        x = ix.getByIndex(i)
        if x.supportsService("com.sun.star.text.DocumentIndex"):
            existing = x
            break
    show, right, leader, _links = read_level_format(existing, 1) if existing is not None \
        else (True, False, ".", False)
    d = FDialog(win, "Index")
    page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    page.set_border_width(10)
    indented = Gtk.RadioButton.new_with_mnemonic(None, "In_dented")
    runin = Gtk.RadioButton.new_with_mnemonic_from_widget(indented, "Ru_n-in")
    if existing is not None and getattr(existing, "IsCommaSeparated", False):
        runin.set_active(True)
    cols = Gtk.SpinButton.new_with_range(1, 4, 1)
    try:
        cols.set_value(existing.TextColumns.getColumnCount() if existing is not None else 2)
    except Exception:
        cols.set_value(2)
    langs = [n for n, _l, _c in docapi.LANGUAGES]
    lang = combo(langs, 0)
    ralign = Gtk.CheckButton.new_with_mnemonic("_Right align page numbers")
    ralign.set_active(right)
    lead = combo([n for n, _c in LEADERS],
                 next((i for i, (_n, c) in enumerate(LEADERS) if c == leader), 1))
    fmt = combo(FORMATS, 0)

    state = {"cols": lambda: int(cols.get_value())}

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
        x0, y = 6, 16
        col = 0
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
                    ld = LEADERS[max(0, lead.get_active())][1]
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
    lab = Gtk.Label(label="Print Pre_view", xalign=0, use_underline=True)
    page.pack_start(lab, False, False, 0)
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
    fmt.connect("changed", lambda *_: mod.set_sensitive(fmt.get_active() == 0))
    mark.connect("clicked", lambda *_: (d.response(Gtk.ResponseType.CANCEL),
                                        win.dialogs.mark_entry()))
    concord = {"url": getattr(existing, "AutoMarkFileURL", "") if existing is not None else ""}

    def pick_auto(*_):
        fc = Gtk.FileChooserDialog(title="Open Index AutoMark File", transient_for=d,
                                   action=Gtk.FileChooserAction.OPEN)
        fc.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Open", Gtk.ResponseType.OK)
        if fc.run() == Gtk.ResponseType.OK:
            concord["url"] = fc.get_uri()
        fc.destroy()
    auto.connect("clicked", pick_auto)
    mod.connect("clicked", lambda *_: _modify_styles(
        win, ["Index %d" % i for i in range(1, 4)] + ["Index Heading"]))
    d.show_all()
    if d.ask() == Gtk.ResponseType.OK:
        um = m.getUndoManager()
        um.enterUndoContext("Index")
        try:
            idx = existing
            if idx is None:
                idx = m.createInstance("com.sun.star.text.DocumentIndex")
                idx.Title = ""
                vc = docapi.view_cursor(m)
                vc.getText().insertTextContent(vc, idx, False)
            idx.UseAlphabeticalSeparators = fmt.get_active_text() in (
                "Classic", "Fancy", "Modern", "Formal")
            try:
                idx.IsCommaSeparated = runin.get_active()
            except Exception:
                pass
            idx.TextColumns = docapi._text_columns(m, int(cols.get_value()), 500)
            name, l, c = docapi.LANGUAGES[max(0, lang.get_active())]
            try:
                idx.Locale = bridge.struct("com.sun.star.lang.Locale", Language=l, Country=c)
            except Exception:
                pass
            if concord["url"]:
                try:
                    idx.AutoMarkFileURL = concord["url"]
                    idx.UseKeyAsEntry = False
                except Exception:
                    pass
            _style_format(m, "Index", fmt.get_active_text(), 3)
            set_level_format(idx, 1, level_tokens(True, ralign.get_active(),
                                                  LEADERS[max(0, lead.get_active())][1],
                                                  False, False, ", "))
            idx.update()
        finally:
            um.leaveUndoContext()
    d.destroy()
    win.focus_document()
