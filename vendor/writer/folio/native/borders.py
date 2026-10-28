"""Borders and Shading with the new engine: the Borders, Page Border and Shading tabs of
the original dialog, written as w:pBdr / w:tcBorders / w:tblBorders / w:bdr, w:pgBorders and
w:shd."""
from gi.repository import Gtk

from ..bordersdlg import PATTERNS, SIDES, BorderPage, _options, blend
from ..widgets import FDialog, color_button, combo, grid, heading, rgb

# the dialog's line styles (as numbered there) -> Word's border values
VAL = {0: "single", 1: "dotted", 2: "dashed", 16: "dotDash", 17: "dotDotDash", 3: "double",
       4: "thinThickSmallGap", 7: "thickThinSmallGap", 10: "threeDEmboss", 11: "threeDEngrave",
       12: "outset", 13: "inset"}
STYLE_OF = {v: k for k, v in VAL.items()}
STYLE_OF.update({"thick": 0, "triple": 3, "wave": 0})
PT_PER_MM100 = 72 / 2540.0


def _state(items, dist_default):
    """Dialog state from (side, attrs) border elements."""
    sides, st, col, wid, dist, shadow = set(), 0, None, None, {}, False
    for side, attrs in items:
        a = dict(attrs)
        if side not in SIDES:
            continue
        if a.get("w:val") in (None, "nil", "none"):
            continue
        sides.add(side)
        st = STYLE_OF.get(a.get("w:val"), 0)
        c = a.get("w:color", "auto")
        col = int(c, 16) if c not in ("auto", "") else 0
        try:
            wid = int(a.get("w:sz", "4")) / 8.0
        except ValueError:
            wid = 0.5
        try:
            dist[side] = int(round(int(a.get("w:space", "0")) / PT_PER_MM100))
        except ValueError:
            pass
        shadow = shadow or a.get("w:shadow") in ("1", "true", "on")
    for s in SIDES:
        dist.setdefault(s, dist_default(s))
    setting = "none" if not sides else ("custom" if sides != set(SIDES) else
                                       "shadow" if shadow else "3d" if st == 10 else "box")
    return {"setting": setting, "style": st, "color": col, "width": wid, "sides": sides, "dist": dist}


def _line(page, side, dist_pt_default):
    """A side's border element attributes (or nil)."""
    if side not in page.sides:
        return [("w:val", "nil")]
    col = page.color.color if page.color.color is not None and page.color.color >= 0 else None
    dist = page.dist.get(side)
    space = int(round(dist * PT_PER_MM100)) if dist is not None else dist_pt_default
    attrs = [("w:val", VAL.get(page.style_value(), "single")),
             ("w:sz", str(max(2, int(round(page.width_pt() * 8))))),
             ("w:space", str(max(0, min(31, space)))),
             ("w:color", "%06X" % col if col is not None else "auto")]
    if page.setting() == "shadow":
        attrs.append(("w:shadow", "1"))
    return attrs


def dialog(win, tab=0):
    ed = win.engine.ed
    if ed is None:
        return
    in_table = bool(ed.cell_name())
    sel = ed.selected_text() if ed.has_selection() else ""
    has_sel = bool(sel)
    targets = (["Text"] if has_sel else []) + ["Paragraph"] + (["Cell", "Table"] if in_table else [])
    default = "Table" if in_table and not has_sel else ("Text" if has_sel and "\n" not in sel else "Paragraph")
    targets.remove(default)
    targets.insert(0, default)
    d = FDialog(win, "Borders and Shading")
    nb = Gtk.Notebook()
    d.add(nb)
    key = {"Paragraph": "paras", "Cell": "cells", "Table": "table", "Text": "paras"}[default]
    pt_mm = lambda pt: int(round(pt / PT_PER_MM100))  # noqa: E731
    st = _state(ed.border_state(key), lambda s: pt_mm(1 if s in ("top", "bottom") else 4))
    b = BorderPage(d, False, targets, st["sides"], st)
    b.options.connect("clicked", lambda *_: _options(d, b.dist))
    nb.append_page(b.box, Gtk.Label(label="Borders"))
    # page border: the section's w:pgBorders
    sec = ed.current_section()
    pst = _state(_page_items(ed, sec), lambda s: pt_mm(24))
    pg = BorderPage(d, True, ["Whole document", "This section", "This section - First page only",
                              "This section - All except first page"], pst["sides"], pst)
    measure = [1]
    pg.options.connect("clicked", lambda *_: _options(d, pg.dist, True, measure))
    nb.append_page(pg.box, Gtk.Label(label="Page Border"))
    # shading
    sbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    sbox.set_border_width(10)
    cur = ed.shading_state(key)
    cur_fill = int(cur, 16) if cur else -1
    fill = color_button(cur_fill, auto_label="No Color")
    sbox.pack_start(heading("Fill"), False, False, 0)
    sbox.pack_start(fill, False, False, 0)
    sbox.pack_start(heading("Patterns"), False, False, 0)
    pstyle = combo([n for n, _v in PATTERNS], 0)
    pcolor = color_button(-1)
    sbox.pack_start(grid([["St_yle:", pstyle], ["C_olor:", pcolor]]), False, False, 0)
    sprev = Gtk.DrawingArea()
    sprev.set_size_request(170, 60)

    def sdraw(w, cr):
        c = blend(fill.color, pcolor.color, PATTERNS[max(0, pstyle.get_active())][1])
        cr.set_source_rgb(*rgb(c if c is not None and c >= 0 else 0xFFFFFF))
        cr.paint()
        cr.set_source_rgb(0, 0, 0)
        cr.select_font_face("Sans")
        cr.set_font_size(11)
        cr.move_to(20, 35)
        cr.show_text("Sample text")
    sprev.connect("draw", sdraw)
    pstyle.connect("changed", lambda *_: sprev.queue_draw())
    sbox.pack_start(Gtk.Label(label="Preview", xalign=0), False, False, 0)
    sbox.pack_start(sprev, False, False, 0)
    sapply = combo(targets, 0)
    sbox.pack_start(grid([["Appl_y to:", sapply]]), False, False, 0)
    nb.append_page(sbox, Gtk.Label(label="Shading"))
    d.show_all()
    nb.set_current_page(tab)
    d.borders, d.page, d.fill, d.pstyle, d.pcolor, d.sapply, d.nb = b, pg, fill, pstyle, pcolor, sapply, nb
    win._borders_dialog = d
    ok = d.ask() == Gtk.ResponseType.OK
    if ok:
        apply(win, d, cur_fill, measure[0])
    d.destroy()
    win.focus_document()


