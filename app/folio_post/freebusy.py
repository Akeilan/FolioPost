"""Free/busy for the Scheduling Assistant (M3-03) and other people's calendars (M3-04): Google
Calendar's freeBusy query, CalDAV scheduling (RFC 6638: a VFREEBUSY request to the schedule
outbox), Exchange's GetUserAvailability, and this computer's own calendars. Delegation on
CalDAV servers is CalendarServer's calendar-proxy (Nextcloud, iCloud, Fastmail and others)."""
import datetime as dt
import json
import re
import urllib.parse
import urllib.request
import uuid
import xml.etree.ElementTree as ET

from . import ical
from .caldav import NS, Client, DavError, GOOGLE_CALDAV

UTC = dt.timezone.utc
GOOGLE_FREEBUSY = "https://www.googleapis.com/calendar/v3/freeBusy"


def _z(d):
    return d.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


# ---------------------------------------------------------------- CalDAV
def caldav_outbox(c):
    pr = c.principal()
    if pr is None:
        return None
    for _h, p in c.propfind(pr, ["c:schedule-outbox-URL"]):
        e = p.get("{urn:ietf:params:xml:ns:caldav}schedule-outbox-URL")
        if e is not None:
            h = e.findtext("d:href", "", NS)
            if h:
                return h
    return None


def caldav_freebusy(c, organizer, emails, start, end):
    """{email: [(start, end, status)] or None} from the CalDAV server's scheduling."""
    out = c and caldav_outbox(c)
    if not out:
        return {e: None for e in emails}
    body = ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Folio//Folio Post//EN\r\nMETHOD:REQUEST\r\nBEGIN:VFREEBUSY\r\n"
            "UID:%s\r\nDTSTAMP:%s\r\nDTSTART:%s\r\nDTEND:%s\r\nORGANIZER:mailto:%s\r\n%sEND:VFREEBUSY\r\nEND:VCALENDAR\r\n"
            % (uuid.uuid4(), _z(dt.datetime.now(UTC)), _z(start), _z(end), organizer,
               "".join("ATTENDEE:mailto:%s\r\n" % e for e in emails)))
    st, _h, data = c.request("POST", out, body, {"Content-Type": "text/calendar; charset=utf-8",
                                                 "Originator": "mailto:" + organizer,
                                                 "Recipient": ", ".join("mailto:" + e for e in emails)})
    if st >= 400:
        raise DavError(st)
    res = {e: None for e in emails}
    root = ET.fromstring(data)
    for r in root.iter("{urn:ietf:params:xml:ns:caldav}response"):
        who = re.sub(r"(?i)^mailto:", "", (r.findtext("c:recipient/d:href", "", NS) or r.findtext("c:recipient", "", NS)).strip())
        stat = r.findtext("c:request-status", "", NS)
        if not stat.startswith("2"):
            continue
        cal = ical.parse(r.findtext("c:calendar-data", "", NS))
        slots = []
        for fb in (cal.sub("VFREEBUSY") if cal else []):
            for p, v in fb.all("FREEBUSY"):
                kind = {"BUSY-TENTATIVE": "tentative", "BUSY-UNAVAILABLE": "oof", "FREE": "free"}.get((p or {}).get("FBTYPE", "BUSY"), "busy")
                for per in v.split(","):
                    a, _, b = per.partition("/")
                    s = ical.parse_time(a)[0]
                    e = s + ical.parse_duration(b) if b.startswith(("P", "-P")) else ical.parse_time(b)[0]
                    slots.append((s, e, kind))
        for k in res:
            if k.lower() == who.lower():
                res[k] = slots
    return res


def caldav_delegations(c):
    """[(principal href, "read" | "write")]: the people who made this account their delegate."""
    pr = c.principal()
    if pr is None:
        return []
    out = []
    for _h, p in c.propfind(pr, ["cs:calendar-proxy-read-for", "cs:calendar-proxy-write-for"]):
        for tag, mode in (("calendar-proxy-read-for", "read"), ("calendar-proxy-write-for", "write")):
            e = p.get("{http://calendarserver.org/ns/}" + tag)
            if e is not None:
                out += [(h.text, mode) for h in e.findall("d:href", NS) if h.text]
    return out


