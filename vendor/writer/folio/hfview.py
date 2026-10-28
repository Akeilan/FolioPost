"""Header/footer editing look: while the cursor is in a header or footer the
body text is dimmed and dashed boundaries with "Header"/"Footer" tabs are
drawn; while editing the body, header and footer content is dimmed."""
from . import docapi

MM100_TO_TWIP = 1440.0 / 2540.0


class HFOverlay:
    def __init__(self, win):
        self.win = win
        self.inside = False
        self.geom = None
        self.label_first = False
        self.odd_even = False
        self.show_body = True
        win.engine.view.connect_after("draw", self._draw)

    def update(self, inside):
        m = self.win.engine.model
        changed = inside != self.inside
        self.inside = inside
        if m is None:
            self.geom = None
            return
        try:
            ps = docapi.page_style(m)
            g = {"top": ps.TopMargin, "bottom": ps.BottomMargin,
                 "head": ps.HeaderHeight if ps.HeaderIsOn else 0,
                 "foot": ps.FooterHeight if ps.FooterIsOn else 0,
                 "hon": bool(ps.HeaderIsOn), "fon": bool(ps.FooterIsOn)}
            self.label_first = not ps.FirstIsShared
            self.odd_even = not ps.HeaderIsShared
        except Exception:
            g = None
        if g != self.geom or changed:
            self.geom = g
            self.win.engine.view.queue_draw()

    def _label(self, kind, page_no):
        if self.label_first and page_no == 1:
            return "First Page " + kind
        if self.odd_even:
            return ("Even Page " if page_no % 2 == 0 else "Odd Page ") + kind
        return kind

    def _draw(self, view, cr):
        g = self.geom
        if g is None or getattr(self.win, "multipage", None) is not None:
            return False
        eng = self.win.engine
        if not g["hon"] and not g["fon"] and not self.inside:
            return False
        for i, (rx, ry, rw, rh) in enumerate(eng.page_rects(), start=1):
            x0, y0 = eng.twips_to_px(rx, ry)
            x1, y1 = eng.twips_to_px(rx + rw, ry + rh)
            body_top = ry + (g["top"] + g["head"]) * MM100_TO_TWIP
            body_bot = ry + rh - (g["bottom"] + g["foot"]) * MM100_TO_TWIP
            _bx, bt = eng.twips_to_px(rx, body_top)
            _bx, bb = eng.twips_to_px(rx, body_bot)
            if self.inside:
                # dim the body, draw the boundaries and tabs
                # Show Document Text off: the body is hidden altogether
                cr.set_source_rgba(1, 1, 1, 0.55 if self.show_body else 1.0)
                cr.rectangle(x0, bt, x1 - x0, bb - bt)
                cr.fill()
                cr.set_source_rgb(0.18, 0.42, 0.25)
                cr.set_line_width(1)
                cr.set_dash([4, 3])
                for y in (bt, bb):
                    cr.move_to(x0, int(y) + 0.5)
                    cr.line_to(x1, int(y) + 0.5)
                cr.stroke()
                cr.set_dash([])
                self._tab(cr, x0, bt, self._label("Header", i), below=True)
                self._tab(cr, x0, bb, self._label("Footer", i), below=False)
            else:
                cr.set_source_rgba(1, 1, 1, 0.45)
                if g["hon"]:
                    cr.rectangle(x0, y0, x1 - x0, bt - y0)
                if g["fon"]:
                    cr.rectangle(x0, bb, x1 - x0, y1 - bb)
                cr.fill()
        return False

    def _tab(self, cr, x, y, text, below):
        cr.select_font_face("Sans")
        cr.set_font_size(11)
        ext = cr.text_extents(text)
        w, h = ext.width + 12, 18
        top = y if below else y - h
        cr.set_source_rgb(0.86, 0.93, 0.88)
        cr.rectangle(x + 2, top, w, h)
        cr.fill_preserve()
        cr.set_source_rgb(0.18, 0.42, 0.25)
        cr.set_line_width(1)
        cr.stroke()
        cr.set_source_rgb(0.15, 0.15, 0.15)
        cr.move_to(x + 8 - ext.x_bearing, top + (h - ext.height) / 2 - ext.y_bearing)
        cr.show_text(text)
