"""Engine tests: the store, MIME, safe HTML, IMAP/SMTP sync against the test server."""
import os
import urllib.parse
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "app"))
sys.path.insert(0, HERE)
os.environ["FOLIO_POST_FILE_SECRETS"] = "1"

import mailserver  # noqa: E402
from folio_post import mime, store as S, sync  # noqa: E402

FAILS = []


def check(cond, what):
    print(("ok   " if cond else "FAIL ") + what)
    if not cond:
        FAILS.append(what)


world = mailserver.World()
boxes = world.add_user("me@example.org", "secret")
world.add_user("bob@example.org", "pw")
for i in range(12):
    boxes["INBOX"].add(mailserver.sample(i, html=i % 3 == 0, attach=i == 4), ["\\Seen"] if i > 5 else [])
_w, ip, sp, stop = mailserver.start(world)

root = tempfile.mkdtemp()
st = S.Store(root)
sec = sync.Secrets(os.path.join(root, "secrets.json"))
cfg = {"imap_host": "127.0.0.1", "imap_port": ip, "imap_security": "none", "smtp_host": "127.0.0.1", "smtp_port": sp,
       "smtp_security": "none", "user": "me@example.org"}
sy = sync.Syncer(st, sec)
check(sy.test_account(cfg, "secret") == "", "sign-in works")
check("didn't accept" in sy.test_account(cfg, "wrong"), "a wrong password is reported")
aid = st.add_account("Me", "me@example.org", "imap", cfg)
sec.set(aid, "secret")
check(sy.sync_account(aid), "first sync")
inbox = st.folder_by_role(aid, "inbox")
check(inbox is not None and st.folder_by_role(aid, "sent") and st.folder_by_role(aid, "trash"), "folders and their roles")
msgs = st.messages(inbox["id"])
check(len(msgs) == 12 and msgs[0]["subject"] == "Message 0", "12 messages, newest first")
n, unread = st.counts(inbox["id"])
check(unread == 6, "unread count: %d" % unread)
m4 = [m for m in msgs if m["subject"] == "Message 4"][0]
check(m4["attach"] == 1, "attachment noticed")
att = mime.attachments(mime.parse(st.raw(m4["id"])))
check(att and att[0]["name"] == "notes.txt" and att[0]["data"] == b"attached notes\n", "attachment read")
# flags up
st.set_flag([msgs[0]["id"]], "seen", True)
st.set_flag([msgs[1]["id"]], "flagged", True)
sy.sync_account(aid)
srv = {m[0]: m[1] for m in boxes["INBOX"].msgs}
uid0 = st.message(msgs[0]["id"])["uid"]
check("\\Seen" in srv[uid0], "read state sent to the server")
check("\\Flagged" in srv[st.message(msgs[1]["id"])["uid"]], "flag sent to the server")
# flags down
for m in boxes["INBOX"].msgs:
    if m[0] == uid0:
        m[1].discard("\\Seen")
sy.sync_account(aid)
check(st.message(msgs[0]["id"])["seen"] == 0, "read state from the server")
# new mail arrives
boxes["INBOX"].add(mailserver.sample(99, subject="Fresh news", when=time.time() + 60))
sy.sync_account(aid)
check(st.messages(inbox["id"])[0]["subject"] == "Fresh news", "new mail")
# move to Archive
arch = st.folder_by_role(aid, "archive")
fresh = st.messages(inbox["id"])[0]
st.move([fresh["id"]], arch["id"])
sy.sync_account(aid)
check(any(b"Fresh news" in m[3] for m in boxes["Archive"].msgs) and not any(b"Fresh news" in m[3] for m in boxes["INBOX"].msgs),
      "moved on the server")
am = st.messages(arch["id"])
check(len(am) == 1 and am[0]["uid"] > 0, "the moved message has its new uid: %s" % [(x["uid"], x["pending"]) for x in am])
# delete
victim = st.messages(inbox["id"])[-1]
st.delete(victim["id"])
sy.sync_account(aid)
check(len(boxes["INBOX"].msgs) == 11, "deleted on the server")
# send
msg = mime.build(("Me", "me@example.org"), [("Bob", "bob@example.org")], cc=["me@example.org"], subject="Hi Bob",
                 text="Plain", html_body="<p>Hello <b>Bob</b></p>", attachments=[("a.txt", "text/plain", b"x")])
raw = mime.to_bytes(msg)
st.queue(aid, raw, mime.recipients(msg))
sy.sync_account(aid)
check(len(world.smtp_log) == 1 and world.smtp_log[0][1] == ["bob@example.org", "me@example.org"], "sent through SMTP")
check(any(b"Hi Bob" in m[3] for m in world.users["bob@example.org"][1]["INBOX"].msgs), "delivered")
check(any(b"Hi Bob" in m[3] for m in boxes["Sent"].msgs), "a copy in Sent on the server")
sy.sync_account(aid)
check(st.messages(inbox["id"])[0]["subject"] == "Hi Bob", "the copy sent to myself arrives")
check(not st.outbox(aid), "the Outbox is empty")
# search
hits = st.search("fresh")
check(len(hits) == 1 and hits[0]["subject"] == "Fresh news", "search finds words")
hits = st.search("Ann")
check(len(hits) >= 10, "search finds people: %d" % len(hits))
# mime round trip
p = mime.parse(raw)
check(mime.body_part(p, "html").strip().startswith("<p>Hello") and mime.text_of(p).strip() == "Plain", "HTML and text bodies")
check(mime.without_bcc(raw).count(b"Bcc") == 0, "Bcc removed before sending")
# folders on the server
sy.server_op(aid, lambda c: c.create("Projects"))
sy.sync_account(aid)
check(any(f["path"] == "Projects" for f in st.folders(aid)), "new folder")
# POP3 isn't in the test server; local folders
loc = st.add_account("On My Computer", "", "local", {})
check(len(st.folders(loc)) == 7, "local folders")
stop()
from folio_post import oauth as OA
u = OA.auth_url("cid", "http://127.0.0.1:1/", "chal", "st", "me@outlook.com", "microsoft")
check(u.startswith(OA.MS_AUTH) and "IMAP.AccessAsUser.All" in urllib.parse.unquote(u) and "offline_access" in u, "Outlook.com sign-in address")
g = OA.auth_url("cid", "http://127.0.0.1:1/", "chal", "st", "", "google")
check(g.startswith(OA.GOOGLE_AUTH) and "access_type=offline" in g, "Google sign-in address")
print("FAILED: %d" % len(FAILS) if FAILS else "all passed")
sys.exit(1 if FAILS else 0)
