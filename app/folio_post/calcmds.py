"""Calendar in the main window: its ribbon, the commands behind it, and switching between Mail and
Calendar on the Navigation bar."""
import datetime as dt
import os

from gi.repository import GLib, Gtk

from . import caldav, ical
from .ribbon import Ribbon, Tab
from .ribbon_post import Builder


def build_cal_ribbon(win, r):
    B = Builder(win)
    B.r = r
    na = lambda n: "not-available:" + n  # noqa: E731
    t = r.building(Tab("Home", "H"))
    B.group(t, "New", [
        B.big("New Appointment", "p-nav-calendar", "new-appointment", "N", tip="New Appointment (Ctrl+N)"),
        B.big("New Meeting", "p-meeting", "new-meeting", "MR", tip="New Meeting (Ctrl+Shift+Q)"),
        [B.small("New Items", "p-new-email", None, "I", menu=[("E-mail Message", "new-email-message"), ("All Day Event", "new-all-day"),
                                                            ("Contact", "new-contact"), ("Task", "new-task")])],
    ])
    B.group(t, "Go To", [B.big("Today", "p-nav-calendar", "cal-today", "OD"), B.big("Next 7 Days", "p-change-view", "cal-next7", "X")])
    B.group(t, "Arrange", [
        B.big("Day", "p-change-view", "cal-view:day", "D", tip="Day (Ctrl+Alt+1)"),
        B.big("Work Week", "p-change-view", "cal-view:workweek", "K", tip="Work Week (Ctrl+Alt+2)"),
        B.big("Week", "p-change-view", "cal-view:week", "W", tip="Week (Ctrl+Alt+3)"),
        B.big("Month", "p-change-view", "cal-view:month", "T", tip="Month (Ctrl+Alt+4)"),
    ])
    B.group(t, "Manage Calendars", [
        B.big("Open Calendar", "p-open-file", None, "OC", menu=[
            ("From Internet...", "open-calendar-internet"), ("From a Calendar Server (CalDAV)...", "open-calendar-server"),
            ("Google Calendar of an Account", "add-google-calendar"), ("From File...", "open-calendar-file"), None,
            ("Create New Blank Calendar...", "new-calendar")]),
        [B.small("Calendar Groups", "p-folder", na("Calendar Groups"), "G")],
    ])
    B.group(t, "Share", [[B.small("E-mail Calendar", "p-new-email", "email-calendar", "E"),
                          B.small("Publish Online", "p-send-all", "out-of-scope:Publish Online", "PO")]])
    B.group(t, "Find", [[B.small("Search People", "p-search-people", "search-people", "FP"),
                         B.small("Address Book", "p-address-book", "address-book", "AB")]])
    r.add_tab(t)
    t = r.building(Tab("Send / Receive", "S"))
    B.group(t, "Send & Receive", [B.big("Send/Receive All Folders", "p-send-receive", "send-receive", "A", tip="F9"),
                                  [B.small("Update Folder", "p-update-folder", "update-calendars", "F")]])
    B.group(t, "Preferences", [B.big("Work Offline", "p-offline", "work-offline", "W")])
    r.add_tab(t)
    t = r.building(Tab("Folder", "O"))
    B.group(t, "New", [B.big("New Calendar", "p-new-folder", "new-calendar", "N")])
    B.group(t, "Actions", [[B.small("Rename Calendar", "p-rename-folder", "rename-calendar", "RN"),
                            B.small("Delete Calendar", "p-delete-folder", "delete-calendar", "D"),
                            B.small("Set as Default", "p-nav-calendar", "default-calendar", "DF")]])
    B.group(t, "Properties", [B.big("Calendar Properties", "p-properties", "calendar-properties", "FP")])
    r.add_tab(t)
    t = r.building(Tab("View", "V"))
    B.group(t, "Arrangement", [
        B.big("Day", "p-change-view", "cal-view:day", "D"), B.big("Work Week", "p-change-view", "cal-view:workweek", "K"),
        B.big("Week", "p-change-view", "cal-view:week", "W"), B.big("Month", "p-change-view", "cal-view:month", "T"),
        [B.small("Time Scale", "p-delay", None, "C", menu=[("60 Minutes", "cal-scale:60"), ("30 Minutes", "cal-scale:30"),
                                                           ("15 Minutes", "cal-scale:15"), ("10 Minutes", "cal-scale:10"),
                                                           ("6 Minutes", "cal-scale:6"), ("5 Minutes", "cal-scale:5")]),
         B.small("Working Hours", "p-options", "work-hours", "WH")],
    ])
    B.group(t, "Color", [B.big("Color", "p-categorize", None, "CO", menu=[(n, "calendar-color:" + c) for n, c in (
        ("Blue", "#0078D4"), ("Red", "#E74856"), ("Green", "#16C60C"), ("Orange", "#FF8C00"), ("Purple", "#886CE4"),
        ("Teal", "#038387"), ("Pink", "#C239B3"), ("Brown", "#986F0B"), ("USPS Blue", "#333366"))])])
    B.group(t, "Layout", [B.big("Folder Pane", "p-folder-pane", None, "F",
                                menu=[("Normal", "cal-folder-pane:normal"), ("Off", "cal-folder-pane:off")])])
    r.add_tab(t)
    t = r.building(Tab("Help", "Y"))
    B.group(t, "Help", [B.big("Help", "p-help", "help", "H"), B.big("Keyboard Shortcuts", "p-options", "shortcuts", "K"),
                        B.big("About", "p-about", "about", "A")])
    r.add_tab(t)
    r.select(r.tab_by_name("Home"))


