"""Automatic Replies (File > Info > Automatic Replies): sent by the mail server, so they go out
while this computer is off. Exchange keeps them itself (Out of Office); Gmail has its vacation
responder; other servers take a Sieve script through ManageSieve (RFC 5804, RFC 5230).
Proton Mail's Bridge doesn't pass them on, so Post says so."""
import base64
import datetime as dt
import json
import re
import socket
import ssl
import urllib.request

UTC = dt.timezone.utc
GMAIL_API = "https://gmail.googleapis.com/gmail/v1/users/me/settings/vacation"
MARK_BEGIN = "# Folio Post: Automatic Replies (begin)"
MARK_END = "# Folio Post: Automatic Replies (end)"
SCRIPT = "folio-post"


class NotReachable(Exception):
    """Automatic Replies can't be set for this account from here (the text says why)."""


def blank():
    return {"state": "off", "start": None, "end": None, "internal": "", "external": "", "audience": "all", "subject": ""}


# ---------------------------------------------------------------- ManageSieve
class SieveError(Exception):
    pass


class ManageSieve:
    def __init__(self, host, port=4190, security="starttls", insecure=False, timeout=20):
        self.host, self.port, self.security, self.insecure = host, port, security, insecure
        self.sock = socket.create_connection((host, port), timeout=timeout)
        if security == "ssl":
            self._wrap()
        self.f = self.sock.makefile("rb")
        self.caps = self._caps()
        if security == "starttls":
            if "STARTTLS" not in self.caps:
                raise SieveError("the server doesn't offer an encrypted connection")
            self._cmd("STARTTLS")
            self._wrap()
            self.f = self.sock.makefile("rb")
            self.caps = self._caps()

    def _wrap(self):
        ctx = ssl.create_default_context()
        if self.insecure:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        self.sock = ctx.wrap_socket(self.sock, server_hostname=self.host)

    def _line(self):
        ln = self.f.readline()
        if not ln:
            raise SieveError("the server closed the connection")
        return ln.decode("utf-8", "replace").rstrip("\r\n")

    def _caps(self):
        caps = {}
        while True:
            ln = self._line()
            if ln.startswith("OK"):
                return caps
            if ln.startswith(("NO", "BYE")):
                raise SieveError(ln)
            m = re.match(r'"([^"]+)"(?:\s+"([^"]*)")?', ln)
            if m:
                caps[m.group(1).upper()] = m.group(2) or ""

    def _send(self, data):
        self.sock.sendall(data if isinstance(data, bytes) else data.encode("utf-8"))

    def _response(self):
        """(lines before the OK, the OK line); literals {n} are read whole."""
        out = []
        while True:
            ln = self._line()
            m = re.match(r"^\{(\d+)\+?\}$", ln)
            if m:
                n = int(m.group(1))
                out.append(self.f.read(n).decode("utf-8", "replace"))
                continue
            if ln.startswith("OK"):
                return out, ln
            if ln.startswith(("NO", "BYE")):
                raise SieveError(re.sub(r'^(NO|BYE)\s*(\([^)]*\))?\s*', "", ln).strip('"') or ln)
            out.append(ln)

    def _cmd(self, line):
        self._send(line + "\r\n")
        return self._response()

    @staticmethod
    def _lit(s):
        b = s.encode("utf-8")
        return "{%d+}\r\n" % len(b), b

    def login(self, user, password):
        tok = base64.b64encode(("\0%s\0%s" % (user, password)).encode()).decode()
        try:
            self._cmd('AUTHENTICATE "PLAIN" "%s"' % tok)
        except SieveError as e:
            raise SieveError("the server didn't accept the sign-in (%s)" % e)

    def list(self):
        lines, _ok = self._cmd("LISTSCRIPTS")
        out = []
        for ln in lines:
            m = re.match(r'"((?:[^"\\]|\\.)*)"(\s+ACTIVE)?', ln)
            if m:
                out.append((m.group(1), bool(m.group(2))))
        return out

    def get(self, name):
        lines, _ok = self._cmd('GETSCRIPT "%s"' % name)
        return lines[0] if lines else ""

    def put(self, name, script):
        head, body = self._lit(script)
        self._send(('PUTSCRIPT "%s" ' % name) + head)
        self._send(body + b"\r\n")
        self._response()

    def activate(self, name):
        self._cmd('SETACTIVE "%s"' % name)

    def logout(self):
        try:
            self._cmd("LOGOUT")
        except Exception:
            pass
        try:
            self.sock.close()
        except Exception:
            pass


