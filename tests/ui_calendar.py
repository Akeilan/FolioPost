# Run inside Folio Post (FOLIO_TEST_SCRIPT): Calendar — views, appointments, recurrence, meetings, reminders and
# two-way CalDAV sync against the local test servers.
import datetime as dt
import os
import sys
import time
import traceback

from gi.repository import Gdk, Gtk

sys.path.insert(0, os.environ["FOLIO_TESTS"])
import davserver  # noqa: E402
import mailserver  # noqa: E402

FAILS = []
INFO = []
OUT = os.environ.get("UI_OUT", "/tmp/ui_out")
os.makedirs(OUT, exist_ok=True)


def pump(t=0.15):
    end = time.time() + t
    while time.time() < end:
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)
        time.sleep(0.003)


def wait(cond, t=20):
    end = time.time() + t
    while time.time() < end:
        pump(0.05)
        try:
            if cond():
                return True
        except Exception:
            pass
    return False


def check(cond, what):
    print(("ok   " if cond else "FAIL ") + what)
    sys.stdout.flush()
    if not cond:
        FAILS.append(what)


def shot(w, name):
    import cairo
    pump(0.3)
    alloc = w.get_allocation()
    img = cairo.ImageSurface(cairo.FORMAT_ARGB32, max(1, alloc.width), max(1, alloc.height))
    w.draw(cairo.Context(img))
    img.write_to_png(os.path.join(OUT, "cal_" + name + ".png"))


class Ev:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def key(name, ctrl=False, shift=False, alt=False):
    st = 0
    if ctrl:
        st |= Gdk.ModifierType.CONTROL_MASK
    if shift:
        st |= Gdk.ModifierType.SHIFT_MASK
    if alt:
        st |= Gdk.ModifierType.MOD1_MASK
    r = win.on_key(win, Ev(keyval=Gdk.keyval_from_name(name), state=Gdk.ModifierType(st), type=Gdk.EventType.KEY_PRESS))
    pump(0.1)
    return r


from folio_post import dialogs as D  # noqa: E402
from folio_post import window as W  # noqa: E402
ANSWERS = []
D.Dialogs.info = lambda self, text, title=None: INFO.append(text)
D.Dialogs.message = lambda self, text, title=None: INFO.append(text)
D.Dialogs.ask_text = lambda self, title, label, value="": ANSWERS.pop(0) if ANSWERS else value
W.PostWindow.ask = lambda self, text, yes="Yes", no="No": True
CHOICE = [1]
Gtk.Dialog.run = lambda d: CHOICE[0] if isinstance(d, Gtk.MessageDialog) else Gtk.ResponseType.CANCEL