class CalendarCommands:
    """Mixed into the main window."""

    module = "mail"
    calview = None

    def ensure_calendar(self):
        if self.calview is not None:
            return self.calview
        from .calview import CalendarView
        self.calview = CalendarView(self)
        self.calview.show_all()
        self.modules.add_named(self.calview, "calendar")
        self.cal_ribbon = Ribbon(self.run, lambda: self.calview.area.grab_focus())
        self.cal_ribbon.connect("file-clicked", lambda *_: self.show_backstage())
        build_cal_ribbon(self, self.cal_ribbon)
        self.cal_ribbon.show_all()
        self.mail_ribbon = self.ribbon
        return self.calview

    def switch_module(self, name):
        if name == self.module:
            return
        if not hasattr(self, "mail_ribbon"):
            self.mail_ribbon = self.ribbon
        self.module = name
        if name == "calendar":
            self.ensure_calendar()
            new = self.cal_ribbon
            self.search.set_placeholder_text("Search Calendar (Ctrl+E)")
        elif name == "people":
            self.ensure_people()
            new = self.people_ribbon
            self.search.set_placeholder_text("Search People (Ctrl+E)")
        elif name == "tasks":
            self.ensure_tasks()
            new = self.tasks_ribbon
            self.search.set_placeholder_text("Search Tasks (Ctrl+E)")
        else:
            new = self.mail_ribbon
            self.search.set_placeholder_text("Search Current Mailbox (Ctrl+E)")
        if self.search.get_text():
            self.search.set_text("")
        old = self.ribbon
        if new is not old:
            self.outer.remove(old)
            self.outer.pack_start(new, False, False, 0)
            self.outer.reorder_child(new, 0)
            new.show_all()
            self.ribbon = new
        self.modules.set_visible_child_name(name)
        if name == "calendar":
            self.calview.refresh()
            self.calview.area.grab_focus()
            self.set_title("Calendar - Folio Post")
            self.title_label.set_text(self.get_title())
            self.update_cal_status(self.calview)
        elif name == "tasks":
            self.tasksview.refresh()
            self.tasksview.tv.grab_focus()
            self.set_title("Tasks - Folio Post")
            self.title_label.set_text(self.get_title())
        elif name == "people":
            self.peopleview.refresh_books()
            self.peopleview.refresh()
            self.peopleview.tv.grab_focus()
            self.set_title("Contacts - Folio Post")
            self.title_label.set_text(self.get_title())
        else:
            self.update_title()
            self.update_status()
        self._nav_quiet = True
        for k, b in self.nav_buttons.items():
            b.set_active(k == name)
        self._nav_quiet = False

    def update_cal_status(self, view):
        if self.module != "calendar":
            return
        n = len(view.instances)
        self.status.left.set_text("Items: %d" % n)
        errs = list(self.app.calsync.errors.values()) if hasattr(self.app, "calsync") else []
        if self.app.syncer.offline:
            self.status.right.set_text("Working Offline")
        elif errs:
            self.status.right.set_text("Calendar: " + errs[0])
        else:
            self.status.right.set_text("All folders are up to date.")

    def calendar_changed(self, push=False):
        if self.calview is not None:
            self.calview.invalidate()
            self.calview.refresh_calendars() if getattr(self, "_cals_dirty", False) else None
            self.calview.refresh()
        if push and not self.app.syncer.offline:
            if getattr(self, "_cal_push", None):
                GLib.source_remove(self._cal_push)
            self._cal_push = GLib.timeout_add_seconds(int(os.environ.get("FOLIO_POST_PUSH_DELAY", "8")), self._push_calendars)
        self.app.reminders.check()

    def _push_calendars(self):
        self._cal_push = None
        if self.app.syncer.offline:
            return False
        dirty = [c["id"] for c in self.store.calendars() if c["kind"] not in ("local", "ics") and
                 any(e["pending"] for e in self.store.events(c["id"], with_deleted=True))]
        if dirty:
            self.app.background(lambda: [self.app.calsync.sync(c) for c in dirty], lambda *_: self.calendar_changed())
        return False

    # ---- new and open
    def _slot(self):
        v = self.ensure_calendar()
        if v.slot is not None:
            s, e = v.slot
            if v.mode == "month" or (e - s) >= dt.timedelta(days=1):
                s = s.replace(hour=max(8, dt.datetime.now().hour + 1) if s.date() == dt.date.today() else 9)
                e = s + dt.timedelta(minutes=30)
            return s, e
        now = dt.datetime.now(ical.local_tz())
        s = dt.datetime.combine(v.date, dt.time(min(23, now.hour + 1) if v.date == now.date() else 9)).replace(tzinfo=ical.local_tz())
        return s, s + dt.timedelta(minutes=30)

    def act_new_appointment(self):
        from .eventwin import EventWindow
        s, e = self._slot()
        w = EventWindow(self, start=s, end=e)
        w.present()
        return w

    def act_new_meeting(self):
        from .eventwin import EventWindow
        s, e = self._slot()
        w = EventWindow(self, start=s, end=e, meeting=True)
        w.present()
        return w

    def act_new_all_day(self):
        from .eventwin import EventWindow
        v = self.ensure_calendar()
        d = v.slot[0].date() if v.slot else v.date
        s = dt.datetime.combine(d, dt.time(0)).replace(tzinfo=ical.local_tz())
        w = EventWindow(self, start=s, end=s + dt.timedelta(days=1), all_day=True)
        w.present()
        return w

    def act_new_email_message(self):
        acc = self.current_account()
        self.app.compose(account=acc["id"] if acc else None)

    def act_reply_with_meeting(self):
        """A meeting with the message's sender and recipients, its subject and text."""
        from . import mime
        from .eventwin import EventWindow
        ids = self.selected_ids()
        if not ids:
            return self.dialogs.info("Select a message first.")
        msg = mime.parse(self.store.raw(ids[0]))
        me = self.my_addresses()
        people = [(n, a) for n, a in mime.addresses(msg, "From") + mime.addresses(msg, "To") + mime.addresses(msg, "Cc")
                  if a and a.lower() not in me]
        self.ensure_calendar()
        s, e = self._slot()
        w = EventWindow(self, start=s, end=e, meeting=True)
        w.subject.set_text(mime.header(msg, "Subject"))
        w.to.set_text("; ".join(("%s <%s>" % (n, a)) if n else a for n, a in dict.fromkeys(people)))
        w.notes.get_buffer().set_text(mime.text_of(msg)[:5000])
        w.present()
        return w

    def act_open_event(self, which=None):
        from .eventwin import EventWindow
        v = self.ensure_calendar()
        i = v.selected
        if i is None:
            return None
        occurrence = None
        if i.recurring:
            if which is None:
                which = self.ask_occurrence("open")
            if which is None:
                return None
            if which == "occurrence":
                occurrence = i.event.recurrence_id or i.start
        w = EventWindow(self, row_id=i.row["id"], occurrence=occurrence)
        w.present()
        return w

    def ask_occurrence(self, verb):
        d = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.QUESTION,
                              text="This is one appointment in a series. What do you want to %s?" % verb)
        d.add_button("Just this one", 1)
        d.add_button("The entire series", 2)
        d.add_button("Cancel", 3)
        r = d.run()
        d.destroy()
        return {1: "occurrence", 2: "series"}.get(r)

    def act_delete_event(self, which=None):
        v = self.ensure_calendar()
        i = v.selected
        if i is None:
            return
        if i.cal["readonly"]:
            return self.dialogs.info("This calendar is read-only.")
        from .eventwin import EventWindow
        if i.recurring and which is None:
            which = self.ask_occurrence("delete")
            if which is None:
                return
        w = EventWindow(self, row_id=i.row["id"], occurrence=(i.event.recurrence_id or i.start) if which == "occurrence" else None)
        w.act_delete()
        v.selected = None
        self.calendar_changed(push=True)

    def act_event_busy(self, how):
        v = self.ensure_calendar()
        i = v.selected
        if i is None or i.cal["readonly"]:
            return
        evs = ical.events_of(ical.parse(i.row["ics"]))
        for e in evs:
            if e.recurrence_id is None or (i.event.recurrence_id and ical._key(e.recurrence_id) == ical._key(i.event.recurrence_id)):
                e.set_busy(how)
        caldav.save_event(self.store, i.row["calendar"], evs, i.row["id"])
        self.calendar_changed(push=True)

    def cal_change_times(self, inst, start, end):
        """A drag in the view: the appointment (or this occurrence of a series) moves."""
        if inst.cal["readonly"]:
            return self.dialogs.info("This calendar is read-only.")
        evs = ical.events_of(ical.parse(inst.row["ics"]))
        master = [e for e in evs if e.recurrence_id is None]
        if inst.recurring:
            rid = inst.event.recurrence_id or inst.start
            ex = [e for e in evs if e.recurrence_id is not None and ical._key(e.recurrence_id) == ical._key(rid)]
            if ex:
                ex[0].set_times(start, end, False)
                ex[0].touch()
            else:
                src = master[0] if master else inst.event
                o = ical.Event(ical.parse(ical.dumps(ical.calendar_of([src]))).sub("VEVENT")[0])
                o.comp.set("RRULE", None)
                o.comp.props = [p for p in o.comp.props if p[0] not in ("EXDATE", "RDATE")]
                v, p = ical.fmt_time(rid, src.all_day, utc=False)
                o.comp.set("RECURRENCE-ID", v, p)
                o.set_times(start, end, False)
                o.touch()
                evs.append(o)
        else:
            target = master[0] if master else evs[0]
            target.set_times(start, end, inst.event.all_day)
            target.comp.set("SEQUENCE", str(target.sequence + 1))
            target.touch()
        caldav.save_event(self.store, inst.row["calendar"], evs, inst.row["id"])
        self.calendar_changed(push=True)

    # ---- moving about
    def act_cal_today(self):
        v = self.ensure_calendar()
        v.go(dt.date.today())
        GLib.idle_add(v.scroll_to_work)

    def act_cal_next7(self):
        v = self.ensure_calendar()
        v.mode = "week"
        v.date = dt.date.today()
        v.refresh()

    def act_cal_view(self, mode):
        self.ensure_calendar().set_mode(mode)

    def act_cal_prev(self):
        self.ensure_calendar().step(-1)

    def act_cal_next(self):
        self.ensure_calendar().step(1)

    def act_cal_go_to(self, text=None):
        from .eventwin import parse_date
        v = self.ensure_calendar()
        if text is None:
            text = self.dialogs.ask_text("Go To Date", "Date (day/month/year):", v.date.strftime("%d/%m/%Y"))
        d = parse_date(text or "")
        if d:
            v.go(d)

    def act_cal_scale(self, n):
        v = self.ensure_calendar()
        v.scale = int(n)
        self.set_vset("cal_scale", int(n))
        v.refresh()

    def act_work_hours(self, spec=None):
        v = self.ensure_calendar()
        if spec is None:
            spec = self.dialogs.ask_text("Working Hours", "Start and end hour (like 8-17):", "%d-%d" % v.work)
        try:
            a, b = [int(x) for x in (spec or "").split("-")]
            if 0 <= a < b <= 24:
                v.work = (a, b)
                self.set_vset("work_start", a)
                self.set_vset("work_end", b)
                v.refresh()
        except ValueError:
            pass

    def act_cal_folder_pane(self, how):
        self.ensure_calendar().left.set_visible(how != "off")

    # ---- calendars
    def _after_calendars(self):
        if self.calview is not None:
            self.calview.refresh_calendars()
            self.calview.invalidate()
            self.calview.refresh()

    def act_new_calendar(self, name=None):
        if name is None:
            name = self.dialogs.ask_text("Create New Calendar", "Name:")
        if not name:
            return None
        cid = self.store.add_calendar(name, caldav.COLORS[len(self.store.calendars()) % len(caldav.COLORS)], "local")
        self._after_calendars()
        return cid

    def _cal_target(self):
        v = self.ensure_calendar()
        c = v.selected_calendar()
        if c is None:
            self.dialogs.info("Select a calendar in the list first.")
        return c

    def act_rename_calendar(self):
        c = self._cal_target()
        if c:
            n = self.dialogs.ask_text("Rename Calendar", "Name:", c["name"])
            if n:
                self.store.update_calendar(c["id"], name=n)
                self._after_calendars()

    def act_delete_calendar(self):
        c = self._cal_target()
        if c and self.ask("Remove the calendar “%s” from Folio Post? Events on a server stay there." % c["name"]):
            self.store.remove_calendar(c["id"])
            self._after_calendars()

    def act_default_calendar(self):
        c = self._cal_target()
        if c:
            self.store.put("default-calendar", c["id"])

    def act_calendar_color(self, color):
        c = self._cal_target()
        if c:
            self.store.update_calendar(c["id"], color=color)
            self._after_calendars()

    def act_calendar_properties(self):
        c = self._cal_target()
        if c:
            n = len(self.store.events(c["id"]))
            kind = {"local": "On this computer", "caldav": "Calendar server (CalDAV)", "google": "Google Calendar",
                    "ics": "Internet calendar (read-only)"}.get(c["kind"], c["kind"])
            self.dialogs.info("%s\n\nType: %s\nAddress: %s\nItems: %d" % (c["name"], kind, c["url"] or "-", n), "Calendar Properties")

    def act_open_calendar_internet(self, url=None):
        if url is None:
            url = self.dialogs.ask_text("New Internet Calendar Subscription",
                                        "The internet calendar's address (.ics), for example Proton Calendar's share link:")
        if not url:
            return None
        try:
            cid = self.app.calsync.add_ics(url.strip())
        except Exception as e:
            self.dialogs.message("Folio Post couldn't read a calendar from that address: %s" % e)
            return None
        self._after_calendars()
        return cid

    def act_open_calendar_file(self, path=None):
        if path is None:
            dlg = Gtk.FileChooserDialog(title="Open Calendar", transient_for=self, action=Gtk.FileChooserAction.OPEN)
            dlg.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Open", Gtk.ResponseType.OK)
            f = Gtk.FileFilter()
            f.set_name("iCalendar (*.ics)")
            f.add_pattern("*.ics")
            dlg.add_filter(f)
            path = dlg.get_filename() if dlg.run() == Gtk.ResponseType.OK else None
            dlg.destroy()
        if not path:
            return None
        return self.import_ics(open(path, encoding="utf-8", errors="replace").read())

    def import_ics(self, text, cid=None):
        cal = ical.parse(text)
        if cal is None:
            self.dialogs.message("That isn't an iCalendar file.")
            return 0
        target = self.store.calendar(cid) if cid else self.ensure_calendar().default_calendar()
        groups = {}
        for e in ical.events_of(cal):
            groups.setdefault(e.uid or str(id(e)), []).append(e)
        n = 0
        for uid, evs in groups.items():
            old = self.store.event_by_uid(target["id"], uid)
            caldav.save_event(self.store, target["id"], evs, old["id"] if old else None)
            n += 1
        self.calendar_changed(push=True)
        return n

    def act_open_calendar_server(self):
        from .accounts import CalDavDialog
        return CalDavDialog(self)

    def act_add_google_calendar(self):
        accs = [a for a in self.store.accounts() if a["config"].get("auth") == "oauth"]
        if not accs:
            self.dialogs.info("Google Calendar needs a Gmail account added with Google sign-in (File > Add Account). "
                              "Google doesn't let app passwords into calendars.")
            return None
        acc = accs[0]
        if any(c["account"] == acc["id"] and c["kind"] == "google" for c in self.store.calendars()):
            self.dialogs.info("The calendars of %s are already here." % acc["email"])
            return None

        def job():
            ids = self.app.calsync.add_google(acc["id"])
            for i in ids:
                self.app.calsync.sync(i)
            return ids
        self.app.background(job, lambda r, e: (self._after_calendars(),
                                               self.dialogs.message("Google Calendar couldn't be reached: %s" % e) if e else None))

    def act_email_calendar(self):
        v = self.ensure_calendar()
        days = v.range()
        start, end = days[0], days[-1]
        lines = []
        for i in v.instances:
            lines.append("%s  %s%s" % (i.start.strftime("%a %d/%m %H:%M") if not i.all_day else i.start.strftime("%a %d/%m") + " (all day)",
                                      i.event.summary, (" — " + i.event.location) if i.event.location else ""))
        text = "Calendar, %s to %s\n\n%s\n" % (start.strftime("%d/%m/%Y"), end.strftime("%d/%m/%Y"), "\n".join(lines) or "(nothing planned)")
        ics = ical.dumps(ical.calendar_of([i.event for i in v.instances if i.event.recurrence_id is None]))
        acc = self.current_account()
        return self.app.compose(account=acc["id"] if acc else None, subject="Calendar", body_text=text,
                                attach_data=[("calendar.ics", "text/calendar", ics.encode())])

    def act_update_calendars(self):
        if not self.app.syncer.offline:
            self.app.background(self.app.calsync.sync_all, lambda *_: self.calendar_changed())

    # ---- meeting requests
    def find_event(self, uid):
        for c in self.store.calendars():
            e = self.store.event_by_uid(c["id"], uid)
            if e is not None and e["pending"] != "deleted":
                return e
        return None

    def my_addresses(self):
        return {a["email"].lower() for a in self.store.accounts() if a["email"]}

    def my_status(self, row):
        me = self.my_addresses()
        for e in ical.events_of(ical.parse(row["ics"])):
            for a in e.attendees:
                if a["email"].lower() in me:
                    return a["status"]
        return None

    def respond_to_invitation(self, ics_text, partstat, account=None):
        """Accept, Tentative or Decline: the meeting goes in (or out of) the calendar, the organizer gets the answer."""
        from .eventwin import send_calendar_mail
        cal = ical.parse(ics_text)
        evs = ical.events_of(cal)
        if not evs:
            return None
        me = self.my_addresses()
        acc = account or next((a for a in self.store.accounts() if a["kind"] != "local"), None)
        my = acc["email"] if acc else (sorted(me)[0] if me else "")
        for e in evs:
            for a in e.attendees:
                if a["email"].lower() in me:
                    my = a["email"]
        for e in evs:
            people = e.attendees
            for a in people:
                if a["email"].lower() == my.lower():
                    a["status"] = partstat
            e.set_attendees(people, e.organizer)
            e.set_busy("tentative" if partstat == "TENTATIVE" else "busy")
            for i, (n, p, v) in enumerate(e.comp.props):
                if n == "METHOD":
                    e.comp.props.pop(i)
                    break
        old = self.find_event(evs[0].uid)
        if partstat == "DECLINED":
            if old is not None:
                caldav.delete_event(self.store, old["id"])
        else:
            target = self.store.calendar(old["calendar"]) if old else self.ensure_calendar().default_calendar()
            caldav.save_event(self.store, target["id"], evs, old["id"] if old else None)
        org = evs[0].organizer
        if acc is not None and org and org[1] and org[1].lower() not in me:
            reply = ical.reply_to(evs[0], my, partstat)
            word = {"ACCEPTED": "Accepted", "TENTATIVE": "Tentative", "DECLINED": "Declined"}[partstat]
            send_calendar_mail(self.store, acc, [org], "%s: %s" % (word, evs[0].summary), "%s has %s." % (
                acc["name"] or my, word.lower()), reply, "REPLY")
            if not self.app.syncer.offline:
                self.app.send_receive([acc["id"]])
        self.calendar_changed(push=True)
        return True

    def remove_canceled(self, ics_text):
        evs = ical.events_of(ical.parse(ics_text))
        if evs:
            old = self.find_event(evs[0].uid)
            if old is not None:
                caldav.delete_event(self.store, old["id"])
                self.calendar_changed(push=True)

    def record_reply(self, reply_event):
        """An attendee's answer to a meeting we organized updates its tracking."""
        old = self.find_event(reply_event.uid)
        if old is None or not reply_event.attendees:
            return
        who = reply_event.attendees[0]
        evs = ical.events_of(ical.parse(old["ics"]))
        changed = False
        for e in evs:
            people = e.attendees
            for a in people:
                if a["email"].lower() == who["email"].lower() and a["status"] != who["status"]:
                    a["status"] = who["status"]
                    changed = True
            if changed:
                e.set_attendees(people, e.organizer)
        if changed:
            caldav.save_event(self.store, old["calendar"], evs, old["id"])
            self.calendar_changed(push=True)
