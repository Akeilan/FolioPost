"""Borders and Shading, as in the original: settings None / Box / Shadow /
3-D / Custom, line style, color and width, a preview whose edges are
switched on and off by clicking, Apply to (text, paragraph, cell, table,
whole document, this section), Options (distance from text) and shading
with a fill colour and a pattern."""
from gi.repository import Gdk, Gtk

from . import bridge, docapi
from .widgets import FDialog, LengthSpin, color_button, combo, grid, heading, rgb

STYLES = [("Single", 0), ("Dotted", 1), ("Dashed", 2), ("Dash dot", 16),
          ("Dash dot dot", 17), ("Double", 3), ("Thin thick", 4), ("Thick thin", 7),
          ("3-D emboss", 10), ("3-D engrave", 11), ("Outset", 12), ("Inset", 13)]
WIDTHS = [("¼ pt", 0.25), ("½ pt", 0.5), ("¾ pt", 0.75), ("1 pt", 1), ("1½ pt", 1.5),
          ("2¼ pt", 2.25), ("3 pt", 3), ("4½ pt", 4.5), ("6 pt", 6)]
PATTERNS = [("Clear", 0), ("Solid (100%)", 100), ("5%", 5), ("10%", 10), ("12.5%", 12.5),
            ("20%", 20), ("25%", 25), ("30%", 30), ("37.5%", 37.5), ("40%", 40), ("50%", 50),
            ("60%", 60), ("62.5%", 62.5), ("70%", 70), ("75%", 75), ("80%", 80),
            ("87.5%", 87.5), ("90%", 90), ("95%", 95)]
SIDES = ("top", "bottom", "left", "right")
PROP = {"top": "TopBorder", "bottom": "BottomBorder", "left": "LeftBorder",
        "right": "RightBorder"}


def _line(style, width_pt, color):
    w = int(round(width_pt * 2540 / 72))
    if style == 3:          # double: two lines and a gap
        return bridge.struct("com.sun.star.table.BorderLine2", Color=color, LineWidth=w * 3,
                             OuterLineWidth=w, InnerLineWidth=w, LineDistance=w,
                             LineStyle=style)
    return bridge.struct("com.sun.star.table.BorderLine2", Color=color, LineWidth=w,
                         OuterLineWidth=w, LineStyle=style)


def _empty():
    return bridge.struct("com.sun.star.table.BorderLine2")


def blend(fill, pat_color, pct):
    """A pattern as seen from a distance: the fill with pct% of the pattern
    colour."""
    if pct <= 0:
        return fill
    if fill is None or fill < 0:
        fill = 0xFFFFFF
    if pat_color is None or pat_color < 0:
        pat_color = 0x000000
    f = pct / 100.0
    out = 0
    for sh in (16, 8, 0):
        a, b = (fill >> sh) & 255, (pat_color >> sh) & 255
        out |= int(round(a + (b - a) * f)) << sh
    return out


