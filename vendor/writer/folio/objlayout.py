"""Pictures and shapes, the rest of the original's layout features: the
Layout dialog (Position, Text Wrapping, Size), Edit Wrap Points, Move with
Text / Fix Position on Page, Crop to Shape, Crop Fill / Fit, and the Glow
and Soft Edges effects."""
import math
import os
import tempfile

from gi.repository import Gdk, GdkPixbuf, Gtk

from ._lazy import Lazy, bridge, docapi, uno
drawing = Lazy("folio.drawing")
from .widgets import FDialog, LengthSpin, combo, grid, heading

# RelOrientation
FRAME, PRINT_AREA, CHAR, PAGE_LEFT, PAGE_RIGHT, PAGE_FRAME, PAGE_PRINT_AREA, TEXT_LINE = \
    0, 1, 2, 3, 4, 7, 8, 9
H_REL = [("Margin", PAGE_PRINT_AREA), ("Page", PAGE_FRAME), ("Column", FRAME),
         ("Character", CHAR), ("Left Margin", PAGE_LEFT), ("Right Margin", PAGE_RIGHT)]
V_REL = [("Margin", PAGE_PRINT_AREA), ("Page", PAGE_FRAME), ("Paragraph", FRAME),
         ("Line", TEXT_LINE)]
H_ALIGN = [("Left", 3), ("Centered", 2), ("Right", 1)]          # HoriOrientation
V_ALIGN = [("Top", 1), ("Centered", 2), ("Bottom", 3)]          # VertOrientation
WRAP_STYLES = [("In line with text", "inline"), ("Square", "square"), ("Tight", "tight"),
               ("Through", "through"), ("Top and bottom", "topbottom"),
               ("Behind text", "behind"), ("In front of text", "front")]
WRAP_SIDES = [("Both sides", "PARALLEL"), ("Left only", "LEFT"), ("Right only", "RIGHT"),
              ("Largest only", "DYNAMIC")]


def _get(obj, name, default=None):
    try:
        return obj.getPropertyValue(name)
    except Exception:
        return default


def _set(obj, name, value):
    try:
        obj.setPropertyValue(name, value)
        return True
    except Exception as e:
        print("layout %s:" % name, e)
        return False


def has(obj, name):
    try:
        return obj.getPropertySetInfo().hasPropertyByName(name)
    except Exception:
        return False


def wrap_of(obj):
    try:
        if obj.AnchorType.value == "AS_CHARACTER":
            return "inline"
    except Exception:
        pass
    mode = getattr(_get(obj, "TextWrap"), "value", "PARALLEL")
    if mode == "THROUGH" or mode == "THROUGHT":
        return "front" if _get(obj, "Opaque", True) else "behind"
    if mode == "NONE":
        return "topbottom"
    if _get(obj, "SurroundContour", False):
        return "tight"
    return "square"


# ================================================================ dialog
def _native(win):
    return getattr(win.engine, "native", False)


