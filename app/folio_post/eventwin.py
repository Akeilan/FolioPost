"""The appointment and meeting window: subject, location, start and end, all day, recurrence,
reminder, Show As, calendar, notes; for a meeting, the attendees and Send."""
import datetime as dt
import re

from gi.repository import Gdk, GLib, Gtk

from . import APP_NAME, caldav, ical, icons, mime
from .dialogs import Dialogs
from .ribbon import Ribbon, Tab
from .ribbon_post import Builder

REMINDERS = [(None, "None"), (0, "0 minutes"), (5, "5 minutes"), (10, "10 minutes"), (15, "15 minutes"), (30, "30 minutes"),
             (60, "1 hour"), (120, "2 hours"), (240, "4 hours"), (720, "0.5 days"), (1080, "18 hours"), (1440, "1 day"),
             (2880, "2 days"), (10080, "1 week")]
SHOW_AS = [("free", "Free"), ("tentative", "Tentative"), ("busy", "Busy"), ("oof", "Out of Office")]


def times_list():
    return ["%02d:%02d" % (h, m) for h in range(24) for m in (0, 30)]


def parse_hm(text):
    m = re.match(r"\s*(\d{1,2})(?::?(\d{2}))?\s*(am|pm)?\s*$", text or "", re.I)
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2) or 0)
    if m.group(3):
        h = h % 12 + (12 if m.group(3).lower() == "pm" else 0)
    if h > 23 or mi > 59:
        return None
    return dt.time(h, mi)


def parse_date(text):
    for f in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d.%m.%Y", "%a %d/%m/%Y"):
        try:
            return dt.datetime.strptime(text.strip(), f).date()
        except ValueError:
            pass
    return None


class DateTimeRow(Gtk.Box):
    def __init__(self, when, all_day=False):
        Gtk.Box.__init__(self, spacing=6)
        self.date = Gtk.Entry()
        self.date.set_width_chars(16)
        self.date.set_text(when.strftime("%a %d/%m/%Y"))
        self.pick = Gtk.MenuButton()
        self.pick.add(Gtk.Label(label="▾"))
        pop = Gtk.Popover()
        self.cal = Gtk.Calendar()
        self.cal.select_month(when.month - 1, when.year)
        self.cal.select_day(when.day)
        self.cal.connect("day-selected-double-click", lambda c: (self._picked(), pop.popdown()))
        self.cal.connect("day-selected", lambda c: self._picked())
        self.cal.show()
        pop.add(self.cal)
        self.pick.set_popover(pop)
        self.time = Gtk.ComboBoxText.new_with_entry()
        for t in times_list():
            self.time.append_text(t)
        self.time.get_child().set_text(when.strftime("%H:%M"))
        self.time.get_child().set_width_chars(6)
        self.pack_start(self.date, False, False, 0)
        self.pack_start(self.pick, False, False, 0)
        self.pack_start(self.time, False, False, 0)
        self.set_all_day(all_day)

    def _picked(self):
        y, m, d = self.cal.get_date()
        self.date.set_text(dt.date(y, m + 1, d).strftime("%a %d/%m/%Y"))

    def set_all_day(self, on):
        self.time.set_visible(not on)
        self.time.set_no_show_all(on)

    def value(self):
        d = parse_date(self.date.get_text())
        t = parse_hm(self.time.get_child().get_text()) or dt.time(0)
        if d is None:
            return None
        return dt.datetime.combine(d, t).replace(tzinfo=ical.local_tz())

    def set_value(self, when):
        self.date.set_text(when.strftime("%a %d/%m/%Y"))
        self.time.get_child().set_text(when.strftime("%H:%M"))


