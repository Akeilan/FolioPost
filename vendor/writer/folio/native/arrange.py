"""Pictures and shapes with the new engine, the rest of Arrange and Size: several
objects selected at once, align and distribute, group / ungroup / regroup, Move
with Text / Fix Position on Page, the Layout dialog, Edit Wrap Points, crop
(handles, aspect ratios, shapes, fill and fit), Remove Background, Compress
Pictures, Merge Shapes, Edit Points and Select Objects."""
import io
import math

from gi.repository import Gdk, GdkPixbuf, Gtk

from ..widgets import FDialog, LengthSpin, combo, grid, heading

PT = 2540.0 / 72.0          # mm100 per point
EMU = 12700.0

CROP_SHAPES = {"rectangle": "rect", "round-rectangle": "roundRect", "ellipse": "ellipse",
               "isosceles-triangle": "triangle", "right-triangle": "rtTriangle", "diamond": "diamond",
               "pentagon": "pentagon", "hexagon": "hexagon", "octagon": "octagon",
               "parallelogram": "parallelogram", "trapezoid": "trapezoid", "star5": "star5",
               "heart": "heart", "cloud": "cloud", "right-arrow": "rightArrow", "chevron": "chevron"}


def _ed(win):
    return win.engine.ed


def _done(win):
    v = win.engine.view
    v.after_edit()
    v.objs.refresh()
    v.queue_draw()
    try:
        win.update_object_tabs()
    except Exception:
        pass


def _flash(win, text):
    try:
        win.status.flash(text)
    except Exception:
        print(text)


def selected(win):
    """[(node, page, x, y, w, h, inline, kind)]"""
    ed = _ed(win)
    return ed.selected_objects() if ed is not None else []


# ================================================================ align, distribute
def align(win, where):
    ed = _ed(win)
    objs = selected(win)
    if not objs:
        return
    mode = getattr(win, "align_mode", "auto")
    ed.begin_group("Align")
    try:
        if len(objs) > 1 and mode in ("auto", "objects"):
            fl = [o for o in objs if not o[6]]
            x0 = min(o[2] for o in fl)
            y0 = min(o[3] for o in fl)
            x1 = max(o[2] + o[4] for o in fl)
            y1 = max(o[3] + o[5] for o in fl)
            for node, _pg, x, y, w, h, inline, _k in fl:
                nx, ny = x, y
                if where == "left":
                    nx = x0
                elif where == "center":
                    nx = (x0 + x1) / 2 - w / 2
                elif where == "right":
                    nx = x1 - w
                elif where == "top":
                    ny = y0
                elif where == "middle":
                    ny = (y0 + y1) / 2 - h / 2
                elif where == "bottom":
                    ny = y1 - h
                ed.select_object_node(node)
                ed.object_move(nx, ny)
        else:
            for node, _pg, _x, _y, _w, _h, inline, _k in objs:
                ed.select_object_node(node)
                if inline:
                    ed.object_set_wrap("square")
                ed.object_align(where, mode == "page")
    finally:
        ed.end_group()
    ed.select_object_nodes([o[0] for o in objs])
    _done(win)


def distribute(win, axis):
    ed = _ed(win)
    objs = [o for o in selected(win) if not o[6]]
    if len(objs) < 3:
        _flash(win, "Select three or more objects to distribute them.")
        return False
    i = 2 if axis == "h" else 3
    size = 4 if axis == "h" else 5
    objs.sort(key=lambda o: o[i])
    first, last = objs[0], objs[-1]
    span = (last[i] + last[size]) - first[i]
    total = sum(o[size] for o in objs)
    gap = (span - total) / (len(objs) - 1)
    pos = first[i] + first[size] + gap
    ed.begin_group("Distribute")
    try:
        for o in objs[1:-1]:
            ed.select_object_node(o[0])
            if axis == "h":
                ed.object_move(pos, o[3])
            else:
                ed.object_move(o[2], pos)
            pos += o[size] + gap
    finally:
        ed.end_group()
    ed.select_object_nodes([o[0] for o in objs])
    _done(win)
    return True


# ================================================================ groups
_LAST_UNGROUP = {}


def group(win):
    ok, msg = _ed(win).object_group()
    if not ok:
        _flash(win, msg)
        return False
    _done(win)
    return True


def ungroup(win):
    ed = _ed(win)
    o = ed.selected_object()
    if o is None or o.get("kind") != "group":
        _flash(win, "Select a group to ungroup it.")
        return False
    made = ed.object_ungroup()
    _LAST_UNGROUP[id(win)] = made
    _done(win)
    return bool(made)


def regroup(win):
    ed = _ed(win)
    nodes = _LAST_UNGROUP.get(id(win)) or []
    live = {n for n, *_r in ed.objects_list()}
    nodes = [n for n in nodes if n in live]
    if len(nodes) < 2:
        _flash(win, "There's nothing to regroup.")
        return False
    ed.select_object_nodes(nodes)
    return group(win)


# ================================================================ position, crop
def set_anchor_mode(win, mode):
    o = _ed(win).selected_object()
    if o is None:
        return
    if o["inline"]:
        _ed(win).object_set_wrap("square")
    _ed(win).object_anchor_mode(mode)
    _done(win)


