"""Lists, as in the original: the numbered-list commands of the right-click
menu (Restart at 1, Continue Numbering, Set Numbering Value, Adjust List
Indents) and the Multilevel List gallery."""
from gi.repository import Gtk

from . import bridge, docapi

ARABIC, UPPER, LOWER, ROMAN_UP, ROMAN_LOW, BULLET, NONE = 4, 0, 1, 2, 3, 6, 5
LISTTAB, SPACE, NOTHING = 0, 1, 2
INDENT = 635          # 0.25" per level (1/100 mm)


# ---------------------------------------------------------------- helpers
def _para_cursor(m):
    vc = docapi.view_cursor(m)
    c = vc.getText().createTextCursorByRange(vc.getStart())
    c.gotoStartOfParagraph(False)
    c.gotoEndOfParagraph(True)
    return vc, c


def _paragraph(m):
    _vc, c = _para_cursor(m)
    en = c.createEnumeration()
    return en.nextElement() if en.hasMoreElements() else None


def _native(m):
    eng = getattr(m, "eng", None)
    return eng is not None and getattr(eng, "native", False)


def _nwin(m):
    return m.eng.win


def in_numbered_list(m):
    if _native(m):
        i = m.eng.ed.list_info()
        return i is not None and not i[2]
    try:
        p = _paragraph(m)
        return p is not None and bool(getattr(p, "NumberingIsNumber", False)) and \
            bool(p.NumberingStyleName or p.NumberingRules is not None) and \
            _level_type(p) not in (BULLET, NONE)
    except Exception:
        return False


def in_list(m):
    if _native(m):
        return m.eng.ed.list_info() is not None
    try:
        p = _paragraph(m)
        return p is not None and bool(getattr(p, "NumberingIsNumber", False))
    except Exception:
        return False


def _level_props(p):
    rules = p.NumberingRules
    lvl = p.NumberingLevel or 0
    return {x.Name: x.Value for x in rules.getByIndex(lvl)}, rules, lvl


def _level_type(p):
    try:
        return _level_props(p)[0].get("NumberingType", ARABIC)
    except Exception:
        return ARABIC


def _list_paragraphs(m, p):
    """Every paragraph of p's list, in document order."""
    lid = p.ListId
    out = []
    en = m.getText().createEnumeration()
    while en.hasMoreElements():
        q = en.nextElement()
        try:
            if q.supportsService("com.sun.star.text.Paragraph") and \
                    getattr(q, "NumberingIsNumber", False) and q.ListId == lid:
                out.append(q)
        except Exception:
            pass
    return out


def _undo(m, title, fn):
    um = m.getUndoManager()
    um.enterUndoContext(title)
    try:
        return fn()
    finally:
        um.leaveUndoContext()


# ---------------------------------------------------------------- numbering value
def restart_at(m, value=1):
    if _native(m):
        from .native import lists as NL
        return NL.restart_at(_nwin(m), value)

    def go():
        p = _paragraph(m)
        p.ParaIsNumberingRestart = True
        p.NumberingStartValue = int(value)
    _undo(m, "Restart Numbering", go)


def continue_numbering(m):
    """Join this list onto the previous list (of the same kind)."""
    if _native(m):
        from .native import lists as NL
        return NL.continue_numbering(_nwin(m))
    def go():
        p = _paragraph(m)
        prev = None
        en = m.getText().createEnumeration()
        lid = p.ListId
        while en.hasMoreElements():
            q = en.nextElement()
            if not q.supportsService("com.sun.star.text.Paragraph"):
                continue
            if m.getText().compareRegionStarts(q.getStart(), p.getStart()) == 0:
                break
            if getattr(q, "NumberingIsNumber", False) and q.ListId != lid and \
                    _level_type(q) not in (BULLET, NONE):
                prev = q
        p.ParaIsNumberingRestart = False
        try:
            p.setPropertyToDefault("NumberingStartValue")
        except Exception:
            pass
        if prev is None:
            return False
        rules = prev.NumberingRules
        # this paragraph and the rest of its list follow on from prev
        tail, on = [], False
        for q in _list_paragraphs(m, p):
            if m.getText().compareRegionStarts(q.getStart(), p.getStart()) == 0:
                on = True
            if on:
                tail.append(q)
        for q in tail:
            lvl = q.NumberingLevel
            if prev.NumberingStyleName:
                q.NumberingStyleName = prev.NumberingStyleName
            else:
                q.NumberingRules = rules
            q.ListId = prev.ListId
            q.NumberingLevel = lvl
        return True
    return _undo(m, "Continue Numbering", go)


