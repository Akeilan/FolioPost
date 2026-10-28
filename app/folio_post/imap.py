"""Talking to mail servers: IMAP (reading, folders, flags), SMTP (sending) and POP3, with
passwords or OAuth 2 (XOAUTH2) tokens, over TLS, STARTTLS or a trusted self-signed certificate
(as Proton Mail Bridge uses)."""
import base64
import hashlib
import imaplib
import poplib
import re
import smtplib
import socket
import ssl

TIMEOUT = 40


class AuthError(Exception):
    pass


def tls_context(cfg):
    ctx = ssl.create_default_context()
    pin = cfg.get("cert_sha256")
    if pin or cfg.get("insecure"):
        # a pinned certificate (Proton Mail Bridge's own) is checked by its fingerprint below
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


def cert_fingerprint(sock):
    der = sock.getpeercert(binary_form=True)
    return hashlib.sha256(der).hexdigest() if der else ""


def check_pin(sock, cfg, key="cert_sha256"):
    pin = cfg.get(key) or cfg.get("cert_sha256")
    if pin and cert_fingerprint(sock) != pin:
        raise ssl.SSLError("the server's certificate isn't the one you trusted")


def fetch_certificate(host, port, starttls=None):
    """The SHA-256 fingerprint of a server's certificate (to trust a self-signed one)."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    raw = socket.create_connection((host, port), timeout=TIMEOUT)
    try:
        if starttls == "imap":
            raw.recv(1024)
            raw.sendall(b"a1 STARTTLS\r\n")
            raw.recv(1024)
        elif starttls == "smtp":
            raw.recv(1024)
            raw.sendall(b"EHLO folio\r\n")
            raw.recv(4096)
            raw.sendall(b"STARTTLS\r\n")
            raw.recv(1024)
        s = ctx.wrap_socket(raw, server_hostname=host)
        fp = cert_fingerprint(s)
        s.close()
        return fp
    finally:
        try:
            raw.close()
        except OSError:
            pass


def xoauth2(user, token):
    return "user=%s\x01auth=Bearer %s\x01\x01" % (user, token)


# ---------------------------------------------------------------- IMAP
LIST_RE = re.compile(r'\((?P<flags>[^)]*)\) (?P<delim>"[^"]*"|NIL) (?P<name>.*)')


def _unquote(s):
    s = s.strip()
    if s.startswith('"') and s.endswith('"'):
        s = s[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return s


def decode_mutf7(s):
    """IMAP's modified UTF-7 folder names."""
    out = []
    i = 0
    while i < len(s):
        if s[i] == "&":
            j = s.find("-", i)
            if j == i + 1:
                out.append("&")
            else:
                b = s[i + 1:j].replace(",", "/")
                b += "=" * (-len(b) % 4)
                try:
                    out.append(base64.b64decode(b).decode("utf-16-be"))
                except Exception:
                    out.append(s[i:j + 1])
            i = j + 1
        else:
            out.append(s[i])
            i += 1
    return "".join(out)


def encode_mutf7(s):
    out = []
    buf = ""

    def flush():
        nonlocal buf
        if buf:
            b = base64.b64encode(buf.encode("utf-16-be")).decode().rstrip("=").replace("/", ",")
            out.append("&" + b + "-")
            buf = ""
    for ch in s:
        if 0x20 <= ord(ch) <= 0x7e:
            flush()
            out.append("&-" if ch == "&" else ch)
        else:
            buf += ch
    flush()
    return "".join(out)


ROLE_FLAGS = {"\\sent": "sent", "\\drafts": "drafts", "\\trash": "trash", "\\junk": "junk", "\\archive": "archive",
              "\\all": "all", "\\flagged": "starred", "\\important": "important"}
ROLE_NAMES = {"inbox": "inbox", "sent": "sent", "sent items": "sent", "sent mail": "sent", "sent messages": "sent",
              "drafts": "drafts", "draft": "drafts", "trash": "trash", "deleted items": "trash", "deleted messages": "trash",
              "bin": "trash", "junk": "junk", "spam": "junk", "junk email": "junk", "junk e-mail": "junk", "archive": "archive"}


