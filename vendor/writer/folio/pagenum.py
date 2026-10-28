"""Insert > Page Number, as in the original: Top of Page, Bottom of Page,
Page Margins and Current Position each open a gallery of ready-made page
numbers; then Format Page Numbers and Remove Page Numbers."""
import cairo
from gi.repository import Gtk

from . import bridge, docapi

TW, TH = 64, 82        # thumbnail size


def _thumb(where, align, style):
    """A little page with grey text lines and the number where it goes."""
    area = Gtk.DrawingArea()
    area.set_size_request(TW, TH)

    def draw(_w, cr):
        cr.set_source_rgb(1, 1, 1)
        cr.rectangle(2, 2, TW - 4, TH - 4)
        cr.fill_preserve()
        cr.set_source_rgb(0.7, 0.7, 0.7)
        cr.set_line_width(1)
        cr.stroke()
        cr.set_source_rgb(0.85, 0.85, 0.85)
        top = 18 if where == "top" else 10
        for i in range(8):
            y = top + i * 6
            if y > TH - 18:
                break
            cr.rectangle(10, y, TW - 20 - (8 if i % 3 == 2 else 0), 2.5)
            cr.fill()
        txt = {"plain": "1", "xofy": "Page 1 of 3", "bold": "1", "accent": "1"}[style]
        cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL,
                            cairo.FONT_WEIGHT_BOLD if style == "bold" else
                            cairo.FONT_WEIGHT_NORMAL)
        cr.set_font_size(6.5 if style == "xofy" else 8)
        ext = cr.text_extents(txt)
        if where in ("top", "bottom", "here"):
            y = 11 if where == "top" else (TH - 7 if where == "bottom" else 40)
            x = {"left": 8, "center": (TW - ext.width) / 2,
                 "right": TW - 8 - ext.width}[align]
        else:      # margin
            x = TW - 9 if align == "right" else 4
            y = TH / 2
        if style == "accent":
            cr.set_source_rgb(0.18, 0.42, 0.25)
            cr.arc(x + ext.width / 2, y - ext.height / 2, 6, 0, 6.3)
            cr.fill()
            cr.set_source_rgb(1, 1, 1)
        else:
            cr.set_source_rgb(0.15, 0.15, 0.15)
        cr.move_to(x, y)
        cr.show_text(txt)
        return False
    area.connect("draw", draw)
    return area


GALLERIES = {
    "Top of Page": [("Plain Number 1", "top", "left", "plain"),
                    ("Plain Number 2", "top", "center", "plain"),
                    ("Plain Number 3", "top", "right", "plain"),
                    ("Bold Numbers", "top", "right", "bold"),
                    ("Page X of Y", "top", "right", "xofy")],
    "Bottom of Page": [("Plain Number 1", "bottom", "left", "plain"),
                       ("Plain Number 2", "bottom", "center", "plain"),
                       ("Plain Number 3", "bottom", "right", "plain"),
                       ("Bold Numbers", "bottom", "center", "bold"),
                       ("Page X of Y", "bottom", "center", "xofy")],
    "Page Margins": [("Circle, Right", "margin", "right", "accent"),
                     ("Plain Number, Right", "margin", "right", "plain"),
                     ("Plain Number, Left", "margin", "left", "plain")],
    "Current Position": [("Plain Number", "here", "left", "plain"),
                         ("Page X of Y", "here", "left", "xofy")],
}


def insert(win, where, align, style):
    if getattr(win, "native", False):
        _insert_native(win, where, align, style)
        return
    m = win.engine.model
    if m is None:
        return
    um = m.getUndoManager()
    um.enterUndoContext("Page Number")
    try:
        if where in ("top", "bottom"):
            docapi.insert_header_footer(m, "header" if where == "top" else "footer",
                                        page_numbers="page-x-of-y" if style == "xofy"
                                        else "plain", align=align)
            if style == "bold":
                ps = docapi.page_style(m)
                body = ps.HeaderText if where == "top" else ps.FooterText
                c = body.createTextCursor()
                c.gotoStart(False)
                c.gotoEnd(True)
                c.CharWeight = 150.0
        elif where == "here":
            vc = docapi.view_cursor(m)
            text = vc.getText()
            cur = text.createTextCursorByRange(vc.getStart())
            pf = m.createInstance("com.sun.star.text.textfield.PageNumber")
            pf.NumberingType = 4
            pf.SubType = bridge.enum("com.sun.star.text.PageNumberType", "CURRENT")
            if style == "xofy":
                text.insertString(cur, "Page ", False)
                text.insertTextContent(cur, pf, False)
                text.insertString(cur, " of ", False)
                cf = m.createInstance("com.sun.star.text.textfield.PageCount")
                cf.NumberingType = 4
                text.insertTextContent(cur, cf, False)
            else:
                text.insertTextContent(cur, pf, False)
            vc.gotoRange(cur.getEnd(), False)
        else:
            _margin_number(m, align, style)
    finally:
        um.leaveUndoContext()
    win.engine.sync(win.refresh_hf)