def set_numbering_value(win):
    if getattr(win.engine, "native", False):
        from .native import lists as NL
        return NL.set_numbering_value(win)
    m = win.engine.model
    if m is None or not in_list(m):
        return
    p = _paragraph(m)
    props, _r, _l = _level_props(p)
    cur = 1
    try:
        cur = p.NumberingStartValue if p.ParaIsNumberingRestart and \
            p.NumberingStartValue > 0 else int(props.get("StartWith", 1))
    except Exception:
        pass
    from .widgets import FDialog
    d = FDialog(win, "Set Numbering Value")
    new = Gtk.RadioButton.new_with_mnemonic(None, "_Start new list")
    cont = Gtk.RadioButton.new_with_mnemonic_from_widget(new, "_Continue from previous list")
    adv = Gtk.CheckButton.new_with_mnemonic("_Advance value (skip numbers)")
    adv.set_sensitive(False)
    new.set_active(True)
    spin = Gtk.SpinButton.new_with_range(0, 9999, 1)
    spin.set_value(cur)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    box.set_border_width(10)
    for w in (new, cont):
        box.pack_start(w, False, False, 0)
    adv.set_margin_start(20)
    box.pack_start(adv, False, False, 0)
    row = Gtk.Box(spacing=8)
    lab = Gtk.Label.new_with_mnemonic("Set _value to:")
    lab.set_mnemonic_widget(spin)
    row.pack_start(lab, False, False, 0)
    row.pack_start(spin, False, False, 0)
    box.pack_start(row, False, False, 0)
    cont.connect("toggled", lambda b: adv.set_sensitive(b.get_active()))
    d.add(box)
    d.show_all()
    if d.ask() == Gtk.ResponseType.OK:
        if new.get_active():
            restart_at(m, int(spin.get_value()))
        else:
            continue_numbering(m)
            if adv.get_active():
                restart_at(m, int(spin.get_value()))
    d.destroy()
    win.focus_document()


# ---------------------------------------------------------------- indents
def _set_level(p, rules, lvl, changes):
    out = []
    for x in rules.getByIndex(lvl):
        if x.Name in changes:
            x = bridge.prop(x.Name, changes.pop(x.Name))
        out.append(x)
    for k, v in changes.items():
        out.append(bridge.prop(k, v))
    import uno
    uno.invoke(rules, "replaceByIndex",
               (lvl, uno.Any("[]com.sun.star.beans.PropertyValue", tuple(out))))


def adjust_indents(win):
    if getattr(win.engine, "native", False):
        from .native import lists as NL
        return NL.adjust_indents(win)
    m = win.engine.model
    if m is None or not in_list(m):
        return
    p = _paragraph(m)
    props, rules, lvl = _level_props(p)
    indent_at = props.get("IndentAt", 1270)
    first = props.get("FirstLineIndent", -635)
    follow = props.get("LabelFollowedBy", LISTTAB)
    tabpos = props.get("ListtabStopPosition", indent_at)
    from .widgets import FDialog
    from .widgets import LengthSpin, grid, combo
    d = FDialog(win, "Adjust List Indents")
    num_pos = LengthSpin(indent_at + first, 0, 55880)
    text_ind = LengthSpin(indent_at, 0, 55880)
    fol = combo(["Tab character", "Space", "Nothing"], follow)
    addtab = Gtk.CheckButton.new_with_mnemonic("Add tab _stop at:")
    addtab.set_active(follow == LISTTAB and abs(tabpos - indent_at) > 5)
    tab = LengthSpin(tabpos, 0, 55880)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    box.set_border_width(10)
    box.pack_start(grid([["_Number position:", num_pos], ["_Text indent:", text_ind],
                         ["Follow number _with:", fol], [addtab, tab]]), False, False, 0)

    def sens(*_):
        addtab.set_sensitive(fol.get_active() == LISTTAB)
        tab.set_sensitive(fol.get_active() == LISTTAB and addtab.get_active())
    fol.connect("changed", sens)
    addtab.connect("toggled", sens)
    sens()
    d.add(box)
    d.show_all()
    if d.ask() == Gtk.ResponseType.OK:
        ia = text_ind.mm100
        fl = num_pos.mm100 - ia
        fb = fol.get_active()
        ts = tab.mm100 if (fb == LISTTAB and addtab.get_active()) else ia

        def go():
            for q in _list_paragraphs(m, p) or [p]:
                if q.NumberingLevel != lvl:
                    continue
                r = q.NumberingRules
                _set_level(q, r, lvl, {"PositionAndSpaceMode": 1, "IndentAt": ia,
                                       "FirstLineIndent": fl, "LabelFollowedBy": fb,
                                       "ListtabStopPosition": ts})
                q.NumberingRules = r
                break          # the rules are shared by the list
        _undo(m, "Adjust List Indents", go)
    d.destroy()
    win.focus_document()


