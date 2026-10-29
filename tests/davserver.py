"""A small CalDAV server for the tests: calendars in memory, enough of WebDAV and CalDAV for Post's
client (PROPFIND discovery, calendar-query, calendar-multiget, PUT with If-Match / If-None-Match,
DELETE), Basic or Bearer sign-in, and a GET of a calendar as one .ics file (a share link)."""
import base64
import hashlib
import http.server
import re
import threading
import urllib.parse


class Cal:
    def __init__(self, name, color="#16C60C"):
        self.name = name
        self.color = color
        self.items = {}          # file name -> (etag, data)
        self.ctag = 1

    def put(self, fname, data):
        et = '"%s"' % hashlib.md5(data.encode()).hexdigest()[:12]
        self.items[fname] = (et, data)
        self.ctag += 1
        return et


class World:
    def __init__(self):
        self.users = {}          # user -> (password, {cal id: Cal})
        self.log = []
        self.proxies = {}
        self.emails = {}

    def add_user(self, user, password, cals=("personal",), books=("contacts",)):
        self.users[user] = (password, {c: Cal(c.capitalize()) for c in cals})
        self.proxies = getattr(self, "proxies", {})      # owner -> {user: "read" | "write"}
        self.emails = getattr(self, "emails", {})        # e-mail address -> user
        if "@" in user:
            self.emails[user.lower()] = user
        self.books = getattr(self, "books", {})
        self.books[user] = {b: Cal(b.capitalize()) for b in books}
        return self.users[user][1]


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def auth(self):
        w = self.server.world
        h = self.headers.get("Authorization", "")
        if h.startswith("Bearer ") and h[7:] == "test-token":
            return next(iter(w.users))
        if h.startswith("Basic "):
            u, _, p = base64.b64decode(h[6:]).decode().partition(":")
            if u in w.users and w.users[u][0] == p:
                return u
        return None

    def send(self, code, body=b"", ctype="application/xml; charset=utf-8", extra=None):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n).decode("utf-8", "replace") if n else ""

    def ms(self, responses):
        return ('<?xml version="1.0"?><d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav" '
                'xmlns:cs="http://calendarserver.org/ns/" xmlns:a="http://apple.com/ns/ical/">%s</d:multistatus>' % "".join(responses))

    def resp(self, href, props):
        return "<d:response><d:href>%s</d:href><d:propstat><d:prop>%s</d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>" % (esc(href), props)

    def parts(self):
        return [urllib.parse.unquote(p) for p in urllib.parse.urlparse(self.path).path.strip("/").split("/") if p]

    def do_GET(self):
        p = self.parts()
        w = self.server.world
        if len(p) == 3 and p[0] == "share":
            cals = w.users.get(p[1], (None, {}))[1]
            c = cals.get(p[2].replace(".ics", ""))
            if c is None:
                return self.send(404)
            evs = []
            for _et, data in c.items.values():
                evs += re.findall(r"BEGIN:VEVENT.*?END:VEVENT\r?\n", data, re.S)
            text = "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//test//EN\r\nX-WR-CALNAME:%s\r\n%sEND:VCALENDAR\r\n" % (c.name, "".join(evs))
            return self.send(200, text, "text/calendar")
        user = self.auth()
        if not user:
            return self.send(401, "", extra={"WWW-Authenticate": 'Basic realm="test"'})
        c, f = self.item(user, p)
        if c is None or f not in c.items:
            return self.send(404)
        et, data = c.items[f]
        self.send(200, data, "text/calendar", {"ETag": et})

    def allowed(self, user, owner, write=False):
        m = self.server.world.proxies.get(owner, {}).get(user)
        return m == "write" or (m == "read" and not write)

    def item(self, user, p, write=False):
        cals = self.server.world.users[user][1]
        if len(p) >= 2 and p[0] == "calendars" and p[1] != user and p[1] in self.server.world.users:
            if not self.allowed(user, p[1], write):
                return None, None
            cals = self.server.world.users[p[1]][1]
        if len(p) >= 3 and p[0] == "calendars" and p[2] in cals:
            return cals[p[2]], (p[3] if len(p) > 3 else None)
        books = self.server.world.books.get(user, {})
        if len(p) >= 3 and p[0] == "addressbooks" and p[2] in books:
            return books[p[2]], (p[3] if len(p) > 3 else None)
        return None, None

    def do_PROPFIND(self):
        user = self.auth()
        if not user:
            return self.send(401, "", extra={"WWW-Authenticate": 'Basic realm="test"'})
        self.body()
        p = self.parts()
        depth = self.headers.get("Depth", "0")
        cals = self.server.world.users[user][1]
        home = "/calendars/%s/" % user
        if not p or p[0] == ".well-known":
            return self.send(207, self.ms([self.resp(self.path, "<d:current-user-principal><d:href>/principals/%s/</d:href>"
                                                                "</d:current-user-principal>" % user)]))
        if p[0] == "principals":
            w = self.server.world
            who = p[1] if len(p) > 1 and p[1] in w.users else user
            if len(p) > 2 and p[2].startswith("calendar-proxy-"):
                mode = p[2].split("-")[-1]
                members = [u for u, m in w.proxies.get(who, {}).items() if m == mode]
                return self.send(207, self.ms([self.resp(self.path, "<d:group-member-set>%s</d:group-member-set>"
                                                         % "".join("<d:href>/principals/%s/</d:href>" % u for u in members))]))
            fors = {"read": [], "write": []}
            for owner, granted in w.proxies.items():
                if user in granted:
                    fors[granted[user]].append(owner)
            extra = ("<cs:calendar-proxy-read-for>%s</cs:calendar-proxy-read-for><cs:calendar-proxy-write-for>%s"
                     "</cs:calendar-proxy-write-for>" % ("".join("<d:href>/principals/%s/</d:href>" % o for o in fors["read"]),
                                                        "".join("<d:href>/principals/%s/</d:href>" % o for o in fors["write"]))
                     if who == user else "")
            return self.send(207, self.ms([self.resp(self.path, "<c:calendar-home-set><d:href>/calendars/%s/</d:href></c:calendar-home-set>"
                                                     "<card:addressbook-home-set xmlns:card=\"urn:ietf:params:xml:ns:carddav\">"
                                                     "<d:href>/addressbooks/%s/</d:href></card:addressbook-home-set>"
                                                     "<c:schedule-outbox-URL><d:href>/outbox/%s/</d:href></c:schedule-outbox-URL>"
                                                     "<d:displayname>%s</d:displayname>%s" % (who, who, who, who, extra))]))
        if p[0] == "addressbooks" and len(p) == 2:
            bh = "/addressbooks/%s/" % user
            out = [self.resp(bh, "<d:resourcetype><d:collection/></d:resourcetype>")]
            if depth != "0":
                for bid, b in self.server.world.books.get(user, {}).items():
                    out.append(self.resp(bh + bid + "/", "<d:resourcetype><d:collection/><card:addressbook xmlns:card="
                                         "\"urn:ietf:params:xml:ns:carddav\"/></d:resourcetype><d:displayname>%s</d:displayname>"
                                         "<cs:getctag>%d</cs:getctag>" % (esc(b.name), b.ctag)))
            return self.send(207, self.ms(out))
        if p[0] == "calendars" and len(p) == 2:
            if p[1] != user:
                if not self.allowed(user, p[1]):
                    return self.send(403)
                cals = self.server.world.users[p[1]][1]
                home = "/calendars/%s/" % p[1]
            out = [self.resp(home, "<d:resourcetype><d:collection/></d:resourcetype>")]
            if depth != "0":
                for cid, c in cals.items():
                    out.append(self.resp(home + cid + "/", "<d:resourcetype><d:collection/><c:calendar/></d:resourcetype>"
                                         "<d:displayname>%s</d:displayname><a:calendar-color>%s</a:calendar-color>"
                                         "<cs:getctag>%d</cs:getctag><c:supported-calendar-component-set><c:comp name=\"VEVENT\"/>"
                                         "</c:supported-calendar-component-set>" % (esc(c.name), c.color, c.ctag)))
            return self.send(207, self.ms(out))
        c, _f = self.item(user, p)
        if c is not None:
            return self.send(207, self.ms([self.resp(self.path, "<cs:getctag>%d</cs:getctag>" % c.ctag)]))
        self.send(404)

    def do_REPORT(self):
        user = self.auth()
        if not user:
            return self.send(401)
        body = self.body()
        p = self.parts()
        if "principal-property-search" in body:
            m = re.search(r"<d:match>mailto:([^<]+)</d:match>", body)
            u = getattr(self.server.world, "emails", {}).get(m.group(1).lower()) if m else None
            return self.send(207, self.ms([self.resp("/principals/%s/" % u, "<d:displayname>%s</d:displayname>" % u)] if u else []))
        c, _f = self.item(user, p)
        if c is None:
            return self.send(404)
        base = "/%s/%s/%s/" % (p[0], p[1], p[2])
        tag = "c:calendar-data" if p[0] == "calendars" else "card:address-data"
        out = []
        if "multiget" in body:
            for h in re.findall(r"<d:href>(.*?)</d:href>", body):
                f = urllib.parse.unquote(h.replace("&amp;", "&")).rstrip("/").split("/")[-1]
                if f in c.items:
                    et, data = c.items[f]
                    out.append(self.resp(base + f, "<d:getetag>%s</d:getetag><%s xmlns:card=\"urn:ietf:params:xml:ns:carddav\">%s</%s>"
                                         % (et, tag, esc(data), tag)))
        else:
            for f, (et, _d) in c.items.items():
                out.append(self.resp(base + urllib.parse.quote(f), "<d:getetag>%s</d:getetag>" % et))
        self.send(207, self.ms(out))

    def do_POST(self):
        """RFC 6638 free/busy: a VFREEBUSY request to the schedule outbox."""
        user = self.auth()
        if not user:
            return self.send(401)
        body = self.body()
        p = self.parts()
        if not p or p[0] != "outbox":
            return self.send(404)
        w = self.server.world
        start = re.search(r"DTSTART:(\d{8}T\d{6}Z)", body).group(1)
        end = re.search(r"DTEND:(\d{8}T\d{6}Z)", body).group(1)
        out = []
        for a in re.findall(r"ATTENDEE[^:]*:mailto:([^\r\n]+)", body):
            u = w.emails.get(a.lower()) if hasattr(w, "emails") else None
            if u is None:
                out.append("<c:response><c:recipient><d:href>mailto:%s</d:href></c:recipient><c:request-status>3.7;Invalid "
                           "calendar user</c:request-status></c:response>" % esc(a))
                continue
            busy = []
            for c in w.users[u][1].values():
                for _et, data in c.items.values():
                    for ev in re.findall(r"BEGIN:VEVENT.*?END:VEVENT", data, re.S):
                        s = re.search(r"DTSTART(?:;[^:]*)?:(\d{8}T\d{6}Z)", ev)
                        e = re.search(r"DTEND(?:;[^:]*)?:(\d{8}T\d{6}Z)", ev)
                        if s and e and s.group(1) < end and e.group(1) > start and "TRANSP:TRANSPARENT" not in ev:
                            busy.append("%s/%s" % (s.group(1), e.group(1)))
            fb = ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//test//EN\r\nMETHOD:REPLY\r\nBEGIN:VFREEBUSY\r\nDTSTART:%s\r\n"
                  "DTEND:%s\r\n%sEND:VFREEBUSY\r\nEND:VCALENDAR\r\n" % (start, end, "".join("FREEBUSY;FBTYPE=BUSY:%s\r\n" % b for b in busy)))
            out.append("<c:response><c:recipient><d:href>mailto:%s</d:href></c:recipient><c:request-status>2.0;Success"
                       "</c:request-status><c:calendar-data>%s</c:calendar-data></c:response>" % (esc(a), esc(fb)))
        self.send(200, '<?xml version="1.0"?><c:schedule-response xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">%s'
                  '</c:schedule-response>' % "".join(out))

    def do_PROPPATCH(self):
        user = self.auth()
        if not user:
            return self.send(401)
        body = self.body()
        p = self.parts()
        if len(p) == 3 and p[0] == "principals" and p[1] == user and p[2].startswith("calendar-proxy-"):
            mode = p[2].split("-")[-1]
            w = self.server.world
            g = w.proxies.setdefault(user, {})
            for u in [u for u, m in g.items() if m == mode]:
                del g[u]
            for h in re.findall(r"<d:href>/principals/([^/<]+)/?</d:href>", body):
                g[h] = mode
            return self.send(207, self.ms([self.resp(self.path, "<d:group-member-set/>")]))
        self.send(403)

    def do_PUT(self):
        user = self.auth()
        if not user:
            return self.send(401)
        data = self.body()
        c, f = self.item(user, self.parts(), write=True)
        if c is None or not f:
            return self.send(404)
        if self.headers.get("If-None-Match") == "*" and f in c.items:
            return self.send(412)
        im = self.headers.get("If-Match")
        if im and (f not in c.items or c.items[f][0] != im):
            return self.send(412)
        self.server.world.log.append(("PUT", f))
        et = c.put(f, data)
        self.send(201, "", extra={"ETag": et})

    def do_DELETE(self):
        user = self.auth()
        if not user:
            return self.send(401)
        c, f = self.item(user, self.parts(), write=True)
        if c is None or f not in c.items:
            return self.send(404)
        im = self.headers.get("If-Match")
        if im and c.items[f][0] != im:
            return self.send(412)
        del c.items[f]
        c.ctag += 1
        self.server.world.log.append(("DELETE", f))
        self.send(204)


class _Server(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def start(world=None):
    world = world or World()
    s = _Server(("127.0.0.1", 0), Handler)
    s.world = world
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return world, s.server_address[1], s.shutdown


def event(uid, summary, start, end, rrule="", tzid="Europe/Amsterdam", extra=""):
    return ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//test//EN\r\nBEGIN:VEVENT\r\nUID:%s\r\nDTSTAMP:20260101T000000Z\r\n"
            "DTSTART;TZID=%s:%s\r\nDTEND;TZID=%s:%s\r\nSUMMARY:%s\r\n%s%sEND:VEVENT\r\nEND:VCALENDAR\r\n"
            % (uid, tzid, start, tzid, end, summary, ("RRULE:%s\r\n" % rrule) if rrule else "", extra))
