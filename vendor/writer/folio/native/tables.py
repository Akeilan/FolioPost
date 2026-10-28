"""Table Layout and Table Design for the new engine: table styles written as
real Word table style definitions, style options, cell size, alignment,
borders and shading."""
from .. import tablestyles as TS

MM = 2540.0 / 1440.0
TOPT = {"header": ("w:firstRow", 0x20), "total": ("w:lastRow", 0x40),
        "first_col": ("w:firstColumn", 0x80), "last_col": ("w:lastColumn", 0x100),
        "banded_rows": ("w:noHBand", 0x200), "banded_cols": ("w:noVBand", 0x400)}


# ------------------------------------------------------------- style XML
def _ids(kind, accent):
    """Word's name and style id for a gallery entry."""
    names = dict((k, n) for n, k in TS.PLAIN + TS.GRID + TS.LIST)
    base = names.get(kind, "Table Grid")
    an = next((n for n, c in TS.ACCENTS if c == accent and n), "")
    name = base + (" " + an if an else "")
    sid = base.replace(" ", "") + ("-" + an.replace(" ", "") if an else "")
    return name, sid


def _border_xml(tag, b):
    if b is None:
        return '<w:%s w:val="nil"/>' % tag
    w, color = b
    sz = max(2, int(round(w * 8)))
    return '<w:%s w:val="single" w:sz="%d" w:space="0" w:color="%06X"/>' % (tag, sz, color & 0xFFFFFF)


def _rpr(s, base):
    out = ""
    if s["bold"] != base["bold"]:
        out += "<w:b/><w:bCs/>" if s["bold"] else '<w:b w:val="0"/><w:bCs w:val="0"/>'
    if s.get("caps") and not base.get("caps"):
        out += "<w:caps/>"
    if s["color"] != base["color"] and s["color"] >= 0:
        out += '<w:color w:val="%06X"/>' % s["color"]
    return "<w:rPr>%s</w:rPr>" % out if out else ""


def _tcpr(s, base, sides=("top", "left", "bottom", "right")):
    out = ""
    bd = ""
    for side in sides:
        if s[side] != base[side]:
            bd += _border_xml(side, s[side])
    if bd:
        out += "<w:tcBorders>%s</w:tcBorders>" % bd
    if s["fill"] != base["fill"]:
        if s["fill"] >= 0:
            out += '<w:shd w:val="clear" w:color="auto" w:fill="%06X"/>' % s["fill"]
        else:
            out += '<w:shd w:val="clear" w:color="auto" w:fill="auto"/>'
    return "<w:tcPr>%s</w:tcPr>" % out if out else ""


