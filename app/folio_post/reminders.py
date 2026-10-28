"""Reminders: the Reminder window that comes up before appointments, with Dismiss and Snooze."""
import datetime as dt
import time

from gi.repository import GLib, Gtk

from . import ical

SNOOZE = [(5, "5 minutes"), (10, "10 minutes"), (15, "15 minutes"), (30, "30 minutes"), (60, "1 hour"), (240, "4 hours"),
          (1440, "1 day")]


class Reminders:
    def __init__(self, app):
        self.app = app
        self.store = app.store
        self.window = None
        self.timer = None
        self.shown = []

    def start(self):
        if self.timer is None:
            self.timer = GLib.timeout_add_seconds(30, lambda: (self.check(), True)[1])

    def _state(self):
        return self.store.get("reminders", {}) or {}

    def due(self, now=None):
        """[(key, summary, start, location)] of reminders due now (not dismissed, not snoozed)."""
        now = now or dt.datetime.now(ical.local_tz())
        st = self._state()
        out = []
        lo, hi = now - dt.timedelta(days=1), now + dt.timedelta(days=15)
        for cal in self.store.calendars():
            if not cal["shown"]:
                continue
            for row in self.store.events(cal["id"]):
                if row["start"] and row["start"] > hi.timestamp():
                    continue
                if row["until"] and row["until"] < lo.timestamp():
                    continue
                try:
                    evs = ical.events_of(ical.parse(row["ics"]))
                except Exception:
                    continue
                for e, s, en in ical.expand(evs, lo, hi):
                    m = e.reminder
                    if m is None:
                        continue
                    key = "%s|%s" % (e.uid, ical._key(s))
                    v = st.get(key)
                    if v == "dismissed" or (isinstance(v, (int, float)) and v > time.time()):
                        continue
                    if s - dt.timedelta(minutes=m) <= now < en:
                        out.append((key, e.summary or "(No subject)", s, e.location))
        # tasks with a reminder time
        from . import tasks as T
        for r in self.store.todos("task"):
            t = T.parse(r["data"])
            if t is None or t.done or t.reminder is None:
                continue
            key = "%s|task" % t.uid
            v = st.get(key)
            if v == "dismissed" or (isinstance(v, (int, float)) and v > time.time()):
                continue
            if t.reminder <= now:
                out.append((key, t.subject or "(No subject)", t.reminder.astimezone(ical.local_tz()), ""))
        out.sort(key=lambda x: x[2])
        return out

    def dismiss(self, keys):
        st = self._state()
        for k in keys:
            st[k] = "dismissed"
        # forget old entries
        if len(st) > 3000:
            st = dict(list(st.items())[-2000:])
        self.store.put("reminders", st)

    def snooze(self, keys, minutes):
        st = self._state()
        for k in keys:
            st[k] = time.time() + minutes * 60
        self.store.put("reminders", st)

    def check(self):
        items = self.due()
        new = [i for i in items if i[0] not in self.shown]
        if items and (new or self.window is None):
            self.show(items)
        elif not items and self.window is not None:
            self.window.destroy()
            self.window = None
        return items

    def show(self, items):
        if self.window is None:
            self.window = ReminderWindow(self)
        self.window.fill(items)
        self.window.present()
        self.shown = [i[0] for i in items]
        try:
            from gi.repository import Gio
            if self.app.get_dbus_connection() is not None:
                n = Gio.Notification.new("Reminder: %s" % items[0][1])
                n.set_body(items[0][2].strftime("%a %d/%m %H:%M") + ((" — " + items[0][3]) if items[0][3] else ""))
                self.app.send_notification("reminder", n)
        except Exception:
            pass


class ReminderWindow(Gtk.Window):
    def __init__(self, rem):
        Gtk.Window.__init__(self, title="Reminder")
        self.rem = rem
        self.set_default_size(460, 300)
        self.set_keep_above(True)
        self.set_icon_name("folio-post")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_border_width(10)
        self.head = Gtk.Label(xalign=0)
        box.pack_start(self.head, False, False, 0)
        self.model = Gtk.ListStore(str, str, str)
        self.tv = Gtk.TreeView(model=self.model)
        self.tv.get_selection().set_mode(Gtk.SelectionMode.MULTIPLE)
        self.tv.append_column(Gtk.TreeViewColumn("Subject", Gtk.CellRendererText(), text=1))
        self.tv.append_column(Gtk.TreeViewColumn("Due in", Gtk.CellRendererText(), text=2))
        sw = Gtk.ScrolledWindow()
        sw.add(self.tv)
        box.pack_start(sw, True, True, 0)
        row = Gtk.Box(spacing=6)
        b = Gtk.Button(label="Dismiss All")
        b.connect("clicked", lambda *_: self.dismiss(all_=True))
        row.pack_start(b, False, False, 0)
        b = Gtk.Button(label="Dismiss")
        b.connect("clicked", lambda *_: self.dismiss())
        row.pack_end(b, False, False, 0)
        box.pack_start(row, False, False, 0)
        row = Gtk.Box(spacing=6)
        row.pack_start(Gtk.Label(label="Click Snooze to be reminded again in:"), False, False, 0)
        box.pack_start(row, False, False, 0)
        row = Gtk.Box(spacing=6)
        self.snooze_combo = Gtk.ComboBoxText()
        for m, label in SNOOZE:
            self.snooze_combo.append(str(m), label)
        self.snooze_combo.set_active(0)
        row.pack_start(self.snooze_combo, True, True, 0)
        b = Gtk.Button(label="Snooze")
        b.connect("clicked", lambda *_: self.snooze())
        row.pack_end(b, False, False, 0)
        box.pack_start(row, False, False, 0)
        self.add(box)
        self.connect("destroy", lambda *_: setattr(rem, "window", None))
        self.show_all()

    def fill(self, items):
        self.model.clear()
        now = dt.datetime.now(ical.local_tz())
        for key, summ, s, loc in items:
            mins = int((s - now).total_seconds() // 60)
            due = ("%d minutes" % mins if mins < 60 else "%d hours" % (mins // 60)) if mins > 0 else ("Now" if mins > -5 else
                                                                                                   "%d minutes overdue" % -mins)
            self.model.append([key, summ, due])
        first = items[0]
        self.head.set_markup("<b>%s</b>\nStart time: %s%s" % (GLib.markup_escape_text(first[1]), first[2].strftime("%A, %d %B %Y %H:%M"),
                                                             ("\nLocation: " + GLib.markup_escape_text(first[3])) if first[3] else ""))
        self.tv.get_selection().select_path(Gtk.TreePath.new_first())

    def keys(self, all_=False):
        if all_:
            return [r[0] for r in self.model]
        m, paths = self.tv.get_selection().get_selected_rows()
        return [m[p][0] for p in paths]

    def dismiss(self, all_=False):
        self.rem.dismiss(self.keys(all_))
        self._after()

    def snooze(self):
        self.rem.snooze(self.keys(), int(self.snooze_combo.get_active_id()))
        self._after()

    def _after(self):
        items = self.rem.due()
        if items:
            self.fill(items)
        else:
            self.destroy()
