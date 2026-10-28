"""Tasks and Notes in the main window: ribbon, task window, note window and commands."""
import datetime as dt

from gi.repository import Gdk, GLib, Gtk

from . import APP_NAME, ical, icons, tasks
from .dialogs import Dialogs
from .ribbon import Ribbon, Tab
from .ribbon_post import Builder


def build_tasks_ribbon(win, r):
    B = Builder(win)
    B.r = r
    t = r.building(Tab("Home", "H"))
    B.group(t, "New", [B.big("New Task", "p-nav-tasks", "new-task", "N", tip="New Task (Ctrl+N)"),
                       B.big("New Note", "p-rename-folder", "new-note", "NN", tip="New Note (Ctrl+Shift+N)"),
                       [B.small("New Items", "p-new-email", None, "I", menu=[("E-mail Message", "new-email-message"),
                                                                            ("Appointment", "new-appointment"),
                                                                            ("Contact", "new-contact")])]])
    B.group(t, "Delete", [B.big("Delete", "p-delete", "delete-task", "D")])
    B.group(t, "Manage Task", [B.big("Mark Complete", "p-flag-done", "mark-complete", "MC"),
                               B.big("Remove from List", "p-cancel-all", "remove-from-list", "RL")])
    B.group(t, "Follow Up", [[B.small("Today", "p-flag", "task-due:today", "T"), B.small("Tomorrow", "p-flag", "task-due:tomorrow", "R"),
                              B.small("This Week", "p-flag", "task-due:this-week", "W")],
                             [B.small("Next Week", "p-flag", "task-due:next-week", "K"), B.small("No Date", "p-flag", "task-due:none", "O")]])
    B.group(t, "Current View", [B.big("Change View", "p-change-view", None, "CV",
                                      menu=[(label, "tasks-view:" + k) for k, label in __import__("folio_post.tasksview", fromlist=["VIEWS"]).VIEWS])])
    B.group(t, "Tags", [[B.small("Categorize", "p-categorize", None, "G", menu=[(n, "task-category:" + n) for n in
                                                                                ("Red", "Orange", "Yellow", "Green", "Blue", "Purple")] +
                                 [None, ("Clear All Categories", "task-category:")])]])
    r.add_tab(t)
    t = r.building(Tab("Send / Receive", "S"))
    B.group(t, "Send & Receive", [B.big("Send/Receive All Folders", "p-send-receive", "send-receive", "A")])
    B.group(t, "Preferences", [B.big("Work Offline", "p-offline", "work-offline", "W")])
    r.add_tab(t)
    t = r.building(Tab("View", "V"))
    B.group(t, "Current View", [B.big("Change View", "p-change-view", None, "CV",
                                      menu=[(label, "tasks-view:" + k) for k, label in __import__("folio_post.tasksview", fromlist=["VIEWS"]).VIEWS])])
    B.group(t, "Layout", [B.big("Folder Pane", "p-folder-pane", None, "F",
                                menu=[("Normal", "tasks-folder-pane:normal"), ("Off", "tasks-folder-pane:off")])])
    r.add_tab(t)
    t = r.building(Tab("Help", "Y"))
    B.group(t, "Help", [B.big("Help", "p-help", "help", "H"), B.big("Keyboard Shortcuts", "p-options", "shortcuts", "K"),
                        B.big("About", "p-about", "about", "A")])
    r.add_tab(t)
    r.select(r.tab_by_name("Home"))