def crop_to_ratio(win, w, h):
    if _ed(win).crop_to_ratio(float(w), float(h)):
        _done(win)


def aspect_fill(win):
    if _ed(win).crop_aspect(False):
        _done(win)


def aspect_fit(win):
    if _ed(win).crop_aspect(True):
        _done(win)


def crop_mm100(win, l, t, r, b):
    """Crop by lengths (1/100 mm) off each side of what shows now."""
    ed = _ed(win)
    o = ed.selected_object()
    c = ed.object_crop()
    if o is None or c is None:
        return
    vw = 1 - c[0] - c[2]
    vh = 1 - c[1] - c[3]
    w, h = o["w"] * PT, o["h"] * PT
    nc = (c[0] + l / w * vw, c[1] + t / h * vh, c[2] + r / w * vw, c[3] + b / h * vh)
    ed.set_object_crop(*nc)
    _done(win)


def crop_to_shape(win, kind):
    ed = _ed(win)
    o = ed.selected_object()
    if o is None or o["kind"] != "picture":
        return
    ed.object_geometry(CROP_SHAPES.get(kind, kind))
    _done(win)


# ================================================================ crop handles
class CropTool:
    """Black crop handles on the picture's edges; drag them, then press Enter or
    click outside the picture to apply (Esc cancels)."""
    H = 14

    def __init__(self, win):
        self.win = win
        self.active = False
        self.rect = None
        self.cut = [0, 0, 0, 0]
        self.drag = None

    def begin(self):
        v = self.win.engine.view
        o = _ed(self.win).selected_object()
        if o is None or o["kind"] != "picture":
            self.win.dialogs.crop()
            return
        v.objs.refresh()
        self.rect = v.objs.rect()
        self.cut = [0, 0, 0, 0]
        self.active = True
        _flash(self.win, "Drag the black handles to crop. Enter applies, Esc cancels.")
        v.queue_draw()

    def cancel(self):
        self.active = False
        self.drag = None
        self.win.engine.view.queue_draw()

    def apply(self):
        if not self.active:
            return
        s = self.win.engine.view.ppp
        vals = [c / s * PT for c in self.cut]
        self.cancel()
        if any(vals):
            crop_mm100(self.win, *vals)

    def _edges(self):
        x, y, w, h = self.rect
        l, t, r, b = self.cut
        return x + l, y + t, x + w - r, y + h - b

    def _hit(self, ex, ey):
        x0, y0, x1, y1 = self._edges()
        tol = 8
        sides = []
        iy = y0 - tol <= ey <= y1 + tol
        ix = x0 - tol <= ex <= x1 + tol
        if abs(ex - x0) <= tol and iy:
            sides.append(0)
        if abs(ex - x1) <= tol and iy:
            sides.append(2)
        if abs(ey - y0) <= tol and ix:
            sides.append(1)
        if abs(ey - y1) <= tol and ix:
            sides.append(3)
        return sides

    def press(self, ev):
        if ev.button != 1:
            return True
        sides = self._hit(ev.x, ev.y)
        if not sides:
            self.apply()
            return True
        self.drag = (sides, ev.x, ev.y, list(self.cut))
        return True

    def motion(self, ev):
        if self.drag is None:
            return True
        sides, sx, sy, start = self.drag
        _x, _y, w, h = self.rect
        dx, dy = ev.x - sx, ev.y - sy
        cut = list(start)
        for s in sides:
            if s == 0:
                cut[0] = max(0, min(w - cut[2] - 10, start[0] + dx))
            elif s == 2:
                cut[2] = max(0, min(w - cut[0] - 10, start[2] - dx))
            elif s == 1:
                cut[1] = max(0, min(h - cut[3] - 10, start[1] + dy))
            elif s == 3:
                cut[3] = max(0, min(h - cut[1] - 10, start[3] - dy))
        self.cut = cut
        return True

    def release(self, ev):
        self.drag = None
        return True

    def draw(self, cr):
        if self.rect is None:
            return
        x, y, w, h = self.rect
        x0, y0, x1, y1 = self._edges()
        cr.save()
        cr.set_source_rgba(0.2, 0.2, 0.2, 0.45)
        cr.rectangle(x, y, w, h)
        cr.rectangle(x0, y0, x1 - x0, y1 - y0)
        cr.set_fill_rule(1)
        cr.fill()
        cr.set_fill_rule(0)
        cr.set_source_rgb(0, 0, 0)
        L, T = self.H, 4
        for cx, cy, sx, sy in ((x0, y0, 1, 1), (x1, y0, -1, 1), (x0, y1, 1, -1), (x1, y1, -1, -1)):
            cr.rectangle(cx if sx > 0 else cx - L, cy if sy > 0 else cy - T, L, T)
            cr.rectangle(cx if sx > 0 else cx - T, cy if sy > 0 else cy - L, T, L)
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        cr.rectangle(mx - L / 2, y0, L, T)
        cr.rectangle(mx - L / 2, y1 - T, L, T)
        cr.rectangle(x0, my - L / 2, T, L)
        cr.rectangle(x1 - T, my - L / 2, T, L)
        cr.fill()
        cr.restore()

    def key(self, event):
        if not self.active:
            return False
        if event.keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            self.apply()
        elif event.keyval == Gdk.KEY_Escape:
            self.cancel()
        return True


