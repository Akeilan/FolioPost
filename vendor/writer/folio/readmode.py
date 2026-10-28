"""View > Read Mode, as in the original: the ribbon gives way to a slim menu
bar (File, Tools, View), the pages fill the window two at a time, and you
turn them with the arrows at the sides, the arrow keys, Page Up/Down, Space
or the mouse wheel. Esc goes back to editing.

The pages are the document's own pages, drawn by the engine (the original's
"Paper Layout" of Read Mode)."""
import cairo
from gi.repository import Gdk, GLib, Gtk

GAP = 28
MARGIN = 26
ARROW_R = 22


class ReadMode(Gtk.Box):
    def __init__(self, win):
        Gtk.Box.__init__(self, orientation=Gtk.Orientation.VERTICAL)
        self.win = win
        self.first = 0
        self.color = win.app.settings.get("read_page_color", "none")
        self.cache = {}
        self.hover = None
        self.get_style_context().add_class("folio-readmode")
        # ---- menu bar
        bar = Gtk.Box(spacing=2)
        bar.get_style_context().add_class("folio-readbar")
        for name, items in (("File", self._file_items), ("Tools", self._tools_items),
                            ("View", self._view_items)):
            b = Gtk.MenuButton(label=name)
            b.set_relief(Gtk.ReliefStyle.NONE)
            b.connect("toggled", lambda btn, f=items: btn.get_active() and
                      btn.set_popover(self._popover(btn, f())))
            b.set_popover(Gtk.Popover())
            bar.pack_start(b, False, False, 0)
        close = Gtk.Button(label="Exit Read Mode")
        close.set_relief(Gtk.ReliefStyle.NONE)
        close.connect("clicked", lambda *_: self.leave())
        bar.pack_end(close, False, False, 6)
        self.pack_start(bar, False, False, 0)
        # ---- pages
        self.area = Gtk.DrawingArea()
        self.area.set_can_focus(True)
        self.area.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.SCROLL_MASK |
                             Gdk.EventMask.SMOOTH_SCROLL_MASK |
                             Gdk.EventMask.POINTER_MOTION_MASK |
                             Gdk.EventMask.KEY_PRESS_MASK |
                             Gdk.EventMask.LEAVE_NOTIFY_MASK)
        self.area.connect("draw", self._draw)
        self.area.connect("button-press-event", self._press)
        self.area.connect("scroll-event", self._scroll)
        self.area.connect("motion-notify-event", self._motion)
        self.area.connect("leave-notify-event", lambda *_: self._set_hover(None))
        self.area.connect("key-press-event", self._key)
        self.area.connect("size-allocate", lambda *_: self.cache.clear())
        self.pack_start(self.area, True, True, 0)
        # ---- bottom line
        foot = Gtk.Box(spacing=8)
        foot.get_style_context().add_class("folio-readfoot")
        self.where = Gtk.Label(xalign=0)
        foot.pack_start(self.where, False, False, 10)
        self.pack_start(foot, False, False, 0)
        self.pages = []
        GLib.idle_add(self._load)

    # ------------------------------------------------------------ pages
    def _load(self):
        self.pages = self.win.engine.page_rects()
        try:
            if getattr(self.win.engine, "native", False):
                self.first = self.win.engine.ed.caret_page()
            else:
                m = self.win.engine.model
                self.first = max(0, m.getCurrentController().getViewCursor().getPage() - 1)
        except Exception:
            self.first = 0
        self.first -= self.first % 2
        self._update()
        self.area.grab_focus()
        return False

    def per_screen(self):
        a = self.area.get_allocation()
        if not self.pages:
            return 1
        # two pages side by side whenever the window is wider than tall
        return 2 if a.width > a.height * 1.15 and len(self.pages) > 1 else 1

    def _update(self):
        n = len(self.pages)
        k = self.per_screen()
        last = min(n, self.first + k)
        if n:
            self.where.set_text("Screens %d-%d of %d" % (self.first + 1, last, n)
                                if last > self.first + 1 else
                                "Screen %d of %d" % (self.first + 1, n))
        self.area.queue_draw()

    def go(self, d):
        k = self.per_screen()
        n = len(self.pages)
        new = max(0, min(self.first + d * k, (n - 1) - (n - 1) % k))
        if new != self.first:
            self.first = new
            self._update()

    def _surface(self, i, width_px):
        key = (i, int(width_px), self.color)
        s = self.cache.get(key)
        if s is None:
            x, y, w, h = self.pages[i]
            s = self.win.engine.render(x, y, w, h, width_px)
            if len(self.cache) > 8:
                self.cache.clear()
            self.cache[key] = s
        return s

    # ------------------------------------------------------------ drawing
    def _geometry(self):
        """(allocation, pages on screen, [(index, x, y, w, h)]) in pixels."""
        a = self.area.get_allocation()
        k = self.per_screen()
        shown = [i for i in range(self.first, min(self.first + k, len(self.pages)))]
        if not shown:
            return a, k, []
        tw = sum(self.pages[i][2] for i in shown)
        th = max(self.pages[i][3] for i in shown)
        scale = min((a.height - 2 * MARGIN) / float(th),
                    (a.width - 2 * MARGIN - 4 * ARROW_R - (len(shown) - 1) * GAP) / float(tw))
        total = tw * scale + (len(shown) - 1) * GAP
        x = (a.width - total) / 2
        out = []
        for i in shown:
            pw, ph = self.pages[i][2] * scale, self.pages[i][3] * scale
            out.append((i, x, (a.height - ph) / 2, pw, ph))
            x += pw + GAP
        return a, k, out

    def _arrows(self):
        a = self.area.get_allocation()
        cy = a.height / 2
        return {"prev": (MARGIN / 2 + ARROW_R, cy), "next": (a.width - MARGIN / 2 - ARROW_R, cy)}

    def _draw(self, area, cr):
        if self.color == "inverse":
            cr.set_source_rgb(0.12, 0.12, 0.12)
        elif self.color == "sepia":
            cr.set_source_rgb(0.93, 0.89, 0.80)
        else:
            cr.set_source_rgb(0.92, 0.92, 0.92)
        cr.paint()
        if not self.pages:
            return False
        a, k, boxes = self._geometry()
        for i, px, py, pw, ph in boxes:
            cr.save()
            cr.set_source_rgba(0, 0, 0, 0.18)
            cr.rectangle(px + 3, py + 3, pw, ph)
            cr.fill()
            s = self._surface(i, pw)
            if s is not None:
                cr.save()
                cr.translate(px, py)
                cr.scale(pw / s.get_width(), ph / s.get_height())
                cr.set_source_surface(s, 0, 0)
                cr.paint()
                cr.restore()
            if self.color == "sepia":
                cr.set_operator(cairo.OPERATOR_MULTIPLY)
                cr.set_source_rgb(0.98, 0.94, 0.85)
                cr.rectangle(px, py, pw, ph)
                cr.fill()
            elif self.color == "inverse":
                cr.set_operator(cairo.OPERATOR_DIFFERENCE)
                cr.set_source_rgb(1, 1, 1)
                cr.rectangle(px, py, pw, ph)
                cr.fill()
            cr.restore()
        n = len(self.pages)
        for name, (cx, cy) in self._arrows().items():
            enabled = self.first > 0 if name == "prev" else self.first + k < n
            if not enabled:
                continue
            hot = self.hover == name
            cr.set_source_rgba(0.18, 0.42, 0.25, 0.95 if hot else 0.55)
            cr.arc(cx, cy, ARROW_R, 0, 6.2832)
            cr.fill()
            cr.set_source_rgb(1, 1, 1)
            cr.set_line_width(3)
            d = -1 if name == "prev" else 1
            cr.move_to(cx - 5 * d, cy - 9)
            cr.line_to(cx + 5 * d, cy)
            cr.line_to(cx - 5 * d, cy + 9)
            cr.stroke()
        return False

    def _hit(self, x, y):
        for name, (cx, cy) in self._arrows().items():
            if (x - cx) ** 2 + (y - cy) ** 2 <= (ARROW_R + 4) ** 2:
                return name
        return None

    def _set_hover(self, name):
        if name != self.hover:
            self.hover = name
            self.area.queue_draw()

    def _motion(self, _w, ev):
        self._set_hover(self._hit(ev.x, ev.y))

    def _press(self, _w, ev):
        self.area.grab_focus()
        hit = self._hit(ev.x, ev.y)
        if ev.button == 1 and hit:
            self.go(-1 if hit == "prev" else 1)
            return True
        if ev.type == Gdk.EventType._2BUTTON_PRESS and ev.button == 1:
            # double-click a page: back to editing at that page
            a, k, boxes = self._geometry()
            for i, px, py, pw, ph in boxes:
                if px <= ev.x <= px + pw and py <= ev.y <= py + ph:
                    self.leave(page=i + 1)
            return True
        return False

    def _scroll(self, _w, ev):
        d = 0
        if ev.direction == Gdk.ScrollDirection.DOWN:
            d = 1
        elif ev.direction == Gdk.ScrollDirection.UP:
            d = -1
        elif ev.direction == Gdk.ScrollDirection.SMOOTH:
            dy = ev.get_scroll_deltas()[2]
            d = 1 if dy > 0.3 else -1 if dy < -0.3 else 0
        if d:
            self.go(d)
        return True

    def _key(self, _w, ev):
        k = ev.keyval
        if k in (Gdk.KEY_Right, Gdk.KEY_Down, Gdk.KEY_Page_Down, Gdk.KEY_space,
                 Gdk.KEY_Return):
            self.go(1)
        elif k in (Gdk.KEY_Left, Gdk.KEY_Up, Gdk.KEY_Page_Up, Gdk.KEY_BackSpace):
            self.go(-1)
        elif k == Gdk.KEY_Home:
            self.first = 0
            self._update()
        elif k == Gdk.KEY_End:
            n = len(self.pages)
            kk = self.per_screen()
            self.first = max(0, (n - 1) - (n - 1) % kk)
            self._update()
        elif k == Gdk.KEY_Escape:
            self.leave()
        else:
            return False
        return True

    # ------------------------------------------------------------ menus
    def _popover(self, btn, items):
        from .ribbon import menu_popover
        pop = menu_popover(btn, items)
        return pop

    def _file_items(self):
        w = self.win
        return [("Save", lambda: w.run("save")), ("Save As...", lambda: w.run("save-as")),
                ("Print...", lambda: (self.leave(), w.run("backstage-print"))),
                None, ("Close Read Mode", self.leave)]

    def _tools_items(self):
        return [("Find...", self._find)]

    def _view_items(self):
        w = self.win
        return [("Edit Document", self.leave),
                ("Navigation Pane", lambda: w.toggle_navigation_pane()),
                None, ("#", "Page Color"),
                ("None" + ("  ✓" if self.color == "none" else ""), lambda: self.set_color("none")),
                ("Sepia" + ("  ✓" if self.color == "sepia" else ""),
                 lambda: self.set_color("sepia")),
                ("Inverse" + ("  ✓" if self.color == "inverse" else ""),
                 lambda: self.set_color("inverse"))]

    def set_color(self, c):
        self.color = c
        self.win.app.settings["read_page_color"] = c
        self.win.app.save_settings()
        self.cache.clear()
        self.area.queue_draw()

    def _find(self):
        text = self.win.dialogs.ask_text("Find", "Find what:", "") if hasattr(
            self.win.dialogs, "ask_text") else None
        if not text:
            return
        if getattr(self.win.engine, "native", False):
            ed = self.win.engine.ed
            if not ed.find(text, {}, True, True):
                self.win.dialogs.message("We couldn't find what you were looking for.")
                return
            page = ed.caret_page()
            k = self.per_screen()
            self.first = page - page % k
            self._update()
            return
        m = self.win.engine.model
        sd = m.createSearchDescriptor()
        sd.SearchString = text
        found = m.findFirst(sd)
        if found is None:
            self.win.dialogs.message("We couldn't find what you were looking for.")
            return
        vc = m.getCurrentController().getViewCursor()
        vc.gotoRange(found.getStart(), False)
        page = vc.getPage() - 1
        k = self.per_screen()
        self.first = page - page % k
        self._update()

    # ------------------------------------------------------------ leaving
    def leave(self, page=None):
        win = self.win
        if page:
            try:
                if getattr(win.engine, "native", False):
                    win.engine.ed.goto_page(page - 1)
                else:
                    win.engine.model.getCurrentController().getViewCursor().jumpToPage(page)
            except Exception:
                pass
        win.leave_read_mode()
