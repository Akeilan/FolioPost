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
        c.editor.insert_text("text ")
        c.editor.select_offsets(0, 4)
        try:
            c.run(cmd)
        except Exception:
            ERRORS.append("compose " + cmd + ": " + traceback.format_exc())
        cleanup(keep=(c,))
        ran += 1
    cleanup()
wait(lambda: not app.busy(), 20)

# ---------------------------------------------------------------- calendar
import datetime as dt  # noqa: E402
from folio_post import ical, caldav as CD  # noqa: E402
win.run("go:calendar")
pump(0.2)
v = win.calview
cid = v.default_calendar()["id"]
L = ical.local_tz()


def cal_state(k):
    if win.module != "calendar":
        win.run("go:calendar")
    v.go(dt.date(2026, 11, 3))
    if not v.instances:
        CD.save_event(store, cid, [ical.new_event("Walk", dt.datetime(2026, 11, 3, 10, tzinfo=L), dt.datetime(2026, 11, 3, 11, tzinfo=L))])
        CD.save_event(store, cid, [ical.new_event("Series", dt.datetime(2026, 11, 2, 9, tzinfo=L), dt.datetime(2026, 11, 2, 10, tzinfo=L),
                                                  rrule="FREQ=DAILY;COUNT=5")])
        win.calendar_changed()
    v.selected = v.instances[0] if (k == 0 and v.instances) else None
    v.slot = (dt.datetime(2026, 11, 4, 9, tzinfo=L), dt.datetime(2026, 11, 4, 10, tzinfo=L)) if k == 2 else None
    for r in v.cal_list.get_children():
        if getattr(r, "cal_id", None) == cid:
            v.cal_list.select_row(r)


cal_cmds = commands(win.cal_ribbon, ["open-event", "open-event:series", "open-event:occurrence", "delete-event:occurrence",
                                     "event-busy:free", "cal-prev", "cal-next", "cal-go-to", "new-all-day", "cal-folder-pane:off",
                                     "cal-folder-pane:normal"])
cal_cmds = [c for c in cal_cmds if c not in ("delete-calendar",)] + ["delete-event", "delete-calendar"]
for cmd in cal_cmds:
    for k, resp in enumerate((Gtk.ResponseType.OK, Gtk.ResponseType.CANCEL, Gtk.ResponseType.OK)):
        cal_state(k)
        answer[0] = resp
        try:
            win.run(cmd)
        except Exception:
            ERRORS.append("calendar " + cmd + ": " + traceback.format_exc())
        for w in Gtk.Window.list_toplevels():
            if type(w).__name__ in ("EventWindow", "ReminderWindow") or isinstance(w, Gtk.Dialog):
                try:
                    w.modified = False
                    w.destroy()
                except Exception:
                    pass
        cleanup()
        if not store.calendars():
            store.add_calendar("Calendar", "#0078D4", "local")
            cid = store.calendars()[0]["id"]
            win._after_calendars()
        ran += 1
# the appointment window
from folio_post.eventwin import EventWindow  # noqa: E402
cal_state(1)
ew_cmds = None
for k in range(2):
    ew = EventWindow(win, start=dt.datetime(2026, 11, 5, 9, tzinfo=L), end=dt.datetime(2026, 11, 5, 10, tzinfo=L), calendar=cid)
    pump(0.1)
    if ew_cmds is None:
        ew_cmds = commands(ew.ribbon, ["save", "save-as", "close", "send-invitation"])
        ew_cmds = [c for c in ew_cmds if c not in ("delete", "save-close")] + ["save-close"]
    for cmd in ew_cmds:
        if not ew.get_visible():
            ew = EventWindow(win, start=dt.datetime(2026, 11, 5, 9, tzinfo=L), end=dt.datetime(2026, 11, 5, 10, tzinfo=L), calendar=cid)
            pump(0.05)
        ew.subject.set_text("walk")
        answer[0] = (Gtk.ResponseType.OK, Gtk.ResponseType.CANCEL)[k]
        try:
            ew.run(cmd)
        except Exception:
            ERRORS.append("appointment " + cmd + ": " + traceback.format_exc())
        cleanup(keep=(ew,))
        ran += 1
    try:
        ew.modified = False
        ew.destroy()
    except Exception:
        pass
# ---------------------------------------------------------------- people and tasks
from folio_post import vcard as VC, carddav as CRD, tasks as TK  # noqa: E402
win.run("go:people")
pv = win.peopleview
bid = pv.current_book()["id"]


def people_state(k):
    if win.module != "people":
        win.run("go:people")
    if not store.contacts():
        CRD.save_contact(store, bid, VC.new_contact("Walk Person", "walk@example.org"))
        CRD.save_contact(store, bid, VC.new_group("Walk Group", ["walk@example.org"]))
    pv.book_id = None
    pv.refresh()
    if k == 0 and len(pv.model):
        pv.select_ids([pv.model[0][0]])
    elif k == 1:
        pv.tv.get_selection().unselect_all()