def caldav_principal_calendars(c, principal):
    """The calendars under another person's principal (when they let this account see them)."""
    home = None
    name = ""
    for _h, p in c.propfind(principal, ["c:calendar-home-set", "d:displayname"]):
        e = p.get("{urn:ietf:params:xml:ns:caldav}calendar-home-set")
        if e is not None:
            home = e.findtext("d:href", "", NS)
        dn = p.get("{DAV:}displayname")
        if dn is not None and dn.text:
            name = dn.text
    if not home:
        return name, []
    sub = Client(c.url(home), c.user, c.password, c.token)
    sub.principal = lambda: None
    sub.home = lambda: home
    return name, sub.calendars()


def caldav_find_principal(c, email):
    """The principal of an e-mail address (RFC 3744 principal-property-search), or None."""
    body = ('<?xml version="1.0"?><d:principal-property-search xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
            '<d:property-search><d:prop><c:calendar-user-address-set/></d:prop><d:match>mailto:%s</d:match>'
            '</d:property-search><d:prop><d:displayname/></d:prop></d:principal-property-search>' % email)
    pr = c.principal()
    base = pr.rstrip("/").rsplit("/", 1)[0] + "/" if pr else "/principals/"
    try:
        root = c.xml("REPORT", base, body, "0")
    except DavError:
        return None
    for r in (root.findall("d:response", NS) if root is not None else []):
        return r.findtext("d:href", "", NS)
    return None


def caldav_set_delegate(c, principal, mode):
    """Let another principal read ("read"), change ("write") or no longer see ("none") this account's calendars."""
    pr = c.principal()
    groups = {}
    for mode_ in ("read", "write"):
        g = pr.rstrip("/") + "/calendar-proxy-%s/" % mode_
        cur = []
        try:
            for _h, p in c.propfind(g, ["d:group-member-set"]):
                e = p.get("{DAV:}group-member-set")
                if e is not None:
                    cur = [h.text for h in e.findall("d:href", NS) if h.text]
        except DavError:
            cur = []
        cur = [h for h in cur if h.rstrip("/") != principal.rstrip("/")]
        if mode_ == mode:
            cur.append(principal)
        groups[mode_] = (g, cur)
    for g, members in groups.values():
        body = ('<?xml version="1.0"?><d:propertyupdate xmlns:d="DAV:"><d:set><d:prop><d:group-member-set>%s'
                '</d:group-member-set></d:prop></d:set></d:propertyupdate>' % "".join("<d:href>%s</d:href>" % h for h in members))
        c.xml("PROPPATCH", g, body)


def caldav_delegates(c):
    """[(principal href, mode)] of the people this account has made delegates."""
    pr = c.principal()
    out = []
    for mode in ("read", "write"):
        try:
            for _h, p in c.propfind(pr.rstrip("/") + "/calendar-proxy-%s/" % mode, ["d:group-member-set"]):
                e = p.get("{DAV:}group-member-set")
                if e is not None:
                    out += [(h.text, mode) for h in e.findall("d:href", NS) if h.text]
        except DavError:
            pass
    return out


# ---------------------------------------------------------------- Google
def google_freebusy(token, emails, start, end, url=None):
    body = {"timeMin": start.astimezone(UTC).isoformat().replace("+00:00", "Z"),
            "timeMax": end.astimezone(UTC).isoformat().replace("+00:00", "Z"), "items": [{"id": e} for e in emails]}
    r = urllib.request.Request(url or GOOGLE_FREEBUSY, data=json.dumps(body).encode(), method="POST",
                               headers={"Authorization": "Bearer " + (token() if callable(token) else token),
                                        "Content-Type": "application/json"})
    with urllib.request.urlopen(r, timeout=30) as resp:
        d = json.loads(resp.read().decode())
    out = {}
    for e in emails:
        c = d.get("calendars", {}).get(e)
        if c is None or c.get("errors"):
            out[e] = None
            continue
        out[e] = [(dt.datetime.fromisoformat(b["start"].replace("Z", "+00:00")), dt.datetime.fromisoformat(b["end"].replace("Z", "+00:00")),
                   "busy") for b in c.get("busy", [])]
    return out


