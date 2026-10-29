# Run inside Folio Post (FOLIO_TEST_SCRIPT): Gmail's "Sign in with Google" in the web browser — the first-run
# guide, reading the client file Google gives, the browser sign-in (loopback + PKCE, against the test OAuth
# server), the token kept for Calendar and Contacts, and Online Accounts only when it really works.
import json
import os
import sys
import tempfile
import time
import traceback

from gi.repository import Gtk

sys.path.insert(0, os.environ["FOLIO_TESTS"])
import mailserver  # noqa: E402
import oauthstub  # noqa: E402

FAILS = []
INFO = []
OUT = os.environ.get("UI_OUT", "/tmp/ui_out")
os.makedirs(OUT, exist_ok=True)


def pump(t=0.15):
    end = time.time() + t
    while time.time() < end:
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)
        time.sleep(0.003)


def wait(cond, t=20):
    end = time.time() + t
    while time.time() < end:
        pump(0.05)
        try:
            if cond():
                return True
        except Exception:
            pass
    return False


def check(cond, what):
    print(("ok   " if cond else "FAIL ") + what)
    sys.stdout.flush()
    if not cond:
        FAILS.append(what)


def shot(w, name):
    import cairo
    pump(0.3)
    alloc = w.get_allocation()
    img = cairo.ImageSurface(cairo.FORMAT_ARGB32, max(1, alloc.width), max(1, alloc.height))
    w.draw(cairo.Context(img))
    img.write_to_png(os.path.join(OUT, "google_" + name + ".png"))


from folio_post import dialogs as D  # noqa: E402
D.Dialogs.info = lambda self, text, title=None: INFO.append(text)
D.Dialogs.message = lambda self, text, title=None: INFO.append(text)

