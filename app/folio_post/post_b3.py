"""Backlog 3 for Mail and Calendar: Automatic Replies (M3-02), the Scheduling Assistant (M3-03),
other people's calendars and delegates (M3-04), and their commands in the main window."""
import datetime as dt
import threading

from gi.repository import GLib, Gtk

from . import freebusy

STATUS_COLORS = {"busy": (0.0, 0.47, 0.83), "tentative": (0.55, 0.75, 0.93), "oof": (0.53, 0.11, 0.51), "free": None}
LEVELS = [("None", "None"), ("Reviewer", "Reviewer (can read items)"), ("Author", "Author (can read and create items)"),
          ("Editor", "Editor (can read, create, and modify items)")]


# ---------------------------------------------------------------- Scheduling Assistant
class SchedulingAssistant(Gtk.Dialog):
    """Everyone's free/busy for the meeting's day, the meeting time on top; click a time to move the
    meeting there, AutoPick finds the next time all are free."""
    HOURS = (7, 20)
    SLOT = 30

    def __init__(self, ew, people, start, end, lookup=None):
        Gtk.Dialog.__init__(self, title="Scheduling Assistant", transient_for=ew, modal=True)
        self.ew = ew
        self.get_style_context().add_class("folio-dialog")
        self.set_default_size(900, 420)
        self.add_button("Cancel", Gtk.ResponseType.CANCEL)
        ok = self.add_button("OK", Gtk.ResponseType.OK)
        ok.get_style_context().add_class("folio-default")
        self.people = people                     # [(name, email, role)]
        self.start, self.end = start, end
        self.length = end - start
        self.lookup = lookup or (lambda emails, a, b: freebusy.lookup(ew.app, ew.organizer_account(), emails, a, b))
        self.busy = {}
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin=10)
        self.get_content_area().pack_start(box, True, True, 0)
        bar = Gtk.Box(spacing=6)
        prev = Gtk.Button(label="<")
        nxt = Gtk.Button(label=">")
        self.day_label = Gtk.Label()
        self.day_label.set_width_chars(26)
        auto = Gtk.Button(label="AutoPick Next >>")
        prev.connect("clicked", lambda *_: self.shift_day(-1))
        nxt.connect("clicked", lambda *_: self.shift_day(1))
        auto.connect("clicked", lambda *_: self.autopick())
        for w in (prev, self.day_label, nxt):
            bar.pack_start(w, False, False, 0)
        bar.pack_end(auto, False, False, 0)
        box.pack_start(bar, False, False, 0)
        self.area = Gtk.DrawingArea()
        self.area.set_size_request(860, 60 + 26 * (len(people) + 2))
        self.area.add_events(1 << 8)            # button press
        self.area.connect("draw", self.on_draw)
        self.area.connect("button-press-event", self.on_click)
        box.pack_start(self.area, True, True, 0)
        legend = Gtk.Label(xalign=0)
        legend.set_markup("<small>Busy  ·  Tentative  ·  Out of Office  ·  hatched: No Information</small>")
        box.pack_start(legend, False, False, 0)
        self.status = Gtk.Label(xalign=0)
        box.pack_start(self.status, False, False, 0)
        self.day = start.astimezone().date()
        self.refresh()
        self.show_all()

    def window(self):
        lt = self.start.astimezone().tzinfo
        a = dt.datetime.combine(self.day, dt.time(0), lt)
        return a, a + dt.timedelta(days=1)

    def refresh(self, wait=False):
        a, b = self.window()
        self.day_label.set_markup("<b>%s</b>" % self.day.strftime("%A, %d %B %Y"))
        emails = [e for _n, e, _r in self.people]
        self.status.set_text("Getting free/busy...")

        def work():
            try:
                got = self.lookup(emails, a - dt.timedelta(days=1), b + dt.timedelta(days=14))
            except Exception:
                got = {}
            GLib.idle_add(done, got)

        def done(got):
            self.busy = got
            self.status.set_text("")
            self.area.queue_draw()
            return False
        if wait:
            done(self.lookup(emails, a - dt.timedelta(days=1), b + dt.timedelta(days=14)))
        else:
            threading.Thread(target=work, daemon=True).start()

    def shift_day(self, n):
        self.day += dt.timedelta(days=n)
        self.area.queue_draw()
        self.day_label.set_markup("<b>%s</b>" % self.day.strftime("%A, %d %B %Y"))

    def _x(self, w, t):
        a, _b = self.window()
        h0, h1 = self.HOURS
        left = 220
        frac = ((t - a).total_seconds() / 3600 - h0) / (h1 - h0)
        return left + frac * (w - left - 10)

    def on_draw(self, area, cr):
        w = area.get_allocated_width()
        ctx = area.get_style_context()
        fg = ctx.get_color(ctx.get_state())
        a, _b = self.window()
        h0, h1 = self.HOURS
        top = 30
        row = 26
        cr.set_line_width(1)
        cr.set_font_size(11)
        for h in range(h0, h1 + 1):
            x = self._x(w, a + dt.timedelta(hours=h))
            cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.25)
            cr.move_to(x + 0.5, top - 6)
            cr.line_to(x + 0.5, top + row * (len(self.people) + 1))
            cr.stroke()
            cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.8)
            cr.move_to(x + 2, top - 10)
            cr.show_text("%d:00" % h)
        rows = [("All Attendees", None, "")] + self.people
        for i, (name, email, _role) in enumerate(rows):
            y = top + row * i
            cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.9)
            cr.move_to(8, y + 17)
            cr.show_text((name or email or "")[:32])
            cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.15)
            cr.rectangle(220, y + row - 1, w - 230, 1)
            cr.fill()
            if email is None:
                slots = [s for p in self.people for s in (self.busy.get(p[1]) or [])]
                known = True
            else:
                slots = self.busy.get(email)
                known = slots is not None
                slots = slots or []
            if not known and self.busy:
                cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.18)
                x0, x1 = 220, w - 10
                for k in range(int(x0), int(x1), 8):
                    cr.move_to(k, y + row - 4)
                    cr.line_to(k + 6, y + 4)
                cr.stroke()
                continue
            for s, e, kind in slots:
                col = STATUS_COLORS.get(kind)
                if col is None:
                    continue
                x0, x1 = max(220, self._x(w, s)), min(w - 10, self._x(w, e))
                if x1 <= x0:
                    continue
                cr.set_source_rgb(*col)
                cr.rectangle(x0, y + 5, x1 - x0, row - 10)
                cr.fill()
        # the meeting
        x0, x1 = self._x(w, self.start), self._x(w, self.start + self.length)
        if x1 > 220 and x0 < w - 10:
            cr.set_source_rgba(0.06, 0.49, 0.06, 0.9)
            cr.set_line_width(2)
            cr.rectangle(max(220, x0), top, min(w - 10, x1) - max(220, x0), row * len(rows))
            cr.stroke()
        return False

    def on_click(self, area, ev):
        w = area.get_allocated_width()
        if ev.x < 220:
            return False
        a, _b = self.window()
        h0, h1 = self.HOURS
        hours = h0 + (ev.x - 220) / (w - 230) * (h1 - h0)
        mins = int(hours * 60) // self.SLOT * self.SLOT
        self.set_start(a + dt.timedelta(minutes=mins))
        return True

    def set_start(self, t):
        self.start = t
        self.day = t.astimezone().date()
        self.day_label.set_markup("<b>%s</b>" % self.day.strftime("%A, %d %B %Y"))
        self.area.queue_draw()

    def conflicts(self):
        out = []
        for name, email, _r in self.people:
            for s, e, kind in self.busy.get(email) or []:
                if kind != "free" and s < self.start + self.length and e > self.start:
                    out.append(name or email)
                    break
        return out

    def autopick(self):
        t = freebusy.next_free([self.busy.get(e) for _n, e, _r in self.people], self.start + dt.timedelta(minutes=self.SLOT),
                               self.length)
        if t is None:
            self.status.set_text("No time in the next two weeks when everyone is free.")
            return None
        self.set_start(t)
        self.status.set_text("")
        return t


