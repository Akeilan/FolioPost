"""A small IMAP4rev1 and SMTP server for the tests: mailboxes in memory, enough of both
protocols for Folio Post's client (LOGIN / XOAUTH2, LIST, SELECT, UID SEARCH / FETCH / STORE /
COPY / MOVE / EXPUNGE, APPEND, CREATE / DELETE / RENAME; SMTP with AUTH). Mail sent to a
local user lands in that user's INBOX."""
import base64
import re
import socketserver
import threading
import time
from email.utils import formatdate


class Mailbox:
    def __init__(self):
        self.msgs = []           # [uid, flags(set), internaldate, raw]
        self.uidnext = 1
        self.uidvalidity = int(time.time()) % 100000 + 1

    def add(self, raw, flags=()):
        uid = self.uidnext
        self.uidnext += 1
        when = time.time()
        m = re.search(rb"^Date: (.+?)\r?$", raw, re.M)
        if m:
            try:
                from email.utils import parsedate_to_datetime
                when = parsedate_to_datetime(m.group(1).decode()).timestamp()
            except Exception:
                pass
        self.msgs.append([uid, set(flags), when, raw])
        return uid


class World:
    """Users and their folders."""
    def __init__(self):
        self.users = {}          # user -> (password, {folder: Mailbox})
        self.lock = threading.RLock()
        self.smtp_log = []       # (from, [rcpts], raw)
        self.tokens = {"test-token": None}

    def add_user(self, user, password, folders=("INBOX", "Sent", "Drafts", "Trash", "Junk", "Archive")):
        self.users[user] = (password, {f: Mailbox() for f in folders})
        return self.users[user][1]

    def deliver(self, raw, rcpts):
        for r in rcpts:
            r = r.lower()
            if r in self.users:
                self.users[r][1]["INBOX"].add(raw)


SPECIAL = {"Sent": "\\Sent", "Drafts": "\\Drafts", "Trash": "\\Trash", "Junk": "\\Junk", "Archive": "\\Archive"}


def seqset(spec, uids):
    """The uids an IMAP sequence set names."""
    out = set()
    top = max(uids) if uids else 0
    for part in spec.split(","):
        if ":" in part:
            a, b = part.split(":")
            a = top if a == "*" else int(a)
            b = top if b == "*" else int(b)
            lo, hi = min(a, b), max(a, b)
            # n:* with n above every uid still means the last one
            out |= {u for u in uids if lo <= u <= hi}
            if part.endswith(":*") and not any(lo <= u for u in uids) and uids:
                out.add(top)
        else:
            u = top if part == "*" else int(part)
            if u in uids:
                out.add(u)
    return out


