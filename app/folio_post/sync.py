"""Keeping the local store and the server in step: folders, new mail, flags, moves and deletes
made here, drafts and sent mail, and the Outbox. Runs in a worker thread; the window hears
about changes through the store's listeners."""
import json
import os
import threading
import time
import traceback

from . import imap as net
from . import mime

# how much of a folder the first sync brings down
FIRST_SYNC = 1000


class Secrets:
    """Passwords and tokens: the desktop's keyring when it has one, else a private file."""

    def __init__(self, path):
        self.path = path
        self.secret = None
        try:
            import gi
            gi.require_version("Secret", "1")
            from gi.repository import Secret
            self.schema = Secret.Schema.new("org.folio.Post", Secret.SchemaFlags.NONE,
                                            {"account": Secret.SchemaAttributeType.STRING,
                                             "kind": Secret.SchemaAttributeType.STRING})
            self.secret = Secret
        except Exception:
            self.secret = None
        if os.environ.get("FOLIO_POST_FILE_SECRETS"):
            self.secret = None

    def _file(self):
        try:
            with open(self.path) as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return {}

    def get(self, account, kind="password"):
        if self.secret is not None:
            try:
                v = self.secret.password_lookup_sync(self.schema, {"account": str(account), "kind": kind}, None)
                if v is not None:
                    return v
            except Exception:
                pass
        return self._file().get("%s:%s" % (account, kind))

    def set(self, account, value, kind="password"):
        if self.secret is not None:
            try:
                self.secret.password_store_sync(self.schema, {"account": str(account), "kind": kind},
                                                self.secret.COLLECTION_DEFAULT, "Folio Post %s" % kind, value, None)
                return
            except Exception:
                pass
        d = self._file()
        d["%s:%s" % (account, kind)] = value
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w") as fh:
            os.chmod(tmp, 0o600)
            json.dump(d, fh)
        os.replace(tmp, self.path)