try:
    from folio_post import accounts, goa
    store = app.store
    ow, obase, ostop = oauthstub.start()
    os.environ["FOLIO_POST_OAUTH_BASE"] = obase
    os.environ["FOLIO_POST_TEST_BROWSER"] = "1"
    mw = mailserver.World()
    mw.add_user("me@gmail.com", "unused")
    mw.users["me@gmail.com"][1]["INBOX"].add(mailserver.sample(1, to="me@gmail.com"))
    _m, ip, sp, mstop = mailserver.start(mw)
    accounts.GMAIL.update({"imap_host": "127.0.0.1", "imap_port": ip, "imap_security": "none", "smtp_host": "127.0.0.1",
                           "smtp_port": sp, "smtp_security": "none"})
    # Online Accounts has no working Google account here: it must not be the way in
    goa.available = lambda: True
    goa.find = lambda email, provider=None: {"id": "g1", "email": email, "provider": "google", "mail": True}

    def broken(_i):
        raise RuntimeError("Google rejected the embedded sign-in")
    goa.token = broken
    opened = []
    goa.open_settings = lambda: opened.append(1)
    check(accounts.google_goa_account("me@gmail.com") is None, "Online Accounts' Google entry without a token isn't used")
    d = accounts.AccountDialog(win)
    d.name_entry.set_text("Me")
    d.email_entry.set_text("me@gmail.com")
    d.on_response(d, Gtk.ResponseType.OK)
    pump(0.3)
    check(d.page == "gmail" and d.use_browser and not d.use_goa, "Gmail: Sign in with Google in the browser")
    check(d.ok.get_label() == "Sign in with Google", "the button says Sign in with Google")
    g = d.guide
    check(g is not None and len(g.steps) == 5 and "console.cloud.google.com" in g.steps[0].get_label() and
          "gmail.googleapis.com" in g.steps[1].get_label() and "In production" in g.steps[2].get_label() and
          "Desktop app" in g.steps[3].get_label() and "Download JSON" in g.steps[4].get_label(),
          "no client yet: the five steps, with links")
    check(d.app_toggle.get_visible() and not d.pw_box.get_visible(), "the app password stays as a fallback link")
    shot(d, "guide")
    # Sign in before the client is there: told what to do, nothing opened
    d.on_response(d, Gtk.ResponseType.OK)
    pump(0.2)
    check("First make the app's sign-in" in d.msg.get_label() and not opened, "Sign in without the client file says what's missing")
    tmp = tempfile.mkdtemp()
    bad = os.path.join(tmp, "web.json")
    json.dump({"web": {"client_id": "9-x.apps.googleusercontent.com", "client_secret": "y"}}, open(bad, "w"))
    check(not g.take_file(bad) and "Desktop app" in d.msg.get_label(), "a Web application client is refused, saying why")
    good = os.path.join(tmp, "client_secret_123-abc.apps.googleusercontent.com.json")
    json.dump({"installed": {"client_id": ow.client_id, "project_id": "folio", "client_secret": ow.secret,
                             "redirect_uris": ["http://localhost"]}}, open(good, "w"))
    n0 = len(store.accounts())
    check(g.take_file(good), "the downloaded client file is read")
    check(store.get("google-client") == {"id": ow.client_id, "secret": ow.secret}, "and kept as Post's Google client")
    ok = wait(lambda: len(store.accounts()) == n0 + 1, 30)
    check(ok, "straight on to the browser sign-in, and the account is added")
    auths = [q for k, q in ow.log if k == "auth"]
    check(auths and auths[0]["code_challenge_method"] == "S256" and auths[0]["redirect_uri"].startswith("http://127.0.0.1:") and
          "gmail.settings.basic" in auths[0]["scope"] and "auth/calendar" in auths[0]["scope"] and "carddav" in auths[0]["scope"]
          and auths[0]["login_hint"] == "me@gmail.com", "loopback redirect, PKCE, Gmail + Calendar + Contacts scopes")
    acc = [a for a in store.accounts() if a["email"] == "me@gmail.com"][0]
    check(acc["config"].get("auth") == "oauth" and acc["config"].get("oauth_provider") == "google" and not opened,
          "signed in with Google, Online Accounts never opened")
    check(app.tokens(acc) == "test-token", "the token Mail, Calendar and Contacts use")
    tk = json.loads(app.secrets.get(acc["id"], "oauth"))
    tk["expires_at"] = 0
    app.secrets.set(acc["id"], json.dumps(tk), "oauth")
    check(app.tokens(acc) == "test-token" and any(q.get("grant_type") == "refresh_token" for k, q in ow.log if k == "token"),
          "an expired token is refreshed with the same client")
    ok = wait(lambda: store.folder_by_role(acc["id"], "inbox") and store.messages(store.folder_by_role(acc["id"], "inbox")["id"]), 30)
    check(ok, "mail arrives over XOAUTH2")
    # A second Gmail address: the client is there now, so it's one click
    d2 = accounts.AccountDialog(win)
    d2.email_entry.set_text("other@gmail.com")
    d2.on_response(d2, Gtk.ResponseType.OK)
    pump(0.3)
    check(d2.guide is None and "Sign in with Google" in d2.ok.get_label(), "with the client set, no guide: one button")
    shot(d2, "ready")
    d2.destroy()
    # Online Accounts that does work for the address is used
    goa.token = lambda _i: "goa-token"
    d3 = accounts.AccountDialog(win)
    d3.email_entry.set_text("third@gmail.com")
    d3.on_response(d3, Gtk.ResponseType.OK)
    pump(0.3)
    check(d3.use_goa and d3.goa_found["id"] == "g1" and d3.ok.get_label() == "Connect", "a working Online Accounts entry is used")
    d3.destroy()
    mstop()
    ostop()
except Exception:
    traceback.print_exc()
    FAILS.append("exception")
print("UI FAILS: %d" % len(FAILS) if FAILS else "UI all passed")
sys.stdout.flush()
os._exit(1 if FAILS else 0)