class ImapHandler(socketserver.StreamRequestHandler):
    def setup(self):
        socketserver.StreamRequestHandler.setup(self)
        self.world = self.server.world
        self.user = None
        self.box = None
        self.boxname = None

    def send(self, s):
        if isinstance(s, str):
            s = s.encode()
        self.wfile.write(s)

    def line(self, s):
        self.send(s + "\r\n")

    def read_line(self):
        """One command line with its literals ({n} then n bytes)."""
        data = self.rfile.readline()
        if not data:
            return None, []
        lits = []
        while True:
            m = re.search(rb"\{(\d+)\}\r\n$", data)
            if not m:
                break
            n = int(m.group(1))
            self.line("+ go ahead")
            self.wfile.flush()
            lit = self.rfile.read(n)
            lits.append(lit)
            data = data[:m.start()] + b"\x00LIT%d\x00" % (len(lits) - 1) + self.rfile.readline()
        return data.decode("utf-8", "replace").rstrip("\r\n"), lits

    def handle(self):
        self.line("* OK [CAPABILITY IMAP4rev1 AUTH=PLAIN AUTH=XOAUTH2 MOVE UIDPLUS] Folio test server ready")
        while True:
            try:
                ln, lits = self.read_line()
            except (ConnectionError, OSError):
                return
            if ln is None:
                return
            if not ln.strip():
                continue
            parts = ln.split(" ", 2)
            tag = parts[0]
            cmd = parts[1].upper() if len(parts) > 1 else ""
            arg = parts[2] if len(parts) > 2 else ""
            try:
                with self.world.lock:
                    if not self.dispatch(tag, cmd, arg, lits):
                        return
            except Exception as e:
                self.line("%s BAD %s" % (tag, e))
            self.wfile.flush()

    def args(self, s):
        """Split an argument string into words, quoted strings and literals."""
        out = []
        i = 0
        while i < len(s):
            c = s[i]
            if c == " ":
                i += 1
            elif c == '"':
                j = i + 1
                buf = ""
                while j < len(s) and s[j] != '"':
                    if s[j] == "\\":
                        j += 1
                    buf += s[j]
                    j += 1
                out.append(buf)
                i = j + 1
            elif c == "(":
                depth = 0
                j = i
                while j < len(s):
                    if s[j] == "(":
                        depth += 1
                    elif s[j] == ")":
                        depth -= 1
                        if depth == 0:
                            break
                    j += 1
                out.append(s[i:j + 1])
                i = j + 1
            else:
                j = s.find(" ", i)
                j = len(s) if j < 0 else j
                out.append(s[i:j])
                i = j
        return out

    def boxes(self):
        return self.world.users[self.user][1]

    def dispatch(self, tag, cmd, arg, lits):
        if cmd == "CAPABILITY":
            self.line("* CAPABILITY IMAP4rev1 AUTH=PLAIN AUTH=XOAUTH2 MOVE UIDPLUS")
        elif cmd == "NOOP":
            pass
        elif cmd == "LOGOUT":
            self.line("* BYE bye")
            self.line(tag + " OK LOGOUT done")
            return False
        elif cmd == "LOGIN":
            a = self.args(arg)
            u, p = a[0].lower(), a[1]
            if u in self.world.users and self.world.users[u][0] == p:
                self.user = u
            else:
                self.line(tag + " NO [AUTHENTICATIONFAILED] Invalid credentials")
                return True
        elif cmd == "AUTHENTICATE":
            mech = arg.split()[0].upper()
            self.line("+ ")
            self.wfile.flush()
            resp = base64.b64decode(self.rfile.readline().strip()).decode("utf-8", "replace")
            if mech == "XOAUTH2":
                m = re.match(r"user=([^\x01]*)\x01auth=Bearer ([^\x01]*)", resp)
                if m and m.group(2) in self.world.tokens and m.group(1).lower() in self.world.users:
                    self.user = m.group(1).lower()
                else:
                    self.line(tag + " NO [AUTHENTICATIONFAILED] bad token")
                    return True
            else:
                _z, u, p = (resp.split("\x00") + ["", "", ""])[:3]
                if u.lower() in self.world.users and self.world.users[u.lower()][0] == p:
                    self.user = u.lower()
                else:
                    self.line(tag + " NO [AUTHENTICATIONFAILED] no")
                    return True
        elif self.user is None:
            self.line(tag + " NO log in first")
            return True
        elif cmd == "LIST":
            for name in sorted(self.boxes()):
                flags = SPECIAL.get(name, "\\HasNoChildren")
                self.line('* LIST (%s) "/" "%s"' % (flags, name))
        elif cmd in ("SELECT", "EXAMINE"):
            name = self.args(arg)[0]
            if name.upper() == "INBOX":
                name = "INBOX"
            if name not in self.boxes():
                self.line(tag + " NO no such mailbox")
                return True
            self.box, self.boxname = self.boxes()[name], name
            self.line("* FLAGS (\\Answered \\Flagged \\Deleted \\Seen \\Draft)")
            self.line("* %d EXISTS" % len(self.box.msgs))
            self.line("* 0 RECENT")
            self.line("* OK [UIDVALIDITY %d] UIDs valid" % self.box.uidvalidity)
            self.line("* OK [UIDNEXT %d] next" % self.box.uidnext)
            self.line("%s OK [%s] %s done" % (tag, "READ-ONLY" if cmd == "EXAMINE" else "READ-WRITE", cmd))
            return True
        elif cmd == "STATUS":
            a = self.args(arg)
            b = self.boxes().get(a[0])
            if b is None:
                self.line(tag + " NO no such mailbox")
                return True
            unseen = sum(1 for m in b.msgs if "\\Seen" not in m[1])
            self.line('* STATUS "%s" (MESSAGES %d UIDNEXT %d UIDVALIDITY %d UNSEEN %d)' % (a[0], len(b.msgs), b.uidnext, b.uidvalidity, unseen))
        elif cmd == "CREATE":
            name = self.args(arg)[0]
            self.boxes().setdefault(name, Mailbox())
        elif cmd == "DELETE":
            self.boxes().pop(self.args(arg)[0], None)
        elif cmd == "RENAME":
            a = self.args(arg)
            if a[0] in self.boxes():
                self.boxes()[a[1]] = self.boxes().pop(a[0])
        elif cmd == "APPEND":
            a = self.args(arg)
            name = a[0]
            flags = []
            for w in a[1:]:
                if w.startswith("("):
                    flags = w.strip("()").split()
            raw = lits[-1] if lits else b""
            b = self.boxes().get(name)
            if b is None:
                self.line(tag + " NO [TRYCREATE] no such mailbox")
                return True
            uid = b.add(raw, flags)
            self.line("%s OK [APPENDUID %d %d] APPEND done" % (tag, b.uidvalidity, uid))
            return True
        elif cmd == "EXPUNGE":
            self.expunge(None)
        elif cmd == "UID":
            return self.uid(tag, arg)
        elif cmd == "CLOSE":
            self.box = None
        else:
            self.line(tag + " BAD unknown command")
            return True
        self.line("%s OK %s done" % (tag, cmd))
        return True

    def expunge(self, only):
        keep = []
        for k, m in enumerate(self.box.msgs):
            if "\\Deleted" in m[1] and (only is None or m[0] in only):
                self.line("* %d EXPUNGE" % (len(keep) + 1))
            else:
                keep.append(m)
        self.box.msgs = keep

    def uid(self, tag, arg):
        sub, _, rest = arg.partition(" ")
        sub = sub.upper()
        if self.box is None:
            self.line(tag + " NO select a mailbox first")
            return True
        uids = [m[0] for m in self.box.msgs]
        if sub == "SEARCH":
            r = rest.strip().upper()
            if r.startswith("UID "):
                found = sorted(seqset(r[4:].strip(), uids))
            else:
                found = uids
            self.line("* SEARCH" + "".join(" %d" % u for u in found))
        elif sub == "FETCH":
            spec, _, what = rest.partition(" ")
            want = seqset(spec, uids)
            what = what.upper()
            for k, m in enumerate(self.box.msgs):
                if m[0] not in want:
                    continue
                items = ["UID %d" % m[0]]
                if "FLAGS" in what:
                    items.append("FLAGS (%s)" % " ".join(sorted(m[1])))
                if "INTERNALDATE" in what:
                    d = time.strftime("%d-%b-%Y %H:%M:%S +0000", time.gmtime(m[2]))
                    items.append('INTERNALDATE "%s"' % d)
                if "RFC822.SIZE" in what:
                    items.append("RFC822.SIZE %d" % len(m[3]))
                body = None
                if "BODY.PEEK[]" in what or "BODY[]" in what or "RFC822)" in what:
                    body = m[3]
                    if "BODY[]" in what and "PEEK" not in what:
                        m[1].add("\\Seen")
                if body is not None:
                    self.send("* %d FETCH (%s BODY[] {%d}\r\n" % (k + 1, " ".join(items), len(body)))
                    self.send(body)
                    self.send(")\r\n")
                else:
                    self.line("* %d FETCH (%s)" % (k + 1, " ".join(items)))
        elif sub == "STORE":
            spec, how, flags = rest.split(" ", 2)
            fl = set(flags.strip("()").split())
            for m in self.box.msgs:
                if m[0] in seqset(spec, uids):
                    if how.upper().startswith("+"):
                        m[1] |= fl
                    elif how.upper().startswith("-"):
                        m[1] -= fl
                    else:
                        m[1] = set(fl)
        elif sub in ("COPY", "MOVE"):
            spec, _, dest = rest.partition(" ")
            dest = self.args(dest)[0]
            db = self.boxes().get(dest)
            if db is None:
                self.line(tag + " NO [TRYCREATE] no such mailbox")
                return True
            moved = []
            for m in list(self.box.msgs):
                if m[0] in seqset(spec, uids):
                    db.add(m[3], m[1] - {"\\Deleted"})
                    moved.append(m)
            if sub == "MOVE":
                for m in moved:
                    k = self.box.msgs.index(m)
                    self.line("* %d EXPUNGE" % (k + 1))
                    self.box.msgs.remove(m)
        elif sub == "EXPUNGE":
            self.expunge(seqset(rest.strip(), uids))
        else:
            self.line(tag + " BAD unknown UID command")
            return True
        self.line("%s OK UID %s done" % (tag, sub))
        return True


