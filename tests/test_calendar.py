"""Calendar engine tests: iCalendar, recurrence, CalDAV two-way sync, internet calendars."""
import datetime as dt
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "app"))
sys.path.insert(0, HERE)
from folio_post import caldav, ical  # noqa: E402
from folio_post import store as S  # noqa: E402
from folio_post import sync  # noqa: E402
import davserver  # noqa: E402

FAILS = []


def check(cond, what):
    print(("ok   " if cond else "FAIL ") + what)
    if not cond:
        FAILS.append(what)


AMS = ical.tz("Europe/Amsterdam")


def d(y, m, day, h=0, mi=0):
    return dt.datetime(y, m, day, h, mi, tzinfo=AMS)


# ---------------------------------------------------------------- iCalendar
text = davserver.event("a1", "Stand-up, daily", "20261026T093000", "20261026T094500", "FREQ=WEEKLY;BYDAY=MO,WE,FR;COUNT=6",
                       extra="DESCRIPTION:Line one\\nLine two\r\nBEGIN:VALARM\r\nACTION:DISPLAY\r\nTRIGGER:-PT10M\r\nEND:VALARM\r\n")
cal = ical.parse(text)
e = ical.events_of(cal)[0]
check(e.summary == "Stand-up, daily" and e.description == "Line one\nLine two", "text values unescaped")
check(e.start == d(2026, 10, 26, 9, 30) and e.end - e.start == dt.timedelta(minutes=15), "times with their time zone")
check(e.reminder == 10, "reminder 10 minutes before")
occ = ical.occurrences(e.start, e.rrule, d(2027, 1, 1))
check([o.strftime("%a %d") for o in occ] == ["Mon 26", "Wed 28", "Fri 30", "Mon 02", "Wed 04", "Fri 06"], "weekly on three days, 6 times")
check(occ[3].utcoffset() == dt.timedelta(hours=1) and occ[0].utcoffset() == dt.timedelta(hours=1), "wall-clock time kept across DST")
st = d(2026, 3, 27, 9)
occ = ical.occurrences(st, "FREQ=DAILY;COUNT=3", d(2027, 1, 1))
check([o.utcoffset().seconds // 3600 for o in occ] == [1, 1, 2] and all(o.hour == 9 for o in occ), "daily across the spring change stays at 9:00")
occ = ical.occurrences(d(2026, 1, 13, 10), "FREQ=MONTHLY;BYDAY=2TU", d(2026, 6, 1))
check([o.day for o in occ] == [13, 10, 10, 14, 12], "second Tuesday of each month: %s" % [o.day for o in occ])
occ = ical.occurrences(d(2026, 1, 30, 10), "FREQ=MONTHLY;BYDAY=-1FR", d(2026, 4, 1))
check([o.day for o in occ] == [30, 27, 27], "last Friday")
occ = ical.occurrences(d(2026, 1, 31, 10), "FREQ=MONTHLY", d(2026, 6, 1))
check([o.month for o in occ] == [1, 3, 5], "the 31st skips short months")
occ = ical.occurrences(d(2024, 2, 29), "FREQ=YEARLY;UNTIL=20330101", d(2034, 1, 1))
check([o.year for o in occ] == [2024, 2028, 2032], "29 February only in leap years")
occ = ical.occurrences(d(2026, 1, 5, 8), "FREQ=WEEKLY;INTERVAL=2;UNTIL=20260216T235959Z", d(2027, 1, 1), exdates=[d(2026, 1, 19, 8)])
check([o.day for o in occ] == [5, 2, 16], "every 2 weeks, until, with an exception: %s" % [(o.month, o.day) for o in occ])
occ = ical.occurrences(d(2026, 1, 1), "FREQ=MONTHLY;BYDAY=MO,TU,WE,TH,FR;BYSETPOS=-1", d(2026, 4, 1))
check([o.day for o in occ] == [30, 27, 31], "last weekday of the month (BYSETPOS)")
# changed and cancelled instances
ov = ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:r1\r\nDTSTART;TZID=Europe/Amsterdam:20261102T100000\r\n"
      "DTEND;TZID=Europe/Amsterdam:20261102T110000\r\nRRULE:FREQ=DAILY;COUNT=5\r\nSUMMARY:Series\r\nEXDATE;TZID=Europe/Amsterdam:20261104T100000\r\n"
      "END:VEVENT\r\nBEGIN:VEVENT\r\nUID:r1\r\nRECURRENCE-ID;TZID=Europe/Amsterdam:20261103T100000\r\nDTSTART;TZID=Europe/Amsterdam:20261103T150000\r\n"
      "DTEND;TZID=Europe/Amsterdam:20261103T160000\r\nSUMMARY:Moved one\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")
inst = ical.expand(ical.events_of(ical.parse(ov)), d(2026, 11, 1), d(2026, 11, 30))
check([(x[1].day, x[1].hour, x[0].summary) for x in inst] == [(2, 10, "Series"), (3, 15, "Moved one"), (5, 10, "Series"), (6, 10, "Series")],
      "expand: exception skipped, changed instance moved: %s" % [(x[1].day, x[1].hour) for x in inst])
# all-day
ad = ical.parse("BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:x\r\nDTSTART;VALUE=DATE:20261224\r\nDTEND;VALUE=DATE:20261227\r\nSUMMARY:Holiday\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")
ev = ical.events_of(ad)[0]
check(ev.all_day and (ev.end - ev.start).days == 3, "all-day, three days")
# writing
n = ical.new_event("Lunch; with Ann", d(2026, 11, 5, 12), d(2026, 11, 5, 13), location="Café", rrule="FREQ=WEEKLY", reminder=15)
out = ical.dumps(ical.calendar_of([n]))
back = ical.events_of(ical.parse(out))[0]
check(back.summary == "Lunch; with Ann" and back.location == "Café" and back.start == d(2026, 11, 5, 12), "written and read back")
check("BEGIN:VTIMEZONE" in out and "TZID:Europe/Amsterdam" in out, "a VTIMEZONE is written for the zone")
check(back.reminder == 15 and back.rrule == "FREQ=WEEKLY", "reminder and recurrence written")
long = ical.new_event("x" * 200, d(2026, 1, 1), d(2026, 1, 1, 1))
check(all(len(line.encode()) <= 75 for line in ical.dumps(ical.calendar_of([long])).split("\r\n")), "long lines folded")
check(ical.events_of(ical.parse(ical.dumps(ical.calendar_of([long]))))[0].summary == "x" * 200, "folded lines unfold")
check(ical.describe_rrule("FREQ=WEEKLY;INTERVAL=2;BYDAY=MO,WE", d(2026, 1, 5)) == "Every 2 weeks on Monday, Wednesday", "recurrence described")
# meetings
n.set_attendees([{"email": "bob@example.org", "name": "Bob"}], ("Me", "me@example.org"))
req = ical.invitation(n)
check("METHOD:REQUEST" in req and "ATTENDEE;" in req and "ORGANIZER" in req, "meeting request")
rep = ical.reply_to(ical.events_of(ical.parse(req))[0], "bob@example.org", "ACCEPTED")
check("METHOD:REPLY" in rep and "PARTSTAT=ACCEPTED" in rep, "meeting reply")
check(ical.tz("W. Europe Standard Time") is not None, "Windows time zone names")

# ---------------------------------------------------------------- CalDAV
world = davserver.World()
cals = world.add_user("me@example.org", "secret", ("personal", "work"))
cals["personal"].put("e1.ics", davserver.event("e1", "Dentist", "20261105T090000", "20261105T100000"))
cals["personal"].put("e2.ics", davserver.event("e2", "Yoga", "20261102T180000", "20261102T190000", "FREQ=WEEKLY"))
_w, port, stop = davserver.start(world)
root = tempfile.mkdtemp()
st = S.Store(root)
sec = sync.Secrets(os.path.join(root, "secrets.json"))
cs = caldav.CalendarSync(st, sec, None)
url = "http://127.0.0.1:%d/" % port
c = caldav.Client(url, "me@example.org", "secret")
found = c.calendars()
check(sorted(x["name"] for x in found) == ["Personal", "Work"], "discovery finds both calendars: %s" % found)
try:
    caldav.Client(url, "me@example.org", "bad").calendars()
    check(False, "a wrong password is refused")
except caldav.DavError as ex:
    check(ex.status == 401, "a wrong password is refused")
ids = cs.add_caldav(url, "me@example.org", "secret")
check(len(ids) == 2, "two calendars added")
pid = [i for i in ids if st.calendar(i)["name"] == "Personal"][0]
check(cs.sync(pid), "first sync")
evs = st.events(pid)
check(sorted(e["summary"] for e in evs) == ["Dentist", "Yoga"], "events brought down")
# new here → server
ne = ical.new_event("Haircut", d(2026, 11, 6, 15), d(2026, 11, 6, 16))
eid = caldav.save_event(st, pid, [ne.comp])
check(st.event(eid)["pending"] == "new", "new event waits for the sync")
cs.sync(pid)
check(any("Haircut" in data for _et, data in cals["personal"].items.values()), "new event on the server")
check(st.event(eid)["pending"] == "" and st.event(eid)["etag"], "with its etag")
# changed here → server
e1 = [e for e in st.events(pid) if e["summary"] == "Dentist"][0]
ev = ical.events_of(ical.parse(e1["ics"]))[0]
ev.set_text("SUMMARY", "Dentist (moved)")
ev.set_times(d(2026, 11, 5, 11), d(2026, 11, 5, 12))
caldav.save_event(st, pid, [ev.comp], e1["id"])
cs.sync(pid)
check("Dentist (moved)" in cals["personal"].items["e1.ics"][1], "change sent to the server")
# changed on the server → here
cals["personal"].put("e2.ics", davserver.event("e2", "Yoga (new room)", "20261102T180000", "20261102T190000", "FREQ=WEEKLY"))
cals["personal"].put("e3.ics", davserver.event("e3", "Concert", "20261120T200000", "20261120T230000"))
cs.sync(pid)
names = sorted(e["summary"] for e in st.events(pid))
check(names == ["Concert", "Dentist (moved)", "Haircut", "Yoga (new room)"], "server changes come down: %s" % names)
# deleted on the server → gone here; deleted here → gone there
del cals["personal"].items["e3.ics"]
cals["personal"].ctag += 1
cs.sync(pid)
check("Concert" not in [e["summary"] for e in st.events(pid)], "deleted on the server")
h = [e for e in st.events(pid) if e["summary"] == "Haircut"][0]
caldav.delete_event(st, h["id"])
check("Haircut" not in [e["summary"] for e in st.events(pid)], "deleted here at once")
cs.sync(pid)
check(not any("Haircut" in data for _et, data in cals["personal"].items.values()), "and on the server")
# both changed: the server's version wins
y = [e for e in st.events(pid) if e["summary"].startswith("Yoga")][0]
ev = ical.events_of(ical.parse(y["ics"]))[0]
ev.set_text("SUMMARY", "Yoga (mine)")
caldav.save_event(st, pid, [ev.comp], y["id"])
cals["personal"].put("e2.ics", davserver.event("e2", "Yoga (theirs)", "20261102T180000", "20261102T190000", "FREQ=WEEKLY"))
cs.sync(pid)
check([e["summary"] for e in st.events(pid) if e["summary"].startswith("Yoga")] == ["Yoga (theirs)"], "conflict: the server wins")
# internet calendar (as Proton shares one)
cals["work"].put("w1.ics", davserver.event("w1", "Board meeting", "20261110T140000", "20261110T160000"))
ics_id = cs.add_ics("http://127.0.0.1:%d/share/me@example.org/work.ics" % port)
check(st.calendar(ics_id)["readonly"] and [e["summary"] for e in st.events(ics_id)] == ["Board meeting"], "internet calendar, read-only")
cals["work"].put("w2.ics", davserver.event("w2", "Offsite", "20261111T090000", "20261111T170000"))
cs.sync(ics_id)
check(sorted(e["summary"] for e in st.events(ics_id)) == ["Board meeting", "Offsite"], "internet calendar refreshes")
# Bearer sign-in (Google uses OAuth tokens)
cb = caldav.Client(url, "me@example.org", token=lambda: "test-token")
check(len(cb.calendars()) == 2, "OAuth bearer sign-in")
stop()
print("FAILED: %d" % len(FAILS) if FAILS else "all passed")
sys.exit(1 if FAILS else 0)