class Imap:
    def __init__(self, cfg):
        self.cfg = cfg
        self.c = None
        self.selected = None
        self.caps = set()

    def connect(self, password=None, token=None):
        cfg = self.cfg
        host, port, sec = cfg["imap_host"], int(cfg.get("imap_port") or 993), cfg.get("imap_security", "ssl")
        if sec == "ssl":
            self.c = imaplib.IMAP4_SSL(host, port, ssl_context=tls_context(cfg), timeout=TIMEOUT)
            check_pin(self.c.sock, cfg)
        else:
            self.c = imaplib.IMAP4(host, port, timeout=TIMEOUT)
            if sec == "starttls":
                self.c.starttls(ssl_context=tls_context(cfg))
                check_pin(self.c.sock, cfg)
        user = cfg.get("user") or cfg.get("email")
        try:
            if token:
                self.c.authenticate("XOAUTH2", lambda _x: xoauth2(user, token).encode())
            else:
                self.c.login(user, password or "")
        except imaplib.IMAP4.error as e:
            raise AuthError(str(e))
        typ, data = self.c.capability()
        self.caps = set((data[0] or b"").decode().upper().split()) if typ == "OK" else set()
        return self

    def close(self):
        try:
            if self.c is not None:
                self.c.logout()
        except Exception:
            pass
        self.c = None

    def _ok(self, r, what):
        typ, data = r
        if typ != "OK":
            raise imaplib.IMAP4.error("%s: %s" % (what, data))
        return data

    def folders(self):
        """[(path, delimiter, role)] of the account's folders."""
        out = []
        data = self._ok(self.c.list(), "LIST")
        for line in data:
            if not line:
                continue
            if isinstance(line, tuple):
                line = line[0] + b" " + line[1]
            m = LIST_RE.match(line.decode("utf-8", "replace"))
            if not m:
                continue
            flags = m.group("flags").lower().split()
            if "\\noselect" in flags or "\\nonexistent" in flags:
                continue
            delim = None if m.group("delim") == "NIL" else _unquote(m.group("delim"))
            raw = _unquote(m.group("name"))
            path = decode_mutf7(raw)
            role = ""
            for f in flags:
                if f in ROLE_FLAGS and ROLE_FLAGS[f] in ("sent", "drafts", "trash", "junk", "archive"):
                    role = ROLE_FLAGS[f]
            leaf = path.split(delim)[-1] if delim else path
            if not role and path.upper() == "INBOX":
                role = "inbox"
            if not role and leaf.lower() in ROLE_NAMES and ROLE_NAMES[leaf.lower()] != "inbox":
                role = ROLE_NAMES[leaf.lower()]
            out.append((path, delim or "/", role, raw, "\\all" in flags or "\\flagged" in flags))
        # one folder per role: the server's flags first
        seen = set()
        res = []
        for path, delim, role, raw, virtual in out:
            if role in seen:
                role = ""
            if role:
                seen.add(role)
            res.append((path, delim, role, raw, virtual))
        return res

    def q(self, path):
        return '"%s"' % encode_mutf7(path).replace("\\", "\\\\").replace('"', '\\"')

    def select(self, path, readonly=False):
        typ, data = self.c.select(self.q(path), readonly=readonly)
        if typ != "OK":
            raise imaplib.IMAP4.error("SELECT %s: %s" % (path, data))
        self.selected = path
        uv = self.c.untagged_responses.get("UIDVALIDITY", [b"0"])[-1]
        un = self.c.untagged_responses.get("UIDNEXT", [b"0"])[-1]
        return int(uv or 0), int(un or 0), int(data[0] or 0)

    def uids(self, since_uid=1):
        data = self._ok(self.c.uid("SEARCH", None, "UID %d:*" % max(1, since_uid)), "SEARCH")
        out = [int(x) for x in (data[0] or b"").split()]
        return [u for u in out if u >= since_uid]

    def all_uids(self):
        data = self._ok(self.c.uid("SEARCH", None, "ALL"), "SEARCH")
        return [int(x) for x in (data[0] or b"").split()]

    def flags(self, uids):
        """uid -> set of flags."""
        out = {}
        for chunk in _chunks(uids, 400):
            data = self._ok(self.c.uid("FETCH", ",".join(map(str, chunk)), "(FLAGS)"), "FETCH")
            for item in data:
                line = item[0] if isinstance(item, tuple) else item
                if not line:
                    continue
                line = line.decode("utf-8", "replace")
                m = re.search(r"UID (\d+)", line)
                f = re.search(r"FLAGS \(([^)]*)\)", line)
                if m:
                    out[int(m.group(1))] = set(x.lower() for x in (f.group(1).split() if f else []))
        return out

    def fetch(self, uids):
        """Whole messages: [(uid, flags, internal date, raw bytes)]."""
        out = []
        for chunk in _chunks(uids, 25):
            data = self._ok(self.c.uid("FETCH", ",".join(map(str, chunk)), "(UID FLAGS INTERNALDATE BODY.PEEK[])"), "FETCH")
            for item in data:
                if not isinstance(item, tuple):
                    continue
                head = item[0].decode("utf-8", "replace")
                m = re.search(r"UID (\d+)", head)
                f = re.search(r"FLAGS \(([^)]*)\)", head)
                d = re.search(r'INTERNALDATE "([^"]+)"', head)
                when = None
                if d:
                    try:
                        import email.utils
                        when = email.utils.parsedate_to_datetime(_idate(d.group(1))).timestamp()
                    except Exception:
                        when = None
                if m:
                    out.append((int(m.group(1)), set(x.lower() for x in (f.group(1).split() if f else [])), when, item[1]))
        return out

    def store(self, uids, flags, add=True):
        if uids:
            self._ok(self.c.uid("STORE", ",".join(map(str, uids)), "+FLAGS.SILENT" if add else "-FLAGS.SILENT",
                                "(%s)" % " ".join(flags)), "STORE")

    def move(self, uids, path):
        if not uids:
            return
        s = ",".join(map(str, uids))
        if "MOVE" in self.caps:
            self._ok(self.c.uid("MOVE", s, self.q(path)), "MOVE")
        else:
            self._ok(self.c.uid("COPY", s, self.q(path)), "COPY")
            self.store(uids, ["\\Deleted"])
            self.expunge(uids)

    def expunge(self, uids=None):
        if uids and "UIDPLUS" in self.caps:
            self.c.uid("EXPUNGE", ",".join(map(str, uids)))
        else:
            self.c.expunge()

    def append(self, path, raw, flags=("\\Seen",)):
        typ, data = self.c.append(self.q(path), "(%s)" % " ".join(flags), imaplib.Time2Internaldate(__import__("time").time()), raw)
        if typ != "OK":
            raise imaplib.IMAP4.error("APPEND: %s" % data)
        m = re.search(rb"APPENDUID \d+ (\d+)", (data[0] or b"") if data else b"")
        return int(m.group(1)) if m else 0

    def create(self, path):
        self._ok(self.c.create(self.q(path)), "CREATE")

    def delete_folder(self, path):
        self._ok(self.c.delete(self.q(path)), "DELETE")

    def rename(self, old, new):
        self._ok(self.c.rename(self.q(old), self.q(new)), "RENAME")

    def noop(self):
        self.c.noop()