def layout_dialog(win, tab=0):
    if _native(win):
        from .native import arrange
        return arrange.layout_dialog(win, tab)
    m = win.engine.model
    obj = drawing.selected_shape(m) if m is not None else None
    if obj is None:
        return
    d = FDialog(win, "Layout")
    nb = Gtk.Notebook()
    d.add(nb)
    inline = wrap_of(obj) == "inline"
    # ---------------------------------------------------- position
    p1 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    p1.set_border_width(10)
    p1.pack_start(heading("Horizontal"), False, False, 0)
    h_al_rb = Gtk.RadioButton.new_with_mnemonic(None, "_Alignment")
    h_abs_rb = Gtk.RadioButton.new_with_mnemonic_from_widget(h_al_rb, "Absolute _position")
    h_al = combo([n for n, _v in H_ALIGN], 0)
    h_rel1 = combo([n for n, _v in H_REL], 0)
    h_pos = LengthSpin(_get(obj, "HoriOrientPosition", 0) or 0, -558800, 558800)
    h_rel2 = combo([n for n, _v in H_REL], 0)
    ho = _get(obj, "HoriOrient", 0)
    hr = _get(obj, "HoriOrientRelation", PAGE_PRINT_AREA)
    hr_i = next((i for i, (_n, v) in enumerate(H_REL) if v == hr), 0)
    if ho and ho in [v for _n, v in H_ALIGN]:
        h_al_rb.set_active(True)
        h_al.set_active(next(i for i, (_n, v) in enumerate(H_ALIGN) if v == ho))
        h_rel1.set_active(hr_i)
    else:
        h_abs_rb.set_active(True)
        h_rel2.set_active(hr_i)
    p1.pack_start(grid([[h_al_rb, h_al, "relative to", h_rel1],
                        [h_abs_rb, h_pos, "to the right of", h_rel2]]), False, False, 0)
    p1.pack_start(heading("Vertical"), False, False, 0)
    v_al_rb = Gtk.RadioButton.new_with_mnemonic(None, "Al_ignment")
    v_abs_rb = Gtk.RadioButton.new_with_mnemonic_from_widget(v_al_rb, "Absolute po_sition")
    v_al = combo([n for n, _v in V_ALIGN], 0)
    v_rel1 = combo([n for n, _v in V_REL], 0)
    v_pos = LengthSpin(_get(obj, "VertOrientPosition", 0) or 0, -558800, 558800)
    v_rel2 = combo([n for n, _v in V_REL], 2)
    vo = _get(obj, "VertOrient", 0)
    vr = _get(obj, "VertOrientRelation", FRAME)
    vr_i = next((i for i, (_n, v) in enumerate(V_REL) if v == vr), 2)
    if vo and vo in [v for _n, v in V_ALIGN]:
        v_al_rb.set_active(True)
        v_al.set_active(next(i for i, (_n, v) in enumerate(V_ALIGN) if v == vo))
        v_rel1.set_active(vr_i)
    else:
        v_abs_rb.set_active(True)
        v_rel2.set_active(vr_i)
    p1.pack_start(grid([[v_al_rb, v_al, "relative to", v_rel1],
                        [v_abs_rb, v_pos, "below", v_rel2]]), False, False, 0)
    p1.pack_start(heading("Options"), False, False, 0)
    move = Gtk.CheckButton.new_with_mnemonic("_Move object with text")
    try:
        move.set_active(obj.AnchorType.value != "AT_PAGE")
    except Exception:
        move.set_active(True)
    lock = Gtk.CheckButton.new_with_mnemonic("_Lock anchor")
    overlap = Gtk.CheckButton.new_with_mnemonic("Allow o_verlap")
    overlap.set_active(bool(_get(obj, "AllowOverlap", True)))
    overlap.set_sensitive(has(obj, "AllowOverlap"))
    cell = Gtk.CheckButton.new_with_mnemonic("La_yout in table cell")
    cell.set_active(bool(_get(obj, "IsFollowingTextFlow", True)))
    og = Gtk.Grid(column_spacing=30, row_spacing=4)
    og.attach(move, 0, 0, 1, 1)
    og.attach(lock, 0, 1, 1, 1)
    og.attach(overlap, 1, 0, 1, 1)
    og.attach(cell, 1, 1, 1, 1)
    p1.pack_start(og, False, False, 0)
    p1.set_sensitive(not inline)
    # ---------------------------------------------------- wrapping
    p2 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    p2.set_border_width(10)
    p2.pack_start(heading("Wrapping style"), False, False, 0)
    cur = wrap_of(obj)
    radios = []
    wg = Gtk.Grid(column_spacing=18, row_spacing=4)
    first = None
    for i, (lab, key) in enumerate(WRAP_STYLES):
        rb = Gtk.RadioButton.new_with_label_from_widget(first, lab)
        first = first or rb
        rb.set_active(key == cur)
        radios.append((rb, key))
        wg.attach(rb, i % 4, i // 4, 1, 1)
    p2.pack_start(wg, False, False, 0)
    p2.pack_start(heading("Wrap text"), False, False, 0)
    side_now = getattr(_get(obj, "TextWrap"), "value", "PARALLEL")
    sides = []
    sg = Gtk.Box(spacing=18)
    first = None
    for lab, key in WRAP_SIDES:
        rb = Gtk.RadioButton.new_with_label_from_widget(first, lab)
        first = first or rb
        rb.set_active(key == side_now)
        sides.append((rb, key))
        sg.pack_start(rb, False, False, 0)
    p2.pack_start(sg, False, False, 0)
    p2.pack_start(heading("Distance from text"), False, False, 0)
    dt = LengthSpin(_get(obj, "TopMargin", 0) or 0, 0, 55880)
    db = LengthSpin(_get(obj, "BottomMargin", 0) or 0, 0, 55880)
    dl = LengthSpin(_get(obj, "LeftMargin", 318) or 0, 0, 55880)
    dr = LengthSpin(_get(obj, "RightMargin", 318) or 0, 0, 55880)
    p2.pack_start(grid([["To_p", dt, "L_eft", dl], ["_Bottom", db, "Ri_ght", dr]]),
                  False, False, 0)

    def wrap_sens(*_):
        key = next(k for rb, k in radios if rb.get_active())
        for rb, _k in sides:
            rb.set_sensitive(key in ("square", "tight", "through"))
        for w in (dt, db):
            w.set_sensitive(key in ("square", "topbottom"))
        for w in (dl, dr):
            w.set_sensitive(key in ("square", "tight", "through"))
        p1.set_sensitive(key != "inline")
    for rb, _k in radios:
        rb.connect("toggled", wrap_sens)
    wrap_sens()
    # ---------------------------------------------------- size
    p3 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    p3.set_border_width(10)
    size = obj.Size
    orig = None
    if drawing.kind_of(obj) == "picture":
        try:
            a = obj.ActualSize
            c = obj.GraphicCrop
            orig = (a.Width - c.Left - c.Right, a.Height - c.Top - c.Bottom)
            if orig[0] <= 0 or orig[1] <= 0:
                orig = None
        except Exception:
            orig = None
    p3.pack_start(heading("Height"), False, False, 0)
    hgt = LengthSpin(size.Height, 10, 558800)
    p3.pack_start(grid([["Abso_lute", hgt]]), False, False, 0)
    p3.pack_start(heading("Width"), False, False, 0)
    wid = LengthSpin(size.Width, 10, 558800)
    p3.pack_start(grid([["Absol_ute", wid]]), False, False, 0)
    p3.pack_start(heading("Rotate"), False, False, 0)
    rot_now = (_get(obj, "GraphicRotation", None) if drawing.kind_of(obj) == "picture"
               else _get(obj, "RotateAngle", 0)) or 0
    rot = Gtk.SpinButton.new_with_range(-360, 360, 1)
    rot.set_value(-(rot_now / 100.0) % 360 if rot_now else 0)
    p3.pack_start(grid([["Rota_tion:", rot, Gtk.Label(label="°")]]), False, False, 0)
    p3.pack_start(heading("Scale"), False, False, 0)
    sh = Gtk.SpinButton.new_with_range(1, 2000, 1)
    sw_ = Gtk.SpinButton.new_with_range(1, 2000, 1)
    base = orig or (size.Width, size.Height)
    sh.set_value(round(100.0 * size.Height / base[1]) if base[1] else 100)
    sw_.set_value(round(100.0 * size.Width / base[0]) if base[0] else 100)
    p3.pack_start(grid([["H_eight:", sh, Gtk.Label(label="%"), "W_idth:", sw_,
                         Gtk.Label(label="%")]]), False, False, 0)
    keep = Gtk.CheckButton.new_with_mnemonic("Lock _aspect ratio")
    keep.set_active(drawing.kind_of(obj) == "picture")
    relorig = Gtk.CheckButton.new_with_mnemonic("_Relative to original picture size")
    relorig.set_active(orig is not None)
    relorig.set_sensitive(orig is not None)
    p3.pack_start(keep, False, False, 0)
    p3.pack_start(relorig, False, False, 0)
    if orig is not None:
        from .widgets import fmt_len
        p3.pack_start(heading("Original size"), False, False, 0)
        ob = Gtk.Box(spacing=20)
        ob.pack_start(Gtk.Label(label="Height:  %s" % fmt_len(orig[1])), False, False, 0)
        ob.pack_start(Gtk.Label(label="Width:  %s" % fmt_len(orig[0])), False, False, 0)
        reset = Gtk.Button(label="R_eset", use_underline=True)
        ob.pack_end(reset, False, False, 0)
        p3.pack_start(ob, False, False, 0)
        reset.connect("clicked", lambda *_: (hgt.set_value(orig[1]), wid.set_value(orig[0]),
                                             rot.set_value(0)))
    busy = [False]
    ratio = size.Width / float(size.Height or 1)

    def from_abs(src, *_):
        if busy[0]:
            return
        busy[0] = True
        try:
            if keep.get_active():
                if src is wid:
                    hgt.set_value(wid.get_value() / ratio)
                else:
                    wid.set_value(hgt.get_value() * ratio)
            sh.set_value(round(100.0 * hgt.get_value() / base[1]))
            sw_.set_value(round(100.0 * wid.get_value() / base[0]))
        finally:
            busy[0] = False

    def from_scale(src, *_):
        if busy[0]:
            return
        busy[0] = True
        try:
            if keep.get_active():
                (sw_ if src is sh else sh).set_value(src.get_value())
            hgt.set_value(base[1] * sh.get_value() / 100.0)
            wid.set_value(base[0] * sw_.get_value() / 100.0)
        finally:
            busy[0] = False
    wid.connect("value-changed", lambda *_: from_abs(wid))
    hgt.connect("value-changed", lambda *_: from_abs(hgt))
    sh.connect("value-changed", lambda *_: from_scale(sh))
    sw_.connect("value-changed", lambda *_: from_scale(sw_))
    nb.append_page(p1, Gtk.Label(label="Position"))
    nb.append_page(p2, Gtk.Label(label="Text Wrapping"))
    nb.append_page(p3, Gtk.Label(label="Size"))
    d.show_all()
    nb.set_current_page(tab)
    if d.ask() == Gtk.ResponseType.OK:
        um = m.getUndoManager()
        um.enterUndoContext("Layout")
        try:
            key = next(k for rb, k in radios if rb.get_active())
            drawing.set_wrap(obj, key)
            if key in ("square", "tight", "through"):
                side = next(k for rb, k in sides if rb.get_active())
                _set(obj, "TextWrap", bridge.enum("com.sun.star.text.WrapTextMode", side))
            if key == "front" or key == "behind":
                _set(obj, "TextWrap", bridge.enum("com.sun.star.text.WrapTextMode", "THROUGH"))
                _set(obj, "Opaque", key == "front")
            for prop, w in (("TopMargin", dt), ("BottomMargin", db), ("LeftMargin", dl),
                            ("RightMargin", dr)):
                _set(obj, prop, int(w.mm100))
            if key != "inline":
                if not move.get_active():
                    drawing.set_anchor_mode(obj, "page")
                elif getattr(_get(obj, "AnchorType"), "value", "") == "AT_PAGE":
                    drawing.set_anchor_mode(obj, "paragraph")
                if h_al_rb.get_active():
                    _set(obj, "HoriOrient", H_ALIGN[h_al.get_active()][1])
                    _set(obj, "HoriOrientRelation", H_REL[h_rel1.get_active()][1])
                else:
                    _set(obj, "HoriOrient", 0)
                    _set(obj, "HoriOrientRelation", H_REL[h_rel2.get_active()][1])
                    _set(obj, "HoriOrientPosition", int(h_pos.mm100))
                if v_al_rb.get_active():
                    _set(obj, "VertOrient", V_ALIGN[v_al.get_active()][1])
                    _set(obj, "VertOrientRelation", V_REL[v_rel1.get_active()][1])
                else:
                    _set(obj, "VertOrient", 0)
                    _set(obj, "VertOrientRelation", V_REL[v_rel2.get_active()][1])
                    _set(obj, "VertOrientPosition", int(v_pos.mm100))
                if has(obj, "AllowOverlap"):
                    _set(obj, "AllowOverlap", overlap.get_active())
                if has(obj, "IsFollowingTextFlow"):
                    _set(obj, "IsFollowingTextFlow", cell.get_active())
            obj.Size = bridge.struct("com.sun.star.awt.Size", Width=int(wid.mm100),
                                     Height=int(hgt.mm100))
            angle = int(round((-rot.get_value()) % 360 * 100))
            if drawing.kind_of(obj) == "picture":
                _set(obj, "GraphicRotation", angle // 10)
            elif has(obj, "RotateAngle"):
                _set(obj, "RotateAngle", angle)
        finally:
            um.leaveUndoContext()
        win.object_call_refresh()
    d.destroy()
    win.focus_document()


# ================================================================ wrap points
def _graphic_png(obj):
    gp = bridge.create("com.sun.star.graphic.GraphicProvider")
    fd, path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    from .engine import file_url
    gp.storeGraphic(obj.Graphic, (bridge.prop("URL", file_url(path)),
                                  bridge.prop("MimeType", "image/png")))
    return path


def edit_wrap_points(win):
    """Wrap points around the picture: drag a point to change where text
    wraps; text wraps tightly along them."""
    if _native(win):
        from .native import arrange
        return arrange.edit_wrap_points(win)
    m = win.engine.model
    obj = drawing.selected_shape(m) if m is not None else None
    if obj is None:
        return
    if wrap_of(obj) not in ("tight", "through"):
        drawing.set_wrap(obj, "tight")
    pix = None
    if drawing.kind_of(obj) == "picture":
        try:
            path = _graphic_png(obj)
            pix = GdkPixbuf.Pixbuf.new_from_file(path)
            os.unlink(path)
        except Exception as e:
            print("wrap points image:", e)
    W, H = (pix.get_width(), pix.get_height()) if pix is not None else (400, 300)
    pts = []
    try:
        poly = obj.ContourPolyPolygon
        if poly and len(poly) and len(poly[0]) >= 3:
            pixel = bool(_get(obj, "IsPixelContour", True))
            sx = 1.0 if pixel else W / float(obj.Size.Width)
            sy = 1.0 if pixel else H / float(obj.Size.Height)
            pts = [[p.X * sx, p.Y * sy] for p in poly[0]]
    except Exception:
        pts = []
    if len(pts) > 24:
        pts = _simplify(pts, 24)
    if not pts:
        pts = [[0, 0], [W / 2.0, 0], [W, 0], [W, H / 2.0], [W, H], [W / 2.0, H], [0, H],
               [0, H / 2.0]]
    scale = min(480.0 / W, 360.0 / H, 1.0)
    d = FDialog(win, "Edit Wrap Points")
    hint = Gtk.Label(label="Drag a black point to move it. Click the red line to add a "
                           "point; Ctrl+click a point to delete it.", xalign=0)
    hint.set_line_wrap(True)
    hint.set_max_width_chars(60)
    d.add(hint)
    da = Gtk.DrawingArea()
    pad = 12
    da.set_size_request(int(W * scale) + 2 * pad, int(H * scale) + 2 * pad)
    da.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK |
                  Gdk.EventMask.POINTER_MOTION_MASK)
    drag = [None]

    def to_screen(p):
        return pad + p[0] * scale, pad + p[1] * scale

    def draw(_w, cr):
        cr.set_source_rgb(1, 1, 1)
        cr.paint()
        if pix is not None:
            cr.save()
            cr.translate(pad, pad)
            cr.scale(scale, scale)
            Gdk.cairo_set_source_pixbuf(cr, pix, 0, 0)
            cr.paint()
            cr.restore()
        else:
            cr.set_source_rgb(0.85, 0.9, 1)
            cr.rectangle(pad, pad, W * scale, H * scale)
            cr.fill()
        cr.set_source_rgb(0.85, 0.1, 0.1)
        cr.set_line_width(1.2)
        cr.set_dash([4, 3])
        for i, p in enumerate(pts):
            x, y = to_screen(p)
            (cr.move_to if i == 0 else cr.line_to)(x, y)
        cr.close_path()
        cr.stroke()
        cr.set_dash([])
        for p in pts:
            x, y = to_screen(p)
            cr.set_source_rgb(0, 0, 0)
            cr.rectangle(x - 3.5, y - 3.5, 7, 7)
            cr.fill()
        return False

    def nearest(x, y):
        best, bi = 81, None
        for i, p in enumerate(pts):
            sx, sy = to_screen(p)
            dd = (sx - x) ** 2 + (sy - y) ** 2
            if dd < best:
                best, bi = dd, i
        return bi

    def on_segment(x, y):
        for i in range(len(pts)):
            ax, ay = to_screen(pts[i])
            bx, by = to_screen(pts[(i + 1) % len(pts)])
            L = math.hypot(bx - ax, by - ay) or 1
            t = max(0, min(1, ((x - ax) * (bx - ax) + (y - ay) * (by - ay)) / (L * L)))
            px, py = ax + t * (bx - ax), ay + t * (by - ay)
            if math.hypot(px - x, py - y) < 5:
                return i
        return None

    def press(_w, ev):
        i = nearest(ev.x, ev.y)
        if i is not None:
            if ev.state & Gdk.ModifierType.CONTROL_MASK and len(pts) > 3:
                del pts[i]
                da.queue_draw()
                return True
            drag[0] = i
            return True
        seg = on_segment(ev.x, ev.y)
        if seg is not None:
            pts.insert(seg + 1, [(ev.x - pad) / scale, (ev.y - pad) / scale])
            drag[0] = seg + 1
            da.queue_draw()
        return True

    def motion(_w, ev):
        if drag[0] is not None:
            pts[drag[0]] = [min(W, max(0, (ev.x - pad) / scale)),
                            min(H, max(0, (ev.y - pad) / scale))]
            da.queue_draw()
        return True
    da.connect("draw", draw)
    da.connect("button-press-event", press)
    da.connect("motion-notify-event", motion)
    da.connect("button-release-event", lambda *_: drag.__setitem__(0, None) or True)
    fr = Gtk.Frame()
    fr.add(da)
    d.add(fr)
    d.show_all()
    d._points = pts       # for tests
    if d.ask() == Gtk.ResponseType.OK:
        um = m.getUndoManager()
        um.enterUndoContext("Edit Wrap Points")
        try:
            set_contour(obj, pts, W, H)
        finally:
            um.leaveUndoContext()
    d.destroy()
    win.focus_document()


def _simplify(pts, n):
    """Fewer points along the same outline (drop the points that change its
    shape least, one at a time)."""
    pts = [list(p) for p in pts]
    while len(pts) > n:
        best, bi = None, 0
        for i in range(len(pts)):
            a, b, c = pts[i - 1], pts[i], pts[(i + 1) % len(pts)]
            area = abs((b[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (b[1] - a[1]))
            if best is None or area < best:
                best, bi = area, i
        del pts[bi]
    return pts


def set_contour(obj, pts, W, H):
    pixel = drawing.kind_of(obj) == "picture"
    if not pixel:
        s = obj.Size
        pts = [[p[0] * s.Width / float(W), p[1] * s.Height / float(H)] for p in pts]
    seq = tuple(bridge.struct("com.sun.star.awt.Point", X=int(round(x)), Y=int(round(y)))
                for x, y in pts)
    uno.invoke(obj, "setPropertyValue", ("ContourPolyPolygon", uno.Any(
        "[][]com.sun.star.awt.Point", (seq,))))
    _set(obj, "SurroundContour", True)


# ================================================================ crop
def aspect_fill(obj):
    """Crop > Fill: the picture fills its frame, cropping what doesn't fit."""
    s = obj.Size
    a = obj.ActualSize
    if not (a.Width and a.Height and s.Width and s.Height):
        return
    target = s.Width / float(s.Height)
    crop = bridge.struct("com.sun.star.text.GraphicCrop", Top=0, Bottom=0, Left=0, Right=0)
    if a.Width / float(a.Height) > target:
        keep_w = a.Height * target
        cut = int((a.Width - keep_w) / 2)
        crop.Left = crop.Right = cut
    else:
        keep_h = a.Width / target
        cut = int((a.Height - keep_h) / 2)
        crop.Top = crop.Bottom = cut
    obj.GraphicCrop = crop
    obj.Size = s


def aspect_fit(obj):
    """Crop > Fit: the whole picture shown inside the current frame size."""
    s = obj.Size
    a = obj.ActualSize
    if not (a.Width and a.Height and s.Width and s.Height):
        return
    obj.GraphicCrop = bridge.struct("com.sun.star.text.GraphicCrop", Top=0, Bottom=0,
                                    Left=0, Right=0)
    r = min(s.Width / float(a.Width), s.Height / float(a.Height))
    obj.Size = bridge.struct("com.sun.star.awt.Size", Width=int(a.Width * r),
                             Height=int(a.Height * r))


CROP_SHAPES = [("Rectangle", "rectangle"), ("Rounded Rectangle", "round-rectangle"),
               ("Oval", "ellipse"), ("Triangle", "isosceles-triangle"),
               ("Right Triangle", "right-triangle"), ("Diamond", "diamond"),
               ("Pentagon", "pentagon"), ("Hexagon", "hexagon"), ("Octagon", "octagon"),
               ("Parallelogram", "parallelogram"), ("Trapezoid", "trapezoid"),
               ("Star: 5 Points", "star5"), ("Heart", "heart"), ("Cloud", "cloud"),
               ("Arrow: Right", "right-arrow"), ("Chevron", "chevron")]


def crop_to_shape(win, kind):
    """Replace the picture by a shape of that kind filled with the picture
    (the same size and place)."""
    if _native(win):
        from .native import arrange
        return arrange.crop_to_shape(win, kind)
    m = win.engine.model
    obj = drawing.selected_shape(m) if m is not None else None
    if obj is None or drawing.kind_of(obj) != "picture":
        return
    um = m.getUndoManager()
    um.enterUndoContext("Crop to Shape")
    try:
        size = obj.Size
        anchor = obj.getAnchor()
        shape = m.createInstance("com.sun.star.drawing.CustomShape")
        shape.Size = size
        shape.AnchorType = obj.AnchorType
        if anchor is None:          # fixed on a page
            text = m.getText()
            m.getDrawPage().add(shape)
            _set(shape, "AnchorPageNo", _get(obj, "AnchorPageNo", 1))
        else:
            text = anchor.getText()
            cur = text.createTextCursorByRange(anchor.getStart())
            text.insertTextContent(cur, shape, False)
        for prop in ("HoriOrient", "HoriOrientRelation", "HoriOrientPosition", "VertOrient",
                     "VertOrientRelation", "VertOrientPosition", "TextWrap", "Opaque",
                     "LeftMargin", "RightMargin", "TopMargin", "BottomMargin", "Description",
                     "Title"):
            v = _get(obj, prop)
            if v is not None:
                _set(shape, prop, v)
        uno.invoke(shape, "setPropertyValue", ("CustomShapeGeometry", uno.Any(
            "[]com.sun.star.beans.PropertyValue", (bridge.prop("Type", kind),))))
        shape.FillStyle = bridge.enum("com.sun.star.drawing.FillStyle", "BITMAP")
        try:
            shape.FillBitmap = obj.Graphic.queryInterface(
                uno.getTypeByName("com.sun.star.awt.XBitmap")) or obj.Graphic
        except Exception:
            shape.FillBitmap = obj.Graphic
        shape.FillBitmapMode = bridge.enum("com.sun.star.drawing.BitmapMode", "STRETCH")
        shape.LineStyle = bridge.enum("com.sun.star.drawing.LineStyle", "NONE")
        shape.Size = size
        try:
            text.removeTextContent(obj)
        except Exception:
            obj.dispose()
        docapi.controller(m).select(shape)
    except Exception as e:
        print("crop to shape:", e)
    finally:
        um.leaveUndoContext()


# ================================================================ effects
GLOWS = [("No Glow", 0, None)] + [
    ("Glow: %g pt; %s" % (pt, name), pt, col) for pt in (5, 8, 11, 18)
    for name, col in (("Blue, Accent color 1", 0x4472C4), ("Orange, Accent color 2", 0xED7D31),
                      ("Gold, Accent color 4", 0xFFC000), ("Green, Accent color 6", 0x70AD47))]
SOFT = [("No Soft Edges", 0)] + [("%g Point" % p, p) for p in (1, 2.5, 5, 10, 25, 50)]


def supports_glow(obj):
    return has(obj, "GlowEffectRadius")


def set_glow(obj, pt, color=None):
    if not supports_glow(obj):
        return False
    _set(obj, "GlowEffectRadius", int(pt * 2540 / 72.0))
    if color is not None:
        _set(obj, "GlowEffectColor", int(color))
        _set(obj, "GlowEffectTransparency", 60)
    return True


def set_soft_edges(obj, pt):
    if not has(obj, "SoftEdgeRadius"):
        return False
    _set(obj, "SoftEdgeRadius", int(pt * 2540 / 72.0))
    return True
