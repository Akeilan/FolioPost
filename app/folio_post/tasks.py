"""Tasks (iCalendar VTODO, kept on this computer) and Notes; the To-Do List also shows flagged mail."""
import datetime as dt
import uuid

from . import ical

STATUS = [("NEEDS-ACTION", "Not Started"), ("IN-PROCESS", "In Progress"), ("COMPLETED", "Completed"),
          ("X-WAITING", "Waiting on someone else"), ("X-DEFERRED", "Deferred")]
PRIORITY = [(9, "Low"), (5, "Normal"), (1, "High")]


class Task:
    def __init__(self, comp=None):
        self.comp = comp or ical.Component("VTODO")

    @property
    def uid(self):
        return self.comp.get("UID", "")

    @property
    def subject(self):
        return ical.unescape(self.comp.get("SUMMARY", ""))

    @property
    def notes(self):
        return ical.unescape(self.comp.get("DESCRIPTION", ""))

    def _date(self, name):
        p, v = self.comp.getp(name)
        if not v:
            return None
        return ical.parse_time(v, p)[0].date()

    @property
    def due(self):
        return self._date("DUE")

    @property
    def start(self):
        return self._date("DTSTART")

    @property
    def status(self):
        return self.comp.get("STATUS", "NEEDS-ACTION").upper()

    @property
    def done(self):
        return self.status == "COMPLETED"

    @property
    def percent(self):
        try:
            return int(self.comp.get("PERCENT-COMPLETE", "100" if self.done else "0"))
        except ValueError:
            return 0

    @property
    def priority(self):
        try:
            p = int(self.comp.get("PRIORITY", "5") or 5)
        except ValueError:
            p = 5
        return 1 if 1 <= p <= 4 else 9 if p >= 6 else 5

    @property
    def reminder(self):
        for a in self.comp.sub("VALARM"):
            p, v = a.getp("TRIGGER")
            if v and (p or {}).get("VALUE") == "DATE-TIME":
                return ical.parse_time(v, p)[0]
        return None

    @property
    def categories(self):
        v = self.comp.get("CATEGORIES", "")
        return [x for x in v.split(",") if x]

    def set_subject(self, s):
        self.comp.set("SUMMARY", ical.escape(s))

    def set_notes(self, s):
        self.comp.set("DESCRIPTION", ical.escape(s) if s else None)

    def set_date(self, name, d):
        self.comp.set(name, d.strftime("%Y%m%d") if d else None, {"VALUE": "DATE"} if d else None)

    def set_status(self, st):
        self.comp.set("STATUS", st)
        if st == "COMPLETED":
            self.comp.set("PERCENT-COMPLETE", "100")
            self.comp.set("COMPLETED", dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
        else:
            self.comp.set("COMPLETED", None)
            if self.percent == 100:
                self.comp.set("PERCENT-COMPLETE", "0")

    def set_percent(self, n):
        self.comp.set("PERCENT-COMPLETE", str(max(0, min(100, int(n)))))

    def set_priority(self, p):
        self.comp.set("PRIORITY", str(p))

    def set_reminder(self, when):
        self.comp.children = [c for c in self.comp.children if c.name != "VALARM"]
        if when is not None:
            a = ical.Component("VALARM")
            a.add("ACTION", "DISPLAY")
            a.add("DESCRIPTION", "Reminder")
            a.add("TRIGGER", when.astimezone(ical.UTC).strftime("%Y%m%dT%H%M%SZ"), {"VALUE": "DATE-TIME"})
            self.comp.children.append(a)

    def touch(self):
        self.comp.set("LAST-MODIFIED", dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
        self.comp.set("DTSTAMP", self.comp.get("LAST-MODIFIED"))

    def dumps(self):
        cal = ical.Component("VCALENDAR")
        cal.add("VERSION", "2.0")
        cal.add("PRODID", "-//Folio//Folio Post//EN")
        cal.children.append(self.comp)
        return ical.dumps(cal)


def new_task(subject, due=None):
    t = Task()
    t.comp.add("UID", "%s@folio-post" % uuid.uuid4())
    t.set_subject(subject)
    t.comp.add("STATUS", "NEEDS-ACTION")
    t.comp.add("PRIORITY", "5")
    if due:
        t.set_date("DUE", due)
    t.touch()
    return t


def parse(text):
    cal = ical.parse(text)
    if cal is None:
        return None
    todos = cal.sub("VTODO")
    return Task(todos[0]) if todos else None


def save(store, task, tid=None):
    d = task.due
    due = int(dt.datetime.combine(d, dt.time(0)).timestamp()) if d else 0
    return store.put_todo("task", task.uid, task.dumps(), task.subject, due, task.done, tid=tid)


def follow_up_date(how, today=None):
    today = today or dt.date.today()
    if how == "today":
        return today
    if how == "tomorrow":
        return today + dt.timedelta(days=1)
    if how == "this-week":
        return today + dt.timedelta(days=max(0, 4 - today.weekday()))
    if how == "next-week":
        return today + dt.timedelta(days=7 - today.weekday() + 4)
    return None
