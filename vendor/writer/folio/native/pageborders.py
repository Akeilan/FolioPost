"""Design > Page Borders with the new engine: box, shadow or none, line
style, colour and width, or an art border (pictures around the page),
applied to the whole document or the caret's section."""
import re

import cairo
from gi.repository import Gtk

from ..widgets import FDialog, color_button, combo, combo_text, grid, heading

STYLES = [("Single", "single"), ("Double", "double"), ("Dotted", "dotted"), ("Dashed", "dashed"),
          ("Dot dash", "dotDash"), ("Thick", "thick"), ("Triple", "triple"),
          ("Thin-thick", "thinThickSmallGap"), ("Thick-thin", "thickThinSmallGap"),
          ("Wave", "wave"), ("3-D Emboss", "threeDEmboss"), ("3-D Engrave", "threeDEngrave")]
WIDTHS = [0.25, 0.5, 0.75, 1, 1.5, 2.25, 3, 4.5, 6]
APPLY = ["Whole document", "This section", "This section - First page only",
         "This section - All except first page"]


def _pretty(name):
    """'balloons3Colors' -> 'Balloons 3 colors'."""
    s = re.sub(r"(?<=[a-z])(?=[A-Z0-9])", " ", name)
    return s[:1].upper() + s[1:].lower()


def dialog(win):
    ed = win.engine.ed
    if ed is None:
        return
    arts = ed.art_names()
    d = FDialog(win, "Borders and Shading")
    d.add(heading("Page Border"))
    body = Gtk.Box(spacing=18)
    d.add(body)
    left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    body.pack_start(left, False, False, 0)
    left.pack_start(Gtk.Label(label="Setting:", xalign=0), False, False, 0)
    group = None
    setting = {}
    for label in ("None", "Box", "Shadow"):
        rb = Gtk.RadioButton.new_with_label_from_widget(group, label)
        group = group or rb
        setting[label] = rb
        left.pack_start(rb, False, False, 0)
    setting["Box"].set_active(True)
    style = combo([s[0] for s in STYLES], 0)
    color = color_button(0)
    width = combo(["%g pt" % w for w in WIDTHS], 1)
    art = combo(["(none)"] + [_pretty(a) for a in arts], 0)
    art_w = Gtk.SpinButton.new_with_range(1, 31, 1)
    art_w.set_value(15)
    mid = grid([["St_yle:", style], ["_Color:", color], ["_Width:", width], ["A_rt:", art],
                ["Art width (pt):", art_w]])
    body.pack_start(mid, False, False, 0)
    right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    body.pack_start(right, False, False, 0)
    right.pack_start(Gtk.Label(label="Preview", xalign=0), False, False, 0)
    prev = Gtk.DrawingArea()
    prev.set_size_request(150, 190)
    right.pack_start(prev, False, False, 0)
    apply_to = combo(APPLY, 0)
    measure = combo(["Text", "Edge of page"], 1)
    d.add(grid([["Appl_y to:", apply_to], ["Measure from:", measure]]))

    def spec():
        """(val, width pt, colour or None) or None for no border."""
        if setting["None"].get_active():
            return None
        ai = art.get_active()
        c = color.color if color.color is not None and color.color >= 0 else None
        if ai > 0:
            return arts[ai - 1], art_w.get_value(), c
        return STYLES[style.get_active()][1], WIDTHS[width.get_active()], c

    def draw(w, cr):
        a = w.get_allocation()
        sp = spec()
        cr.set_source_rgb(0.85, 0.85, 0.85)
        cr.paint()
        pw, ph = a.width - 20, a.height - 20
        if sp is None:
            cr.set_source_rgb(1, 1, 1)
            cr.rectangle(10, 10, pw, ph)
            cr.fill()
            return
        val, wpt, c = sp
        # the border at preview scale (a page is about 8.5in tall)
        scale = ph / 792.0 * 2.5
        iw, ih, stride, data = ed.border_sample(val, pw, ph, max(1.0, wpt * scale), c)
        surf = cairo.ImageSurface.create_for_data(bytearray(data), cairo.FORMAT_ARGB32, iw, ih, stride)
        cr.set_source_surface(surf, 10, 10)
        cr.paint()
        if setting["Shadow"].get_active():
            cr.set_source_rgb(0.4, 0.4, 0.4)
            cr.rectangle(10 + pw, 14, 3, ph)
            cr.rectangle(14, 10 + ph, pw, 3)
            cr.fill()
    prev.connect("draw", draw)
    for wdg in (style, width, art):
        wdg.connect("changed", lambda *_: prev.queue_draw())
    art_w.connect("value-changed", lambda *_: prev.queue_draw())
    for rb in setting.values():
        rb.connect("toggled", lambda *_: prev.queue_draw())
    color.connect("clicked", lambda *_: prev.queue_draw())
    r = d.ask()
    sp = spec()
    shadow = setting["Shadow"].get_active()
    which = apply_to.get_active()
    from_page = measure.get_active() == 1
    d.done()
    if r != Gtk.ResponseType.OK:
        return
    sec = None if which == 0 else ed.current_section()
    if sp is None:
        ed.set_page_borders(sec, None)
    else:
        val, wpt, c = sp
        is_art = val in arts
        sz = int(round(wpt)) if is_art else int(round(wpt * 8))
        space = 24 if from_page else 4
        col = "%06X" % c if c is not None else "auto"
        sides = "".join('<w:%s w:val="%s" w:sz="%d" w:space="%d" w:color="%s"%s/>' % (
            s, val, sz, space, col, ' w:shadow="1"' if shadow and not is_art else "")
            for s in ("top", "left", "bottom", "right"))
        display = {2: ' w:display="firstPage"', 3: ' w:display="notFirstPage"'}.get(which, "")
        offset = ' w:offsetFrom="page"' if from_page else ""
        ed.set_page_borders(sec, "<w:pgBorders%s%s>%s</w:pgBorders>" % (offset, display, sides))
    win.engine.view.document_changed()