def _margin_number(m, side, style):
    """A page number in the side margin, half way down every page: a small
    frame anchored in the header, positioned against the page."""
    ps = docapi.page_style(m)
    docapi.enable_header_footer(m, "header", ps)
    body = ps.HeaderText
    cur = body.createTextCursor()
    cur.gotoEnd(False)
    fr = m.createInstance("com.sun.star.text.TextFrame")
    fr.AnchorType = bridge.enum("com.sun.star.text.TextContentAnchorType", "AT_PARAGRAPH")
    size = 1000
    fr.Width = size
    fr.Height = size
    try:
        fr.WidthType = 1
        fr.SizeType = 1
    except Exception:
        pass
    body.insertTextContent(cur, fr, False)
    fr.HoriOrient = 0                              # NONE
    fr.HoriOrientRelation = 7                      # page
    width = ps.Width
    edge = ps.RightMargin if side == "right" else ps.LeftMargin
    fr.HoriOrientPosition = int(width - edge / 2 - size / 2) if side == "right" \
        else int(edge / 2 - size / 2)
    fr.VertOrient = 2                              # CENTER
    fr.VertOrientRelation = 7                      # page
    none = bridge.struct("com.sun.star.table.BorderLine2")
    for b in ("LeftBorder", "RightBorder", "TopBorder", "BottomBorder"):
        setattr(fr, b, none)
    for d in ("LeftBorderDistance", "RightBorderDistance", "TopBorderDistance",
              "BottomBorderDistance"):
        setattr(fr, d, 0)
    fr.TextWrap = bridge.enum("com.sun.star.text.WrapTextMode", "THROUGH")
    try:
        fr.TextVerticalAdjust = bridge.enum("com.sun.star.drawing.TextVerticalAdjust",
                                            "CENTER")
    except Exception:
        pass
    if style == "accent":
        fr.BackColor = 0x2E6B3F
        fr.BackTransparent = False
    else:
        fr.BackTransparent = True
    t = fr.getText()
    c = t.createTextCursor()
    c.ParaAdjust = 3
    if style == "accent":
        c.CharColor = 0xFFFFFF
        c.CharWeight = 150.0
    f = m.createInstance("com.sun.star.text.textfield.PageNumber")
    f.NumberingType = 4
    f.SubType = bridge.enum("com.sun.star.text.PageNumberType", "CURRENT")
    t.insertTextContent(c, f, False)
    names = set(m.getTextFrames().getElementNames())
    n = 1
    while "PageNumberFrame%d" % n in names:
        n += 1
    fr.Name = "PageNumberFrame%d" % n