def _page_items(ed, sec):
    xml = ed.page_borders_xml(sec) or ""
    import re
    out = []
    for side, attrs in re.findall(r"<w:(top|left|bottom|right)\b([^>]*)/>", xml):
        out.append((side, re.findall(r'(w:\w+)="([^"]*)"', attrs)))
    return out


def apply(win, d, cur_fill=-1, measure=1):
    """The dialog's choices onto the document (one undo step)."""
    ed = win.engine.ed
    b, pg = d.borders, d.page
    ed.begin_group("Borders and Shading")
    try:
        if b.touched:
            target = b.apply_to.get_active_text()
            if target == "Text":
                # a box around the text: one border for the run
                if b.sides:
                    ed.apply_run([("w:bdr", _line(b, "top", 0))], "Borders")
                else:
                    ed.apply_run([("w:bdr", None)], "Borders")
            elif target == "Paragraph":
                ed.set_borders("paras", [(s, _line(b, s, 1 if s in ("top", "bottom") else 4) if s in b.sides else None)
                                         for s in SIDES])
            elif target == "Cell":
                ed.set_borders("cells", [(s, _line(b, s, 0)) for s in SIDES])
            else:
                ed.set_borders("table", [(s, _line(b, s, 0)) for s in SIDES])
        if pg.touched:
            which = pg.apply_to.get_active()
            sec = None if which == 0 else ed.current_section()
            if not pg.sides:
                ed.set_page_borders(sec, None)
            else:
                sides = "".join('<w:%s %s/>' % (s, " ".join('%s="%s"' % kv for kv in _line(pg, s, 24)))
                                for s in ("top", "left", "bottom", "right"))
                display = {2: ' w:display="firstPage"', 3: ' w:display="notFirstPage"'}.get(which, "")
                offset = ' w:offsetFrom="page"' if measure == 1 else ""
                ed.set_page_borders(sec, "<w:pgBorders%s%s>%s</w:pgBorders>" % (offset, display, sides))
        pat = PATTERNS[max(0, d.pstyle.get_active())][1]
        c = blend(d.fill.color, d.pcolor.color, pat)
        if pat > 0 and (d.fill.color is None or d.fill.color < 0):
            c = blend(0xFFFFFF, d.pcolor.color, pat)
        if d.nb.get_current_page() == 2 or c != cur_fill:
            target = d.sapply.get_active_text()
            shd = None if c is None or c < 0 else [("w:val", "clear"), ("w:color", "auto"), ("w:fill", "%06X" % (c & 0xFFFFFF))]
            if target == "Text":
                ed.apply_run([("w:shd", shd)], "Shading")
            elif target == "Paragraph":
                ed.apply_para([("w:shd", shd)], "Shading")
            elif target == "Cell":
                ed.table_apply("cells", [("w:shd", shd)], "Shading")
            else:
                ed.table_apply("table", [("w:shd", shd)], "Shading")
    finally:
        ed.end_group()
    win.engine.view.document_changed()