def style_xml(kind, accent):
    """(id, XML of a w:style) for a Plain/Grid/List table style, built from the
    same per-cell rules the gallery thumbnails use."""
    name, sid = _ids(kind, accent)
    R = C = 8
    none = {k: False for k in TS.DEFAULT_OPTS}
    cell = lambda opts, r, c: TS.cell(kind, accent, dict(none, **opts), r, c, R, C)  # noqa: E731
    base = cell({}, 3, 3)
    top = cell({}, 0, 3)["top"]
    bottom = cell({}, R - 1, 3)["bottom"]
    left = cell({}, 3, 0)["left"]
    right = cell({}, 3, C - 1)["right"]
    tbl_borders = "".join(_border_xml(t, b) for t, b in (
        ("top", top), ("left", left), ("bottom", bottom), ("right", right),
        ("insideH", base["top"]), ("insideV", base["left"])))
    whole_rpr = '<w:rPr><w:color w:val="%06X"/></w:rPr>' % base["color"] if base["color"] >= 0 else ""
    whole_tc = ('<w:tcPr><w:shd w:val="clear" w:color="auto" w:fill="%06X"/></w:tcPr>' % base["fill"]
                if base["fill"] >= 0 else "")
    conds = ""
    for typ, opts, r, c in (("firstRow", {"header": True}, 0, 3),
                            ("lastRow", {"total": True}, R - 1, 3),
                            ("firstCol", {"first_col": True}, 3, 0),
                            ("lastCol", {"last_col": True}, 3, C - 1),
                            ("band1Vert", {"banded_cols": True}, 3, 2),
                            ("band1Horz", {"banded_rows": True}, 2, 3)):
        s = cell(opts, r, c)
        # compare with the same cell without the option (outer edges stay)
        plain = cell({}, r, c)
        rpr = _rpr(s, plain)
        tcpr = _tcpr(s, plain)
        if rpr or tcpr:
            conds += '<w:tblStylePr w:type="%s">%s%s</w:tblStylePr>' % (typ, rpr, tcpr)
    xml = ('<w:style w:type="table" w:styleId="%s"><w:name w:val="%s"/>'
           '<w:basedOn w:val="TableNormal"/><w:uiPriority w:val="%d"/>'
           '<w:pPr><w:spacing w:after="0" w:line="240" w:lineRule="auto"/></w:pPr>%s'
           '<w:tblPr><w:tblStyleRowBandSize w:val="1"/><w:tblStyleColBandSize w:val="1"/>'
           '<w:tblBorders>%s</w:tblBorders></w:tblPr>%s%s</w:style>'
           % (sid, name, 39 if kind == "grid" else 40, whole_rpr, tbl_borders, whole_tc, conds))
    return sid, xml


# ------------------------------------------------------------- actions
def _ed(win):
    return win.engine.ed


def _done(win):
    win.engine.view.after_edit()


def apply_style(win, kind, accent):
    ed = _ed(win)
    if not ed.cell_name():
        return
    sid, xml = style_xml(kind, accent)
    ed.begin_group("Table Style")
    ed.add_style_xml(xml)
    ed.table_apply("table", [("w:tblStyle", [("w:val", sid)])], "Table Style")
    ed.end_group()
    _done(win)


def set_option(win, key):
    ed = _ed(win)
    info = ed.table_info()
    if info is None or key not in TOPT:
        return
    on = not info[key]
    info[key] = on
    bits = 0
    attrs = []
    for k, (attr, bit) in TOPT.items():
        v = info[k]
        if k.startswith("banded"):
            if not v:
                bits |= bit
            attrs.append((attr, "0" if v else "1"))
        else:
            if v:
                bits |= bit
            attrs.append((attr, "1" if v else "0"))
    ed.table_apply("table", [("w:tblLook", [("w:val", "%04X" % bits)] + attrs)], "Table Style Options")
    _done(win)


def set_row_height(win, mm100):
    _ed(win).table_apply("rows", [("w:trHeight", [("w:val", str(int(round(mm100 / MM)))),
                                                  ("w:hRule", "atLeast")])], "Row Height")
    _done(win)


def set_col_width(win, mm100):
    ed = _ed(win)
    widths = list(ed.grid_widths())
    cols = ed.selected_grid_cols()
    if not widths or cols is None:
        return
    tw = int(round(mm100 / MM))
    for i in range(cols[0], min(cols[1], len(widths))):
        widths[i] = tw
    ed.set_grid_widths(widths, "Column Width")
    _done(win)


def distribute(win, what):
    ed = _ed(win)
    if what == "cols":
        widths = list(ed.grid_widths())
        if widths:
            each = sum(widths) // len(widths)
            ed.set_grid_widths([each] * len(widths), "Distribute Columns")
    _done(win)


def autofit(win, how):
    ed = _ed(win)
    if how == "contents":
        ed.autofit_contents()
    elif how == "window":
        ed.table_apply("table", [("w:tblW", [("w:w", "5000"), ("w:type", "pct")]),
                                 ("w:tblLayout", None)], "AutoFit Window")
    elif how == "fixed":
        ed.table_apply("table", [("w:tblLayout", [("w:type", "fixed")])], "Fixed Column Width")
    _done(win)