ppl_cmds = commands(win.people_ribbon, ["open-contact", "add-sender-to-contacts", "people-folder-pane:off", "people-folder-pane:normal"])
ppl_cmds = [c for c in ppl_cmds if c != "delete-address-book"] + ["delete-address-book"]
for cmd in ppl_cmds:
    for k, resp in enumerate((Gtk.ResponseType.OK, Gtk.ResponseType.CANCEL, Gtk.ResponseType.OK)):
        people_state(k)
        answer[0] = resp
        try:
            win.run(cmd)
        except Exception:
            ERRORS.append("people " + cmd + ": " + traceback.format_exc())
        for w in Gtk.Window.list_toplevels():
            if type(w).__name__ in ("ContactWindow", "EventWindow", "TaskWindow", "NoteWindow") or isinstance(w, Gtk.Dialog):
                try:
                    w.modified = False
                    w.destroy()
                except Exception:
                    pass
        cleanup()
        if not store.books():
            bid = store.add_book("Contacts", "local")
            win._after_books()
        ran += 1
from folio_post.contactwin import ContactWindow  # noqa: E402
ct_cmds = None
for grp in (False, True):
    people_state(1)
    cwn = ContactWindow(win, group=grp, name="Walk")
    pump(0.1)
    cmds_here = commands(cwn.ribbon, ["save", "save-as", "close", "add-member-address"])
    cmds_here = [c for c in cmds_here if c not in ("delete", "save-close", "save-new")] + ["save-new", "save-close"]
    ct_cmds = (ct_cmds or []) + [c for c in cmds_here if c not in (ct_cmds or [])]
    for cmd in cmds_here:
        if not cwn.get_visible():
            cwn = ContactWindow(win, group=grp, name="Walk")
            pump(0.05)
        if not grp:
            cwn.f["email0"].set_text("w@example.org")
        try:
            cwn.run(cmd)
        except Exception:
            ERRORS.append("contact " + cmd + ": " + traceback.format_exc())
        for w in Gtk.Window.list_toplevels():
            if type(w).__name__ == "ContactWindow" and w is not cwn:
                w.modified = False
                w.destroy()
        cleanup(keep=(cwn,))
        ran += 1
    try:
        cwn.modified = False
        cwn.destroy()
    except Exception:
        pass
win.run("go:tasks")
tv = win.tasksview


def tasks_state(k):
    if win.module != "tasks":
        win.run("go:tasks")
    tv.folders.select_row(tv.folders.get_row_at_index(0))
    if not store.todos("task"):
        TK.save(store, TK.new_task("Walk task"))
    tv.view = "simple"
    tv.refresh()
    if k == 0 and len(tv.model):
        tv.select_keys([tv.model[0][0]])
    elif k == 1:
        tv.tv.get_selection().unselect_all()


tk_cmds = commands(win.tasks_ribbon, ["open-task", "tasks-folder-pane:off", "tasks-folder-pane:normal", "go:notes"])
for cmd in tk_cmds:
    for k, resp in enumerate((Gtk.ResponseType.OK, Gtk.ResponseType.CANCEL, Gtk.ResponseType.OK)):
        tasks_state(k)
        answer[0] = resp
        try:
            win.run(cmd)
        except Exception:
            ERRORS.append("tasks " + cmd + ": " + traceback.format_exc())
        for w in Gtk.Window.list_toplevels():
            if type(w).__name__ in ("ContactWindow", "EventWindow", "TaskWindow", "NoteWindow") or isinstance(w, Gtk.Dialog):
                try:
                    w.modified = False
                    w.destroy()
                except Exception:
                    pass
        cleanup()
        ran += 1
from folio_post.taskcmds import TaskWindow  # noqa: E402
tw_cmds = None
tw = TaskWindow(win, subject="walk")
pump(0.1)
tw_cmds = commands(tw.ribbon, ["save", "close"])
tw_cmds = [c for c in tw_cmds if c not in ("delete", "save-close", "mark-complete")] + ["mark-complete", "save-close", "delete"]
for cmd in tw_cmds:
    if not tw.get_visible():
        tw = TaskWindow(win, subject="walk")
        pump(0.05)
    try:
        tw.run(cmd)
    except Exception:
        ERRORS.append("task window " + cmd + ": " + traceback.format_exc())
    cleanup(keep=(tw,))
    ran += 1
try:
    tw.destroy()
except Exception:
    pass
win.run("go:mail")
wait(lambda: not app.busy(), 20)

missing = sorted(set(c.split(":", 1)[1] if c.startswith("not-available:") else c
                     for c in win.missing_log))
out = os.environ.get("WALK_OUT", "/tmp/post-command-walk.tsv")
with open(out, "w") as f:
    for where, cmds in (("main", main_cmds), ("message", mw_cmds), ("compose", cw_cmds), ("calendar", cal_cmds), ("appointment", ew_cmds),
                        ("people", ppl_cmds), ("contact", ct_cmds), ("tasks", tk_cmds), ("task", tw_cmds)):
        for c in cmds:
            status = "NOT_YET" if c.startswith("not-available:") else "OK"
            f.write("%s\t%s\t%s\n" % (where, c, status))
ALL = (main_cmds, mw_cmds, cw_cmds, cal_cmds, ew_cmds, ppl_cmds, ct_cmds, tk_cmds, tw_cmds)
print("commands:", sum(len(x) for x in ALL), "runs:", ran)
print("not available yet:", len([1 for cmds in ALL for c in cmds if c.startswith("not-available:")]))
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
