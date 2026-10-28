"""Page Setup, as in the original: Margins (gutter position, mirror
margins), Paper (paper source), Layout (section start, different odd and
even / first page, header and footer distance from edge, vertical
alignment), Apply to, and Set As Default."""
from gi.repository import Gtk

from . import bridge, docapi
from .widgets import FDialog, LengthSpin, Preview, combo, grid, heading

PAPER = [("Letter", 21590, 27940), ("Legal", 21590, 35560), ("Executive", 18415, 26670),
         ("A3", 29700, 42000), ("A4", 21000, 29700), ("A5", 14800, 21000),
         ("B5 (JIS)", 18200, 25700), ("Tabloid", 27940, 43180),
         ("Envelope #10", 10477, 24130), ("Envelope DL", 11000, 22000)]
SECTION_START = ["Continuous", "New column", "New page", "Even page", "Odd page"]
VALIGN = [("Top", "TOP"), ("Center", "CENTER"), ("Justified", "BLOCK"), ("Bottom", "BOTTOM")]
APPLY = ["Whole document", "This section", "This point forward"]


def _layout(ps):
    try:
        return ps.PageStyleLayout.value
    except Exception:
        return "ALL"


def _set_layout(ps, value):
    try:
        ps.PageStyleLayout = bridge.enum("com.sun.star.style.PageStyleLayout", value)
    except Exception as e:
        print("page layout:", e)


def _doc_settings(m):
    try:
        return m.createInstance("com.sun.star.text.DocumentSettings")
    except Exception:
        return None


def used_page_styles(m):
    fam = m.getStyleFamilies().getByName("PageStyles")
    out = []
    for n in fam.getElementNames():
        st = fam.getByName(n)
        try:
            if st.isInUse():
                out.append(st)
        except Exception:
            pass
    return out or [docapi.page_style(m)]


def section_start_of(m, ps):
    """The current section's start type, from its page style."""
    lay = _layout(ps)
    if lay == "LEFT":
        return 3
    if lay == "RIGHT":
        return 4
    return 2


def read(m):
    ps = docapi.page_style(m)
    info = docapi.page_setup(m)
    info["mirror"] = _layout(ps) == "MIRRORED"
    try:
        info["valign"] = ps.TextVerticalAdjust.value
    except Exception:
        info["valign"] = "TOP"
    info["diff_odd_even"] = bool(ps.HeaderIsOn and not ps.HeaderIsShared) or \
        bool(ps.FooterIsOn and not ps.FooterIsShared)
    info["diff_first"] = not bool(getattr(ps, "FirstIsShared", True))
    info["header_edge"] = ps.TopMargin if ps.HeaderIsOn else 1270
    info["footer_edge"] = ps.BottomMargin if ps.FooterIsOn else 1270
    s = _doc_settings(m)
    info["gutter_top"] = bool(getattr(s, "GutterAtTop", False)) if s is not None else False
    info["start"] = section_start_of(m, ps)
    return info


def apply(m, ps, v):
    """Apply the dialog's values (a dict) to one page style."""
    if v["landscape"] != bool(ps.IsLandscape):
        w, h = ps.Width, ps.Height
        ps.IsLandscape = v["landscape"]
        if (v["landscape"] and w < h) or (not v["landscape"] and w > h):
            ps.Width, ps.Height = h, w
    width, height = v["width"], v["height"]
    if ps.IsLandscape:
        width, height = max(width, height), min(width, height)
    else:
        width, height = min(width, height), max(width, height)
    ps.Width, ps.Height = int(width), int(height)
    ps.LeftMargin, ps.RightMargin = int(v["left"]), int(v["right"])
    try:
        ps.GutterMargin = int(v["gutter"])
    except Exception:
        pass
    # headers and footers: distance from the edge, the body margin kept
    for key, side, edge in (("Header", "top", v["header_edge"]),
                            ("Footer", "bottom", v["footer_edge"])):
        body = v["top"] if side == "top" else v["bottom"]
        margin = "TopMargin" if side == "top" else "BottomMargin"
        if getattr(ps, key + "IsOn"):
            e = min(int(edge), max(0, int(body) - 300))
            setattr(ps, margin, e)
            setattr(ps, key + "Height", max(300, int(body) - e))
        else:
            setattr(ps, margin, int(body))
    # odd / even and first page
    for key in ("Header", "Footer"):
        if getattr(ps, key + "IsOn"):
            setattr(ps, key + "IsShared", not v["diff_odd_even"])
    try:
        ps.FirstIsShared = not v["diff_first"]
    except Exception as e:
        print("first page:", e)
    # layout: mirror margins / section start on even or odd page
    if v["mirror"]:
        _set_layout(ps, "MIRRORED")
    elif v["start"] == 3:
        _set_layout(ps, "LEFT")
    elif v["start"] == 4:
        _set_layout(ps, "RIGHT")
    elif _layout(ps) in ("MIRRORED", "LEFT", "RIGHT"):
        _set_layout(ps, "ALL")
    try:
        ps.TextVerticalAdjust = bridge.enum("com.sun.star.drawing.TextVerticalAdjust",
                                            v["valign"])
    except Exception as e:
        print("vertical alignment:", e)
    if v.get("columns") is not None:
        tc = ps.TextColumns
        if tc.getColumnCount() != v["columns"]:
            tc.setColumnCount(max(1, int(v["columns"])))
            try:
                tc.AutomaticDistance = 1270
            except Exception:
                pass
            ps.TextColumns = tc


