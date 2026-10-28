"""Tasks and Notes: the To-Do List (tasks and flagged mail), the task list with its views, and notes."""
import datetime as dt
import time

from gi.repository import GLib, Gtk, Pango

from . import tasks

VIEWS = [("todo", "To-Do List"), ("simple", "Simple List"), ("active", "Active"), ("completed", "Completed"),
         ("overdue", "Overdue"), ("next7", "Next 7 Days")]


class TasksView(Gtk.Box):
    def __init__(self, win):
        Gtk.Box.__init__(self)
        self.win = win
        self.store = win.store
        self.view = win.vset("tasks_view", "todo")
        self.folder = "todo"           # todo | tasks | notes
        paned = Gtk.Paned()
        self.pack_start(paned, True, True, 0)
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        left.get_style_context().add_class("folio-folderpane")
        left.set_size_request(200, -1)
        self.folders = Gtk.ListBox()
        for key, label in (("todo", "To-Do List"), ("tasks", "Tasks"), ("notes", "Notes")):
            r = Gtk.ListBoxRow()
            lab = Gtk.Label(label=label, xalign=0)
            lab.set_margin_start(12)
            lab.set_margin_top(4)
            lab.set_margin_bottom(4)
            r.add(lab)
            r.key = key
            self.folders.add(r)
        self.folders.connect("row-selected", self._folder_picked)
        left.pack_start(self.folders, True, True, 0)
        self.left = left
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        right.get_style_context().add_class("folio-listpane")
        bar = Gtk.Box(spacing=6)
        bar.get_style_context().add_class("folio-listbar")
        self.quick = Gtk.Entry()
        self.quick.set_placeholder_text("Type a new task")
        self.quick.connect("activate", self._quick_add)
        bar.pack_start(self.quick, True, True, 6)
        self.quick_bar = bar
        right.pack_start(bar, False, False, 0)
        self.model = Gtk.ListStore(str, str, str, str, bool, int)    # kind:id, subject, due text, extra, done, sort
        self.tv = Gtk.TreeView(model=self.model)
        self.tv.get_style_context().add_class("folio-messages")
        self.tv.get_selection().set_mode(Gtk.SelectionMode.MULTIPLE)
        chk = Gtk.CellRendererToggle()
        chk.connect("toggled", self._toggled)
        c = Gtk.TreeViewColumn("✓", chk, active=4)
        self.tv.append_column(c)
        tr = Gtk.CellRendererText()
        tr.set_property("ellipsize", Pango.EllipsizeMode.END)
        col = Gtk.TreeViewColumn("Task Subject", tr)
        col.set_expand(True)
        col.set_cell_data_func(tr, lambda c, cell, m, it, _d: cell.set_property(
            "markup", ("<s>%s</s>" if m[it][4] else "%s") % GLib.markup_escape_text(m[it][1] or "(no subject)") +
            ("  <span foreground='#767676'>%s</span>" % GLib.markup_escape_text(m[it][3]) if m[it][3] else "")))
        self.tv.append_column(col)
        dr = Gtk.CellRendererText()
        self.due_col = Gtk.TreeViewColumn("Due Date", dr)
        self.due_col.set_cell_data_func(dr, self._due_cell)
        self.tv.append_column(self.due_col)
        self.tv.connect("row-activated", lambda *_: self.win.run("open-task"))
        sw = Gtk.ScrolledWindow()
        sw.add(self.tv)
        right.pack_start(sw, True, True, 0)
        # notes as tiles
        self.notes_flow = Gtk.FlowBox()
        self.notes_flow.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.notes_flow.set_max_children_per_line(8)
        self.notes_flow.connect("child-activated", lambda *_: self.win.run("open-task"))
        nsw = Gtk.ScrolledWindow()
        nsw.add(self.notes_flow)
        self.stack = Gtk.Stack()
        self.stack.add_named(right, "list")
        self.stack.add_named(nsw, "notes")
        paned.pack1(left, False, False)
        paned.pack2(self.stack, True, False)
        paned.set_position(210)
        self.folders.select_row(self.folders.get_row_at_index(0))
        self.refresh()

    def _due_cell(self, col, cell, m, it, _d):
        txt = m[it][2]
        overdue = m[it][5] and m[it][5] < time.time() - 86400 and not m[it][4]
        cell.set_property("markup", "<span foreground='#c42b1c'>%s</span>" % txt if overdue else GLib.markup_escape_text(txt))

    def _folder_picked(self, lb, row):
        if row is not None:
            self.folder = row.key
            self.refresh()

    def rows(self):
        out = []
        today = dt.date.today()
        for r in self.store.todos("task"):
            t = tasks.parse(r["data"])
            if t is None:
                continue
            out.append(("task:%d" % r["id"], t.subject, t.due, "", t.done, t))
        if self.folder == "todo":
            for m in self.store.flagged():
                d = dt.date.fromtimestamp(m["due"]) if m["due"] else None
                out.append(("mail:%d" % m["id"], m["subject"], d, "✉ " + (m["from_name"] or m["from_addr"]), bool(m["done"]), None))
        v = self.view
        if v == "active" or (self.folder == "todo" and v == "todo"):
            out = [x for x in out if not x[4]]
        elif v == "completed":
            out = [x for x in out if x[4]]
        elif v == "overdue":
            out = [x for x in out if x[2] and x[2] < today and not x[4]]
        elif v == "next7":
            out = [x for x in out if x[2] and today <= x[2] <= today + dt.timedelta(days=7) and not x[4]]
        out.sort(key=lambda x: (x[4], x[2] is None, x[2] or dt.date.max, x[1].lower()))
        return out

    def refresh(self):
        if self.folder == "notes":
            self.stack.set_visible_child_name("notes")
            for c in self.notes_flow.get_children():
                self.notes_flow.remove(c)
            for n in self.store.todos("note"):
                lab = Gtk.Label(label=n["data"][:300], xalign=0, yalign=0)
                lab.set_line_wrap(True)
                lab.set_max_width_chars(22)
                lab.set_size_request(170, 150)
                ev = Gtk.EventBox()
                ev.add(lab)
                ev.get_style_context().add_class("folio-note")
                ev.note_id = n["id"]
                self.notes_flow.add(ev)
            self.notes_flow.show_all()
            self.win.update_tasks_status(self)
            return
        self.stack.set_visible_child_name("list")
        sel = self.selected()
        self.model.clear()
        for key, subj, due, extra, done, _t in self.rows():
            ts = int(dt.datetime.combine(due, dt.time(0)).timestamp()) if due else 0
            self.model.append([key, subj, due.strftime("%a %d/%m/%Y") if due else "None", extra, done, ts])
        if sel:
            s = self.tv.get_selection()
            for row in self.model:
                if row[0] in sel:
                    s.select_iter(row.iter)
        self.win.update_tasks_status(self)

    def selected(self):
        if self.folder == "notes":
            ch = self.notes_flow.get_selected_children()
            return ["note:%d" % c.get_child().note_id for c in ch]
        m, paths = self.tv.get_selection().get_selected_rows()
        return [m[p][0] for p in paths]

    def select_keys(self, keys):
        s = self.tv.get_selection()
        s.unselect_all()
        for row in self.model:
            if row[0] in keys:
                s.select_iter(row.iter)

    def _toggled(self, cell, path):
        key = self.model[path][0]
        self.win.set_done(key, not self.model[path][4])

    def _quick_add(self, e):
        t = e.get_text().strip()
        if t:
            tasks.save(self.store, tasks.new_task(t))
            e.set_text("")
            self.refresh()
