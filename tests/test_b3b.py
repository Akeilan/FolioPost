"""Backlog 3 engine tests, part two: voting buttons, Outlook templates (.oft/.msg), RSS feeds
and the mail merge contract with Folio Writer (--send-merge, --list-contacts)."""
import http.server
import json
import os
import subprocess
import sys
import tempfile
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "app"))
sys.path.insert(0, HERE)
os.environ["FOLIO_POST_FILE_SECRETS"] = "1"

import mailserver  # noqa: E402
from folio_post import carddav, cfb, merge, mime, msgfile, rss, store as S, sync, vcard, voting  # noqa: E402

FAILS = []


def check(cond, what):
    print(("ok   " if cond else "FAIL ") + what)
    sys.stdout.flush()
    if not cond:
        FAILS.append(what)


root = tempfile.mkdtemp()
st = S.Store(root)

# ---------------------------------------------------------------- voting buttons
ch = voting.parse_choices("Approve; Reject ;")
check(ch == ["Approve", "Reject"], "choices from Approve;Reject")
t, h = voting.footer(ch, "me@example.org", "Budget 2027")
check("Vote: Approve | Reject" in t and "mailto:me@example.org?subject=Approve%3A%20Budget%202027" in h, "a vote line with reply links")
check(voting.vote_of("approve: Budget 2027", ch) == "Approve" and voting.vote_of("RE: Budget", ch) is None, "a vote read from a reply")
orig = mime.build(("Me", "me@example.org"), [("Ann", "ann@example.org")], (), (), "Budget 2027", "Please vote", None, (), (),
                  extra={voting.HEADER: "Approve;Reject"})
check(voting.choices_of(orig) == ["Approve", "Reject"], "the choices travel with the message")
acc = {"name": "Ann", "email": "ann@example.org"}
resp = voting.build_response(acc, orig, "Reject")
check(mime.header(resp, "Subject") == "Reject: Budget 2027" and mime.header(resp, "In-Reply-To") == mime.header(orig, "Message-ID")
      and mime.header(resp, voting.VOTE_HEADER) == "Reject", "the vote is a reply to the message")
aid = st.add_account("Me", "me@example.org", "local", {})
sent = st.folder_by_role(aid, "sent")
inbox = st.folder_by_role(aid, "inbox")
smid = st.add_message(sent["id"], mime.to_bytes(orig), 0, ["seen"])
for who, c in (("ann", "Reject"), ("bob", "Approve"), ("cy", "Approve"), ("ann", "Approve")):
    r = voting.build_response({"name": who.capitalize(), "email": who + "@example.org"}, orig, c)
    st.add_message(inbox["id"], mime.to_bytes(r), 0, [])
other = mime.build(("Dee", "dee@example.org"), [("Me", "me@example.org")], (), (), "Re: Budget 2027", "Looks fine", None, (), (),
                   in_reply_to=mime.header(orig, "Message-ID"))
st.add_message(inbox["id"], mime.to_bytes(other), 0, [])
counts, rows = voting.tally(st, st.message(smid), ch)
check(sorted(counts["Approve"]) == ["Ann", "Bob", "Cy"] and counts["Reject"] == [], "the tally: Ann's last answer counts (%s)" % counts)
check(len(rows) == 3, "an ordinary reply isn't a vote")

# ---------------------------------------------------------------- Outlook templates
fields = {"subject": "Weekly report", "to": [("Ann Lee", "ann@example.org")], "cc": [("", "team@example.org")], "bcc": [],
          "text": "Hello,\n\nThis week:", "html": "<html><body><p>Hello,</p><p><b>This week:</b></p></body></html>",
          "attachments": [("notes.txt", "text/plain", b"attached notes\n")], "importance": 2}
data = msgfile.write(fields, template=True)
check(data[:8] == cfb.SIG, "an .oft is a compound file")
streams = cfb.read(data)
check("__substg1.0_0037001F" in streams and "__recip_version1.0_#00000000/__substg1.0_39FE001F" in streams and
      "__attach_version1.0_#00000000/__substg1.0_37010102" in streams and "__nameid_version1.0/__substg1.0_00020102" in streams,
      "with Outlook's streams for subject, recipients, attachment and named properties")
try:
    import olefile
    ole = olefile.OleFileIO(data)
    check(ole.exists("__properties_version1.0") and
          ole.openstream("__substg1.0_0037001F").read().decode("utf-16-le").rstrip("\0") == "Weekly report",
          "another reader (olefile) reads it")
except ImportError:
    pass
back = msgfile.read(data)
check(back["subject"] == "Weekly report" and back["to"] == [("Ann Lee", "ann@example.org")] and back["cc"] == [("team@example.org", "team@example.org")],
      "read back: subject and recipients")
check("<b>This week:</b>" in back["html"] and back["text"].startswith("Hello") and back["importance"] == 2 and
      back["attachments"] == [("notes.txt", "text/plain", b"attached notes\n")] and back["message_class"] == "IPM.Note",
      "read back: body, importance and attachment")
