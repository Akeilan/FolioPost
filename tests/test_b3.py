"""Backlog 3 engine tests: Automatic Replies (Sieve, Gmail, Exchange), free/busy (CalDAV,
Google, Exchange, this computer) and other people's calendars / delegates (CalDAV proxies)."""
import datetime as dt
import http.server
import json
import os
import sys
import tempfile
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "app"))
sys.path.insert(0, HERE)
os.environ["FOLIO_POST_FILE_SECRETS"] = "1"

import davserver  # noqa: E402
import ewsserver  # noqa: E402
import sieveserver  # noqa: E402
from folio_post import autoreply, caldav, freebusy, ical, store as S, sync  # noqa: E402
from folio_post.caldav import Client  # noqa: E402

FAILS = []
UTC = dt.timezone.utc


def check(cond, what):
    print(("ok   " if cond else "FAIL ") + what)
    sys.stdout.flush()
    if not cond:
        FAILS.append(what)


root = tempfile.mkdtemp()
st = S.Store(root)
sec = sync.Secrets(os.path.join(root, "secrets.json"))


class App:
    store = st
    secrets = sec

    @staticmethod
    def tokens(acc):
        return "test-token"


app = App()
app.calsync = caldav.CalendarSync(st, sec, App.tokens)

# ---------------------------------------------------------------- Automatic Replies: Sieve
sw = sieveserver.World()
su = sw.add_user("me@example.org", "secret")
su["scripts"]["main"] = 'require ["fileinto"];\n# my filters\nif header :contains "subject" "invoice" {\n    fileinto "Bills";\n}\n'
su["active"] = "main"
ssrv, sport = sieveserver.start(sw)
acc_id = st.add_account("Me", "me@example.org", "imap", {"imap_host": "127.0.0.1", "imap_security": "none", "sieve_port": sport,
                                                      "user": "me@example.org"})
sec.set(acc_id, "secret")
acc = st.account(acc_id)
be = autoreply.backend_for(app, acc)
check(isinstance(be, autoreply.SieveBackend), "an IMAP server's automatic replies go through ManageSieve")
check(be.get()["state"] == "off", "off at first")
start = dt.datetime(2026, 11, 2, 9, 0, tzinfo=UTC)
s = autoreply.blank()
s.update({"state": "scheduled", "start": start, "end": start + dt.timedelta(days=5), "internal": 'Away "until" Friday.',
          "subject": "Out of office"})
be.set(s)
script = su["scripts"]["main"]
check(su["active"] == "main" and 'fileinto "Bills"' in script, "the user's own rules are kept")
check(script.index("require [\"vacation\"") < script.index('require ["fileinto"]') < script.index("vacation :days 1"),
      "requires first, then the reply")
check('currentdate :zone "+0000" :value "ge" "time" "09:00:00"' in script and '"2026-11-07"' in script, "only in the time range")
check('\\"until\\"' in script and ':subject "Out of office"' in script, "the message and subject quoted for Sieve")
back = be.get()
check(back["state"] == "scheduled" and back["start"] == start and back["internal"] == 'Away "until" Friday.', "read back")
s["state"] = "off"
be.set(s)
script = su["scripts"]["main"]
check("vacation :days" not in script and 'fileinto "Bills"' in script and script.count("Folio Post") == 3,
      "switched off: no reply left, own rules kept")
su2 = sw.add_user("new@example.org", "pw")
be2 = autoreply.SieveBackend("127.0.0.1", sport, "new@example.org", "pw", "none")
be2.set(dict(autoreply.blank(), state="on", internal="Back soon"))
check(su2["active"] == autoreply.SCRIPT and "vacation" in su2["scripts"][autoreply.SCRIPT], "a server with no script gets one, active")
try:
    autoreply.SieveBackend("127.0.0.1", 1, "x", "y", "none").get()
    check(False, "no ManageSieve: said plainly")
except autoreply.NotReachable as e:
    check("doesn't take automatic replies" in str(e), "no ManageSieve: said plainly")
try:
    autoreply.backend_for(app, {"id": 99, "kind": "imap", "email": "me@proton.me", "config": {"bridge": True}})
    check(False, "Proton says it isn't reachable")
except autoreply.NotReachable as e:
    check("Proton" in str(e), "Proton says it isn't reachable")


