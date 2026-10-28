# Run inside Folio Post (FOLIO_TEST_SCRIPT): S/MIME — a certificate imported, signed and encrypted mail out and in.
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
    from folio_post import mime, smime
    if smime.openssl() is None:
        print("openssl missing: skipped")
        raise SystemExit
    os.environ["FOLIO_POST_SMIME"] = tempfile.mkdtemp()
    d = tempfile.mkdtemp()

    def make(addr, name):
        key, crt, p12 = [os.path.join(d, name + x) for x in (".key", ".crt", ".p12")]
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", key, "-out", crt, "-days", "30",
                        "-subj", "/CN=%s/emailAddress=%s" % (name, addr), "-addext", "subjectAltName=email:%s" % addr],
                       capture_output=True, check=True)
        subprocess.run(["openssl", "pkcs12", "-export", "-in", crt, "-inkey", key, "-out", p12, "-passout", "pass:pw"],
                       capture_output=True, check=True)
        return crt, p12
    _mc, mp12 = make("me@example.org", "Me")
    bc, _bp = make("bob@example.org", "Bob")
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
    inbox = store.folder_by_role(aid, "inbox")
    win.go_folder(inbox["id"])
    cert = win.run("import-certificate:%s" % mp12) if False else win.act_import_certificate(mp12, "pw")
    check(cert and smime.has_mine("me@example.org"), "my certificate imported from a .p12")
    # signed to myself: arrives, checks, and teaches Post my certificate
    c = app.compose(account=aid, to="me@example.org", subject="Signed S/MIME")
    pump(0.3)
    c.editor.buf.insert_at_cursor("Signed with a certificate.")
    c.run("toggle-sign")
    c.run("send")
    ok = wait(lambda: any(b"Signed S/MIME" in r for _f, _r, r in mw.smtp_log), 20)
    raw = [r for _f, _r, r in mw.smtp_log if b"Signed S/MIME" in r][-1]
    check(b"pkcs7-signature" in raw, "S/MIME signed message")
    msg, note = smime.open_message(raw, ["me@example.org"])
    check(note and note.startswith("Signed") and "Signed with a certificate." in (mime.text_of(msg) or ""), "it checks: %s" % note)
    bad = raw.replace(b"Signed with a certificate.", b"Signed with a certificatE.")
    msg, note = smime.open_message(bad, ["me@example.org"])
    check(note and "NOT" in note, "a changed message is caught")
    # encrypted to Bob (his certificate known)
    import shutil
    shutil.copyfile(bc, os.path.join(os.environ["FOLIO_POST_SMIME"], "bob@example.org.crt"))
    c = app.compose(account=aid, to="bob@example.org", subject="Encrypted S/MIME")
    pump(0.3)
    c.editor.buf.insert_at_cursor("Only Bob reads this.")
    c.run("toggle-encrypt")
    c.run("send")
    ok = wait(lambda: any(b"Encrypted S/MIME" in r for _f, _r, r in mw.smtp_log), 20)
    raw = [r for _f, _r, r in mw.smtp_log if b"Encrypted S/MIME" in r][-1]
    check(b"pkcs7-mime" in raw and b"Only Bob" not in raw, "S/MIME encrypted, nothing in the clear")
    msg, note = smime.open_message(raw, ["me@example.org"])
    check("Only Bob reads this." in (mime.text_of(msg) or "") and note.startswith("Encrypted"), "and I can read my copy: %s" % note)
    # in the Reading Pane
    win.run("send-receive")
    ok = wait(lambda: any(r["subject"] == "Signed S/MIME" for r in store.messages(inbox["id"])), 20)
    pump(0.4)
    m = [r for r in store.messages(inbox["id"]) if r["subject"] == "Signed S/MIME"][0]
    win.select_ids([m["id"]])
    pump(0.3)
    check("Signed" in win.reading.info.get_text() and "Signed with a certificate" in win.reading.view.text(), "the Reading Pane shows it")
    mstop()
except SystemExit:
    pass
except Exception:
    traceback.print_exc()
    FAILS.append("exception")
print("UI FAILS: %d" % len(FAILS) if FAILS else "UI all passed")
sys.stdout.flush()
os._exit(1 if FAILS else 0)