# ---------------------------------------------------------------- multilevel
def _lvl(kind, fmt, n, char=None, font=None):
    return {"kind": kind, "fmt": fmt, "char": char, "font": font, "n": n}


def _numbered(fmts):
    out = []
    for i in range(9):
        kind, fmt = fmts[i % len(fmts)]
        out.append(_lvl(kind, fmt.replace("#", "%%%d%%" % (i + 1)), i))
    return out


MULTI = [
    ("1.  a.  i.", _numbered([(ARABIC, "#."), (LOWER, "#."), (ROMAN_LOW, "#.")])),
    ("1)  a)  i)", _numbered([(ARABIC, "#)"), (LOWER, "#)"), (ROMAN_LOW, "#)")])),
    ("1.  1.1.  1.1.1.",
     [_lvl(ARABIC, "".join("%%%d%%." % (k + 1) for k in range(i + 1)), i) for i in range(9)]),
    ("•  ◦  ▪", [_lvl(BULLET, "", i, char="•◦▪"[i % 3], font="OpenSymbol") for i in range(9)]),
    ("Article I.  Section 1.01  (a)",
     [_lvl(ROMAN_UP, "Article %1%.", 0), _lvl(ARABIC, "Section %1%.%2%", 1),
      _lvl(LOWER, "(%3%)", 2), _lvl(ROMAN_LOW, "(%4%)", 3)] +
     [_lvl(ARABIC, "%%%d%%)" % (i + 1), i) for i in range(4, 9)]),
    ("I.  A.  1.  a)", _numbered([(ROMAN_UP, "#."), (UPPER, "#."), (ARABIC, "#."),
                                  (LOWER, "#)"), (LOWER, "(#)"), (ROMAN_LOW, "(#)")])),
]