# ---------------------------------------------------------------- Gmail
class Gmail(http.server.BaseHTTPRequestHandler):
    state = {"enableAutoReply": False}

    def log_message(self, *a):
        pass

    def _send(self, d):
        b = json.dumps(d).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.headers.get("Authorization") != "Bearer test-token":
            self.send_response(401)
            self.end_headers()
            return
        if self.path.startswith("/freebusy"):
            return
        self._send(Gmail.state)

    def do_PUT(self):
        Gmail.state = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self._send(Gmail.state)

    def do_POST(self):
        req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        cals = {}
        for it in req["items"]:
            if it["id"] == "kim@gmail.test":
                cals[it["id"]] = {"busy": [{"start": "2026-11-02T13:00:00Z", "end": "2026-11-02T14:00:00Z"}]}
            else:
                cals[it["id"]] = {"errors": [{"domain": "global", "reason": "notFound"}]}
        self._send({"calendars": cals})


gsrv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Gmail)
threading.Thread(target=gsrv.serve_forever, daemon=True).start()
gurl = "http://127.0.0.1:%d" % gsrv.server_address[1]
st.put("gmail-api-url", gurl + "/gmail/v1/users/me/settings/vacation")
st.put("google-freebusy-url", gurl + "/freebusy")
gid = st.add_account("G", "me@gmail.test", "imap", {"imap_host": "imap.gmail.com", "auth": "oauth"})
gb = autoreply.backend_for(app, st.account(gid))
check(isinstance(gb, autoreply.GmailBackend), "Gmail uses its vacation responder")
gb.set(dict(autoreply.blank(), state="scheduled", start=start, end=start + dt.timedelta(days=2), internal="Hiking",
            subject="Away", audience="known"))
check(Gmail.state["enableAutoReply"] and Gmail.state["startTime"] == str(int(start.timestamp() * 1000)) and
      Gmail.state["restrictToContacts"] and Gmail.state["responseSubject"] == "Away", "Gmail vacation responder set")
g = gb.get()
check(g["state"] == "scheduled" and g["internal"] == "Hiking" and g["audience"] == "known", "and read back")
try:
    autoreply.backend_for(app, {"id": 98, "kind": "imap", "email": "x@gmail.com", "config": {"imap_host": "imap.gmail.com"}})
    check(False, "Gmail with an app password says what's needed")
except autoreply.NotReachable as e:
    check("Google sign-in" in str(e), "Gmail with an app password says what's needed")

# ---------------------------------------------------------------- Exchange
ew = ewsserver.World()
megan = ew.add_user("me@contoso.test", "secret", "Megan")
bob = ew.add_user("bob@contoso.test", "pw", "Bob")
esrv, eurl = ewsserver.start(ew)
eid = st.add_account("Megan", "me@contoso.test", "ews", {"ews_url": eurl, "user": "me@contoso.test", "auth": "password",
                                                       "ews_auth": "basic"})
sec.set(eid, "secret")
eb = autoreply.backend_for(app, st.account(eid))
check(isinstance(eb, autoreply.ExchangeBackend) and eb.has_external, "Exchange: inside and outside the organization")
eb.set(dict(autoreply.blank(), state="on", internal="Inside", external="Outside", audience="known"))
check(megan.oof["state"] == "Enabled" and megan.oof["external"] == "Outside" and megan.oof["audience"] == "Known", "Exchange OOF set")

# ---------------------------------------------------------------- free/busy
dw, dport, dstop = davserver.start()
dw.add_user("me@dav.test", "pw", cals=("personal",))
cals = dw.add_user("ann@dav.test", "pw2", cals=("work",))
cals["work"].put("a.ics", "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:a\r\nDTSTART:20261102T100000Z\r\nDTEND:20261102T113000Z\r\n"
                 "SUMMARY:Ann busy\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")
base = "http://127.0.0.1:%d/" % dport
c = Client(base, "me@dav.test", "pw")
check(freebusy.caldav_outbox(c) == "/outbox/me@dav.test/", "the schedule outbox found")
fb = freebusy.caldav_freebusy(c, "me@dav.test", ["ann@dav.test", "zed@dav.test"], start, start + dt.timedelta(hours=10))
check(fb["ann@dav.test"] == [(dt.datetime(2026, 11, 2, 10, 0, tzinfo=UTC), dt.datetime(2026, 11, 2, 11, 30, tzinfo=UTC), "busy")],
      "Ann's busy time from the CalDAV server")
