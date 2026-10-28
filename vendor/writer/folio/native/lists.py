"""List commands with the new engine: Restart at 1, Continue Numbering, Set Numbering Value,
Adjust List Indents and the Multilevel List gallery (as w:abstractNum definitions)."""
from gi.repository import Gtk

TW_PER_MM100 = 1440.0 / 2540.0
# the classic module's numbering types -> w:numFmt
FMT = {4: "decimal", 0: "upperLetter", 1: "lowerLetter", 2: "upperRoman", 3: "lowerRoman", 6: "bullet", 5: "none"}


def _ed(win):
    return win.engine.ed


def in_list(win):
    return _ed(win).list_info() is not None


def in_numbered_list(win):
    i = _ed(win).list_info()
    return i is not None and not i[2]


def _done(win):
    win.engine.view.after_edit()


def restart_at(win, value=1):
    if _ed(win).restart_numbering(int(value)):
        _done(win)


def continue_numbering(win):
    if _ed(win).continue_numbering():
        _done(win)
    else:
        win.status.flash("There's no numbered list before this one to continue.")


def set_numbering_value(win):
    ed = _ed(win)
    info = ed.list_info()
    if info is None:
        return
    import re
    m = re.search(r"\d+", info[3] or "")
    cur = int(m.group(0)) if m else info[4]
    from ..widgets import FDialog
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
    d.widgets = (new, cont, adv, spin)
    if d.ask() == Gtk.ResponseType.OK:
        apply_numbering_value(win, new.get_active(), adv.get_active(), int(spin.get_value()))
    d.destroy()
    win.focus_document()


def apply_numbering_value(win, start_new, advance, value):
    ed = _ed(win)
    ed.begin_group("Set Numbering Value")
    sel = ed.selection_range() if ed.has_selection() else None
    if sel is not None:
        # the selection's first paragraph takes the value
        ed.select_nodes(sel[0], sel[1], sel[0], sel[1])
    try:
        if start_new:
            ed.restart_numbering(value)
        else:
            ed.continue_numbering()
            if advance:
                ed.restart_numbering(value)
    finally:
        if sel is not None:
            ed.select_nodes(*sel)
        ed.end_group()
    _done(win)


def adjust_indents(win):
    ed = _ed(win)
    cur = ed.list_level_indents()
    if cur is None:
        return
    number_at, text_at, suff = cur
    from ..widgets import FDialog, LengthSpin, combo, grid
    mm = lambda tw: int(round(tw / TW_PER_MM100))  # noqa: E731
    d = FDialog(win, "Adjust List Indents")
    num_pos = LengthSpin(mm(number_at), 0, 55880)
    text_ind = LengthSpin(mm(text_at), 0, 55880)
    fol = combo(["Tab character", "Space", "Nothing"], {"tab": 0, "space": 1, "nothing": 2}.get(suff, 0))
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    box.set_border_width(10)
    box.pack_start(grid([["_Number position:", num_pos], ["_Text indent:", text_ind],
                         ["Follow number _with:", fol]]), False, False, 0)
    d.add(box)
    d.show_all()
    if d.ask() == Gtk.ResponseType.OK:
        tw = lambda v: int(round(v * TW_PER_MM100))  # noqa: E731
        if ed.set_list_level_indents(tw(num_pos.mm100), tw(text_ind.mm100), ("tab", "space", "nothing")[max(0, fol.get_active())]):
            _done(win)
    d.destroy()
    win.focus_document()


def _lvl_text(fmt):
    """The classic module's '%1%.%2%' -> Word's '%1.%2'."""
    import re
    return re.sub(r"%(\d)%", r"%\1", fmt)


def levels_xml(levels):
    out = ['<w:multiLevelType w:val="multilevel"/>']
    tw = lambda mm: int(round(mm * TW_PER_MM100))  # noqa: E731
    for k, spec in enumerate(levels):
        i = spec.get("n", k)
        if "indent" in spec:
            left = tw(spec["indent"])
            hang = max(0, left - tw(spec.get("pos", 0)))
        else:
            left, hang = 360 * (i + 1), 360
        start = int(spec.get("start", 1))
        suff = {1: '<w:suff w:val="space"/>', 2: '<w:suff w:val="nothing"/>'}.get(spec.get("follow", 0), "")
        if spec["kind"] == 6:
            ch = spec.get("char") or "•"
            font = spec.get("font") or "Symbol"
            if font == "OpenSymbol":
                font = "Arial"
            out.append('<w:lvl w:ilvl="%d"><w:start w:val="%d"/><w:numFmt w:val="bullet"/>%s<w:lvlText w:val="%s"/>'
                       '<w:lvlJc w:val="left"/><w:pPr><w:ind w:left="%d" w:hanging="%d"/></w:pPr>'
                       '<w:rPr><w:rFonts w:ascii="%s" w:hAnsi="%s" w:hint="default"/></w:rPr></w:lvl>'
                       % (i, start, suff, ch, left, hang, font, font))
        else:
            out.append('<w:lvl w:ilvl="%d"><w:start w:val="%d"/><w:numFmt w:val="%s"/>%s<w:lvlText w:val="%s"/>'
                       '<w:lvlJc w:val="left"/><w:pPr><w:ind w:left="%d" w:hanging="%d"/></w:pPr></w:lvl>'
                       % (i, start, FMT.get(spec["kind"], "decimal"), suff, _lvl_text(spec["fmt"]), left, hang))
    return "".join(out)


def apply_multilevel(win, levels):
    if _ed(win).apply_list_definition(levels_xml(levels)):
        _done(win)


def heading_numbering(win, chapter=False):
    """1 Heading 1, 1.1 Heading 2... (or Chapter 1): a list linked to the Heading styles."""
    ed = _ed(win)
    ids = {name: sid for sid, name in ed.paragraph_styles()}
    out = ['<w:multiLevelType w:val="multilevel"/>']
    for i in range(9):
        first = chapter and i == 0
        text = "Chapter %1" if first else ".".join("%%%d" % (k + 1) for k in range(i + 1))
        sid = ids.get("Heading %d" % (i + 1))
        ps = '<w:pStyle w:val="%s"/>' % sid if sid else ""
        out.append('<w:lvl w:ilvl="%d"><w:start w:val="1"/><w:numFmt w:val="decimal"/>%s%s<w:lvlText w:val="%s"/>'
                   '<w:lvlJc w:val="left"/><w:pPr><w:ind w:left="%d" w:hanging="%d"/></w:pPr></w:lvl>'
                   % (i, ps, '<w:suff w:val="space"/>' if first else "", text, 432 + 144 * i, 432 + 144 * i))
    ed.begin_group("Heading Numbering")
    try:
        nid = ed.new_list_definition("".join(out))
        for i in range(9):
            sid = ids.get("Heading %d" % (i + 1))
            if sid and nid:
                ed.style_set_num(sid, nid, i)
    finally:
        ed.end_group()
    _done(win)
