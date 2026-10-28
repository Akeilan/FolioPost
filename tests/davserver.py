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

    def add_user(self, user, password, cals=("personal",)):
        self.users[user] = (password, {c: Cal(c.capitalize()) for c in cals})
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

    def item(self, user, p):
        cals = self.server.world.users[user][1]
        if len(p) >= 3 and p[0] == "calendars" and p[2] in cals:
            return cals[p[2]], (p[3] if len(p) > 3 else None)
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
            return self.send(207, self.ms([self.resp(self.path, "<c:calendar-home-set><d:href>%s</d:href></c:calendar-home-set>" % home)]))
        if p[0] == "calendars" and len(p) == 2:
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
        c, _f = self.item(user, p)
        if c is None:
            return self.send(404)
        base = "/calendars/%s/%s/" % (user, p[2])
        out = []
        if "calendar-multiget" in body:
            for h in re.findall(r"<d:href>(.*?)</d:href>", body):
                f = urllib.parse.unquote(h.replace("&amp;", "&")).rstrip("/").split("/")[-1]
                if f in c.items:
                    et, data = c.items[f]
                    out.append(self.resp(base + f, "<d:getetag>%s</d:getetag><c:calendar-data>%s</c:calendar-data>" % (et, esc(data))))
        else:
            for f, (et, _d) in c.items.items():
                out.append(self.resp(base + urllib.parse.quote(f), "<d:getetag>%s</d:getetag>" % et))
        self.send(207, self.ms(out))

    def do_PUT(self):
        user = self.auth()
        if not user:
            return self.send(401)
        data = self.body()
        c, f = self.item(user, self.parts())
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
        c, f = self.item(user, self.parts())
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