def _sieve_str(s):
    return '"%s"' % s.replace("\\", "\\\\").replace('"', '\\"')


def sieve_block(s):
    """The Sieve lines for the settings (the settings themselves kept in a comment for reading back)."""
    keep = {"state": s["state"], "start": s["start"].isoformat() if s.get("start") else None,
            "end": s["end"].isoformat() if s.get("end") else None, "internal": s.get("internal", ""),
            "subject": s.get("subject", "")}
    out = [MARK_BEGIN, "# folio-settings: " + json.dumps(keep)]
    if s["state"] == "off":
        out.append(MARK_END)
        return "\n".join(out) + "\n"
    act = "vacation :days 1 %s%s;" % (":subject %s " % _sieve_str(s["subject"]) if s.get("subject") else "",
                                      _sieve_str(s.get("internal", "")))
    if s["state"] == "scheduled" and s.get("start") and s.get("end"):
        a, b = s["start"].astimezone(UTC), s["end"].astimezone(UTC)

        def after(d):
            return ('anyof(currentdate :zone "+0000" :value "gt" "date" "%s", allof(currentdate :zone "+0000" :is "date" "%s", '
                    'currentdate :zone "+0000" :value "ge" "time" "%s"))' % (d.strftime("%Y-%m-%d"), d.strftime("%Y-%m-%d"), d.strftime("%H:%M:%S")))

        def before(d):
            return ('anyof(currentdate :zone "+0000" :value "lt" "date" "%s", allof(currentdate :zone "+0000" :is "date" "%s", '
                    'currentdate :zone "+0000" :value "lt" "time" "%s"))' % (d.strftime("%Y-%m-%d"), d.strftime("%Y-%m-%d"), d.strftime("%H:%M:%S")))
        out.append("if allof(%s, %s) {" % (after(a), before(b)))
        out.append("    " + act)
        out.append("}")
    else:
        out.append(act)
    out.append(MARK_END)
    return "\n".join(out) + "\n"


REQUIRE = 'require ["vacation", "date", "relational"]; # Folio Post'


def merge_script(old, s):
    """The user's own Sieve rules with the Automatic Replies put in (or taken out)."""
    lines = (old or "").replace("\r\n", "\n").split("\n")
    keep, inside = [], False
    for ln in lines:
        if ln.strip() == MARK_BEGIN:
            inside = True
            continue
        if ln.strip() == MARK_END:
            inside = False
            continue
        if inside or ln.strip() == REQUIRE:
            continue
        keep.append(ln)
    while keep and not keep[-1].strip():
        keep.pop()
    head, k = [], 0
    while k < len(keep) and (keep[k].strip().startswith(("require", "#")) or not keep[k].strip()):
        head.append(keep[k])
        k += 1
    body = keep[k:]
    out = [REQUIRE] + head + [sieve_block(s).rstrip("\n")] + body
    return "\n".join(out).strip("\n") + "\n"


def read_block(script):
    m = re.search(r"^# folio-settings: (.*)$", script or "", re.M)
    s = blank()
    if not m:
        return s
    try:
        d = json.loads(m.group(1))
    except ValueError:
        return s
    s.update({"state": d.get("state", "off"), "internal": d.get("internal", ""), "subject": d.get("subject", "")})
    for k in ("start", "end"):
        if d.get(k):
            s[k] = dt.datetime.fromisoformat(d[k])
    s["external"] = s["internal"]
    return s


