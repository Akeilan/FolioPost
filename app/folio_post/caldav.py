"""Calendars on servers: CalDAV (RFC 4791) — Google Calendar (with the Google sign-in), Fastmail,
iCloud, Nextcloud and the rest — and read-only calendars from an internet address (.ics), as Proton
Calendar shares them. Two-way sync keeps changes made offline and sends them later."""
import base64
import datetime as dt
import re
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import xml.etree.ElementTree as ET

from . import ical

NS = {"d": "DAV:", "c": "urn:ietf:params:xml:ns:caldav", "cs": "http://calendarserver.org/ns/",
      "a": "http://apple.com/ns/ical/"}
GOOGLE_CALDAV = "https://apidata.googleusercontent.com/caldav/v2/"
TIMEOUT = 30
COLORS = ["#0078D4", "#E74856", "#16C60C", "#FF8C00", "#886CE4", "#038387", "#C239B3", "#986F0B"]


class DavError(Exception):
    def __init__(self, status, text=""):
        Exception.__init__(self, "HTTP %s %s" % (status, text))
        self.status = status


class Client:
    def __init__(self, base, user="", password=None, token=None, insecure=False):
        self.base = base
        self.user = user
        self.password = password
        self.token = token
        self.ctx = ssl.create_default_context()
        if insecure:
            self.ctx.check_hostname = False
            self.ctx.verify_mode = ssl.CERT_NONE

    def url(self, href):
        return urllib.parse.urljoin(self.base, href)

    def request(self, method, url, body=None, headers=None):
        h = {"User-Agent": "Folio Post"}
        if self.token:
            h["Authorization"] = "Bearer " + (self.token() if callable(self.token) else self.token)
        elif self.password is not None:
            h["Authorization"] = "Basic " + base64.b64encode(("%s:%s" % (self.user, self.password)).encode()).decode()
        h.update(headers or {})
        data = body.encode("utf-8") if isinstance(body, str) else body
        req = urllib.request.Request(self.url(url), data=data, method=method, headers=h)
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT, context=self.ctx) as r:
                return r.status, dict(r.headers), r.read()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers or {}), e.read() if hasattr(e, "read") else b""

    def xml(self, method, url, body, depth="0"):
        st, h, data = self.request(method, url, body, {"Content-Type": "application/xml; charset=utf-8", "Depth": depth})
        if st in (401, 403):
            raise DavError(st, "the server didn't accept the sign-in")
        if st >= 400:
            raise DavError(st)
        try:
            return ET.fromstring(data) if data else None
        except ET.ParseError:
            return None

    # ------------------------------------------------------------ discovery
    def propfind(self, url, props, depth="0"):
        body = ('<?xml version="1.0"?><d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav" '
                'xmlns:cs="http://calendarserver.org/ns/" xmlns:a="http://apple.com/ns/ical/"><d:prop>%s</d:prop>'
                '</d:propfind>' % "".join("<%s/>" % p for p in props))
        root = self.xml("PROPFIND", url, body, depth)
        out = []
        for r in (root.findall("d:response", NS) if root is not None else []):
            href = r.findtext("d:href", "", NS)
            props_ = {}
            for ps in r.findall("d:propstat", NS):
                if "200" not in (ps.findtext("d:status", "", NS) or "200"):
                    continue
                prop = ps.find("d:prop", NS)
                for p in (list(prop) if prop is not None else []):
                    props_[p.tag] = p
            out.append((href, props_))
        return out

    def principal(self):
        for start in (self.base, "/.well-known/caldav"):
            try:
                res = self.propfind(start, ["d:current-user-principal"])
            except DavError:
                continue
            for _href, p in res:
                e = p.get("{DAV:}current-user-principal")
                if e is not None:
                    h = e.findtext("d:href", "", NS)
                    if h:
                        return h
        return None

    def home(self):
        pr = self.principal()
        if pr is None:
            return self.base
        for _href, p in self.propfind(pr, ["c:calendar-home-set"]):
            e = p.get("{urn:ietf:params:xml:ns:caldav}calendar-home-set")
            if e is not None:
                h = e.findtext("d:href", "", NS)
                if h:
                    return h
        return pr

    def calendars(self):
        """[{href, name, color, ctag, readonly}] of the calendars that hold events."""
        home = self.home()
        out = []
        for href, p in self.propfind(home, ["d:resourcetype", "d:displayname", "a:calendar-color", "cs:getctag",
                                            "c:supported-calendar-component-set", "d:current-user-privilege-set"], "1"):
            rt = p.get("{DAV:}resourcetype")
            if rt is None or rt.find("c:calendar", NS) is None:
                continue
            comps = p.get("{urn:ietf:params:xml:ns:caldav}supported-calendar-component-set")
            if comps is not None and comps.findall("c:comp", NS) and \
                    not any(c.get("name") == "VEVENT" for c in comps.findall("c:comp", NS)):
                continue
            priv = p.get("{DAV:}current-user-privilege-set")
            readonly = priv is not None and priv.find(".//d:write", NS) is None and priv.find(".//d:all", NS) is None and \
                priv.find(".//d:write-content", NS) is None
            name = (p.get("{DAV:}displayname").text if p.get("{DAV:}displayname") is not None else "") or \
                urllib.parse.unquote(href.rstrip("/").split("/")[-1])
            color = p.get("{http://apple.com/ns/ical/}calendar-color")
            out.append({"href": href, "name": name, "color": (color.text or "")[:7] if color is not None else "",
                        "ctag": (p.get("{http://calendarserver.org/ns/}getctag").text or "")
                        if p.get("{http://calendarserver.org/ns/}getctag") is not None else "", "readonly": readonly})
        return out

    def ctag(self, href):
        for _h, p in self.propfind(href, ["cs:getctag", "d:sync-token"]):
            e = p.get("{http://calendarserver.org/ns/}getctag")
            if e is None:
                e = p.get("{DAV:}sync-token")
            return (e.text or "") if e is not None else ""
        return ""

    # ------------------------------------------------------------ events
    def etags(self, href, since=None):
        flt = '<c:comp-filter name="VEVENT"/>'
        if since:
            flt = '<c:comp-filter name="VEVENT"><c:time-range start="%s"/></c:comp-filter>' % since
        body = ('<?xml version="1.0"?><c:calendar-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
                '<d:prop><d:getetag/></d:prop><c:filter><c:comp-filter name="VCALENDAR">%s</c:comp-filter></c:filter>'
                '</c:calendar-query>' % flt)
        root = self.xml("REPORT", href, body, "1")
        out = {}
        for r in (root.findall("d:response", NS) if root is not None else []):
            h = r.findtext("d:href", "", NS)
            et = r.findtext(".//d:getetag", "", NS)
            if h and not h.endswith("/"):
                out[h] = et
        return out

    def multiget(self, href, hrefs):
        out = []
        for i in range(0, len(hrefs), 50):
            chunk = hrefs[i:i + 50]
            body = ('<?xml version="1.0"?><c:calendar-multiget xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
                    '<d:prop><d:getetag/><c:calendar-data/></d:prop>%s</c:calendar-multiget>' %
                    "".join("<d:href>%s</d:href>" % _xesc(h) for h in chunk))
            root = self.xml("REPORT", href, body, "1")
            for r in (root.findall("d:response", NS) if root is not None else []):
                data = r.findtext(".//c:calendar-data", None, NS)
                if data:
                    out.append((r.findtext("d:href", "", NS), r.findtext(".//d:getetag", "", NS), data))
        return out

    def put(self, href, ics, etag=None, new=False):
        h = {"Content-Type": "text/calendar; charset=utf-8"}
        if new:
            h["If-None-Match"] = "*"
        elif etag:
            h["If-Match"] = etag
        st, headers, _b = self.request("PUT", href, ics, h)
        if st == 412:
            raise DavError(412, "changed on the server")
        if st >= 400:
            raise DavError(st)
        return headers.get("ETag") or headers.get("Etag") or headers.get("etag") or ""

    def delete(self, href, etag=None):
        st, _h, _b = self.request("DELETE", href, None, {"If-Match": etag} if etag else {})
        if st >= 400 and st not in (404, 410):
            raise DavError(st)


