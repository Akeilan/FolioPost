"""Calendar: the date navigator and calendar list on the left, and the Day, Work Week, Week and
Month views — drawn here, with appointments laid side by side where they overlap; drag to move
or (by the bottom edge) to change the length; double-click to make one."""
import calendar as pycal
import datetime as dt
import math

from gi.repository import Gdk, GLib, Gtk, Pango, PangoCairo

from . import ical

HOUR_H = 44
HEAD_H = 40
TIME_W = 56
ALLDAY_ROW = 22


def rgb(hexcolor, alpha=1.0):
    c = Gdk.RGBA()
    if not c.parse(hexcolor or "#0078D4"):
        c.parse("#0078D4")
    return c.red, c.green, c.blue, alpha


def day_start(d):
    return dt.datetime.combine(d, dt.time(0)).replace(tzinfo=ical.local_tz())


class Instance:
    """One appointment as drawn: its stored event, this occurrence's times and its calendar."""

    def __init__(self, row, event, start, end, cal):
        self.row = row
        self.event = event
        self.start = start
        self.end = end
        self.cal = cal
        self.all_day = event.all_day or (end - start) >= dt.timedelta(hours=24)
        self.rect = None
        self.col = 0
        self.cols = 1

    @property
    def recurring(self):
        return bool(self.event.rrule) or self.event.recurrence_id is not None