class SmtpHandler(socketserver.StreamRequestHandler):
    def line(self, s):
        self.wfile.write((s + "\r\n").encode())

    def handle(self):
        world = self.server.world
        self.line("220 folio test SMTP")
        frm, rcpts = None, []
        authed = False
        while True:
            ln = self.rfile.readline()
            if not ln:
                return
            s = ln.decode("utf-8", "replace").rstrip("\r\n")
            u = s.upper()
            if u.startswith(("EHLO", "HELO")):
                self.wfile.write(b"250-folio\r\n250-AUTH PLAIN LOGIN XOAUTH2\r\n250 8BITMIME\r\n")
            elif u.startswith("AUTH"):
                parts = s.split()
                mech = parts[1].upper()
                if mech == "PLAIN":
                    tok = parts[2] if len(parts) > 2 else None
                    if tok is None:
                        self.line("334 ")
                        self.wfile.flush()
                        tok = self.rfile.readline().strip().decode()
                    _z, user, pw = (base64.b64decode(tok).decode().split("\x00") + ["", ""])[:3]
                    ok = user.lower() in world.users and world.users[user.lower()][0] == pw
                elif mech == "LOGIN":
                    self.line("334 VXNlcm5hbWU6")
                    self.wfile.flush()
                    user = base64.b64decode(self.rfile.readline().strip()).decode()
                    self.line("334 UGFzc3dvcmQ6")
                    self.wfile.flush()
                    pw = base64.b64decode(self.rfile.readline().strip()).decode()
                    ok = user.lower() in world.users and world.users[user.lower()][0] == pw
                else:
                    resp = base64.b64decode(parts[2]).decode() if len(parts) > 2 else ""
                    ok = "auth=Bearer test-token" in resp
                authed = ok
                self.line("235 ok" if ok else "535 authentication failed")
            elif u.startswith("MAIL FROM"):
                if not authed:
                    self.line("530 authentication required")
                    continue
                frm = re.search(r"<([^>]*)>", s).group(1)
                rcpts = []
                self.line("250 ok")
            elif u.startswith("RCPT TO"):
                rcpts.append(re.search(r"<([^>]*)>", s).group(1))
                self.line("250 ok")
            elif u == "DATA":
                self.line("354 go")
                self.wfile.flush()
                lines = []
                while True:
                    d = self.rfile.readline()
                    if d in (b".\r\n", b".\n", b""):
                        break
                    if d.startswith(b".."):
                        d = d[1:]
                    lines.append(d)
                raw = b"".join(lines)
                with world.lock:
                    world.smtp_log.append((frm, list(rcpts), raw))
                    world.deliver(raw, rcpts)
                self.line("250 queued")
            elif u == "QUIT":
                self.line("221 bye")
                return
            elif u in ("RSET", "NOOP"):
                self.line("250 ok")
            else:
                self.line("502 not implemented")
            self.wfile.flush()


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def start(world=None, host="127.0.0.1"):
    """Start both servers on free ports: (world, imap port, smtp port, stop())."""
    world = world or World()
    imap = _Server((host, 0), ImapHandler)
    imap.world = world
    smtp = _Server((host, 0), SmtpHandler)
    smtp.world = world
    for s in (imap, smtp):
        threading.Thread(target=s.serve_forever, daemon=True).start()

    def stop():
        imap.shutdown()
        smtp.shutdown()
    return world, imap.server_address[1], smtp.server_address[1], stop