def _xesc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def summary_of(ics):
    """(uid, summary, first start, last end or 0 for 'goes on') of a calendar object."""
    cal = ical.parse(ics)
    evs = ical.events_of(cal)
    if not evs:
        return "", "", 0, 0
    master = [e for e in evs if e.recurrence_id is None] or evs
    e = master[0]
    s = e.start
    until = 0
    if e.rrule:
        r = ical.parse_rrule(e.rrule)
        if r.get("UNTIL"):
            until = int(ical.parse_time(r["UNTIL"])[0].timestamp()) + 86400
        elif r.get("COUNT"):
            until = 0
    else:
        en = max((x.end or x.start) for x in evs if x.start)
        until = int(en.timestamp()) if en else 0
    return e.uid, e.summary, int(s.timestamp()) if s else 0, until


def fetch_ics(url):
    url = re.sub(r"^webcals?://", "https://", url.strip())
    req = urllib.request.Request(url, headers={"User-Agent": "Folio Post"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read().decode("utf-8", "replace")


class CalendarSync:
    """Brings an account's calendars and the local store in step."""

    def __init__(self, store, secrets, tokens):
        self.store = store
        self.secrets = secrets
        self.tokens = tokens
        self.lock = threading.Lock()
        self.errors = {}

    def client_for(self, cal):
        if cal["kind"] == "google":
            acc = self.store.account(cal["account"])
            return Client(GOOGLE_CALDAV, acc["email"], token=lambda: self.tokens(acc))
        cfg = self.store.get("caldav:%d" % cal["account"], {}) if cal["account"] else {}
        cfg = cfg or self.store.get("calendar-source:%d" % cal["id"], {}) or {}
        pw = self.secrets.get(cfg.get("secret_key", "cal%d" % cal["id"]), "caldav") if cfg else None
        if cal["account"] and not pw:
            pw = self.secrets.get(cal["account"])
        return Client(cfg.get("url") or cal["url"], cfg.get("user", ""), pw, insecure=cfg.get("insecure", False))

    # ------------------------------------------------------------ adding sources
    def add_caldav(self, url, user, password, account=0, kind="caldav", token=None):
        """Every event calendar at a CalDAV address; returns the new calendar ids."""
        c = Client(url, user, password, token=token)
        cals = c.calendars()
        ids = []
        key = "caldav-src-%s" % uuid.uuid4().hex[:8]
        for i, info in enumerate(cals):
            cid = self.store.add_calendar(info["name"], info["color"] or COLORS[(len(self.store.calendars()) + i) % len(COLORS)],
                                          kind, c.url(info["href"]), account, info["readonly"])
            self.store.put("calendar-source:%d" % cid, {"url": c.url(info["href"]), "user": user, "secret_key": key})
            ids.append(cid)
        if password is not None:
            self.secrets.set(key, password, "caldav")
        return ids

    def add_google(self, account):
        acc = self.store.account(account)
        c = Client(GOOGLE_CALDAV, acc["email"], token=lambda: self.tokens(acc))
        try:
            cals = c.calendars()
        except DavError:
            cals = []
        if not cals:
            cals = [{"href": GOOGLE_CALDAV + urllib.parse.quote(acc["email"]) + "/events/", "name": acc["email"], "color": "",
                     "readonly": False}]
        ids = []
        for i, info in enumerate(cals):
            ids.append(self.store.add_calendar(info["name"], info["color"] or COLORS[i % len(COLORS)], "google",
                                               c.url(info["href"]), account, info["readonly"]))
        return ids

    def add_ics(self, url, name=""):
        """A calendar read from an internet address (Proton Calendar's share link, holiday calendars, ...)."""
        text = fetch_ics(url)
        cal = ical.parse(text)
        if cal is None:
            raise ValueError("that address doesn't give a calendar")
        nm = name or ical.unescape(cal.get("X-WR-CALNAME", "")) or "Internet Calendar"
        cid = self.store.add_calendar(nm, COLORS[len(self.store.calendars()) % len(COLORS)], "ics", url, 0, True)
        self._replace_ics(cid, text)
        return cid

    def _replace_ics(self, cid, text):
        cal = ical.parse(text)
        groups = {}
        for e in ical.events_of(cal):
            groups.setdefault(e.uid, []).append(e)
        tzs = [c for c in (cal.sub("VTIMEZONE") if cal else [])]
        have = {e["uid"]: e for e in self.store.events(cid)}
        for uid, evs in groups.items():
            c = ical.calendar_of(evs)
            c.children = tzs + [x for x in c.children if x.name != "VTIMEZONE"]
            ics = ical.dumps(c)
            u, s, st, un = summary_of(ics)
            old = have.pop(uid, None)
            self.store.put_event(cid, uid, ics, "", "", "", s, st, un, old["id"] if old else None)
        for e in have.values():
            self.store.drop_event(e["id"])
        self.store.update_calendar(cid, ctag=str(int(time.time())))

    # ------------------------------------------------------------ syncing
    def sync(self, cid):
        cal = self.store.calendar(cid)
        if cal is None or cal["kind"] == "local":
            return True
        with self.lock:
            try:
                if cal["kind"] == "ics":
                    self._replace_ics(cid, fetch_ics(cal["url"]))
                elif cal["kind"] == "ews":
                    from . import ews
                    c = ews.client_for(self.store.account(cal["account"]), self.secrets, self.tokens)
                    try:
                        ews.sync_calendar(self.store, c, cal)
                    finally:
                        c.close()
                else:
                    self._sync_dav(cal)
                self.errors.pop(cid, None)
                return True
            except Exception as e:
                self.errors[cid] = str(e)
                return False

    def sync_all(self):
        return [self.sync(c["id"]) for c in self.store.calendars()]

    def _sync_dav(self, cal):
        c = self.client_for(cal)
        cid = cal["id"]
        # local changes first
        for e in self.store.events(cid, with_deleted=True):
            p = e["pending"]
            if not p:
                continue
            try:
                if p == "deleted":
                    if e["href"]:
                        c.delete(e["href"], e["etag"])
                    self.store.drop_event(e["id"])
                elif p == "new":
                    href = e["href"] or (cal["url"].rstrip("/") + "/" + urllib.parse.quote(re.sub(r"[^\w.@-]", "_", e["uid"])) + ".ics")
                    et = c.put(href, e["ics"], new=True)
                    self.store.set_event_fields(e["id"], href=urllib.parse.urlparse(c.url(href)).path, etag=et, pending="")
                elif p == "changed":
                    et = c.put(e["href"], e["ics"], e["etag"])
                    self.store.set_event_fields(e["id"], etag=et, pending="")
            except DavError as err:
                if err.status == 412:
                    # changed on the server too: the server's version wins, fetched below
                    self.store.set_event_fields(e["id"], pending="", etag="conflict")
                else:
                    raise
        tag = c.ctag(cal["url"])
        if tag and tag == cal["ctag"]:
            return
        remote = c.etags(cal["url"])
        local = {e["href"]: e for e in self.store.events(cid, with_deleted=True) if e["href"]}
        for href, e in local.items():
            if href not in remote and not e["pending"]:
                self.store.drop_event(e["id"])
        want = [h for h, et in remote.items() if h not in local or local[h]["etag"] != et]
        for href, et, data in c.multiget(cal["url"], want):
            uid, s, st, un = summary_of(data)
            old = local.get(href)
            if old and old["pending"]:
                continue
            self.store.put_event(cid, uid, data, href, et, "", s, st, un, old["id"] if old else None)
        self.store.update_calendar(cid, ctag=tag)


# ---------------------------------------------------------------- local edits
def save_event(store, cid, event_comps, eid=None, tz_comps=()):
    """Store an event (master and changed instances) made or changed here; the sync sends it."""
    cal = ical.calendar_of([ical.Event(c) if not isinstance(c, ical.Event) else c for c in event_comps])
    ics = ical.dumps(cal)
    uid, s, st, un = summary_of(ics)
    calendar = store.calendar(cid)
    local = calendar is None or calendar["kind"] == "local"
    if eid is not None:
        old = store.event(eid)
        moved = old and old["calendar"] != cid
        if moved:
            # into another calendar: removed from the old one, new in this one
            if old["href"]:
                store.set_event_fields(eid, pending="deleted")
            else:
                store.drop_event(eid)
            return store.put_event(cid, uid, ics, "", "", "" if local else "new", s, st, un)
        pend = "" if local else (old["pending"] or "changed") if old["href"] else "new"
        return store.put_event(cid, uid, ics, old["href"], old["etag"], pend, s, st, un, eid)
    return store.put_event(cid, uid, ics, "", "", "" if local else "new", s, st, un)


def delete_event(store, eid):
    e = store.event(eid)
    if e is None:
        return
    cal = store.calendar(e["calendar"])
    if e["href"] and cal and cal["kind"] not in ("local", "ics"):
        store.set_event_fields(eid, pending="deleted")
    else:
        store.drop_event(eid)
