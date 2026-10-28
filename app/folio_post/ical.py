"""iCalendar (RFC 5545) read and written by Post: events with their times and time zones,
recurrence (RRULE, RDATE, EXDATE, changed instances), alarms, attendees; and meeting requests
and replies (iTIP, RFC 5546)."""
import datetime as dt
import re
import uuid

try:
    from zoneinfo import ZoneInfo
except ImportError:            # pragma: no cover
    ZoneInfo = None

UTC = dt.timezone.utc
WEEKDAYS = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]
# Windows time zone names some servers (and Outlook) write
WINDOWS_TZ = {"W. Europe Standard Time": "Europe/Berlin", "Romance Standard Time": "Europe/Paris",
              "GMT Standard Time": "Europe/London", "Eastern Standard Time": "America/New_York",
              "Central Standard Time": "America/Chicago", "Mountain Standard Time": "America/Denver",
              "Pacific Standard Time": "America/Los_Angeles", "Central Europe Standard Time": "Europe/Budapest",
              "Tokyo Standard Time": "Asia/Tokyo", "China Standard Time": "Asia/Shanghai", "India Standard Time": "Asia/Kolkata",
              "AUS Eastern Standard Time": "Australia/Sydney", "UTC": "UTC"}


def local_tz():
    try:
        import os
        name = os.environ.get("TZ") or ""
        if not name:
            try:
                name = open("/etc/timezone").read().strip()
            except OSError:
                link = os.path.realpath("/etc/localtime")
                name = link.split("zoneinfo/", 1)[1] if "zoneinfo/" in link else ""
        if name and ZoneInfo is not None:
            return ZoneInfo(name)
    except Exception:
        pass
    return dt.datetime.now().astimezone().tzinfo


def tz(name):
    if not name:
        return None
    name = name.strip('"')
    name = WINDOWS_TZ.get(name, name)
    if ZoneInfo is None:
        return None
    try:
        return ZoneInfo(name)
    except Exception:
        m = re.search(r"([A-Za-z]+/[A-Za-z_]+(?:/[A-Za-z_]+)?)", name)
        if m:
            try:
                return ZoneInfo(m.group(1))
            except Exception:
                pass
    return None


# ---------------------------------------------------------------- lines
def unfold(text):
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return re.sub(r"\n[ \t]", "", text).split("\n")


def unescape(v):
    return re.sub(r"\\([\\;,nN])", lambda m: "\n" if m.group(1) in "nN" else m.group(1), v)