# ================================================================ edit points
class EditPointsTool:
    """Edit Points: black squares on the shape's corners; drag them to reshape it.
    Click a red edge to add a point, Ctrl+click a point to delete it; Esc or a
    click outside finishes."""
    S = 7

    def __init__(self, win):
        self.win = win
        self.active = False
        self.rings = []
        self.drag = None
        self.page = 0

    def begin(self):
        ed = _ed(self.win)
        o = ed.selected_object()
        if o is None or o["kind"] not in ("shape", "textbox"):
            _flash(self.win, "Points can't be edited on this object.")
            return
        self.rings = [[list(p) for p in r] for r in ed.shape_points()]
        if not self.rings:
            _flash(self.win, "Points can't be edited on this object.")
            return
        self.page = o["page"]
        self.active = True
        _flash(self.win, "Drag a point to reshape. Esc or click outside to finish.")
        self.win.engine.view.queue_draw()

    def stop(self):
        self.active = False
        self.drag = None
        self.win.engine.view.queue_draw()

    def _px(self, p):
        return self.win.engine.view.to_widget(self.page, p[0], p[1])

    def _pt(self, ex, ey):
        v = self.win.engine.view
        x0, y0 = v.to_widget(self.page, 0, 0)
        s = v.ppp
        return [(ex - x0) / s, (ey - y0) / s]

    def press(self, ev):
        if ev.button != 1:
            return True
        for i, ring in enumerate(self.rings):
            for j, p in enumerate(ring):
                px, py = self._px(p)
                if abs(px - ev.x) <= self.S and abs(py - ev.y) <= self.S:
                    if ev.state & Gdk.ModifierType.CONTROL_MASK and len(ring) > 3:
                        del ring[j]
                        self._apply()
                        return True
                    self.drag = (i, j)
                    return True
        for i, ring in enumerate(self.rings):
            for j in range(len(ring)):
                ax, ay = self._px(ring[j])
                bx, by = self._px(ring[(j + 1) % len(ring)])
                L = math.hypot(bx - ax, by - ay) or 1
                t = max(0, min(1, ((ev.x - ax) * (bx - ax) + (ev.y - ay) * (by - ay)) / (L * L)))
                if math.hypot(ax + t * (bx - ax) - ev.x, ay + t * (by - ay) - ev.y) < 5:
                    ring.insert(j + 1, self._pt(ev.x, ev.y))
                    self.drag = (i, j + 1)
                    return True
        self.stop()
        return False

    def motion(self, ev):
        if self.drag is None:
            return True
        i, j = self.drag
        self.rings[i][j] = self._pt(ev.x, ev.y)
        return True

    def release(self, ev):
        if self.drag is None:
            return True
        self.drag = None
        self._apply()
        return True

    def _apply(self):
        ed = _ed(self.win)
        ed.set_shape_points([[tuple(p) for p in r] for r in self.rings])
        _done(self.win)

    def draw(self, cr):
        cr.save()
        cr.set_source_rgb(0.85, 0.1, 0.1)
        cr.set_line_width(1)
        cr.set_dash([3, 2])
        for ring in self.rings:
            for k, p in enumerate(ring):
                (cr.move_to if k == 0 else cr.line_to)(*self._px(p))
            cr.close_path()
            cr.stroke()
        cr.set_dash([])
        cr.set_source_rgb(0, 0, 0)
        for ring in self.rings:
            for p in ring:
                px, py = self._px(p)
                cr.rectangle(px - 3.5, py - 3.5, 7, 7)
                cr.fill()
        cr.restore()

    def key(self, event):
        if self.active and event.keyval in (Gdk.KEY_Escape, Gdk.KEY_Return):
            self.stop()
            return True
        return False


# ================================================================ select objects
class SelectObjectsTool:
    """Home > Select > Select Objects: drag a box round objects to select them
    (objects behind the text too). Esc ends it."""

    def __init__(self, win):
        self.win = win
        self.active = False
        self.start = None
        self.cur = None

    def begin(self):
        self.active = not self.active
        _flash(self.win, "Drag round the objects to select them." if self.active else "")

    def press(self, ev):
        if ev.button != 1:
            return False
        v = self.win.engine.view
        hit = v.page_at(ev.x, ev.y)
        if hit is None:
            return True
        ed = _ed(self.win)
        pg, x, y = hit
        if ed.object_at(pg, x, y):
            if ev.state & (Gdk.ModifierType.SHIFT_MASK | Gdk.ModifierType.CONTROL_MASK):
                ed.toggle_object_at(pg, x, y)
            else:
                ed.select_object_at(pg, x, y)
            v.objs.refresh()
            self.start = None
            return True
        self.start = (pg, x, y, ev.x, ev.y)
        self.cur = (ev.x, ev.y)
        return True

    def motion(self, ev):
        if self.start is None:
            return False
        self.cur = (ev.x, ev.y)
        return True

    def release(self, ev):
        if self.start is None:
            return False
        pg, x0, y0, _ex, _ey = self.start
        self.start = None
        v = self.win.engine.view
        hit = v.page_at(ev.x, ev.y)
        if hit is None or hit[0] != pg:
            return True
        n = _ed(self.win).select_objects_in(pg, x0, y0, hit[1], hit[2])
        v.objs.refresh()
        _done(self.win)
        if not n:
            _ed(self.win).deselect_object()
        return True

    def draw(self, cr):
        if self.start is None or self.cur is None:
            return
        _pg, _x, _y, ex, ey = self.start
        cx, cy = self.cur
        cr.save()
        cr.set_source_rgba(0.26, 0.45, 0.77, 0.15)
        cr.rectangle(min(ex, cx), min(ey, cy), abs(cx - ex), abs(cy - ey))
        cr.fill_preserve()
        cr.set_source_rgb(0.26, 0.45, 0.77)
        cr.set_line_width(1)
        cr.stroke()
        cr.restore()

    def key(self, event):
        if self.active and event.keyval == Gdk.KEY_Escape:
            self.active = False
            return True
        return False