def apply_to(m, v, where):
    um = m.getUndoManager()
    um.enterUndoContext("Page Setup")
    try:
        if where == 0:
            styles = used_page_styles(m)
        elif where == 2:
            kind = {3: "even", 4: "odd"}.get(v["start"], "next-page")
            if v["start"] == 0:
                kind = "continuous"
            name = docapi.insert_section_break(m, kind)
            fam = m.getStyleFamilies().getByName("PageStyles")
            styles = [fam.getByName(name)] if isinstance(name, str) and \
                fam.hasByName(name) else [docapi.page_style(m)]
        else:
            styles = [docapi.page_style(m)]
        for ps in styles:
            apply(m, ps, v)
        s = _doc_settings(m)
        if s is not None:
            try:
                s.GutterAtTop = bool(v["gutter_top"])
            except Exception:
                pass
    finally:
        um.leaveUndoContext()


def dialog(win, tab=0):
    if getattr(win.engine, "native", False):
        from .native import pagesetup as NP
        m = None
        info = NP.read(win)
        n_styles = info["section_count"]
        do_apply = lambda v, where: NP.apply_to(win, v, where)  # noqa: E731
        do_default = lambda v: NP.set_default(win, v)  # noqa: E731
    else:
        m = win.engine.model
        if m is None:
            return
        info = read(m)
        n_styles = len(used_page_styles(m))
        do_apply = lambda v, where: apply_to(m, v, where)  # noqa: E731
        do_default = lambda v: set_default(win, v)  # noqa: E731
    d = FDialog(win, "Page Setup")
    nb = Gtk.Notebook()
    d.add(nb)
    # ---------------------------------------------------------- margins
    p1 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    p1.set_border_width(10)
    p1.pack_start(heading("Margins"), False, False, 0)
    top, bottom = LengthSpin(info["top"], 0, 55880), LengthSpin(info["bottom"], 0, 55880)
    left, right = LengthSpin(info["left"], 0, 55880), LengthSpin(info["right"], 0, 55880)
    gutter = LengthSpin(info["gutter"] or 0, 0, 55880)
    gpos = combo(["Left", "Top"], 1 if info["gutter_top"] else 0)
    l_lab = Gtk.Label(label="_Left:", xalign=0, use_underline=True)
    r_lab = Gtk.Label(label="_Right:", xalign=0, use_underline=True)
    p1.pack_start(grid([["_Top:", top, "_Bottom:", bottom],
                        [l_lab, left, r_lab, right],
                        ["_Gutter:", gutter, "Gutter positi_on:", gpos]]), False, False, 0)
    p1.pack_start(heading("Orientation"), False, False, 0)
    portrait = Gtk.RadioButton.new_with_mnemonic(None, "_Portrait")
    landscape = Gtk.RadioButton.new_with_mnemonic_from_widget(portrait, "Land_scape")
    (landscape if info["landscape"] else portrait).set_active(True)
    ob = Gtk.Box(spacing=20)
    ob.pack_start(portrait, False, False, 0)
    ob.pack_start(landscape, False, False, 0)
    p1.pack_start(ob, False, False, 0)
    p1.pack_start(heading("Pages"), False, False, 0)
    multi = combo(["Normal", "Mirror margins"], 1 if info["mirror"] else 0)
    p1.pack_start(grid([["_Multiple pages:", multi]]), False, False, 0)

    def multi_changed(*_):
        mir = multi.get_active() == 1
        l_lab.set_text_with_mnemonic("I_nside:" if mir else "_Left:")
        r_lab.set_text_with_mnemonic("O_utside:" if mir else "_Right:")
        gpos.set_sensitive(not mir)
        if mir:
            gpos.set_active(0)
        prev.queue_draw()
    multi.connect("changed", multi_changed)
    # ---------------------------------------------------------- paper
    p2 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    p2.set_border_width(10)
    p2.pack_start(heading("Paper size"), False, False, 0)
    names = [p[0] for p in PAPER] + ["Custom size"]
    pw, ph = min(info["width"], info["height"]), max(info["width"], info["height"])
    idx = next((i for i, p in enumerate(PAPER) if abs(p[1] - pw) < 60 and abs(p[2] - ph) < 60),
               len(PAPER))
    paper = combo(names, idx)
    width = LengthSpin(info["width"], 2540, 304800)
    height = LengthSpin(info["height"], 2540, 304800)
    p2.pack_start(paper, False, False, 0)
    p2.pack_start(grid([["_Width:", width], ["H_eight:", height]]), False, False, 0)
    p2.pack_start(heading("Paper source"), False, False, 0)
    trays = ["Default tray (Automatically Select)", "Automatically Select", "Manual Feed"]
    first_tray, other_tray = Gtk.ListBox(), Gtk.ListBox()
    for lb in (first_tray, other_tray):
        for t in trays:
            lb.add(Gtk.Label(label=t, xalign=0, margin=2))
        lb.select_row(lb.get_row_at_index(0))
    tb = Gtk.Box(spacing=12, homogeneous=True)
    for lab, lb in (("_First page:", first_tray), ("_Other pages:", other_tray)):
        vb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        vb.pack_start(Gtk.Label(label=lab, xalign=0, use_underline=True), False, False, 0)
        fr = Gtk.Frame()
        fr.add(lb)
        vb.pack_start(fr, False, False, 0)
        tb.pack_start(vb, True, True, 0)
    p2.pack_start(tb, False, False, 0)

    def paper_changed(*_):
        i = paper.get_active()
        if 0 <= i < len(PAPER):
            w, h = PAPER[i][1], PAPER[i][2]
            if landscape.get_active():
                w, h = h, w
            width.set_value(w)
            height.set_value(h)
        prev.queue_draw()
    paper.connect("changed", paper_changed)

    def orient_changed(*_):
        w, h = width.get_value(), height.get_value()
        if (landscape.get_active() and w < h) or (portrait.get_active() and w > h):
            width.set_value(h)
            height.set_value(w)
        prev.queue_draw()
    landscape.connect("toggled", orient_changed)
    # ---------------------------------------------------------- layout
    p3 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    p3.set_border_width(10)
    p3.pack_start(heading("Section"), False, False, 0)
    start = combo(SECTION_START, info["start"])
    p3.pack_start(grid([["Section st_art:", start]]), False, False, 0)
    p3.pack_start(heading("Headers and footers"), False, False, 0)
    odd_even = Gtk.CheckButton.new_with_mnemonic("Different _odd and even")
    odd_even.set_active(info["diff_odd_even"])
    first = Gtk.CheckButton.new_with_mnemonic("Different first _page")
    first.set_active(info["diff_first"])
    p3.pack_start(odd_even, False, False, 0)
    p3.pack_start(first, False, False, 0)
    h_edge = LengthSpin(info["header_edge"], 0, 55880)
    f_edge = LengthSpin(info["footer_edge"], 0, 55880)
    p3.pack_start(grid([["From edge:", "_Header:", h_edge], [None, "_Footer:", f_edge]]),
                  False, False, 0)
    p3.pack_start(heading("Page"), False, False, 0)
    valign = combo([n for n, _v in VALIGN],
                   next((i for i, (_n, v) in enumerate(VALIGN) if v == info["valign"]), 0))
    p3.pack_start(grid([["_Vertical alignment:", valign]]), False, False, 0)
    lb_ = Gtk.Box(spacing=6)
    b1 = Gtk.Button(label="Line _Numbers...", use_underline=True)
    b2 = Gtk.Button(label="_Borders...", use_underline=True)
    b1.connect("clicked", lambda *_: win.dialogs.line_numbers_dialog())
    b2.connect("clicked", lambda *_: win.dialogs.page_borders())
    lb_.set_halign(Gtk.Align.END)
    lb_.pack_start(b1, False, False, 0)
    lb_.pack_start(b2, False, False, 0)
    p3.pack_start(lb_, False, False, 0)
    nb.append_page(p1, Gtk.Label(label="Margins"))
    nb.append_page(p2, Gtk.Label(label="Paper"))
    nb.append_page(p3, Gtk.Label(label="Layout"))
    # ---------------------------------------------------------- preview
    d.add(heading("Preview"))

    def draw(cr, W, H):
        w, h = width.get_value(), height.get_value()
        mir = multi.get_active() == 1
        n = 2 if mir else 1
        s = min((W - 20) / (w * n + 6 * (n - 1)), (H - 12) / h)
        pw_, ph_ = w * s, h * s
        x0 = (W - pw_ * n) / 2
        y0 = (H - ph_) / 2
        for k in range(n):
            x = x0 + k * pw_
            cr.set_source_rgb(0.55, 0.55, 0.55)
            cr.rectangle(x + 3, y0 + 3, pw_, ph_)
            cr.fill()
            cr.set_source_rgb(1, 1, 1)
            cr.rectangle(x, y0, pw_, ph_)
            cr.fill_preserve()
            cr.set_source_rgb(0.4, 0.4, 0.4)
            cr.set_line_width(1)
            cr.stroke()
            lm, rm = left.get_value() * s, right.get_value() * s
            if mir and k == 0:
                lm, rm = rm, lm
            g = gutter.get_value() * s
            t_, b_ = top.get_value() * s, bottom.get_value() * s
            if gpos.get_active() == 1 and not mir:
                t_ += g
            elif mir and k == 0:
                rm += g
            else:
                lm += g
            if g > 0:
                cr.set_source_rgb(0.85, 0.85, 0.85)
                if gpos.get_active() == 1 and not mir:
                    cr.rectangle(x, y0, pw_, g)
                elif mir and k == 0:
                    cr.rectangle(x + pw_ - g, y0, g, ph_)
                else:
                    cr.rectangle(x, y0, g, ph_)
                cr.fill()
            cr.set_source_rgb(0.7, 0.7, 0.7)
            area_h = ph_ - t_ - b_
            lines = int(area_h / 3.5)
            va = valign.get_active()
            used = min(lines, 9)
            yy = y0 + t_
            if va == 1:
                yy += (area_h - used * 3.5) / 2
            elif va == 3:
                yy += area_h - used * 3.5
            step = (area_h / max(1, used)) if va == 2 else 3.5
            for _i in range(used):
                cr.rectangle(x + lm + 1, yy, pw_ - lm - rm - 2, 1.2)
                yy += step
            cr.fill()
    prev = Preview(draw, 220, 150)
    prev.set_halign(Gtk.Align.CENTER)
    d.add(prev)
    apply_box = Gtk.Box(spacing=8)
    where = combo(APPLY, 0 if n_styles <= 1 else 1)
    apply_box.pack_start(Gtk.Label(label="Appl_y to:", use_underline=True), False, False, 0)
    apply_box.pack_start(where, False, False, 0)
    d.add(apply_box)
    for w in (top, bottom, left, right, width, height, gutter):
        w.connect("value-changed", lambda *_: prev.queue_draw())
    for w in (gpos, valign):
        w.connect("changed", lambda *_: prev.queue_draw())
    setdef = d.add_button("Set As De_fault", 1)
    setdef.set_use_underline(True)
    d.get_action_area().reorder_child(setdef, 0)
    multi_changed()
    d.show_all()
    nb.set_current_page(tab)

    def values():
        return {"width": width.mm100, "height": height.mm100, "top": top.mm100,
                "bottom": bottom.mm100, "left": left.mm100, "right": right.mm100,
                "gutter": gutter.mm100, "gutter_top": gpos.get_active() == 1,
                "landscape": landscape.get_active(), "mirror": multi.get_active() == 1,
                "start": start.get_active(), "diff_odd_even": odd_even.get_active(),
                "diff_first": first.get_active(), "header_edge": h_edge.mm100,
                "footer_edge": f_edge.mm100, "valign": VALIGN[max(0, valign.get_active())][1],
                "header": info["header"], "footer": info["footer"], "columns": None}
    while True:
        r = d.run()
        if r == 1:
            if win.dialogs.confirm(
                    "Do you want to change the default settings for page setup?\n\n"
                    "This change will affect all new documents based on the Normal "
                    "template.", yes="Yes", no="No"):
                v = values()
                do_default(v)
                do_apply(v, where.get_active())
                break
            continue
        if r == Gtk.ResponseType.OK:
            do_apply(values(), where.get_active())
        break
    d.destroy()
    win.focus_document()


def set_default(win, v):
    def fn(doc):
        fam = doc.getStyleFamilies().getByName("PageStyles")
        for name in ("Standard", "Default Page Style"):
            if fam.hasByName(name):
                apply(doc, fam.getByName(name), dict(v, start=2))
                break
    try:
        win.app._edit_normal_template(fn)
    except Exception as e:
        print("page default:", e)


def mirrored_margins(m):
    ps = docapi.page_style(m)
    docapi.set_page(m, top=2540, bottom=2540, left=3175, right=2540)
    _set_layout(ps, "MIRRORED")