def sample(i, frm="Ann Lee <ann@example.org>", to="me@example.org", subject=None, html=False, attach=False, when=None):
    when = when or time.time() - 3600 * i
    subject = subject or "Message %d" % i
    if html:
        body = ("Content-Type: text/html; charset=utf-8\r\n\r\n<html><body><p>Hello <b>there</b>, message %d.</p>"
                "<p><img src=\"https://tracker.example/pixel.gif\" width=1 height=1>"
                "<img src=\"https://example.org/photo.png\" alt=\"Photo\"></p>"
                "<script>alert(1)</script><a href=\"javascript:evil()\">click</a> <a href=\"https://folio.example/\">site</a></body></html>\r\n" % i)
        head = ""
    else:
        body = "Content-Type: text/plain; charset=utf-8\r\n\r\nHello, this is message %d.\r\nSee https://folio.example/\r\n" % i
        head = ""
    msg = ("From: %s\r\nTo: %s\r\nSubject: %s\r\nDate: %s\r\nMessage-ID: <m%d.%d@example.org>\r\nMIME-Version: 1.0\r\n%s"
           % (frm, to, subject, formatdate(when, localtime=True), i, int(when), head))
    if attach:
        b = "BOUNDARY%d" % i
        msg += ('Content-Type: multipart/mixed; boundary="%s"\r\n\r\n--%s\r\n%s\r\n--%s\r\nContent-Type: text/plain; name="notes.txt"\r\n'
                'Content-Disposition: attachment; filename="notes.txt"\r\nContent-Transfer-Encoding: base64\r\n\r\n%s\r\n--%s--\r\n'
                % (b, b, body, b, base64.b64encode(b"attached notes\n").decode(), b))
    else:
        msg += body
    return msg.encode()


if __name__ == "__main__":
    w = World()
    box = w.add_user("me@example.org", "secret")
    for i in range(5):
        box["INBOX"].add(sample(i))
    w2, ip, sp, _stop = start(w)
    print("IMAP on", ip, "SMTP on", sp)
    while True:
        time.sleep(3600)