class BackgroundTool:
    """Remove Background: clicks on the picture mark areas to keep or remove."""

    def __init__(self, win):
        self.win = win

    @property
    def active(self):
        st = getattr(self.win, "bg_state", None)
        return bool(st and st.get("native") and st.get("mode"))

    def press(self, ev):
        return ev.button == 1 and bg_click(self.win, ev.x, ev.y)

    def motion(self, ev):
        return False

    def release(self, ev):
        return False

    def draw(self, cr):
        pass

    def key(self, event):
        return False


def install(win):
    v = win.engine.view
    win.crop_mode = CropTool(win)
    win.edit_points = EditPointsTool(win)
    win.select_objects = SelectObjectsTool(win)
    v.tools[:] = [win.crop_mode, win.edit_points, win.select_objects, BackgroundTool(win)]


def crop_dialog(win):
    """Crop...: how much to take off each side."""
    native = getattr(win.engine, "native", False)
    if native and (_ed(win).selected_object() or {}).get("kind") != "picture":
        _flash(win, "Select a picture to crop it.")
        return
    d = FDialog(win, "Crop")
    spins = [LengthSpin(0, 0, 558800) for _ in range(4)]
    d.add(heading("Crop from"))
    d.add(grid([["_Left:", spins[0], "_Top:", spins[1]], ["_Right:", spins[2], "_Bottom:", spins[3]]]))
    d._spins = spins
    d.show_all()
    if d.ask() == Gtk.ResponseType.OK:
        vals = [s.mm100 for s in spins]
        if any(vals):
            if native:
                crop_mm100(win, *vals)
            else:
                win.object_call("crop", *vals)
    d.destroy()


# ================================================================ merge shapes
def merge(win, op):
    n, msg = _ed(win).merge_shapes(op)
    if not n:
        _flash(win, msg)
        return False
    _done(win)
    return True


# ================================================================ layout dialog
H_REL = [("Margin", "margin"), ("Page", "page"), ("Column", "column"), ("Character", "character"),
         ("Left Margin", "leftMargin"), ("Right Margin", "rightMargin")]
V_REL = [("Margin", "margin"), ("Page", "page"), ("Paragraph", "paragraph"), ("Line", "line"),
         ("Top Margin", "topMargin"), ("Bottom Margin", "bottomMargin")]
H_ALIGN = [("Left", "left"), ("Centered", "center"), ("Right", "right")]
V_ALIGN = [("Top", "top"), ("Centered", "center"), ("Bottom", "bottom")]
WRAP_STYLES = [("In line with text", "inline"), ("Square", "square"), ("Tight", "tight"),
               ("Through", "through"), ("Top and bottom", "topbottom"),
               ("Behind text", "behind"), ("In front of text", "front")]
WRAP_SIDES = [("Both sides", "bothSides"), ("Left only", "left"), ("Right only", "right"),
              ("Largest only", "largest")]


def _idx(lst, v, d=0):
    return next((i for i, (_n, k) in enumerate(lst) if k == v), d)