eml = msgfile.to_eml(msgfile.write(fields, template=False))
m = mime.parse(eml)
check(mime.header(m, "Subject") == "Weekly report" and mime.attachments(m)[0]["name"] == "notes.txt", "a .msg opens as a message")
# compressed RTF ([MS-OXRTFCP] 3.1.1 example)
comp = bytes.fromhex("2d0000002b0000004c5a4675f1c5c7a703000a007263706731323542320af32068656c090020627705b06c647d0a800fa0")
check(msgfile.lzfu(comp) == b"{\\rtf1\\ansi\\ansicpg1252\\pard hello world}\r\n", "compressed RTF (MS-OXRTFCP example)")
enc = (b"{\\rtf1\\ansi\\fromhtml1 {\\*\\htmltag1 <html>}{\\*\\htmltag <body>}\\htmlrtf {\\b\\htmlrtf0 "
       b"{\\*\\htmltag <b>}Hi{\\*\\htmltag </b>}\\htmlrtf }\\htmlrtf0 {\\*\\htmltag </body></html>}}")
check(msgfile.html_from_rtf(enc).replace(" ", "") .startswith("<html><body><b>Hi</b></body></html>"),
      "HTML kept inside RTF comes back (%r)" % msgfile.html_from_rtf(enc))

# ---------------------------------------------------------------- RSS
FEEDS = {
    "/news.xml": b"""<?xml version="1.0"?><rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/"><channel>
<title>Folio News</title><link>http://example.org/</link>
<item><title>First post</title><link>/posts/1</link><guid>p1</guid><pubDate>Mon, 26 Oct 2026 10:00:00 GMT</pubDate>
<description>&lt;p&gt;Hello &lt;b&gt;world&lt;/b&gt;&lt;/p&gt;</description></item>
</channel></rss>""",
    "/atom.xml": b"""<?xml version="1.0" encoding="utf-8"?><feed xmlns="http://www.w3.org/2005/Atom"><title>Atom Diary</title>
<link href="http://example.org/"/><updated>2026-10-27T09:00:00Z</updated>
<entry><title>Day one</title><id>urn:d1</id><updated>2026-10-27T09:00:00Z</updated><link href="http://example.org/d1"/>
<author><name>Kim</name></author><content type="html">&lt;p&gt;It began.&lt;/p&gt;</content></entry></feed>""",
}
hits = []


class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        hits.append((self.path, self.headers.get("If-None-Match")))
        body = FEEDS.get(self.path)
        if body is None:
            self.send_response(404)
            self.end_headers()
            return
        et = '"%d"' % hash(body)
        if self.headers.get("If-None-Match") == et:
            self.send_response(304)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/rss+xml")
        self.send_header("ETag", et)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


hs = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=hs.serve_forever, daemon=True).start()
base = "http://127.0.0.1:%d" % hs.server_address[1]
fd = rss.Feeds(st)
fid, n = fd.add(base + "/news.xml")
check(n == 1 and st.folder(fid)["name"] == "Folio News", "subscribed: a folder named after the feed, with its article")
msgs = st.messages(fid)
raw = st.raw(msgs[0]["id"])
pm = mime.parse(raw)
check(msgs[0]["subject"] == "First post" and "<b>world</b>" in mime.body_part(pm, "html") and
      base + "/posts/1" in mime.body_part(pm, "html"), "the article as a message, with a link to it")
fid2, n2 = fd.add("feed:" + base + "/atom.xml")
check(n2 == 1 and st.messages(fid2)[0]["subject"] == "Day one" and st.messages(fid2)[0]["from_name"] == "Kim", "an Atom feed too")
try:
    fd.add(base + "/news.xml")
    check(False, "subscribing twice is refused")
except ValueError:
    check(True, "subscribing twice is refused")
hits.clear()
check(fd.refresh() == 0 and all(h[1] for h in hits), "unchanged feeds: asked with their ETag, nothing new")
FEEDS["/news.xml"] = FEEDS["/news.xml"].replace(b"<item>", b"<item><title>Second post</title><link>/posts/2</link><guid>p2</guid>"
                                                 b"<description>Two</description></item><item>", 1)
check(fd.refresh() == 1 and len(st.messages(fid)) == 2, "a new article arrives with Send/Receive")
rid = fd.account(create=False)
check(st.account(rid)["kind"] == "rss" and not st.folder_by_role(rid, "outbox"), "the RSS Feeds account has only feed folders")
sy0 = sync.Syncer(st, sync.Secrets(os.path.join(root, "s0.json")))
check(sy0.sync_account(rid), "Send/Receive updates the feeds")
fd.remove(base + "/atom.xml")
check(st.folder(fid2) is None and len(fd.feeds()) == 1, "unsubscribed")
hs.shutdown()

