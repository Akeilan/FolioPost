"""Multiple Pages / Side to Side: the pages laid out next to each other,
rendered by the engine. Click a page to edit it; Esc returns."""
from gi.repository import Gdk, GLib, Gtk


class MultiPageView(Gtk.ScrolledWindow):
    GAP = 24

    def __init__(self, win, side_to_side=False):
        Gtk.ScrolledWindow.__init__(self)
        self.win = win
        self.side = side_to_side
        self.get_style_context().add_class("folio-canvas")
        self.area = Gtk.DrawingArea()
        self.area.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        self.area.connect("draw", self._draw)
        self.area.connect("button-press-event", self._click)
        self.add(self.area)
        self.cache = {}
        self.layout = []
        self.connect("size-allocate", lambda *_: GLib.idle_add(self._relayout))
        if side_to_side:
            self.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)

    def _relayout(self):
        rects = self.win.engine.page_rects()
        if not rects:
            return False
        aw = max(200, self.get_allocated_width() - 2 * self.GAP)
        ah = max(200, self.get_allocated_height() - 2 * self.GAP)
        pw, ph = rects[0][2], rects[0][3]
        if self.side:
            scale = ah / float(ph)
            cols = len(rects)
        else:
            # as many columns as fit at a readable size (at least 2)
            cols = max(2, min(len(rects), int(aw // 260)))
            scale = min((aw - (cols - 1) * self.GAP) / float(cols * pw), ah / float(ph))
        self.layout = []
        x, y, col, rowh = self.GAP, self.GAP, 0, 0
        for i, (rx, ry, rw, rh) in enumerate(rects):
            w, h = int(rw * scale), int(rh * scale)
            self.layout.append((i, x, y, w, h, (rx, ry, rw, rh)))
            rowh = max(rowh, h)
            col += 1
            if col >= cols and not self.side:
                col, x, y, rowh = 0, self.GAP, y + rowh + self.GAP, 0
            else:
                x += w + self.GAP
        total_w = max(e[1] + e[3] for e in self.layout) + self.GAP
        total_h = max(e[2] + e[4] for e in self.layout) + self.GAP
        self.area.set_size_request(total_w, total_h)
        self.area.queue_draw()
        return False

    def _page(self, i, rect, w):
        key = (i, w)
        surf = self.cache.get(key)
        if surf is None:
            surf = self.win.engine.render(rect[0], rect[1], rect[2], rect[3], w)
            self.cache[key] = surf
        return surf

    def _draw(self, area, cr):
        cr.set_source_rgb(0.89, 0.89, 0.89)
        cr.paint()
        for i, x, y, w, h, rect in self.layout:
            cr.set_source_rgba(0, 0, 0, 0.18)
            cr.rectangle(x + 2, y + 2, w, h)
            cr.fill()
            surf = self._page(i, rect, w)
            if surf is not None:
                cr.save()
                cr.translate(x, y)
                sx = w / float(surf.get_width())
                cr.scale(sx, sx)
                cr.set_source_surface(surf, 0, 0)
                cr.paint()
                cr.restore()
            cr.set_source_rgb(0.75, 0.75, 0.75)
            cr.set_line_width(1)
            cr.rectangle(x + 0.5, y + 0.5, w, h)
            cr.stroke()
        return False

    def _click(self, area, ev):
        for i, x, y, w, h, rect in self.layout:
            if x <= ev.x <= x + w and y <= ev.y <= y + h:
                self.win.close_multipage(page=i + 1)
                return True
        return True

    def refresh(self):
        self.cache.clear()
        self._relayout()