check(fb["zed@dav.test"] is None, "no information for an unknown person")
gfb = freebusy.lookup(app, st.account(gid), ["kim@gmail.test", "who@gmail.test"], start, start + dt.timedelta(hours=10))
check(gfb["kim@gmail.test"][0][0].hour == 13 and gfb["who@gmail.test"] is None, "Google's freeBusy")
import xml.etree.ElementTree as ET  # noqa: E402
bx = ET.fromstring('<t:CalendarItem xmlns:t="%s"><t:Subject>x</t:Subject><t:Start>2026-11-02T09:00:00Z</t:Start>'
                   '<t:End>2026-11-02T10:00:00Z</t:End><t:LegacyFreeBusyStatus>Tentative</t:LegacyFreeBusyStatus></t:CalendarItem>' % ewsserver.T)
ewsserver.set_id(bx, "I-b")
bob.folders[bob.dist["calendar"]]["items"]["I-b"] = bx
efb = freebusy.lookup(app, st.account(eid), ["bob@contoso.test"], start, start + dt.timedelta(hours=10))
check(efb["bob@contoso.test"] and efb["bob@contoso.test"][0][2] == "tentative", "Exchange's availability")
# own calendar here
lc = st.add_calendar("Mine", "#0078D4", "local")
caldav.save_event(st, lc, [ical.new_event("Dentist", dt.datetime(2026, 11, 2, 12, 0, tzinfo=UTC), dt.datetime(2026, 11, 2, 13, 0, tzinfo=UTC))])
own = freebusy.lookup(app, st.account(eid), ["me@contoso.test"], start, start + dt.timedelta(hours=10))["me@contoso.test"]
check(any(s0.astimezone(UTC).hour == 12 for s0, _e, _k in own), "the organizer's own busy time from this computer")
rows = [efb["bob@contoso.test"], own, [(dt.datetime(2026, 11, 2, 10, 0, tzinfo=UTC), dt.datetime(2026, 11, 2, 11, 30, tzinfo=UTC), "busy")]]
t = freebusy.next_free(rows, start, dt.timedelta(hours=1))
check(t is not None and t.astimezone(UTC) == dt.datetime(2026, 11, 2, 13, 0, tzinfo=UTC), "AutoPick: the first hour all are free (%s)" % t)

# ---------------------------------------------------------------- CalDAV delegation
ca = Client(base, "ann@dav.test", "pw2")
check(freebusy.caldav_find_principal(c, "ann@dav.test") == "/principals/ann@dav.test/", "Ann's principal found by address")
check(freebusy.caldav_principal_calendars(c, "/principals/ann@dav.test/")[1] == [], "Ann's calendars closed before she shares")
freebusy.caldav_set_delegate(ca, "/principals/me@dav.test/", "read")
check(freebusy.caldav_delegates(ca) == [("/principals/me@dav.test/", "read")], "Ann makes me a delegate (read)")
check(freebusy.caldav_delegations(c) == [("/principals/ann@dav.test/", "read")], "and I see that she did")
name, shared = freebusy.caldav_principal_calendars(c, "/principals/ann@dav.test/")
check([x["name"] for x in shared] == ["Work"], "Ann's Work calendar is open to me")
sc = st.add_calendar("Work - Ann", "#000000", "caldav", c.url(shared[0]["href"]), 0, True)
st.put("calendar-source:%d" % sc, {"url": c.url(shared[0]["href"]), "user": "me@dav.test", "secret_key": "k1"})
sec.set("k1", "pw", "caldav")
check(app.calsync.sync(sc) and [e["summary"] for e in st.events(sc)] == ["Ann busy"], "and her events come here")
freebusy.caldav_set_delegate(ca, "/principals/me@dav.test/", "write")
check(freebusy.caldav_delegates(ca) == [("/principals/me@dav.test/", "write")], "made an editor instead")
freebusy.caldav_set_delegate(ca, "/principals/me@dav.test/", "none")
check(freebusy.caldav_delegates(ca) == [] and freebusy.caldav_delegations(c) == [], "and taken back")
check(freebusy.google_shared_url("kim@gmail.test").endswith("/caldav/v2/kim%40gmail.test/events/"), "Google: the shared calendar's address")

for x in (ssrv, gsrv, esrv):
    x.shutdown()
dstop()
print("B3 tests: %s" % ("all passed" if not FAILS else "%d FAILED" % len(FAILS)))
sys.exit(1 if FAILS else 0)