def google_shared_url(email):
    return GOOGLE_CALDAV + urllib.parse.quote(email) + "/events/"


# ---------------------------------------------------------------- this computer
def local_busy(store, start, end):
    """Busy times in the calendars here (for the organizer's own row)."""
    out = []
    groups = {}
    for row in store.events():
        cal = store.calendar(row["calendar"])
        if cal is None or not cal["shown"]:
            continue
        acc = cal["account"]
        if acc and store.get("ews-cal:%d" % cal["id"], {}).get("mailbox"):
            continue                                # someone else's calendar
        if row["start"] and row["start"] > end.timestamp():
            continue
        if row["until"] and row["until"] < start.timestamp():
            continue
        groups.setdefault(row["id"], row)
    for row in groups.values():
        cal = ical.parse(row["ics"])
        if cal is None:
            continue
        for inst in ical.expand(ical.events_of(cal), start, end):
            ev = inst.event if hasattr(inst, "event") else inst[0]
            s, e = (inst.start, inst.end) if hasattr(inst, "start") else (inst[1], inst[2])
            if ev.busy == "free":
                continue
            if isinstance(s, dt.date) and not isinstance(s, dt.datetime):
                lt = ical.local_tz() or UTC
                s, e = dt.datetime(s.year, s.month, s.day, tzinfo=lt), dt.datetime(e.year, e.month, e.day, tzinfo=lt)
            out.append((s, e, ev.busy))
    return out


def lookup(app, acc, emails, start, end):
    """{email: slots or None} through the organizer's account, the way its server offers."""
    emails = [e for e in emails if e]
    if not emails:
        return {}
    res = {e: None for e in emails}
    if acc is None:
        return res
    cfg = acc["config"]
    try:
        if acc["kind"] == "ews":
            from . import ews
            c = ews.client_for(acc, app.secrets, app.tokens)
            try:
                res.update(c.availability(emails, start, end))
            finally:
                c.close()
        elif cfg.get("imap_host") == "imap.gmail.com" and cfg.get("auth") in ("oauth", "goa"):
            res.update(google_freebusy(lambda: app.tokens(acc), emails, start, end, app.store.get("google-freebusy-url") or None))
        else:
            cals = [c for c in app.store.calendars() if c["kind"] == "caldav" and (c["account"] == acc["id"] or not c["account"])]
            if cals:
                cl = app.calsync.client_for(cals[0])
                res.update(caldav_freebusy(cl, acc["email"], emails, start, end))
    except Exception as e:  # noqa: F841  (no free/busy: the rows say "No information")
        import traceback
        traceback.print_exc()
    me = acc["email"].lower()
    for e in emails:
        if e.lower() == me:
            res[e] = local_busy(app.store, start, end)
    return res


def next_free(busy_rows, start, length, day_start=8, day_end=18, step=30, days=14):
    """The first time from start, inside working hours, when everyone is free for length."""
    t = start
    end_search = start + dt.timedelta(days=days)
    while t < end_search:
        lt = t.astimezone()
        if lt.hour < day_start:
            t = lt.replace(hour=day_start, minute=0)
            continue
        if lt + length > lt.replace(hour=day_end, minute=0) or lt.weekday() >= 5:
            t = (lt + dt.timedelta(days=1)).replace(hour=day_start, minute=0)
            continue
        clash = None
        for slots in busy_rows:
            for s, e, kind in slots or []:
                if kind != "free" and s < t + length and e > t:
                    clash = e if clash is None or e > clash else clash
        if clash is None:
            return t
        t = clash
        mins = (t.minute // step) * step
        if t.minute % step or t.second:
            t = t.replace(minute=mins, second=0, microsecond=0) + dt.timedelta(minutes=step)
    return None
