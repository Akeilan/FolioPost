"""The main window: Folder Pane, message list and Reading Pane under the ribbon, as Outlook lays
out Mail."""
import os
import re
import time

from gi.repository import Gdk, GLib, Gtk, Pango

from . import APP_NAME, VERSION, icons, mime
from .dialogs import Dialogs
from .readingpane import ReadingPane, nice_size
from .ribbon import Ribbon
from .ribbon_post import CATEGORIES, build_ribbon, move_menu
from .calcmds import CalendarCommands
from .peoplecmds import PeopleCommands
from .taskcmds import TaskCommands
from .post_b3 import Backlog3Commands
from .store import ROLE_NAMES

DND_TARGET = "folio-post/messages"
ROLE_ICONS = {"inbox": "p-nav-mail", "drafts": "p-rename-folder", "sent": "p-send", "trash": "p-delete",
              "junk": "p-junk", "archive": "p-archive", "outbox": "p-send-all"}
CAT_COLORS = {n.split()[0]: c for n, c in CATEGORIES}

# list columns
C_ID, C_HEAD, C_FROM, C_SUBJ, C_DATE, C_SIZE, C_UNREAD, C_FLAG, C_ATTACH, C_IMP, C_CATS, C_PREV, C_TO, C_COUNT = range(14)


def accent():
    """The accent for text in the lists: USPS blue, lighter on the dark theme."""
    from . import appearance
    return "#a8a8e0" if appearance.is_dark() else "#333366"


def when_text(ts, now=None):
    if not ts:
        return ""
    now = now or time.time()
    lt, ln = time.localtime(ts), time.localtime(now)
    if lt.tm_year == ln.tm_year and lt.tm_yday == ln.tm_yday:
        return time.strftime("%H:%M", lt)
    if now - ts < 6 * 86400 and ts < now:
        return time.strftime("%a %H:%M", lt)
    return time.strftime("%d/%m/%Y", lt)


def date_group(ts, now=None):
    now = now or time.time()
    lt, ln = time.localtime(ts), time.localtime(now)
    start_today = now - (ln.tm_hour * 3600 + ln.tm_min * 60 + ln.tm_sec)
    if ts >= start_today:
        return 0, "Today"
    if ts >= start_today - 86400:
        return 1, "Yesterday"
    start_week = start_today - ln.tm_wday * 86400
    if ts >= start_week:
        return 2, time.strftime("%A", lt)
    if ts >= start_week - 7 * 86400:
        return 3, "Last Week"
    if ts >= start_week - 14 * 86400:
        return 4, "Two Weeks Ago"
    if lt.tm_year == ln.tm_year and lt.tm_mon == ln.tm_mon:
        return 5, "Earlier this Month"
    if (ln.tm_year * 12 + ln.tm_mon) - (lt.tm_year * 12 + lt.tm_mon) == 1:
        return 6, "Last Month"
    return 7, "Older"


class StatusBar(Gtk.Box):
    def __init__(self, win):
        Gtk.Box.__init__(self, spacing=12)
        self.get_style_context().add_class("folio-status")
        self.left = Gtk.Label(xalign=0)
        self.right = Gtk.Label(xalign=1)
        self.right.set_ellipsize(Pango.EllipsizeMode.END)
        self.pack_start(self.left, False, False, 8)
        self.pack_end(self.right, True, True, 8)