def layout_dialog(win, tab=0):
    ed = _ed(win)
    o = ed.selected_object()
    vals = dict(ed.object_layout() or [])
    if o is None or not vals:
        return
    num = lambda k, d=0.0: float(vals.get(k) or d)       # noqa: E731
    d = FDialog(win, "Layout")
    nb = Gtk.Notebook()
    d.add(nb)
    # ---------------------------------------------------- position
    p1 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    p1.set_border_width(10)
    p1.pack_start(heading("Horizontal"), False, False, 0)
    h_al_rb = Gtk.RadioButton.new_with_mnemonic(None, "_Alignment")
    h_abs_rb = Gtk.RadioButton.new_with_mnemonic_from_widget(h_al_rb, "Absolute _position")
    h_al = combo([n for n, _v in H_ALIGN], _idx(H_ALIGN, vals.get("h_align")))
    h_rel1 = combo([n for n, _v in H_REL], _idx(H_REL, vals.get("h_rel"), 2))
    h_pos = LengthSpin(num("h_off") * PT, -558800, 558800)
    h_rel2 = combo([n for n, _v in H_REL], _idx(H_REL, vals.get("h_rel"), 2))
    (h_al_rb if "h_align" in vals else h_abs_rb).set_active(True)
    p1.pack_start(grid([[h_al_rb, h_al, "relative to", h_rel1],
                        [h_abs_rb, h_pos, "to the right of", h_rel2]]), False, False, 0)
    p1.pack_start(heading("Vertical"), False, False, 0)
    v_al_rb = Gtk.RadioButton.new_with_mnemonic(None, "Al_ignment")
    v_abs_rb = Gtk.RadioButton.new_with_mnemonic_from_widget(v_al_rb, "Absolute po_sition")
    v_al = combo([n for n, _v in V_ALIGN], _idx(V_ALIGN, vals.get("v_align")))
    v_rel1 = combo([n for n, _v in V_REL], _idx(V_REL, vals.get("v_rel"), 2))
    v_pos = LengthSpin(num("v_off") * PT, -558800, 558800)
    v_rel2 = combo([n for n, _v in V_REL], _idx(V_REL, vals.get("v_rel"), 2))
    (v_al_rb if "v_align" in vals else v_abs_rb).set_active(True)
    p1.pack_start(grid([[v_al_rb, v_al, "relative to", v_rel1],
                        [v_abs_rb, v_pos, "below", v_rel2]]), False, False, 0)
    p1.pack_start(heading("Options"), False, False, 0)
    move = Gtk.CheckButton.new_with_mnemonic("_Move object with text")
    move.set_active(vals.get("v_rel") in ("paragraph", "line", None))
    lock = Gtk.CheckButton.new_with_mnemonic("_Lock anchor")
    lock.set_active(vals.get("locked") == "1")
    overlap = Gtk.CheckButton.new_with_mnemonic("Allow o_verlap")
    overlap.set_active(vals.get("allowOverlap", "1") == "1")
    cell = Gtk.CheckButton.new_with_mnemonic("La_yout in table cell")
    cell.set_active(vals.get("layoutInCell", "1") == "1")
    og = Gtk.Grid(column_spacing=30, row_spacing=4)
    og.attach(move, 0, 0, 1, 1)
    og.attach(lock, 0, 1, 1, 1)
    og.attach(overlap, 1, 0, 1, 1)
    og.attach(cell, 1, 1, 1, 1)
    p1.pack_start(og, False, False, 0)
    # ---------------------------------------------------- wrapping
    p2 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    p2.set_border_width(10)
    p2.pack_start(heading("Wrapping style"), False, False, 0)
    cur = vals.get("wrap", "inline")
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
    sides = []
    sg = Gtk.Box(spacing=18)
    first = None
    for lab, key in WRAP_SIDES:
        rb = Gtk.RadioButton.new_with_label_from_widget(first, lab)
        first = first or rb
        rb.set_active(key == vals.get("side", "bothSides"))
        sides.append((rb, key))
        sg.pack_start(rb, False, False, 0)
    p2.pack_start(sg, False, False, 0)
    p2.pack_start(heading("Distance from text"), False, False, 0)
    dist = {k: LengthSpin(num(k) / EMU * PT, 0, 55880) for k in ("distT", "distB", "distL", "distR")}
    p2.pack_start(grid([["To_p", dist["distT"], "L_eft", dist["distL"]],
                        ["_Bottom", dist["distB"], "Ri_ght", dist["distR"]]]), False, False, 0)

    def wrap_sens(*_):
        key = next(k for rb, k in radios if rb.get_active())
        for rb, _k in sides:
            rb.set_sensitive(key in ("square", "tight", "through"))
        for k in ("distT", "distB"):
            dist[k].set_sensitive(key in ("square", "topbottom"))
        for k in ("distL", "distR"):
            dist[k].set_sensitive(key in ("square", "tight", "through"))
        p1.set_sensitive(key != "inline")
    for rb, _k in radios:
        rb.connect("toggled", wrap_sens)
    wrap_sens()
    # ---------------------------------------------------- size
    p3 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    p3.set_border_width(10)
    w0, h0 = num("w"), num("h")
    nat = (num("nat_w"), num("nat_h")) if "nat_w" in vals else None
    base = nat or (w0, h0)
    p3.pack_start(heading("Height"), False, False, 0)
    hgt = LengthSpin(h0 * PT, 10, 558800)
    p3.pack_start(grid([["Abso_lute", hgt]]), False, False, 0)
    p3.pack_start(heading("Width"), False, False, 0)
    wid = LengthSpin(w0 * PT, 10, 558800)
    p3.pack_start(grid([["Absol_ute", wid]]), False, False, 0)
    p3.pack_start(heading("Rotate"), False, False, 0)
    rot = Gtk.SpinButton.new_with_range(-360, 360, 1)
    rot.set_value(num("rot"))
    p3.pack_start(grid([["Rota_tion:", rot, Gtk.Label(label="°")]]), False, False, 0)
    p3.pack_start(heading("Scale"), False, False, 0)
    sh = Gtk.SpinButton.new_with_range(1, 2000, 1)
    sw_ = Gtk.SpinButton.new_with_range(1, 2000, 1)
    sh.set_value(round(100.0 * h0 / base[1]) if base[1] else 100)
    sw_.set_value(round(100.0 * w0 / base[0]) if base[0] else 100)
    p3.pack_start(grid([["H_eight:", sh, Gtk.Label(label="%"), "W_idth:", sw_, Gtk.Label(label="%")]]),
                  False, False, 0)
    keep = Gtk.CheckButton.new_with_mnemonic("Lock _aspect ratio")
    keep.set_active(o["kind"] == "picture" or vals.get("lock_aspect") == "1")
    relorig = Gtk.CheckButton.new_with_mnemonic("_Relative to original picture size")
    relorig.set_active(nat is not None)
    relorig.set_sensitive(nat is not None)
    p3.pack_start(keep, False, False, 0)
    p3.pack_start(relorig, False, False, 0)
    if nat is not None:
        from ..widgets import fmt_len
        p3.pack_start(heading("Original size"), False, False, 0)
        ob = Gtk.Box(spacing=20)
        ob.pack_start(Gtk.Label(label="Height:  %s" % fmt_len(int(nat[1] * PT))), False, False, 0)
        ob.pack_start(Gtk.Label(label="Width:  %s" % fmt_len(int(nat[0] * PT))), False, False, 0)
        reset = Gtk.Button(label="R_eset", use_underline=True)
        ob.pack_end(reset, False, False, 0)
        p3.pack_start(ob, False, False, 0)
        reset.connect("clicked", lambda *_: (hgt.set_value(nat[1] * PT), wid.set_value(nat[0] * PT),
                                             rot.set_value(0)))
    busy = [False]
    ratio = w0 / float(h0 or 1)

    def from_abs(src):
        if busy[0]:
            return
        busy[0] = True
        try:
            if keep.get_active():
                if src is wid:
                    hgt.set_value(wid.get_value() / ratio)
                else:
                    wid.set_value(hgt.get_value() * ratio)
            sh.set_value(round(100.0 * hgt.get_value() / PT / base[1]))
            sw_.set_value(round(100.0 * wid.get_value() / PT / base[0]))
        finally:
            busy[0] = False

    def from_scale(src):
        if busy[0]:
            return
        busy[0] = True
        try:
            if keep.get_active():
                (sw_ if src is sh else sh).set_value(src.get_value())
            hgt.set_value(base[1] * PT * sh.get_value() / 100.0)
            wid.set_value(base[0] * PT * sw_.get_value() / 100.0)
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
    d._widgets = {"h_pos": h_pos, "v_pos": v_pos, "h_al_rb": h_al_rb, "h_abs_rb": h_abs_rb, "h_al": h_al,
                  "radios": radios, "wid": wid, "hgt": hgt, "rot": rot, "move": move, "dist": dist}
    if d.ask() == Gtk.ResponseType.OK:
        key = next(k for rb, k in radios if rb.get_active())
        out = [("wrap", key)]
        if key != "inline":
            if h_al_rb.get_active():
                out += [("h_rel", H_REL[h_rel1.get_active()][1]), ("h_align", H_ALIGN[h_al.get_active()][1])]
            else:
                out += [("h_rel", H_REL[h_rel2.get_active()][1]), ("h_off", "%.3f" % (h_pos.get_value() / PT))]
            if v_al_rb.get_active():
                out += [("v_rel", V_REL[v_rel1.get_active()][1]), ("v_align", V_ALIGN[v_al.get_active()][1])]
            else:
                out += [("v_rel", V_REL[v_rel2.get_active()][1]), ("v_off", "%.3f" % (v_pos.get_value() / PT))]
            out += [("allowOverlap", "1" if overlap.get_active() else "0"),
                    ("locked", "1" if lock.get_active() else "0"),
                    ("layoutInCell", "1" if cell.get_active() else "0")]
            if key in ("square", "tight", "through"):
                out.append(("side", next(k for rb, k in sides if rb.get_active())))
            out += [(k, "%.3f" % (dist[k].get_value() / PT)) for k in dist]
        ed.begin_group("Layout")
        try:
            ed.set_object_layout(out)
            nw, nh = wid.get_value() / PT, hgt.get_value() / PT
            if abs(nw - w0) > 0.05 or abs(nh - h0) > 0.05:
                ed.object_resize(nw, nh)
            if abs(rot.get_value() - num("rot")) > 0.01:
                ed.object_set_rotation(rot.get_value())
            if key != "inline" and not move.get_active() and vals.get("v_rel") in ("paragraph", "line"):
                ed.object_anchor_mode("page")
        finally:
            ed.end_group()
        _done(win)
    d.destroy()
    win.focus_document()


