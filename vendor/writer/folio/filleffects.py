"""Page Color > Fill Effects: gradient, pattern and picture page
backgrounds, as in the original."""
from ._lazy import uno
from gi.repository import Gtk

from . import bridge, docapi
from .widgets import FDialog, Preview, color_button, combo, grid, heading, rgb

STYLES = [("Horizontal", 0), ("Vertical", 90), ("Diagonal up", 45), ("Diagonal down", 135),
          ("From corner", "corner"), ("From center", "center")]
PATTERNS = [("5%", 0, 0, 30), ("Light horizontal", 0, 0, 8), ("Light vertical", 0, 900, 8),
            ("Light upward diagonal", 0, 450, 8), ("Light downward diagonal", 0, 1350, 8),
            ("Small grid", 1, 0, 8), ("Large grid", 1, 0, 20), ("Diagonal cross", 1, 450, 10),
            ("Wide horizontal", 0, 0, 4), ("Wide vertical", 0, 900, 4)]


def _apply(m, spec):
    styles = []
    try:
        from .pagesetup import used_page_styles
        styles = used_page_styles(m)
    except Exception:
        styles = [docapi.page_style(m)]
    for ps in styles:
        try:
            ps.BackgroundFullSize = True
        except Exception:
            pass
        kind = spec["kind"]
        if kind == "gradient":
            g = bridge.struct("com.sun.star.awt.Gradient")
            c1, c2 = spec["c1"], spec["c2"]
            st = spec["style"]
            if st == "center":
                g.Style = bridge.enum("com.sun.star.awt.GradientStyle", "RADIAL")
                g.XOffset = g.YOffset = 50
            elif st == "corner":
                g.Style = bridge.enum("com.sun.star.awt.GradientStyle", "RADIAL")
                g.XOffset = g.YOffset = 0
            else:
                g.Style = bridge.enum("com.sun.star.awt.GradientStyle", "LINEAR")
                g.Angle = int(st) * 10
            g.StartColor, g.EndColor = c1, c2
            g.StartIntensity = g.EndIntensity = 100
            g.StepCount = 0
            ps.FillStyle = bridge.enum("com.sun.star.drawing.FillStyle", "GRADIENT")
            uno.invoke(ps, "setPropertyValue", ("FillGradient", uno.Any("com.sun.star.awt.Gradient", g)))
        elif kind == "pattern":
            _n, style, angle, dist = PATTERNS[spec["pattern"]]
            h = bridge.struct("com.sun.star.drawing.Hatch")
            h.Style = bridge.enum("com.sun.star.drawing.HatchStyle",
                                  "DOUBLE" if style else "SINGLE")
            h.Color = spec["fg"]
            h.Distance = dist * 10
            h.Angle = angle
            ps.FillStyle = bridge.enum("com.sun.star.drawing.FillStyle", "HATCH")
            uno.invoke(ps, "setPropertyValue", ("FillHatch", uno.Any("com.sun.star.drawing.Hatch", h)))
            try:
                ps.FillBackground = True
                ps.FillColor = spec["bg"]
            except Exception:
                pass
        elif kind == "picture":
            prov = bridge.create("com.sun.star.graphic.GraphicProvider")
            g = prov.queryGraphic((bridge.prop("URL", docapi.uno_url(spec["path"])),))
            ps.FillStyle = bridge.enum("com.sun.star.drawing.FillStyle", "BITMAP")
            ps.FillBitmap = g
            ps.FillBitmapMode = bridge.enum("com.sun.star.drawing.BitmapMode",
                                            "STRETCH" if not spec.get("tile") else "REPEAT")


def _apply_native(win, spec):
    ed = win.engine.ed
    k = spec["kind"]
    h = lambda c: "%06X" % (int(c) & 0xFFFFFF)  # noqa: E731
    if k == "gradient":
        st = spec["style"]
        if st in ("center", "corner"):
            ed.set_page_fill("gradientRadial", h(spec["c1"]), h(spec["c2"]), 0.0, ".5,.5" if st == "center" else "")
        else:
            ed.set_page_fill("gradient", h(spec["c1"]), h(spec["c2"]), float(st))
    elif k == "pattern":
        name = PATTERNS[spec["pattern"]][0]
        ed.set_page_fill("pattern", h(spec["fg"]), h(spec["bg"]), 0.0, "", name)
    elif k == "picture":
        import os
        ext = os.path.splitext(spec["path"])[1].lstrip(".").lower() or "png"
        ext = "jpeg" if ext == "jpg" else ext
        with open(spec["path"], "rb") as fh:
            data = fh.read()
        ed.set_page_fill("tile" if spec.get("tile") else "frame", "FFFFFF", "FFFFFF", 0.0, "",
                         os.path.basename(spec["path"]), data, ext)
    win.engine.view.after_edit()