class BorderPage:
    """One Borders / Page Border page."""

    def __init__(self, dlg, page, apply_to, sides_now, state_now):
        self.page = page
        box = Gtk.Box(spacing=14)
        box.set_border_width(10)
        self.box = box
        # settings
        setting = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        setting.pack_start(Gtk.Label(label="Setting:", xalign=0), False, False, 0)
        self.radios = {}
        grp = None
        for key, label in (("none", "_None"), ("box", "Bo_x"), ("shadow", "Sh_adow"),
                           ("3d", "3-_D"), ("custom", "C_ustom")):
            rb = Gtk.RadioButton.new_with_mnemonic_from_widget(grp, label)
            grp = grp or rb
            self.radios[key] = rb
            setting.pack_start(rb, False, False, 0)
        box.pack_start(setting, False, False, 0)
        # style
        mid = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        mid.pack_start(Gtk.Label(label="St_yle:", xalign=0, use_underline=True), False, False, 0)
        self.style = Gtk.ListBox()
        for name, _v in STYLES:
            self.style.add(Gtk.Label(label=name, xalign=0, margin=2))
        sw = Gtk.ScrolledWindow()
        sw.set_size_request(160, 150)
        sw.add(self.style)
        mid.pack_start(sw, False, False, 0)
        self.touched = False
        self.color = color_button(0x000000, on_change=lambda *_: self._touch())
        self.width = combo([n for n, _v in WIDTHS], 1)
        mid.pack_start(grid([["_Color:", self.color], ["_Width:", self.width]]), False, False, 0)
        if page:
            self.art = combo(["(none)"], 0)
            mid.pack_start(grid([["A_rt:", self.art]]), False, False, 0)
        box.pack_start(mid, False, False, 0)
        # preview
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        right.pack_start(Gtk.Label(label="Preview", xalign=0), False, False, 0)
        right.pack_start(Gtk.Label(label="Click on diagram below or use buttons to apply "
                                         "borders", xalign=0, wrap=True, max_width_chars=26),
                         False, False, 0)
        self.sides = set(sides_now)
        self.da = Gtk.DrawingArea()
        self.da.set_size_request(170, 140)
        self.da.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        self.da.connect("draw", self._draw)
        self.da.connect("button-press-event", self._click)
        right.pack_start(self.da, False, False, 0)
        tb = Gtk.Box(spacing=4)
        self.toggles = {}
        for side in SIDES:
            t = Gtk.ToggleButton(label=side.capitalize())
            t.set_active(side in self.sides)
            t.connect("toggled", lambda b, s=side: self._toggle(s, b.get_active()))
            self.toggles[side] = t
            tb.pack_start(t, False, False, 0)
        right.pack_start(tb, False, False, 0)
        ab = Gtk.Box(spacing=6)
        ab.pack_start(Gtk.Label(label="Appl_y to:", use_underline=True), False, False, 0)
        self.apply_to = combo(apply_to, 0)
        ab.pack_start(self.apply_to, False, False, 0)
        right.pack_start(ab, False, False, 0)
        self.options = Gtk.Button(label="_Options...", use_underline=True)
        self.options.set_halign(Gtk.Align.END)
        right.pack_start(self.options, False, False, 0)
        box.pack_start(right, True, True, 0)
        # current state
        self.radios[state_now.get("setting", "none")].set_active(True)
        self.style.select_row(self.style.get_row_at_index(
            next((i for i, (_n, v) in enumerate(STYLES) if v == state_now.get("style", 0)), 0)))
        if state_now.get("color") is not None:
            self.color.color = state_now["color"]
        w = state_now.get("width")
        if w:
            self.width.set_active(min(range(len(WIDTHS)), key=lambda i: abs(WIDTHS[i][1] - w)))
        self.dist = dict(state_now.get("dist") or {})
        for rb in self.radios.values():
            rb.connect("toggled", self._setting)
        self._busy = False
        self.touched = False
        self.style.connect("row-selected", lambda *_: self._touch())
        self.width.connect("changed", lambda *_: self._touch())
        self.apply_to.connect("changed", lambda *_: self._touch())
        self.options.connect("clicked", lambda *_: self._touch())

    def _touch(self):
        self.touched = True
        self.da.queue_draw()

    def setting(self):
        return next(k for k, r in self.radios.items() if r.get_active())

    def style_value(self):
        row = self.style.get_selected_row()
        st = STYLES[row.get_index() if row else 0][1]
        if self.setting() == "3d":
            st = 10
        return st

    def width_pt(self):
        return WIDTHS[max(0, self.width.get_active())][1]

    def _setting(self, rb):
        if not rb.get_active() or self._busy:
            return
        self.touched = True
        k = self.setting()
        self._busy = True
        if k == "none":
            self.sides = set()
        elif k in ("box", "shadow", "3d"):
            self.sides = set(SIDES)
        for s, t in self.toggles.items():
            t.set_active(s in self.sides)
        self._busy = False
        self.da.queue_draw()

    def _toggle(self, side, on):
        if self._busy:
            return
        self.touched = True
        if on:
            self.sides.add(side)
        else:
            self.sides.discard(side)
        self._busy = True
        full = self.sides == set(SIDES)
        if not self.sides:
            self.radios["none"].set_active(True)
        elif not (full and self.setting() in ("box", "shadow", "3d")):
            self.radios["custom"].set_active(True)
        self._busy = False
        self.da.queue_draw()

    def _click(self, w, ev):
        a = w.get_allocation()
        x, y = ev.x / a.width, ev.y / a.height
        d = {"top": y, "bottom": 1 - y, "left": x, "right": 1 - x}
        side = min(d, key=d.get)
        self.toggles[side].set_active(side not in self.sides)
        return True

    def _draw(self, w, cr):
        a = w.get_allocation()
        W, H = a.width, a.height
        cr.set_source_rgb(1, 1, 1)
        cr.paint()
        x0, y0, x1, y1 = 25, 20, W - 25, H - 20
        cr.set_source_rgb(0.75, 0.75, 0.75)
        y = y0 + 12
        while y < y1 - 8:
            cr.rectangle(x0 + 10, y, x1 - x0 - 20, 2)
            y += 8
        cr.fill()
        col = self.color.color if self.color.color is not None and self.color.color >= 0 else 0
        cr.set_source_rgb(*rgb(col))
        cr.set_line_width(max(1, self.width_pt() * 1.3))
        st = self.style_value()
        cr.set_dash([2, 2] if st == 1 else [6, 3] if st == 2 else [])
        segs = {"top": (x0, y0, x1, y0), "bottom": (x0, y1, x1, y1),
                "left": (x0, y0, x0, y1), "right": (x1, y0, x1, y1)}
        for s in self.sides:
            sx, sy, ex, ey = segs[s]
            cr.move_to(sx, sy)
            cr.line_to(ex, ey)
            cr.stroke()
            if st == 3:
                off = 3
                dx, dy = (0, off) if s in ("top", "bottom") else (off, 0)
                if s in ("bottom", "right"):
                    dx, dy = -dx, -dy
                cr.move_to(sx + dx, sy + dy)
                cr.line_to(ex + dx, ey + dy)
                cr.stroke()
        if self.setting() == "shadow" and self.sides:
            cr.set_dash([])
            cr.set_source_rgb(0.45, 0.45, 0.45)
            cr.rectangle(x1, y0 + 4, 4, y1 - y0)
            cr.rectangle(x0 + 4, y1, x1 - x0, 4)
            cr.fill()
        cr.set_dash([])
        return False

    def lines(self):
        col = self.color.color if self.color.color is not None and self.color.color >= 0 else 0
        line = _line(self.style_value(), self.width_pt(), col)
        return {s: (line if s in self.sides else _empty()) for s in SIDES}