# ================================================================ wrap points
def edit_wrap_points(win):
    """Wrap points round the object: drag a point to change where text wraps."""
    ed = _ed(win)
    o = ed.selected_object()
    if o is None:
        return
    if o["wrap"] not in ("tight", "through"):
        ed.object_set_wrap("tight")
        _done(win)
    pts = [list(p) for p in ed.wrap_polygon()]
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts.pop()
    if len(pts) < 3:
        pts = [[0, 0], [0.5, 0], [1, 0], [1, 0.5], [1, 1], [0.5, 1], [0, 1], [0, 0.5]]
    pix = None
    img = ed.object_image() if o["kind"] == "picture" else None
    if img is not None:
        try:
            loader = GdkPixbuf.PixbufLoader()
            loader.write(bytes(img[0]))
            loader.close()
            pix = loader.get_pixbuf()
        except Exception:
            pix = None
    W, H = 480.0, 480.0 * o["h"] / max(1, o["w"])
    if H > 360:
        W, H = W * 360 / H, 360.0
    d = FDialog(win, "Edit Wrap Points")
    hint = Gtk.Label(label="Drag a black point to move it. Click the red line to add a point; "
                           "Ctrl+click a point to delete it.", xalign=0)
    hint.set_line_wrap(True)
    hint.set_max_width_chars(60)
    d.add(hint)
    da = Gtk.DrawingArea()
    pad = 12
    da.set_size_request(int(W) + 2 * pad, int(H) + 2 * pad)
    da.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK |
                  Gdk.EventMask.POINTER_MOTION_MASK)
    drag = [None]

    def scr(p):
        return pad + p[0] * W, pad + p[1] * H

    def draw(_w, cr):
        cr.set_source_rgb(1, 1, 1)
        cr.paint()
        if pix is not None:
            cr.save()
            cr.translate(pad, pad)
            cr.scale(W / pix.get_width(), H / pix.get_height())
            Gdk.cairo_set_source_pixbuf(cr, pix, 0, 0)
            cr.paint()
            cr.restore()
        else:
            cr.set_source_rgb(0.85, 0.9, 1)
            cr.rectangle(pad, pad, W, H)
            cr.fill()
        cr.set_source_rgb(0.85, 0.1, 0.1)
        cr.set_line_width(1.2)
        cr.set_dash([4, 3])
        for i, p in enumerate(pts):
            (cr.move_to if i == 0 else cr.line_to)(*scr(p))
        cr.close_path()
        cr.stroke()
        cr.set_dash([])
        cr.set_source_rgb(0, 0, 0)
        for p in pts:
            x, y = scr(p)
            cr.rectangle(x - 3.5, y - 3.5, 7, 7)
            cr.fill()
        return False

    def press(_w, ev):
        for i, p in enumerate(pts):
            x, y = scr(p)
            if (x - ev.x) ** 2 + (y - ev.y) ** 2 < 81:
                if ev.state & Gdk.ModifierType.CONTROL_MASK and len(pts) > 3:
                    del pts[i]
                    da.queue_draw()
                    return True
                drag[0] = i
                return True
        for i in range(len(pts)):
            ax, ay = scr(pts[i])
            bx, by = scr(pts[(i + 1) % len(pts)])
            L = math.hypot(bx - ax, by - ay) or 1
            t = max(0, min(1, ((ev.x - ax) * (bx - ax) + (ev.y - ay) * (by - ay)) / (L * L)))
            if math.hypot(ax + t * (bx - ax) - ev.x, ay + t * (by - ay) - ev.y) < 5:
                pts.insert(i + 1, [(ev.x - pad) / W, (ev.y - pad) / H])
                drag[0] = i + 1
                da.queue_draw()
                return True
        return True

    def motion(_w, ev):
        if drag[0] is not None:
            pts[drag[0]] = [min(1.5, max(-0.5, (ev.x - pad) / W)), min(1.5, max(-0.5, (ev.y - pad) / H))]
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
    d._points = pts
    if d.ask() == Gtk.ResponseType.OK:
        ed.set_wrap_polygon([tuple(p) for p in pts])
        _done(win)
    d.destroy()
    win.focus_document()


