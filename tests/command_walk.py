# Run inside Folio Post (FOLIO_TEST_SCRIPT): every command on the ribbons and in their menus — the main window
# with a message selected and with none, the message window and the compose window; every dialog answered OK,
# then Cancel. Nothing may raise. Writes the list of commands and which are not available yet.
import os
import sys
import time
import traceback

from gi.repository import Gtk

sys.path.insert(0, os.environ["FOLIO_TESTS"])
import mailserver  # noqa: E402

ERRORS = []
_hook = sys.excepthook
sys.excepthook = lambda t, v, tb: (ERRORS.append("".join(traceback.format_exception(t, v, tb))), _hook(t, v, tb))


def pump(t=0.02):
    end = time.time() + t
    while time.time() < end:
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)
        time.sleep(0.002)


def wait(cond, t=20):
    end = time.time() + t
    while time.time() < end:
        pump(0.05)
        if cond():
            return True
    return False


answer = [Gtk.ResponseType.OK]


def fake_run(d):
    pump(0.01)
    n = getattr(d, "_walk_runs", 0)
    d._walk_runs = n + 1
    return answer[0] if n == 0 else Gtk.ResponseType.CANCEL


from folio_post import dialogs as D  # noqa: E402
from folio_post import window as W  # noqa: E402
Gtk.Dialog.run = fake_run
Gtk.MessageDialog.run = fake_run
Gtk.NativeDialog.run = lambda d: Gtk.ResponseType.CANCEL
Gtk.PrintOperation.run = lambda *a: Gtk.PrintOperationResult.CANCEL
Gtk.Menu.popup_at_pointer = lambda *a: None
Gtk.Menu.popup_at_widget = lambda *a: None
D.Dialogs.message = lambda self, text, title=None: ERRORS.append("dialog: " + text) if "went wrong" in text else None
D.Dialogs.info = lambda self, text, title=None: None
D.Dialogs.ask_text = lambda self, title, label, value="": (value or "Walk") if answer[0] == Gtk.ResponseType.OK else None

store = app.store
world = mailserver.World()
boxes = world.add_user("me@example.org", "secret")
for i in range(40):
    boxes["INBOX"].add(mailserver.sample(i, html=i % 5 == 0, attach=i % 7 == 0))
_w, ip, sp, stop = mailserver.start(world)
cfg = {"imap_host": "127.0.0.1", "imap_port": ip, "imap_security": "none", "smtp_host": "127.0.0.1", "smtp_port": sp,
       "smtp_security": "none", "user": "me@example.org"}
from folio_post.accounts import create_account  # noqa: E402
from folio_post.ribbon_post import Cmd  # noqa: E402
aid = create_account(win, "Me", "me@example.org", cfg, "secret")
wait(lambda: store.folder_by_role(aid, "inbox") and len(store.messages(store.folder_by_role(aid, "inbox")["id"])) == 40, 30)
wait(lambda: not app.busy(), 10)
pump(0.5)
inbox = store.folder_by_role(aid, "inbox")
SKIP = {"exit", "close", "help", "shortcuts", "about"}


def commands(ribbon, extra=()):
    out = []

    def walk_menu(items):
        for it in items:
            if isinstance(it, tuple) and len(it) >= 2:
                if isinstance(it[1], Cmd):
                    out.append(it[1].cmd)
                elif isinstance(it[1], list):
                    walk_menu(it[1])
    for c in ribbon.controls:
        a = getattr(c, "action", None)
        if isinstance(a, str):
            out.append(a)
        m = getattr(c, "menu", None)
        if isinstance(m, list):
            walk_menu(m)
    out += list(extra)
    seen = []
    for c in out:
        if c not in seen and c.split(":")[0] not in SKIP:
            seen.append(c)
    return seen


def cleanup(keep=()):
    for w in Gtk.Window.list_toplevels():
        if w in keep or w is win:
            continue
        if isinstance(w, Gtk.Dialog) or w.get_title() in ("Screen Recording",) or type(w).__name__ == "MessageWindow":
            try:
                w.destroy()
            except Exception:
                pass
    for c in list(app.composers):
        if c not in keep:
            c.modified = False
            c.destroy_window()
    if win.backstage.get_visible():
        win.backstage.close()


def ensure_mail():
    win.go_folder(inbox["id"])
    if len(store.messages(inbox["id"])) < 10:
        for i in range(10):
            store.add_message(inbox["id"], mailserver.sample(100 + i), 0, [])
        store.changed("messages")
        pump(0.3)


def state(k):
    ensure_mail()
    win._do_refresh()
    if k == 1:
        win.list_view.get_selection().unselect_all()
    else:
        rows = win.iter_rows()
        if rows:
            win.select_ids([rows[min(3, len(rows) - 1)][0]])
    pump(0.01)


