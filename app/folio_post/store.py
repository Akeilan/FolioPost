"""The local mail store: accounts, folders and messages in SQLite (with a full-text index for
search), each message's raw form in a file of its own. Everything works offline from here;
syncing fills and follows it."""
import json
import os
import sqlite3
import threading
import time

SCHEMA = """
create table if not exists accounts (
  id integer primary key, name text, email text, kind text, config text, position integer default 0);
create table if not exists folders (
  id integer primary key, account integer, path text, name text, role text default '', parent text default '',
  uidvalidity integer default 0, uidnext integer default 0, delim text default '/', subscribed integer default 1,
  unique(account, path));
create table if not exists messages (
  id integer primary key, folder integer, uid integer default 0, msgid text default '', thread text default '',
  in_reply_to text default '', refs text default '', subject text default '', from_name text default '',
  from_addr text default '', to_text text default '', cc_text text default '', date integer default 0,
  size integer default 0, seen integer default 0, flagged integer default 0, answered integer default 0,
  forwarded integer default 0, draft integer default 0, deleted integer default 0, attach integer default 0,
  categories text default '', snippet text default '', importance integer default 1, due integer default 0,
  done integer default 0, file text default '', pending text default '');
create index if not exists msg_folder on messages(folder, date);
create index if not exists msg_uid on messages(folder, uid);
create index if not exists msg_thread on messages(thread);
create table if not exists outbox (
  id integer primary key, account integer, raw blob, rcpts text, created integer, tries integer default 0,
  error text default '', send_at integer default 0);
create table if not exists kv (k text primary key, v text);
"""

FTS = "create virtual table if not exists msgfts using fts5(subject, sender, recipients, body, content='', tokenize='unicode61')"

ROLE_NAMES = {"inbox": "Inbox", "drafts": "Drafts", "sent": "Sent Items", "trash": "Deleted Items", "junk": "Junk Email",
              "archive": "Archive", "outbox": "Outbox"}
ROLE_ORDER = ["inbox", "drafts", "sent", "trash", "archive", "junk", "outbox"]


def norm_subject(s):
    s = (s or "").strip()
    while True:
        low = s.lower()
        for p in ("re:", "fw:", "fwd:", "aw:", "sv:", "wg:"):
            if low.startswith(p):
                s = s[len(p):].strip()
                break
        else:
            return s