class EventWindow(Gtk.Window):
    """Opens a new appointment (start/end given), or an existing one (row id; for a recurring one,
    `occurrence` is the instance's start when only that occurrence is being changed)."""

    def __init__(self, main, row_id=None, start=None, end=None, all_day=False, meeting=False, occurrence=None,
                 calendar=None, from_event=None):
        Gtk.Window.__init__(self)
        self.main = main
        self.app = main.app
        self.store = main.store
        self.dialogs = Dialogs(self)
        self.row_id = row_id
        self.occurrence = occurrence
        self.missing_log = []
        self.modified = False
        self.saved = False
        self.set_default_size(820, 640)
        self.set_icon_name("folio-post")
        self.header = Gtk.HeaderBar()
        self.header.set_show_close_button(True)
        self.header.get_style_context().add_class("folio-titlebar")
        self.title_label = Gtk.Label()
        self.title_label.get_style_context().add_class("title")
        self.header.set_custom_title(self.title_label)
        self.qat = Gtk.Box()
        b = Gtk.Button()
        b.add(icons.white_image("qat-save", 16))
        b.set_tooltip_text("Save (Ctrl+S)")
        b.connect("clicked", lambda *_: self.run("save"))
        self.qat.pack_start(b, False, False, 0)
        self.header.pack_start(self.qat)
        self.set_titlebar(self.header)
        self.overlay = Gtk.Overlay()
        self.add(self.overlay)
        self.outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.overlay.add(self.outer)
        self.ribbon = Ribbon(self.run, lambda: self.subject.grab_focus())
        self.ribbon.connect("file-clicked", lambda *_: self.show_backstage())
        self.outer.pack_start(self.ribbon, False, False, 0)

        # the event
        self.master = None           # ical.Event of the series / event being edited
        self.others = []             # other VEVENTs of the same object (changed instances)
        cal_id = calendar
        if row_id is not None:
            row = self.store.event(row_id)
            evs = ical.events_of(ical.parse(row["ics"]))
            masters = [e for e in evs if e.recurrence_id is None]
            self.master = masters[0] if masters else evs[0]
            self.others = [e for e in evs if e is not self.master]
            cal_id = row["calendar"]
            if occurrence is not None:
                ex = [e for e in self.others if e.recurrence_id and ical._key(e.recurrence_id) == ical._key(occurrence)]
                self.editing = ex[0] if ex else None
            else:
                self.editing = self.master
        elif from_event is not None:
            self.master = from_event
            self.editing = from_event
        else:
            start = start or dt.datetime.now(ical.local_tz()).replace(minute=0, second=0, microsecond=0) + dt.timedelta(hours=1)
            end = end or start + dt.timedelta(minutes=30)
            self.master = ical.new_event("", start, end, all_day, reminder=None if all_day else 15)
            if all_day:
                self.master.set_busy("free")
            self.editing = self.master
        self.cal_id = cal_id
        ev = self.editing or self.master
        if occurrence is not None and self.editing is None:
            length = (self.master.end or self.master.start) - self.master.start
            s0, e0 = occurrence, occurrence + length
        else:
            s0, e0 = ev.start, ev.end or ev.start
        if ev.all_day and e0 > s0:
            e0 = e0 - dt.timedelta(days=1)
        self.rrule = self.master.rrule if occurrence is None else ""
        self.attendees = ev.attendees
        self.is_meeting = meeting or bool(self.attendees)

        # fields
        grid = Gtk.Grid(column_spacing=8, row_spacing=6)
        grid.set_border_width(12)
        r = 0
        self.send_btn = Gtk.Button()
        sb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        sb.pack_start(icons.image("p-send", 32), False, False, 0)
        sb.pack_start(Gtk.Label(label="Send"), False, False, 0)
        self.send_btn.add(sb)
        self.send_btn.get_style_context().add_class("folio-send")
        self.send_btn.connect("clicked", lambda *_: self.run("send-invitation"))
        self.to_label = Gtk.Label(label="Required", xalign=0)
        self.to = Gtk.Entry()
        self.to.set_hexpand(True)
        self.to.set_text("; ".join(("%s <%s>" % (a["name"], a["email"])) if a["name"] else a["email"] for a in self.attendees
                                   if a["role"] != "OPT-PARTICIPANT"))
        self.opt_label = Gtk.Label(label="Optional", xalign=0)
        self.opt = Gtk.Entry()
        self.opt.set_text("; ".join(a["email"] for a in self.attendees if a["role"] == "OPT-PARTICIPANT"))
        grid.attach(self.send_btn, 0, r, 1, 2)
        grid.attach(self.to_label, 1, r, 1, 1)
        grid.attach(self.to, 2, r, 3, 1)
        grid.attach(self.opt_label, 1, r + 1, 1, 1)
        grid.attach(self.opt, 2, r + 1, 3, 1)
        self.meeting_widgets = [self.send_btn, self.to_label, self.to, self.opt_label, self.opt]
        r += 2
        grid.attach(Gtk.Label(label="Subject", xalign=0), 1, r, 1, 1)
        self.subject = Gtk.Entry()
        self.subject.set_hexpand(True)
        self.subject.set_text(ev.summary if (self.editing is not None or occurrence is None) else self.master.summary)
        self.subject.connect("changed", lambda *_: (self._dirty(), self.update_title()))
        grid.attach(self.subject, 2, r, 3, 1)
        r += 1
        grid.attach(Gtk.Label(label="Location", xalign=0), 1, r, 1, 1)
        self.location = Gtk.Entry()
        self.location.set_text(ev.location)
        self.location.connect("changed", lambda *_: self._dirty())
        grid.attach(self.location, 2, r, 3, 1)
        r += 1
        grid.attach(Gtk.Label(label="Start time", xalign=0), 1, r, 1, 1)
        self.start_row = DateTimeRow(s0, ev.all_day)
        grid.attach(self.start_row, 2, r, 1, 1)
        self.all_day = Gtk.CheckButton(label="All day event")
        self.all_day.set_active(ev.all_day)
        self.all_day.connect("toggled", self._all_day_toggled)
        grid.attach(self.all_day, 3, r, 1, 1)
        r += 1
        grid.attach(Gtk.Label(label="End time", xalign=0), 1, r, 1, 1)
        self.end_row = DateTimeRow(e0, ev.all_day)
        grid.attach(self.end_row, 2, r, 1, 1)
        self._length = e0 - s0
        self.start_row.time.connect("changed", self._start_moved)
        self.start_row.date.connect("changed", self._start_moved)
        r += 1
        self.recur_label = Gtk.Label(xalign=0)
        self.recur_label.set_line_wrap(True)
        grid.attach(self.recur_label, 2, r, 3, 1)
        r += 1
        grid.attach(Gtk.Label(label="Calendar", xalign=0), 1, r, 1, 1)
        self.cal_combo = Gtk.ComboBoxText()
        for c in self.store.calendars():
            if not c["readonly"] or c["id"] == cal_id:
                self.cal_combo.append(str(c["id"]), c["name"])
        if cal_id is None:
            cal_id = main.calview.default_calendar()["id"] if getattr(main, "calview", None) else None
        if cal_id is not None:
            self.cal_combo.set_active_id(str(cal_id))
        elif self.store.calendars():
            self.cal_combo.set_active(0)
        grid.attach(self.cal_combo, 2, r, 1, 1)
        r += 1
        self.notes = Gtk.TextView()
        self.notes.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.notes.get_buffer().set_text(ev.description)
        self.notes.get_buffer().connect("changed", lambda *_: self._dirty())
        self.notes.get_style_context().add_class("folio-editor")
        self.notes.set_left_margin(8)
        sw = Gtk.ScrolledWindow()
        sw.add(self.notes)
        sw.set_vexpand(True)
        sw.set_hexpand(True)
        grid.attach(sw, 0, r, 5, 1)
        self.outer.pack_start(grid, True, True, 0)
        self.reminder = ev.reminder if row_id is not None or from_event is not None else self.master.reminder
        self.busy = ev.busy
        self.categories = ev.categories
        self.build_ribbon()
        from .keytips import KeyTips
        self.keytips = KeyTips(self)
        self.connect("key-press-event", self.on_key)
        self.connect("delete-event", self.on_delete)
        self.show_all()
        for w in self.meeting_widgets:
            w.set_visible(self.is_meeting)
        self.start_row.set_all_day(ev.all_day)
        self.end_row.set_all_day(ev.all_day)
        self.update_recur_label()
        self.update_title()
        self.sync_ribbon()
        self.modified = False
        cal = self.store.calendar(cal_id) if cal_id else None
        self.readonly = bool(cal and cal["readonly"])
        GLib.idle_add(lambda: (self.subject.grab_focus(), False)[1])

    # ------------------------------------------------------------ ribbon
    def build_ribbon(self):
        B = Builder(self)
        r = self.ribbon
        t = r.building(Tab("Meeting" if self.is_meeting else "Appointment", "H"))
        B.group(t, "Actions", [
            B.big("Save & Close", "qat-save", "save-close", "AV"),
            B.big("Delete", "p-delete", "delete", "D"),
            [B.small("Forward", "p-forward", "forward", "FW"), B.small("Copy to My Calendar", "p-nav-calendar", "copy-to-calendar", "C")],
        ])
        B.group(t, "Attendees", [B.big("Invite Attendees", "p-nav-people", "invite", "I"),
                                 [B.small("Cancel Invitation", "p-cancel-all", "cancel-invitation", "CI")]])
        B.group(t, "Options", [
            [B.small("Show As", "p-delay", None, "B", menu=[(label, "show-as:" + k) for k, label in SHOW_AS]),
             B.small("Reminder", "p-delay", None, "R", menu=[(label, "reminder:%s" % ("none" if m is None else m)) for m, label in REMINDERS]),
             B.small("Recurrence", "p-send-receive", "recurrence", "E", tip="Recurrence (Ctrl+G)")],
            B.big("Time Zones", "p-options", "time-zones", "Z"),
        ])
        B.group(t, "Tags", [[B.small("Categorize", "p-categorize", None, "G",
                                     menu=[(n, "categorize:" + n) for n in ("Red", "Orange", "Yellow", "Green", "Blue", "Purple")] +
                                     [None, ("Clear All Categories", "categorize:")]),
                             B.small("High Importance", "p-high", "importance", "H")]])
        r.add_tab(t)
        r.select(t)

    def sync_ribbon(self):
        pass

    def show_backstage(self, page=None):
        menu = Gtk.Menu()
        for label, cmd in (("Save", "save"), ("Save As .ics...", "save-as"), ("Delete", "delete"), ("Close", "close")):
            mi = Gtk.MenuItem(label=label)
            mi.connect("activate", lambda _m, c=cmd: self.run(c))
            menu.append(mi)
        menu.show_all()
        menu.popup_at_widget(self.ribbon.file_button, Gdk.Gravity.SOUTH_WEST, Gdk.Gravity.NORTH_WEST, None)

    def run(self, cmd, *args):
        if cmd is None:
            return None
        name, _, arg = cmd.partition(":")
        fn = getattr(self, "act_" + name.replace("-", "_"), None)
        if fn is None:
            self.missing_log.append(cmd)
            self.dialogs.info("“%s” isn't available yet in %s." % (arg if name == "not-available" else cmd, APP_NAME))
            return None
        if self.keytips.active:
            self.keytips.leave()
        try:
            return fn(arg) if arg or _ else fn()
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.dialogs.message("Something went wrong running this command.\n\n%s" % e)
            return None

    def update_title(self):
        kind = "Meeting" if self.is_meeting else "Appointment"
        self.title_label.set_text("%s - %s" % (self.subject.get_text().strip() or "Untitled", kind))
        self.set_title(self.title_label.get_text())

    def update_recur_label(self):
        s = self.start_row.value()
        text = ical.describe_rrule(self.rrule, s) if self.rrule and s else ""
        self.recur_label.set_markup("<small>Recurrence: %s</small>" % GLib.markup_escape_text(text) if text else "")
        self.recur_label.set_visible(bool(text))
        # a series' dates are set in the Recurrence box
        for w in (self.start_row.date, self.start_row.pick, self.end_row.date, self.end_row.pick):
            w.set_sensitive(not self.rrule)

    def _dirty(self):
        self.modified = True

    def _all_day_toggled(self, b):
        on = b.get_active()
        self.start_row.set_all_day(on)
        self.end_row.set_all_day(on)
        self.busy = "free" if on else "busy"
        self._dirty()

    def _start_moved(self, *_):
        s = self.start_row.value()
        if s is not None and not getattr(self, "_moving", False):
            self._moving = True
            self.end_row.set_value(s + self._length)
            self._moving = False
        self._dirty()

    # ------------------------------------------------------------ the result
    def collect(self):
        s, e = self.start_row.value(), self.end_row.value()
        if s is None or e is None:
            self.dialogs.message("Type the dates as day/month/year.")
            return None
        ad = self.all_day.get_active()
        if ad:
            s = s.replace(hour=0, minute=0)
            e = e.replace(hour=0, minute=0) + dt.timedelta(days=1)
        if e < s:
            self.dialogs.message("The end time you entered occurs before the start time.")
            return None
        return s, e, ad

    def _apply(self, ev, s, e, ad):
        ev.set_text("SUMMARY", self.subject.get_text().strip())
        ev.set_text("LOCATION", self.location.get_text().strip())
        b = self.notes.get_buffer()
        ev.set_text("DESCRIPTION", b.get_text(b.get_start_iter(), b.get_end_iter(), False))
        ev.set_times(s, e, ad)
        ev.set_reminder(self.reminder)
        ev.set_busy(self.busy)
        ev.comp.set("CATEGORIES", ",".join(self.categories) if self.categories else None)
        if self.is_meeting:
            acc = self.organizer_account()
            people = [{"email": a, "name": n} for n, a in self._people(self.to.get_text())] + \
                     [{"email": a, "name": n, "role": "OPT-PARTICIPANT"} for n, a in self._people(self.opt.get_text())]
            old = {a["email"].lower(): a["status"] for a in ev.attendees}
            for p in people:
                p["status"] = old.get(p["email"].lower(), "NEEDS-ACTION")
            org = ev.organizer or ((acc["name"], acc["email"]) if acc else None)
            ev.set_attendees(people, org)
        ev.comp.set("SEQUENCE", str(ev.sequence + 1) if self.row_id is not None else "0")
        ev.touch()

    def _people(self, text):
        from .compose import parse_recipients
        return [(n, a) for n, a in parse_recipients(text) if a]

    def organizer_account(self):
        cal = self.store.calendar(int(self.cal_combo.get_active_id())) if self.cal_combo.get_active_id() else None
        if cal and cal["account"]:
            return self.store.account(cal["account"])
        accs = [a for a in self.store.accounts() if a["kind"] != "local"]
        return accs[0] if accs else None

    def act_save(self):
        got = self.collect()
        if got is None:
            return None
        if self.readonly:
            self.dialogs.message("This calendar is read-only. Use Copy to My Calendar to keep your own copy.")
            return None
        s, e, ad = got
        cid = int(self.cal_combo.get_active_id()) if self.cal_combo.get_active_id() else self.main.calview.default_calendar()["id"]
        if self.occurrence is not None:
            # this occurrence only: a changed instance with its RECURRENCE-ID
            ev = self.editing
            if ev is None:
                ev = ical.Event(ical.Component("VEVENT"))
                ev.comp.add("UID", self.master.uid)
                v, p = ical.fmt_time(self.occurrence, self.master.all_day, utc=False)
                ev.comp.add("RECURRENCE-ID", v, p)
                self.others.append(ev)
                self.editing = ev
            self._apply(ev, s, e, ad)
        else:
            self._apply(self.master, s, e, ad)
            self.master.comp.set("RRULE", self.rrule or None)
            if not self.rrule:
                self.others = []
        comps = [self.master] + self.others
        self.row_id = caldav.save_event(self.store, cid, comps, self.row_id)
        self.modified = False
        self.saved = True
        self.main.calendar_changed(push=True)
        return self.row_id

    def act_save_close(self):
        if self.is_meeting and self.to.get_text().strip() and not self.saved:
            return self.act_send_invitation()
        if self.act_save() is not None:
            self.destroy()

    def act_close(self):
        self.close()

    def on_delete(self, *a):
        if self.modified and not self.readonly:
            d = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.QUESTION,
                                  text="Want to save your changes?")
            d.add_button("Save", 1)
            d.add_button("Don't Save", 2)
            d.add_button("Cancel", 3)
            r = d.run()
            d.destroy()
            if r == 1:
                if self.act_save() is None:
                    return True
            elif r != 2:
                return True
        return False

    def act_delete(self):
        if self.row_id is None:
            self.modified = False
            self.destroy()
            return
        if self.is_meeting and self.organizer_is_me():
            self.send_itip("CANCEL")
        if self.occurrence is not None:
            # this occurrence: an exception date on the series
            v, p = ical.fmt_time(self.occurrence, self.master.all_day, utc=False)
            self.master.comp.add("EXDATE", v, p)
            self.others = [o for o in self.others if not (o.recurrence_id and ical._key(o.recurrence_id) == ical._key(self.occurrence))]
            caldav.save_event(self.store, self.store.event(self.row_id)["calendar"], [self.master] + self.others, self.row_id)
        else:
            caldav.delete_event(self.store, self.row_id)
        self.modified = False
        self.main.calendar_changed(push=True)
        self.destroy()

    def organizer_is_me(self):
        org = (self.editing or self.master).organizer
        me = {a["email"].lower() for a in self.store.accounts()}
        return org is None or org[1].lower() in me

    def act_invite(self):
        self.is_meeting = True
        for w in self.meeting_widgets:
            w.set_visible(True)
        self.update_title()
        self.to.grab_focus()

    def act_cancel_invitation(self):
        self.is_meeting = False
        self.to.set_text("")
        self.opt.set_text("")
        for w in self.meeting_widgets:
            w.set_visible(False)
        self.update_title()

    def act_send_invitation(self):
        if not self._people(self.to.get_text()) and not self._people(self.opt.get_text()):
            self.dialogs.message("There must be at least one name in the Required or Optional box.")
            return None
        if self.act_save() is None:
            return None
        self.send_itip("REQUEST")
        self.destroy()
        return True

    def send_itip(self, method):
        acc = self.organizer_account()
        if acc is None:
            self.dialogs.message("Add a mail account to send meeting requests.")
            return
        ev = self.editing or self.master
        if method == "CANCEL":
            ev.comp.set("STATUS", "CANCELLED")
        people = [(a["name"], a["email"]) for a in ev.attendees]
        if not people:
            return
        ics = ical.invitation(ev if self.occurrence is not None else self.master, method)
        subj = ("Canceled: " if method == "CANCEL" else "") + (ev.summary or "Meeting")
        when = "%s – %s" % (ev.start.astimezone(ical.local_tz()).strftime("%A, %d %B %Y %H:%M"),
                            (ev.end or ev.start).astimezone(ical.local_tz()).strftime("%H:%M"))
        text = "%s\n\nWhen: %s\nWhere: %s\n\n%s" % (ev.summary, when, ev.location, ev.description)
        send_calendar_mail(self.store, acc, people, subj, text, ics, method)
        self.app.send_receive([acc["id"]])

    def act_forward(self):
        ev = self.master
        acc = self.organizer_account()
        ics = ical.dumps(ical.calendar_of([ev] + self.others))
        self.app.compose(account=acc["id"] if acc else None, subject="FW: " + ev.summary,
                         attach_data=[("%s.ics" % (re.sub(r"[^\w -]", "", ev.summary) or "event"), "text/calendar", ics.encode())])

    def act_copy_to_calendar(self):
        cals = [c for c in self.store.calendars() if not c["readonly"]]
        if not cals:
            cid = self.store.add_calendar("Calendar", "#0078D4", "local")
        else:
            cid = cals[0]["id"]
        comps = [ical.Event(ical.parse(ical.dumps(ical.calendar_of([self.master]))).sub("VEVENT")[0])]
        caldav.save_event(self.store, cid, comps)
        self.main.calendar_changed(push=True)
        self.dialogs.info("Copied to %s." % self.store.calendar(cid)["name"])

    def act_show_as(self, how):
        self.busy = how
        self._dirty()

    def act_reminder(self, m):
        self.reminder = None if m == "none" else int(m)
        self._dirty()

    def act_categorize(self, name=""):
        if not name:
            self.categories = []
        elif name in self.categories:
            self.categories.remove(name)
        else:
            self.categories.append(name)
        self._dirty()

    def act_importance(self):
        ev = self.editing or self.master
        ev.comp.set("PRIORITY", None if ev.comp.get("PRIORITY") == "1" else "1")
        self._dirty()

    def act_time_zones(self):
        tzname = getattr(ical.local_tz(), "key", "local time")
        self.dialogs.info("Times are in your computer's time zone (%s). Appointments from other time zones are shown "
                          "converted to it." % tzname)

    def act_save_as(self):
        dlg = Gtk.FileChooserDialog(title="Save As", transient_for=self, action=Gtk.FileChooserAction.SAVE)
        dlg.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Save", Gtk.ResponseType.OK)
        dlg.set_current_name((re.sub(r"[^\w -]", "", self.subject.get_text()) or "event") + ".ics")
        path = dlg.get_filename() if dlg.run() == Gtk.ResponseType.OK else None
        dlg.destroy()
        if path:
            with open(path, "w") as fh:
                fh.write(ical.dumps(ical.calendar_of([self.master] + self.others)))

    def act_recurrence(self):
        s = self.start_row.value()
        if s is None:
            return
        got = recurrence_dialog(self, s, self.rrule, self._length)
        if got is None:
            return
        rule, start, end = got
        self.rrule = rule
        if start is not None:
            self.start_row.set_value(start)
            self.end_row.set_value(end)
        self.update_recur_label()
        self._dirty()

    def on_key(self, w, ev):
        ctrl = ev.state & Gdk.ModifierType.CONTROL_MASK
        if self.keytips.active:
            return self.keytips.key(ev)
        if ctrl and ev.keyval in (Gdk.KEY_s, Gdk.KEY_S):
            self.run("save")
            return True
        if ctrl and ev.keyval in (Gdk.KEY_g, Gdk.KEY_G):
            self.run("recurrence")
            return True
        if ctrl and ev.keyval in (Gdk.KEY_Return,) and self.is_meeting:
            self.run("send-invitation")
            return True
        if ev.keyval == Gdk.KEY_F10:
            self.keytips.start()
            return True
        if ev.keyval == Gdk.KEY_Escape:
            self.close()
            return True
        return False


