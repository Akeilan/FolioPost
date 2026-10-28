# Run inside Folio Post (FOLIO_TEST_SCRIPT): search folders, moving and copying folders, import and export.
import os
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
from folio_post import window as W  # noqa: E402
ANSWERS = []
D.Dialogs.info = lambda self, text, title=None: INFO.append(text)
D.Dialogs.message = lambda self, text, title=None: INFO.append(text)
D.Dialogs.ask_text = lambda self, title, label, value="": ANSWERS.pop(0) if ANSWERS else value
W.PostWindow.ask = lambda self, text, yes="Yes", no="No": True
Gtk.Dialog.run = lambda d: Gtk.ResponseType.CANCEL

try:
    store = app.store
    mw = mailserver.World()
    boxes = mw.add_user("me@example.org", "secret")
    for i in range(6):
        boxes["INBOX"].add(mailserver.sample(i, attach=i == 2, frm="Bob Stone <bob@example.org>" if i % 2 else "Ann Lee <ann@example.org>"),
                           ["\\Seen"] if i > 2 else [])
    _m, ip, sp, mstop = mailserver.start(mw)
    cfg = {"imap_host": "127.0.0.1", "imap_port": ip, "imap_security": "none", "smtp_host": "127.0.0.1", "smtp_port": sp,
           "smtp_security": "none", "user": "me@example.org"}
    from folio_post.accounts import create_account
    aid = create_account(win, "Me", "me@example.org", cfg, "secret")
    wait(lambda: store.folder_by_role(aid, "inbox") and len(store.messages(store.folder_by_role(aid, "inbox")["id"])) == 6, 20)
    wait(lambda: not app.busy(), 10)
    pump(0.4)
    inbox = store.folder_by_role(aid, "inbox")
    # search folders
    sid = win.run("new-search-folder:unread")
    pump(0.3)
    check(sid == -1 and len(win.iter_rows()) == 3, "Unread Mail search folder: %d" % len(win.iter_rows()))
    labels = []
    win.folders_model.foreach(lambda m, p, it: labels.append(m[it][0]))
    check(any("Search Folders" in l for l in labels), "Search Folders in the Folder Pane")
    sid2 = win.run("new-search-folder:from:bob")
    pump(0.3)
    check(len(win.iter_rows()) == 3 and all(store.message(i)["from_addr"] == "bob@example.org" for i, _ in win.iter_rows()),
          "From Bob search folder")
    win.run("new-search-folder:attach")
    check(len(win.iter_rows()) == 1, "with attachments")
    win.run("delete-folder")
    check(len(store.get("search-folders")) == 2, "a search folder deleted")
    # folders: make, move, copy
    win.go_folder(inbox["id"])
    ANSWERS[:] = ["Projects"]
    pfid = win.run("new-folder:account:%d" % aid)
    ANSWERS[:] = ["Old"]
    ofid = win.run("new-folder:account:%d" % aid)
    win.go_folder(inbox["id"])
    win.select_ids([win.iter_rows()[0][0]])
    win.run("move:%d" % ofid)
    time.sleep(1.5)
    wait(lambda: not app.busy(), 10)
    win.go_folder(ofid)
    win.choose_folder = lambda title="": pfid
    newpath = win.run("move-folder")
    check(newpath == "Projects/Old" and store.folder(ofid)["path"] == "Projects/Old", "Move Folder: %s" % newpath)
    check("Projects/Old" in mw.users["me@example.org"][1], "moved on the server")
    win.go_folder(ofid)
    win.choose_folder = lambda title="": ofid
    cid = win.run("copy-folder")
    check(cid and store.folder(cid)["path"] == "Projects/Old/Old" and len(store.messages(cid)) == 1, "Copy Folder")
    # export and import mbox, eml
    d = tempfile.mkdtemp()
    win.go_folder(inbox["id"])
    from folio_post import importexport
    n = importexport.import_export(win, "export-mbox", os.path.join(d, "inbox.mbox"))
    check(n == len(store.messages(inbox["id"])) and os.path.getsize(os.path.join(d, "inbox.mbox")) > 500, "export to .mbox")
    from folio_post import importexport
    n = importexport.import_mbox(win, os.path.join(d, "inbox.mbox"))
    loc = [f for f in store.folders() if f["path"] == "inbox"]
    check(n >= 5 and loc and len(store.messages(loc[0]["id"])) == n, "import a .mbox into a folder on this computer")
    p = os.path.join(d, "one.eml")
    open(p, "wb").write(mailserver.sample(50, subject="From a file"))
    win.go_folder(pfid)
    n = importexport.import_eml(win, p)
    check(n == 1 and any(r["subject"] == "From a file" for r in store.messages(pfid)), "import .eml into the current folder")
    time.sleep(1.5)
    wait(lambda: not app.busy(), 10)
    wait(lambda: len(mw.users["me@example.org"][1]["Projects"].msgs) == 1, 10)
    check(len(mw.users["me@example.org"][1]["Projects"].msgs) == 1, "and onto the server")
    # tools that may be missing say so
    import shutil
    if not shutil.which("readpst"):
        INFO.clear()
        importexport.import_export(win, "import-pst", os.path.join(d, "x.pst"))
        check(any("pst-utils" in t for t in INFO), ".pst import says what to install")
    if not shutil.which("msgconvert"):
        INFO.clear()
        open(os.path.join(d, "x.msg"), "wb").write(b"x")
        win.open_message_file(os.path.join(d, "x.msg"))
        check(any("libemail-outlook-message-perl" in t for t in INFO), ".msg says what to install")
    mstop()
except Exception:
    traceback.print_exc()
    FAILS.append("exception")
print("UI FAILS: %d" % len(FAILS) if FAILS else "UI all passed")
sys.stdout.flush()
os._exit(1 if FAILS else 0)