class SieveBackend:
    name = "Sieve"
    has_external = False

    def __init__(self, host, port, user, password, security="starttls", insecure=False):
        self.args = (host, port, security, insecure)
        self.user, self.password = user, password

    def _open(self):
        try:
            c = ManageSieve(*self.args)
        except (OSError, SieveError) as e:
            raise NotReachable("This mail server doesn't take automatic replies from other mail apps (no ManageSieve at "
                               "%s:%d: %s)." % (self.args[0], self.args[1], e))
        c.login(self.user, self.password)
        return c

    def get(self):
        c = self._open()
        try:
            active = [n for n, a in c.list() if a]
            return read_block(c.get(active[0])) if active else blank()
        finally:
            c.logout()

    def set(self, s):
        c = self._open()
        try:
            scripts = c.list()
            active = [n for n, a in scripts if a]
            name = active[0] if active else SCRIPT
            old = c.get(name) if any(n == name for n, _a in scripts) else ""
            c.put(name, merge_script(old, s))
            if not active:
                c.activate(name)
        finally:
            c.logout()


# ---------------------------------------------------------------- Gmail
class GmailBackend:
    name = "Gmail"
    has_external = False

    def __init__(self, token, url=None):
        self.token = token
        self.url = url or GMAIL_API

    def _req(self, method, body=None):
        r = urllib.request.Request(self.url, method=method, data=json.dumps(body).encode() if body is not None else None,
                                   headers={"Authorization": "Bearer " + (self.token() if callable(self.token) else self.token),
                                            "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(r, timeout=30) as resp:
                return json.loads(resp.read().decode() or "{}")
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise NotReachable("Google didn't let Post change the vacation responder. Sign in to this account again "
                                   "(File > Account Settings) so Post may manage Gmail settings.")
            raise

    def get(self):
        d = self._req("GET")
        s = blank()
        on = d.get("enableAutoReply", False)
        st, en = d.get("startTime"), d.get("endTime")
        s["start"] = dt.datetime.fromtimestamp(int(st) / 1000, UTC) if st else None
        s["end"] = dt.datetime.fromtimestamp(int(en) / 1000, UTC) if en else None
        s["state"] = ("scheduled" if s["start"] and s["end"] else "on") if on else "off"
        s["internal"] = s["external"] = d.get("responseBodyPlainText", "")
        s["subject"] = d.get("responseSubject", "")
        s["audience"] = "known" if d.get("restrictToContacts") else "all"
        return s

    def set(self, s):
        body = {"enableAutoReply": s["state"] != "off", "responseSubject": s.get("subject", ""),
                "responseBodyPlainText": s.get("internal", ""), "restrictToContacts": s.get("audience") == "known",
                "restrictToDomain": False}
        if s["state"] == "scheduled" and s.get("start") and s.get("end"):
            body["startTime"] = str(int(s["start"].timestamp() * 1000))
            body["endTime"] = str(int(s["end"].timestamp() * 1000))
        self._req("PUT", body)


# ---------------------------------------------------------------- Exchange
class ExchangeBackend:
    name = "Exchange"
    has_external = True

    def __init__(self, client, email):
        self.c, self.email = client, email

    def get(self):
        s = blank()
        s.update(self.c.get_oof(self.email))
        return s

    def set(self, s):
        self.c.set_oof(self.email, s)


def backend_for(app, acc):
    """The way to this account's Automatic Replies, or NotReachable."""
    cfg = acc["config"]
    if acc["kind"] == "ews":
        from . import ews
        return ExchangeBackend(ews.client_for(acc, app.secrets, app.tokens), acc["email"])
    if acc["kind"] == "local":
        raise NotReachable("Messages kept on this computer have no server to send automatic replies.")
    if cfg.get("bridge") or acc["email"].split("@")[-1].lower() in ("proton.me", "protonmail.com", "protonmail.ch", "pm.me"):
        raise NotReachable("Proton Mail's Bridge doesn't pass automatic replies on to mail apps. Set them in Proton's web "
                           "app (Settings > Auto-reply).")
    if cfg.get("imap_host") == "outlook.office365.com":
        raise NotReachable("Over IMAP, Outlook.com doesn't let mail apps set automatic replies. For a work or school account, "
                           "add it as Microsoft Exchange (File > Add Account) and they're set from here; for Outlook.com, "
                           "set them on outlook.com (Settings > Mail > Automatic replies).")
    if cfg.get("imap_host") == "imap.gmail.com":
        if cfg.get("auth") not in ("oauth", "goa"):
            raise NotReachable("Gmail's vacation responder needs the Google sign-in (an app password only reaches mail). "
                               "Add the account again with Google sign-in, or set it on mail.google.com.")
        return GmailBackend(lambda: app.tokens(acc), app.store.get("gmail-api-url") or None)
    host = cfg.get("sieve_host") or cfg.get("imap_host", "")
    pw = app.secrets.get(acc["id"]) or cfg.get("password", "")
    return SieveBackend(host, int(cfg.get("sieve_port", 4190)), cfg.get("user", acc["email"]), pw,
                        cfg.get("sieve_security", "starttls" if cfg.get("imap_security") != "none" else "none"),
                        cfg.get("insecure", False))


# ---------------------------------------------------------------- the dialog
def dialog(win, acc=None):
    from gi.repository import GLib, Gtk
    acc = acc or win.current_account()
    if acc is None:
        win.dialogs.info("Add an account first.", "Automatic Replies")
        return None
    try:
        be = backend_for(win.app, acc)
        cur = be.get()
    except NotReachable as e:
        win.dialogs.info(str(e), "Automatic Replies")
        return None
    except Exception as e:
        win.dialogs.message("Folio Post couldn't read the automatic replies of %s.\n\n%s" % (acc["email"], e))
        return None
    d = Gtk.Dialog(title="Automatic Replies - %s" % acc["email"], transient_for=win, modal=True)
    d.get_style_context().add_class("folio-dialog")
    d.add_button("Cancel", Gtk.ResponseType.CANCEL)
    okb = d.add_button("OK", Gtk.ResponseType.OK)
    okb.get_style_context().add_class("folio-default")
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin=14)
    d.get_content_area().pack_start(box, True, True, 0)
    off = Gtk.RadioButton.new_with_label(None, "Do not send automatic replies")
    on = Gtk.RadioButton.new_with_label_from_widget(off, "Send automatic replies")
    box.pack_start(off, False, False, 0)
    box.pack_start(on, False, False, 0)
    timed = Gtk.CheckButton(label="Only send during this time range:")
    box.pack_start(timed, False, False, 0)
    grid = Gtk.Grid(column_spacing=8, row_spacing=6, margin_start=24)
    now = dt.datetime.now().astimezone().replace(minute=0, second=0, microsecond=0)
    st = (cur.get("start") or now).astimezone()
    en = (cur.get("end") or now + dt.timedelta(days=1)).astimezone()
    entries = {}
    for r, (label, when) in enumerate((("Start time", st), ("End time", en))):
        grid.attach(Gtk.Label(label=label, xalign=0), 0, r, 1, 1)
        e = Gtk.Entry(text=when.strftime("%Y-%m-%d %H:%M"))
        e.set_width_chars(18)
        grid.attach(e, 1, r, 1, 1)
        entries[label] = e
    box.pack_start(grid, False, False, 0)
    subj = None
    if be.name != "Exchange":
        sb = Gtk.Box(spacing=8)
        sb.pack_start(Gtk.Label(label="Subject"), False, False, 0)
        subj = Gtk.Entry(text=cur.get("subject", ""))
        subj.set_placeholder_text("Automatic reply")
        sb.pack_start(subj, True, True, 0)
        box.pack_start(sb, False, False, 0)
    nb = Gtk.Notebook()
    views = {}
    tabs = [("internal", "Inside My Organization" if be.has_external else "Reply")]
    if be.has_external:
        tabs.append(("external", "Outside My Organization"))
    for key, title in tabs:
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin=8)
        if key == "external":
            ext_on = Gtk.CheckButton(label="Auto-reply to people outside my organization")
            ext_on.set_active(cur.get("audience", "all") != "none")
            page.pack_start(ext_on, False, False, 0)
            known = Gtk.RadioButton.new_with_label(None, "My Contacts only")
            anyone = Gtk.RadioButton.new_with_label_from_widget(known, "Anyone outside my organization")
            (known if cur.get("audience") == "known" else anyone).set_active(True)
            page.pack_start(known, False, False, 0)
            page.pack_start(anyone, False, False, 0)
            views["ext_on"], views["known"] = ext_on, known
        elif be.name == "Gmail":
            known = Gtk.CheckButton(label="Only send a response to people in my Contacts")
            known.set_active(cur.get("audience") == "known")
            page.pack_start(known, False, False, 0)
            views["known_only"] = known
        tv = Gtk.TextView()
        tv.set_wrap_mode(Gtk.WrapMode.WORD)
        tv.get_buffer().set_text(cur.get(key, "") or "")
        sw = Gtk.ScrolledWindow()
        sw.set_size_request(460, 160)
        sw.add(tv)
        page.pack_start(sw, True, True, 0)
        nb.append_page(page, Gtk.Label(label=title))
        views[key] = tv
    box.pack_start(nb, True, True, 0)
    note = Gtk.Label(xalign=0)
    note.set_markup("<small>Sent by %s's server, so replies go out while this computer is off.</small>"
                    % GLib.markup_escape_text(be.name if be.name != "Sieve" else "the mail"))
    box.pack_start(note, False, False, 0)
    (on if cur["state"] != "off" else off).set_active(True)
    timed.set_active(cur["state"] == "scheduled")

    def sync(*_):
        act = on.get_active()
        for w in [timed, nb] + ([subj] if subj else []):
            w.set_sensitive(act)
        grid.set_sensitive(act and timed.get_active())
    on.connect("toggled", sync)
    timed.connect("toggled", sync)
    sync()
    d.show_all()
    d.views = views
    d.on, d.off, d.timed, d.entries, d.subj = on, off, timed, entries, subj
    while True:
        resp = d.run()
        if resp != Gtk.ResponseType.OK:
            d.destroy()
            return None
        s = blank()
        s["state"] = "off" if not on.get_active() else "scheduled" if timed.get_active() else "on"

        def text(key):
            b = views[key].get_buffer()
            return b.get_text(b.get_start_iter(), b.get_end_iter(), False) if key in views else ""
        s["internal"] = text("internal")
        s["external"] = text("external") if "external" in views else s["internal"]
        if "ext_on" in views:
            s["audience"] = "none" if not views["ext_on"].get_active() else "known" if views["known"].get_active() else "all"
        elif "known_only" in views:
            s["audience"] = "known" if views["known_only"].get_active() else "all"
        if subj is not None:
            s["subject"] = subj.get_text()
        try:
            local = dt.datetime.now().astimezone().tzinfo
            s["start"] = dt.datetime.strptime(entries["Start time"].get_text().strip(), "%Y-%m-%d %H:%M").replace(tzinfo=local)
            s["end"] = dt.datetime.strptime(entries["End time"].get_text().strip(), "%Y-%m-%d %H:%M").replace(tzinfo=local)
        except ValueError:
            if s["state"] == "scheduled":
                win.dialogs.info("Type the times as 2026-11-02 09:00.", "Automatic Replies")
                continue
            s["start"] = s["end"] = None
        if s["state"] == "scheduled" and s["end"] <= s["start"]:
            win.dialogs.info("The end time is before the start time.", "Automatic Replies")
            continue
        if s["state"] != "scheduled":
            s["start"] = s["end"] = None
        try:
            be.set(s)
        except NotReachable as e:
            win.dialogs.info(str(e), "Automatic Replies")
            continue
        except Exception as e:
            win.dialogs.message("Folio Post couldn't change the automatic replies.\n\n%s" % e)
            continue
        d.destroy()
        win.store.put("autoreply-on:%d" % acc["id"], s["state"] != "off")
        if hasattr(win, "show_autoreply_bar"):
            win.show_autoreply_bar()
        return s
