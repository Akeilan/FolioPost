"""Draw tab: pens, highlighter and eraser. Strokes become line shapes on the
page (pen: on top of the text; highlighter: translucent, behind it)."""
import math

from gi.repository import Gdk, GLib

from . import bridge, docapi

TWIP = 2540.0 / 1440.0      # mm100 per twip

PENS = {
    "pen": {"color": 0x000000, "width": 50, "alpha": 0},
    "pen2": {"color": 0xC00000, "width": 100, "alpha": 0},
    "highlighter": {"color": 0xFFFF00, "width": 500, "alpha": 50},
}


class InkMode:
    def __init__(self, win):
        self.win = win
        self.tool = None             # 'pen', 'pen2', 'highlighter', 'eraser'
        self.points = []
        self.shapes = {}             # name -> (page_no, bbox mm100 page coords)
        view = win.engine.view
        view.connect("button-press-event", self._press)
        view.connect("motion-notify-event", self._motion)
        view.connect("button-release-event", self._release)
        view.connect_after("draw", self._draw)
        self._n = 0

    @property
    def active(self):
        return self.tool is not None

    def begin(self, tool):
        self.tool = tool
        self.points = []
        w = self.win.engine.view.get_window()
        if w is not None:
            name = "cell" if tool == "eraser" else "pencil"
            try:
                w.set_cursor(Gdk.Cursor.new_from_name(w.get_display(), name) or
                             Gdk.Cursor.new_from_name(w.get_display(), "crosshair"))
            except Exception:
                pass
        self.win.status.flash("Draw on the page. Esc or Select returns to typing."
                              if tool != "eraser" else "Click or drag over ink to erase it.")
        if hasattr(self.win, "draw_buttons"):
            for k, b in self.win.draw_buttons.items():
                b.apply_state("true" if k == tool else "false")

    def stop(self):
        self.tool = None
        self.points = []
        w = self.win.engine.view.get_window()
        if w is not None:
            w.set_cursor(None)
        if hasattr(self.win, "draw_buttons"):
            for k, b in self.win.draw_buttons.items():
                b.apply_state("true" if k == "select" else "false")
        self.win.engine.view.queue_draw()

    def set_pen(self, tool, color=None, width=None):
        if color is not None:
            PENS[tool]["color"] = color
        if width is not None:
            PENS[tool]["width"] = width
        self.begin(tool)

    # ------------------------------------------------------------ events
    def _press(self, view, ev):
        if not self.active or ev.button != 1:
            return False
        if self.tool == "eraser":
            self._erase_at(ev.x, ev.y)
        else:
            self.points = [(ev.x, ev.y)]
        return True

    def _motion(self, view, ev):
        if not self.active:
            return False
        if not (ev.state & Gdk.ModifierType.BUTTON1_MASK):
            return False
        if self.tool == "eraser":
            self._erase_at(ev.x, ev.y)
        elif self.points:
            lx, ly = self.points[-1]
            if math.hypot(ev.x - lx, ev.y - ly) >= 2:
                self.points.append((ev.x, ev.y))
                view.queue_draw()
        return True

    def _release(self, view, ev):
        if not self.active or ev.button != 1:
            return False
        if self.tool != "eraser" and len(self.points) >= 2:
            pts = list(self.points)
            tool = self.tool
            GLib.idle_add(lambda: (self._create(tool, pts), False)[1])
        self.points = []
        return True

    def _draw(self, view, cr):
        if not self.active or len(self.points) < 2 or self.tool == "eraser":
            return False
        p = PENS[self.tool]
        c = p["color"]
        z = self.win.engine.view.get_zoom() or 1.0
        cr.set_source_rgba(((c >> 16) & 255) / 255.0, ((c >> 8) & 255) / 255.0,
                           (c & 255) / 255.0, 1 - p["alpha"] / 100.0)
        cr.set_line_width(max(1.0, p["width"] / 2540.0 * 96 * z))
        cr.set_line_cap(1)
        cr.set_line_join(1)
        cr.move_to(*self.points[0])
        for pt in self.points[1:]:
            cr.line_to(*pt)
        cr.stroke()
        return False

    # ------------------------------------------------------------ shapes
    def _page_coords(self, x, y):
        eng = self.win.engine
        tx, ty = eng.px_to_twips(x, y)
        for i, (rx, ry, rw, rh) in enumerate(eng.page_rects(), start=1):
            if ry <= ty < ry + rh:
                return i, int((tx - rx) * TWIP), int((ty - ry) * TWIP)
        return None, 0, 0

    def _create(self, tool, pts):
        m = self.win.engine.model
        if m is None:
            return
        page, _x, _y = self._page_coords(*pts[0])
        if page is None:
            return
        coords = []
        for x, y in pts:
            pg, px, py = self._page_coords(x, y)
            if pg == page:
                coords.append((px, py))
        if len(coords) < 2:
            return
        coords = _simplify(coords, 8)
        xs = [c[0] for c in coords]
        ys = [c[1] for c in coords]
        x0, y0 = min(xs), min(ys)
        p = PENS[tool]
        um = m.getUndoManager()
        um.enterUndoContext("Ink")
        try:
            shape = m.createInstance("com.sun.star.drawing.PolyLineShape")
            shape.AnchorType = bridge.enum("com.sun.star.text.TextContentAnchorType", "AT_PAGE")
            m.getDrawPage().add(shape)
            import uno
            pts_u = tuple(bridge.struct("com.sun.star.awt.Point", X=x, Y=y) for x, y in coords)
            uno.invoke(shape, "setPropertyValue", ("PolyPolygon", uno.Any(
                "[][]com.sun.star.awt.Point", (pts_u,))))
            from .drawing import _anchor_page
            _anchor_page(shape, page, x0, y0)
            shape.LineColor = p["color"]
            shape.LineWidth = p["width"]
            shape.LineTransparence = p["alpha"]
            try:
                shape.LineCap = bridge.enum("com.sun.star.drawing.LineCap", "ROUND")
                shape.LineJoint = bridge.enum("com.sun.star.drawing.LineJoint", "ROUND")
            except Exception:
                pass
            try:
                shape.TextWrap = bridge.enum("com.sun.star.text.WrapTextMode", "THROUGH")
                shape.Opaque = tool != "highlighter"     # highlighter goes behind the text
            except Exception:
                pass
            self._n += 1
            name = "Ink %d" % self._n
            while m.getDrawPage() and _has_name(m, name):
                self._n += 1
                name = "Ink %d" % self._n
            shape.Name = name
            pad = p["width"]
            self.shapes[name] = (page, (x0 - pad, y0 - pad, max(xs) + pad, max(ys) + pad),
                                 coords)
        finally:
            um.leaveUndoContext()

    def _erase_at(self, x, y):
        m = self.win.engine.model
        if m is None:
            return
        page, px, py = self._page_coords(x, y)
        if page is None:
            return
        dp = m.getDrawPage()
        tol = 250
        for i in range(dp.getCount() - 1, -1, -1):
            sh = dp.getByIndex(i)
            try:
                name = sh.Name
            except Exception:
                continue
            if not name.startswith("Ink "):
                continue
            info = self.shapes.get(name)
            if info is None:
                info = _shape_info(sh)
                if info is None:
                    continue
                self.shapes[name] = info
            pg, (a, b, c, d), coords = info
            if pg != page or not (a - tol <= px <= c + tol and b - tol <= py <= d + tol):
                continue
            reach = tol + 250
            if any(_seg_dist(px, py, coords[k], coords[k + 1]) < reach
                   for k in range(len(coords) - 1)) or \
                    (len(coords) == 1 and math.hypot(px - coords[0][0], py - coords[0][1]) < reach):
                try:
                    dp.remove(sh)
                except Exception:
                    try:
                        sh.getAnchor().getText().removeTextContent(sh)
                    except Exception:
                        pass
                self.shapes.pop(name, None)
                return

    def key(self, event):
        if self.active and event.keyval == Gdk.KEY_Escape:
            self.stop()
            return True
        return False


def _seg_dist(px, py, a, b):
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    if dx == dy == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / float(dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _has_name(m, name):
    dp = m.getDrawPage()
    for i in range(dp.getCount()):
        try:
            if dp.getByIndex(i).Name == name:
                return True
        except Exception:
            pass
    return False


def _shape_info(sh):
    """Page and points of an ink stroke loaded from a file."""
    try:
        poly = sh.PolyPolygon
        coords = [(p.X, p.Y) for p in poly[0]]
        xs = [c[0] for c in coords]
        ys = [c[1] for c in coords]
        page = sh.AnchorPageNo or 1
        return page, (min(xs), min(ys), max(xs), max(ys)), coords
    except Exception:
        return None


def _simplify(pts, tol):
    """Drop points closer than tol to the previous kept point."""
    out = [pts[0]]
    for p in pts[1:]:
        if math.hypot(p[0] - out[-1][0], p[1] - out[-1][1]) >= tol:
            out.append(p)
    if out[-1] != pts[-1]:
        out.append(pts[-1])
    return out