class TaskWindow(Gtk.Window):
    def __init__(self, main, tid=None, subject="", due=None):
        Gtk.Window.__init__(self)
        self.main = main
        self.app = main.app
        self.store = main.store
        self.dialogs = Dialogs(self)
        self.tid = tid
        self.missing_log = []
        row = self.store.todo(tid) if tid else None
        self.task = tasks.parse(row["data"]) if row else tasks.new_task(subject, due)
        self.set_default_size(720, 520)
        self.set_icon_name("folio-post")
        hb = Gtk.HeaderBar()
        hb.set_show_close_button(True)
        hb.get_style_context().add_class("folio-titlebar")
        self.title_label = Gtk.Label()
        self.title_label.get_style_context().add_class("title")
        hb.set_custom_title(self.title_label)
        self.qat = Gtk.Box()
        b = Gtk.Button()
        b.add(icons.white_image("qat-save", 16))
        b.connect("clicked", lambda *_: self.run("save"))
        self.qat.pack_start(b, False, False, 0)
        hb.pack_start(self.qat)
        self.set_titlebar(hb)
        self.overlay = Gtk.Overlay()
        self.add(self.overlay)
        self.outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.overlay.add(self.outer)
        self.ribbon = Ribbon(self.run, lambda: None)
        self.outer.pack_start(self.ribbon, False, False, 0)
        B = Builder(self)
        tab = self.ribbon.building(Tab("Task", "H"))
        B.group(tab, "Actions", [B.big("Save & Close", "qat-save", "save-close", "AV"), B.big("Delete", "p-delete", "delete", "D"),
                                 [B.small("Forward", "p-forward", "forward", "FW")]])
        B.group(tab, "Manage Task", [B.big("Mark Complete", "p-flag-done", "mark-complete", "MC")])
        self.ribbon.add_tab(tab)
        self.ribbon.select(tab)
        from .eventwin import DateTimeRow
        g = Gtk.Grid(column_spacing=8, row_spacing=8)
        g.set_border_width(14)
        t = self.task
        g.attach(Gtk.Label(label="Subject", xalign=0), 0, 0, 1, 1)
        self.subject = Gtk.Entry(text=t.subject)
        self.subject.set_hexpand(True)
        self.subject.connect("changed", lambda *_: self.update_title())
        g.attach(self.subject, 1, 0, 3, 1)
        today = dt.datetime.now(ical.local_tz())

        def date_row(d):
            e = Gtk.Entry()
            e.set_text(d.strftime("%a %d/%m/%Y") if d else "None")
            return e
        g.attach(Gtk.Label(label="Start date", xalign=0), 0, 1, 1, 1)
        self.start = date_row(t.start)
        g.attach(self.start, 1, 1, 1, 1)
        g.attach(Gtk.Label(label="Status", xalign=0), 2, 1, 1, 1)
        self.status = Gtk.ComboBoxText()
        for k, label in tasks.STATUS:
            self.status.append(k, label)
        self.status.set_active_id(t.status if t.status in dict(tasks.STATUS) else "NEEDS-ACTION")
        g.attach(self.status, 3, 1, 1, 1)
        g.attach(Gtk.Label(label="Due date", xalign=0), 0, 2, 1, 1)
        self.due = date_row(t.due)
        g.attach(self.due, 1, 2, 1, 1)
        g.attach(Gtk.Label(label="Priority", xalign=0), 2, 2, 1, 1)
        self.priority = Gtk.ComboBoxText()
        for p, label in tasks.PRIORITY:
            self.priority.append(str(p), label)
        self.priority.set_active_id(str(t.priority))
        g.attach(self.priority, 3, 2, 1, 1)
        g.attach(Gtk.Label(label="% Complete", xalign=0), 2, 3, 1, 1)
        self.percent = Gtk.SpinButton.new_with_range(0, 100, 25)
        self.percent.set_value(t.percent)
        g.attach(self.percent, 3, 3, 1, 1)
        self.remind = Gtk.CheckButton(label="Reminder")
        self.remind.set_active(t.reminder is not None)
        g.attach(self.remind, 0, 4, 1, 1)
        self.remind_row = DateTimeRow(t.reminder.astimezone(ical.local_tz()) if t.reminder else
                                      today.replace(hour=8, minute=0, second=0, microsecond=0) + dt.timedelta(days=1))
        g.attach(self.remind_row, 1, 4, 3, 1)
        self.notes = Gtk.TextView()
        self.notes.get_buffer().set_text(t.notes)
        self.notes.get_style_context().add_class("folio-editor")
        sw = Gtk.ScrolledWindow()
        sw.add(self.notes)
        sw.set_vexpand(True)
        sw.set_hexpand(True)
        g.attach(sw, 0, 5, 4, 1)
        self.outer.pack_start(g, True, True, 0)
        from .keytips import KeyTips
        self.keytips = KeyTips(self)
        self.connect("key-press-event", self.on_key)
        self.show_all()
        self.update_title()

    def update_title(self):
        self.title_label.set_text("%s - Task" % (self.subject.get_text().strip() or "Untitled"))
        self.set_title(self.title_label.get_text())

    def show_backstage(self, page=None):
        pass

    def run(self, cmd, *args):
        name, _, arg = (cmd or "").partition(":")
        fn = getattr(self, "act_" + name.replace("-", "_"), None)
        if fn is None:
            self.dialogs.info("“%s” isn't available yet in %s." % (cmd, APP_NAME))
            return None
        return fn(arg) if arg or _ else fn()

    def _date(self, e):
        from .eventwin import parse_date
        t = e.get_text().strip()
        return None if t.lower() in ("", "none") else parse_date(t)

    def act_save(self):
        t = self.task
        if not self.subject.get_text().strip():
            self.dialogs.message("Type a subject first.")
            return None
        t.set_subject(self.subject.get_text().strip())
        t.set_date("DTSTART", self._date(self.start))
        t.set_date("DUE", self._date(self.due))
        t.set_status(self.status.get_active_id())
        if self.status.get_active_id() != "COMPLETED":
            t.set_percent(self.percent.get_value())
        t.set_priority(int(self.priority.get_active_id()))
        t.set_reminder(self.remind_row.value() if self.remind.get_active() else None)
        b = self.notes.get_buffer()
        t.set_notes(b.get_text(b.get_start_iter(), b.get_end_iter(), False))
        t.touch()
        self.tid = tasks.save(self.store, t, self.tid)
        self.main.tasks_changed()
        return self.tid

    def act_save_close(self):
        if self.act_save() is not None:
            self.destroy()

    def act_delete(self):
        if self.tid:
            self.store.drop_todo(self.tid)
            self.main.tasks_changed()
        self.destroy()

    def act_mark_complete(self):
        self.status.set_active_id("COMPLETED")
        self.percent.set_value(100)
        self.act_save_close()

    def act_forward(self):
        acc = self.main.current_account()
        self.app.compose(account=acc["id"] if acc else None, subject="Task: " + self.subject.get_text(),
                         body_text="%s\nDue: %s\nStatus: %s\n\n%s" % (self.subject.get_text(), self.due.get_text(),
                                                                       self.status.get_active_text(),
                                                                       self.notes.get_buffer().get_text(
                                                                           *self.notes.get_buffer().get_bounds(), False)))

    def act_close(self):
        self.destroy()

    def on_key(self, w, ev):
        if self.keytips.active:
            return self.keytips.key(ev)
        if ev.state & Gdk.ModifierType.CONTROL_MASK and ev.keyval in (Gdk.KEY_s, Gdk.KEY_S):
            self.run("save")
            return True
        if ev.keyval == Gdk.KEY_Escape:
            self.destroy()
            return True
        return False