class PostWindow(Backlog3Commands, TaskCommands, PeopleCommands, CalendarCommands, Gtk.ApplicationWindow):
    def __init__(self, app):
        Gtk.ApplicationWindow.__init__(self, application=app)
        self.app = app
        self.store = app.store
        self.dialogs = Dialogs(self)
        self.folder_id = None
        self.search_text = ""
        self.filter = "all"
        self.undo_stack = []
        self.missing_log = []
        self.prev_selected = None
        self._refresh_pending = False
        self._push_timer = None
        self.view_settings = app.settings.setdefault("views", {})
        geo = app.settings.get("window", {})
        self.set_default_size(geo.get("w", 1280), geo.get("h", 820))
        if geo.get("max", True):
            self.maximize()
        self.set_icon_name("folio-post")

        # ---- title bar
        self.header = Gtk.HeaderBar()
        self.header.set_show_close_button(True)
        self.header.get_style_context().add_class("folio-titlebar")
        self.title_label = Gtk.Label(label=APP_NAME)
        self.title_label.get_style_context().add_class("title")
        self.header.set_custom_title(self.title_label)
        self.qat = Gtk.Box(spacing=0)
        for icon, cmd, tip in (("p-send-receive", "send-receive", "Send/Receive All Folders (F9)"),
                               ("r-undo-sm", "undo", "Undo (Ctrl+Z)")):
            b = Gtk.Button()
            b.add(icons.white_image(icon, 16))
            b.set_tooltip_text(tip)
            b.set_focus_on_click(False)
            b.connect("clicked", lambda _b, c=cmd: self.run(c))
            self.qat.pack_start(b, False, False, 0)
        self.header.pack_start(self.qat)
        self.search = Gtk.SearchEntry()
        self.search.set_placeholder_text("Search Current Mailbox (Ctrl+E)")
        self.search.get_style_context().add_class("folio-search")
        self.search.set_width_chars(34)
        self.search.connect("search-changed", self.on_search)
        self.search.connect("stop-search", lambda *_: self.clear_search())
        self.header.pack_end(self.search)
        self.set_titlebar(self.header)

        # ---- layout
        self.overlay = Gtk.Overlay()
        self.add(self.overlay)
        self.outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.overlay.add(self.outer)
        self.ribbon = Ribbon(self.run, self.focus_document)
        self.ribbon.connect("file-clicked", lambda *_: self.show_backstage())
        self.outer.pack_start(self.ribbon, False, False, 0)
        # Automatic Replies are on: said under the ribbon, as Outlook does
        self.autoreply_bar = Gtk.Box(spacing=8)
        self.autoreply_bar.get_style_context().add_class("folio-messagebar")
        ab_lab = Gtk.Label(xalign=0)
        ab_lab.set_markup("<b>AUTOMATIC REPLIES</b>   Automatic replies are being sent for this account.")
        self.autoreply_bar.pack_start(ab_lab, False, False, 10)
        ab_off = Gtk.Button(label="Turn off")
        ab_off.connect("clicked", lambda *_: self.run("automatic-replies"))
        self.autoreply_bar.pack_start(ab_off, False, False, 0)
        self.autoreply_bar.set_no_show_all(True)
        self.outer.pack_start(self.autoreply_bar, False, False, 2)
        self.body = Gtk.Paned()
        self.modules = Gtk.Stack()
        self.modules.set_transition_type(Gtk.StackTransitionType.NONE)
        self.modules.add_named(self.body, "mail")
        self.outer.pack_start(self.modules, True, True, 0)
        self.build_folder_pane()
        self.build_list()
        self.reading = ReadingPane(self)
        self.reading.clear()
        self.right = Gtk.Paned()
        self.right.pack1(self.list_box, True, False)
        self.right.pack2(self.reading, True, False)
        self.body.pack1(self.folder_box, False, False)
        self.body.pack2(self.right, True, False)
        self.body.set_position(240)
        self.status = StatusBar(self)
        self.outer.pack_start(self.status, False, False, 0)
        build_ribbon(self)
        from .backstage import Backstage
        self.backstage = Backstage(self)
        self.overlay.add_overlay(self.backstage)
        from .keytips import KeyTips
        self.keytips = KeyTips(self)
        self.connect("key-press-event", self.on_key)
        self.connect("key-release-event", self.on_key_release)
        self._alt_alone = False
        self.connect("delete-event", self.on_delete)
        self.connect("configure-event", self._remember_geometry)
        self.store.listeners.append(self._store_changed)
        app.syncer.listeners.append(lambda aid, text: GLib.idle_add(self.update_status))
        self.show_all()
        self.backstage.hide()
        self.apply_layout()
        self.refresh_folders()
        self.select_first_inbox()
        self.update_status()
        if not os.environ.get("FOLIO_POST_NO_AUTOSYNC") and not app.syncer.offline and self.store.accounts():
            GLib.timeout_add(600, lambda: (app.send_receive(), False)[1])

    # ================================================================ folder pane
    def build_folder_pane(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.get_style_context().add_class("folio-folderpane")
        self.folders_model = Gtk.TreeStore(str, int, int, str, str)   # markup, folder id, account id, icon, role
        tv = Gtk.TreeView(model=self.folders_model)
        tv.set_headers_visible(False)
        tv.set_enable_search(False)
        tv.get_style_context().add_class("folio-folders")
        col = Gtk.TreeViewColumn()
        pr = Gtk.CellRendererPixbuf()
        col.pack_start(pr, False)
        col.set_cell_data_func(pr, lambda c, cell, m, it, _d: cell.set_property(
            "pixbuf", icons.pixbuf(m[it][3], 16) if m[it][3] else None))
        tr = Gtk.CellRendererText()
        tr.set_property("ellipsize", Pango.EllipsizeMode.END)
        col.pack_start(tr, True)
        col.add_attribute(tr, "markup", 0)
        tv.append_column(col)
        tv.get_selection().connect("changed", self._folder_selected)
        tv.connect("button-press-event", self._folder_button)
        # dropping messages on folders
        tv.enable_model_drag_dest([Gtk.TargetEntry.new(DND_TARGET, Gtk.TargetFlags.SAME_APP, 0)],
                                  Gdk.DragAction.MOVE | Gdk.DragAction.COPY)
        tv.connect("drag-data-received", self._drop_on_folder)
        self.folder_view = tv
        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sw.add(tv)
        box.pack_start(sw, True, True, 0)
        # Navigation bar
        nav = Gtk.Box(spacing=0)
        nav.get_style_context().add_class("folio-navbar")
        self.nav_buttons = {}
        for key, icon, tip in (("mail", "p-nav-mail", "Mail (Ctrl+1)"), ("calendar", "p-nav-calendar", "Calendar (Ctrl+2)"),
                               ("people", "p-nav-people", "People (Ctrl+3)"), ("tasks", "p-nav-tasks", "Tasks (Ctrl+4)")):
            b = Gtk.ToggleButton()
            b.add(icons.image(icon, 20))
            b.set_relief(Gtk.ReliefStyle.NONE)
            b.set_tooltip_text(tip)
            b.set_active(key == "mail")
            b.connect("clicked", lambda btn, k=key: self.run("go:" + k))
            nav.pack_start(b, True, True, 0)
            self.nav_buttons[key] = b
        box.pack_end(nav, False, False, 0)
        self.folder_box = box

    def folder_label(self, f):
        if f["role"] in ROLE_NAMES:
            return ROLE_NAMES[f["role"]]
        return f["name"] or f["path"]

    def refresh_folders(self):
        sel = self.folder_id
        exp = set()

        def remember(m, path, it):
            if self.folder_view.row_expanded(path):
                exp.add((m[it][2], m[it][1]))
        self.folders_model.foreach(remember)
        first = not len(self.folders_model)
        self.folders_model.clear()
        outbox_n = {}
        for o in self.store.outbox():
            outbox_n[o["account"]] = outbox_n.get(o["account"], 0) + 1
        sel_it = None
        for acc in self.store.accounts():
            top = self.folders_model.append(None, ["<b>%s</b>" % GLib.markup_escape_text(acc["email"] or acc["name"]),
                                                   0, acc["id"], "p-account", "account"])
            nodes = {}
            for f in self.store.folders(acc["id"]):
                if f["role"] == "outbox" and not outbox_n.get(acc["id"]):
                    continue
                total, unread = self.store.counts(f["id"])
                name = GLib.markup_escape_text(self.folder_label(f))
                if f["role"] == "outbox":
                    label = "<b>%s</b> <span foreground='%s'>[%d]</span>" % (name, accent(), outbox_n[acc["id"]])
                elif f["role"] in ("drafts",) and total:
                    label = "%s <span foreground='%s'>[%d]</span>" % (name, accent(), total)
                elif unread and f["role"] not in ("sent", "trash", "drafts"):
                    label = "<b>%s</b> <span foreground='%s'>%d</span>" % (name, accent(), unread)
                else:
                    label = name
                parent = nodes.get(f["parent"], top) if f["parent"] else top
                it = self.folders_model.append(parent, [label, f["id"], acc["id"], ROLE_ICONS.get(f["role"], "p-folder"),
                                                        f["role"]])
                nodes[f["path"]] = it
                if f["id"] == sel:
                    sel_it = it
        sf = self.store.get("search-folders", []) or []
        if sf:
            top = self.folders_model.append(None, ["<b>Search Folders</b>", 0, 0, "p-filter", "search-root"])
            for i, f in enumerate(sf):
                rows = self.search_folder_rows(f)
                unread = sum(1 for r in rows if not r["seen"])
                name = GLib.markup_escape_text(f["name"])
                label = "<b>%s</b> <span foreground='%s'>%d</span>" % (name, accent(), unread) if unread else name
                it = self.folders_model.append(top, [label, -(i + 1), 0, "p-filter", "search"])
                if -(i + 1) == sel:
                    sel_it = it
        if first:
            self.folder_view.expand_all()
        else:
            def restore(m, path, it):
                if (m[it][2], m[it][1]) in exp or m[it][4] == "account":
                    self.folder_view.expand_row(path, False)
            self.folders_model.foreach(restore)
        if sel_it is not None:
            self._quiet_folder = True
            path = self.folders_model.get_path(sel_it)
            self.folder_view.expand_to_path(path)
            self.folder_view.get_selection().select_iter(sel_it)
            self._quiet_folder = False

    def select_first_inbox(self):
        for acc in self.store.accounts():
            f = self.store.folder_by_role(acc["id"], "inbox")
            if f:
                self.go_folder(f["id"])
                return
        self.update_title()

    def go_folder(self, fid):
        def find(m, path, it):
            if m[it][1] == fid:
                self.folder_view.expand_to_path(path)
                self.folder_view.get_selection().select_iter(it)
                return True
            return False
        self.folders_model.foreach(find)
        if self.folder_id != fid:
            self.folder_id = fid
            self.refresh_list()
        self.update_title()

    def _folder_selected(self, sel):
        if getattr(self, "_quiet_folder", False):
            return
        m, it = sel.get_selected()
        if it is None or not m[it][1]:
            return
        if m[it][1] != self.folder_id:
            self.mark_previous_read()
            self.folder_id = m[it][1]
            if self.search_text:
                self.search.set_text("")
                self.search_text = ""
            self.refresh_list()
            self.update_title()
            self.show_autoreply_bar()

    def _folder_button(self, tv, ev):
        if ev.button != 3:
            return False
        r = tv.get_path_at_pos(int(ev.x), int(ev.y))
        if r is None:
            return False
        tv.get_selection().select_path(r[0])
        m = tv.get_model()
        it = m.get_iter(r[0])
        menu = Gtk.Menu()
        items = []
        if m[it][1]:
            items = [("New Folder...", "new-folder"), ("Rename Folder", "rename-folder"), ("Delete Folder", "delete-folder"),
                     None, ("Mark All as Read", "mark-all-read"), ("Update Folder", "update-folder"),
                     ("Clean Up Folder", "clean-up:folder"), ("Delete All", "delete-all"), None,
                     ("Properties...", "folder-properties")]
            if m[it][4] == "trash":
                items.insert(5, ("Empty Folder", "empty-trash"))
        else:
            items = [("New Folder...", "new-folder:account:%d" % m[it][2]), ("Send/Receive", "send-receive:%d" % m[it][2]),
                     None, ("Account Settings...", "account-settings:%d" % m[it][2])]
        for x in items:
            if x is None:
                menu.append(Gtk.SeparatorMenuItem())
                continue
            mi = Gtk.MenuItem(label=x[0])
            mi.connect("activate", lambda _m, c=x[1]: self.run(c))
            menu.append(mi)
        menu.show_all()
        menu.attach_to_widget(tv, None)
        menu.popup_at_pointer(ev)
        return True

    def current_folder(self):
        return self.store.folder(self.folder_id) if self.folder_id and self.folder_id > 0 else None

    SEARCH_KINDS = [("unread", "Unread mail"), ("flagged", "Mail flagged for follow up"), ("important", "Important mail"),
                    ("attach", "Mail with attachments"), ("large", "Large mail (over 100 KB)"), ("from", "Mail from specific people"),
                    ("words", "Mail with specific words"), ("categorized", "Categorized mail")]

    def search_folder_rows(self, f):
        """The messages a search folder shows, from every mail folder but Deleted Items, Junk and the Outbox."""
        fids = [x["id"] for x in self.store.folders() if x["role"] not in ("trash", "junk", "outbox")]
        if not fids:
            return []
        marks = ",".join("?" * len(fids))
        kind, arg = f.get("kind"), (f.get("arg") or "").lower()
        if kind == "words" and arg:
            return self.store.search(arg, fids)
        where = {"unread": "seen=0", "flagged": "flagged=1", "important": "importance=2", "attach": "attach=1",
                 "large": "size>102400", "categorized": "categories!=''"}.get(kind)
        args = list(fids)
        if kind == "from":
            people = [x.strip() for x in arg.replace(",", ";").split(";") if x.strip()]
            if not people:
                return []
            where = "(" + " or ".join("lower(from_addr) like ? or lower(from_name) like ?" for _p in people) + ")"
            for p_ in people:
                args += ["%" + p_ + "%", "%" + p_ + "%"]
        if where is None:
            return []
        return [dict(r) for r in self.store.q("select * from messages where deleted=0 and folder in (%s) and %s order by date desc"
                                              % (marks, where), args)]

    def current_account(self):
        f = self.current_folder()
        if f:
            return self.store.account(f["account"])
        accs = self.store.accounts()
        return accs[0] if accs else None

    # ================================================================ message list
    def build_list(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.get_style_context().add_class("folio-listpane")
        bar = Gtk.Box(spacing=4)
        bar.get_style_context().add_class("folio-listbar")
        self.filter_all = Gtk.RadioButton.new_with_label(None, "All")
        self.filter_unread = Gtk.RadioButton.new_with_label_from_widget(self.filter_all, "Unread")
        for b in (self.filter_all, self.filter_unread):
            b.set_mode(False)
            b.set_relief(Gtk.ReliefStyle.NONE)
            b.get_style_context().add_class("folio-listfilter")
            bar.pack_start(b, False, False, 0)
        self.filter_all.connect("toggled", lambda b: b.get_active() and self.run("filter:all"))
        self.filter_unread.connect("toggled", lambda b: b.get_active() and self.run("filter:unread"))
        self.arrange_label = Gtk.Button(label="By Date ↓")
        self.arrange_label.set_relief(Gtk.ReliefStyle.NONE)
        self.arrange_label.connect("clicked", lambda *_: self.run("reverse-sort"))
        bar.pack_end(self.arrange_label, False, False, 0)
        box.pack_start(bar, False, False, 0)
        self.list_model = Gtk.TreeStore(int, str, str, str, str, str, bool, int, bool, int, str, str, str, int)
        tv = Gtk.TreeView(model=self.list_model)
        tv.get_selection().set_mode(Gtk.SelectionMode.MULTIPLE)
        tv.set_enable_search(False)
        tv.set_rubber_banding(False)
        tv.get_style_context().add_class("folio-messages")
        tv.get_selection().connect("changed", self._list_selected)
        tv.connect("row-activated", lambda *_: self.run("open-item"))
        tv.connect("button-press-event", self._list_button)
        tv.enable_model_drag_source(Gdk.ModifierType.BUTTON1_MASK,
                                    [Gtk.TargetEntry.new(DND_TARGET, Gtk.TargetFlags.SAME_APP, 0)],
                                    Gdk.DragAction.MOVE | Gdk.DragAction.COPY)
        tv.connect("drag-data-get", self._drag_get)
        self.list_view = tv
        sw = Gtk.ScrolledWindow()
        sw.add(tv)
        box.pack_start(sw, True, True, 0)
        self.empty_list = Gtk.Label(label="We didn't find anything to show here.")
        self.empty_list.get_style_context().add_class("folio-reading-empty")
        self.empty_list.set_no_show_all(True)
        box.pack_start(self.empty_list, False, False, 20)
        self.list_box = box
        self.build_columns()

    def vset(self, key, default=None):
        return self.view_settings.get(key, default)

    def set_vset(self, key, value):
        self.view_settings[key] = value
        try:
            self.app.save_settings()
        except OSError:
            pass

    def build_columns(self):
        tv = self.list_view
        for c in tv.get_columns():
            tv.remove_column(c)
        mode = self.vset("mode", "compact")
        tv.set_headers_visible(mode == "single")

        def icon_cell(kind):
            r = Gtk.CellRendererPixbuf()

            def f(col, cell, m, it, _d):
                name = None
                if m[it][C_ID]:
                    if kind == "imp":
                        name = "p-high" if m[it][C_IMP] == 2 else "p-low" if m[it][C_IMP] == 0 else None
                    elif kind == "attach":
                        name = "p-attach" if m[it][C_ATTACH] else None
                    elif kind == "flag":
                        name = "p-flag" if m[it][C_FLAG] == 1 else "p-flag-done" if m[it][C_FLAG] == 2 else None
                cell.set_property("pixbuf", icons.pixbuf(name, 16) if name else None)
            return r, f

        def add(title, renderer, func, expand=False, width=None, sort=None):
            col = Gtk.TreeViewColumn(title)
            if title in ("📎", "⚑"):
                img = icons.image("p-attach" if title == "📎" else "p-flag", 16)
                img.show()
                col.set_widget(img)
            col.pack_start(renderer, True)
            col.set_cell_data_func(renderer, func)
            col.set_expand(expand)
            col.set_resizable(True)
            if width:
                col.set_fixed_width(width)
                col.set_sizing(Gtk.TreeViewColumnSizing.FIXED)
            if sort:
                col.set_clickable(True)
                col.connect("clicked", lambda *_: self.run("arrange:" + sort))
            tv.append_column(col)
            return col

        def head_or(m, it, cell, markup):
            if not m[it][C_ID]:
                cell.set_property("markup", "<b>%s</b>" % GLib.markup_escape_text(m[it][C_HEAD]) if m[it][C_HEAD] else "")
                return True
            cell.set_property("markup", markup)
            return False

        if mode == "single":
            r, f = icon_cell("imp")
            add("!", r, f, width=24, sort="importance")
            r, f = icon_cell("attach")
            add("📎", r, f, width=24, sort="attach")
            for title, colno, key, w in (("From", C_FROM, "from", 150), ("Subject", C_SUBJ, "subject", None),
                                         ("Received", C_DATE, "date", 100), ("Size", C_SIZE, "size", 60)):
                tr = Gtk.CellRendererText()
                tr.set_property("ellipsize", Pango.EllipsizeMode.END)

                def f(col, cell, m, it, _d, colno=colno):
                    if colno == C_FROM and not m[it][C_ID]:
                        head_or(m, it, cell, "")
                        return
                    if not m[it][C_ID]:
                        cell.set_property("markup", "")
                        return
                    t = GLib.markup_escape_text(m[it][colno])
                    if colno == C_SUBJ and m[it][C_COUNT] > 1:
                        t += " <span foreground='%s'>(%d)</span>" % (accent(), m[it][C_COUNT])
                    cell.set_property("markup", "<b>%s</b>" % t if m[it][C_UNREAD] else t)
                add(title, tr, f, expand=w is None, width=w, sort=key)
            cr = Gtk.CellRendererText()

            def fc(col, cell, m, it, _d):
                cats = [c for c in m[it][C_CATS].split(",") if c]
                cell.set_property("markup", " ".join("<span foreground='#%s'>■</span>" % CAT_COLORS.get(c, "808080")
                                                     for c in cats))
            add("Categories", cr, fc, width=50, sort="categories")
            r, f = icon_cell("flag")
            add("⚑", r, f, width=26, sort="flag")
        else:
            preview_lines = int(self.vset("preview", 1))
            tr = Gtk.CellRendererText()
            tr.set_property("ellipsize", Pango.EllipsizeMode.END)
            tr.set_padding(6, 4)

            def f(col, cell, m, it, _d):
                if head_or(m, it, cell, ""):
                    return
                unread = m[it][C_UNREAD]
                who = GLib.markup_escape_text(m[it][C_FROM] or "(no sender)")
                subj = GLib.markup_escape_text(m[it][C_SUBJ] or "(no subject)")
                if m[it][C_COUNT] > 1:
                    subj += " (%d)" % m[it][C_COUNT]
                line1 = "<b>%s</b>" % who if unread else who
                line2 = ("<span foreground='%s'><b>%s</b></span>" % (accent(), subj)) if unread else subj
                cats = [c for c in m[it][C_CATS].split(",") if c]
                if cats:
                    line2 += "  " + " ".join("<span foreground='#%s'>■</span>" % CAT_COLORS.get(c, "808080") for c in cats)
                out = line1 + "\n" + line2
                if preview_lines and m[it][C_PREV] and mode != "single":
                    out += "\n<span foreground='#767676'>%s</span>" % GLib.markup_escape_text(m[it][C_PREV][:160])
                cell.set_property("markup", out)
            add("", tr, f, expand=True)
            dr = Gtk.CellRendererText()
            dr.set_property("xalign", 1.0)
            dr.set_padding(4, 4)

            def fd(col, cell, m, it, _d):
                if not m[it][C_ID]:
                    cell.set_property("markup", "")
                    return
                t = GLib.markup_escape_text(m[it][C_DATE])
                cell.set_property("markup", "<span foreground='%s'>%s</span>" % (accent(), t) if m[it][C_UNREAD] else t)
            dr.set_property("yalign", 0.2)
            add("", dr, fd)
            icol = Gtk.TreeViewColumn("")
            for kind in ("attach", "imp", "flag"):
                r, fn = icon_cell(kind)
                r.set_property("yalign", 0.2)
                icol.pack_start(r, False)
                icol.set_cell_data_func(r, fn)
            tv.append_column(icol)

    def list_rows(self):
        """The messages to show: the folder (or the search), filtered and sorted."""
        if self.search_text:
            acc = self.current_account()
            fids = [f["id"] for f in self.store.folders(acc["id"])] if acc else None
            rows = self.store.search(self.search_text, fids)
        elif self.folder_id and self.folder_id < 0:
            sf = self.store.get("search-folders", []) or []
            i = -self.folder_id - 1
            rows = self.search_folder_rows(sf[i]) if i < len(sf) else []
        elif self.folder_id:
            rows = self.store.messages(self.folder_id)
        else:
            rows = []
        flt = self.filter
        now = time.time()
        me = set(a["email"].lower() for a in self.store.accounts() if a["email"])
        if flt == "unread":
            rows = [r for r in rows if not r["seen"]]
        elif flt == "attach":
            rows = [r for r in rows if r["attach"]]
        elif flt == "flagged":
            rows = [r for r in rows if r["flagged"]]
        elif flt == "important":
            rows = [r for r in rows if r["importance"] == 2]
        elif flt == "week":
            rows = [r for r in rows if r["date"] >= now - 7 * 86400]
        elif flt == "categorized":
            rows = [r for r in rows if r["categories"]]
        elif flt == "to-me":
            rows = [r for r in rows if any(m in (r["to_text"] or "").lower() for m in me)]
        key = self.vset("arrange", "date")
        keys = {"date": lambda r: r["date"], "from": lambda r: (r["from_name"] or r["from_addr"]).lower(),
                "to": lambda r: (r["to_text"] or "").lower(), "subject": lambda r: (r["subject"] or "").lower(),
                "size": lambda r: r["size"], "importance": lambda r: r["importance"],
                "flag": lambda r: (r["flagged"], r["date"]), "attach": lambda r: (r["attach"], r["date"]),
                "categories": lambda r: r["categories"], "type": lambda r: r["draft"]}
        rev = self.vset("reverse", key in ("date", "size", "importance", "flag", "attach"))
        rows.sort(key=keys.get(key, keys["date"]), reverse=rev)
        return rows

    def _row_values(self, r, count=1):
        f = self.current_folder()
        sentish = f and f["role"] in ("sent", "drafts", "outbox")
        who = r["to_text"] if sentish else (r["from_name"] or r["from_addr"])
        return [r["id"], "", who or "", r["subject"] or "", when_text(r["date"]), nice_size(r["size"]), not r["seen"],
                2 if r["done"] else 1 if r["flagged"] else 0, bool(r["attach"]), r["importance"], r["categories"] or "",
                r["snippet"] or "", r["to_text"] or "", count]

    def refresh_list(self, keep=True):
        sel = self.selected_ids() if keep else []
        tv = self.list_view
        adj = tv.get_vadjustment()
        pos = adj.get_value() if adj and keep else 0
        self._quiet_list = True
        m = self.list_model
        m.clear()
        rows = self.list_rows()
        self.rows = rows
        groups = self.vset("groups", True) and not self.search_text
        convs = self.vset("conversations", False)
        key = self.vset("arrange", "date")
        heads = {}

        def group_of(r):
            if key == "date":
                return date_group(r["date"])
            if key == "from":
                return (r["from_name"] or r["from_addr"] or "").lower(), r["from_name"] or r["from_addr"] or "(none)"
            if key == "subject":
                return (r["subject"] or "").lower(), r["subject"] or "(no subject)"
            if key == "importance":
                return r["importance"], {2: "Importance: High", 1: "Importance: Normal", 0: "Importance: Low"}[r["importance"]]
            if key == "attach":
                return r["attach"], "With Attachments" if r["attach"] else "Without Attachments"
            if key == "flag":
                return r["flagged"], "Flagged" if r["flagged"] else "Not Flagged"
            if key == "categories":
                return r["categories"], r["categories"].replace(",", ", ") or "(none)"
            if key == "size":
                s = r["size"]
                lab = ("Tiny (< 10 KB)" if s < 10240 else "Small (10 - 25 KB)" if s < 25600 else
                       "Medium (25 - 100 KB)" if s < 102400 else "Large (100 - 500 KB)" if s < 512000 else
                       "Very Large (500 KB - 1 MB)" if s < 1048576 else "Huge (1 - 5 MB)" if s < 5242880 else "Enormous (> 5 MB)")
                return lab, lab
            return 0, ""
        threads = {}
        order = []
        if convs:
            for r in rows:
                t = r["thread"] or str(r["id"])
                if t not in threads:
                    threads[t] = []
                    order.append(t)
                threads[t].append(r)
        else:
            order = [str(r["id"]) for r in rows]
            threads = {str(r["id"]): [r] for r in rows}
        for t in order:
            msgs = threads[t]
            first = msgs[0]
            parent = None
            if groups:
                g = group_of(first)
                if g not in heads:
                    heads[g] = m.append(None, [0, g[1]] + [""] * 4 + [False, 0, False, 1, "", "", "", 0])
                parent = heads[g]
            vals = self._row_values(first, len(msgs))
            if len(msgs) > 1:
                vals[C_UNREAD] = any(not x["seen"] for x in msgs)
            it = m.append(parent, vals)
            for x in msgs[1:]:
                m.append(it, self._row_values(x))
        tv.expand_all() if groups and not convs else None
        if groups and convs:
            for it in heads.values():
                tv.expand_row(m.get_path(it), False)
        self.empty_list.set_visible(not rows)
        if sel:
            self.select_ids(sel)
        if adj and keep:
            GLib.idle_add(lambda: (adj.set_value(pos), False)[1])
        self._quiet_list = False
        arr = {"date": "Date", "from": "From", "to": "To", "subject": "Subject", "size": "Size", "importance": "Importance",
               "flag": "Flag", "attach": "Attachments", "categories": "Categories", "type": "Type"}.get(key, "Date")
        rev = self.vset("reverse", key in ("date", "size", "importance", "flag", "attach"))
        self.arrange_label.set_label("By %s %s" % (arr, "↓" if rev else "↑"))
        self.update_status()
        if not self.selected_ids():
            self.reading.clear("Select an item to read" if rows else "")

    def iter_rows(self):
        out = []

        def walk(m, path, it):
            if m[it][C_ID]:
                out.append((m[it][C_ID], it))
        self.list_model.foreach(walk)
        return out

    def selected_ids(self):
        if not hasattr(self, "list_view"):
            return []
        m, paths = self.list_view.get_selection().get_selected_rows()
        out = []
        for p in paths:
            it = m.get_iter(p)
            mid = m[it][C_ID]
            if not mid:
                continue
            out.append(mid)
            # a collapsed conversation stands for all its messages
            if m.iter_has_child(it) and not self.list_view.row_expanded(p):
                c = m.iter_children(it)
                while c is not None:
                    out.append(m[c][C_ID])
                    c = m.iter_next(c)
        return list(dict.fromkeys(out))

    def select_ids(self, ids, scroll=False):
        sel = self.list_view.get_selection()
        sel.unselect_all()
        first = None
        for mid, it in self.iter_rows():
            if mid in ids:
                p = self.list_model.get_path(it)
                self.list_view.expand_to_path(p)
                sel.select_iter(it)
                first = first or p
        if first is not None and scroll:
            self.list_view.scroll_to_cell(first, None, False, 0, 0)

    def select_index(self, i):
        rows = self.iter_rows()
        if not rows:
            return
        i = max(0, min(len(rows) - 1, i))
        self.select_ids([rows[i][0]], scroll=True)
        self.list_view.set_cursor(self.list_model.get_path(rows[i][1]), None, False)

    def _list_selected(self, sel):
        if getattr(self, "_quiet_list", False):
            return
        ids = self.selected_ids()
        cur = ids[0] if len(ids) == 1 or (ids and self._is_conversation_selection()) else None
        if cur != self.prev_selected:
            self.mark_previous_read()
        if cur:
            if self.reading.mid != cur:
                self.reading.show_message(cur)
                self._arm_read_timer(cur)
            self.prev_selected = cur
        else:
            self.prev_selected = None
            if len(ids) > 1:
                self.reading.clear("%d items selected" % len(ids))
            else:
                self.reading.clear()
        self.update_status()

    def _is_conversation_selection(self):
        m, paths = self.list_view.get_selection().get_selected_rows()
        return len(paths) == 1

    def _arm_read_timer(self, mid):
        how = self.app.setting("mark_read", "change")
        if getattr(self, "_read_timer", None):
            GLib.source_remove(self._read_timer)
            self._read_timer = None
        if how == "wait":
            secs = int(self.app.setting("mark_read_seconds", 5))

            def go():
                self._read_timer = None
                if self.reading.mid == mid:
                    self.mark_read([mid])
                return False
            self._read_timer = GLib.timeout_add_seconds(max(0, secs), go) if secs else GLib.idle_add(go)

    def mark_previous_read(self):
        mid = self.prev_selected
        if mid and self.app.setting("mark_read", "change") == "change":
            m = self.store.message(mid)
            if m and not m["seen"]:
                self.mark_read([mid])

    def mark_read(self, ids, on=True):
        ids = [i for i in ids if (self.store.message(i) or {}).get("seen") != int(on)]
        if not ids:
            return
        self.store.set_flag(ids, "seen", on)
        self.push_soon()

    def _list_button(self, tv, ev):
        if ev.button != 3:
            return False
        r = tv.get_path_at_pos(int(ev.x), int(ev.y))
        if r is None:
            return False
        if not tv.get_selection().path_is_selected(r[0]):
            tv.get_selection().unselect_all()
            tv.get_selection().select_path(r[0])
        menu = Gtk.Menu()

        def item(label, cmd=None, sub=None):
            mi = Gtk.MenuItem(label=label)
            if sub is not None:
                sm = Gtk.Menu()
                for x in sub:
                    if x is None:
                        sm.append(Gtk.SeparatorMenuItem())
                        continue
                    if isinstance(x[1], list):
                        sm.append(item(x[0], sub=x[1]))
                        continue
                    smi = Gtk.MenuItem(label=x[0])
                    smi.connect("activate", lambda _m, c=x[1]: self.run(c))
                    sm.append(smi)
                mi.set_submenu(sm)
            elif cmd:
                mi.connect("activate", lambda _m: self.run(cmd))
            return mi
        for x in [("Copy", "copy"), ("Quick Print", "print"), None, ("Reply", "reply"), ("Reply All", "reply-all"),
                  ("Forward", "forward"), None, ("Mark as Read", "mark-read"), ("Mark as Unread", "mark-unread"),
                  ("Categorize", [(n, "categorize:" + n.split()[0]) for n, _c in CATEGORIES] + [None, ("Clear All Categories", "categorize:")]),
                  ("Follow Up", [("Flag Message", "flag:on"), ("Mark Complete", "flag:done"), ("Clear Flag", "flag:off")]),
                  None, ("Junk", [("Block Sender", "block-sender"), ("Never Block Sender", "never-block"), ("Not Junk", "not-junk")]),
                  ("Delete", "delete"), ("Archive...", "archive"), None,
                  ("Move", move_menu(self)), ("Rules", [("Always Move Messages From This Sender...", "rule-from")]),
                  None, ("Add Sender to Contacts", "add-sender-to-contacts"), ("Save As...", "save-as"),
                  ("Open in New Window", "open-item")]:
            if x is None:
                menu.append(Gtk.SeparatorMenuItem())
            elif isinstance(x[1], list):
                menu.append(item(x[0], sub=x[1]))
            else:
                menu.append(item(x[0], x[1]))
        menu.show_all()
        menu.attach_to_widget(tv, None)
        menu.popup_at_pointer(ev)
        return True

    # ---- drag to folders
    def _drag_get(self, tv, ctx, data, info, time_):
        data.set(Gdk.Atom.intern(DND_TARGET, False), 8, ",".join(str(i) for i in self.selected_ids()).encode())

    def _drop_on_folder(self, tv, ctx, x, y, data, info, time_):
        r = tv.get_dest_row_at_pos(x, y)
        ok = False
        if r is not None:
            m = tv.get_model()
            fid = m[m.get_iter(r[0])][1]
            ids = [int(i) for i in (data.get_data() or b"").decode().split(",") if i]
            if fid and ids:
                copy = ctx.get_selected_action() == Gdk.DragAction.COPY
                self.copy_to(ids, fid) if copy else self.move_to(ids, fid)
                ok = True
        ctx.finish(ok, False, time_)

    # ================================================================ refreshing
    def _store_changed(self, what, folder=None):
        if self._refresh_pending:
            return
        self._refresh_pending = True
        GLib.timeout_add(150, self._do_refresh)

    def _do_refresh(self):
        self._refresh_pending = False
        self.refresh_folders()
        self.refresh_list()
        if self.reading.mid and self.store.message(self.reading.mid) is None:
            self.reading.clear()
        return False

    def update_title(self):
        if self.module in ("calendar", "people", "tasks"):
            return
        f = self.current_folder()
        acc = self.current_account()
        if self.search_text:
            t = "Search Results"
        elif f:
            t = self.folder_label(f)
        else:
            t = "Mail"
        parts = [t]
        if acc:
            parts.append(acc["email"] or acc["name"])
        parts.append(APP_NAME)
        self.title_label.set_text(" - ".join(parts))
        self.set_title(" - ".join(parts))

    def update_status(self):
        if self.module == "calendar" and self.calview is not None:
            return self.update_cal_status(self.calview)
        if self.module == "people" and self.peopleview is not None:
            return self.update_people_status(self.peopleview)
        if self.module == "tasks" and self.tasksview is not None:
            return self.update_tasks_status(self.tasksview)
        n = len(getattr(self, "rows", []))
        unread = sum(1 for r in getattr(self, "rows", []) if not r["seen"])
        sel = len(self.selected_ids())
        left = "Items: %d" % n
        if unread:
            left += "    Unread: %d" % unread
        if sel > 1:
            left += "    Selected: %d" % sel
        if self.filter != "all":
            left += "    Filter applied"
        self.status.left.set_text(left)
        sy = self.app.syncer
        if sy.offline:
            right = "Working Offline"
        else:
            errs = [t for t in sy.errors.values()]
            busy = [t for t in sy.status.values() if t.endswith("...")]
            if busy:
                right = busy[0]
            elif errs:
                right = errs[0]
            elif self.store.accounts() and sy.status:
                right = "All folders are up to date."
            elif self.store.accounts():
                right = "Connected"
            else:
                right = "No accounts yet: File > Add Account"
        self.status.right.set_text(right)
        b = getattr(self, "offline_button", None)
        ctx = (getattr(b, "main", b)).get_style_context() if b is not None else None
        if ctx is not None:
            (ctx.add_class if sy.offline else ctx.remove_class)("checked")

    def push_soon(self):
        """Flags and moves made here reach the server shortly after."""
        if self._push_timer:
            GLib.source_remove(self._push_timer)
        f = self.current_folder()

        def go():
            self._push_timer = None
            if f and not self.app.syncer.offline:
                acc = self.store.account(f["account"])
                if acc and acc["kind"] == "imap":
                    fids = [x["id"] for x in self.store.folders(acc["id"]) if self.store.pending(x["id"]) or self.store.gone(x["id"])]
                    if fids:
                        self.app.send_receive([acc["id"]], fids)
            return False
        self._push_timer = GLib.timeout_add_seconds(int(os.environ.get("FOLIO_POST_PUSH_DELAY", "8")), go)

    def apply_layout(self):
        rp = self.vset("reading", "right")
        fp = self.vset("folder_pane", "normal")
        orient = Gtk.Orientation.VERTICAL if rp == "bottom" else Gtk.Orientation.HORIZONTAL
        self.right.set_orientation(orient)
        self.reading.set_visible(rp != "off")
        self.folder_box.set_visible(fp != "off")
        if fp == "min":
            self.body.set_position(48)
        elif fp == "normal" and self.body.get_position() < 100:
            self.body.set_position(240)
        alloc = self.right.get_allocated_width() if rp != "bottom" else self.right.get_allocated_height()
        if alloc > 50:
            self.right.set_position(int(alloc * (0.42 if rp == "right" else 0.45)))
        else:
            GLib.idle_add(self._initial_split)

    def _initial_split(self):
        rp = self.vset("reading", "right")
        alloc = self.right.get_allocated_width() if rp != "bottom" else self.right.get_allocated_height()
        if alloc > 50:
            self.right.set_position(int(alloc * (0.42 if rp == "right" else 0.45)))
            return False
        return True

    # ================================================================ commands
    def run(self, cmd, *args):
        if cmd is None:
            return None
        name, _, arg = cmd.partition(":")
        fn = getattr(self, "act_" + name.replace("-", "_"), None)
        if fn is None:
            return self.not_available(cmd)
        if self.keytips.active:
            self.keytips.leave()
        try:
            return fn(arg) if arg or _ else fn()
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.dialogs.message("Something went wrong running this command.\n\n%s" % e)
            return None

    def not_available(self, cmd):
        label = cmd.split(":", 1)[1] if cmd.startswith("not-available:") else cmd
        self.missing_log.append(cmd)
        self.dialogs.info("“%s” isn't available yet in %s." % (label, APP_NAME))

    def act_not_available(self, label):
        self.not_available("not-available:" + label)

    def act_out_of_scope(self, label):
        self.dialogs.info("“%s” isn't part of %s: it has no cloud of its own to publish to. E-mail Calendar sends "
                          "it to people instead." % (label, APP_NAME) if label == "Publish Online" else
                          "“%s” isn't part of %s." % (label, APP_NAME))

    def focus_document(self):
        self.list_view.grab_focus()

    def show_backstage(self, page="info"):
        self.backstage.open(page)

    def ask(self, text, yes="Yes", no="No"):
        d = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.QUESTION, text=text)
        d.set_title(APP_NAME)
        d.add_button(no, Gtk.ResponseType.NO)
        d.add_button(yes, Gtk.ResponseType.YES)
        d.set_default_response(Gtk.ResponseType.YES)
        r = d.run()
        d.destroy()
        return r == Gtk.ResponseType.YES

    def need_selection(self):
        ids = self.selected_ids()
        if not ids:
            self.dialogs.info("Select a message first.")
        return ids

    # ---- new
    def act_new_email(self):
        if self.module == "tasks":
            return self.act_new_task()
        if self.module == "calendar":
            return self.act_new_appointment()
        if self.module == "people":
            return self.act_new_contact()
        acc = self.current_account()
        self.app.compose(account=acc["id"] if acc else None)

    def act_new(self):
        self.act_new_email()

    # ---- respond
    def _respond(self, kind, mid=None):
        mid = mid or (self.need_selection() or [None])[0]
        if not mid:
            return None
        m = self.store.message(mid)
        f = self.store.folder(m["folder"]) if m else None
        if m and m["draft"] and kind == "open":
            return self.app.compose(draft=mid)
        return self.app.compose(reply_to=mid, mode=kind, account=f["account"] if f else None)

    def act_reply(self, mid=None):
        return self._respond("reply", mid)

    def act_reply_all(self, mid=None):
        return self._respond("reply-all", mid)

    def act_forward(self, mid=None):
        return self._respond("forward", mid)

    def act_forward_attachment(self):
        ids = self.need_selection()
        if not ids:
            return None
        acc = self.current_account()
        atts = []
        subj = ""
        for mid in ids:
            m = self.store.message(mid)
            subj = subj or m["subject"]
            name = re.sub(r"[^\w .,-]+", "", m["subject"] or "message")[:60] or "message"
            atts.append((name + ".eml", "message/rfc822", self.store.raw(mid)))
        return self.app.compose(account=acc["id"] if acc else None, subject="FW: " + (subj or ""), attach_data=atts)

    # ---- moving and deleting
    def move_to(self, ids, fid, remember=True):
        if not ids:
            return []
        src = {mid: (self.store.message(mid) or {}).get("folder") for mid in ids}
        new = self.store.move(ids, fid)
        if remember:
            self.undo_stack.append(("move", [(n, src[o]) for o, n in zip(ids, new) if src.get(o)]))
        self.push_soon()
        return new

    def copy_to(self, ids, fid):
        out = []
        for mid in ids:
            m = self.store.message(mid)
            if m is None:
                continue
            flags = [f for f in ("seen", "flagged", "answered", "draft") if m[f]]
            n = self.store.add_message(fid, self.store.raw(mid), 0, flags, m["date"])
            dst_acc = self.store.account(self.store.folder(fid)["account"])
            self.store.set_fields(n, categories=m["categories"], pending="" if dst_acc["kind"] in ("local", "pop3") else "new")
            out.append(n)
        self.store.changed("messages")
        self.push_soon()
        return out

    def _role_folder(self, role, mid=None):
        f = self.store.folder(self.store.message(mid)["folder"]) if mid else self.current_folder()
        if f is None:
            return None
        rf = self.store.folder_by_role(f["account"], role)
        if rf is None and role in ("trash", "archive", "junk"):
            acc = self.store.account(f["account"])
            if acc["kind"] in ("local", "pop3", "rss"):
                rf = {"id": self.store.ensure_folder(acc["id"], ROLE_NAMES[role], role)}
        return rf

    def _next_after(self, ids):
        rows = [r[0] for r in self.iter_rows()]
        idx = [rows.index(i) for i in ids if i in rows]
        if not idx:
            return None
        after = [r for r in rows[max(idx) + 1:] if r not in ids]
        before = [r for r in rows[:min(idx)] if r not in ids]
        return after[0] if after else (before[-1] if before else None)

    def act_delete(self, permanent=False):
        ids = self.need_selection()
        if not ids:
            return
        nxt = self._next_after(ids)
        by_folder = {}
        for mid in ids:
            m = self.store.message(mid)
            if m:
                by_folder.setdefault(m["folder"], []).append(mid)
        for fid, group in by_folder.items():
            trash = self._role_folder("trash", group[0])
            f = self.store.folder(fid)
            if permanent or trash is None or f["role"] == "trash":
                if not self.ask("This permanently deletes %s. Continue?" % ("this item" if len(group) == 1 else
                                                                          "%d items" % len(group))):
                    return
                for mid in group:
                    self.store.delete(mid)
                self.undo_stack.append(("none", None))
            else:
                self.move_to(group, trash["id"])
        self.push_soon()
        self._after_remove(nxt)

    def _after_remove(self, nxt):
        self._do_refresh()
        if nxt:
            self.select_ids([nxt], scroll=True)

    def act_delete_permanently(self):
        self.act_delete(permanent=True)

    def act_archive(self):
        ids = self.need_selection()
        if not ids:
            return
        nxt = self._next_after(ids)
        af = self._role_folder("archive", ids[0])
        if af is None:
            f = self.store.folder(self.store.message(ids[0])["folder"])
            fid = self.store.ensure_folder(f["account"], "Archive", "archive", f["delim"] or "/")
            acc = self.store.account(f["account"])
            if acc["kind"] == "imap" and not self.app.syncer.offline:
                try:
                    self.app.syncer.server_op(acc["id"], lambda c: c.create("Archive"))
                except Exception:
                    pass
            af = {"id": fid}
        self.move_to(ids, af["id"])
        self._after_remove(nxt)

    def act_move(self, fid):
        ids = self.need_selection()
        if not ids:
            return
        nxt = self._next_after(ids)
        self.move_to(ids, int(fid))
        self._after_remove(nxt)

    def act_copy_folder_item(self, fid):
        self.copy_to(self.selected_ids(), int(fid))

    def choose_folder(self, title="Move Items"):
        d = Gtk.Dialog(title=title, transient_for=self, modal=True)
        d.get_style_context().add_class("folio-dialog")
        d.add_button("Cancel", Gtk.ResponseType.CANCEL)
        d.add_button("OK", Gtk.ResponseType.OK)
        d.set_default_size(340, 420)
        box = d.get_content_area()
        box.set_border_width(10)
        box.pack_start(Gtk.Label(label="Move the selected items to the folder:", xalign=0), False, False, 4)
        model = Gtk.TreeStore(str, int)
        for acc in self.store.accounts():
            top = model.append(None, [acc["email"] or acc["name"], 0])
            nodes = {}
            for f in self.store.folders(acc["id"]):
                if f["role"] == "outbox":
                    continue
                parent = nodes.get(f["parent"], top) if f["parent"] else top
                nodes[f["path"]] = model.append(parent, [self.folder_label(f), f["id"]])
        tv = Gtk.TreeView(model=model)
        tv.set_headers_visible(False)
        tv.append_column(Gtk.TreeViewColumn("", Gtk.CellRendererText(), text=0))
        tv.expand_all()
        tv.connect("row-activated", lambda *_: d.response(Gtk.ResponseType.OK))
        sw = Gtk.ScrolledWindow()
        sw.add(tv)
        box.pack_start(sw, True, True, 0)
        d.show_all()
        r = d.run()
        m, it = tv.get_selection().get_selected()
        fid = m[it][1] if (r == Gtk.ResponseType.OK and it is not None) else 0
        d.destroy()
        return fid or None

    def act_move_other(self):
        ids = self.need_selection()
        if ids:
            fid = self.choose_folder()
            if fid:
                self.act_move(fid)

    def act_copy_other(self):
        ids = self.need_selection()
        if ids:
            fid = self.choose_folder("Copy Items")
            if fid:
                self.copy_to(ids, fid)

    def act_undo(self):
        while self.undo_stack:
            kind, data = self.undo_stack.pop()
            if kind == "move":
                for mid, fid in data:
                    if self.store.message(mid):
                        self.store.move([mid], fid)
                self.push_soon()
                return True
            if kind == "flags":
                for mid, field, val in data:
                    if self.store.message(mid):
                        if field in self.store.FLAG_COLS:
                            self.store.set_flag([mid], field, bool(val))
                        else:
                            self.store.set_fields(mid, **{field: val})
                self.push_soon()
                return True
            if kind == "none":
                break
        return False

    # ---- junk
    def _senders(self, ids):
        return list(dict.fromkeys((self.store.message(i) or {}).get("from_addr", "").lower() for i in ids if i))

    def act_block_sender(self):
        ids = self.need_selection()
        if not ids:
            return
        blocked = self.store.get("blocked-senders", []) or []
        for s in self._senders(ids):
            if s and s not in blocked:
                blocked.append(s)
        self.store.put("blocked-senders", blocked)
        junk = self._role_folder("junk", ids[0])
        if junk:
            nxt = self._next_after(ids)
            self.move_to(ids, junk["id"])
            self._after_remove(nxt)

    def act_never_block(self):
        ids = self.need_selection()
        if not ids:
            return
        safe = self.store.get("safe-senders", []) or []
        blocked = self.store.get("blocked-senders", []) or []
        for s in self._senders(ids):
            if s and s not in safe:
                safe.append(s)
            if s in blocked:
                blocked.remove(s)
        self.store.put("safe-senders", safe)
        self.store.put("blocked-senders", blocked)

    def act_not_junk(self):
        ids = self.need_selection()
        if not ids:
            return
        self.act_never_block()
        inbox = self._role_folder("inbox", ids[0])
        if inbox:
            nxt = self._next_after(ids)
            self.move_to(ids, inbox["id"])
            self._after_remove(nxt)

    def act_junk_options(self):
        from .options import junk_options
        junk_options(self)

    # ---- conversations
    def act_ignore(self):
        ids = self.need_selection()
        if not ids:
            return
        threads = set((self.store.message(i) or {}).get("thread") for i in ids)
        ign = self.store.get("ignored-threads", []) or []
        ign = list(dict.fromkeys(ign + [t for t in threads if t]))
        self.store.put("ignored-threads", ign[-2000:])
        allids = []
        for t in threads:
            allids += [m["id"] for m in self.store.conversation(t)
                       if (self.store.folder(m["folder"]) or {}).get("role") not in ("trash", "sent")]
        nxt = self._next_after(ids)
        by_acc = {}
        for mid in allids:
            f = self.store.folder(self.store.message(mid)["folder"])
            by_acc.setdefault(f["account"], []).append(mid)
        for aid, group in by_acc.items():
            trash = self.store.folder_by_role(aid, "trash")
            if trash:
                self.move_to(group, trash["id"])
        self._after_remove(nxt)

    def act_clean_up(self, what="conversation"):
        """Removes messages whose whole text is quoted in a later message of the same conversation."""
        if what == "folder":
            rows = self.store.messages(self.folder_id) if self.folder_id else []
        else:
            ids = self.need_selection()
            if not ids:
                return
            rows = []
            for t in set((self.store.message(i) or {}).get("thread") for i in ids):
                rows += [m for m in self.store.conversation(t) if m["folder"] == self.folder_id]
        threads = {}
        for r in rows:
            threads.setdefault(r["thread"], []).append(r)
        redundant = []
        for t, msgs in threads.items():
            msgs.sort(key=lambda r: r["date"])
            texts = {m["id"]: _norm(mime.text_of(mime.parse(self.store.raw(m["id"])))) for m in msgs}
            for i, m in enumerate(msgs[:-1]):
                mine = texts[m["id"]]
                if not mine or m["flagged"]:
                    continue
                for later in msgs[i + 1:]:
                    if mine in texts[later["id"]]:
                        redundant.append(m["id"])
                        break
        if not redundant:
            self.dialogs.info("No messages were cleaned up.")
            return 0
        trash = self._role_folder("trash")
        if trash:
            self.move_to(redundant, trash["id"])
        self._do_refresh()
        return len(redundant)

    # ---- tags
    def act_toggle_read(self):
        ids = self.need_selection()
        if not ids:
            return
        unread = any(not (self.store.message(i) or {}).get("seen") for i in ids)
        self.undo_stack.append(("flags", [(i, "seen", (self.store.message(i) or {}).get("seen", 0)) for i in ids]))
        self.mark_read(ids, unread)
        if not unread:
            self.prev_selected = None

    def act_mark_read(self):
        ids = self.need_selection()
        if ids:
            self.mark_read(ids, True)

    def act_mark_unread(self):
        ids = self.need_selection()
        if ids:
            self.mark_read(ids, False)
            self.prev_selected = None

    def act_categorize(self, name=""):
        ids = self.need_selection()
        if not ids:
            return
        self.undo_stack.append(("flags", [(i, "categories", (self.store.message(i) or {}).get("categories", "")) for i in ids]))
        for mid in ids:
            m = self.store.message(mid)
            cats = [c for c in (m["categories"] or "").split(",") if c]
            if not name:
                cats = []
            elif name in cats and len(ids) == 1:
                cats.remove(name)
            elif name not in cats:
                cats.append(name)
            self.store.set_fields(mid, categories=",".join(cats))
        self.reading.show_message(self.reading.mid) if self.reading.mid in ids else None

    def act_flag(self, how="toggle"):
        ids = self.need_selection()
        if not ids:
            return
        self.undo_stack.append(("flags", [(i, "flagged", (self.store.message(i) or {}).get("flagged", 0)) for i in ids] +
                                [(i, "done", (self.store.message(i) or {}).get("done", 0)) for i in ids]))
        if how == "toggle":
            how = "off" if all((self.store.message(i) or {}).get("flagged") for i in ids) else "on"
        for mid in ids:
            if how == "on":
                self.store.set_flag([mid], "flagged", True)
                self.store.set_flag([mid], "done", False, pending=False)
            elif how == "done":
                self.store.set_flag([mid], "flagged", False)
                self.store.set_flag([mid], "done", True, pending=False)
            else:
                self.store.set_flag([mid], "flagged", False)
                self.store.set_flag([mid], "done", False, pending=False)
        self.push_soon()
        if self.reading.mid in ids:
            self.reading.show_message(self.reading.mid)

    # ---- quick steps
    def quick_steps(self):
        steps = self.store.get("quick-steps", None)
        if steps is None:
            steps = [{"name": "Done", "actions": ["read", "flag-done", "archive"]},
                     {"name": "Reply & Delete", "actions": ["reply", "delete"]},
                     {"name": "Flag & Move to Archive", "actions": ["flag", "archive"]}]
            self.store.put("quick-steps", steps)
        return steps

    def quick_steps_menu(self):
        steps = self.quick_steps()
        return [(s["name"], "quick-step:%d" % i) for i, s in enumerate(steps)] + [None, ("New Quick Step...", "new-quick-step"),
                                                                                  ("Manage Quick Steps...", "manage-quick-steps")]

    def act_quick_step(self, i):
        steps = self.quick_steps()
        step = steps[int(i)]
        ids = self.need_selection()
        if not ids:
            return
        for a in step["actions"]:
            if a == "read":
                self.mark_read(ids, True)
            elif a == "unread":
                self.mark_read(ids, False)
            elif a == "flag":
                self.act_flag("on")
            elif a == "flag-done":
                self.act_flag("done")
            elif a == "archive":
                self.act_archive()
                ids = []
            elif a == "delete":
                self.act_delete()
                ids = []
            elif a == "reply":
                self.act_reply(ids[0] if ids else None)
            elif a == "forward":
                self.act_forward(ids[0] if ids else None)
            elif a.startswith("move:"):
                self.act_move(a[5:])
                ids = []
            elif a.startswith("category:"):
                self.act_categorize(a[9:])
            if not ids:
                break

    def act_new_quick_step(self):
        from .options import quick_step_dialog
        quick_step_dialog(self)

    def act_manage_quick_steps(self):
        from .options import manage_quick_steps
        manage_quick_steps(self)

    # ---- rules
    def act_rule_from(self):
        ids = self.need_selection()
        if not ids:
            return
        sender = self._senders(ids)[0]
        fid = self.choose_folder("Always move messages from %s" % sender)
        if not fid:
            return
        rules = self.store.get("rules", []) or []
        rules.append({"name": "From %s" % sender, "from": sender, "move": fid, "on": True})
        self.store.put("rules", rules)
        # run it on the folder now
        hits = [m["id"] for m in self.store.messages(self.folder_id) if (m["from_addr"] or "").lower() == sender]
        self.move_to(hits, fid)
        self._do_refresh()

    def after_sync(self):
        self.apply_rules()
        self.notify_new_mail()
        self._do_refresh()

    def notify_new_mail(self):
        """A desktop alert for new unread mail in the Inboxes, as the original shows."""
        from gi.repository import Gio
        fresh = []
        for acc in self.store.accounts():
            inbox = self.store.folder_by_role(acc["id"], "inbox")
            if inbox is None:
                continue
            key = "notify-mark:%d" % inbox["id"]
            rows = self.store.messages(inbox["id"], order="id")
            top = max([r["id"] for r in rows] or [0])
            mark = self.store.get(key)
            self.store.put(key, top)
            if mark is None:
                continue
            fresh += [r for r in rows if r["id"] > mark and not r["seen"]]
        if fresh:
            self.last_new_mail = fresh
        if not fresh or not self.app.setting("new_mail_alert", True) or self.app.get_dbus_connection() is None:
            return
        n = Gio.Notification.new(fresh[0]["from_name"] or fresh[0]["from_addr"] if len(fresh) == 1 else
                                 "%d new messages" % len(fresh))
        n.set_body(fresh[0]["subject"] if len(fresh) == 1 else ", ".join(r["from_name"] or r["from_addr"] for r in fresh[:4]))
        try:
            self.app.send_notification("new-mail", n)
        except Exception:
            pass

    def apply_rules(self, all_inbox=False):
        """Blocked senders to Junk, ignored conversations to Deleted Items, then the rules, on new Inbox mail."""
        rules = [r for r in (self.store.get("rules", []) or []) if r.get("on", True)]
        blocked = self.store.get("blocked-senders", []) or []
        safe = set(self.store.get("safe-senders", []) or [])
        ignored = set(self.store.get("ignored-threads", []) or [])
        moved = 0
        for acc in self.store.accounts():
            inbox = self.store.folder_by_role(acc["id"], "inbox")
            if inbox is None:
                continue
            key = "rules-mark:%d" % inbox["id"]
            mark = self.store.get(key)
            rows = self.store.messages(inbox["id"], order="id")
            if not rows:
                continue
            top = max(r["id"] for r in rows)
            if mark is None and not all_inbox:
                self.store.put(key, top)
                continue
            new = rows if all_inbox else [r for r in rows if r["id"] > mark]
            self.store.put(key, top)
            junk = self.store.folder_by_role(acc["id"], "junk")
            trash = self.store.folder_by_role(acc["id"], "trash")
            for r in new:
                sender = (r["from_addr"] or "").lower()
                dom = "@" + sender.split("@")[-1] if "@" in sender else ""
                if sender not in safe and (sender in blocked or (dom and dom in blocked)) and junk:
                    self.store.move([r["id"]], junk["id"])
                    moved += 1
                    continue
                if r["thread"] in ignored and trash:
                    self.store.move([r["id"]], trash["id"])
                    moved += 1
                    continue
                for rule in rules:
                    if rule.get("from") and rule["from"] not in sender and rule["from"] not in (r["from_name"] or "").lower():
                        continue
                    if rule.get("subject") and rule["subject"] not in (r["subject"] or "").lower():
                        continue
                    if rule.get("to") and rule["to"] not in ((r["to_text"] or "") + " " + (r["cc_text"] or "")).lower():
                        continue
                    if rule.get("read"):
                        self.store.set_flag([r["id"]], "seen", True)
                    if rule.get("flag"):
                        self.store.set_flag([r["id"]], "flagged", True)
                    if rule.get("category"):
                        self.store.set_fields(r["id"], categories=rule["category"])
                    if rule.get("move") and self.store.folder(rule["move"]):
                        self.store.move([r["id"]], rule["move"])
                        moved += 1
                    break
        if moved:
            self.push_soon()
        return moved

    def act_rules(self):
        from .options import manage_rules
        manage_rules(self)

    # ---- find
    def act_search(self):
        self.search.grab_focus()

    def act_search_people(self):
        self.search.grab_focus()
        if not self.search.get_text():
            self.search.set_text("from:")
            self.search.set_position(-1)

    def on_search(self, entry):
        text = entry.get_text().strip()
        if self.module == "calendar":
            return self.search_calendar(text)
        if self.module == "people":
            v = self.ensure_people()
            v.filter = text
            v.refresh()
            return None
        if self.module == "tasks":
            v = self.ensure_tasks()
            if text:
                for row in v.model:
                    if text.lower() in row[1].lower():
                        v.select_keys([row[0]])
                        break
            return None
        if text.lower().startswith("from:"):
            text = text[5:].strip()
        if text == self.search_text:
            return
        self.search_text = text
        self.refresh_list(keep=False)
        self.update_title()

    def search_calendar(self, text):
        if len(text) < 2:
            return
        import datetime as dt
        from . import ical
        v = self.ensure_calendar()
        now = dt.datetime.now(ical.local_tz())
        hits = [i for i in v.load(now - dt.timedelta(days=365), now + dt.timedelta(days=730))
                if text.lower() in (i.event.summary + " " + i.event.location + " " + i.event.description).lower()]
        if hits:
            nxt = [i for i in hits if i.end >= now] or hits
            v.go(nxt[0].start.date())
            v.selected = next((i for i in v.instances if i.row["id"] == nxt[0].row["id"] and i.start == nxt[0].start), None)
            v.area.queue_draw()
        self.status.left.set_text("Found: %d" % len(hits))

    def clear_search(self):
        self.search.set_text("")
        self.search_text = ""
        self.refresh_list(keep=False)
        self.update_title()
        self.focus_document()

    def act_filter(self, kind):
        self.filter = kind
        if kind == "unread" and not self.filter_unread.get_active():
            self.filter_unread.set_active(True)
        elif kind != "unread" and self.filter_unread.get_active():
            self.filter_all.set_active(True)
        self.refresh_list(keep=False)

    # ---- send / receive
    def act_send_receive(self, aid=None):
        if self.app.syncer.offline:
            self.dialogs.info("Folio Post is working offline. Turn off Work Offline to send and receive.")
            return
        if not self.store.accounts():
            return self.run("add-account")
        self.app.send_receive([int(aid)] if aid else None, done=lambda *_: self.update_status())
        self.update_status()

    def act_update_folder(self):
        f = self.current_folder()
        if f and not self.app.syncer.offline:
            self.app.send_receive([f["account"]], [f["id"]], done=lambda *_: self.update_status())

    def act_send_all(self):
        def job():
            for acc in self.store.accounts():
                if acc["kind"] != "local" and self.store.outbox(acc["id"]):
                    try:
                        self.app.syncer.send_outbox(acc)
                    except Exception as e:
                        self.app.syncer.errors[acc["id"]] = "Couldn't send: %s" % e
            self.store.changed("outbox")
        if not self.app.syncer.offline:
            self.app.background(job, lambda *_: self.update_status())

    def act_show_progress(self):
        lines = []
        for acc in self.store.accounts():
            if acc["kind"] == "local":
                continue
            st = self.app.syncer.errors.get(acc["id"]) or self.app.syncer.status.get(acc["id"], "Not yet synchronized")
            n = len(self.store.outbox(acc["id"]))
            lines.append("%s: %s%s" % (acc["email"], st, ("  (%d in Outbox)" % n) if n else ""))
        self.dialogs.info("\n".join(lines) or "There are no accounts to synchronize.", "Send/Receive Progress")

    def act_cancel_all(self):
        self.app.cancel_all()
        self.update_status()

    def act_work_offline(self):
        self.app.set_offline(not self.app.syncer.offline)

    # ---- folders
    def act_new_folder(self, where=""):
        acc = None
        parent = None
        if where.startswith("account:"):
            acc = self.store.account(int(where.split(":")[1]))
        else:
            f = self.current_folder()
            if f:
                acc = self.store.account(f["account"])
                parent = f if f["role"] != "inbox" or acc["kind"] == "imap" else None
        if acc is None:
            return self.dialogs.info("Add an account first.")
        name = self.dialogs.ask_text("Create New Folder", "Name:")
        if not name:
            return
        delim = (parent or {}).get("delim") or "/"
        if parent and parent["role"] not in ("",) and parent["role"] != "inbox":
            parent = None
        path = (parent["path"] + delim + name) if parent else name
        if acc["kind"] == "imap":
            if self.app.syncer.offline:
                return self.dialogs.info("Folders on the server can be made only while online.")
            try:
                self.app.syncer.server_op(acc["id"], lambda c: c.create(path))
            except Exception as e:
                return self.dialogs.message("The server didn't create the folder: %s" % e)
        fid = self.store.ensure_folder(acc["id"], path, "", delim)
        self.refresh_folders()
        return fid

    def act_rename_folder(self):
        f = self.current_folder()
        if not f:
            return
        if f["role"]:
            return self.dialogs.info("“%s” is a special folder and can't be renamed." % self.folder_label(f))
        name = self.dialogs.ask_text("Rename Folder", "Name:", f["name"])
        if not name or name == f["name"]:
            return
        newpath = (f["parent"] + f["delim"] + name) if f["parent"] else name
        acc = self.store.account(f["account"])
        if acc["kind"] == "imap":
            try:
                self.app.syncer.server_op(acc["id"], lambda c: c.rename(f["path"], newpath))
            except Exception as e:
                return self.dialogs.message("The server didn't rename the folder: %s" % e)
        # subfolders follow
        for sub in self.store.folders(acc["id"]):
            if sub["path"].startswith(f["path"] + f["delim"]):
                p = newpath + sub["path"][len(f["path"]):]
                self.store.x("update folders set path=?, parent=? where id=?",
                             (p, f["delim"].join(p.split(f["delim"])[:-1]), sub["id"]))
        self.store.rename_folder(f["id"], newpath, name)
        self.refresh_folders()

    def act_delete_folder(self):
        if self.folder_id and self.folder_id < 0:
            return self.act_delete_search_folder()
        f = self.current_folder()
        if not f:
            return
        if f["role"]:
            return self.dialogs.info("“%s” is a special folder and can't be deleted." % self.folder_label(f))
        if not self.ask("Delete the folder “%s” and everything in it?" % f["name"]):
            return
        acc = self.store.account(f["account"])
        if acc["kind"] == "imap":
            try:
                self.app.syncer.server_op(acc["id"], lambda c: c.delete_folder(f["path"]))
            except Exception as e:
                return self.dialogs.message("The server didn't delete the folder: %s" % e)
        self.store.drop_folder(f["id"])
        inbox = self.store.folder_by_role(acc["id"], "inbox")
        self.folder_id = inbox["id"] if inbox else None
        self._do_refresh()

    def _folder_dest(self, title):
        """A parent for a folder: another folder of the same account, or the account's top."""
        f = self.current_folder()
        if not f or f["role"]:
            self.dialogs.info("Select one of your own folders first; special folders like the Inbox stay where they are.")
            return None, None
        dest = self.choose_folder(title)
        if dest is None:
            return f, None
        return f, self.store.folder(dest)

    def act_move_folder(self):
        f, dest = self._folder_dest("Move Folder")
        if not f or not dest:
            return None
        if dest["account"] != f["account"]:
            return self.dialogs.info("A folder moves within its own account. Use Copy Folder to copy it to another.")
        if dest["id"] == f["id"] or dest["path"].startswith(f["path"] + f["delim"]):
            return self.dialogs.info("A folder can't go inside itself.")
        d = f["delim"] or "/"
        newpath = dest["path"] + d + f["name"] if dest["role"] != "inbox" or True else f["name"]
        acc = self.store.account(f["account"])
        if acc["kind"] == "imap":
            try:
                self.app.syncer.server_op(acc["id"], lambda c: c.rename(f["path"], newpath))
            except Exception as e:
                return self.dialogs.message("The server didn't move the folder: %s" % e)
        for sub in self.store.folders(acc["id"]):
            if sub["path"] == f["path"] or sub["path"].startswith(f["path"] + d):
                p_ = newpath + sub["path"][len(f["path"]):]
                self.store.x("update folders set path=?, parent=? where id=?", (p_, d.join(p_.split(d)[:-1]), sub["id"]))
        self.store.changed("folders")
        self.refresh_folders()
        return newpath

    def act_copy_folder(self):
        f, dest = self._folder_dest("Copy Folder")
        if not f or not dest:
            return None
        acc = self.store.account(dest["account"])
        d = dest["delim"] or "/"
        path = dest["path"] + d + f["name"]
        have = {x["path"] for x in self.store.folders(acc["id"])}
        k = 2
        while path in have:
            path = "%s%s%s (%d)" % (dest["path"], d, f["name"], k)
            k += 1
        if acc["kind"] == "imap":
            try:
                self.app.syncer.server_op(acc["id"], lambda c: c.create(path))
            except Exception as e:
                return self.dialogs.message("The server didn't make the folder: %s" % e)
        nid = self.store.ensure_folder(acc["id"], path, "", d)
        self.copy_to([m["id"] for m in self.store.messages(f["id"])], nid)
        self.refresh_folders()
        return nid

    def act_new_search_folder(self, spec=None):
        """spec: 'kind' or 'kind:argument' (tests); otherwise the New Search Folder box."""
        if spec is None:
            d = Gtk.Dialog(title="New Search Folder", transient_for=self, modal=True)
            d.get_style_context().add_class("folio-dialog")
            box = d.get_content_area()
            box.set_border_width(12)
            box.set_spacing(4)
            box.pack_start(Gtk.Label(label="Select a Search Folder:", xalign=0), False, False, 0)
            first = None
            radios = {}
            for k, label in self.SEARCH_KINDS:
                r = Gtk.RadioButton.new_with_label_from_widget(first, label)
                first = first or r
                radios[k] = r
                box.pack_start(r, False, False, 0)
            arg = Gtk.Entry()
            arg.set_placeholder_text("people or words (for the last choices)")
            box.pack_start(arg, False, False, 6)
            d.add_button("Cancel", Gtk.ResponseType.CANCEL)
            d.add_button("OK", Gtk.ResponseType.OK)
            d.show_all()
            ok = d.run() == Gtk.ResponseType.OK
            kind = [k for k, r in radios.items() if r.get_active()][0]
            text = arg.get_text().strip()
            d.destroy()
            if not ok:
                return None
        else:
            kind, _, text = spec.partition(":")
        if kind in ("from", "words") and not text:
            return self.dialogs.info("Type the people or the words to look for.")
        name = dict(self.SEARCH_KINDS).get(kind, kind)
        if text:
            name = ("From " if kind == "from" else "Containing ") + text
        sf = self.store.get("search-folders", []) or []
        sf.append({"name": name, "kind": kind, "arg": text})
        self.store.put("search-folders", sf)
        self.refresh_folders()
        self.go_folder(-len(sf))
        return -len(sf)

    def act_delete_search_folder(self):
        if not self.folder_id or self.folder_id > 0:
            return
        sf = self.store.get("search-folders", []) or []
        i = -self.folder_id - 1
        if i < len(sf):
            del sf[i]
            self.store.put("search-folders", sf)
        self.select_first_inbox()
        self.refresh_folders()

    def act_mark_all_read(self):
        if not self.folder_id:
            return
        src = self.list_rows() if self.folder_id < 0 else self.store.messages(self.folder_id)
        ids = [m["id"] for m in src if not m["seen"]]
        self.mark_read(ids, True)

    def act_delete_all(self):
        if not self.folder_id:
            return
        ids = [m["id"] for m in self.store.messages(self.folder_id)]
        if not ids or not self.ask("Delete all %d items in this folder?" % len(ids)):
            return
        f = self.current_folder()
        trash = self._role_folder("trash")
        if trash and f["role"] != "trash":
            self.move_to(ids, trash["id"])
        else:
            for mid in ids:
                self.store.delete(mid)
        self.push_soon()
        self._do_refresh()

    def act_empty_trash(self):
        acc = self.current_account()
        if not acc:
            return
        t = self.store.folder_by_role(acc["id"], "trash")
        if not t:
            return
        ids = [m["id"] for m in self.store.messages(t["id"])]
        if ids and self.ask("Everything in Deleted Items will be permanently deleted. Continue?"):
            for mid in ids:
                self.store.delete(mid)
            self.push_soon()
            self._do_refresh()

    def act_folder_properties(self):
        f = self.current_folder()
        if not f:
            return
        total, unread = self.store.counts(f["id"])
        size = sum(m["size"] for m in self.store.messages(f["id"]))
        acc = self.store.account(f["account"])
        self.dialogs.info("%s\n\nAccount: %s\nLocation: %s\nItems: %d\nUnread: %d\nSize: %s" %
                          (self.folder_label(f), acc["email"], f["path"], total, unread, nice_size(size)),
                          "%s Properties" % self.folder_label(f))

    # ---- view
    def act_view_mode(self, mode):
        self.set_vset("mode", mode)
        if mode == "preview":
            self.set_vset("mode", "compact")
            self.set_vset("preview", 2)
        self.build_columns()
        self.refresh_list()

    def act_reset_view(self):
        for k in ("mode", "arrange", "reverse", "groups", "conversations", "preview"):
            self.view_settings.pop(k, None)
        self.set_vset("reading", "right")
        self.filter = "all"
        self.filter_all.set_active(True)
        self.build_columns()
        self.apply_layout()
        self.refresh_list()
        self.ribbon.update("conversations", "false")

    def act_toggle_conversations(self):
        on = self.conv_check.get_active() if getattr(self.ribbon, "current_control", None) is self.conv_check else not self.vset("conversations", False)
        self.set_vset("conversations", bool(on))
        self.ribbon.update("conversations", "true" if on else "false")
        self.refresh_list()

    def act_arrange(self, key):
        if self.vset("arrange", "date") == key:
            return self.act_reverse_sort()
        self.set_vset("arrange", key)
        self.view_settings.pop("reverse", None)
        self.refresh_list()

    def act_reverse_sort(self):
        key = self.vset("arrange", "date")
        cur = self.vset("reverse", key in ("date", "size", "importance", "flag", "attach"))
        self.set_vset("reverse", not cur)
        self.refresh_list()

    def act_toggle_groups(self):
        self.set_vset("groups", not self.vset("groups", True))
        self.refresh_list()

    def act_preview(self, n):
        self.set_vset("preview", int(n))
        self.build_columns()
        self.refresh_list()

    def act_folder_pane(self, how):
        self.set_vset("folder_pane", how)
        self.apply_layout()

    def act_reading_pane(self, where):
        self.set_vset("reading", where)
        self.apply_layout()

    def act_zoom(self):
        z = self.dialogs.ask_text("Zoom", "Zoom (percent):", str(int(self.reading.zoom * 100)))
        try:
            self.reading.set_zoom(max(50, min(500, int((z or "").strip().rstrip("%")))) / 100.0)
        except ValueError:
            pass

    def act_open_item(self):
        ids = self.selected_ids()
        if not ids:
            return None
        m = self.store.message(ids[0])
        if m and m["draft"]:
            return self.app.compose(draft=ids[0])
        from .msgwindow import MessageWindow
        w = MessageWindow(self, ids[0])
        w.present()
        self.mark_read([ids[0]])
        return w

    def act_close_items(self):
        from .msgwindow import MessageWindow
        for w in Gtk.Window.list_toplevels():
            if isinstance(w, MessageWindow):
                w.destroy()

    def act_go(self, where):
        if getattr(self, "_nav_quiet", False):
            return
        if where == "notes":
            self.switch_module("tasks")
            v = self.tasksview
            v.folders.select_row(v.folders.get_row_at_index(2))
            return
        if where in ("mail", "calendar", "people", "tasks"):
            self.switch_module(where)
            return
        self.not_available("not-available:" + where.capitalize())

    def act_go_folder(self):
        fid = self.choose_folder("Go to Folder")
        if fid:
            self.go_folder(fid)

    # ---- files
    def open_message_file(self, path):
        with open(path, "rb") as fh:
            raw = fh.read()
        if path.lower().endswith(".oft"):
            return self.act_choose_form(path)
        if path.lower().endswith(".msg"):
            from .importexport import msg_to_eml
            try:
                raw = msg_to_eml(path)
            except Exception as e:
                return self.dialogs.message("Folio Post couldn't open “%s”: %s" % (os.path.basename(path), e))
        from .msgwindow import MessageWindow
        w = MessageWindow(self, None, raw=raw, path=path)
        w.present()
        return w

    def act_open(self):
        dlg = Gtk.FileChooserDialog(title="Open Message", transient_for=self, action=Gtk.FileChooserAction.OPEN)
        dlg.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Open", Gtk.ResponseType.OK)
        flt = Gtk.FileFilter()
        flt.set_name("Messages (*.eml, *.msg, *.oft)")
        flt.add_pattern("*.eml")
        flt.add_pattern("*.msg")
        flt.add_pattern("*.oft")
        dlg.add_filter(flt)
        path = dlg.get_filename() if dlg.run() == Gtk.ResponseType.OK else None
        dlg.destroy()
        if path:
            self.open_message_file(path)

    def act_save_as(self, path=None):
        ids = self.need_selection()
        if not ids:
            return
        m = self.store.message(ids[0])
        base = re.sub(r"[^\w .,-]+", "", m["subject"] or "message")[:80].strip() or "message"
        if path is None:
            dlg = Gtk.FileChooserDialog(title="Save As", transient_for=self, action=Gtk.FileChooserAction.SAVE)
            dlg.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Save", Gtk.ResponseType.OK)
            dlg.set_do_overwrite_confirmation(True)
            dlg.set_current_name(base + ".eml")
            for name, pat in (("Message (*.eml)", "*.eml"), ("Text Only (*.txt)", "*.txt"), ("HTML (*.html)", "*.html")):
                f = Gtk.FileFilter()
                f.set_name(name)
                f.add_pattern(pat)
                dlg.add_filter(f)
            path = dlg.get_filename() if dlg.run() == Gtk.ResponseType.OK else None
            dlg.destroy()
        if not path:
            return
        save_message(self.store.raw(ids[0]), path)
        return path

    def act_save_attachments(self):
        if self.reading.msg is not None:
            self.reading.save_all()

    def act_print(self):
        ids = self.need_selection()
        if not ids:
            return
        from .printing import print_message
        print_message(self, self.store.raw(ids[0]))

    def act_copy(self):
        t = self.reading.selected_text()
        if not t and self.reading.msg is not None:
            t = self.reading.view.text()
        Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(t or "", -1)

    # ---- accounts and options
    def act_add_account(self):
        from .accounts import add_account
        return add_account(self)

    def act_account_settings(self, aid=None):
        from .accounts import account_settings
        return account_settings(self, int(aid) if aid else None)

    def act_options(self, page=""):
        from .options import options_dialog
        options_dialog(self, page)

    def act_import_certificate(self, path=None, password=None):
        """Your S/MIME certificate and key, for the current account."""
        from . import smime
        acc = self.current_account()
        if acc is None:
            return self.dialogs.info("Add an account first.")
        if path is None:
            dlg = Gtk.FileChooserDialog(title="Import S/MIME Certificate", transient_for=self, action=Gtk.FileChooserAction.OPEN)
            dlg.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Open", Gtk.ResponseType.OK)
            f = Gtk.FileFilter()
            f.set_name("Certificates (*.p12, *.pfx)")
            f.add_pattern("*.p12")
            f.add_pattern("*.pfx")
            dlg.add_filter(f)
            path = dlg.get_filename() if dlg.run() == Gtk.ResponseType.OK else None
            dlg.destroy()
            if not path:
                return None
        if password is None:
            password = self.dialogs.ask_password("Import S/MIME Certificate", "The file's password:")
            if password is None:
                return None
        try:
            cert = smime.import_p12(path, password, acc["email"])
        except Exception as e:
            return self.dialogs.message("The certificate couldn't be imported: %s" % e)
        self.dialogs.info("Your S/MIME certificate for %s is ready. Encrypt and Sign in a message now use it." % acc["email"])
        return cert

    def act_signatures(self):
        from .options import signatures_dialog
        signatures_dialog(self)

    def act_import_export(self, choice=None, path=None):
        from .importexport import import_export
        return import_export(self, choice, path)

    def act_exit(self):
        self.app.quit()

    def act_close(self):
        self.close()

    # ---- help
    def act_help(self):
        from .helpwin import show_help
        show_help(self)

    def act_shortcuts(self):
        from .helpwin import show_shortcuts
        show_shortcuts(self)

    def act_about(self):
        d = Gtk.AboutDialog(transient_for=self, modal=True)
        d.set_program_name(APP_NAME)
        d.set_version(VERSION)
        d.set_logo_icon_name("folio-post")
        d.set_comments("Mail for your own accounts. No cloud of its own, no tracking.")
        d.set_license_type(Gtk.License.GPL_3_0)
        d.run()
        d.destroy()

    # ================================================================ keys
    SHORTCUTS = {
        ("ctrl", "n"): "new-email", ("ctrl", "r"): "reply", ("ctrl+shift", "r"): "reply-all", ("ctrl", "f"): "forward",
        ("ctrl+alt", "f"): "forward-attachment", ("ctrl", "d"): "delete", ("ctrl", "q"): "mark-read",
        ("ctrl", "u"): "mark-unread", ("ctrl+shift", "v"): "move-other", ("ctrl", "e"): "search", ("", "F3"): "search",
        ("", "F9"): "send-receive", ("shift", "F9"): "update-folder", ("ctrl", "z"): "undo", ("ctrl", "p"): "print",
        ("ctrl", "s"): "save-as", ("ctrl", "o"): "open-item", ("ctrl+shift", "e"): "new-folder", ("ctrl", "y"): "go-folder",
        ("ctrl", "1"): "go:mail", ("ctrl", "2"): "go:calendar", ("ctrl", "3"): "go:people", ("ctrl", "4"): "go:tasks",
        ("ctrl", "5"): "go:notes", ("ctrl+shift", "k"): "new-task", ("ctrl+shift", "n"): "new-note",
        ("ctrl+shift", "c"): "new-contact", ("ctrl+shift", "a"): "new-appointment", ("ctrl+shift", "q"): "new-meeting", ("", "Insert"): "flag:toggle", ("ctrl+alt", "j"): "not-junk", ("", "F1"): "help",
        ("ctrl+shift", "b"): "address-book", ("ctrl", "c"): "copy", ("ctrl+shift", "m"): "new-email",
        ("shift", "Delete"): "delete-permanently",
    }

    def on_key(self, w, ev):
        state = ev.state & (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK | Gdk.ModifierType.MOD1_MASK)
        mods = "+".join(n for n, m in (("ctrl", Gdk.ModifierType.CONTROL_MASK), ("shift", Gdk.ModifierType.SHIFT_MASK),
                                       ("alt", Gdk.ModifierType.MOD1_MASK)) if state & m)
        name = Gdk.keyval_name(ev.keyval) or ""
        key = name.lower() if len(name) == 1 else name
        self._alt_alone = ev.keyval in (Gdk.KEY_Alt_L, Gdk.KEY_Alt_R) and not mods
        if self.keytips.active:
            return self.keytips.key(ev)
        if self.backstage.get_visible():
            if ev.keyval == Gdk.KEY_Escape:
                self.backstage.close()
                return True
            return False
        if ev.keyval == Gdk.KEY_F10 and not mods:
            self.keytips.start()
            return True
        focus = self.get_focus()
        typing = isinstance(focus, (Gtk.Entry, Gtk.TextView)) and not (isinstance(focus, Gtk.TextView) and not focus.get_editable())
        if typing and focus is self.search and ev.keyval in (Gdk.KEY_Down, Gdk.KEY_Return):
            self.focus_document()
            self.select_index(0)
            return True
        if typing and (mods in ("", "shift") or (mods == "ctrl" and key in ("c", "v", "x", "a", "z"))):
            return False
        if self.module == "tasks":
            tcmd = {("ctrl", "n"): "new-task", ("ctrl+shift", "n"): "new-note", ("ctrl", "o"): "open-task",
                    ("ctrl", "d"): "delete-task", ("", "Delete"): "delete-task", ("", "Insert"): "mark-complete"}.get((mods, key))
            if tcmd and not typing:
                self.run(tcmd)
                return True
            if (mods, key) in (("", "BackSpace"), ("ctrl", "r"), ("ctrl+shift", "r"), ("ctrl", "f")):
                return False
        if self.module == "people":
            pcmd = {("ctrl", "n"): "new-contact", ("ctrl+shift", "l"): "new-contact-group", ("ctrl", "o"): "open-contact",
                    ("ctrl", "d"): "delete-contact", ("", "Delete"): "delete-contact", ("ctrl", "r"): "contact-email",
                    ("ctrl", "f"): "forward-contact"}.get((mods, key))
            if pcmd and not typing:
                self.run(pcmd)
                return True
            if (mods, key) in (("", "BackSpace"), ("", "Insert"), ("ctrl+shift", "r")):
                return False
        if self.module == "calendar":
            ccmd = {("ctrl+alt", "1"): "cal-view:day", ("ctrl+alt", "2"): "cal-view:workweek", ("ctrl+alt", "3"): "cal-view:week",
                    ("ctrl+alt", "4"): "cal-view:month", ("ctrl", "g"): "cal-go-to", ("ctrl+shift", "q"): "new-meeting",
                    ("ctrl", "n"): "new-appointment", ("ctrl", "o"): "open-event", ("ctrl", "d"): "delete-event",
                    ("ctrl", "t"): "cal-today", ("shift", "F9"): "update-calendars"}.get((mods, key))
            if ccmd:
                self.run(ccmd)
                return True
            if focus is self.calview.area and self.calview.key(ev):
                return True
            if (mods, key) in (("ctrl", "r"), ("ctrl+shift", "r"), ("ctrl", "f"), ("", "Delete"), ("", "BackSpace"), ("", "Insert")):
                return False
        cmd = self.SHORTCUTS.get((mods, key))
        if cmd is None and mods == "ctrl" and key in ("period", "comma"):
            ids = self.selected_ids()
            rows = [r[0] for r in self.iter_rows()]
            i = rows.index(ids[0]) if ids and ids[0] in rows else -1
            self.select_index(i + (1 if key == "period" else -1))
            return True
        if cmd is None and not mods and ev.keyval == Gdk.KEY_Delete and not typing:
            cmd = "delete"
        if cmd is None and not mods and ev.keyval == Gdk.KEY_BackSpace and not typing:
            cmd = "archive"
        if cmd is None and not mods and ev.keyval == Gdk.KEY_space and focus is self.list_view:
            adj = self.reading.scroller.get_vadjustment()
            if adj.get_value() + adj.get_page_size() < adj.get_upper() - 1:
                adj.set_value(adj.get_value() + adj.get_page_size() * 0.9)
            else:
                ids = self.selected_ids()
                rows = [r[0] for r in self.iter_rows()]
                i = rows.index(ids[0]) if ids and ids[0] in rows else -1
                self.select_index(i + 1)
            return True
        if cmd is None and ev.keyval == Gdk.KEY_Escape and self.search_text:
            self.clear_search()
            return True
        if cmd:
            self.run(cmd)
            return True
        return False

    def on_key_release(self, w, ev):
        if ev.keyval in (Gdk.KEY_Alt_L, Gdk.KEY_Alt_R) and self._alt_alone:
            self._alt_alone = False
            if not self.keytips.active and not self.backstage.get_visible():
                self.keytips.start()
            return True
        return False

    # ================================================================ closing
    def on_delete(self, *a):
        self.mark_previous_read()
        self.store.listeners.remove(self._store_changed) if self._store_changed in self.store.listeners else None
        self.app.window_closed(self)
        return False

    def _remember_geometry(self, w, ev):
        if not self.is_maximized():
            self.app.settings["window"] = {"w": ev.width, "h": ev.height, "max": False}
        else:
            self.app.settings.setdefault("window", {})["max"] = True
        return False


def _norm(text):
    return re.sub(r"\s+", " ", text or "").strip()


def save_message(raw, path):
    low = path.lower()
    if low.endswith(".txt"):
        msg = mime.parse(raw)
        head = "\n".join("%s: %s" % kv for kv in mime.quote_header(msg))
        with open(path, "w") as fh:
            fh.write(head + "\n\n" + mime.text_of(msg))
    elif low.endswith((".html", ".htm")):
        import html
        msg = mime.parse(raw)
        h = mime.body_part(msg, "html")
        head = "".join("<b>%s:</b> %s<br>" % (k, html.escape(v)) for k, v in mime.quote_header(msg))
        body = h if h is not None else "<pre>%s</pre>" % html.escape(mime.text_of(msg))
        with open(path, "w") as fh:
            fh.write("<html><head><meta charset='utf-8'></head><body>%s<hr>%s</body></html>" % (head, body))
    else:
        with open(path, "wb") as fh:
            fh.write(raw)