def scheduling_assistant(ew, lookup=None, answer=None):
    """From the meeting window: Scheduling Assistant. Moves the meeting when OK is pressed."""
    got = ew.collect()
    if got is None:
        return None
    s, e, _ad = got
    acc = ew.organizer_account()
    people = []
    if acc:
        people.append((acc["name"] or acc["email"], acc["email"], "ORG"))
    people += [(n, a, "REQ") for n, a in ew._people(ew.to.get_text())]
    people += [(n, a, "OPT") for n, a in ew._people(ew.opt.get_text())]
    d = SchedulingAssistant(ew, people, s, e, lookup)
    ew.assistant = d
    resp = answer(d) if answer else d.run()
    new = d.start
    d.destroy()
    ew.assistant = None
    if resp == Gtk.ResponseType.OK and new != s:
        from . import ical
        lt = ical.local_tz()
        ew.start_row.set_value(new.astimezone(lt))
        ew.end_row.set_value((new + (e - s)).astimezone(lt))
        ew._dirty()
        return new
    return None


# ---------------------------------------------------------------- the main window's commands
class Backlog3Commands:
    """Mixed into the main window."""

    def act_automatic_replies(self):
        from . import autoreply
        return autoreply.dialog(self)

    def show_autoreply_bar(self):
        acc = self.current_account()
        on = bool(acc and self.store.get("autoreply-on:%d" % acc["id"]))
        bar = getattr(self, "autoreply_bar", None)
        if bar is None:
            return on
        if on:
            bar.set_no_show_all(False)
            bar.show_all()
        else:
            bar.hide()
        return on

    # ---- RSS Feeds (M3-07)
    def act_add_rss_feed(self, url=None):
        from . import rss
        if url is None:
            url = self.dialogs.ask_text("New RSS Feed", "Enter the location of the RSS Feed you want to add:", "")
        if not url or not url.strip():
            return None
        try:
            fid, n = rss.Feeds(self.store).add(url)
        except Exception as e:
            self.dialogs.info("Folio Post couldn't add the feed.\n\n%s" % e, "New RSS Feed")
            return None
        self.refresh_folders()
        self.go_folder(fid)
        return fid

    def act_remove_rss_feed(self):
        from . import rss
        f = self.current_folder()
        feeds = rss.Feeds(self.store)
        hit = [x for x in feeds.feeds() if f and x["folder"] == f["id"]]
        if not hit:
            self.dialogs.info("Select the folder of an RSS feed first.", "Remove RSS Feed")
            return None
        feeds.remove(hit[0]["url"])
        self.refresh_folders()
        return True

    # ---- Outlook templates (M3-06)
    def act_choose_form(self, path=None):
        """New Items > Choose Form: a new message from an Outlook template (.oft)."""
        if path is None:
            dlg = Gtk.FileChooserDialog(title="Choose Form", transient_for=self, action=Gtk.FileChooserAction.OPEN)
            dlg.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Open", Gtk.ResponseType.OK)
            f = Gtk.FileFilter()
            f.set_name("Outlook Templates (*.oft)")
            f.add_pattern("*.oft")
            f.add_pattern("*.OFT")
            dlg.add_filter(f)
            path = dlg.get_filename() if dlg.run() == Gtk.ResponseType.OK else None
            dlg.destroy()
        if not path:
            return None
        from . import msgfile
        try:
            fields = msgfile.read(open(path, "rb").read())
        except Exception as e:
            self.dialogs.message("Folio Post couldn't open the template “%s”.\n\n%s" % (path.rsplit("/", 1)[-1], e))
            return None
        join = lambda xs: "; ".join(("%s <%s>" % (n, a)) if n and n != a else a for n, a in xs)  # noqa: E731
        c = self.app.compose(to=join(fields["to"]), cc=join(fields["cc"]), bcc=join(fields["bcc"]), subject=fields["subject"],
                             body_text="" if fields["html"] else fields["text"], attach_data=fields["attachments"])
        if fields["html"]:
            c.editor.load_html(fields["html"])
        c.importance = fields["importance"]
        if hasattr(c, "sync_tags"):
            c.sync_tags()
        c.modified = False
        return c

    # ---- other people's calendars
    def _accounts_for_sharing(self):
        out = []
        for a in self.store.accounts():
            if a["kind"] == "ews":
                out.append(a)
            elif a["config"].get("imap_host") == "imap.gmail.com" and a["config"].get("auth") in ("oauth", "goa"):
                out.append(a)
            elif any(c["kind"] == "caldav" and c["account"] == a["id"] for c in self.store.calendars()):
                out.append(a)
        return out

    def _ask_person(self, title, text, with_level=False, accounts=None):
        d = Gtk.Dialog(title=title, transient_for=self, modal=True)
        d.get_style_context().add_class("folio-dialog")
        d.add_button("Cancel", Gtk.ResponseType.CANCEL)
        ok = d.add_button("OK", Gtk.ResponseType.OK)
        ok.get_style_context().add_class("folio-default")
        d.set_default_response(Gtk.ResponseType.OK)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin=12)
        d.get_content_area().pack_start(box, True, True, 0)
        box.pack_start(Gtk.Label(label=text, xalign=0), False, False, 0)
        acc_combo = Gtk.ComboBoxText()
        for a in accounts or []:
            acc_combo.append(str(a["id"]), a["email"])
        if accounts:
            acc_combo.set_active(0)
            if len(accounts) > 1:
                box.pack_start(acc_combo, False, False, 0)
        e = Gtk.Entry()
        e.set_activates_default(True)
        e.set_placeholder_text("name@example.com")
        box.pack_start(e, False, False, 0)
        lvl = None
        if with_level:
            lvl = Gtk.ComboBoxText()
            for k, label in LEVELS[1:]:
                lvl.append(k, label)
            lvl.set_active_id("Editor")
            box.pack_start(Gtk.Label(label="Calendar permission", xalign=0), False, False, 0)
            box.pack_start(lvl, False, False, 0)
        d.show_all()
        d.entry, d.level, d.account = e, lvl, acc_combo
        self.person_dialog = d
        resp = d.run()
        res = None
        if resp == Gtk.ResponseType.OK and e.get_text().strip():
            aid = int(acc_combo.get_active_id()) if acc_combo.get_active_id() else None
            res = (self.store.account(aid) if aid else None, e.get_text().strip(), lvl.get_active_id() if lvl else None)
        d.destroy()
        self.person_dialog = None
        return res

    def act_open_shared_calendar(self, email=None, aid=None):
        """Open Calendar > Open Shared Calendar: another person's calendar, through the account's server."""
        accs = self._accounts_for_sharing()
        if not accs:
            self.dialogs.info("Other people's calendars open through Microsoft Exchange, Google or a calendar server (CalDAV). "
                              "Add one of those accounts first.", "Open Shared Calendar")
            return None
        if email is None:
            got = self._ask_person("Open a Shared Calendar", "Name:", accounts=accs)
            if got is None:
                return None
            acc, email, _l = got
        else:
            acc = self.store.account(aid) if aid else accs[0]
        acc = acc or accs[0]
        try:
            ids = self.open_shared_for(acc, email)
        except Exception as e:
            self.dialogs.info("Folio Post couldn't open the calendar of %s.\n\n%s\n\nThey may need to share it with you "
                              "first (Calendar Permissions in their mail app)." % (email, e), "Open Shared Calendar")
            return None
        if hasattr(self, "_after_calendars"):
            self._after_calendars()
        for cid in ids:
            self.app.calsync.sync(cid)
        if hasattr(self, "_after_calendars"):
            self._after_calendars()
        return ids

    def open_shared_for(self, acc, email):
        from . import ews, caldav
        store = self.store
        if acc["kind"] == "ews":
            c = ews.client_for(acc, self.app.secrets, self.app.tokens)
            try:
                hits = c.resolve(email) if "@" not in email else []
                email = hits[0][1] if hits else email
                return [ews.open_shared_calendar(store, c, acc, email)]
            finally:
                c.close()
        if acc["config"].get("imap_host") == "imap.gmail.com":
            url = freebusy.google_shared_url(email)
            cid = store.add_calendar(email, caldav.COLORS[len(store.calendars()) % len(caldav.COLORS)], "google", url, acc["id"])
            return [cid]
        cal = [c for c in store.calendars() if c["kind"] == "caldav" and c["account"] == acc["id"]][0]
        cl = self.app.calsync.client_for(cal)
        pr = freebusy.caldav_find_principal(cl, email)
        if pr is None:
            raise RuntimeError("the calendar server doesn't know %s" % email)
        return self._add_principal_calendars(cl, cal, pr, email)

    def _add_principal_calendars(self, cl, cal, principal, label):
        from . import caldav
        store = self.store
        name, cals = freebusy.caldav_principal_calendars(cl, principal)
        src = store.get("calendar-source:%d" % cal["id"], {}) or {}
        ids = []
        for info in cals:
            u = cl.url(info["href"])
            if any(c["url"] == u for c in store.calendars()):
                continue
            cid = store.add_calendar("%s - %s" % (info["name"], name or label), info["color"] or
                                     caldav.COLORS[len(store.calendars()) % len(caldav.COLORS)], "caldav", u, cal["account"],
                                     info["readonly"])
            store.put("calendar-source:%d" % cid, dict(src, url=u))
            ids.append(cid)
        return ids

    def act_open_delegated_calendars(self):
        """The calendars of the people who made this account their delegate (CalDAV servers)."""
        found = []
        for cal in [c for c in self.store.calendars() if c["kind"] == "caldav"]:
            cl = self.app.calsync.client_for(cal)
            try:
                for pr, _mode in freebusy.caldav_delegations(cl):
                    found += self._add_principal_calendars(cl, cal, pr, pr.rstrip("/").split("/")[-1])
            except Exception:
                continue
            break
        for cid in found:
            self.app.calsync.sync(cid)
        if hasattr(self, "_after_calendars"):
            self._after_calendars()
        self.dialogs.info(("Opened %d calendar%s shared with you." % (len(found), "" if len(found) == 1 else "s")) if found else
                          "Nobody has shared a calendar with you on your calendar server yet. For Exchange and Google, use "
                          "Open Shared Calendar with their name.", "Calendars Shared With Me")
        return found

    # ---- Calendar Permissions / Delegate Access
    def act_calendar_permissions(self, aid=None):
        """Who may see or change your calendar: Exchange delegates, or a CalDAV server's calendar proxies."""
        accs = [a for a in self._accounts_for_sharing() if a["kind"] == "ews" or
                any(c["kind"] == "caldav" and c["account"] == a["id"] for c in self.store.calendars())]
        if not accs:
            self.dialogs.info("Calendar permissions are kept by Microsoft Exchange or a calendar server (CalDAV). For Google, "
                              "share the calendar on calendar.google.com.", "Calendar Permissions")
            return None
        acc = self.store.account(aid) if aid else accs[0]
        d = PermissionsDialog(self, acc)
        self.permissions_dialog = d
        d.run()
        d.destroy()
        self.permissions_dialog = None
        return True