class Store:
    def __init__(self, root):
        self.root = root
        os.makedirs(os.path.join(root, "mail"), exist_ok=True)
        self.db = sqlite3.connect(os.path.join(root, "store.db"), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        with self.lock:
            self.db.executescript(SCHEMA)
            try:
                self.db.execute(FTS)
                self.fts = True
            except sqlite3.OperationalError:
                self.fts = False
            self.db.commit()
        self.listeners = []
        self.version = 0

    def changed(self, what="messages", folder=None):
        self.version += 1
        for f in list(self.listeners):
            try:
                f(what, folder)
            except Exception:
                pass

    def q(self, sql, args=()):
        with self.lock:
            return self.db.execute(sql, args).fetchall()

    def x(self, sql, args=()):
        with self.lock:
            c = self.db.execute(sql, args)
            self.db.commit()
            return c.lastrowid

    # ------------------------------------------------------------ settings
    def get(self, k, default=None):
        r = self.q("select v from kv where k=?", (k,))
        return json.loads(r[0]["v"]) if r else default

    def put(self, k, v):
        self.x("insert or replace into kv(k, v) values(?, ?)", (k, json.dumps(v)))

    # ------------------------------------------------------------ accounts
    def add_account(self, name, email, kind, config):
        pos = (self.q("select max(position) m from accounts")[0]["m"] or 0) + 1
        aid = self.x("insert into accounts(name, email, kind, config, position) values(?,?,?,?,?)",
                     (name, email, kind, json.dumps(config), pos))
        if kind == "local":
            for role in ROLE_ORDER:
                self.ensure_folder(aid, ROLE_NAMES[role], role)
        else:
            self.ensure_folder(aid, "Outbox", "outbox")
        self.changed("accounts")
        return aid

    def accounts(self):
        out = []
        for r in self.q("select * from accounts order by position, id"):
            d = dict(r)
            d["config"] = json.loads(d["config"] or "{}")
            out.append(d)
        return out

    def account(self, aid):
        for a in self.accounts():
            if a["id"] == aid:
                return a
        return None

    def update_account(self, aid, **kw):
        a = self.account(aid)
        if a is None:
            return
        cfg = dict(a["config"])
        cfg.update(kw.pop("config", {}))
        self.x("update accounts set name=?, email=?, config=? where id=?",
               (kw.get("name", a["name"]), kw.get("email", a["email"]), json.dumps(cfg), aid))
        self.changed("accounts")

    def remove_account(self, aid):
        for f in self.folders(aid):
            self.drop_folder(f["id"])
        self.x("delete from accounts where id=?", (aid,))
        self.x("delete from outbox where account=?", (aid,))
        self.changed("accounts")

    # ------------------------------------------------------------ folders
    def ensure_folder(self, aid, path, role="", delim="/"):
        r = self.q("select id from folders where account=? and path=?", (aid, path))
        if r:
            if role:
                self.x("update folders set role=? where id=?", (role, r[0]["id"]))
            return r[0]["id"]
        name = path.split(delim)[-1] if delim else path
        parent = delim.join(path.split(delim)[:-1]) if delim and delim in path else ""
        fid = self.x("insert into folders(account, path, name, role, parent, delim) values(?,?,?,?,?,?)",
                     (aid, path, name, role, parent, delim))
        self.changed("folders")
        return fid

    def folders(self, aid=None):
        rows = self.q("select * from folders" + (" where account=?" if aid is not None else "") + " order by path",
                      (aid,) if aid is not None else ())
        out = [dict(r) for r in rows]
        # the well-known folders first, in Outlook's order
        out.sort(key=lambda f: (f["account"], ROLE_ORDER.index(f["role"]) if f["role"] in ROLE_ORDER else 99, f["path"].lower()))
        return out

    def folder(self, fid):
        r = self.q("select * from folders where id=?", (fid,))
        return dict(r[0]) if r else None

    def folder_by_role(self, aid, role):
        r = self.q("select * from folders where account=? and role=?", (aid, role))
        return dict(r[0]) if r else None

    def rename_folder(self, fid, path, name):
        self.x("update folders set path=?, name=? where id=?", (path, name, fid))
        self.changed("folders")

    def drop_folder(self, fid):
        for r in self.q("select id, file from messages where folder=?", (fid,)):
            self._unlink(r["file"])
            self._unindex(r["id"])
        self.x("delete from messages where folder=?", (fid,))
        self.x("delete from folders where id=?", (fid,))
        self.changed("folders")

    def counts(self, fid):
        r = self.q("select count(*) n, sum(case when seen=0 then 1 else 0 end) u from messages where folder=? and deleted=0", (fid,))
        return (r[0]["n"] or 0, r[0]["u"] or 0)

    # ------------------------------------------------------------ messages
    def _path_for(self, fid, mid):
        d = os.path.join(self.root, "mail", str(fid))
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, "%d.eml" % mid)

    def _unlink(self, f):
        if f:
            try:
                os.remove(os.path.join(self.root, f))
            except OSError:
                pass

    def add_message(self, fid, raw, uid=0, flags=(), date=None, index=True):
        """Store a message (raw bytes); returns its id."""
        from . import mime
        h = mime.summary(raw)
        flags = set(f.lower().lstrip("\\") for f in flags)
        thread = h["thread"] or h["msgid"] or ("subj:" + norm_subject(h["subject"]).lower())
        mid = self.x("""insert into messages(folder, uid, msgid, thread, in_reply_to, refs, subject, from_name, from_addr,
                        to_text, cc_text, date, size, seen, flagged, answered, draft, deleted, attach, snippet, importance, forwarded)
                        values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                     (fid, uid, h["msgid"], thread, h["in_reply_to"], h["refs"], h["subject"], h["from_name"],
                      h["from_addr"], h["to"], h["cc"], int(date or h["date"] or time.time()), len(raw),
                      int("seen" in flags), int("flagged" in flags), int("answered" in flags), int("draft" in flags),
                      int("deleted" in flags), int(h["attach"]), h["snippet"], h["importance"], int("$forwarded" in flags)))
        path = self._path_for(fid, mid)
        with open(path, "wb") as fh:
            fh.write(raw)
        self.x("update messages set file=? where id=?", (os.path.relpath(path, self.root), mid))
        if index and self.fts:
            self.x("insert into msgfts(rowid, subject, sender, recipients, body) values(?,?,?,?,?)",
                   (mid, h["subject"], h["from_name"] + " " + h["from_addr"], h["to"] + " " + h["cc"], h["text"][:20000]))
        return mid

    def _unindex(self, mid):
        if not self.fts:
            return
        r = self.q("select subject, from_name, from_addr, to_text, cc_text, file from messages where id=?", (mid,))
        if not r:
            return
        # contentless fts: a delete needs the same values
        from . import mime
        body = ""
        try:
            with open(os.path.join(self.root, r[0]["file"]), "rb") as fh:
                body = mime.summary(fh.read())["text"][:20000]
        except OSError:
            pass
        try:
            self.x("insert into msgfts(msgfts, rowid, subject, sender, recipients, body) values('delete',?,?,?,?,?)",
                   (mid, r[0]["subject"], r[0]["from_name"] + " " + r[0]["from_addr"],
                    r[0]["to_text"] + " " + r[0]["cc_text"], body))
        except sqlite3.DatabaseError:
            pass

    def message(self, mid):
        r = self.q("select * from messages where id=?", (mid,))
        return dict(r[0]) if r else None

    def raw(self, mid):
        m = self.message(mid)
        if not m or not m["file"]:
            return b""
        try:
            with open(os.path.join(self.root, m["file"]), "rb") as fh:
                return fh.read()
        except OSError:
            return b""

    def messages(self, fid, order="date desc", where="", args=()):
        sql = "select * from messages where folder=? and deleted=0" + (" and " + where if where else "") + " order by " + order
        return [dict(r) for r in self.q(sql, (fid,) + tuple(args))]

    def by_uid(self, fid, uid):
        r = self.q("select * from messages where folder=? and uid=?", (fid, uid))
        return dict(r[0]) if r else None

    def uids(self, fid):
        return {r["uid"]: r["id"] for r in self.q("select id, uid from messages where folder=? and uid>0", (fid,))}

    FLAG_COLS = {"seen", "flagged", "answered", "draft", "deleted", "forwarded", "done"}

    def set_flag(self, ids, flag, on=True, pending=True):
        """Set a flag on messages; `pending` marks it for the next sync to send to the server."""
        if flag not in self.FLAG_COLS:
            return
        for mid in ids:
            m = self.message(mid)
            if m is None:
                continue
            p = set(filter(None, m["pending"].split(",")))
            if pending:
                p.add(("+" if on else "-") + flag)
                p.discard(("-" if on else "+") + flag)
            self.x("update messages set %s=?, pending=? where id=?" % flag, (int(on), ",".join(sorted(p)), mid))
        self.changed("flags")

    def clear_pending(self, mid):
        self.x("update messages set pending='' where id=?", (mid,))

    def set_fields(self, mid, **kw):
        cols = ", ".join("%s=?" % k for k in kw)
        self.x("update messages set %s where id=?" % cols, tuple(kw.values()) + (mid,))
        self.changed("flags")

    def move(self, ids, fid):
        """Move messages to another folder (locally; the sync moves them on the server)."""
        out = []
        for mid in ids:
            m = self.message(mid)
            if m is None or m["folder"] == fid:
                continue
            raw = self.raw(mid)
            flags = [f for f in ("seen", "flagged", "answered", "draft") if m[f]]
            new = self.add_message(fid, raw, 0, flags, m["date"])
            src, dst = self.folder(m["folder"]), self.folder(fid)
            same = src and dst and src["account"] == dst["account"]
            local_dst = dst and (self.account(dst["account"]) or {}).get("kind") in ("local", "pop3")
            pend = "" if local_dst else ("moved-from:%d:%d" % (m["folder"], m["uid"]) if (m["uid"] and same) else "new")
            self.set_fields(new, categories=m["categories"], due=m["due"], done=m["done"], pending=pend)
            if same or not m["uid"]:
                self.delete(mid, hard=True)
            else:
                # from another account: removed from that server at its next sync
                self.delete(mid)
            out.append(new)
        self.changed("messages")
        return out

    def delete(self, mid, hard=False):
        m = self.message(mid)
        if m is None:
            return
        if not hard and m["uid"]:
            # removed on the server at the next sync
            self.x("update messages set deleted=1, pending='expunge' where id=?", (mid,))
        else:
            self._unindex(mid)
            self._unlink(m["file"])
            self.x("delete from messages where id=?", (mid,))
        self.changed("messages")

    def gone(self, fid):
        """Messages marked deleted locally, waiting for the sync."""
        return [dict(r) for r in self.q("select * from messages where folder=? and pending like '%expunge%'", (fid,))]

    def pending(self, fid):
        return [dict(r) for r in self.q("select * from messages where folder=? and pending!='' and pending not like '%expunge%'", (fid,))]

    # ------------------------------------------------------------ search
    def search(self, text, fids=None, limit=500):
        """Messages matching words (subject, people, body); newest first."""
        text = (text or "").strip()
        if not text:
            return []
        where = ""
        args = []
        if fids:
            where = " and m.folder in (%s)" % ",".join("?" * len(fids))
            args = list(fids)
        if self.fts:
            words = [w.replace('"', "") for w in text.split() if w]
            fq = " ".join('"%s"*' % w for w in words)
            rows = self.q("select m.* from msgfts f join messages m on m.id=f.rowid where msgfts match ? and m.deleted=0%s "
                          "order by m.date desc limit %d" % (where, limit), [fq] + args)
        else:
            like = "%" + text + "%"
            rows = self.q("select * from messages m where m.deleted=0 and (subject like ? or from_name like ? or from_addr like ? "
                          "or to_text like ?)%s order by date desc limit %d" % (where, limit), [like] * 4 + args)
        return [dict(r) for r in rows]

    def conversation(self, thread):
        return [dict(r) for r in self.q("select * from messages where thread=? and deleted=0 order by date", (thread,))]

    # ------------------------------------------------------------ outbox
    def queue(self, aid, raw, rcpts, send_at=0):
        oid = self.x("insert into outbox(account, raw, rcpts, created, send_at) values(?,?,?,?,?)",
                     (aid, raw, json.dumps(rcpts), int(time.time()), int(send_at)))
        self.changed("outbox")
        return oid

    def outbox(self, aid=None):
        rows = self.q("select * from outbox" + (" where account=?" if aid else "") + " order by id", (aid,) if aid else ())
        return [dict(r) for r in rows]

    def sent(self, oid):
        self.x("delete from outbox where id=?", (oid,))
        self.changed("outbox")

    def send_failed(self, oid, error):
        self.x("update outbox set tries=tries+1, error=? where id=?", (str(error)[:500], oid))
        self.changed("outbox")