# ================================================================ pictures (PIL)
def _pil_image(win):
    from PIL import Image
    got = _ed(win).object_image()
    if got is None:
        return None
    return Image.open(io.BytesIO(bytes(got[0])))


def _png(img):
    b = io.BytesIO()
    img.save(b, "PNG", optimize=True)
    return b.getvalue()


def bg_start(win):
    from .. import pictools
    ed = _ed(win)
    o = ed.selected_object()
    if o is None or o["kind"] != "picture":
        return
    if not pictools._pil():
        win.dialogs.message("Remove Background needs the python3-pil package.")
        return
    got = ed.object_image()
    win.bg_state = {"native": True, "orig": bytes(got[0]), "ext": got[1].rsplit(".", 1)[-1],
                    "keep": [], "remove": [], "mode": None, "node": o}
    bg_apply(win)
    win.ribbon.show_contextual("Background Removal", True)
    win.select_tab("Background Removal")


def bg_apply(win):
    from PIL import Image, ImageChops
    from .. import pictools
    st = win.bg_state
    img = Image.open(io.BytesIO(st["orig"])).convert("RGBA")
    mask = pictools.background_mask(img, st["keep"], st["remove"])
    img.putalpha(ImageChops.multiply(img.getchannel("A"), mask))
    _ed(win).object_set_image(_png(img), "png")
    _done(win)