class PermissionsDialog(Gtk.Dialog):
    def __init__(self, win, acc):
        Gtk.Dialog.__init__(self, title="Calendar Permissions - %s" % acc["email"], transient_for=win, modal=True)
        self.win, self.acc = win, acc
        self.get_style_context().add_class("folio-dialog")
        self.add_button("Close", Gtk.ResponseType.CLOSE)
        self.set_default_size(520, 360)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin=12)
        self.get_content_area().pack_start(box, True, True, 0)
        lab = Gtk.Label(xalign=0)
        lab.set_line_wrap(True)
        lab.set_markup("People listed here can see your calendar, or change it as your <b>delegate</b>.")
        box.pack_start(lab, False, False, 0)
        self.store_ = Gtk.ListStore(str, str)
        tv = Gtk.TreeView(model=self.store_)
        for k, title in enumerate(("Person", "Permission")):
            tv.append_column(Gtk.TreeViewColumn(title, Gtk.CellRendererText(), text=k))
        sw = Gtk.ScrolledWindow()
        sw.set_vexpand(True)
        sw.add(tv)
        box.pack_start(sw, True, True, 0)
        self.tv = tv
        bar = Gtk.Box(spacing=6)
        add = Gtk.Button(label="Add...")
        rem = Gtk.Button(label="Remove")
        add.connect("clicked", lambda *_: self.add())
        rem.connect("clicked", lambda *_: self.remove())
        bar.pack_start(add, False, False, 0)
        bar.pack_start(rem, False, False, 0)
        box.pack_start(bar, False, False, 0)
        self.fill()
        self.show_all()

    def _client(self):
        from . import ews
        if self.acc["kind"] == "ews":
            return ews.client_for(self.acc, self.win.app.secrets, self.win.app.tokens)
        cal = [c for c in self.win.store.calendars() if c["kind"] == "caldav" and c["account"] == self.acc["id"]][0]
        return self.win.app.calsync.client_for(cal)

    def list(self):
        c = self._client()
        if self.acc["kind"] == "ews":
            try:
                return [(d["email"], d["calendar"]) for d in c.get_delegates(self.acc["email"])]
            finally:
                c.close()
        names = {"read": "Reviewer", "write": "Editor"}
        return [(pr.rstrip("/").split("/")[-1], names[m]) for pr, m in freebusy.caldav_delegates(c)]

    def fill(self):
        self.store_.clear()
        try:
            for who, lvl in self.list():
                self.store_.append([who, lvl])
        except Exception as e:
            self.win.dialogs.info("Folio Post couldn't read the permissions.\n\n%s" % e, "Calendar Permissions")

    def grant(self, who, level):
        c = self._client()
        if self.acc["kind"] == "ews":
            try:
                existing = [d["email"].lower() for d in c.get_delegates(self.acc["email"])]
                c.add_delegate(self.acc["email"], who, calendar=level, update=who.lower() in existing)
            finally:
                c.close()
        else:
            pr = freebusy.caldav_find_principal(c, who) if "@" in who else "/principals/%s/" % who
            if pr is None:
                raise RuntimeError("the calendar server doesn't know %s" % who)
            freebusy.caldav_set_delegate(c, pr, "none" if level == "None" else "read" if level == "Reviewer" else "write")
        self.fill()

    def add(self, who=None, level=None):
        if who is None:
            got = self.win._ask_person("Add Permission", "Name:", with_level=True)
            if got is None:
                return
            _acc, who, level = got
        try:
            self.grant(who, level or "Editor")
        except Exception as e:
            self.win.dialogs.info("Folio Post couldn't give %s permission.\n\n%s" % (who, e), "Calendar Permissions")

    def remove(self, who=None):
        if who is None:
            m, it = self.tv.get_selection().get_selected()
            if it is None:
                return
            who = m[it][0]
        try:
            if self.acc["kind"] == "ews":
                c = self._client()
                try:
                    c.remove_delegate(self.acc["email"], who)
                finally:
                    c.close()
                self.fill()
            else:
                self.grant(who, "None")
        except Exception as e:
            self.win.dialogs.info("Folio Post couldn't remove %s.\n\n%s" % (who, e), "Calendar Permissions")