def dialog(win):
    native = getattr(win.engine, "native", False)
    m = None if native else win.engine.model
    if m is None and not native:
        return
    d = FDialog(win, "Fill Effects")
    nb = Gtk.Notebook()
    d.add(nb)
    # gradient
    g = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    g.set_border_width(10)
    g.pack_start(heading("Colors"), False, False, 0)
    one = Gtk.RadioButton.new_with_mnemonic(None, "_One color")
    two = Gtk.RadioButton.new_with_mnemonic_from_widget(one, "_Two colors")
    two.set_active(True)
    c1 = color_button(0x4472C4)
    c2 = color_button(0xFFFFFF)
    g.pack_start(grid([[one, "Color _1:", c1], [two, "Color _2:", c2]]), False, False, 0)
    g.pack_start(heading("Shading styles"), False, False, 0)
    sty = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
    srb = []
    first = None
    for lab, v in STYLES:
        rb = Gtk.RadioButton.new_with_label_from_widget(first, lab)
        first = first or rb
        srb.append((rb, v))
        sty.pack_start(rb, False, False, 0)
    g.pack_start(sty, False, False, 0)

    def gspec():
        a = c1.color if c1.color is not None and c1.color >= 0 else 0x4472C4
        b = c2.color if two.get_active() and c2.color is not None and c2.color >= 0 \
            else 0xFFFFFF
        st = next(v for rb, v in srb if rb.get_active())
        return {"kind": "gradient", "c1": a, "c2": b, "style": st}
    nb.append_page(g, Gtk.Label(label="Gradient"))
    # pattern
    p = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    p.set_border_width(10)
    pat = combo([x[0] for x in PATTERNS], 0)
    fg = color_button(0x000000)
    bg = color_button(0xFFFFFF)
    p.pack_start(grid([["_Pattern:", pat], ["_Foreground:", fg], ["_Background:", bg]]),
                 False, False, 0)
    nb.append_page(p, Gtk.Label(label="Pattern"))
    # picture
    pc = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    pc.set_border_width(10)
    path = [None]
    lab = Gtk.Label(label="(no picture)", xalign=0)
    selb = Gtk.Button(label="Select _Picture...", use_underline=True)

    def pick(*_):
        f = win.dialogs.pick_file("Select Picture", ["*.png", "*.jpg", "*.jpeg", "*.gif",
                                                     "*.bmp", "*.svg"], "All Pictures")
        if f:
            path[0] = f
            lab.set_text(f)
            prev.queue_draw()
    selb.connect("clicked", pick)
    tile = Gtk.CheckButton.new_with_mnemonic("_Tile picture")
    pc.pack_start(selb, False, False, 0)
    pc.pack_start(lab, False, False, 0)
    pc.pack_start(tile, False, False, 0)
    nb.append_page(pc, Gtk.Label(label="Picture"))
    # sample
    d.add(heading("Sample"))

    def draw(cr, W, H):
        pg = nb.get_current_page()
        if pg == 0:
            sp = gspec()
            import cairo
            st = sp["style"]
            if st in ("center", "corner"):
                cx, cy = (W / 2, H / 2) if st == "center" else (0, 0)
                grad = cairo.RadialGradient(cx, cy, 0, cx, cy, max(W, H))
            else:
                import math
                a = math.radians(int(st))
                grad = cairo.LinearGradient(W / 2 - math.sin(a) * W / 2, H / 2 - math.cos(a) * H / 2,
                                            W / 2 + math.sin(a) * W / 2, H / 2 + math.cos(a) * H / 2)
            grad.add_color_stop_rgb(0, *rgb(sp["c1"]))
            grad.add_color_stop_rgb(1, *rgb(sp["c2"]))
            cr.set_source(grad)
            cr.paint()
        elif pg == 1:
            cr.set_source_rgb(*rgb(bg.color if bg.color is not None and bg.color >= 0
                                   else 0xFFFFFF))
            cr.paint()
            cr.set_source_rgb(*rgb(fg.color if fg.color is not None and fg.color >= 0 else 0))
            cr.set_line_width(1)
            _n, style, angle, dist = PATTERNS[max(0, pat.get_active())]
            step = max(3, dist / 2)
            x = -H
            while x < W + H:
                if angle == 0:
                    cr.move_to(0, x)
                    cr.line_to(W, x)
                elif angle == 900:
                    cr.move_to(x, 0)
                    cr.line_to(x, H)
                else:
                    cr.move_to(x, 0)
                    cr.line_to(x + (H if angle == 450 else -H), H)
                if style:
                    cr.move_to(x, 0)
                    cr.line_to(x, H)
                x += step
            cr.stroke()
        else:
            cr.set_source_rgb(0.95, 0.95, 0.95)
            cr.paint()
    prev = Preview(draw, 120, 90)
    d.add(prev)
    nb.connect("switch-page", lambda *_: prev.queue_draw())
    for rb, _v in srb:
        rb.connect("toggled", lambda *_: prev.queue_draw())
    pat.connect("changed", lambda *_: prev.queue_draw())
    d.show_all()
    if d.ask() == Gtk.ResponseType.OK:
        pg = nb.get_current_page()
        spec = gspec() if pg == 0 else {"kind": "pattern", "pattern": max(0, pat.get_active()),
                                        "fg": fg.color if fg.color is not None and
                                        fg.color >= 0 else 0,
                                        "bg": bg.color if bg.color is not None and
                                        bg.color >= 0 else 0xFFFFFF} if pg == 1 else \
            ({"kind": "picture", "path": path[0], "tile": tile.get_active()} if path[0] else None)
        if spec and native:
            try:
                _apply_native(win, spec)
            except Exception as e:
                win.dialogs.message("The fill couldn't be applied: %s" % e)
        elif spec:
            um = m.getUndoManager()
            um.enterUndoContext("Page Color")
            try:
                _apply(m, spec)
            except Exception as e:
                win.dialogs.message("The fill couldn't be applied: %s" % e)
            finally:
                um.leaveUndoContext()
    d.destroy()
    win.focus_document()
