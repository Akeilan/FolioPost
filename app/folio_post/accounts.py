"""Adding and changing accounts: Gmail (Google sign-in or an app password), Proton Mail (through
Proton Mail Bridge), the common providers' settings, and any IMAP, POP3 and SMTP server."""
import json
import os
import pwd
import threading
import urllib.parse

from gi.repository import Gdk, GLib, Gtk

from . import APP_NAME, imap, oauth

GMAIL = {"imap_host": "imap.gmail.com", "imap_port": 993, "imap_security": "ssl", "smtp_host": "smtp.gmail.com",
         "smtp_port": 465, "smtp_security": "ssl", "server_saves_sent": True, "skip_virtual": True}
PROTON = {"imap_host": "127.0.0.1", "imap_port": 1143, "imap_security": "starttls", "smtp_host": "127.0.0.1",
          "smtp_port": 1025, "smtp_security": "starttls", "server_saves_sent": True, "bridge": True}
PROVIDERS = {
    "gmail.com": ("gmail", GMAIL), "googlemail.com": ("gmail", GMAIL),
    "proton.me": ("proton", PROTON), "protonmail.com": ("proton", PROTON), "protonmail.ch": ("proton", PROTON),
    "pm.me": ("proton", PROTON),
    "yahoo.com": ("app-password", {"imap_host": "imap.mail.yahoo.com", "imap_port": 993, "imap_security": "ssl",
                                   "smtp_host": "smtp.mail.yahoo.com", "smtp_port": 465, "smtp_security": "ssl",
                                   "server_saves_sent": True}),
    "icloud.com": ("app-password", {"imap_host": "imap.mail.me.com", "imap_port": 993, "imap_security": "ssl",
                                    "smtp_host": "smtp.mail.me.com", "smtp_port": 587, "smtp_security": "starttls"}),
    "me.com": ("app-password", {"imap_host": "imap.mail.me.com", "imap_port": 993, "imap_security": "ssl",
                                "smtp_host": "smtp.mail.me.com", "smtp_port": 587, "smtp_security": "starttls"}),
    "fastmail.com": ("app-password", {"imap_host": "imap.fastmail.com", "imap_port": 993, "imap_security": "ssl",
                                      "smtp_host": "smtp.fastmail.com", "smtp_port": 465, "smtp_security": "ssl"}),
    "gmx.com": ("password", {"imap_host": "imap.gmx.com", "imap_port": 993, "imap_security": "ssl",
                             "smtp_host": "mail.gmx.com", "smtp_port": 465, "smtp_security": "ssl"}),
    "gmx.net": ("password", {"imap_host": "imap.gmx.net", "imap_port": 993, "imap_security": "ssl",
                             "smtp_host": "mail.gmx.net", "smtp_port": 465, "smtp_security": "ssl"}),
    "aol.com": ("app-password", {"imap_host": "imap.aol.com", "imap_port": 993, "imap_security": "ssl",
                                 "smtp_host": "smtp.aol.com", "smtp_port": 465, "smtp_security": "ssl"}),
    "zoho.com": ("password", {"imap_host": "imap.zoho.com", "imap_port": 993, "imap_security": "ssl",
                              "smtp_host": "smtp.zoho.com", "smtp_port": 465, "smtp_security": "ssl"}),
}
OUTLOOK = {"imap_host": "outlook.office365.com", "imap_port": 993, "imap_security": "ssl", "smtp_host": "smtp.office365.com",
           "smtp_port": 587, "smtp_security": "starttls", "server_saves_sent": True, "auth": "oauth", "oauth_provider": "microsoft"}
MICROSOFT = ("outlook.com", "hotmail.com", "live.com", "msn.com", "outlook.nl", "hotmail.nl", "live.nl")
SECURITY = [("ssl", "SSL/TLS"), ("starttls", "STARTTLS"), ("none", "None")]


def real_name():
    try:
        return pwd.getpwuid(os.getuid()).pw_gecos.split(",")[0]
    except Exception:
        return ""


def guess(email):
    dom = email.split("@")[-1].lower()
    if dom in PROVIDERS:
        kind, cfg = PROVIDERS[dom]
        return kind, dict(cfg)
    if dom in MICROSOFT:
        return "microsoft", {}
    return "password", {"imap_host": "imap." + dom, "imap_port": 993, "imap_security": "ssl", "smtp_host": "smtp." + dom,
                        "smtp_port": 465, "smtp_security": "ssl"}


def create_account(win, name, email, cfg, secret=None, oauth_tokens=None, kind="imap"):
    """Adds the account to the store, keeps its password or tokens, and starts the first sync."""
    store = win.store
    cfg = dict(cfg)
    cfg.setdefault("user", email)
    cfg.setdefault("email", email)
    aid = store.add_account(name or email, email, kind, cfg)
    if oauth_tokens is not None:
        win.app.secrets.set(aid, json.dumps(oauth_tokens), "oauth")
    elif secret is not None:
        win.app.secrets.set(aid, secret)
    win.refresh_folders()
    if kind == "ews":
        # the Exchange account's Calendar, Contacts and Tasks, kept the same both ways
        from . import ews
        cals, books = ews.add_account_sources(store, None, store.account(aid))
        if not store.get("tasks-account"):
            store.put("tasks-account", aid)
        for hook in ("_after_calendars", "_after_books"):
            if hasattr(win, hook):
                getattr(win, hook)()
    signed_in = oauth_tokens is not None or cfg.get("auth") == "goa"
    if signed_in and cfg.get("imap_host") == "imap.gmail.com" and not win.app.syncer.offline:
        # the same Google sign-in opens Google Calendar
        def cal_job():
            ids = win.app.calsync.add_google(aid)
            for i in ids:
                win.app.calsync.sync(i)
            for b in win.app.contactsync.add_google(aid):
                win.app.contactsync.sync(b)
        win.app.background(cal_job, lambda *_: (win._after_calendars(), win._after_books()))
    if not win.app.syncer.offline:
        def done(*_):
            win.refresh_folders()
            if not win.folder_id:
                win.select_first_inbox()
        win.app.send_receive([aid], done=done)
    return aid