def escape(v):
    return (v or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def parse_line(line):
    """'DTSTART;TZID=Europe/Paris:20261028T090000' → ('DTSTART', {'TZID': 'Europe/Paris'}, '2026...')."""
    i, q = 0, False
    while i < len(line):
        c = line[i]
        if c == '"':
            q = not q
        elif c == ":" and not q:
            break
        i += 1
    head, value = line[:i], line[i + 1:]
    parts = re.findall(r'(?:[^;"]|"[^"]*")+', head)
    name = parts[0].upper() if parts else ""
    params = {}
    for p in parts[1:]:
        if "=" in p:
            k, v = p.split("=", 1)
            params[k.upper()] = v.strip('"')
    return name, params, value


class Component:
    def __init__(self, name):
        self.name = name
        self.props = []          # (name, params, value)
        self.children = []

    def get(self, name, default=None):
        for n, p, v in self.props:
            if n == name:
                return v
        return default

    def getp(self, name):
        for n, p, v in self.props:
            if n == name:
                return p, v
        return None, None

    def all(self, name):
        return [(p, v) for n, p, v in self.props if n == name]

    def set(self, name, value, params=None):
        self.props = [x for x in self.props if x[0] != name]
        if value is not None:
            self.props.append((name, params or {}, value))

    def add(self, name, value, params=None):
        self.props.append((name, params or {}, value))

    def sub(self, name):
        return [c for c in self.children if c.name == name]

    def dump(self, out):
        out.append("BEGIN:" + self.name)
        for n, p, v in self.props:
            head = n + "".join(";%s=%s" % (k, ('"%s"' % pv) if re.search(r"[:;,]", pv) else pv) for k, pv in p.items())
            out.append(fold(head + ":" + v))
        for c in self.children:
            c.dump(out)
        out.append("END:" + self.name)


def fold(line):
    b = line.encode("utf-8")
    if len(b) <= 75:
        return line
    out, cur = [], b""
    for ch in line:
        e = ch.encode("utf-8")
        if len(cur) + len(e) > (75 if not out else 74):
            out.append(cur.decode("utf-8"))
            cur = b""
        cur += e
    out.append(cur.decode("utf-8"))
    return "\r\n ".join(out)


def parse(text):
    """The VCALENDAR component (or None)."""
    if isinstance(text, bytes):
        text = text.decode("utf-8", "replace")
    stack = []
    root = None
    for line in unfold(text):
        if not line.strip():
            continue
        name, params, value = parse_line(line)
        if name == "BEGIN":
            c = Component(value.upper())
            if stack:
                stack[-1].children.append(c)
            else:
                root = c
            stack.append(c)
        elif name == "END":
            if stack:
                stack.pop()
        elif stack:
            stack[-1].props.append((name, params, value))
    return root


def dumps(cal):
    out = []
    cal.dump(out)
    return "\r\n".join(out) + "\r\n"


# ---------------------------------------------------------------- times
def parse_time(value, params=None, default_tz=None):
    """A DATE or DATE-TIME as (aware datetime, all_day)."""
    params = params or {}
    v = value.strip()
    if params.get("VALUE") == "DATE" or re.fullmatch(r"\d{8}", v):
        d = dt.datetime.strptime(v[:8], "%Y%m%d")
        return d.replace(tzinfo=default_tz or local_tz()), True
    if v.endswith("Z"):
        return dt.datetime.strptime(v[:15], "%Y%m%dT%H%M%S").replace(tzinfo=UTC), False
    d = dt.datetime.strptime(v[:15], "%Y%m%dT%H%M%S")
    z = tz(params.get("TZID")) or default_tz or local_tz()
    return d.replace(tzinfo=z), False


def fmt_time(d, all_day=False, utc=True):
    if all_day:
        return d.strftime("%Y%m%d"), {"VALUE": "DATE"}
    if utc:
        return d.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ"), {}
    name = getattr(d.tzinfo, "key", None)
    if name:
        return d.strftime("%Y%m%dT%H%M%S"), {"TZID": name}
    return d.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ"), {}


def parse_duration(v):
    m = re.fullmatch(r"([+-])?P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", v.strip())
    if not m:
        return dt.timedelta(0)
    sign = -1 if m.group(1) == "-" else 1
    w, d, h, mi, s = (int(x or 0) for x in m.groups()[1:])
    return sign * dt.timedelta(weeks=w, days=d, hours=h, minutes=mi, seconds=s)


def fmt_duration(td):
    secs = int(td.total_seconds())
    sign = "-" if secs < 0 else ""
    secs = abs(secs)
    d, rem = divmod(secs, 86400)
    h, rem = divmod(rem, 3600)
    m, s = divmod(rem, 60)
    out = sign + "P"
    if d:
        out += "%dD" % d
    if h or m or s or not d:
        out += "T" + ("%dH" % h if h else "") + ("%dM" % m if m else "") + ("%dS" % s if s else "")
        if out.endswith("T"):
            out += "0M"
    return out


# ---------------------------------------------------------------- recurrence
def parse_rrule(v):
    out = {}
    for part in v.split(";"):
        if "=" in part:
            k, val = part.split("=", 1)
            out[k.upper()] = val
    return out


def fmt_rrule(r):
    order = ["FREQ", "INTERVAL", "COUNT", "UNTIL", "BYDAY", "BYMONTHDAY", "BYMONTH", "BYSETPOS", "WKST"]
    return ";".join("%s=%s" % (k, r[k]) for k in order if k in r and r[k] not in (None, ""))


def _byday(spec):
    out = []
    for s in spec.split(","):
        m = re.fullmatch(r"([+-]?\d+)?(MO|TU|WE|TH|FR|SA|SU)", s.strip().upper())
        if m:
            out.append((int(m.group(1)) if m.group(1) else 0, WEEKDAYS.index(m.group(2))))
    return out


def _nth_weekdays(year, month, n, wd):
    first = dt.date(year, month, 1)
    days = []
    d = first + dt.timedelta(days=(wd - first.weekday()) % 7)
    while d.month == month:
        days.append(d)
        d += dt.timedelta(days=7)
    if n == 0:
        return days
    if n > 0:
        return days[n - 1:n] if n <= len(days) else []
    return days[n:n + 1 or None] if -n <= len(days) else []


def occurrences(start, rule, until_window, exdates=(), rdates=(), limit=5000):
    """Start times of a recurring event up to `until_window` (aware datetimes), in order."""
    r = parse_rrule(rule) if isinstance(rule, str) else dict(rule or {})
    freq = r.get("FREQ", "").upper()
    interval = max(1, int(r.get("INTERVAL", "1") or 1))
    count = int(r["COUNT"]) if r.get("COUNT") else None
    until = None
    if r.get("UNTIL"):
        until = parse_time(r["UNTIL"], default_tz=start.tzinfo)[0]
        if re.fullmatch(r"\d{8}", r["UNTIL"]):
            until = until + dt.timedelta(days=1) - dt.timedelta(seconds=1)
    byday = _byday(r["BYDAY"]) if r.get("BYDAY") else None
    bymd = [int(x) for x in r["BYMONTHDAY"].split(",")] if r.get("BYMONTHDAY") else None
    bymonth = [int(x) for x in r["BYMONTH"].split(",")] if r.get("BYMONTH") else None
    setpos = [int(x) for x in r["BYSETPOS"].split(",")] if r.get("BYSETPOS") else None
    ex = set(_key(e) for e in exdates)
    tzinfo = start.tzinfo
    naive = start.replace(tzinfo=None)
    t = naive.time()
    out = []
    n = 0

    def emit(d):
        nonlocal n
        when = dt.datetime.combine(d, t).replace(tzinfo=tzinfo) if isinstance(d, dt.date) and not isinstance(d, dt.datetime) else d
        if when < start:
            return True
        if until is not None and when > until:
            return False
        n += 1
        if count is not None and n > count:
            return False
        if when > until_window:
            return False
        if _key(when) not in ex:
            out.append(when)
        return len(out) < limit

    if not freq:
        out = [start] if start <= until_window else []
    elif freq == "DAILY":
        d = naive.date()
        while True:
            if (bymonth is None or d.month in bymonth) and (byday is None or d.weekday() in [w for _n, w in byday]):
                if not emit(d):
                    break
            d += dt.timedelta(days=interval)
            if dt.datetime.combine(d, t).replace(tzinfo=tzinfo) > until_window + dt.timedelta(days=1):
                break
    elif freq == "WEEKLY":
        days = sorted(w for _n, w in byday) if byday else [naive.weekday()]
        wkst = WEEKDAYS.index(r.get("WKST", "MO")) if r.get("WKST", "MO") in WEEKDAYS else 0
        week = naive.date() - dt.timedelta(days=(naive.weekday() - wkst) % 7)
        go = True
        while go:
            for wd in sorted(days, key=lambda w: (w - wkst) % 7):
                d = week + dt.timedelta(days=(wd - wkst) % 7)
                if bymonth is not None and d.month not in bymonth:
                    continue
                if not emit(d):
                    go = False
                    break
            week += dt.timedelta(weeks=interval)
            if dt.datetime.combine(week, t).replace(tzinfo=tzinfo) > until_window + dt.timedelta(days=7):
                break
    elif freq in ("MONTHLY", "YEARLY"):
        y, mo = naive.year, naive.month
        go = True
        while go:
            months = [mo] if freq == "MONTHLY" else (bymonth or [naive.month])
            for mm in months:
                if freq == "MONTHLY" and bymonth is not None and mm not in bymonth:
                    continue
                cands = []
                if byday:
                    for nth, wd in byday:
                        cands += _nth_weekdays(y, mm, nth, wd)
                if bymd:
                    import calendar
                    last = calendar.monthrange(y, mm)[1]
                    for md in bymd:
                        day = md if md > 0 else last + 1 + md
                        if 1 <= day <= last:
                            cands.append(dt.date(y, mm, day))
                if not byday and not bymd:
                    import calendar
                    if naive.day <= calendar.monthrange(y, mm)[1]:
                        cands.append(dt.date(y, mm, naive.day))
                cands = sorted(set(cands))
                if setpos:
                    cands = [cands[p - 1 if p > 0 else p] for p in setpos if -len(cands) <= p <= len(cands) and p != 0]
                for d in cands:
                    if not emit(d):
                        go = False
                        break
                if not go:
                    break
            if freq == "MONTHLY":
                mo += interval
                while mo > 12:
                    mo -= 12
                    y += 1
            else:
                y += interval
            if dt.datetime(y, mo, 1, tzinfo=tzinfo) > until_window + dt.timedelta(days=31) or y > 9000:
                break
    for rd in rdates:
        if start <= rd <= until_window and _key(rd) not in ex:
            out.append(rd)
    return sorted(set(out))


def _key(d):
    return d.astimezone(UTC).strftime("%Y%m%dT%H%M%S")


# ---------------------------------------------------------------- events
class Event:
    """One VEVENT, in Post's terms."""

    def __init__(self, comp=None):
        self.comp = comp or Component("VEVENT")

    @property
    def uid(self):
        return self.comp.get("UID", "")

    def _time(self, name):
        p, v = self.comp.getp(name)
        if v is None:
            return None, False
        return parse_time(v, p)

    @property
    def start(self):
        return self._time("DTSTART")[0]

    @property
    def all_day(self):
        return self._time("DTSTART")[1]

    @property
    def end(self):
        e, _ad = self._time("DTEND")
        if e is not None:
            return e
        d = self.comp.get("DURATION")
        s = self.start
        if s is None:
            return None
        if d:
            return s + parse_duration(d)
        return s + (dt.timedelta(days=1) if self.all_day else dt.timedelta(0))

    @property
    def summary(self):
        return unescape(self.comp.get("SUMMARY", ""))

    @property
    def location(self):
        return unescape(self.comp.get("LOCATION", ""))

    @property
    def description(self):
        return unescape(self.comp.get("DESCRIPTION", ""))

    @property
    def rrule(self):
        return self.comp.get("RRULE", "")

    @property
    def recurrence_id(self):
        p, v = self.comp.getp("RECURRENCE-ID")
        return parse_time(v, p)[0] if v else None

    @property
    def exdates(self):
        out = []
        for p, v in self.comp.all("EXDATE"):
            for x in v.split(","):
                if x.strip():
                    out.append(parse_time(x, p)[0])
        return out

    @property
    def rdates(self):
        out = []
        for p, v in self.comp.all("RDATE"):
            if (p or {}).get("VALUE") == "PERIOD":
                continue
            for x in v.split(","):
                if x.strip():
                    out.append(parse_time(x, p)[0])
        return out

    @property
    def busy(self):
        t = self.comp.get("TRANSP", "OPAQUE").upper()
        return {"FREE": "free", "TENTATIVE": "tentative", "OOF": "oof"}.get(
            self.comp.get("X-MICROSOFT-CDO-BUSYSTATUS", "").upper(), "free" if t == "TRANSPARENT" else "busy")

    @property
    def status(self):
        return self.comp.get("STATUS", "CONFIRMED").upper()

    @property
    def organizer(self):
        p, v = self.comp.getp("ORGANIZER")
        if v is None:
            return None
        return (p.get("CN", ""), re.sub(r"(?i)^mailto:", "", v))

    @property
    def attendees(self):
        out = []
        for p, v in self.comp.all("ATTENDEE"):
            out.append({"name": p.get("CN", ""), "email": re.sub(r"(?i)^mailto:", "", v),
                        "status": p.get("PARTSTAT", "NEEDS-ACTION"), "role": p.get("ROLE", "REQ-PARTICIPANT")})
        return out

    @property
    def reminder(self):
        """Minutes before the start of the first display/audio alarm, or None."""
        for a in self.comp.sub("VALARM"):
            p, v = a.getp("TRIGGER")
            if v is None:
                continue
            if (p or {}).get("VALUE") == "DATE-TIME":
                s = self.start
                return max(0, int((s - parse_time(v, p)[0]).total_seconds() // 60)) if s else None
            return max(0, int(-parse_duration(v).total_seconds() // 60))
        return None

    @property
    def categories(self):
        v = self.comp.get("CATEGORIES", "")
        return [unescape(x) for x in re.split(r"(?<!\\),", v) if x]

    @property
    def sequence(self):
        try:
            return int(self.comp.get("SEQUENCE", "0"))
        except ValueError:
            return 0

    # ---- writing
    def set_times(self, start, end, all_day=False):
        v, p = fmt_time(start, all_day, utc=False)
        self.comp.set("DTSTART", v, p)
        v, p = fmt_time(end, all_day, utc=False)
        self.comp.set("DTEND", v, p)
        self.comp.set("DURATION", None)

    def set_text(self, name, value):
        self.comp.set(name, escape(value) if value else None)

    def set_reminder(self, minutes):
        self.comp.children = [c for c in self.comp.children if c.name != "VALARM"]
        if minutes is not None:
            a = Component("VALARM")
            a.add("ACTION", "DISPLAY")
            a.add("DESCRIPTION", "Reminder")
            a.add("TRIGGER", "-" + fmt_duration(dt.timedelta(minutes=minutes)))
            self.comp.children.append(a)

    def set_busy(self, how):
        self.comp.set("TRANSP", "TRANSPARENT" if how == "free" else "OPAQUE")
        self.comp.set("X-MICROSOFT-CDO-BUSYSTATUS", {"free": "FREE", "tentative": "TENTATIVE", "oof": "OOF"}.get(how, "BUSY"))

    def set_attendees(self, people, organizer=None):
        self.comp.props = [x for x in self.comp.props if x[0] not in ("ATTENDEE", "ORGANIZER")]
        if organizer:
            self.comp.add("ORGANIZER", "mailto:" + organizer[1], {"CN": organizer[0]} if organizer[0] else {})
        for a in people:
            p = {"ROLE": a.get("role", "REQ-PARTICIPANT"), "PARTSTAT": a.get("status", "NEEDS-ACTION"), "RSVP": "TRUE"}
            if a.get("name"):
                p["CN"] = a["name"]
            self.comp.add("ATTENDEE", "mailto:" + a["email"], p)

    def touch(self):
        now = dt.datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        self.comp.set("DTSTAMP", now)
        self.comp.set("LAST-MODIFIED", now)


def new_event(summary, start, end, all_day=False, location="", description="", rrule="", reminder=15):
    e = Event()
    e.comp.add("UID", "%s@folio-post" % uuid.uuid4())
    e.touch()
    e.comp.add("CREATED", e.comp.get("DTSTAMP"))
    e.set_text("SUMMARY", summary)
    e.set_times(start, end, all_day)
    if location:
        e.set_text("LOCATION", location)
    if description:
        e.set_text("DESCRIPTION", description)
    if rrule:
        e.comp.add("RRULE", rrule)
    e.comp.add("SEQUENCE", "0")
    e.set_reminder(reminder)
    return e


def calendar_of(events, method=None):
    cal = Component("VCALENDAR")
    cal.add("VERSION", "2.0")
    cal.add("PRODID", "-//Folio//Folio Post//EN")
    if method:
        cal.add("METHOD", method)
    used = set()
    for e in events:
        for n in ("DTSTART", "DTEND", "RECURRENCE-ID"):
            p, _v = e.comp.getp(n)
            if p and p.get("TZID"):
                used.add(p["TZID"])
    for name in sorted(used):
        cal.children.append(vtimezone(name))
    for e in events:
        cal.children.append(e.comp)
    return cal


def vtimezone(name):
    """A VTIMEZONE for an IANA zone: its standard and daylight rules for this year (enough for other apps)."""
    c = Component("VTIMEZONE")
    c.add("TZID", name)
    z = tz(name)
    if z is None:
        return c
    year = dt.datetime.now().year
    jan = dt.datetime(year, 1, 1, tzinfo=z)
    offs = []
    prev = jan.utcoffset()
    d = jan
    while d.year == year:
        n = d + dt.timedelta(hours=1)
        if n.utcoffset() != prev:
            offs.append((n.replace(minute=0, second=0), prev, n.utcoffset()))
            prev = n.utcoffset()
        d = n
        if len(offs) >= 2:
            break

    def off(td):
        s = int(td.total_seconds())
        return "%s%02d%02d" % ("+" if s >= 0 else "-", abs(s) // 3600, abs(s) % 3600 // 60)
    if not offs:
        s = Component("STANDARD")
        s.add("DTSTART", "19700101T000000")
        s.add("TZOFFSETFROM", off(jan.utcoffset()))
        s.add("TZOFFSETTO", off(jan.utcoffset()))
        c.children.append(s)
        return c
    for when, a, b in offs:
        kind = "DAYLIGHT" if b > a else "STANDARD"
        s = Component(kind)
        local = when.replace(tzinfo=None) - (b - a) if b > a else when.replace(tzinfo=None) + (a - b)
        s.add("DTSTART", local.strftime("%Y%m%dT%H%M%S"))
        nth = (local.day - 1) // 7 + 1
        last = (local + dt.timedelta(days=7)).month != local.month
        s.add("RRULE", "FREQ=YEARLY;BYMONTH=%d;BYDAY=%s%s" % (local.month, "-1" if last else str(nth), WEEKDAYS[local.weekday()]))
        s.add("TZOFFSETFROM", off(a))
        s.add("TZOFFSETTO", off(b))
        c.children.append(s)
    return c


def events_of(cal):
    return [Event(c) for c in (cal.sub("VEVENT") if cal is not None else [])]


def expand(events, window_start, window_end):
    """Instances in a window: [(event, start, end)] — recurring events expanded, changed instances in place."""
    masters = {}
    overrides = {}
    out = []
    for e in events:
        if e.recurrence_id is not None:
            overrides.setdefault(e.uid, {})[_key(e.recurrence_id)] = e
        else:
            masters.setdefault(e.uid, e)
    for uid, e in masters.items():
        s = e.start
        if s is None or e.status == "CANCELLED":
            continue
        en = e.end or s
        length = en - s
        ov = overrides.get(uid, {})
        if e.rrule or e.rdates:
            starts = occurrences(s, e.rrule, window_end, e.exdates, e.rdates)
        else:
            starts = [s]
        for st in starts:
            k = _key(st)
            if k in ov:
                o = ov.pop(k)
                if o.status == "CANCELLED":
                    continue
                os_, oe = o.start, o.end or o.start
                if oe > window_start and os_ < window_end:
                    out.append((o, os_, oe))
                continue
            if st + length > window_start and st < window_end:
                out.append((e, st, st + length))
        for o in ov.values():
            if o.start and (o.end or o.start) > window_start and o.start < window_end and o.status != "CANCELLED":
                out.append((o, o.start, o.end or o.start))
    for uid, ov in overrides.items():
        if uid not in masters:
            for o in ov.values():
                if o.start and (o.end or o.start) > window_start and o.start < window_end:
                    out.append((o, o.start, o.end or o.start))
    out.sort(key=lambda x: (x[1], -(x[2] - x[1]).total_seconds()))
    return out


def describe_rrule(rule, start):
    """'Every 2 weeks on Monday, Wednesday', as the Recurrence box says it."""
    r = parse_rrule(rule)
    f = r.get("FREQ", "")
    n = int(r.get("INTERVAL", "1") or 1)
    names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    if f == "DAILY":
        s = "Every day" if n == 1 else "Every %d days" % n
        if r.get("BYDAY") == "MO,TU,WE,TH,FR":
            s = "Every weekday"
    elif f == "WEEKLY":
        days = [names[w] for _x, w in _byday(r.get("BYDAY", ""))] or [names[start.weekday()]]
        s = ("Every week" if n == 1 else "Every %d weeks" % n) + " on " + ", ".join(days)
    elif f == "MONTHLY":
        s = ("Every month" if n == 1 else "Every %d months" % n)
        if r.get("BYDAY"):
            nth, w = _byday(r["BYDAY"])[0]
            s += " on the %s %s" % ({1: "first", 2: "second", 3: "third", 4: "fourth", -1: "last"}.get(nth or int(r.get("BYSETPOS", "1")), str(nth)), names[w])
        else:
            s += " on day %s" % r.get("BYMONTHDAY", start.day)
    elif f == "YEARLY":
        s = "Every year" if n == 1 else "Every %d years" % n
        s += " on %s" % start.strftime("%B %d")
    else:
        return ""
    if r.get("COUNT"):
        s += ", %s times" % r["COUNT"]
    elif r.get("UNTIL"):
        s += ", until %s" % parse_time(r["UNTIL"])[0].strftime("%d/%m/%Y")
    return s


# ---------------------------------------------------------------- meetings (iTIP)
def invitation(event, method="REQUEST"):
    return dumps(calendar_of([event], method))


def reply_to(event, me, partstat):
    """The REPLY to a meeting request: our attendee line with our answer."""
    r = Event(Component("VEVENT"))
    for n in ("UID", "DTSTART", "DTEND", "DURATION", "RECURRENCE-ID", "SEQUENCE", "SUMMARY", "ORGANIZER"):
        p, v = event.comp.getp(n)
        if v is not None:
            r.comp.add(n, v, dict(p))
    r.touch()
    name = ""
    for a in event.attendees:
        if a["email"].lower() == me.lower():
            name = a["name"]
    r.comp.add("ATTENDEE", "mailto:" + me, dict({"PARTSTAT": partstat}, **({"CN": name} if name else {})))
    return dumps(calendar_of([r], "REPLY"))
