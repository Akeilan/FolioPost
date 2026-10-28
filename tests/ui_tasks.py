# Run inside Folio Post (FOLIO_TEST_SCRIPT): Tasks, the To-Do List with flagged mail, Notes.
import datetime as dt
import os
import sys
import time
import traceback

from gi.repository import Gdk, Gtk

sys.path.insert(0, os.environ["FOLIO_TESTS"])
import mailserver  # noqa: E402

FAILS = []
INFO = []
OUT = os.environ.get("UI_OUT", "/tmp/ui_out")


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
    a = w.get_allocation()
    img = cairo.ImageSurface(cairo.FORMAT_ARGB32, max(1, a.width), max(1, a.height))
    w.draw(cairo.Context(img))
    img.write_to_png(os.path.join(OUT, "tasks_" + name + ".png"))


class Ev:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def key(name, ctrl=False, shift=False):
    st = (Gdk.ModifierType.CONTROL_MASK if ctrl else 0) | (Gdk.ModifierType.SHIFT_MASK if shift else 0)
    r = win.on_key(win, Ev(keyval=Gdk.keyval_from_name(name), state=Gdk.ModifierType(st), type=Gdk.EventType.KEY_PRESS))
    pump(0.1)
    return r


from folio_post import dialogs as D  # noqa: E402
D.Dialogs.info = lambda self, text, title=None: INFO.append(text)
D.Dialogs.message = lambda self, text, title=None: INFO.append(text)
Gtk.Dialog.run = lambda d: Gtk.ResponseType.CANCEL

try:
    from folio_post import tasks
    store = app.store
    mw = mailserver.World()
    boxes = mw.add_user("me@example.org", "secret")
    boxes["INBOX"].add(mailserver.sample(1, subject="Send the report"))
    _m, ip, sp, mstop = mailserver.start(mw)
    cfg = {"imap_host": "127.0.0.1", "imap_port": ip, "imap_security": "none", "smtp_host": "127.0.0.1", "smtp_port": sp,
           "smtp_security": "none", "user": "me@example.org"}
    from folio_post.accounts import create_account
    aid = create_account(win, "Me", "me@example.org", cfg, "secret")
    inbox = None
    wait(lambda: store.folder_by_role(aid, "inbox") and store.messages(store.folder_by_role(aid, "inbox")["id"]), 20)
    wait(lambda: not app.busy(), 10)
    pump(0.4)
    inbox = store.folder_by_role(aid, "inbox")
    win.go_folder(inbox["id"])
    pump(0.2)
    mid = win.iter_rows()[0][0]
    win.select_ids([mid])
    win.run("flag-due:tomorrow")
    m = store.message(mid)
    check(m["flagged"] and m["due"] and dt.date.fromtimestamp(m["due"]) == dt.date.today() + dt.timedelta(days=1),
          "Follow Up Tomorrow on a message")
    key("4", ctrl=True)
    check(win.module == "tasks" and win.tasksview is not None, "Ctrl+4 opens Tasks")
    v = win.tasksview
    check(any(r[0] == "mail:%d" % mid for r in v.model), "flagged mail on the To-Do List")
    tw = win.run("new-task")
    pump(0.2)
    tw.subject.set_text("Book flights")
    tw.due.set_text((dt.date.today() + dt.timedelta(days=3)).strftime("%d/%m/%Y"))
    tw.priority.set_active_id("1")
    tw.notes.get_buffer().set_text("Window seat")
    shot(tw, "task")
    tw.run("save-close")
    pump(0.2)
    rows = store.todos("task")
    check(len(rows) == 1 and rows[0]["subject"] == "Book flights", "task saved")
    t = tasks.parse(rows[0]["data"])
    check(t.priority == 1 and t.notes == "Window seat" and t.due == dt.date.today() + dt.timedelta(days=3), "its fields")
    check(any(r[1] == "Book flights" for r in v.model), "on the list")
    v.quick.set_text("Call the plumber")
    v.quick.activate()
    pump(0.2)
    check(any(r[1] == "Call the plumber" for r in v.model), "a task typed straight into the list")
    shot(win, "todo")
    # complete
    k = [r[0] for r in v.model if r[1] == "Call the plumber"][0]
    v.select_keys([k])
    win.run("mark-complete")
    check(not any(r[1] == "Call the plumber" for r in v.model), "Mark Complete takes it off the To-Do List")
    win.run("tasks-view:completed")
    check(any(r[1] == "Call the plumber" for r in v.model), "Completed view")
    win.run("tasks-view:todo")
    v.select_keys(["mail:%d" % mid])
    win.run("mark-complete")
    check(store.message(mid)["done"] == 1 and not store.message(mid)["flagged"], "completing flagged mail")
    # due dates, overdue
    k = [r[0] for r in v.model if r[1] == "Book flights"][0]
    v.select_keys([k])
    win.run("task-due:today")
    check(tasks.parse(store.todos("task")[0]["data"]).due == dt.date.today() or
          any(tasks.parse(r["data"]).due == dt.date.today() for r in store.todos("task")), "Follow Up Today on a task")
    # reminder
    tw = tasks.new_task("Water plants")
    from folio_post import ical
    tw.set_reminder(dt.datetime.now(ical.local_tz()) - dt.timedelta(minutes=1))
    tasks.save(store, tw)
    check(any(x[1] == "Water plants" for x in app.reminders.due()), "task reminder")
    # notes
    key("5", ctrl=True)
    check(v.folder == "notes", "Ctrl+5 Notes")
    nw = win.run("new-note")
    nw.text.get_buffer().set_text("Gate code 4711\nback door")
    nw.save()
    pump(0.2)
    notes = store.todos("note")
    check(len(notes) == 1 and notes[0]["subject"] == "Gate code 4711", "a note")
    check(len(v.notes_flow.get_children()) == 1, "notes shown")
    nw.destroy()
    win.run("go:mail")
    mstop()
except Exception:
    traceback.print_exc()
    FAILS.append("exception")
print("UI FAILS: %d" % len(FAILS) if FAILS else "UI all passed")
sys.stdout.flush()
os._exit(1 if FAILS else 0)