def google_goa_account(email):
    """The Online Accounts entry of this Google address, only when it gives a token (so it really works)."""
    from . import goa
    try:
        if not goa.available():
            return None
        f = goa.find(email, "google")
        if f is None or not f["mail"]:
            return None
        goa.token(f["id"])
        return f
    except Exception:
        return None


def read_google_client(data):
    """(client id, secret) from the client_secret_*.json Google Cloud console gives for a Desktop app."""
    import json as _j
    d = _j.loads(data.decode("utf-8") if isinstance(data, bytes) else data)
    c = d.get("installed") or d.get("web") or d
    cid = c.get("client_id", "")
    if not cid.endswith(".apps.googleusercontent.com"):
        raise ValueError("this isn't an OAuth client file from Google (no client_id ending in .apps.googleusercontent.com)")
    if "web" in d and "installed" not in d:
        raise ValueError("this client is of type “Web application”; make one of type “Desktop app”")
    return cid, c.get("client_secret", "")


def save_google_client(store, data):
    cid, sec = read_google_client(data)
    store.put("google-client", {"id": cid, "secret": sec})
    return cid


GUIDE_STEPS = [
    ("Open the <a href=\"https://console.cloud.google.com/projectcreate\">Google Cloud console</a> signed in with this Google "
     "account and make a project (any name, for example “Folio Post”)."),
    ("Turn on the APIs Post uses: <a href=\"https://console.cloud.google.com/apis/library/gmail.googleapis.com\">Gmail API</a>, "
     "<a href=\"https://console.cloud.google.com/apis/library/caldav.googleapis.com\">CalDAV API</a>, "
     "<a href=\"https://console.cloud.google.com/apis/library/calendar-json.googleapis.com\">Google Calendar API</a> and "
     "<a href=\"https://console.cloud.google.com/apis/library/carddav.googleapis.com\">CardDAV API</a> (Enable on each)."),
    ("On the <a href=\"https://console.cloud.google.com/apis/credentials/consent\">OAuth consent screen</a> choose "
     "<b>External</b>, fill in the app name and your address, add the scopes for Gmail, Calendar and Contacts, then "
     "<b>Publish app</b> so it says <b>In production</b> (otherwise Google signs you out every 7 days)."),
    ("Under <a href=\"https://console.cloud.google.com/apis/credentials\">Credentials</a>: Create credentials &gt; "
     "OAuth client ID &gt; Application type <b>Desktop app</b> &gt; Create."),
    "Click <b>Download JSON</b> and drop the file below (or choose it).",
]