def bg_click(win, ex, ey):
    st = win.bg_state
    r = win.engine.view.objs.rect()
    if r is None:
        return False
    rx, ry, rw, rh = r
    if not (rx <= ex <= rx + rw and ry <= ey <= ry + rh):
        return False
    st[st["mode"]].append(((ex - rx) / rw, (ey - ry) / rh))
    bg_apply(win)
    return True


def bg_finish(win, keep):
    st = win.bg_state
    win.bg_state = None
    if st is not None and not keep:
        _ed(win).object_set_image(st["orig"], st["ext"])
        _done(win)
    win.ribbon.show_contextual("Background Removal", False)
    win.select_tab("Picture Format")


def compress(win, ppi, delete_cropped=True):
    """One picture: cropped-away parts dropped, resampled to ppi (0: as it is)."""
    from PIL import Image
    ed = _ed(win)
    img = _pil_image(win)
    o = ed.selected_object()
    if img is None or o is None:
        return False
    alpha = img.mode in ("RGBA", "LA", "P") and ("transparency" in img.info or img.mode != "P")
    img = img.convert("RGBA" if alpha else "RGB")
    c = ed.object_crop() or (0, 0, 0, 0)
    if delete_cropped and any(v > 0 for v in c):
        box = (int(max(0, c[0]) * img.width), int(max(0, c[1]) * img.height),
               img.width - int(max(0, c[2]) * img.width), img.height - int(max(0, c[3]) * img.height))
        if box[2] > box[0] and box[3] > box[1]:
            img = img.crop(box)
            ed.set_object_crop(min(0, c[0]), min(0, c[1]), min(0, c[2]), min(0, c[3]), False)
    if ppi:
        ww, wh = int(o["w"] / 72.0 * ppi), int(o["h"] / 72.0 * ppi)
        if img.width > ww > 0 and img.height > wh > 0:
            img = img.resize((ww, wh), Image.LANCZOS)
    b = io.BytesIO()
    if alpha:
        img.save(b, "PNG", optimize=True)
        ext = "png"
    else:
        img.save(b, "JPEG", quality=85 if ppi else 95, optimize=True)
        ext = "jpeg"
    ed.object_set_image(b.getvalue(), ext)
    return True


def compress_dialog(win):
    from .. import pictools
    if not pictools._pil():
        win.dialogs.message("Picture tools need the python3-pil package.")
        return
    ed = _ed(win)
    o = ed.selected_object()
    d = FDialog(win, "Compress Pictures")
    d.add(heading("Compression options:"))
    only = Gtk.CheckButton.new_with_mnemonic("Apply only to this _picture")
    only.set_active(o is not None and o["kind"] == "picture")
    only.set_sensitive(only.get_active())
    crop = Gtk.CheckButton.new_with_mnemonic("_Delete cropped areas of pictures")
    crop.set_active(True)
    d.add(only)
    d.add(crop)
    d.add(heading("Resolution:"))
    group_, radios = None, []
    for label, _ppi in pictools.RESOLUTIONS:
        rb = Gtk.RadioButton.new_with_label_from_widget(group_, label)
        group_ = group_ or rb
        radios.append(rb)
        d.add(rb)
    radios[2].set_active(True)
    res = d.ask()
    ppi = pictools.RESOLUTIONS[[r.get_active() for r in radios].index(True)][1]
    one, dc = only.get_active(), crop.get_active()
    d.done()
    if res != Gtk.ResponseType.OK:
        return
    keep = [x[0] for x in ed.selected_objects()]
    nodes = [keep[0]] if one and keep else [n for n, _nm, kind, _v in ed.objects_list() if kind == "Picture"]
    n = 0
    ed.begin_group("Compress Pictures")
    try:
        for node in nodes:
            ed.select_object_node(node)
            if compress(win, ppi, dc):
                n += 1
    finally:
        ed.end_group()
    if keep:
        ed.select_object_nodes(keep)
    else:
        ed.deselect_object()
    _done(win)
    _flash(win, "Compressed %d picture%s." % (n, "" if n == 1 else "s"))


# ================================================================ WordArt transform
WARPS = {"fontwork-arch-up-curve": "textArchUp", "fontwork-arch-down-curve": "textArchDown",
         "fontwork-circle-curve": "textCircle", "fontwork-plain-text": "textNoShape",
         "fontwork-triangle-up": "textTriangle", "fontwork-triangle-down": "textTriangleInverted",
         "fontwork-chevron-up": "textChevron", "fontwork-chevron-down": "textChevronInverted",
         "fontwork-wave": "textWave1", "fontwork-inflate": "textInflate",
         "fontwork-curve-down": "textDeflate", "fontwork-slant-up": "textSlantUp",
         "fontwork-slant-down": "textSlantDown", "fontwork-fade-right": "textFadeRight",
         "fontwork-fade-left": "textFadeLeft", "fontwork-fade-up": "textFadeUp",
         "fontwork-fade-down": "textFadeDown"}


def transform(win, kind):
    ed = _ed(win)
    if ed.selected_object() is None and ed.story() == "textbox":
        ed.select_story_textbox()
    o = ed.selected_object()
    if o is None or o["kind"] not in ("shape", "textbox"):
        _flash(win, "Select a shape with text first.")
        return
    ed.object_warp(WARPS.get(kind, kind))
    _done(win)