def _rules_for(m, levels, headings=False):
    rules = m.createInstance("com.sun.star.text.NumberingRules")
    for spec in levels:
        i = spec["n"]
        ch = {"PositionAndSpaceMode": 1,
              "IndentAt": INDENT * (i + 1),
              "FirstLineIndent": -INDENT,
              "LabelFollowedBy": LISTTAB,
              "ListtabStopPosition": INDENT * (i + 1),
              "NumberingType": spec["kind"]}
        if spec["kind"] == BULLET:
            ch.update({"BulletChar": spec["char"], "Prefix": "", "Suffix": ""})
            try:
                f = bridge.struct("com.sun.star.awt.FontDescriptor", Name=spec["font"])
                ch["BulletFont"] = f
            except Exception:
                pass
        else:
            ch["ListFormat"] = spec["fmt"]
            ch["StartWith"] = 1
            # Prefix/Suffix/ParentNumbering for engines without ListFormat
            fmt = spec["fmt"]
            pre = fmt.split("%")[0]
            suf = fmt.rsplit("%", 1)[-1]
            ch["Prefix"], ch["Suffix"] = pre, suf
            ch["ParentNumbering"] = max(1, fmt.count("%") // 2)
        _set_level(None, rules, i, ch)
    return rules


def apply_multilevel(m, levels):
    if _native(m):
        from .native import lists as NL
        return NL.apply_multilevel(_nwin(m), levels)

    def go():
        rules = _rules_for(m, levels)
        vc = docapi.view_cursor(m)
        c = vc.getText().createTextCursorByRange(vc.getStart())
        c.gotoRange(vc.getEnd(), True)
        en = c.createEnumeration()
        paras = []
        while en.hasMoreElements():
            q = en.nextElement()
            if q.supportsService("com.sun.star.text.Paragraph"):
                paras.append(q)
        for q in paras:
            lvl = q.NumberingLevel if getattr(q, "NumberingIsNumber", False) else 0
            q.NumberingStyleName = ""
            q.NumberingRules = rules
            q.NumberingLevel = max(0, lvl or 0)
        # one list for the whole selection
        if len(paras) > 1:
            lid = paras[0].ListId
            for q in paras[1:]:
                try:
                    q.ListId = lid
                except Exception:
                    pass
    _undo(m, "Multilevel List", go)


def heading_numbering(m, chapter=False):
    """Number the Heading styles: '1 Heading 1', '1.1 Heading 2' (or
    'Chapter 1')."""
    if _native(m):
        from .native import lists as NL
        return NL.heading_numbering(_nwin(m), chapter)

    def go():
        cn = m.getChapterNumberingRules()
        for i in range(9):
            first = chapter and i == 0
            fmt = "Chapter %1%" if first else ".".join("%%%d%%" % (k + 1) for k in range(i + 1))
            _set_level(None, cn, i, {
                "NumberingType": ARABIC, "ListFormat": fmt, "StartWith": 1,
                "Prefix": "Chapter " if first else "", "Suffix": "",
                "ParentNumbering": 1 if first else i + 1,
                "PositionAndSpaceMode": 1, "LabelFollowedBy": LISTTAB if not first else SPACE,
                "IndentAt": 0, "FirstLineIndent": 0,
                "ListtabStopPosition": 762 + 254 * i})
    _undo(m, "Heading Numbering", go)


def _preview(levels, W=96, H=78):
    da = Gtk.DrawingArea()
    da.set_size_request(W, H)

    def label(spec, counters):
        if spec["kind"] == BULLET:
            return spec["char"]
        s = spec["fmt"]
        for k in range(9):
            tok = "%%%d%%" % (k + 1)
            if tok in s:
                kind = levels[k]["kind"] if k < len(levels) else ARABIC
                s = s.replace(tok, _fmt_num(kind, counters[k]))
        return s

    def draw(_w, cr):
        cr.set_source_rgb(1, 1, 1)
        cr.paint()
        cr.set_source_rgb(0.2, 0.2, 0.2)
        cr.select_font_face("Sans")
        cr.set_font_size(7)
        counters = [1] * 9
        y = 12
        for i in range(3):
            x = 4 + i * 10
            t = label(levels[i], counters)
            cr.move_to(x, y)
            cr.show_text(t)
            ext = cr.text_extents(t)
            cr.set_source_rgb(0.65, 0.65, 0.65)
            cr.rectangle(x + ext.x_advance + 3, y - 4, W - x - ext.x_advance - 8, 2.5)
            cr.fill()
            cr.set_source_rgb(0.2, 0.2, 0.2)
            y += 22
        return False
    da.connect("draw", draw)
    return da


def _fmt_num(kind, n):
    if kind == UPPER:
        return chr(64 + n)
    if kind == LOWER:
        return chr(96 + n)
    if kind == ROMAN_UP:
        return ["I", "II", "III", "IV"][n - 1]
    if kind == ROMAN_LOW:
        return ["i", "ii", "iii", "iv"][n - 1]
    return str(n)


def multilevel_gallery(win):
    """The Multilevel List drop-down."""
    m = win.dialogs.model
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    box.set_border_width(6)
    pop = Gtk.Popover()

    def head(t):
        lab = Gtk.Label(xalign=0)
        lab.set_markup("<b>%s</b>" % t)
        box.pack_start(lab, False, False, 0)

    head("List Library")
    flow = Gtk.FlowBox()
    flow.set_max_children_per_line(3)
    flow.set_min_children_per_line(3)
    flow.set_selection_mode(Gtk.SelectionMode.NONE)

    def add_tile(name, fn, levels):
        b = Gtk.Button()
        b.set_tooltip_text(name)
        b.add(_preview(levels))
        b.get_style_context().add_class("folio-gallery-tile")
        b.connect("clicked", lambda *_: (pop.popdown(), fn(), win.focus_document()))
        flow.add(b)

    add_tile("None", lambda: win.actions.cmd(".uno:RemoveBullets"),
             [_lvl(NONE, "", i) for i in range(9)])
    for name, levels in MULTI:
        add_tile(name, (lambda lv=levels: apply_multilevel(win.dialogs.model, lv)), levels)
    add_tile("1 Heading 1, 1.1 Heading 2", lambda: heading_numbering(win.dialogs.model),
             [_lvl(ARABIC, ".".join("%%%d%%" % (k + 1) for k in range(i + 1)), i)
              for i in range(9)])
    add_tile("Chapter 1 Heading 1", lambda: heading_numbering(win.dialogs.model, True),
             [_lvl(ARABIC, "Ch. %1%", 0)] +
             [_lvl(ARABIC, ".".join("%%%d%%" % (k + 1) for k in range(i + 1)), i)
              for i in range(1, 9)])
    box.pack_start(flow, False, False, 0)
    box.pack_start(Gtk.Separator(), False, False, 2)

    def menu_item(label, cb, sensitive=True):
        b = Gtk.Button(label=label)
        b.set_relief(Gtk.ReliefStyle.NONE)
        b.get_child().set_xalign(0)
        b.set_sensitive(sensitive)
        b.connect("clicked", lambda *_: (pop.popdown(), cb()))
        box.pack_start(b, False, False, 0)
        return b

    listed = m is not None and in_list(m)
    lvlbtn = Gtk.MenuButton(label="Change List Level")
    lvlbtn.set_relief(Gtk.ReliefStyle.NONE)
    lvlbtn.set_sensitive(listed)
    lm = Gtk.Menu()
    for i in range(9):
        mi = Gtk.MenuItem(label="Level %d" % (i + 1))
        mi.connect("activate", lambda _m, i=i: (pop.popdown(), set_level(win.engine.model, i)))
        lm.append(mi)
    lm.show_all()
    lvlbtn.set_popup(lm)
    box.pack_start(lvlbtn, False, False, 0)
    menu_item("Define New Multilevel List...", lambda: define_dialog(win))
    box.show_all()
    pop.add(box)
    return pop


def set_level(m, lvl):
    def go():
        vc = docapi.view_cursor(m)
        c = vc.getText().createTextCursorByRange(vc.getStart())
        c.gotoRange(vc.getEnd(), True)
        en = c.createEnumeration()
        while en.hasMoreElements():
            q = en.nextElement()
            if q.supportsService("com.sun.star.text.Paragraph") and \
                    getattr(q, "NumberingIsNumber", False):
                q.NumberingLevel = lvl
    _undo(m, "Change List Level", go)


KINDS = [("1, 2, 3, ...", ARABIC), ("I, II, III, ...", ROMAN_UP), ("i, ii, iii, ...", ROMAN_LOW),
         ("A, B, C, ...", UPPER), ("a, b, c, ...", LOWER), ("Bullet", BULLET), ("(none)", NONE)]


def define_dialog(win):
    """Define New Multilevel List: each level's number style, format and
    position."""
    native = getattr(win.engine, "native", False)
    m = None if native else win.engine.model
    if m is None and not native:
        return
    from .widgets import FDialog
    from .widgets import LengthSpin, grid, combo
    levels = [dict(x) for x in MULTI[0][1]]
    for i, x in enumerate(levels):
        x["pos"] = INDENT * i
        x["indent"] = INDENT * (i + 1)
    d = FDialog(win, "Define New Multilevel List")
    hb = Gtk.Box(spacing=10)
    hb.set_border_width(10)
    lvlist = Gtk.ListBox()
    for i in range(9):
        lvlist.add(Gtk.Label(label=str(i + 1), xalign=0.5))
    hb.pack_start(lvlist, False, False, 0)
    right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    fmt = Gtk.Entry()
    kind = combo([k for k, _v in KINDS], 0)
    start = Gtk.SpinButton.new_with_range(0, 999, 1)
    start.set_value(1)
    pos = LengthSpin(0, 0, 55880)
    ind = LengthSpin(INDENT, 0, 55880)
    fol = combo(["Tab character", "Space", "Nothing"], 0)
    right.pack_start(grid([["Enter _formatting for number:", fmt],
                           ["_Number style for this level:", kind],
                           ["_Start at:", start],
                           ["_Aligned at:", pos], ["_Text indent at:", ind],
                           ["Follow number _with:", fol]]), False, False, 0)
    hint = Gtk.Label(label="Use %1%, %2%… for the numbers of levels 1, 2…", xalign=0)
    hint.get_style_context().add_class("dim-label")
    right.pack_start(hint, False, False, 0)
    hb.pack_start(right, True, True, 0)
    d.add(hb)
    cur = [0]
    loading = [False]

    def load(i):
        loading[0] = True
        x = levels[i]
        fmt.set_text(x["fmt"] if x["kind"] != BULLET else (x.get("char") or "•"))
        kind.set_active(next((j for j, (_k, v) in enumerate(KINDS) if v == x["kind"]), 0))
        start.set_value(x.get("start", 1))
        pos.set_value(x["pos"])
        ind.set_value(x["indent"])
        fol.set_active(x.get("follow", 0))
        loading[0] = False

    def store(*_):
        if loading[0]:
            return
        x = levels[cur[0]]
        x["kind"] = KINDS[kind.get_active()][1]
        if x["kind"] == BULLET:
            x["char"] = (fmt.get_text() or "•")[:1]
            x["font"] = "OpenSymbol"
        else:
            x["fmt"] = fmt.get_text()
        x["start"] = int(start.get_value())
        x["pos"], x["indent"] = pos.mm100, ind.mm100
        x["follow"] = fol.get_active()

    for w, sig in ((fmt, "changed"), (kind, "changed"), (start, "value-changed"),
                   (pos, "value-changed"), (ind, "value-changed"), (fol, "changed")):
        w.connect(sig, store)

    def pick(_lb, row):
        if row is None:
            return
        cur[0] = row.get_index()
        load(cur[0])
    lvlist.connect("row-selected", pick)
    lvlist.select_row(lvlist.get_row_at_index(0))
    load(0)
    d.show_all()
    ok = d.ask() == Gtk.ResponseType.OK
    if ok and native:
        store()
        from .native import lists as nl
        nl.apply_multilevel(win, [dict(x, n=i) for i, x in enumerate(levels)])
    elif ok:
        store()

        def go():
            rules = m.createInstance("com.sun.star.text.NumberingRules")
            for i, x in enumerate(levels):
                ch = {"PositionAndSpaceMode": 1, "NumberingType": x["kind"],
                      "IndentAt": x["indent"], "FirstLineIndent": x["pos"] - x["indent"],
                      "ListtabStopPosition": x["indent"], "LabelFollowedBy": x.get("follow", 0),
                      "StartWith": x.get("start", 1)}
                if x["kind"] == BULLET:
                    ch["BulletChar"] = x.get("char") or "•"
                else:
                    ch["ListFormat"] = x["fmt"]
                    ch["Prefix"] = x["fmt"].split("%")[0]
                    ch["Suffix"] = x["fmt"].rsplit("%", 1)[-1]
                    ch["ParentNumbering"] = max(1, x["fmt"].count("%") // 2)
                _set_level(None, rules, i, ch)
            vc = docapi.view_cursor(m)
            c = vc.getText().createTextCursorByRange(vc.getStart())
            c.gotoRange(vc.getEnd(), True)
            en = c.createEnumeration()
            while en.hasMoreElements():
                q = en.nextElement()
                if q.supportsService("com.sun.star.text.Paragraph"):
                    lvl = q.NumberingLevel if getattr(q, "NumberingIsNumber", False) else 0
                    q.NumberingStyleName = ""
                    q.NumberingRules = rules
                    q.NumberingLevel = lvl or 0
        _undo(m, "Multilevel List", go)
    d.destroy()
    win.focus_document()