def menu(win):
    """The drop-down: a list whose entries open their galleries."""
    pop = Gtk.Popover()
    stack = Gtk.Stack()
    stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
    stack.set_homogeneous(False)
    main = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, margin=4)

    def entry(label, cb, arrow=False):
        b = Gtk.Button()
        b.set_relief(Gtk.ReliefStyle.NONE)
        row = Gtk.Box(spacing=8)
        row.pack_start(Gtk.Label(label=label, xalign=0), True, True, 0)
        if arrow:
            row.pack_end(Gtk.Image.new_from_icon_name("pan-end-symbolic",
                                                       Gtk.IconSize.MENU), False, False, 0)
        b.add(row)
        b.connect("clicked", lambda *_: cb())
        main.pack_start(b, False, False, 0)

    for name, items in GALLERIES.items():
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, margin=6)
        back = Gtk.Button()
        back.set_relief(Gtk.ReliefStyle.NONE)
        hb = Gtk.Box(spacing=6)
        hb.pack_start(Gtk.Image.new_from_icon_name("pan-start-symbolic", Gtk.IconSize.MENU),
                      False, False, 0)
        t = Gtk.Label(xalign=0)
        t.set_markup("<b>%s</b>" % name)
        hb.pack_start(t, False, False, 0)
        back.add(hb)
        back.connect("clicked", lambda *_: stack.set_visible_child_name("main"))
        page.pack_start(back, False, False, 0)
        flow = Gtk.FlowBox()
        flow.set_selection_mode(Gtk.SelectionMode.NONE)
        flow.set_max_children_per_line(3)
        flow.set_min_children_per_line(3)
        for label, where, align, style in items:
            b = Gtk.Button()
            b.set_relief(Gtk.ReliefStyle.NONE)
            v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            v.pack_start(_thumb(where, align, style), False, False, 0)
            lab = Gtk.Label(label=label)
            lab.set_max_width_chars(12)
            lab.set_line_wrap(True)
            lab.set_justify(Gtk.Justification.CENTER)
            lab.get_style_context().add_class("dim-label")
            v.pack_start(lab, False, False, 0)
            b.add(v)
            b.set_tooltip_text(label)
            b.connect("clicked", lambda _b, a=(where, align, style):
                      (pop.popdown(), insert(win, *a)))
            flow.add(b)
        page.pack_start(flow, False, False, 0)
        stack.add_named(page, name)
        entry(name, lambda n=name: stack.set_visible_child_name(n), arrow=True)
    main.pack_start(Gtk.Separator(), False, False, 3)

    def fmt():
        pop.popdown()
        from . import hfedit
        hfedit.format_dialog(win)

    def remove():
        pop.popdown()
        win.run("remove-page-numbers")
        m = win.engine.model
        if m is not None:
            try:
                for name in list(m.getTextFrames().getElementNames()):
                    if name.startswith("PageNumberFrame"):
                        m.getTextFrames().getByName(name).dispose()
            except Exception:
                pass
    entry("Format Page Numbers...", fmt)
    entry("Remove Page Numbers", remove)
    stack.add_named(main, "main")
    stack.set_visible_child_name("main")
    pop.add(stack)
    pop.connect("closed", lambda *_: stack.set_visible_child_name("main"))
    stack.show_all()
    stack.set_visible_child_name("main")
    return pop


def _insert_native(win, where, align, style):
    ed = win.engine.ed
    if ed is None:
        return
    if where in ("top", "bottom"):
        ok = ed.page_number_in(ed.current_section(), where == "bottom", align, style == "xofy",
                               style == "bold")
        if not ok:
            win.actions._not_yet()
    elif where == "here":
        ed.begin_group("Page Number")
        if style == "xofy":
            ed.type_text("Page ")
            ed.insert_field("PAGE", "1")
            ed.type_text(" of ")
            ed.insert_field("NUMPAGES", "1")
        else:
            ed.insert_field("PAGE", "1")
        ed.end_group()
    elif where == "margin":
        # Page Margins: the number in a box in the side margin, anchored in the
        # header so every page shows it
        pg = ed.caret_page()
        W, H = ed.page_size(pg)
        top, right, bottom, left = ed.page_margins(pg)
        size = 36.0
        x = W - right + (right - size) / 2.0 if align == "right" else (left - size) / 2.0
        y = H / 2.0 - size / 2.0
        ed.begin_group("Page Number")
        try:
            if not ed.page_hf(pg)[0]:
                ed.ensure_header_footer_kind(ed.page_section(pg), False, ed.page_hf_kind(pg))
            ed.edit_header_footer(pg, False)
            ed.move_caret("doc_end", False)
            if ed.insert_shape("textbox", pg, x, y, size, size, "Page Number", False):
                ed.set_align("center")
                ed.insert_field("PAGE", "1")
                ed.select_all()
                if style == "accent":
                    ed.set_color("FFFFFF")
                    ed.toggle("w:b")
                ed.select_story_textbox()
                if style == "accent":
                    ed.object_geometry("ellipse")
                    ed.object_fill('<a:solidFill><a:srgbClr val="4472C4"/></a:solidFill>')
                else:
                    ed.object_fill("<a:noFill/>")
                ed.object_outline("<a:ln><a:noFill/></a:ln>")
                ed.leave_textbox()
                ed.deselect_object()
            ed.edit_header_footer(None)
        finally:
            ed.end_group()
    else:
        win.actions._not_yet()
        return
    win.engine.view.after_edit()