def align_cells(win, h, v):
    ed = _ed(win)
    jc = {"left": None, "center": [("w:val", "center")], "right": [("w:val", "right")]}[h]
    va = {"top": None, "center": [("w:val", "center")], "bottom": [("w:val", "bottom")]}[v]
    ed.begin_group("Cell Alignment")
    ed.table_apply("cell_paras", [("w:jc", jc)], "Cell Alignment")
    ed.table_apply("cells", [("w:vAlign", va)], "Cell Alignment")
    ed.end_group()
    _done(win)


def repeat_header(win):
    ed = _ed(win)
    on = True
    ed.table_apply("rows", [("w:tblHeader", [] if on else None)], "Repeat Header Rows")
    _done(win)


def shading(win, color):
    ed = _ed(win)
    if color is None or color < 0:
        ed.table_apply("cells", [("w:shd", None)], "Shading")
    else:
        ed.table_apply("cells", [("w:shd", [("w:val", "clear"), ("w:color", "auto"),
                                            ("w:fill", "%06X" % (color & 0xFFFFFF))])], "Shading")
    _done(win)


def borders(win, which, width_pt=0.5, color=-1):
    """Borders menu: all, outside, inside, none, top, bottom, left, right,
    inside_h, inside_v."""
    ed = _ed(win)
    line = [("w:val", "single"), ("w:sz", str(max(2, int(round(width_pt * 8))))),
            ("w:space", "0"), ("w:color", "%06X" % color if color >= 0 else "auto")]
    nil = [("w:val", "nil")]
    all6 = ("top", "left", "bottom", "right", "insideH", "insideV")
    if which in ("all", "outside", "inside", "none"):
        on = {"all": all6, "outside": all6[:4], "inside": all6[4:], "none": ()}[which]
        ed.begin_group("Borders")
        ed.set_borders("table", [(s, line if s in on else nil) for s in all6])
        # cell borders would hide the table's: they go
        ed.table_apply("cells", [("w:tcBorders", None)], "Borders")
        ed.end_group()
    elif which in ("diag-down", "diag-up"):
        # diagonal lines across the cells: a second click takes them off
        side = "tl2br" if which == "diag-down" else "tr2bl"
        ed.set_borders("cells", [(side, nil if ed.cell_border_on(side) else line)])
    else:
        side = {"inside_h": "insideH", "inside_v": "insideV"}.get(which, which)
        ed.set_borders("cells", [(side, line)])
    _done(win)


def borders_menu(win, which):
    """Borders drop-down: the selected cells in a table, else paragraphs."""
    ed = _ed(win)
    which = {"inside-h": "inside_h", "inside-v": "inside_v"}.get(which, which)
    if ed.cell_name():
        borders(win, which)
        return
    line = [("w:val", "single"), ("w:sz", "4"), ("w:space", "1"), ("w:color", "auto")]
    nil = [("w:val", "nil")]
    sides = ("top", "left", "bottom", "right", "between")
    if which in ("all", "outside", "none", "inside", "inside_h"):
        on = {"all": sides, "outside": sides[:4], "none": (), "inside": ("between",),
              "inside_h": ("between",)}[which]
        ed.set_borders("paras", [(s, line if s in on else None) for s in sides])
    elif which in sides:
        ed.set_borders("paras", [(which, line)])
    _done(win)


def text_direction(win):
    if _ed(win).cycle_text_direction():
        _done(win)


def distribute_rows(win):
    if _ed(win).distribute_rows():
        _done(win)


TW = 1440.0 / 2540.0   # twips per 1/100 mm