# ---------------------------------------------------------------- mail merge
book = st.add_book("Contacts", "local")
for name, email_, co, ph in (("Ann Lee", "ann@example.org", "Contoso", "+31 6 1"), ("Bob Kelly", "bob@example.org", "", "")):
    carddav.save_contact(st, book, vcard.new_contact(name, email_, co, ph))
carddav.save_contact(st, book, vcard.new_group("Team", ["ann@example.org"]))
lc = merge.list_contacts(st)
ann = [x for x in lc if x["name"] == "Ann Lee"][0]
check(ann == {"name": "Ann Lee", "email": "ann@example.org", "company": "Contoso", "phone": "+31 6 1", "groups": ["Team"]},
      "--list-contacts: name, email, company, phone and groups")
check(any(x["name"] == "Team" and x.get("is_group") and x["members"] == ["ann@example.org"] for x in lc), "and the groups themselves")
env = dict(os.environ, FOLIO_POST_DATA=root, PYTHONPATH=os.path.join(HERE, "..", "app"))
out = subprocess.run([sys.executable, "-m", "folio_post", "--list-contacts", "--json"], env=env, capture_output=True, text=True,
                     timeout=60)
try:
    parsed = json.loads(out.stdout)
except ValueError:
    parsed = None
check(out.returncode == 0 and parsed and any(x["email"] == "bob@example.org" for x in parsed), "folio-post --list-contacts --json, no window")

world = mailserver.World()
world.add_user("me@example.org", "secret")
for u in ("ann@example.org", "bob@example.org"):
    world.add_user(u, "pw")
_w, ip, sp, stop = mailserver.start(world)
cfg = {"imap_host": "127.0.0.1", "imap_port": ip, "imap_security": "none", "smtp_host": "127.0.0.1", "smtp_port": sp,
       "smtp_security": "none", "user": "me@example.org"}
mroot = tempfile.mkdtemp()
ms = S.Store(mroot)
msec = sync.Secrets(os.path.join(mroot, "secrets.json"))
maid = ms.add_account("Me", "me@example.org", "imap", cfg)
msec.set(maid, "secret")
sy = sync.Syncer(ms, msec)
sy.sync_account(maid)
att = os.path.join(mroot, "letter.pdf")
open(att, "wb").write(b"%PDF-1.4 letter")
job = {"subject": "Your invitation", "format": "html", "messages": [
    {"to": "Ann Lee <ann@example.org>", "html": "<p>Dear Ann,</p>"},
    {"to": "bob@example.org", "subject": "For Bob", "html": "<p>Dear Bob,</p>", "attachments": [att]},
    {"to": "", "html": "<p>Nobody</p>"}]}
acc, accs = merge.pick_account(ms, job)
check(acc["id"] == maid, "the sending account")
res = merge.run(ms, sy, job, acc)
check(res["sent"] == 2 and res["failed"] == [{"to": "", "error": "no recipient"}], "merge: two sent, the empty one reported")
anns = [m[3] for m in world.users["ann@example.org"][1]["INBOX"].msgs]
bobs = [m[3] for m in world.users["bob@example.org"][1]["INBOX"].msgs]
check(any(b"Your invitation" in x and b"Dear Ann" in x for x in anns), "Ann gets her letter")
check(any(b"For Bob" in x and b"letter.pdf" in x for x in bobs), "Bob his, with the attachment")
srv_sent = [m[3] for m in world.users["me@example.org"][1]["Sent"].msgs]
check(sum(1 for x in srv_sent if b"Dear" in x) == 2, "copies filed in Sent Items on the server")
jf = os.path.join(mroot, "job.json")
json.dump({"subject": "CLI", "messages": [{"to": "ann@example.org", "text": "From the command line"}]}, open(jf, "w"))
if os.environ.get("DISPLAY"):
    env2 = dict(os.environ, FOLIO_POST_DATA=mroot, XDG_CONFIG_HOME=mroot, FOLIO_POST_MERGE_AUTOSEND="1",
                PYTHONPATH=os.path.join(HERE, "..", "app"))
    import shutil
    os.makedirs(os.path.join(mroot, "folio-post"), exist_ok=True)
    shutil.copy(os.path.join(mroot, "secrets.json"), os.path.join(mroot, "folio-post", "secrets.json"))
    out = subprocess.run([sys.executable, "-m", "folio_post", "--send-merge", jf, "--json"], env=env2, capture_output=True,
                         text=True, timeout=120)
    try:
        r = json.loads(out.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        r = None
    check(out.returncode == 0 and r == {"sent": 1, "failed": []}, "folio-post --send-merge FILE --json (%s %s)" % (out.returncode, out.stdout[-200:]))
    check(any(b"From the command line" in m[3] for m in world.users["ann@example.org"][1]["INBOX"].msgs), "and it arrived")
stop()
print("B3b tests: %s" % ("all passed" if not FAILS else "%d FAILED" % len(FAILS)))
sys.exit(1 if FAILS else 0)