def recurrence_dialog(parent, start, rule, length, answer=None):
    """The Appointment Recurrence box; returns (rule or '', start, end) or None. `answer` fills it in tests."""
    r = ical.parse_rrule(rule) if rule else {}
    d = Gtk.Dialog(title="Appointment Recurrence", transient_for=parent, modal=True)
    d.get_style_context().add_class("folio-dialog")
    box = d.get_content_area()
    box.set_border_width(12)
    box.set_spacing(8)
    box.pack_start(Gtk.Label(label="Recurrence pattern", xalign=0), False, False, 0)
    row = Gtk.Box(spacing=16)
    kinds = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    radios = {}
    first = None
    for k, label in (("DAILY", "Daily"), ("WEEKLY", "Weekly"), ("MONTHLY", "Monthly"), ("YEARLY", "Yearly")):
        b = Gtk.RadioButton.new_with_label_from_widget(first, label)
        first = first or b
        radios[k] = b
        kinds.pack_start(b, False, False, 0)
    row.pack_start(kinds, False, False, 0)
    detail = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    ib = Gtk.Box(spacing=6)
    ib.pack_start(Gtk.Label(label="Recur every"), False, False, 0)
    interval = Gtk.SpinButton.new_with_range(1, 99, 1)
    interval.set_value(int(r.get("INTERVAL", "1") or 1))
    ib.pack_start(interval, False, False, 0)
    unit = Gtk.Label(label="week(s) on:")
    ib.pack_start(unit, False, False, 0)
    detail.pack_start(ib, False, False, 0)
    days = Gtk.Box(spacing=4)
    names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    on = [w for _n, w in ical._byday(r.get("BYDAY", ""))] or [start.weekday()]
    checks = []
    for i, n in enumerate(names):
        c = Gtk.CheckButton(label=n)
        c.set_active(i in on)
        checks.append(c)
        days.pack_start(c, False, False, 0)
    detail.pack_start(days, False, False, 0)
    weekdays_only = Gtk.CheckButton(label="Every weekday")
    weekdays_only.set_active(r.get("BYDAY") == "MO,TU,WE,TH,FR" and r.get("FREQ") == "DAILY")
    detail.pack_start(weekdays_only, False, False, 0)
    month_nth = Gtk.CheckButton(label="On the %s %s instead of day %d" % (["first", "second", "third", "fourth", "last"][min(4, (start.day - 1) // 7)],
                                                                          names[start.weekday()], start.day))
    month_nth.set_active("BYDAY" in r and r.get("FREQ") in ("MONTHLY", "YEARLY"))
    detail.pack_start(month_nth, False, False, 0)
    row.pack_start(detail, True, True, 0)
    box.pack_start(row, False, False, 0)
    box.pack_start(Gtk.Label(label="Range of recurrence", xalign=0), False, False, 4)
    no_end = Gtk.RadioButton.new_with_label(None, "No end date")
    after = Gtk.RadioButton.new_with_label_from_widget(no_end, "End after")
    by = Gtk.RadioButton.new_with_label_from_widget(no_end, "End by")
    count = Gtk.SpinButton.new_with_range(1, 999, 1)
    count.set_value(int(r.get("COUNT", "10") or 10))
    until = Gtk.Entry()
    until.set_text((ical.parse_time(r["UNTIL"])[0] if r.get("UNTIL") else start + dt.timedelta(days=90)).strftime("%d/%m/%Y"))
    (after if r.get("COUNT") else by if r.get("UNTIL") else no_end).set_active(True)
    box.pack_start(no_end, False, False, 0)
    a = Gtk.Box(spacing=6)
    a.pack_start(after, False, False, 0)
    a.pack_start(count, False, False, 0)
    a.pack_start(Gtk.Label(label="occurrences"), False, False, 0)
    box.pack_start(a, False, False, 0)
    b2 = Gtk.Box(spacing=6)
    b2.pack_start(by, False, False, 0)
    b2.pack_start(until, False, False, 0)
    box.pack_start(b2, False, False, 0)
    radios.get(r.get("FREQ", "WEEKLY"), radios["WEEKLY"]).set_active(True)

    def kind_changed(*_):
        k = [k for k, b in radios.items() if b.get_active()][0]
        unit.set_text({"DAILY": "day(s)", "WEEKLY": "week(s) on:", "MONTHLY": "month(s)", "YEARLY": "year(s)"}[k])
        days.set_visible(k == "WEEKLY")
        weekdays_only.set_visible(k == "DAILY")
        month_nth.set_visible(k in ("MONTHLY", "YEARLY"))
    for b in radios.values():
        b.connect("toggled", kind_changed)
    d.add_button("Remove Recurrence", 2)
    d.add_button("Cancel", Gtk.ResponseType.CANCEL)
    d.add_button("OK", Gtk.ResponseType.OK)
    d.show_all()
    kind_changed()
    d.parts = {"radios": radios, "interval": interval, "checks": checks, "after": after, "count": count, "by": by,
               "until": until, "weekdays": weekdays_only, "nth": month_nth}
    if answer is not None:
        resp = answer(d)
    else:
        resp = d.run()
    out = None
    if resp == 2:
        out = ("", None, None)
    elif resp == Gtk.ResponseType.OK:
        k = [k for k, b in radios.items() if b.get_active()][0]
        rr = {"FREQ": k}
        if int(interval.get_value()) > 1:
            rr["INTERVAL"] = str(int(interval.get_value()))
        if k == "WEEKLY":
            sel = [ical.WEEKDAYS[i] for i, c in enumerate(checks) if c.get_active()] or [ical.WEEKDAYS[start.weekday()]]
            rr["BYDAY"] = ",".join(sel)
        if k == "DAILY" and weekdays_only.get_active():
            rr = {"FREQ": "WEEKLY", "BYDAY": "MO,TU,WE,TH,FR"}
        if k in ("MONTHLY", "YEARLY") and month_nth.get_active():
            nth = (start.day - 1) // 7 + 1
            last = (start + dt.timedelta(days=7)).month != start.month
            rr["BYDAY"] = "%d%s" % (-1 if last and nth >= 4 else nth, ical.WEEKDAYS[start.weekday()])
            if k == "YEARLY":
                rr["BYMONTH"] = str(start.month)
        if after.get_active():
            rr["COUNT"] = str(int(count.get_value()))
        elif by.get_active():
            u = parse_date(until.get_text())
            if u:
                rr["UNTIL"] = u.strftime("%Y%m%d") + "T235959Z"
        # the series starts on its first matching day
        s = start
        first_occ = ical.occurrences(start, ical.fmt_rrule(rr), start + dt.timedelta(days=800), limit=1)
        if first_occ and first_occ[0] != start:
            s = first_occ[0]
        out = (ical.fmt_rrule(rr), s, s + length)
    d.destroy()
    return out


def send_calendar_mail(store, acc, people, subject, text, ics, method):
    """A meeting request, cancellation or reply: the text, and the iCalendar part Outlook and Gmail act on."""
    m = mime.build((acc["name"], acc["email"]) if acc["name"] != acc["email"] else ("", acc["email"]), people, (), (),
                   subject, text)
    m.add_alternative(ics, subtype="calendar", params={"method": method})
    m.add_attachment(ics.encode("utf-8"), maintype="application", subtype="ics", filename="invite.ics")
    raw = mime.to_bytes(m)
    store.queue(acc["id"], raw, [a for _n, a in people])
    return raw