def _read_state(obj, prefix=""):
    sides, st, col, wid = set(), 0, None, None
    dist = {}
    for s in SIDES:
        try:
            ln = getattr(obj, prefix + PROP[s])
            if ln.OuterLineWidth > 0 or ln.LineWidth > 0:
                sides.add(s)
                st, col = ln.LineStyle, ln.Color
                wid = (ln.LineWidth or ln.OuterLineWidth) * 72 / 2540.0
                if st == 3:
                    wid /= 3.0
        except Exception:
            pass
        try:
            dist[s] = getattr(obj, prefix + PROP[s] + "Distance")
        except Exception:
            pass
    shadow = False
    try:
        shadow = obj.ShadowFormat.Location.value != "NONE"
    except Exception:
        pass
    setting = "none" if not sides else ("custom" if sides != set(SIDES) else
                                       "shadow" if shadow else "3d" if st == 10 else "box")
    return {"setting": setting, "style": st, "color": col, "width": wid, "sides": sides,
            "dist": dist}


def _options(parent, dist, page=False, measure=None):
    d = FDialog(parent, "Border and Shading Options")
    d.add(heading("Distance from text" if not page else "Margin"))
    sp = {s: LengthSpin(dist.get(s, 0 if not page else 847), 0, 30000) for s in SIDES}
    d.add(grid([["To_p:", sp["top"], "_Left:", sp["left"]],
                ["_Bottom:", sp["bottom"], "_Right:", sp["right"]]]))
    mcombo = None
    if page:
        mcombo = combo(["Text", "Edge of page"], measure[0] if measure else 0)
        d.add(grid([["_Measure from:", mcombo]]))
    d.show_all()
    if d.ask() == Gtk.ResponseType.OK:
        for s in SIDES:
            dist[s] = sp[s].mm100
        if mcombo is not None and measure is not None:
            measure[0] = mcombo.get_active()
    d.destroy()


def dialog(win, tab=0):
    m = win.engine.model
    if m is None:
        return
    vc = docapi.view_cursor(m)
    in_table = False
    try:
        in_table = vc.TextTable is not None
    except Exception:
        pass
    has_sel = not vc.isCollapsed()
    para = vc.getText().createTextCursorByRange(vc.getStart())
    para.gotoStartOfParagraph(False)
    para.gotoEndOfParagraph(True)
    d = FDialog(win, "Borders and Shading")
    nb = Gtk.Notebook()
    d.add(nb)
    targets = (["Text"] if has_sel else []) + ["Paragraph"] + \
        (["Cell", "Table"] if in_table else [])
    default_target = "Table" if in_table and not has_sel else \
        ("Text" if has_sel and "\n" not in vc.getString() else "Paragraph")
    targets.remove(default_target)
    targets.insert(0, default_target)
    st_para = _read_state(para)
    b = BorderPage(d, False, targets, st_para["sides"], st_para)
    b.options.connect("clicked", lambda *_: _options(d, b.dist))
    nb.append_page(b.box, Gtk.Label(label="Borders"))
    ps = docapi.page_style(m)
    st_page = _read_state(ps)
    pg = BorderPage(d, True, ["Whole document", "This section"], st_page["sides"], st_page)
    measure = [0]
    pg.options.connect("clicked", lambda *_: _options(d, pg.dist, True, measure))
    nb.append_page(pg.box, Gtk.Label(label="Page Border"))
    # shading
    sbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    sbox.set_border_width(10)
    cur_fill = -1
    try:
        cur_fill = para.ParaBackColor
    except Exception:
        pass
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
    if d.ask() == Gtk.ResponseType.OK:
        um = m.getUndoManager()
        um.enterUndoContext("Borders and Shading")
        try:
            if b.touched:
                _apply_borders(m, b, vc, para)
            if pg.touched:
                _apply_page(m, pg, measure[0])
            c = blend(fill.color, pcolor.color, PATTERNS[max(0, pstyle.get_active())][1])
            if pstyle.get_active() > 0 and (fill.color is None or fill.color < 0):
                c = blend(0xFFFFFF, pcolor.color, PATTERNS[pstyle.get_active()][1])
            target = sapply.get_active_text()
            if nb.get_current_page() == 2 or c != cur_fill:
                _apply_shading(m, target, c, vc, para)
        finally:
            um.leaveUndoContext()
    d.destroy()
    win.focus_document()