def split_cells_dialog(win):
    from gi.repository import Gtk
    from ..widgets import FDialog, grid
    ed = _ed(win)
    if not ed.cell_name():
        return
    d = FDialog(win, "Split Cells")
    cols = Gtk.SpinButton.new_with_range(1, 63, 1)
    cols.set_value(2)
    rows = Gtk.SpinButton.new_with_range(1, 63, 1)
    rows.set_value(1)
    d.add(grid([["Number of _columns:", cols], ["Number of _rows:", rows]]))
    merge = Gtk.CheckButton.new_with_mnemonic("_Merge cells before split")
    merge.set_active(True)
    d.add(merge)
    r = d.ask()
    c, n, m = int(cols.get_value()), int(rows.get_value()), merge.get_active()
    d.done()
    if r != Gtk.ResponseType.OK:
        return
    ed.begin_group("Split Cells")
    if m and ed.has_selection():
        ed.table_command("merge")
    ed.split_cells(c, n)
    ed.end_group()
    _done(win)


def split_table(win):
    if _ed(win).split_table():
        _done(win)


def select(win, what):
    if _ed(win).select_table_part(what):
        win.engine.view.after_move()


def properties_dialog(win, page=0):
    """Table Properties: Table, Row, Column, Cell and Alt Text."""
    from gi.repository import Gtk
    from ..widgets import FDialog, LengthSpin, combo, grid
    ed = _ed(win)
    tp = ed.table_props()
    if tp is None:
        return
    widths = list(ed.grid_widths())
    cols = ed.selected_grid_cols() or (0, 1)
    d = FDialog(win, "Table Properties")
    nb = Gtk.Notebook()
    d.add(nb)

    def opt_len(on, mm100):
        cb = Gtk.CheckButton.new_with_mnemonic("_Preferred width:")
        sp = LengthSpin(mm100, 0, 55880)
        cb.set_active(on)
        sp.set_sensitive(on)
        cb.connect("toggled", lambda b: sp.set_sensitive(b.get_active()))
        return cb, sp

    def tab(title, rows, extra=()):
        b = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        b.set_border_width(12)
        b.pack_start(grid(rows), False, False, 0)
        for w in extra:
            b.pack_start(w, False, False, 0)
        nb.append_page(b, Gtk.Label(label=title))
    # table
    w, wt = tp["width"]
    t_on, t_w = opt_len(wt == "dxa" and w > 0, w / TW if wt == "dxa" else 0)
    t_pct = Gtk.CheckButton.new_with_mnemonic("Percent of page width")
    t_pct.set_active(wt == "pct")
    aligns = ["left", "center", "right"]
    t_al = combo(["Left", "Center", "Right"], aligns.index(tp["jc"]) if tp["jc"] in aligns else 0)
    t_ind = LengthSpin(tp["ind"] / TW, -55880, 55880)
    tab("Table", [[t_on, t_w], ["", t_pct], ["Alignment:", t_al], ["_Indent from left:", t_ind]])
    # row
    r_on = Gtk.CheckButton.new_with_mnemonic("_Specify height:")
    r_on.set_active(tp["row_height"] > 0)
    r_h = LengthSpin(tp["row_height"] / TW, 0, 55880)
    r_rule = combo(["At least", "Exactly"], 1 if tp["row_rule"] == "exact" else 0)
    r_split = Gtk.CheckButton.new_with_mnemonic("Allow row to _break across pages")
    r_split.set_active(not tp["cant_split"])
    r_head = Gtk.CheckButton.new_with_mnemonic("Repeat as _header row at the top of each page")
    r_head.set_active(tp["header"])
    tab("Row", [[r_on, r_h], ["Row height is:", r_rule]], [r_split, r_head])
    # column
    cw = sum(widths[cols[0]:cols[1]]) if widths else 0
    c_on, c_w = opt_len(cw > 0, cw / TW)
    tab("Column", [[c_on, c_w]])
    # cell
    w, wt = tp["cell_width"]
    e_on, e_w = opt_len(w > 0 and wt == "dxa", w / TW if wt == "dxa" else 0)
    valigns = ["top", "center", "bottom"]
    e_va = combo(["Top", "Center", "Bottom"], valigns.index(tp["valign"]) if tp["valign"] in valigns else 0)
    tab("Cell", [[e_on, e_w], ["Vertical alignment:", e_va]])
    # alt text
    a_title = Gtk.Entry()
    a_title.set_text(tp["caption"])
    a_desc = Gtk.Entry()
    a_desc.set_text(tp["description"])
    tab("Alt Text", [["_Title:", a_title], ["_Description:", a_desc]])
    nb.set_current_page(page)
    r = d.ask()
    vals = dict(t_on=t_on.get_active(), t_w=t_w.mm100, t_pct=t_pct.get_active(), t_al=t_al.get_active(),
                t_ind=t_ind.mm100, r_on=r_on.get_active(), r_h=r_h.mm100, r_rule=r_rule.get_active(),
                r_split=r_split.get_active(), r_head=r_head.get_active(), c_on=c_on.get_active(),
                c_w=c_w.mm100, e_on=e_on.get_active(), e_w=e_w.mm100, e_va=e_va.get_active(),
                a_title=a_title.get_text(), a_desc=a_desc.get_text())
    d.done()
    if r != Gtk.ResponseType.OK:
        return
    v = vals
    tw = lambda mm: str(int(round(mm * TW)))  # noqa: E731
    ed.begin_group("Table Properties")
    if v["t_pct"]:
        width = [("w:w", "5000"), ("w:type", "pct")]
    elif v["t_on"]:
        width = [("w:w", tw(v["t_w"])), ("w:type", "dxa")]
    else:
        width = [("w:w", "0"), ("w:type", "auto")]
    ed.table_apply("table", [
        ("w:tblW", width),
        ("w:jc", None if v["t_al"] == 0 else [("w:val", aligns[v["t_al"]])]),
        ("w:tblInd", [("w:w", tw(v["t_ind"])), ("w:type", "dxa")] if v["t_al"] == 0 else None),
        ("w:tblCaption", [("w:val", v["a_title"])] if v["a_title"] else None),
        ("w:tblDescription", [("w:val", v["a_desc"])] if v["a_desc"] else None)], "Table Properties")
    ed.table_apply("rows", [
        ("w:trHeight", [("w:val", tw(v["r_h"])), ("w:hRule", "exact" if v["r_rule"] else "atLeast")]
         if v["r_on"] else None),
        ("w:cantSplit", None if v["r_split"] else []),
        ("w:tblHeader", [] if v["r_head"] else None)], "Table Properties")
    if v["c_on"] and widths:
        new = list(widths)
        span = max(1, cols[1] - cols[0])
        for i in range(cols[0], min(cols[1], len(new))):
            new[i] = int(round(v["c_w"] * TW / span))
        if new != widths:
            ed.set_grid_widths(new, "Table Properties")
    ed.table_apply("cells", [
        ("w:vAlign", None if v["e_va"] == 0 else [("w:val", valigns[v["e_va"]])])], "Table Properties")
    if v["e_on"] and not v["c_on"]:
        ed.table_apply("cells", [("w:tcW", [("w:w", tw(v["e_w"])), ("w:type", "dxa")])], "Table Properties")
    ed.end_group()
    _done(win)


def insert_cells_dialog(win):
    from gi.repository import Gtk
    from ..widgets import FDialog
    ed = _ed(win)
    if not ed.cell_name():
        return
    d = FDialog(win, "Insert Cells")
    row = Gtk.RadioButton.new_with_mnemonic(None, "Insert entire _row")
    col = Gtk.RadioButton.new_with_mnemonic_from_widget(row, "Insert entire _column")
    d.add(row)
    d.add(col)
    r = d.ask()
    which = "insert_rows_above" if row.get_active() else "insert_cols_left"
    d.done()
    if r == Gtk.ResponseType.OK and ed.table_command(which):
        _done(win)


DISPATCH = {
    "set_row_height": set_row_height, "set_col_width": set_col_width, "autofit": autofit,
    "align_cells": align_cells, "repeat_header": repeat_header, "distribute": distribute,
    "text_direction": text_direction, "distribute_rows": distribute_rows,
}


def call(win, fn, *args):
    f = DISPATCH.get(fn)
    if f is None:
        return False
    f(win, *args)
    return True