class GoogleClientGuide(Gtk.Box):
    """The first-run steps for Google sign-in, and the place the downloaded client file goes."""

    def __init__(self, dialog, on_ready):
        Gtk.Box.__init__(self, orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.dialog, self.on_ready = dialog, on_ready
        lab = Gtk.Label(xalign=0)
        lab.set_line_wrap(True)
        lab.set_max_width_chars(66)
        lab.set_markup("<b>Sign in with Google</b> happens in your web browser, where security keys and passkeys work. "
                       "Google wants each person's own app for this, made once (about five minutes):")
        self.pack_start(lab, False, False, 0)
        self.steps = []
        for k, text in enumerate(GUIDE_STEPS):
            row = Gtk.Box(spacing=8)
            n = Gtk.Label(label="%d." % (k + 1), xalign=0, yalign=0)
            n.set_width_chars(2)
            t = Gtk.Label(xalign=0)
            t.set_line_wrap(True)
            t.set_max_width_chars(62)
            t.set_markup(text)
            row.pack_start(n, False, False, 0)
            row.pack_start(t, True, True, 0)
            self.pack_start(row, False, False, 0)
            self.steps.append(t)
        note = Gtk.Label(xalign=0)
        note.set_line_wrap(True)
        note.set_max_width_chars(66)
        note.set_markup("<small>When you sign in, Google shows <i>Google hasn't verified this app</i> once: click "
                        "<b>Advanced</b> &gt; <b>Go to … (unsafe)</b> / Continue. It's your own app, so that's expected.</small>")
        self.pack_start(note, False, False, 0)
        # the drop zone
        self.drop = Gtk.EventBox()
        self.drop.get_style_context().add_class("folio-dropzone")
        inner = Gtk.Box(spacing=10)
        inner.set_border_width(14)
        self.drop_label = Gtk.Label(label="Drop client_secret_….json here")
        inner.pack_start(self.drop_label, True, True, 0)
        choose = Gtk.Button(label="Choose File...")
        choose.connect("clicked", lambda *_: self.choose())
        inner.pack_end(choose, False, False, 0)
        self.drop.add(inner)
        self.drop.drag_dest_set(Gtk.DestDefaults.ALL, [Gtk.TargetEntry.new("text/uri-list", 0, 0)], Gdk.DragAction.COPY)
        self.drop.connect("drag-data-received", self._dropped)
        self.pack_start(self.drop, False, False, 4)

    def _dropped(self, _w, _ctx, _x, _y, data, _info, _time):
        uris = data.get_uris() or []
        if uris:
            self.take_file(GLib.filename_from_uri(uris[0])[0])

    def choose(self):
        dlg = Gtk.FileChooserDialog(title="The client file from Google", transient_for=self.dialog,
                                    action=Gtk.FileChooserAction.OPEN)
        dlg.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Open", Gtk.ResponseType.OK)
        f = Gtk.FileFilter()
        f.set_name("Google client file (*.json)")
        f.add_pattern("*.json")
        dlg.add_filter(f)
        dl = os.path.expanduser("~/Downloads")
        if os.path.isdir(dl):
            dlg.set_current_folder(dl)
        path = dlg.get_filename() if dlg.run() == Gtk.ResponseType.OK else None
        dlg.destroy()
        if path:
            self.take_file(path)

    def take_file(self, path):
        try:
            with open(path, "rb") as fh:
                save_google_client(self.dialog.win.store, fh.read())
        except Exception as e:
            self.dialog.say("<span foreground='#c42b1c'>%s</span>" % GLib.markup_escape_text(str(e)))
            return False
        self.drop_label.set_markup("<b>✓ Folio Post's Google sign-in is ready.</b>")
        self.on_ready()
        return True

    def done(self):
        for w in self.get_children():
            if w is not self.drop:
                w.hide()


class AccountDialog(Gtk.Dialog):
    """Add Account: the address first, then what the provider needs."""

    def __init__(self, win, account=None):
        Gtk.Dialog.__init__(self, title="Add Account" if account is None else "Change Account", transient_for=win, modal=True)
        self.win = win
        self.account = account
        self.get_style_context().add_class("folio-dialog")
        self.set_default_size(520, -1)
        # the pages go in a box of their own: the content area also holds the dialog's buttons
        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.box.set_border_width(18)
        self.get_content_area().pack_start(self.box, True, True, 0)
        self.result = None
        self.busy = False
        self.cfg = {}
        self.kind = None
        self.cancel = self.add_button("Cancel", Gtk.ResponseType.CANCEL)
        self.back = self.add_button("Back", 1)
        self.ok = self.add_button("Connect", Gtk.ResponseType.OK)
        self.ok.get_style_context().add_class("folio-default")
        self.set_default_response(Gtk.ResponseType.OK)
        self.connect("response", self.on_response)
        self.page = None
        if account is None:
            self.page_email()
        elif account["kind"] == "ews":
            self.cfg = dict(account["config"])
            self.email = account["email"]
            self.display_name = account["name"]
            self.kind = "ews"
            self.page_exchange()
        else:
            self.cfg = dict(account["config"])
            self.kind = "manual"
            self.page_manual()
        self.show_all()
        self.back.set_visible(self.page != "email" and account is None)

    def _clear(self):
        for c in self.box.get_children():
            self.box.remove(c)

    def _title(self, text, sub=None):
        lab = Gtk.Label(xalign=0)
        lab.set_markup("<big><b>%s</b></big>" % GLib.markup_escape_text(text) + ("\n" + GLib.markup_escape_text(sub) if sub else ""))
        lab.set_line_wrap(True)
        lab.set_max_width_chars(60)
        self.box.pack_start(lab, False, False, 4)

    def _note(self, text):
        lab = Gtk.Label(xalign=0)
        lab.set_markup(text)
        lab.set_line_wrap(True)
        lab.set_max_width_chars(64)
        self.box.pack_start(lab, False, False, 2)
        return lab

    def _entry(self, label, value="", visible=True):
        self.box.pack_start(Gtk.Label(label=label, xalign=0), False, False, 0)
        e = Gtk.Entry()
        e.set_text(value or "")
        e.set_visibility(visible)
        e.set_activates_default(True)
        self.box.pack_start(e, False, False, 0)
        return e

    def _status(self):
        self.spinner = Gtk.Spinner()
        self.msg = Gtk.Label(xalign=0)
        self.msg.set_line_wrap(True)
        self.msg.set_max_width_chars(64)
        row = Gtk.Box(spacing=8)
        row.pack_start(self.spinner, False, False, 0)
        row.pack_start(self.msg, True, True, 0)
        self.box.pack_end(row, False, False, 6)

    def say(self, text, busy=False):
        self.msg.set_markup(text)
        (self.spinner.start if busy else self.spinner.stop)()
        self.busy = busy
        self.ok.set_sensitive(not busy)

    # ------------------------------------------------------------ pages
    def page_email(self):
        self._clear()
        self.page = "email"
        self._title(APP_NAME, "Add your e-mail account.")
        self.name_entry = self._entry("Your name (shown to the people you write to)", real_name())
        self.email_entry = self._entry("E-mail address")
        self.exchange_check = Gtk.CheckButton(label="Microsoft Exchange or Microsoft 365 (work or school account)")
        self.box.pack_start(self.exchange_check, False, False, 4)
        self.manual_check = Gtk.CheckButton(label="Let me set up my account manually")
        self.box.pack_start(self.manual_check, False, False, 0)
        self.exchange_check.connect("toggled", lambda b: b.get_active() and self.manual_check.set_active(False))
        self.manual_check.connect("toggled", lambda b: b.get_active() and self.exchange_check.set_active(False))
        self._status()
        self.ok.set_label("Connect")
        self.box.show_all()
        self.email_entry.grab_focus()

    def page_gmail(self):
        self._oauth_page("gmail", "Gmail", "google", "Google")

    def page_microsoft(self):
        self._oauth_page("microsoft", "Outlook.com", "microsoft", "Microsoft")

    def _oauth_page(self, page, title, provider, company):
        """Google: "Sign in with Google" in the web browser (a client ID the user makes once, read from the file Google
        gives), or Online Accounts when it already has this Google account working; an app password as the fallback.
        Microsoft: Online Accounts, or the browser sign-in when a client ID is built in or set."""
        from . import goa
        self._clear()
        self.page = page
        self.provider = provider
        self._title(title, self.email)
        self.password_entry = None
        self.goa_found = None
        if provider == "google":
            self.goa_found = google_goa_account(self.email)
            self.use_goa = self.goa_found is not None
            self.use_browser = not self.use_goa
        else:
            self.use_goa = goa.available()
            self.use_browser = not self.use_goa and bool(self.win.app.tokens.client(provider)[0])
        if provider == "google":
            if self.use_goa:
                self._note("Your Google account is already signed in in Online Accounts. Connect, and that's all.")
            else:
                self.guide = None
                if self.win.app.tokens.client("google")[0]:
                    self._note("<b>Sign in with Google</b> opens Google's sign-in page in your web browser. Sign in there "
                               "(security keys and passkeys work), allow Folio Post, and come back here.")
                else:
                    self.guide = GoogleClientGuide(self, on_ready=self._client_ready)
                    self.box.pack_start(self.guide, False, False, 0)
        elif self.use_goa:
            found = goa.find(self.email, provider)
            if found:
                self._note("Your %s account is in Online Accounts. Connect, and that's all." % company)
            else:
                self._note("Connect opens Settings &gt; Online Accounts. Sign in to %s there and Post picks the "
                           "account up by itself." % company)
        elif self.use_browser:
            self._note("Connect opens %s's sign-in page in your browser." % company)
        if provider == "google":
            self.app_toggle = Gtk.Button(label="Use an app password instead")
            self.app_toggle.set_relief(Gtk.ReliefStyle.NONE)
            self.app_toggle.set_halign(Gtk.Align.START)
            self.box.pack_start(self.app_toggle, False, False, 0)
            pw_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            lab = Gtk.Label(xalign=0)
            lab.set_markup("<small>Make one at <a href=\"https://myaccount.google.com/apppasswords\">myaccount.google.com "
                           "&gt; Security &gt; App passwords</a> (it needs 2-Step Verification). Mail only: Calendar and "
                           "Contacts need Sign in with Google.</small>")
            lab.set_line_wrap(True)
            lab.set_max_width_chars(64)
            pw_box.pack_start(lab, False, False, 0)
            self.password_entry = Gtk.Entry(visibility=False)
            self.password_entry.set_activates_default(True)
            self.password_entry.set_placeholder_text("App password")
            pw_box.pack_start(self.password_entry, False, False, 0)
            self.box.pack_start(pw_box, False, False, 0)
            self.pw_box = pw_box
            self.app_toggle.connect("clicked", lambda *_: (pw_box.show_all(), self.app_toggle.hide(),
                                                           self.ok.set_label("Connect"), self.password_entry.grab_focus()))
        elif not self.use_goa and not self.use_browser:
            self._note("Microsoft lets other mail apps into Outlook.com only through its own sign-in, which Post reaches "
                       "through Settings &gt; Online Accounts. This computer doesn't have Online Accounts (package "
                       "gnome-online-accounts).")
        self._status()
        self.ok.set_label("Sign in with Google" if provider == "google" and self.use_browser else "Connect")
        self.box.show_all()
        if provider == "google":
            self.pw_box.hide()

    def _client_ready(self):
        """The Google client was read from its file: straight on to the sign-in."""
        self.say("")
        if self.guide is not None:
            self.guide.done()
        self.next_gmail()

    def next_gmail(self):
        self._next_oauth(dict(GMAIL), "google")

    def next_microsoft(self):
        self._next_oauth(dict(OUTLOOK), "microsoft")

    def _next_oauth(self, cfg, provider):
        from . import goa
        cfg["user"] = self.email
        if self.password_entry is not None and self.password_entry.get_visible() and self.password_entry.get_text():
            pw = self.password_entry.get_text().replace(" ", "")
            cfg["auth"] = "password"
            cfg.pop("oauth_provider", None)
            self._test(cfg, pw, then=lambda: self._finish(cfg, pw))
            return
        if provider == "google" and self.use_goa and self.goa_found is not None:
            return self._goa_connect(cfg, self.goa_found)
        if provider == "google" and self.use_browser and not self.win.app.tokens.client("google")[0]:
            self.say("First make the app's sign-in for Folio Post (the steps above), then add the file Google gives you.")
            return
        if self.use_goa:
            found = goa.find(self.email, provider)
            if found is None:
                if not getattr(self, "waiting", False):
                    self.waiting = True
                    goa.open_settings()
                    self._wait_goa(cfg, provider, 0)
                self.say("Waiting for the account to appear in Online Accounts...", busy=True)
                self.ok.set_sensitive(True)
                self.busy = False
                return
            return self._goa_connect(cfg, found)
        if self.use_browser:
            return self._browser_sign_in(cfg, provider)
        self.say("Type an app password, or install Online Accounts (gnome-online-accounts).")

    def _wait_goa(self, cfg, provider, n):
        from . import goa
        if not self.get_visible():
            return False
        found = goa.find(self.email, provider)
        if found is not None:
            self.waiting = False
            self._goa_connect(cfg, found)
            return False
        if n > 300:
            self.say("No %s account for %s turned up in Online Accounts." % (provider.capitalize(), self.email))
            return False
        GLib.timeout_add_seconds(2, self._wait_goa, cfg, provider, n + 1)
        return False

    def _goa_connect(self, cfg, found):
        from . import goa
        if not found["mail"]:
            self.say("Mail is switched off for this account in Settings &gt; Online Accounts. Switch it on and Connect again.")
            return
        cfg = dict(cfg, auth="goa", goa_id=found["id"])
        self.say("Connecting...", busy=True)

        def work():
            try:
                tok = goa.token(found["id"])
                err = self.win.app.syncer.test_account(cfg, None, tok)
            except Exception as e:
                err = "Online Accounts didn't give a sign-in: %s" % e
            GLib.idle_add(done, err)

        def done(err):
            self.say("")
            if err:
                self.say("<span foreground='#c42b1c'>%s</span>" % GLib.markup_escape_text(err))
            else:
                self._finish(cfg, tokens=None, oauth_like=True)
            return False
        threading.Thread(target=work, daemon=True).start()

    def _browser_sign_in(self, cfg, provider, kind="imap"):
        cid, sec = self.win.app.tokens.client(provider)
        cfg["auth"] = "oauth"
        cfg["oauth_provider"] = provider
        self.say("Finish signing in in your browser...", busy=True)

        def work():
            try:
                t = oauth.sign_in(cid, sec, login_hint=self.email, provider=provider)
                err = self.win.app.syncer.test_account(cfg, None, t["access_token"], kind)
            except Exception as e:
                t, err = None, "The sign-in didn't finish: %s" % e
            GLib.idle_add(done, t, err)

        def done(t, err):
            self.say("")
            if err:
                self.say("<span foreground='#c42b1c'>%s</span>" % GLib.markup_escape_text(err))
            else:
                self._finish(cfg, tokens=t, kind=kind)
            return False
        threading.Thread(target=work, daemon=True).start()

    # ------------------------------------------------------------ Exchange (M3-01)
    def page_exchange(self):
        self._clear()
        self.page = "exchange"
        c = self.cfg
        self._title("Microsoft Exchange", self.email)
        self._note("Mail, calendar, contacts and tasks, kept the same here and in Outlook.")
        self.ex_ms = Gtk.RadioButton.new_with_label(None, "Sign in with Microsoft (Microsoft 365)")
        self.ex_pw = Gtk.RadioButton.new_with_label_from_widget(self.ex_ms, "Sign in with a password (Exchange in your organisation)")
        self.box.pack_start(self.ex_ms, False, False, 0)
        self.box.pack_start(self.ex_pw, False, False, 0)
        grid = Gtk.Grid(column_spacing=8, row_spacing=6)
        self.ex = {}
        rows = [("url", "Server address (EWS)", c.get("ews_url", "")), ("user", "User name", c.get("user", self.email)),
                ("password", "Password", "")]
        for r, (k, label, v) in enumerate(rows):
            grid.attach(Gtk.Label(label=label, xalign=0), 0, r, 1, 1)
            e = Gtk.Entry(text=v or "")
            e.set_hexpand(True)
            e.set_activates_default(True)
            if k == "password":
                e.set_visibility(False)
                if self.account is not None:
                    e.set_placeholder_text("(unchanged)")
            if k == "url":
                e.set_placeholder_text("Found by itself (Autodiscover); or https://mail.example.com/EWS/Exchange.asmx")
            if k == "user":
                e.set_placeholder_text("name@example.com or DOMAIN\\name")
            grid.attach(e, 1, r, 1, 1)
            self.ex[k] = e
        auth = Gtk.ComboBoxText()
        auth.append("ntlm", "Windows sign-in (NTLM)")
        auth.append("basic", "Basic")
        auth.set_active_id(c.get("ews_auth", "ntlm"))
        grid.attach(Gtk.Label(label="Sign-in method", xalign=0), 0, 3, 1, 1)
        grid.attach(auth, 1, 3, 1, 1)
        self.ex["auth"] = auth
        self.ex_grid = grid
        self.box.pack_start(grid, False, False, 4)
        self.ex_ms.connect("toggled", lambda *_: self._ex_sync())
        (self.ex_pw if c.get("auth") == "password" or (self.account is not None and c.get("auth") != "oauth") else self.ex_ms).set_active(True)
        self._status()
        self.ok.set_label("Save" if self.account else "Connect")
        self.box.show_all()
        self._ex_sync()

    def _ex_sync(self):
        pw = self.ex_pw.get_active()
        for k in ("user", "password", "auth"):
            self.ex[k].set_sensitive(pw)

    def next_exchange(self):
        from . import ews
        url = self.ex["url"].get_text().strip()
        cfg = dict(self.cfg)
        if self.ex_ms.get_active():
            cfg.update({"ews_url": url or ews.OFFICE365, "user": self.email, "auth": "oauth", "oauth_provider": "microsoft"})
            if not self.win.app.tokens.client("microsoft")[0]:
                self.say("Microsoft sign-in needs an app registration (client ID) in File &gt; Options &gt; Accounts.")
                return
            return self._browser_sign_in(cfg, "microsoft", kind="ews")
        user = self.ex["user"].get_text().strip() or self.email
        pw = self.ex["password"].get_text()
        if self.account is not None and not pw:
            pw = self.win.app.secrets.get(self.account["id"])
        cfg.update({"user": user, "auth": "password", "ews_auth": self.ex["auth"].get_active_id()})
        cfg.pop("oauth_provider", None)

        def go(found):
            cfg["ews_url"] = found
            self.ex["url"].set_text(found)
            if self.account is not None:
                def save():
                    self.win.store.update_account(self.account["id"], config=cfg)
                    if self.ex["password"].get_text():
                        self.win.app.secrets.set(self.account["id"], pw)
                    self.result = self.account["id"]
                    self.destroy()
                return self._test(cfg, pw, kind="ews", then=save)
            self._test(cfg, pw, kind="ews", then=lambda: self._finish(cfg, pw, kind="ews"))
        if url:
            return go(url)
        self.say("Looking for the Exchange server...", busy=True)

        def work():
            found = ews.autodiscover(self.email, pw, user)
            GLib.idle_add(done, found)

        def done(found):
            self.say("")
            if not found:
                self.say("Folio Post couldn't find the Exchange server by itself. Type its address (ask whoever runs it, "
                         "or look in Outlook's account settings).")
            else:
                go(found)
            return False
        threading.Thread(target=work, daemon=True).start()

    def page_proton(self):
        self._clear()
        self.page = "proton"
        self._title("Proton Mail", self.email)
        self._note("Proton keeps your mail end-to-end encrypted, so desktop mail apps reach it through <b>Proton Mail "
                   "Bridge</b>, Proton's own app (it needs a paid Proton plan). Install Bridge, sign in there, then copy "
                   "the IMAP/SMTP password Bridge shows for this address.")
        self.password_entry = self._entry("Bridge password", visible=False)
        adv = Gtk.Expander(label="Bridge address and ports (only if you changed them in Bridge)")
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        inner.set_margin_top(6)
        adv.add(inner)
        self.box.pack_start(adv, False, False, 0)
        self.host_entry = Gtk.Entry(text="127.0.0.1")
        self.host_entry.set_activates_default(True)
        inner.pack_start(self.host_entry, False, False, 0)
        row = Gtk.Box(spacing=8)
        self.imap_port_entry = Gtk.SpinButton.new_with_range(1, 65535, 1)
        self.imap_port_entry.set_value(self.cfg.get("imap_port", 1143))
        self.smtp_port_entry = Gtk.SpinButton.new_with_range(1, 65535, 1)
        self.smtp_port_entry.set_value(self.cfg.get("smtp_port", 1025))
        row.pack_start(Gtk.Label(label="IMAP port"), False, False, 0)
        row.pack_start(self.imap_port_entry, False, False, 0)
        row.pack_start(Gtk.Label(label="SMTP port"), False, False, 0)
        row.pack_start(self.smtp_port_entry, False, False, 0)
        inner.pack_start(row, False, False, 0)
        self._note("<small>Bridge uses a certificate of its own. Post trusts the one it finds when you connect and "
                   "refuses any other later.</small>")
        self._status()
        self.ok.set_label("Connect")
        self.box.show_all()

    def page_password(self, note=None):
        self._clear()
        self.page = "password"
        self._title(self.email, "IMAP account")
        if note:
            self._note(note)
        self.password_entry = self._entry("Password", visible=False)
        link = Gtk.Button(label="Change server settings")
        link.set_relief(Gtk.ReliefStyle.NONE)
        link.set_halign(Gtk.Align.START)
        link.connect("clicked", lambda *_: self.page_manual())
        self.box.pack_start(link, False, False, 0)
        self._status()
        self.ok.set_label("Connect")
        self.box.show_all()
        self.password_entry.grab_focus()

    def page_manual(self):
        self._clear()
        self.page = "manual"
        c = self.cfg
        acc = self.account
        self._title("Account Settings" if acc else "IMAP, POP and SMTP", self.email if acc is None else acc["email"])
        grid = Gtk.Grid(column_spacing=8, row_spacing=6)
        self.m = {}

        def add(row, label, w):
            grid.attach(Gtk.Label(label=label, xalign=0), 0, row, 1, 1)
            grid.attach(w, 1, row, 3 if not isinstance(w, Gtk.SpinButton) else 1, 1)
        kind = Gtk.ComboBoxText()
        kind.append("imap", "IMAP")
        kind.append("pop3", "POP3")
        kind.set_active_id((acc or {}).get("kind", "imap") if acc else "imap")
        self.m["kind"] = kind
        add(0, "Account type", kind)
        self.m["name"] = Gtk.Entry(text=(acc["name"] if acc else getattr(self, "display_name", "")) or "")
        add(1, "Your name", self.m["name"])
        r = 2
        for pre, title in (("imap", "Incoming mail"), ("smtp", "Outgoing mail (SMTP)")):
            host = Gtk.Entry(text=c.get(pre + "_host", ""))
            host.set_hexpand(True)
            port = Gtk.SpinButton.new_with_range(1, 65535, 1)
            port.set_value(c.get(pre + "_port") or (993 if pre == "imap" else 465))
            sec = Gtk.ComboBoxText()
            for k, v in SECURITY:
                sec.append(k, v)
            sec.set_active_id(c.get(pre + "_security", "ssl"))
            self.m[pre + "_host"], self.m[pre + "_port"], self.m[pre + "_security"] = host, port, sec
            add(r, title + " server", host)
            grid.attach(Gtk.Label(label="Port", xalign=0), 0, r + 1, 1, 1)
            grid.attach(port, 1, r + 1, 1, 1)
            grid.attach(Gtk.Label(label="Encryption"), 2, r + 1, 1, 1)
            grid.attach(sec, 3, r + 1, 1, 1)
            r += 2
        self.m["user"] = Gtk.Entry(text=c.get("user", "") or (self.email if acc is None else acc["email"]))
        add(r, "User name", self.m["user"])
        self.m["password"] = Gtk.Entry(visibility=False)
        self.m["password"].set_placeholder_text("(unchanged)" if acc else "")
        add(r + 1, "Password", self.m["password"])
        self.m["leave"] = Gtk.CheckButton(label="Leave a copy of messages on the server (POP3)")
        self.m["leave"].set_active(c.get("leave_on_server", True))
        grid.attach(self.m["leave"], 0, r + 2, 4, 1)
        self.m["saves_sent"] = Gtk.CheckButton(label="The server keeps sent messages itself (don't save a copy)")
        self.m["saves_sent"].set_active(c.get("server_saves_sent", False))
        grid.attach(self.m["saves_sent"], 0, r + 3, 4, 1)
        self.box.pack_start(grid, False, False, 4)
        self._status()
        self.ok.set_label("Save" if acc else "Connect")
        self.box.show_all()

    # ------------------------------------------------------------ flow
    def on_response(self, d, resp):
        if self.busy:
            return
        if resp == 1:
            self.page_email()
            self.back.set_visible(False)
            return
        if resp != Gtk.ResponseType.OK:
            self.destroy()
            return
        getattr(self, "next_" + self.page)()
        self.back.set_visible(self.page != "email" and self.account is None)

    def next_email(self):
        email = self.email_entry.get_text().strip()
        if "@" not in email or "." not in email.split("@")[-1]:
            self.say("Type the whole e-mail address, like <i>name@example.com</i>.")
            return
        if any(a["email"].lower() == email.lower() for a in self.win.store.accounts()):
            self.say("This account is already in Folio Post.")
            return
        self.email = email
        self.display_name = self.name_entry.get_text().strip()
        kind, cfg = guess(email)
        self.kind = kind
        self.cfg = cfg
        if self.manual_check.get_active():
            return self.page_manual()
        if self.exchange_check.get_active():
            self.kind = "ews"
            self.cfg = {}
            return self.page_exchange()
        if kind == "gmail":
            return self.page_gmail()
        if kind == "proton":
            return self.page_proton()
        if kind == "microsoft":
            return self.page_microsoft()
        if kind == "app-password":
            return self.page_password("This provider wants an <b>app password</b> made in its account security settings, "
                                      "not your usual password.")
        return self.page_password()

    def _test(self, cfg, password=None, token=None, kind="imap", then=None):
        self.say("Connecting to %s..." % GLib.markup_escape_text(cfg.get("imap_host", "") or
                                                                urllib.parse.urlparse(cfg.get("ews_url", "")).hostname or ""), busy=True)
        syncer = self.win.app.syncer

        def work():
            err = syncer.test_account(cfg, password, token, kind)
            GLib.idle_add(done, err)

        def done(err):
            self.say("")
            if err:
                self.say("<span foreground='#c42b1c'>%s</span>" % GLib.markup_escape_text(err))
            elif then:
                then()
            return False
        threading.Thread(target=work, daemon=True).start()

    def _finish(self, cfg, password=None, tokens=None, kind="imap", oauth_like=False):
        cfg = dict(cfg)
        cfg["user"] = cfg.get("user") or self.email
        self.result = create_account(self.win, self.display_name or self.email, self.email, cfg, password, tokens, kind)
        self.destroy()
        self.win.dialogs.info("Your account %s is set up. Folio Post is getting your mail." % self.email)

    def next_password(self):
        pw = self.password_entry.get_text()
        cfg = dict(self.cfg, user=self.email)
        self._test(cfg, pw, then=lambda: self._finish(cfg, pw))

    def next_proton(self):
        pw = self.password_entry.get_text()
        cfg = dict(PROTON, user=self.email, imap_host=self.host_entry.get_text().strip() or "127.0.0.1",
                   smtp_host=self.host_entry.get_text().strip() or "127.0.0.1",
                   imap_port=int(self.imap_port_entry.get_value()), smtp_port=int(self.smtp_port_entry.get_value()))
        self.say("Looking for Proton Mail Bridge...", busy=True)

        def work():
            try:
                fp = imap.fetch_certificate(cfg["imap_host"], cfg["imap_port"], "imap")
                sfp = imap.fetch_certificate(cfg["smtp_host"], cfg["smtp_port"], "smtp")
                err = None
            except Exception as e:
                fp = sfp = None
                err = ("Folio Post couldn't reach Proton Mail Bridge at %s:%d. Is Bridge running and signed in?"
                       % (cfg["imap_host"], cfg["imap_port"]))
            GLib.idle_add(done, fp, sfp, err)

        def done(fp, sfp, err):
            self.say("")
            if err:
                self.say("<span foreground='#c42b1c'>%s</span>" % GLib.markup_escape_text(err))
                return False
            cfg["cert_sha256"] = fp
            if sfp and sfp != fp:
                cfg["smtp_cert_sha256"] = sfp
            self._test(cfg, pw, then=lambda: self._finish(cfg, pw))
            return False
        threading.Thread(target=work, daemon=True).start()

    def _manual_cfg(self):
        m = self.m
        cfg = dict(self.cfg)
        for pre in ("imap", "smtp"):
            cfg[pre + "_host"] = m[pre + "_host"].get_text().strip()
            cfg[pre + "_port"] = int(m[pre + "_port"].get_value())
            cfg[pre + "_security"] = m[pre + "_security"].get_active_id()
        cfg["user"] = m["user"].get_text().strip()
        cfg["leave_on_server"] = m["leave"].get_active()
        cfg["server_saves_sent"] = m["saves_sent"].get_active()
        return cfg, m["kind"].get_active_id(), m["password"].get_text()

    def next_manual(self):
        cfg, kind, pw = self._manual_cfg()
        if not cfg["imap_host"] or not cfg["smtp_host"]:
            self.say("Fill in both servers.")
            return
        if self.account is not None:
            acc = self.account
            store = self.win.store
            if not pw:
                pw = self.win.app.secrets.get(acc["id"])
            name = self.m["name"].get_text().strip() or acc["name"]

            def save():
                store.update_account(acc["id"], name=name, config=cfg)
                store.x("update accounts set kind=? where id=?", (kind, acc["id"]))
                if self.m["password"].get_text():
                    self.win.app.secrets.set(acc["id"], self.m["password"].get_text())
                self.result = acc["id"]
                self.destroy()
            if cfg.get("auth") == "oauth":
                save()
            else:
                self._test(cfg, pw, kind=kind, then=save)
            return
        self.display_name = self.m["name"].get_text().strip() or getattr(self, "display_name", "")
        self._test(cfg, pw, kind=kind, then=lambda: self._finish(cfg, pw, kind=kind))


def add_account(win):
    return AccountDialog(win)


class AccountSettings(Gtk.Dialog):
    def __init__(self, win, select=None):
        Gtk.Dialog.__init__(self, title="Account Settings", transient_for=win, modal=True)
        self.win = win
        self.get_style_context().add_class("folio-dialog")
        self.set_default_size(560, 360)
        box = self.get_content_area()
        box.set_border_width(12)
        box.set_spacing(8)
        box.pack_start(Gtk.Label(label="E-mail accounts: you can add or remove an account, or change its settings.",
                                 xalign=0), False, False, 0)
        bar = Gtk.Box(spacing=4)
        for label, fn in (("New...", self.new), ("Change...", self.change), ("Set as Default", self.default),
                          ("Remove", self.remove)):
            b = Gtk.Button(label=label)
            b.connect("clicked", lambda *_a, f=fn: f())
            bar.pack_start(b, False, False, 0)
        box.pack_start(bar, False, False, 0)
        self.model = Gtk.ListStore(int, str, str)
        self.tv = Gtk.TreeView(model=self.model)
        self.tv.append_column(Gtk.TreeViewColumn("Name", Gtk.CellRendererText(), text=1))
        self.tv.append_column(Gtk.TreeViewColumn("Type", Gtk.CellRendererText(), text=2))
        self.tv.connect("row-activated", lambda *_: self.change())
        sw = Gtk.ScrolledWindow()
        sw.add(self.tv)
        box.pack_start(sw, True, True, 0)
        self.add_button("Close", Gtk.ResponseType.CLOSE)
        self.connect("response", lambda *_: self.destroy())
        self.fill(select)
        self.show_all()

    def fill(self, select=None):
        self.model.clear()
        for i, a in enumerate(self.win.store.accounts()):
            t = {"imap": "IMAP/SMTP", "pop3": "POP/SMTP", "local": "On this computer"}.get(a["kind"], a["kind"])
            if a["config"].get("bridge"):
                t += " (Proton Mail Bridge)"
            elif a["config"].get("auth") == "oauth":
                t += " (Google sign-in)"
            it = self.model.append([a["id"], a["email"] + (" (sends from this account by default)" if i == 0 else ""), t])
            if a["id"] == select:
                self.tv.get_selection().select_iter(it)

    def selected(self):
        m, it = self.tv.get_selection().get_selected()
        return self.win.store.account(m[it][0]) if it is not None else None

    def new(self):
        d = AccountDialog(self.win)
        d.connect("destroy", lambda *_: self.fill())

    def change(self):
        a = self.selected()
        if a:
            d = AccountDialog(self.win, a)
            d.connect("destroy", lambda *_: self.fill(a["id"]))

    def default(self):
        a = self.selected()
        if a:
            self.win.store.x("update accounts set position=(select min(position) from accounts)-1 where id=?", (a["id"],))
            self.win.store.changed("accounts")
            self.fill(a["id"])

    def remove(self):
        a = self.selected()
        if a and self.win.ask("Remove %s? Its mail stays on the server but is removed from this computer." % a["email"]):
            self.win.store.remove_account(a["id"])
            self.win.folder_id = None
            self.win.refresh_folders()
            self.win.select_first_inbox()
            self.win.refresh_list()
            self.fill()


def account_settings(win, aid=None):
    return AccountSettings(win, aid)


CALDAV_PRESETS = {"fastmail.com": "https://caldav.fastmail.com/dav/", "icloud.com": "https://caldav.icloud.com/",
                  "me.com": "https://caldav.icloud.com/", "gmx.net": "https://caldav.gmx.net/", "gmx.com": "https://caldav.gmx.com/",
                  "yahoo.com": "https://caldav.calendar.yahoo.com/", "zoho.com": "https://calendar.zoho.com/caldav/"}


class CalDavDialog(Gtk.Dialog):
    """Calendars from a CalDAV server (Fastmail, iCloud, Nextcloud, Radicale, ...)."""

    def __init__(self, win):
        Gtk.Dialog.__init__(self, title="Open Calendar from a Server", transient_for=win, modal=True)
        self.win = win
        self.get_style_context().add_class("folio-dialog")
        box = self.get_content_area()
        box.set_border_width(16)
        box.set_spacing(6)
        lab = Gtk.Label(xalign=0)
        lab.set_markup("Your calendar provider's CalDAV address, with your user name and password (an app password where "
                       "the provider asks for one).")
        lab.set_line_wrap(True)
        lab.set_max_width_chars(60)
        box.pack_start(lab, False, False, 4)
        acc = win.current_account()
        dom = (acc["email"].split("@")[-1] if acc else "").lower()
        self.url = Gtk.Entry(text=CALDAV_PRESETS.get(dom, ""))
        self.url.set_placeholder_text("https://example.org/remote.php/dav/")
        self.user = Gtk.Entry(text=acc["email"] if acc else "")
        self.password = Gtk.Entry(visibility=False)
        for label, w in (("Server address", self.url), ("User name", self.user), ("Password", self.password)):
            box.pack_start(Gtk.Label(label=label, xalign=0), False, False, 0)
            box.pack_start(w, False, False, 0)
        self.msg = Gtk.Label(xalign=0)
        self.msg.set_line_wrap(True)
        box.pack_start(self.msg, False, False, 6)
        self.add_button("Cancel", Gtk.ResponseType.CANCEL)
        ok = self.add_button("Connect", Gtk.ResponseType.OK)
        ok.get_style_context().add_class("folio-default")
        self.result = None
        self.busy = False
        self.connect("response", self.on_response)
        self.show_all()

    def on_response(self, d, resp):
        if self.busy:
            return
        if resp != Gtk.ResponseType.OK:
            self.destroy()
            return
        url, user, pw = self.url.get_text().strip(), self.user.get_text().strip(), self.password.get_text()
        if not url.startswith(("http://", "https://")):
            self.msg.set_text("Type the whole address, starting with https://")
            return
        self.busy = True
        self.msg.set_text("Connecting...")

        def work():
            try:
                ids = self.win.app.calsync.add_caldav(url, user, pw)
                for i in ids:
                    self.win.app.calsync.sync(i)
                err = None if ids else "No calendars were found at that address."
            except Exception as e:
                ids, err = [], "Couldn't open the calendars: %s" % e
            GLib.idle_add(done, ids, err)

        def done(ids, err):
            self.busy = False
            if err:
                self.msg.set_markup("<span foreground='#c42b1c'>%s</span>" % GLib.markup_escape_text(err))
                return False
            self.result = ids
            self.win._after_calendars()
            self.destroy()
            return False
        threading.Thread(target=work, daemon=True).start()


class CardDavDialog(CalDavDialog):
    """Address books from a CardDAV server."""

    def __init__(self, win):
        CalDavDialog.__init__(self, win)
        self.set_title("Open Address Book from a Server")
        acc = win.current_account()
        dom = (acc["email"].split("@")[-1] if acc else "").lower()
        self.url.set_text({"fastmail.com": "https://carddav.fastmail.com/dav/", "icloud.com": "https://contacts.icloud.com/",
                           "me.com": "https://contacts.icloud.com/"}.get(dom, ""))

    def on_response(self, d, resp):
        if self.busy:
            return
        if resp != Gtk.ResponseType.OK:
            self.destroy()
            return
        url, user, pw = self.url.get_text().strip(), self.user.get_text().strip(), self.password.get_text()
        if not url.startswith(("http://", "https://")):
            self.msg.set_text("Type the whole address, starting with https://")
            return
        self.busy = True
        self.msg.set_text("Connecting...")

        def work():
            try:
                ids = self.win.app.contactsync.add_carddav(url, user, pw)
                for i in ids:
                    self.win.app.contactsync.sync(i)
                err = None if ids else "No address books were found at that address."
            except Exception as e:
                ids, err = [], "Couldn't open the address books: %s" % e
            GLib.idle_add(done, ids, err)

        def done(ids, err):
            self.busy = False
            if err:
                self.msg.set_markup("<span foreground='#c42b1c'>%s</span>" % GLib.markup_escape_text(err))
                return False
            self.result = ids
            self.win._after_books()
            self.destroy()
            return False
        threading.Thread(target=work, daemon=True).start()