def _apply_borders(m, page, vc, para):
    target = page.apply_to.get_active_text()
    lines = page.lines()
    shadow = page.setting() == "shadow"
    if target == "Text":
        for s in SIDES:
            setattr(vc, "Char" + PROP[s], lines[s])
            try:
                setattr(vc, "Char" + PROP[s] + "Distance", page.dist.get(s, 0))
            except Exception:
                pass
        return
    if target in ("Cell", "Table"):
        t = vc.TextTable
        if target == "Table":
            tb = t.TableBorder2 if hasattr(t, "TableBorder2") else t.TableBorder
            for s in SIDES:
                setattr(tb, PROP[s] + "Line", lines[s])
                setattr(tb, "Is%sLineValid" % PROP[s].replace("Border", ""), True)
            try:
                t.TableBorder2 = tb
            except Exception:
                t.TableBorder = tb
        else:
            cell = vc.Cell
            for s in SIDES:
                setattr(cell, PROP[s], lines[s])
        return
    # paragraphs (all in the selection)
    rng = vc.getText().createTextCursorByRange(vc.getStart())
    rng.gotoRange(vc.getEnd(), True)
    target_rng = para if vc.isCollapsed() else rng
    for s in SIDES:
        setattr(target_rng, PROP[s], lines[s])
        setattr(target_rng, PROP[s] + "Distance",
                page.dist.get(s, int(1 * 2540 / 72) if s in ("top", "bottom") else
                              int(4 * 2540 / 72)) if page.sides else 0)
    sh = bridge.struct("com.sun.star.table.ShadowFormat")
    if shadow:
        sh.Location = bridge.enum("com.sun.star.table.ShadowLocation", "BOTTOM_RIGHT")
        sh.ShadowWidth = int(page.width_pt() * 2540 / 72 * 3)
        sh.Color = 0x808080
    try:
        target_rng.ParaShadowFormat = sh
    except Exception:
        pass


def _apply_page(m, page, measure):
    if page.apply_to.get_active() == 0:
        from .pagesetup import used_page_styles
        styles = used_page_styles(m)
    else:
        styles = [docapi.page_style(m)]
    lines = page.lines()
    for ps in styles:
        for s in SIDES:
            setattr(ps, PROP[s], lines[s])
            dist = page.dist.get(s, int(24 * 2540 / 72) if s in ("top", "bottom") else
                                 int(24 * 2540 / 72))
            if measure == 1:
                margin = {"top": ps.TopMargin, "bottom": ps.BottomMargin,
                          "left": ps.LeftMargin, "right": ps.RightMargin}[s]
                dist = max(0, margin - dist)
            try:
                setattr(ps, PROP[s] + "Distance", dist if page.sides else 0)
            except Exception:
                pass
        sh = bridge.struct("com.sun.star.table.ShadowFormat")
        if page.setting() == "shadow":
            sh.Location = bridge.enum("com.sun.star.table.ShadowLocation", "BOTTOM_RIGHT")
            sh.ShadowWidth = int(page.width_pt() * 2540 / 72 * 3)
            sh.Color = 0x808080
        ps.ShadowFormat = sh


def _apply_shading(m, target, color, vc, para):
    if target == "Text":
        vc.CharBackColor = color if color is not None else -1
    elif target == "Cell":
        vc.Cell.BackColor = color if color is not None else -1
    elif target == "Table":
        t = vc.TextTable
        for n in t.getCellNames():
            t.getCellByName(n).BackColor = color if color is not None else -1
    else:
        rng = para if vc.isCollapsed() else vc
        rng.ParaBackColor = color if color is not None else -1