class CalendarView(Gtk.Box):
    def __init__(self, win):
        Gtk.Box.__init__(self)
        self.win = win
        self.store = win.store
        self.mode = win.vset("cal_mode", "workweek")
        self.date = dt.date.today()
        self.selected = None             # Instance
        self.slot = None                 # (datetime start, datetime end) picked by a click
        self.instances = []
        self._cache = {}
        self.scale = int(win.vset("cal_scale", 30))
        self.work = (int(win.vset("work_start", 8)), int(win.vset("work_end", 17)))
        paned = Gtk.Paned()
        self.pack_start(paned, True, True, 0)
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        left.get_style_context().add_class("folio-folderpane")
        left.set_size_request(230, -1)
        self.navigator = Gtk.Calendar()
        self.navigator.set_margin_start(6)
        self.navigator.set_margin_end(6)
        self.navigator.set_margin_top(6)
        self.navigator.connect("day-selected", self._nav_picked)
        left.pack_start(self.navigator, False, False, 0)
        self.cal_list = Gtk.ListBox()
        self.cal_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.cal_list.connect("row-selected", lambda *_: None)
        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sw.add(self.cal_list)
        left.pack_start(sw, True, True, 0)
        self.left = left
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        bar = Gtk.Box(spacing=4)
        bar.get_style_context().add_class("folio-listbar")
        for label, cmd, tip in (("‹", "cal-prev", "Back"), ("›", "cal-next", "Forward")):
            b = Gtk.Button(label=label)
            b.set_relief(Gtk.ReliefStyle.NONE)
            b.set_tooltip_text(tip)
            b.connect("clicked", lambda _b, c=cmd: self.win.run(c))
            bar.pack_start(b, False, False, 0)
        self.title = Gtk.Label(xalign=0)
        self.title.get_style_context().add_class("folio-cal-title")
        bar.pack_start(self.title, True, True, 8)
        right.pack_start(bar, False, False, 0)
        self.area = Gtk.DrawingArea()
        self.area.set_can_focus(True)
        self.area.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK |
                             Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.SCROLL_MASK | Gdk.EventMask.KEY_PRESS_MASK)
        self.area.connect("draw", self._draw)
        self.area.connect("button-press-event", self._press)
        self.area.connect("button-release-event", self._release)
        self.area.connect("motion-notify-event", self._motion)
        self.area.connect("size-allocate", lambda *_: self.area.queue_draw())
        self.scroller = Gtk.ScrolledWindow()
        self.scroller.add(self.area)
        right.pack_start(self.scroller, True, True, 0)
        self.scroller.get_vadjustment().connect("value-changed", lambda *_: self.area.queue_draw())
        paned.pack1(left, False, False)
        paned.pack2(right, True, False)
        paned.set_position(240)
        self.drag = None
        self.refresh_calendars()
        self.refresh()
        GLib.idle_add(self.scroll_to_work)

    # ------------------------------------------------------------ calendars
    def refresh_calendars(self):
        for c in self.cal_list.get_children():
            self.cal_list.remove(c)
        accounts = {a["id"]: a for a in self.store.accounts()}
        groups = {}
        for c in self.store.calendars():
            groups.setdefault(c["account"], []).append(c)
        for aid, cals in sorted(groups.items()):
            head = Gtk.Label(xalign=0)
            title = (accounts[aid]["email"] if aid in accounts else
                     "Other Calendars" if any(c["kind"] == "ics" for c in cals) and all(c["kind"] != "local" for c in cals)
                     else "My Calendars")
            head.set_markup("<b>%s</b>" % GLib.markup_escape_text(title))
            row = Gtk.ListBoxRow()
            row.add(head)
            row.set_selectable(False)
            row.cal_id = None
            head.set_margin_start(8)
            head.set_margin_top(6)
            self.cal_list.add(row)
            for c in cals:
                r = Gtk.ListBoxRow()
                box = Gtk.Box(spacing=6)
                box.set_margin_start(14)
                chk = Gtk.CheckButton()
                chk.set_active(bool(c["shown"]))
                chk.connect("toggled", lambda b, cid=c["id"]: self.show_calendar(cid, b.get_active()))
                sw = Gtk.DrawingArea()
                sw.set_size_request(12, 12)
                col = c["color"]
                sw.connect("draw", lambda w, cr, col=col: (cr.set_source_rgba(*rgb(col)), cr.rectangle(0, 0, 12, 12), cr.fill()))
                box.pack_start(chk, False, False, 0)
                box.pack_start(sw, False, False, 0)
                lab = Gtk.Label(label=c["name"] + ("  (read-only)" if c["readonly"] else ""), xalign=0)
                lab.set_ellipsize(Pango.EllipsizeMode.END)
                box.pack_start(lab, True, True, 0)
                r.add(box)
                r.cal_id = c["id"]
                r.check = chk
                self.cal_list.add(r)
        self.cal_list.show_all()

    def selected_calendar(self):
        r = self.cal_list.get_selected_row()
        if r is not None and getattr(r, "cal_id", None):
            return self.store.calendar(r.cal_id)
        return None

    def default_calendar(self):
        sel = self.selected_calendar()
        if sel and not sel["readonly"]:
            return sel
        cals = [c for c in self.store.calendars() if not c["readonly"]]
        pref = self.store.get("default-calendar")
        for c in cals:
            if c["id"] == pref:
                return c
        if cals:
            return cals[0]
        cid = self.store.add_calendar("Calendar", "#0078D4", "local")
        self.refresh_calendars()
        return self.store.calendar(cid)

    def show_calendar(self, cid, on):
        self.store.update_calendar(cid, shown=int(on))
        self.invalidate()
        self.refresh()

    # ------------------------------------------------------------ data
    def invalidate(self):
        self._cache = {}

    def range(self):
        d = self.date
        if self.mode == "day":
            days = [d]
        elif self.mode == "workweek":
            mon = d - dt.timedelta(days=d.weekday())
            days = [mon + dt.timedelta(days=i) for i in range(5)]
        elif self.mode == "week":
            first = d - dt.timedelta(days=(d.weekday() - self.week_start()) % 7)
            days = [first + dt.timedelta(days=i) for i in range(7)]
        else:
            first = d.replace(day=1)
            start = first - dt.timedelta(days=(first.weekday() - self.week_start()) % 7)
            days = [start + dt.timedelta(days=i) for i in range(42)]
        return days

    def week_start(self):
        return int(self.win.vset("week_start", 0))

    def load(self, start, end):
        """Every shown appointment between two times, recurring ones expanded."""
        out = []
        for cal in self.store.calendars():
            if not cal["shown"]:
                continue
            for row in self.store.events(cal["id"]):
                if row["start"] and row["start"] > end.timestamp():
                    continue
                if row["until"] and row["until"] < start.timestamp():
                    continue
                evs = self._cache.get((row["id"], row["ics"].__hash__()))
                if evs is None:
                    evs = ical.events_of(ical.parse(row["ics"]))
                    self._cache[(row["id"], row["ics"].__hash__())] = evs
                for e, s, en in ical.expand(evs, start, end):
                    out.append(Instance(row, e, s.astimezone(ical.local_tz()), en.astimezone(ical.local_tz()), cal))
        out.sort(key=lambda i: (i.start, -(i.end - i.start).total_seconds()))
        return out

    def refresh(self):
        days = self.range()
        start, end = day_start(days[0]), day_start(days[-1] + dt.timedelta(days=1))
        sel = self.selected
        self.instances = self.load(start, end)
        if sel is not None:
            self.selected = next((i for i in self.instances if i.row["id"] == sel.row["id"] and i.start == sel.start), None)
        self.days = days
        if self.mode == "month":
            mid = days[15]
            self.title.set_markup("<big>%s</big>" % mid.strftime("%B %Y"))
        elif len(days) == 1:
            self.title.set_markup("<big>%s</big>" % days[0].strftime("%A, %B %-d, %Y"))
        else:
            a, b = days[0], days[-1]
            same = a.month == b.month
            self.title.set_markup("<big>%s</big>" % ("%s %d – %d, %d" % (a.strftime("%B"), a.day, b.day, b.year) if same else
                                                     "%s – %s" % (a.strftime("%B %-d"), b.strftime("%B %-d, %Y"))))
        self.navigator.handler_block_by_func(self._nav_picked)
        self.navigator.select_month(self.date.month - 1, self.date.year)
        self.navigator.select_day(self.date.day)
        self.navigator.clear_marks()
        for i in self.load(day_start(self.date.replace(day=1)), day_start((self.date.replace(day=28) + dt.timedelta(days=4)).replace(day=1))):
            if i.start.month == self.date.month:
                self.navigator.mark_day(i.start.day)
        self.navigator.handler_unblock_by_func(self._nav_picked)
        self._size()
        self.area.queue_draw()
        self.win.update_cal_status(self)

    def _size(self):
        if self.mode == "month":
            self.area.set_size_request(-1, -1)
            self.scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.NEVER)
        else:
            self.scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            self.area.set_size_request(-1, self._grid_top() + int(24 * self.hour_h()) + 4)

    def hour_h(self):
        return HOUR_H * {5: 4.0, 6: 3.4, 10: 2.4, 15: 1.7, 30: 1.0, 60: 0.8}.get(self.scale, 1.0)

    def _allday_rows(self):
        n = 0
        for d in self.days:
            k = sum(1 for i in self.instances if i.all_day and i.start.date() <= d < max(i.end.date(), i.start.date() + dt.timedelta(days=1)))
            n = max(n, k)
        return n

    def _grid_top(self):
        if self.mode == "month":
            return 0
        return HEAD_H + max(1, self._allday_rows()) * ALLDAY_ROW + 6

    def scroll_to_work(self):
        if self.mode != "month":
            adj = self.scroller.get_vadjustment()
            adj.set_value(max(0, self._grid_top() - HEAD_H + self.work[0] * self.hour_h() - 10) if adj else 0)
        return False

    # ------------------------------------------------------------ navigation
    def go(self, d):
        self.date = d
        self.refresh()

    def step(self, n):
        if self.mode == "day":
            self.go(self.date + dt.timedelta(days=n))
        elif self.mode in ("workweek", "week"):
            self.go(self.date + dt.timedelta(days=7 * n))
        else:
            m = self.date.month - 1 + n
            y = self.date.year + m // 12
            m = m % 12 + 1
            self.go(self.date.replace(year=y, month=m, day=min(self.date.day, pycal.monthrange(y, m)[1])))

    def set_mode(self, mode):
        self.mode = mode
        self.win.set_vset("cal_mode", mode)
        self.refresh()
        GLib.idle_add(self.scroll_to_work)

    def _nav_picked(self, cal):
        y, m, d = cal.get_date()
        self.go(dt.date(y, m + 1, d))

    # ------------------------------------------------------------ geometry
    def columns(self):
        w = self.area.get_allocated_width()
        n = len(self.days)
        cw = (w - TIME_W) / n
        return [(TIME_W + k * cw, cw) for k in range(n)]

    def y_of(self, t):
        return self._grid_top() + (t.hour + t.minute / 60.0) * self.hour_h()

    def time_at(self, x, y):
        cols = self.columns()
        adj = self.scroller.get_vadjustment()
        if adj is not None and y < adj.get_value() + self._grid_top():
            for k, (cx, cw) in enumerate(cols):
                if cx <= x < cx + cw:
                    return self.days[k], None
            return None, None
        for k, (cx, cw) in enumerate(cols):
            if cx <= x < cx + cw:
                h = (y - self._grid_top()) / self.hour_h()
                if h < 0:
                    return self.days[k], None
                mins = int(h * 60 // self.scale * self.scale)
                mins = max(0, min(24 * 60 - self.scale, mins))
                return self.days[k], day_start(self.days[k]) + dt.timedelta(minutes=mins)
        return None, None

    def month_cell(self, x, y):
        w, h = self.area.get_allocated_width(), self.area.get_allocated_height()
        cw, ch = w / 7.0, (h - 24) / 6.0
        c, r = int(x // cw), int((y - 24) // ch)
        if 0 <= c < 7 and 0 <= r < 6:
            return self.days[r * 7 + c], (c * cw, 24 + r * ch, cw, ch)
        return None, None

    # ------------------------------------------------------------ drawing
    def _text(self, cr, text, x, y, w, size=9, bold=False, color=(0.1, 0.1, 0.1), h=None, wrap=False):
        lay = PangoCairo.create_layout(cr)
        fd = Pango.FontDescription("Sans %s" % size)
        if bold:
            fd.set_weight(Pango.Weight.BOLD)
        lay.set_font_description(fd)
        lay.set_width(int(max(1, w) * Pango.SCALE))
        if h is not None:
            lay.set_height(int(max(1, h) * Pango.SCALE))
        lay.set_wrap(Pango.WrapMode.WORD_CHAR if wrap else Pango.WrapMode.CHAR)
        lay.set_ellipsize(Pango.EllipsizeMode.END)
        lay.set_text(text, -1)
        cr.set_source_rgb(*color)
        cr.move_to(x, y)
        PangoCairo.show_layout(cr, lay)
        return lay.get_pixel_size()

    def _colors(self):
        from . import appearance
        dark = appearance.is_dark()
        return {"bg": (0.12, 0.12, 0.12) if dark else (1, 1, 1), "off": (0.16, 0.16, 0.16) if dark else (0.96, 0.96, 0.97),
                "line": (0.3, 0.3, 0.3) if dark else (0.86, 0.86, 0.88), "half": (0.22, 0.22, 0.22) if dark else (0.93, 0.93, 0.95),
                "text": (0.94, 0.94, 0.94) if dark else (0.1, 0.1, 0.1), "dim": (0.65, 0.65, 0.65) if dark else (0.45, 0.45, 0.45),
                "today": rgb("#a8a8e0" if dark else "#333366")[:3], "dark": dark}

    def _draw(self, area, cr):
        if self.mode == "month":
            return self._draw_month(cr)
        C = self._colors()
        w = area.get_allocated_width()
        h = area.get_allocated_height()
        top = self._grid_top()
        hh = self.hour_h()
        cr.set_source_rgb(*C["bg"])
        cr.paint()
        cols = self.columns()
        today = dt.date.today()
        # working hours shaded off-hours
        for k, (cx, cw) in enumerate(cols):
            d = self.days[k]
            cr.set_source_rgb(*C["off"])
            if d.weekday() >= 5:
                cr.rectangle(cx, top, cw, 24 * hh)
            else:
                cr.rectangle(cx, top, cw, self.work[0] * hh)
                cr.rectangle(cx, top + self.work[1] * hh, cw, (24 - self.work[1]) * hh)
            cr.fill()
        # slot picked
        if self.slot is not None:
            s, e = self.slot
            for k, (cx, cw) in enumerate(cols):
                if self.days[k] == s.date():
                    cr.set_source_rgba(*rgb("#333366", 0.18))
                    y0 = self.y_of(s)
                    y1 = self.y_of(e) if e.date() == s.date() else top + 24 * hh
                    cr.rectangle(cx + 1, y0, cw - 2, max(4, y1 - y0))
                    cr.fill()
        # hour lines
        cr.set_line_width(1)
        for hr in range(25):
            y = top + hr * hh
            cr.set_source_rgb(*C["line"])
            cr.move_to(TIME_W - 6, int(y) + 0.5)
            cr.line_to(w, int(y) + 0.5)
            cr.stroke()
            if hr < 24:
                cr.set_source_rgb(*C["half"])
                cr.move_to(TIME_W, int(y + hh / 2) + 0.5)
                cr.line_to(w, int(y + hh / 2) + 0.5)
                cr.stroke()
                self._text(cr, "%02d:00" % hr, 4, y + 2, TIME_W - 10, 8, color=C["dim"])
        for k, (cx, cw) in enumerate(cols):
            cr.set_source_rgb(*C["line"])
            cr.move_to(int(cx) + 0.5, 0)
            cr.line_to(int(cx) + 0.5, h)
            cr.stroke()
        # now line
        now = dt.datetime.now(ical.local_tz())
        for k, (cx, cw) in enumerate(cols):
            if self.days[k] == now.date():
                y = self.y_of(now)
                cr.set_source_rgb(0.77, 0.17, 0.11)
                cr.set_line_width(2)
                cr.move_to(cx, y)
                cr.line_to(cx + cw, y)
                cr.stroke()
                cr.set_line_width(1)
        # timed appointments, side by side where they overlap
        timed = [i for i in self.instances if not i.all_day]
        for k, (cx, cw) in enumerate(cols):
            d = self.days[k]
            ds, de = day_start(d), day_start(d + dt.timedelta(days=1))
            todays = [i for i in timed if i.start < de and i.end > ds]
            self._layout(todays)
            for i in todays:
                s = max(i.start, ds)
                e = min(i.end, de)
                y0 = self.y_of(s) if s > ds else top
                y1 = self.y_of(e) if e < de else top + 24 * hh
                y1 = max(y1, y0 + hh / 2 - 2)
                ww = (cw - 8) / i.cols
                x0 = cx + 2 + i.col * ww
                self._block(cr, i, x0, y0 + 1, ww - 2, y1 - y0 - 2, C)
        # header with the days, then all-day appointments: they stay at the top while the hours scroll
        adj = self.scroller.get_vadjustment()
        off = adj.get_value() if adj is not None else 0
        cr.save()
        cr.translate(0, off)
        cr.set_source_rgb(*C["bg"])
        cr.rectangle(0, 0, w, top - 2)
        cr.fill()
        for k, (cx, cw) in enumerate(cols):
            d = self.days[k]
            col = C["today"] if d == today else C["text"]
            self._text(cr, d.strftime("%-d %A" if cw > 110 else "%-d %a"), cx + 6, 8, cw - 8, 10, bold=d == today, color=col)
            if d == today:
                cr.set_source_rgb(*C["today"])
                cr.rectangle(cx, 0, cw, 3)
                cr.fill()
        alld = [i for i in self.instances if i.all_day]
        rows = []
        for i in alld:
            s, e = i.start.date(), max(i.end.date(), i.start.date() + dt.timedelta(days=1))
            if i.end.time() == dt.time(0) and i.end.date() > s:
                e = i.end.date()
            r = 0
            while any(o for o in rows if o[0] == r and o[1] < e and o[2] > s):
                r += 1
            rows.append((r, s, e, i))
        for r, s, e, i in rows:
            ks = [k for k, d in enumerate(self.days) if s <= d < e]
            if not ks:
                continue
            x0 = cols[ks[0]][0] + 2
            x1 = cols[ks[-1]][0] + cols[ks[-1]][1] - 2
            self._block(cr, i, x0, HEAD_H + r * ALLDAY_ROW, x1 - x0, ALLDAY_ROW - 3, C, one_line=True)
        cr.set_source_rgb(*C["line"])
        cr.move_to(0, top - 2.5)
        cr.line_to(w, top - 2.5)
        cr.stroke()
        cr.restore()
        for r, s, e, i in rows:
            if i.rect:
                x, y, ww, hh2 = i.rect
                i.rect = (x, y + off, ww, hh2)

    def _layout(self, items):
        """Overlapping appointments share the day's width in columns."""
        items.sort(key=lambda i: (i.start, -(i.end - i.start).total_seconds()))
        group, group_end = [], None
        for i in items + [None]:
            if i is None or (group_end is not None and i.start >= group_end):
                cols = []
                for g in group:
                    for ci, last in enumerate(cols):
                        if last <= g.start:
                            g.col = ci
                            cols[ci] = g.end
                            break
                    else:
                        g.col = len(cols)
                        cols.append(g.end)
                for g in group:
                    g.cols = max(1, len(cols))
                group, group_end = [], None
                if i is None:
                    break
            group.append(i)
            group_end = max(group_end, i.end) if group_end else i.end

    def _block(self, cr, i, x, y, w, h, C, one_line=False):
        i.rect = (x, y, w, h)
        r, g, b, _a = rgb(i.cal["color"])
        sel = self.selected is not None and self.selected.row["id"] == i.row["id"] and self.selected.start == i.start
        busy = i.event.busy
        cr.set_source_rgba(r, g, b, 0.85 if sel else (0.22 if not C["dark"] else 0.45))
        cr.rectangle(x, y, w, h)
        cr.fill()
        cr.set_source_rgb(r, g, b)
        cr.rectangle(x, y, 4, h)
        cr.fill()
        if busy == "tentative":
            cr.set_source_rgb(*C["bg"])
            for yy in range(int(y), int(y + h), 6):
                cr.rectangle(x, yy, 4, 3)
            cr.fill()
        tc = (1, 1, 1) if sel else C["text"]
        title = i.event.summary or "(No subject)"
        if one_line:
            self._text(cr, title, x + 8, y + 3, w - 10, 8.5, color=tc)
            return
        lines = title + ("\n" + i.event.location if i.event.location and h > 34 else "")
        if i.recurring:
            lines = "⟳ " + lines
        self._text(cr, lines, x + 8, y + 2, w - 10, 8.5, color=tc, h=h - 4, wrap=True)

    def _draw_month(self, cr):
        C = self._colors()
        w, h = self.area.get_allocated_width(), self.area.get_allocated_height()
        cr.set_source_rgb(*C["bg"])
        cr.paint()
        cw, ch = w / 7.0, (h - 24) / 6.0
        names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        ws = self.week_start()
        for c in range(7):
            self._text(cr, names[(c + ws) % 7], c * cw + 6, 4, cw - 8, 9, color=C["dim"])
        today = dt.date.today()
        for k, d in enumerate(self.days):
            r, c = divmod(k, 7)
            x, y = c * cw, 24 + r * ch
            if d.month != self.date.month:
                cr.set_source_rgb(*C["off"])
                cr.rectangle(x, y, cw, ch)
                cr.fill()
            if self.slot is not None and self.slot[0].date() == d:
                cr.set_source_rgba(*rgb("#333366", 0.15))
                cr.rectangle(x, y, cw, ch)
                cr.fill()
            cr.set_source_rgb(*C["line"])
            cr.rectangle(int(x) + 0.5, int(y) + 0.5, cw, ch)
            cr.stroke()
            label = d.strftime("%b %-d") if d.day == 1 or k == 0 else str(d.day)
            self._text(cr, label, x + 6, y + 3, cw - 10, 9, bold=d == today, color=C["today"] if d == today else C["text"])
            ds, de = day_start(d), day_start(d + dt.timedelta(days=1))
            its = [i for i in self.instances if i.start < de and i.end > ds]
            room = max(0, int((ch - 22) // 18))
            for n, i in enumerate(its[:room]):
                if n == room - 1 and len(its) > room:
                    self._text(cr, "+%d more" % (len(its) - n), x + 6, y + 20 + n * 18, cw - 10, 8, color=C["dim"])
                    break
                if i.all_day:
                    self._block(cr, i, x + 3, y + 20 + n * 18, cw - 6, 16, C, one_line=True)
                else:
                    i.rect = (x + 3, y + 20 + n * 18, cw - 6, 16)
                    rr, gg, bb, _a = rgb(i.cal["color"])
                    sel = self.selected is not None and self.selected.row["id"] == i.row["id"] and self.selected.start == i.start
                    if sel:
                        cr.set_source_rgba(rr, gg, bb, 0.85)
                        cr.rectangle(*i.rect)
                        cr.fill()
                    cr.set_source_rgb(rr, gg, bb)
                    cr.arc(x + 10, y + 28 + n * 18, 3.5, 0, 2 * math.pi)
                    cr.fill()
                    self._text(cr, "%s %s" % (i.start.strftime("%H:%M"), i.event.summary or "(No subject)"),
                               x + 18, y + 21 + n * 18, cw - 22, 8.5, color=(1, 1, 1) if sel else C["text"])

    # ------------------------------------------------------------ mouse
    def hit(self, x, y):
        for i in reversed(self.instances):
            if i.rect and i.rect[0] <= x <= i.rect[0] + i.rect[2] and i.rect[1] <= y <= i.rect[1] + i.rect[3]:
                return i
        return None

    def _press(self, area, ev):
        area.grab_focus()
        i = self.hit(ev.x, ev.y)
        if ev.type == Gdk.EventType._2BUTTON_PRESS:
            if i is not None:
                self.win.run("open-event")
            else:
                self.win.run("new-appointment")
            return True
        if ev.button == 3:
            self.selected = i
            self.area.queue_draw()
            self._context(ev, i)
            return True
        self.selected = i
        if i is not None:
            self.slot = None
            if self.mode != "month" and not i.all_day and i.rect and not i.cal["readonly"]:
                edge = ev.y > i.rect[1] + i.rect[3] - 6
                self.drag = {"inst": i, "y0": ev.y, "x0": ev.x, "resize": edge, "moved": False}
        else:
            if self.mode == "month":
                d, _r = self.month_cell(ev.x, ev.y)
                if d:
                    s = day_start(d)
                    self.slot = (s, s + dt.timedelta(days=1))
            else:
                d, t = self.time_at(ev.x, ev.y)
                if d is not None and t is None:
                    s = day_start(d)
                    self.slot = (s, s + dt.timedelta(days=1))
                elif t is not None:
                    self.slot = (t, t + dt.timedelta(minutes=self.scale))
                    self.drag = {"slot": t, "inst": None}
        self.area.queue_draw()
        self.win.update_cal_status(self)
        return True

    def _motion(self, area, ev):
        d = self.drag
        if not d:
            i = self.hit(ev.x, ev.y)
            win = area.get_window()
            if win is not None and self.mode != "month":
                edge = i is not None and i.rect and not i.all_day and ev.y > i.rect[1] + i.rect[3] - 6
                win.set_cursor(Gdk.Cursor.new_from_name(win.get_display(), "ns-resize" if edge else "default"))
            return False
        if d.get("inst") is None and d.get("slot") is not None:
            day, t = self.time_at(ev.x, ev.y)
            if t is not None:
                a, b = sorted([d["slot"], t])
                self.slot = (a, b + dt.timedelta(minutes=self.scale))
                self.area.queue_draw()
            return True
        if abs(ev.y - d["y0"]) > 4 or abs(ev.x - d["x0"]) > 4:
            d["moved"] = True
        if d["moved"]:
            d["at"] = (ev.x, ev.y)
            self.area.queue_draw()
        return True

    def _release(self, area, ev):
        d, self.drag = self.drag, None
        if not d or d.get("inst") is None or not d.get("moved"):
            return False
        i = d["inst"]
        mins = int(round((ev.y - d["y0"]) / self.hour_h() * 60 / self.scale) * self.scale)
        if d["resize"]:
            new_end = i.end + dt.timedelta(minutes=mins)
            if new_end - i.start >= dt.timedelta(minutes=self.scale):
                self.win.cal_change_times(i, i.start, new_end)
        else:
            day_from = self.time_at(d["x0"], d["y0"])[0]
            day_to = self.time_at(ev.x, ev.y)[0] or day_from
            shift = dt.timedelta(days=(day_to - day_from).days if day_from and day_to else 0, minutes=mins)
            if shift:
                self.win.cal_change_times(i, i.start + shift, i.end + shift)
        return True

    def _context(self, ev, i):
        menu = Gtk.Menu()
        items = [("Open", "open-event"), ("Delete", "delete-event")] if i else \
            [("New Appointment", "new-appointment"), ("New All Day Event", "new-all-day"), ("New Meeting Request", "new-meeting"),
             None, ("Today", "cal-today"), ("Go to Date...", "cal-go-to")]
        if i:
            items[1:1] = [("Show As: Busy", "event-busy:busy"), ("Show As: Free", "event-busy:free"),
                          ("Show As: Tentative", "event-busy:tentative")]
        for x in items:
            if x is None:
                menu.append(Gtk.SeparatorMenuItem())
                continue
            mi = Gtk.MenuItem(label=x[0])
            mi.connect("activate", lambda _m, c=x[1]: self.win.run(c))
            menu.append(mi)
        menu.show_all()
        menu.attach_to_widget(self.area, None)
        menu.popup_at_pointer(ev)

    def key(self, ev):
        k = ev.keyval
        ctrl = ev.state & Gdk.ModifierType.CONTROL_MASK
        if k in (Gdk.KEY_Left, Gdk.KEY_Right) and not ctrl:
            delta = -1 if k == Gdk.KEY_Left else 1
            if self.mode == "month":
                self.go(self.date + dt.timedelta(days=delta))
            elif self.mode == "day":
                self.go(self.date + dt.timedelta(days=delta))
            else:
                self.go(self.date + dt.timedelta(days=delta))
            return True
        if k in (Gdk.KEY_Up, Gdk.KEY_Down) and self.mode == "month":
            self.go(self.date + dt.timedelta(days=-7 if k == Gdk.KEY_Up else 7))
            return True
        if k == Gdk.KEY_Page_Down:
            self.step(1)
            return True
        if k == Gdk.KEY_Page_Up:
            self.step(-1)
            return True
        if k == Gdk.KEY_Delete and self.selected is not None:
            self.win.run("delete-event")
            return True
        if k == Gdk.KEY_Return:
            self.win.run("open-event" if self.selected else "new-appointment")
            return True
        return False