def _idate(s):
    # IMAP's "17-Jul-1996 02:44:25 -0700" in RFC 2822 form
    m = re.match(r"\s*(\d+)-(\w+)-(\d+) (\d+:\d+:\d+) ([+-]\d+)", s)
    if not m:
        return s
    return "%s %s %s %s %s" % m.groups()


def _chunks(xs, n):
    xs = list(xs)
    for i in range(0, len(xs), n):
        yield xs[i:i + n]


# ---------------------------------------------------------------- SMTP
def send(cfg, raw, sender, rcpts, password=None, token=None):
    host, port, sec = cfg["smtp_host"], int(cfg.get("smtp_port") or 465), cfg.get("smtp_security", "ssl")
    if sec == "ssl":
        s = smtplib.SMTP_SSL(host, port, context=tls_context(cfg), timeout=TIMEOUT)
        check_pin(s.sock, cfg, "smtp_cert_sha256")
    else:
        s = smtplib.SMTP(host, port, timeout=TIMEOUT)
        s.ehlo()
        if sec == "starttls":
            s.starttls(context=tls_context(cfg))
            check_pin(s.sock, cfg, "smtp_cert_sha256")
            s.ehlo()
    try:
        user = cfg.get("smtp_user") or cfg.get("user") or cfg.get("email")
        if token:
            code, resp = s.docmd("AUTH", "XOAUTH2 " + base64.b64encode(xoauth2(user, token).encode()).decode())
            if code != 235:
                raise AuthError(resp.decode("utf-8", "replace"))
        elif cfg.get("smtp_auth", True) and (password or cfg.get("smtp_password_same", True)):
            try:
                s.login(user, password or "")
            except smtplib.SMTPNotSupportedError:
                pass
            except smtplib.SMTPAuthenticationError as e:
                raise AuthError(str(e))
        s.sendmail(sender, rcpts, raw)
    finally:
        try:
            s.quit()
        except Exception:
            pass


# ---------------------------------------------------------------- POP3
class Pop:
    def __init__(self, cfg):
        self.cfg = cfg
        self.c = None

    def connect(self, password=None):
        cfg = self.cfg
        host, port, sec = cfg["pop_host"], int(cfg.get("pop_port") or 995), cfg.get("pop_security", "ssl")
        if sec == "ssl":
            self.c = poplib.POP3_SSL(host, port, context=tls_context(cfg), timeout=TIMEOUT)
        else:
            self.c = poplib.POP3(host, port, timeout=TIMEOUT)
            if sec == "starttls":
                self.c.stls(context=tls_context(cfg))
        try:
            self.c.user(cfg.get("user") or cfg.get("email"))
            self.c.pass_(password or "")
        except poplib.error_proto as e:
            raise AuthError(str(e))
        return self

    def uidls(self):
        _resp, lines, _o = self.c.uidl()
        out = {}
        for ln in lines:
            n, uid = ln.decode().split(None, 1)
            out[uid] = int(n)
        return out

    def retr(self, n):
        _resp, lines, _o = self.c.retr(n)
        return b"\r\n".join(lines) + b"\r\n"

    def dele(self, n):
        self.c.dele(n)

    def close(self):
        try:
            self.c.quit()
        except Exception:
            pass