class NoteWindow(Gtk.Window):
    """A note: its first line is its title; saved as you type."""

    def __init__(self, main, nid=None):
        Gtk.Window.__init__(self, title="Note")
        self.main = main
        self.store = main.store
        self.nid = nid
        self.set_default_size(300, 280)
        self.set_icon_name("folio-post")
        self.text = Gtk.TextView()
        self.text.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.text.get_style_context().add_class("folio-note")
        self.text.set_border_width(8)
        row = self.store.todo(nid) if nid else None
        if row:
            self.text.get_buffer().set_text(row["data"])
        self.text.get_buffer().connect("changed", self._changed)
        self.add(self.text)
        self._timer = None
        self.connect("delete-event", lambda *_: (self.save(), False)[1])
        self.show_all()

    def _changed(self, *_):
        if self._timer:
            GLib.source_remove(self._timer)
        self._timer = GLib.timeout_add(600, lambda: (self.save(), False)[1])

    def save(self):
        self._timer = None
        b = self.text.get_buffer()
        t = b.get_text(b.get_start_iter(), b.get_end_iter(), False)
        if not t.strip():
            if self.nid:
                self.store.drop_todo(self.nid)
                self.nid = None
        else:
            self.nid = self.store.put_todo("note", "", t, t.split("\n")[0][:80], tid=self.nid)
        self.set_title((t.split("\n")[0][:40] or "Note"))
        self.main.tasks_changed()