try:
    from folio_post import caldav, ical, mime
    store = app.store
    L = ical.local_tz()
    dav = davserver.World()
    cals = dav.add_user("me@example.org", "secret", ("personal", "work"))
    cals["personal"].put("e1.ics", davserver.event("e1", "Dentist", "20261105T090000", "20261105T100000", tzid="Europe/Amsterdam"))
    cals["personal"].put("e2.ics", davserver.event("e2", "Yoga", "20261102T180000", "20261102T190000", "FREQ=WEEKLY;COUNT=6"))
    cals["work"].put("w1.ics", davserver.event("w1", "Board meeting", "20261104T140000", "20261104T160000"))
    _d, dport, dstop = davserver.start(dav)
    mw = mailserver.World()
    boxes = mw.add_user("me@example.org", "secret")
    mw.add_user("org@example.org", "pw")
    _m, ip, sp, mstop = mailserver.start(mw)
    cfg = {"imap_host": "127.0.0.1", "imap_port": ip, "imap_security": "none", "smtp_host": "127.0.0.1", "smtp_port": sp,
           "smtp_security": "none", "user": "me@example.org"}
    from folio_post.accounts import create_account
    aid = create_account(win, "Me", "me@example.org", cfg, "secret")
    wait(lambda: store.folder_by_role(aid, "inbox") is not None, 20)
    wait(lambda: not app.busy(), 10)

    # Calendar on the Navigation bar
    key("2", ctrl=True)
    check(win.module == "calendar" and win.calview is not None, "Ctrl+2 opens Calendar")
    check([t.name for t in win.ribbon.tabs] == ["Home", "Send / Receive", "Folder", "View", "Help"] and
          win.ribbon.tab_by_name("Home") is not None and any(getattr(c, "action", "") == "new-appointment" for c in win.ribbon.controls),
          "the Calendar ribbon")
    v = win.calview
    ids = app.calsync.add_caldav("http://127.0.0.1:%d/" % dport, "me@example.org", "secret")
    for i in ids:
        app.calsync.sync(i)
    win._after_calendars()
    pid = [i for i in ids if store.calendar(i)["name"] == "Personal"][0]
    wid = [i for i in ids if store.calendar(i)["name"] == "Work"][0]
    v.go(dt.date(2026, 11, 3))
    win.run("cal-view:workweek")
    names = sorted(set(i.event.summary for i in v.instances))
    check(names == ["Board meeting", "Dentist", "Yoga"], "work week shows both calendars: %s" % names)
    check(v.title.get_text().startswith("November 2"), "title: %s" % v.title.get_text())
    shot(win, "workweek")
    win.run("cal-view:month")
    yoga = [i for i in v.instances if i.event.summary == "Yoga"]
    check(len(yoga) == 5 and v.mode == "month", "month view: Yoga on the 5 Mondays shown (%d)" % len(yoga))
    shot(win, "month")
    key("1", ctrl=True, alt=True)
    check(v.mode == "day", "Ctrl+Alt+1: Day")
    key("3", ctrl=True, alt=True)
    check(v.mode == "week" and len(v.days) == 7, "Ctrl+Alt+3: Week")
    win.run("cal-view:workweek")
    # hide a calendar
    v.show_calendar(wid, False)
    check("Board meeting" not in [i.event.summary for i in v.instances], "unchecking a calendar hides it")
    v.show_calendar(wid, True)

    # new appointment
    v.slot = (dt.datetime(2026, 11, 3, 11, 0, tzinfo=L), dt.datetime(2026, 11, 3, 11, 30, tzinfo=L))
    for r in v.cal_list.get_children():
        if getattr(r, "cal_id", None) == pid:
            v.cal_list.select_row(r)
    ew = win.run("new-appointment")
    pump(0.3)
    check(ew is not None and ew.start_row.value() == dt.datetime(2026, 11, 3, 11, 0, tzinfo=L), "new appointment at the picked time")
    ew.subject.set_text("Lunch with Ann")
    ew.location.set_text("Café Noir")
    ew.end_row.set_value(dt.datetime(2026, 11, 3, 12, 30, tzinfo=L))
    ew.run("reminder:30")
    shot(ew, "appointment")
    ew.run("save-close")
    pump(0.3)
    lunch = [e for e in store.events(pid) if e["summary"] == "Lunch with Ann"]
    check(len(lunch) == 1 and lunch[0]["pending"] == "new", "saved, waiting to sync")
    check(any(i.event.summary == "Lunch with Ann" and i.event.location == "Café Noir" for i in v.instances), "shown in the view")
    ok = wait(lambda: any("Lunch with Ann" in d for _e, d in cals["personal"].items.values()), 15)
    check(ok, "sent to the calendar server")

    # recurrence through the Recurrence box
    from folio_post import eventwin
    ew = eventwin.EventWindow(win, start=dt.datetime(2026, 11, 2, 8, 0, tzinfo=L), end=dt.datetime(2026, 11, 2, 8, 30, tzinfo=L),
                              calendar=pid)
    ew.subject.set_text("Standup")

    def fill(d):
        p = d.parts
        p["radios"]["WEEKLY"].set_active(True)
        for i, c in enumerate(p["checks"]):
            c.set_active(i in (0, 2))
        p["after"].set_active(True)
        p["count"].set_value(4)
        return Gtk.ResponseType.OK
    got = eventwin.recurrence_dialog(ew, ew.start_row.value(), "", dt.timedelta(minutes=30), answer=fill)
    check(got and got[0] == "FREQ=WEEKLY;COUNT=4;BYDAY=MO,WE", "Recurrence box: %s" % (got,))
    ew.rrule = got[0]
    ew.update_recur_label()
    check("Every week on Monday, Wednesday" in ew.recur_label.get_text(), "recurrence described: %s" % ew.recur_label.get_text())
    ew.run("save-close")
    pump(0.3)
    v.go(dt.date(2026, 11, 2))
    win.run("cal-view:month")
    st = [i for i in v.instances if i.event.summary == "Standup"]
    check(len(st) == 4 and [i.start.day for i in st] == [2, 4, 9, 11], "4 occurrences, Mon and Wed: %s" % [i.start.day for i in st])
    # delete one occurrence
    v.selected = st[1]
    win.run("delete-event:occurrence")
    st = [i for i in v.instances if i.event.summary == "Standup"]
    check([i.start.day for i in st] == [2, 9, 11], "one occurrence deleted")
    # move one occurrence by dragging
    win.run("cal-view:workweek")
    v.go(dt.date(2026, 11, 9))
    occ = [i for i in v.instances if i.event.summary == "Standup" and i.start.day == 9][0]
    win.cal_change_times(occ, occ.start + dt.timedelta(hours=1), occ.end + dt.timedelta(hours=1))
    st = [i for i in v.load(dt.datetime(2026, 11, 1, tzinfo=L), dt.datetime(2026, 12, 1, tzinfo=L)) if i.event.summary == "Standup"]
    check([(i.start.day, i.start.hour) for i in st] == [(2, 8), (9, 9), (11, 8)], "a moved occurrence: %s" % [(i.start.day, i.start.hour) for i in st])
    # move a single appointment
    dent = [i for i in v.load(dt.datetime(2026, 11, 1, tzinfo=L), dt.datetime(2026, 12, 1, tzinfo=L)) if i.event.summary == "Dentist"][0]
    win.cal_change_times(dent, dent.start + dt.timedelta(days=1), dent.end + dt.timedelta(days=1))
    ok = wait(lambda: "20261106T090000" in cals["personal"].items["e1.ics"][1], 15)
    check(ok, "a drag reaches the server")
    # open the series
    v.go(dt.date(2026, 11, 2))
    yo = [i for i in v.instances if i.event.summary == "Yoga"][0]
    v.selected = yo
    w2 = win.run("open-event:series")
    pump(0.2)
    check(w2 is not None and w2.subject.get_text() == "Yoga" and "Every week" in w2.recur_label.get_text(), "open the series")
    w2.modified = False
    w2.destroy()
    # changed on the server, comes down
    cals["work"].put("w2.ics", davserver.event("w2", "Offsite", "20261105T090000", "20261105T170000"))
    key("F9")
    ok = wait(lambda: any(e["summary"] == "Offsite" for e in store.events(wid)), 20)
    check(ok, "F9 brings calendar changes")

    # reminders
    now = dt.datetime.now(L).replace(second=0, microsecond=0)
    soon = ical.new_event("Call Bob", now + dt.timedelta(minutes=10), now + dt.timedelta(minutes=40), reminder=15)
    caldav.save_event(store, pid, [soon])
    due = app.reminders.due()
    check(any(x[1] == "Call Bob" for x in due), "reminder due 15 minutes before")
    items = app.reminders.check()
    check(app.reminders.window is not None, "the Reminder window")
    shot(app.reminders.window, "reminder")
    app.reminders.window.snooze()
    check(not any(x[1] == "Call Bob" for x in app.reminders.due()), "Snooze")
    app.reminders.dismiss([k for k, *_ in due])
    check(not any(x[1] == "Call Bob" for x in app.reminders.due()), "Dismiss")

    # a meeting request arrives by mail; Accept
    org = ical.new_event("Project kickoff", dt.datetime(2026, 11, 10, 10, tzinfo=L), dt.datetime(2026, 11, 10, 11, tzinfo=L),
                         location="Room 4")
    org.set_attendees([{"email": "me@example.org", "name": "Me"}], ("Olga Org", "org@example.org"))
    req = ical.invitation(org)
    m = mime.build(("Olga Org", "org@example.org"), ["me@example.org"], subject="Project kickoff", text="Join us")
    m.add_alternative(req, subtype="calendar", params={"method": "REQUEST"})
    boxes["INBOX"].add(mime.to_bytes(m))
    key("1", ctrl=True)
    check(win.module == "mail", "Ctrl+1 back to Mail")
    key("F9")
    inbox = store.folder_by_role(aid, "inbox")
    ok = wait(lambda: any(r["subject"] == "Project kickoff" for r in store.messages(inbox["id"])), 20)
    pump(0.4)
    msg = [r for r in store.messages(inbox["id"]) if r["subject"] == "Project kickoff"][0]
    win.go_folder(inbox["id"])
    win.select_ids([msg["id"]])
    pump(0.3)
    check(win.reading.invite.get_visible() and "Project kickoff" in win.reading.invite_label.get_text(), "meeting request bar")
    shot(win, "invite")
    win.reading.answer_invite("ACCEPTED")
    pump(0.3)
    ev = win.find_event(org.uid)
    check(ev is not None and win.my_status(ev) == "ACCEPTED", "accepted: in the calendar")
    ok = wait(lambda: any(b"METHOD:REPLY" in r and b"PARTSTAT=ACCEPTED" in r for _f, rc, r in mw.smtp_log if "org@example.org" in rc), 20)
    check(ok, "the reply goes to the organizer")
    check("You accepted" in win.reading.invite_label.get_text(), "the bar says so")

    # a meeting we organize
    key("2", ctrl=True)
    v.slot = (dt.datetime(2026, 11, 12, 15, tzinfo=L), dt.datetime(2026, 11, 12, 16, tzinfo=L))
    mtg = win.run("new-meeting")
    pump(0.3)
    check(mtg.is_meeting and mtg.to.get_visible(), "New Meeting has attendees")
    mtg.to.set_text("Org <org@example.org>")
    mtg.subject.set_text("Review")
    mtg.run("send-invitation")
    ok = wait(lambda: any(b"METHOD:REQUEST" in r and b"Review" in r for _f, rc, r in mw.smtp_log if "org@example.org" in rc), 20)
    check(ok, "meeting request sent")
    rv = [e for e in store.events() if e["summary"] == "Review"]
    check(rv and "ORGANIZER" in rv[0]["ics"] and "ATTENDEE" in rv[0]["ics"], "the meeting in the calendar with its attendees")

    # internet calendar (Proton Calendar's share link) and a file
    cid = win.run("open-calendar-internet:http://127.0.0.1:%d/share/me@example.org/work.ics" % dport)
    check(cid and store.calendar(cid)["readonly"] and len(store.events(cid)) == 2, "internet calendar subscription")
    import tempfile
    p = os.path.join(tempfile.mkdtemp(), "trip.ics")
    open(p, "w").write(ical.dumps(ical.calendar_of([ical.new_event("Trip", dt.datetime(2026, 12, 1, tzinfo=L),
                                                                   dt.datetime(2026, 12, 4, tzinfo=L), all_day=True)])))
    n = win.run("open-calendar-file:" + p)
    check(n == 1 and any(e["summary"] == "Trip" for e in store.events()), "an .ics file imported")
    v.go(dt.date(2026, 12, 2))
    win.run("cal-view:week")
    trip = [i for i in v.instances if i.event.summary == "Trip"]
    check(trip and trip[0].all_day, "all-day event across days")
    shot(win, "week_allday")
    # new local calendar, rename, colour
    ANSWERS[:] = ["Family"]
    fam = win.run("new-calendar")
    check(fam and store.calendar(fam)["kind"] == "local", "New Calendar")
    for r in v.cal_list.get_children():
        if getattr(r, "cal_id", None) == fam:
            v.cal_list.select_row(r)
    win.run("calendar-color:#E74856")
    check(store.calendar(fam)["color"] == "#E74856", "calendar colour")
    # search
    win.search.set_text("Dentist")
    pump(0.3)
    check(v.selected is not None and v.selected.event.summary.startswith("Dentist"), "search finds an appointment")
    win.search.set_text("")
    # offline: changes wait
    win.run("work-offline")
    v.go(dt.date(2026, 11, 2))
    ew = eventwin.EventWindow(win, start=dt.datetime(2026, 11, 20, 9, tzinfo=L), end=dt.datetime(2026, 11, 20, 10, tzinfo=L), calendar=pid)
    ew.subject.set_text("Offline thing")
    ew.run("save-close")
    pump(1.5)
    check(not any("Offline thing" in d for _e, d in cals["personal"].items.values()), "offline: not sent yet")
    win.run("work-offline")
    ok = wait(lambda: any("Offline thing" in d for _e, d in cals["personal"].items.values()), 20)
    check(ok, "back online: sent")
    win.run("go:mail")
    dstop()
    mstop()
except Exception:
    traceback.print_exc()
    FAILS.append("exception")
print("UI FAILS: %d" % len(FAILS) if FAILS else "UI all passed")
sys.stdout.flush()
os._exit(1 if FAILS else 0)