class Syncer:
    def __init__(self, store, secrets, oauth=None):
        self.store = store
        self.secrets = secrets
        self.oauth = oauth            # account -> access token (refreshing when needed)
        self.lock = threading.Lock()
        self.status = {}              # account id -> text
        self.errors = {}
        self.offline = False
        self.listeners = []

    def say(self, aid, text):
        self.status[aid] = text
        for f in list(self.listeners):
            try:
                f(aid, text)
            except Exception:
                pass

    def credentials(self, acc):
        cfg = acc["config"]
        if cfg.get("auth") in ("oauth", "goa") and self.oauth is not None:
            return None, self.oauth(acc)
        return self.secrets.get(acc["id"]) or cfg.get("password", ""), None

    # ------------------------------------------------------------ the whole account
    def sync_account(self, aid, folders=None):
        """Bring an account up to date: send the Outbox, push local changes, fetch new mail."""
        if self.offline:
            return False
        acc = self.store.account(aid)
        if acc is None or acc["kind"] == "local":
            return False
        with self.lock:
            try:
                self.say(aid, "Sending...")
                self.send_outbox(acc)
                if acc["kind"] == "pop3":
                    self.say(aid, "Receiving...")
                    self.pop_sync(acc)
                else:
                    self.say(aid, "Connecting...")
                    pw, tok = self.credentials(acc)
                    c = net.Imap(acc["config"]).connect(pw, tok)
                    try:
                        self.sync_folders(acc, c)
                        for f in self.store.folders(aid):
                            if f["role"] == "outbox" or (folders and f["id"] not in folders):
                                continue
                            self.say(aid, "Updating %s..." % f["name"])
                            self.sync_folder(acc, c, f)
                    finally:
                        c.close()
                self.errors.pop(aid, None)
                self.say(aid, "Updated %s" % time.strftime("%H:%M"))
                return True
            except net.AuthError as e:
                self.errors[aid] = "Sign-in failed: %s" % e
                self.say(aid, self.errors[aid])
            except Exception as e:
                traceback.print_exc()
                self.errors[aid] = "Couldn't connect: %s" % e
                self.say(aid, self.errors[aid])
            finally:
                self.store.changed("messages")
        return False

    def sync_folders(self, acc, c):
        have = {f["path"]: f for f in self.store.folders(acc["id"])}
        server = c.folders()
        names = set()
        for path, delim, role, _raw, virtual in server:
            names.add(path)
            if virtual and acc["config"].get("skip_virtual", True) and role not in ("inbox",):
                # Gmail's All Mail / Starred hold copies of everything
                continue
            fid = self.store.ensure_folder(acc["id"], path, role, delim)
            if path not in have:
                self.store.x("update folders set role=? where id=?", (role, fid))
        for path, f in have.items():
            if path not in names and f["role"] != "outbox" and f["uidvalidity"]:
                self.store.drop_folder(f["id"])

    def sync_folder(self, acc, c, f):
        uv, un, exists = c.select(f["path"])
        if f["uidvalidity"] and f["uidvalidity"] != uv:
            # the server renumbered the folder: start it again
            for r in self.store.q("select id from messages where folder=?", (f["id"],)):
                self.store.delete(r["id"], hard=True)
        self.store.x("update folders set uidvalidity=?, uidnext=? where id=?", (uv, un, f["id"]))
        # changes made here first
        self.push_changes(acc, c, f)
        local = self.store.uids(f["id"])
        server = c.all_uids()
        sset = set(server)
        # gone from the server
        for uid, mid in local.items():
            if uid not in sset:
                self.store.delete(mid, hard=True)
        # new on the server
        new = [u for u in server if u not in local]
        if not local and len(new) > FIRST_SYNC:
            new = new[-FIRST_SYNC:]
        for chunk in _chunks(new, 50):
            for uid, flags, when, raw in c.fetch(chunk):
                if self.store.by_uid(f["id"], uid):
                    continue
                self.store.add_message(f["id"], raw, uid, flags, when or None)
            self.store.changed("messages", f["id"])
        # flags changed elsewhere
        known = [u for u in server if u in local]
        if known:
            fl = c.flags(known[-2000:])
            for uid, flags in fl.items():
                mid = local.get(uid)
                m = self.store.message(mid) if mid else None
                if m is None or m["pending"]:
                    continue
                want = {"seen": "\\seen" in flags, "flagged": "\\flagged" in flags, "answered": "\\answered" in flags,
                        "draft": "\\draft" in flags, "forwarded": "$forwarded" in flags}
                diff = {k: int(v) for k, v in want.items() if m[k] != int(v)}
                if diff:
                    self.store.set_fields(mid, **diff)

    def push_changes(self, acc, c, f):
        flagmap = {"seen": "\\Seen", "flagged": "\\Flagged", "answered": "\\Answered", "draft": "\\Draft",
                   "forwarded": "$Forwarded"}
        folders = {x["id"]: x for x in self.store.folders(acc["id"])}
        for m in self.store.pending(f["id"]):
            p = m["pending"]
            if p == "new" or p.startswith("moved-from:"):
                # a message moved or saved here: onto the server, then away from where it was
                uid = c.append(f["path"], self.store.raw(m["id"]),
                               [flagmap[k] for k in ("seen", "flagged", "answered", "draft") if m[k]])
                if p.startswith("moved-from:"):
                    _x, src, suid = p.split(":")
                    sf = folders.get(int(src))
                    if sf is not None and int(suid):
                        c.select(sf["path"])
                        c.store([int(suid)], ["\\Deleted"])
                        c.expunge([int(suid)])
                        c.select(f["path"])
                self.store.x("update messages set uid=?, pending='' where id=?", (uid or 0, m["id"]))
                if not uid:
                    # no APPENDUID: the next sync brings it back with its uid
                    self.store.delete(m["id"], hard=True)
                continue
            if m["uid"]:
                for item in p.split(","):
                    if len(item) > 1 and item[1:] in flagmap:
                        c.store([m["uid"]], [flagmap[item[1:]]], add=item[0] == "+")
            self.store.clear_pending(m["id"])
        gone = self.store.gone(f["id"])
        if gone:
            uids = [m["uid"] for m in gone if m["uid"]]
            c.store(uids, ["\\Deleted"])
            c.expunge(uids)
            for m in gone:
                self.store.delete(m["id"], hard=True)

    # ------------------------------------------------------------ sending
    def send_outbox(self, acc):
        for o in self.store.outbox(acc["id"]):
            if o["send_at"] and o["send_at"] > time.time():
                continue
            raw = o["raw"]
            rcpts = json.loads(o["rcpts"])
            try:
                pw, tok = self.credentials(acc)
                sender = acc["email"]
                net.send(acc["config"], mime.without_bcc(raw), sender, rcpts, pw, tok)
            except Exception as e:
                self.store.send_failed(o["id"], e)
                raise
            self.store.sent(o["id"])
            self.after_sent(acc, raw)

    def after_sent(self, acc, raw):
        """A copy in Sent Items (servers like Gmail keep their own)."""
        sent = self.store.folder_by_role(acc["id"], "sent")
        if sent is None:
            return
        if acc["config"].get("server_saves_sent"):
            return
        mid = self.store.add_message(sent["id"], raw, 0, ["seen"])
        self.store.set_fields(mid, pending="new")

    # ------------------------------------------------------------ POP3
    def pop_sync(self, acc):
        inbox = self.store.folder_by_role(acc["id"], "inbox")
        if inbox is None:
            inbox = {"id": self.store.ensure_folder(acc["id"], "Inbox", "inbox")}
            for role in ("drafts", "sent", "trash", "junk"):
                self.store.ensure_folder(acc["id"], {"drafts": "Drafts", "sent": "Sent Items", "trash": "Deleted Items",
                                                     "junk": "Junk Email"}[role], role)
        seen = set(self.store.get("pop-seen:%d" % acc["id"], []))
        pw, _tok = self.credentials(acc)
        p = net.Pop(acc["config"]).connect(pw)
        try:
            for uid, n in p.uidls().items():
                if uid in seen:
                    continue
                raw = p.retr(n)
                self.store.add_message(inbox["id"], raw, 0, [])
                seen.add(uid)
                if not acc["config"].get("leave_on_server", True):
                    p.dele(n)
        finally:
            p.close()
        self.store.put("pop-seen:%d" % acc["id"], sorted(seen))

    # ------------------------------------------------------------ folders on the server
    def server_op(self, aid, fn):
        acc = self.store.account(aid)
        if acc is None or acc["kind"] != "imap" or self.offline:
            return None
        pw, tok = self.credentials(acc)
        with self.lock:
            c = net.Imap(acc["config"]).connect(pw, tok)
            try:
                return fn(c)
            finally:
                c.close()

    def test_account(self, cfg, password=None, token=None, kind="imap"):
        """Sign in once to check an account's settings; '' when it works, else the problem."""
        try:
            if kind == "pop3":
                net.Pop(cfg).connect(password).close()
            else:
                c = net.Imap(cfg).connect(password, token)
                c.folders()
                c.close()
            return ""
        except net.AuthError as e:
            return "The server didn't accept the sign-in: %s" % e
        except Exception as e:
            return "Couldn't reach the server: %s" % e


def _chunks(xs, n):
    xs = list(xs)
    for i in range(0, len(xs), n):
        yield xs[i:i + n]
