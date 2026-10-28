# Run inside Folio Post (FOLIO_TEST_SCRIPT): OpenPGP — encrypted and signed mail out and in.
import os
import subprocess
import sys
import tempfile
import time
import traceback

from gi.repository import Gtk

sys.path.insert(0, os.environ["FOLIO_TESTS"])
import mailserver  # noqa: E402

FAILS = []
INFO = []


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


from folio_post import dialogs as D  # noqa: E402
D.Dialogs.info = lambda self, text, title=None: INFO.append(text)
D.Dialogs.message = lambda self, text, title=None: INFO.append(text)
Gtk.Dialog.run = lambda d: Gtk.ResponseType.YES if isinstance(d, Gtk.MessageDialog) else Gtk.ResponseType.CANCEL

try:
    from folio_post import mime, pgp
    if pgp.gpg() is None:
        print("gpg missing: skipped")
        raise SystemExit
    os.environ["GNUPGHOME"] = tempfile.mkdtemp()
    os.chmod(os.environ["GNUPGHOME"], 0o700)
    for who in ("Me <me@example.org>", "Bob <bob@example.org>"):
        subprocess.run(["gpg", "--batch", "--passphrase", "", "--quick-gen-key", who, "default", "default", "never"],
                       capture_output=True)
    check(pgp.has_key("me@example.org", secret=True) and pgp.has_key("bob@example.org"), "test keys made")
    store = app.store
    mw = mailserver.World()
    boxes = mw.add_user("me@example.org", "secret")
    _m, ip, sp, mstop = mailserver.start(mw)
    cfg = {"imap_host": "127.0.0.1", "imap_port": ip, "imap_security": "none", "smtp_host": "127.0.0.1", "smtp_port": sp,
           "smtp_security": "none", "user": "me@example.org"}
    from folio_post.accounts import create_account
    aid = create_account(win, "Me", "me@example.org", cfg, "secret")
    wait(lambda: store.folder_by_role(aid, "inbox") is not None, 20)
    wait(lambda: not app.busy(), 10)
    # encrypted and signed
    c = app.compose(account=aid, to="bob@example.org", subject="Secret plans")
    pump(0.3)
    c.editor.buf.insert_at_cursor("The cake is in the oven.")
    c.run("toggle-encrypt")
    c.run("toggle-sign")
    c.run("send")
    ok = wait(lambda: any(b"Secret plans" in r for _f, _r, r in mw.smtp_log), 20)
    check(ok, "encrypted message sent")
    raw = [r for _f, _r, r in mw.smtp_log if b"Secret plans" in r][-1]
    check(b"multipart/encrypted" in raw and b"BEGIN PGP MESSAGE" in raw and b"cake is in the oven" not in raw, "PGP/MIME, nothing in the clear")
    msg, note = pgp.open_message(raw)
    check("cake is in the oven" in (mime.text_of(msg) or "") and note and note.startswith("Encrypted") and "good signature" in note,
          "it opens again: %s" % note)
    # signed only, arriving by mail, shown in the Reading Pane
    c = app.compose(account=aid, to="me@example.org", subject="Signed note")
    pump(0.3)
    c.editor.buf.insert_at_cursor("Please check this signature.")
    c.run("toggle-sign")
    c.run("send")
    ok = wait(lambda: any(b"Signed note" in r for _f, _r, r in mw.smtp_log), 20)
    raw = [r for _f, _r, r in mw.smtp_log if b"Signed note" in r][-1]
    check(b"multipart/signed" in raw and b"BEGIN PGP SIGNATURE" in raw, "signed message")
    msg, note = pgp.open_message(raw)
    check(note and "good signature" in note, "the signature checks: %s" % note)
    tampered = raw.replace(b"Please check this signature.", b"Please check this signaturE.")
    msg, note = pgp.open_message(tampered)
    check(note and "NOT" in note, "a changed message is caught: %s" % note)
    win.run("send-receive")
    inbox = store.folder_by_role(aid, "inbox")
    ok = wait(lambda: any(r["subject"] == "Signed note" for r in store.messages(inbox["id"])), 20)
    pump(0.4)
    m = [r for r in store.messages(inbox["id"]) if r["subject"] == "Signed note"][0]
    win.go_folder(inbox["id"])
    win.select_ids([m["id"]])
    pump(0.3)
    check("good signature" in win.reading.info.get_text() and "Please check" in win.reading.view.text(), "the Reading Pane shows it")
    # no key for a recipient
    c = app.compose(account=aid, to="carol@example.org", subject="No key")
    pump(0.3)
    c.run("toggle-encrypt")
    INFO.clear()
    check(c.run("send") is False and any("carol@example.org" in t for t in INFO), "a recipient without a key is named")
    c.modified = False
    c.destroy_window()
    mstop()
except SystemExit:
    pass
except Exception:
    traceback.print_exc()
    FAILS.append("exception")
print("UI FAILS: %d" % len(FAILS) if FAILS else "UI all passed")
sys.stdout.flush()
os._exit(1 if FAILS else 0)