class TaskCommands:
    tasksview = None

    def ensure_tasks(self):
        if self.tasksview is not None:
            return self.tasksview
        from .tasksview import TasksView
        self.tasksview = TasksView(self)
        self.tasksview.show_all()
        self.modules.add_named(self.tasksview, "tasks")
        self.tasks_ribbon = Ribbon(self.run, lambda: self.tasksview.tv.grab_focus())
        self.tasks_ribbon.connect("file-clicked", lambda *_: self.show_backstage())
        build_tasks_ribbon(self, self.tasks_ribbon)
        self.tasks_ribbon.show_all()
        return self.tasksview

    def update_tasks_status(self, view):
        if self.module != "tasks":
            return
        n = len(view.model) if view.folder != "notes" else len(view.notes_flow.get_children())
        self.status.left.set_text("Items: %d" % n)
        self.status.right.set_text("Working Offline" if self.app.syncer.offline else "All folders are up to date.")

    def tasks_changed(self):
        if self.tasksview is not None:
            self.tasksview.refresh()

    def act_new_task(self, subject=""):
        w = TaskWindow(self, subject=subject)
        w.present()
        return w

    def act_new_note(self):
        w = NoteWindow(self)
        w.present()
        return w

    def act_open_task(self):
        v = self.ensure_tasks()
        keys = v.selected()
        if not keys:
            return None
        kind, _, n = keys[0].partition(":")
        if kind == "task":
            w = TaskWindow(self, int(n))
        elif kind == "note":
            w = NoteWindow(self, int(n))
        else:
            self.switch_module("mail")
            m = self.store.message(int(n))
            if m:
                self.go_folder(m["folder"])
                self.select_ids([int(n)], scroll=True)
            return None
        w.present()
        return w

    def set_done(self, key, on=True):
        kind, _, n = key.partition(":")
        if kind == "task":
            row = self.store.todo(int(n))
            t = tasks.parse(row["data"])
            t.set_status("COMPLETED" if on else "NEEDS-ACTION")
            t.touch()
            tasks.save(self.store, t, int(n))
        elif kind == "mail":
            mid = int(n)
            if on:
                self.store.set_flag([mid], "flagged", False)
                self.store.set_flag([mid], "done", True, pending=False)
            else:
                self.store.set_flag([mid], "flagged", True)
                self.store.set_flag([mid], "done", False, pending=False)
            self.push_soon()
        self.tasks_changed()

    def act_mark_complete(self):
        for k in self.ensure_tasks().selected():
            if not k.startswith("note:"):
                self.set_done(k, True)

    def act_remove_from_list(self):
        for k in self.ensure_tasks().selected():
            kind, _, n = k.partition(":")
            if kind == "mail":
                self.store.set_flag([int(n)], "flagged", False)
                self.store.set_fields(int(n), due=0, done=0)
                self.push_soon()
            elif kind == "task":
                self.store.drop_todo(int(n))
        self.tasks_changed()

    def act_delete_task(self):
        for k in self.ensure_tasks().selected():
            kind, _, n = k.partition(":")
            if kind in ("task", "note"):
                self.store.drop_todo(int(n))
            elif kind == "mail":
                self.store.set_flag([int(n)], "flagged", False)
                self.store.set_fields(int(n), due=0)
        self.tasks_changed()

    def act_task_due(self, how):
        d = tasks.follow_up_date(how)
        for k in self.ensure_tasks().selected():
            kind, _, n = k.partition(":")
            if kind == "task":
                row = self.store.todo(int(n))
                t = tasks.parse(row["data"])
                t.set_date("DUE", d)
                t.touch()
                tasks.save(self.store, t, int(n))
            elif kind == "mail":
                due = int(dt.datetime.combine(d, dt.time(0)).timestamp()) if d else 0
                self.store.set_fields(int(n), due=due)
        self.tasks_changed()

    def act_tasks_view(self, how):
        v = self.ensure_tasks()
        v.view = how
        self.set_vset("tasks_view", how)
        v.refresh()

    def act_task_category(self, name=""):
        for k in self.ensure_tasks().selected():
            kind, _, n = k.partition(":")
            if kind == "task":
                row = self.store.todo(int(n))
                t = tasks.parse(row["data"])
                cats = t.categories
                cats = [] if not name else (cats + [name] if name not in cats else [c for c in cats if c != name])
                t.comp.set("CATEGORIES", ",".join(cats) if cats else None)
                tasks.save(self.store, t, int(n))
        self.tasks_changed()

    def act_tasks_folder_pane(self, how):
        self.ensure_tasks().left.set_visible(how != "off")

    def act_flag_due(self, how):
        """Follow Up on mail: Today, Tomorrow, This Week, Next Week, No Date — the message goes on the To-Do List."""
        ids = self.need_selection()
        d = tasks.follow_up_date(how)
        for mid in ids:
            self.store.set_flag([mid], "flagged", True)
            self.store.set_fields(mid, due=int(dt.datetime.combine(d, dt.time(0)).timestamp()) if d else 0)
        self.push_soon()
        self.tasks_changed()