# ---------------------------------------------------------------- main window
extra = ["move:%d" % inbox["id"], "quick-step:0", "quick-step:1", "categorize:Red", "send-receive:%d" % aid,
         "account-settings:%d" % aid, "new-folder:account:%d" % aid, "options:reading", "empty-trash", "signatures",
         "delete-permanently", "move-other", "copy-other", "go-folder", "save-attachments", "save-as", "print", "open",
         "import-export", "new-quick-step", "manage-quick-steps", "rule-from", "go:calendar", "go:people", "go:tasks", "copy",
         "undo", "add-account", "account-settings", "options", "open-item", "close-items", "zoom"]
main_cmds = commands(win.ribbon, extra)
ran = 0
for cmd in main_cmds:
    for k, resp in enumerate((Gtk.ResponseType.OK, Gtk.ResponseType.CANCEL, Gtk.ResponseType.OK)):
        state(k)
        answer[0] = resp
        try:
            win.run(cmd)
        except Exception:
            ERRORS.append(cmd + ": " + traceback.format_exc())
        cleanup()
        if app.syncer.offline:
            app.set_offline(False)
        ran += 1
        pump(0.01)
wait(lambda: not app.busy(), 20)

# ---------------------------------------------------------------- message window
state(0)
from folio_post.msgwindow import MessageWindow  # noqa: E402
mw_cmds = None
for k in range(2):
    state(0)
    mid = win.selected_ids()[0]
    mw = MessageWindow(win, mid)
    pump(0.2)
    if mw_cmds is None:
        mw_cmds = commands(mw.ribbon, ["previous", "next", "save-attachments", "close"])
    for cmd in mw_cmds:
        if not mw.get_visible() or mw.mid is None or store.message(mw.mid) is None:
            mw.destroy()
            state(0)
            mw = MessageWindow(win, win.selected_ids()[0])
            pump(0.1)
        answer[0] = (Gtk.ResponseType.OK, Gtk.ResponseType.CANCEL)[k]
        try:
            mw.run(cmd)
        except Exception:
            ERRORS.append("message window " + cmd + ": " + traceback.format_exc())
        cleanup(keep=(mw,))
        ran += 1
    try:
        mw.destroy()
    except Exception:
        pass

# ---------------------------------------------------------------- compose window
cw_cmds = None
for k in range(2):
    state(0)
    c = app.compose(reply_to=win.selected_ids()[0], mode="reply", account=aid)
    pump(0.2)
    if cw_cmds is None:
        cw_cmds = commands(c.ribbon, ["font:DejaVu Sans", "size:14", "color:FF0000", "highlight:FFFF00", "insert-signature:Walk",
                                      "delay-delivery", "direct-replies", "properties", "save-as", "print", "redo"])
        cw_cmds = [x for x in cw_cmds if x != "send"] + ["send"]
    for cmd in cw_cmds:
        if c not in app.composers:
            c = app.compose(account=aid, to="me@example.org", subject="walk")
            pump(0.1)
        answer[0] = (Gtk.ResponseType.OK, Gtk.ResponseType.CANCEL)[k]
        c.editor.buf.insert_at_cursor("text ")
        b = c.editor.buf
        b.select_range(b.get_start_iter(), b.get_iter_at_offset(4))
        try:
            c.run(cmd)
        except Exception:
            ERRORS.append("compose " + cmd + ": " + traceback.format_exc())
        cleanup(keep=(c,))
        ran += 1
    cleanup()
wait(lambda: not app.busy(), 20)

missing = sorted(set(c.split(":", 1)[1] if c.startswith("not-available:") else c
                     for c in win.missing_log))
out = os.environ.get("WALK_OUT", "/tmp/post-command-walk.tsv")
with open(out, "w") as f:
    for where, cmds in (("main", main_cmds), ("message", mw_cmds), ("compose", cw_cmds)):
        for c in cmds:
            status = "NOT_YET" if c.startswith("not-available:") else "OK"
            f.write("%s\t%s\t%s\n" % (where, c, status))
print("commands:", len(main_cmds) + len(mw_cmds) + len(cw_cmds), "runs:", ran)
print("not available yet:", len([1 for cmds in (main_cmds, mw_cmds, cw_cmds) for c in cmds if c.startswith("not-available:")]))
print("unavailable in use:", missing)
stop()
if ERRORS:
    for e in ERRORS[:20]:
        print("ERROR", e)
    print("WALK FAILED: %d errors" % len(ERRORS))
    sys.stdout.flush()
    os._exit(1)
print("WALK OK")
sys.stdout.flush()
os._exit(0)
