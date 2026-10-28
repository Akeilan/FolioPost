"""The File view (backstage): Home, New, Open, Info, Save As, Print,
Export, Close, Options."""
import datetime
import os
import shutil
import subprocess
import tempfile

from gi.repository import GdkPixbuf, GLib, Gtk, Pango

from . import APP_NAME, SHARE, docapi, icons

NAV = [("back", None), ("home", "Home"), ("new", "New"), ("open", "Open"), None,
       ("info", "Info"), ("save", "Save"), ("saveas", "Save As"), ("print", "Print"),
       ("export", "Export"), ("close", "Close"), "spacer", ("options", "Options")]

EXPORT_TYPES = [
    ("docx", "Document", "Uses the standard document format"),
    ("doc", "Document 97-2003", "Uses the older document format"),
    ("odt", "OpenDocument Text", "Uses the OpenDocument format"),
    ("dotx", "Template", "Starting point for new documents"),
    ("txt", "Plain Text", "Contains only the text in your document"),
    ("rtf", "Rich Text Format", "Preserves text formatting information"),
    ("html", "Single File Web Page", "Web page stored as a single file"),
    ("epub", "EPUB", "Electronic book format"),
]


def _when(ts):
    d = datetime.datetime.fromtimestamp(ts)
    now = datetime.datetime.now()
    if d.date() == now.date():
        return d.strftime("%-I:%M %p")
    if (now.date() - d.date()).days == 1:
        return "Yesterday at " + d.strftime("%-I:%M %p")
    if (now.date() - d.date()).days < 7:
        return d.strftime("%A")
    return d.strftime("%-m/%-d/%Y")


def _heading(text, cls="folio-bs-title"):
    lab = Gtk.Label(label=text, xalign=0)
    lab.get_style_context().add_class(cls)
    return lab


class Backstage(Gtk.Box):
    def __init__(self, win):
        Gtk.Box.__init__(self)
        self.win = win
        self.get_style_context().add_class("folio-backstage")
        nav = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        nav.get_style_context().add_class("folio-bs-nav")
        nav.set_size_request(180, -1)
        self.nav_buttons = {}
        for entry in NAV:
            if entry is None:
                s = Gtk.Separator()
                s.get_style_context().add_class("folio-bs-sep")
                nav.pack_start(s, False, False, 6)
                continue
            if entry == "spacer":
                nav.pack_start(Gtk.Box(), True, True, 0)
                continue
            key, label = entry
            b = Gtk.Button()
            b.set_relief(Gtk.ReliefStyle.NONE)
            b.get_style_context().add_class("folio-bs-navbtn")
            if key == "back":
                b.add(Gtk.Image.new_from_icon_name("go-previous-symbolic", Gtk.IconSize.LARGE_TOOLBAR))
                b.set_tooltip_text("Back (Esc)")
                b.set_halign(Gtk.Align.START)
                b.get_style_context().add_class("back")
            else:
                lab = Gtk.Label(label=label, xalign=0)
                b.add(lab)
            b.connect("clicked", lambda _b, k=key: self.nav(k))
            nav.pack_start(b, False, False, 0)
            self.nav_buttons[key] = b
        self.pack_start(nav, False, False, 0)
        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.stack.set_transition_duration(80)
        self.stack.get_style_context().add_class("folio-bs-body")
        self.pack_start(self.stack, True, True, 0)
        self.pages = {}
        self.preview_pdf = None

    # ------------------------------------------------------------ navigation
    current = None

    def open(self, page="home"):
        self.win.ribbon.set_sensitive(False)
        self.show_all()
        self.nav(page)

    def close(self):
        self.hide()
        self.win.ribbon.set_sensitive(True)
        self.win.focus_document()
        self._cleanup_preview()

    def nav(self, key):
        if key == "back":
            self.close()
            return
        if key == "save":
            self.close()
            self.win.save()
            return
        if key == "close":
            self.close()
            self.win.close_document()
            return
        if key == "options":
            self.win.dialogs.options()
            return
        self.current = key
        for k, b in self.nav_buttons.items():
            ctx = b.get_style_context()
            if k == key:
                ctx.add_class("active")
            else:
                ctx.remove_class("active")
        builder = getattr(self, "page_" + key)
        old = self.stack.get_child_by_name(key)
        if old is not None:
            self.stack.remove(old)
        w = builder()
        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        if key == "print":
            sw = w
        else:
            sw.add(w)
        sw.show_all()
        self.stack.add_named(sw, key)
        self.stack.set_visible_child_name(key)

    # ------------------------------------------------------------ helpers
    def _page(self, title):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_border_width(36)
        box.pack_start(_heading(title), False, False, 0)
        return box

    def _templates(self):
        out = [("blank", "Blank document", None)]
        dirs = [os.path.join(SHARE, "templates", "gallery"),
                os.path.join(os.path.dirname(__file__), "..", "..", "share", "templates",
                             "gallery"),
                os.path.join(self.win.app.config_dir, "templates")]
        seen = set()
        for d in dirs:
            if not os.path.isdir(d):
                continue
            for f in sorted(os.listdir(d)):
                if f.endswith((".ott", ".dotx", ".dot")) and f not in seen:
                    seen.add(f)
                    name = os.path.splitext(f)[0].replace("_", " ")
                    out.append(("file", name, os.path.join(d, f)))
        return out

    def _template_tile(self, kind, name, path):
        b = Gtk.Button()
        b.set_relief(Gtk.ReliefStyle.NONE)
        b.get_style_context().add_class("folio-bs-tile")
        v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        thumb = Gtk.Box()
        thumb.set_size_request(150, 194)
        thumb.get_style_context().add_class("folio-bs-thumb")
        img_path = None
        if path:
            png = os.path.splitext(path)[0] + ".png"
            if os.path.exists(png):
                img_path = png
        if img_path:
            try:
                pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(img_path, 150, 194, True)
                thumb.pack_start(Gtk.Image.new_from_pixbuf(pb), True, True, 0)
            except Exception:
                pass
        v.pack_start(thumb, False, False, 0)
        lab = Gtk.Label(label=name)
        lab.set_ellipsize(Pango.EllipsizeMode.END)
        lab.set_max_width_chars(18)
        v.pack_start(lab, False, False, 0)
        b.add(v)

        def go(*_):
            self.close()
            if kind == "blank":
                self.win.app.new_window()
            else:
                self.win.app.new_window(template=path)
        b.connect("clicked", go)
        return b

    def _recent_list(self, limit=50, filter_text=""):
        lb = Gtk.ListBox()
        lb.get_style_context().add_class("folio-bs-list")
        lb.set_selection_mode(Gtk.SelectionMode.NONE)
        pins = self.win.app.pinned()
        files = pins + [f for f in self.win.app.recent() if f not in pins]
        if filter_text:
            files = [f for f in files if filter_text.lower() in os.path.basename(f).lower()]
        if not files:
            lab = Gtk.Label(label="You haven't opened any files recently. Click Browse to "
                                  "look for a file." if not filter_text else
                            "No recent files match your search.", xalign=0)
            lab.get_style_context().add_class("dim-label")
            lab.set_margin_top(10)
            lb.add(lab)
        for p in files[:limit]:
            row = Gtk.ListBoxRow()
            row.path = p
            h = Gtk.Box(spacing=12)
            h.set_border_width(6)
            h.pack_start(icons.image("res/sx03251", 32) if False else
                         icons.image("cmd/lc_newdoc", 32), False, False, 0)
            v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            n = Gtk.Label(label=os.path.splitext(os.path.basename(p))[0], xalign=0)
            n.get_style_context().add_class("folio-bs-filename")
            d = Gtk.Label(label=os.path.dirname(p).replace(os.path.expanduser("~"), "~"), xalign=0)
            d.get_style_context().add_class("dim-label")
            d.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
            v.pack_start(n, False, False, 0)
            v.pack_start(d, False, False, 0)
            h.pack_start(v, True, True, 0)
            pin = Gtk.Button()
            pin.set_relief(Gtk.ReliefStyle.NONE)
            pin.get_style_context().add_class("folio-pin")
            pinned = p in pins
            if pinned:
                pin.get_style_context().add_class("pinned")
            pin.add(icons.image("pinned" if pinned else "pin", 16))
            pin.set_tooltip_text("Unpin this item from the list" if pinned else
                                 "Pin this item to the list")
            pin.connect("clicked", lambda _b, p=p: (self.win.app.toggle_pin(p),
                                                    self.nav(self.current or "home")))
            try:
                when = Gtk.Label(label=_when(os.path.getmtime(p)))
                when.get_style_context().add_class("dim-label")
                h.pack_end(when, False, False, 0)
            except OSError:
                pass
            h.pack_end(pin, False, False, 0)
            row.add(h)
            if pinned and (p == pins[0]) and not filter_text:
                hdr = Gtk.Label(xalign=0)
                hdr.set_markup("<b>Pinned</b>")
                hdr.set_margin_top(4)
                hrow = Gtk.ListBoxRow()
                hrow.set_activatable(False)
                hrow.add(hdr)
                lb.add(hrow)
            if not pinned and pins and (files.index(p) == len(pins)) and not filter_text:
                hdr = Gtk.Label(xalign=0)
                hdr.set_markup("<b>Recent</b>")
                hdr.set_margin_top(8)
                hrow = Gtk.ListBoxRow()
                hrow.set_activatable(False)
                hrow.add(hdr)
                lb.add(hrow)
            lb.add(row)
        lb.connect("row-activated", lambda _l, row: self._open_path(getattr(row, "path", None)))
        lb.connect("button-press-event", self._recent_menu)
        return lb

    def _recent_menu(self, lb, ev):
        if ev.button != 3:
            return False
        row = lb.get_row_at_y(int(ev.y))
        if row is None or not hasattr(row, "path"):
            return False
        from .ribbon import menu_popover
        from .panes import Gdk_rect
        p = row.path
        pop = menu_popover(lb, [
            ("Open", lambda: self._open_path(p)),
            ("Open Containing Folder", lambda: subprocess.Popen(["xdg-open", os.path.dirname(p)])),
            ("Unpin from List" if p in self.win.app.pinned() else "Pin to List",
             lambda: (self.win.app.toggle_pin(p), self.nav(self.current or "home"))),
            ("Copy Path to Clipboard", lambda: Gtk.Clipboard.get(
                __import__("gi.repository.Gdk", fromlist=["Gdk"]).SELECTION_CLIPBOARD).set_text(p, -1)),
            None,
            ("Remove from List", lambda: (self.win.app.remove_recent(p), self.nav("open")))])
        pop.set_pointing_to(Gdk_rect(ev))
        pop.popup()
        return True

    def _open_path(self, p):
        if not p:
            return
        self.close()
        self.win.app.open_path(p, self.win)

    # ------------------------------------------------------------ Home
    def page_home(self):
        h = datetime.datetime.now().hour
        greet = "Good morning" if h < 12 else ("Good afternoon" if h < 18 else "Good evening")
        box = self._page(greet)
        strip = Gtk.Box(spacing=14)
        for kind, name, path in self._templates()[:6]:
            strip.pack_start(self._template_tile(kind, name, path), False, False, 0)
        box.pack_start(strip, False, False, 0)
        more = Gtk.LinkButton(label="More templates →")
        more.set_halign(Gtk.Align.END)
        more.connect("activate-link", lambda *_: (self.nav("new"), True)[1])
        box.pack_start(more, False, False, 0)
        search = Gtk.SearchEntry()
        search.set_placeholder_text("Search")
        search.set_size_request(400, -1)
        search.set_halign(Gtk.Align.START)
        box.pack_start(search, False, False, 0)
        tabs = Gtk.Box(spacing=18)
        r = Gtk.Label()
        r.set_markup("<b>Recent</b>")
        tabs.pack_start(r, False, False, 0)
        box.pack_start(tabs, False, False, 0)
        holder = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        holder.pack_start(self._recent_list(12), False, False, 0)
        box.pack_start(holder, False, False, 0)

        def filt(e):
            for c in holder.get_children():
                holder.remove(c)
            holder.pack_start(self._recent_list(12, e.get_text()), False, False, 0)
            holder.show_all()
        search.connect("search-changed", filt)
        mb = Gtk.LinkButton(label="More documents →")
        mb.set_halign(Gtk.Align.END)
        mb.connect("activate-link", lambda *_: (self.nav("open"), True)[1])
        box.pack_start(mb, False, False, 0)
        return box

    # ------------------------------------------------------------ New
    def page_new(self):
        box = self._page("New")
        flow = Gtk.FlowBox()
        flow.set_selection_mode(Gtk.SelectionMode.NONE)
        flow.set_max_children_per_line(6)
        flow.set_column_spacing(14)
        flow.set_row_spacing(14)
        for kind, name, path in self._templates():
            flow.add(self._template_tile(kind, name, path))
        box.pack_start(flow, False, False, 0)
        return box

    # ------------------------------------------------------------ Open
    def page_open(self):
        box = self._page("Open")
        h = Gtk.Box(spacing=30)
        places = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        places.set_size_request(240, -1)

        def place(label, icon, cb):
            b = Gtk.Button()
            b.set_relief(Gtk.ReliefStyle.NONE)
            b.get_style_context().add_class("folio-bs-place")
            hb = Gtk.Box(spacing=10)
            hb.pack_start(icons.image(icon, 32), False, False, 0)
            hb.pack_start(Gtk.Label(label=label, xalign=0), True, True, 0)
            b.add(hb)
            b.connect("clicked", lambda *_: cb())
            places.pack_start(b, False, False, 0)
        place("Recent", "cmd/lc_recentfilelist", lambda: None)
        place("This PC", "cmd/lc_open", self._browse)
        place("Browse", "cmd/lc_openfromwriter" if False else "cmd/lc_open", self._browse)
        h.pack_start(places, False, False, 0)
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        search = Gtk.SearchEntry()
        search.set_placeholder_text("Search")
        right.pack_start(search, False, False, 0)
        lab = Gtk.Label(xalign=0)
        lab.set_markup("<b>Documents</b>")
        right.pack_start(lab, False, False, 0)
        holder = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        holder.pack_start(self._recent_list(50), False, False, 0)
        right.pack_start(holder, True, True, 0)

        def filt(e):
            for c in holder.get_children():
                holder.remove(c)
            holder.pack_start(self._recent_list(50, e.get_text()), False, False, 0)
            holder.show_all()
        search.connect("search-changed", filt)
        h.pack_start(right, True, True, 0)
        box.pack_start(h, True, True, 0)
        return box

    def _browse(self):
        path = self.win.dialogs.open_file()
        if path:
            self._open_path(path)

    # ------------------------------------------------------------ Info
    def page_info(self):
        box = self._page("Info")
        eng = self.win.engine
        m = self.win.docmodel
        name = self.win.doc_name()
        t = Gtk.Label(label=name, xalign=0)
        t.get_style_context().add_class("folio-bs-docname")
        box.pack_start(t, False, False, 0)
        if eng.path and not eng.is_new:
            p = Gtk.Label(label=os.path.dirname(eng.path).replace(os.path.expanduser("~"), "~")
                          + " » " + os.path.basename(eng.path), xalign=0)
            p.get_style_context().add_class("dim-label")
            box.pack_start(p, False, False, 0)
            ob = Gtk.Box(spacing=8)
            loc = Gtk.Button(label="Open File Location")
            loc.connect("clicked", lambda *_: subprocess.Popen(["xdg-open", os.path.dirname(eng.path)]))
            ob.pack_start(loc, False, False, 0)
            box.pack_start(ob, False, False, 0)
        cols = Gtk.Box(spacing=40)
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)

        def card(icon, title, text, buttons):
            c = Gtk.Box(spacing=16)
            c.get_style_context().add_class("folio-bs-card")
            v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            for label, cb in buttons:
                b = Gtk.Button()
                bb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
                bb.pack_start(icons.image(icon, 32), False, False, 0)
                bb.pack_start(Gtk.Label(label=label), False, False, 0)
                b.add(bb)
                b.set_size_request(100, 90)
                b.connect("clicked", lambda _b, cb=cb: cb())
                v.pack_start(b, False, False, 0)
            c.pack_start(v, False, False, 0)
            tv = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            tl = Gtk.Label(label=title, xalign=0)
            tl.get_style_context().add_class("folio-bs-cardtitle")
            tv.pack_start(tl, False, False, 0)
            tx = Gtk.Label(label=text, xalign=0)
            tx.set_line_wrap(True)
            tx.set_max_width_chars(48)
            tv.pack_start(tx, False, False, 0)
            c.pack_start(tv, True, True, 0)
            left.pack_start(c, False, False, 0)
            left.pack_start(Gtk.Separator(), False, False, 0)
        ro = bool(m is not None and self.win.read_only)
        from . import docprotect, review
        final = m is not None and docprotect.is_final(m)
        restricted = m is not None and review.restriction(m).get("on")
        ptext = "Control what types of changes people can make to this document."
        if final:
            ptext = "This document has been marked as final to discourage editing."
        elif restricted:
            ptext = "Some editing restrictions are in place for this document."
        elif self.win.read_only:
            ptext = "This document is open read-only."
        card("cmd/lc_protect", "Protect Document", ptext,
             [("Protect\nDocument", self._protect_menu)])
        card("cmd/lc_spellingandgrammardialog", "Inspect Document",
             "Before publishing this file, be aware that it contains:\n"
             "• Document properties and author's name",
             [("Check for\nIssues", lambda: self._inspect())])
        vers = docprotect.versions(self.win.app, eng.path) if eng.path and not eng.is_new \
            else []
        card("cmd/lc_versiondialog" if icons.exists("cmd/lc_versiondialog") else "cmd/lc_open",
             "Manage Document",
             "There are no previous versions of this file." if not vers else
             "Autosaved versions of this document:",
             [("Manage\nDocument", self._manage_menu)])
        if vers:
            vb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
            for ts, vp in vers[:6]:
                lnk = Gtk.Button(label=docprotect.version_label(ts))
                lnk.set_relief(Gtk.ReliefStyle.NONE)
                lnk.get_child().set_xalign(0)
                lnk.connect("clicked", lambda _b, ts=ts, vp=vp: (
                    self.close(), docprotect.open_version(self.win, ts, vp)))
                vb.pack_start(lnk, False, False, 0)
            vb.set_margin_start(116)
            left.pack_start(vb, False, False, 0)
        cols.pack_start(left, True, True, 0)
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        right.set_size_request(320, -1)
        pt = Gtk.Label(label="Properties", xalign=0)
        pt.get_style_context().add_class("folio-bs-cardtitle")
        right.pack_start(pt, False, False, 0)
        props = docapi.doc_properties(m) if m is not None else {}
        stats = docapi.statistics(m) if m is not None else {}
        g = Gtk.Grid(column_spacing=24, row_spacing=6)
        rows = []
        if eng.path and not eng.is_new and os.path.exists(eng.path):
            size = os.path.getsize(eng.path)
            rows.append(("Size", "%dKB" % max(1, size // 1024)))
        rows += [("Pages", str(stats.get("PageCount", 1))),
                 ("Words", "{:,}".format(stats.get("WordCount", 0))),
                 ("Total Editing Time", "%d Minutes" % props.get("editing_minutes", 0))]
        editable = [("Title", "title"), ("Tags", "keywords"), ("Comments", "comments")]
        r = 0
        for k, v in rows:
            g.attach(Gtk.Label(label=k, xalign=0), 0, r, 1, 1)
            g.attach(Gtk.Label(label=v, xalign=0), 1, r, 1, 1)
            r += 1
        for label, key in editable:
            g.attach(Gtk.Label(label=label, xalign=0), 0, r, 1, 1)
            e = Gtk.Entry(text=props.get(key) or "")
            e.set_placeholder_text("Add a " + label[:-1].lower() if label.endswith("s")
                                   else "Add a " + label.lower())
            e.get_style_context().add_class("folio-bs-propentry")
            e.connect("changed", lambda w, k=key: m is not None and
                      docapi.set_doc_property(m, k, w.get_text()))
            g.attach(e, 1, r, 1, 1)
            r += 1
        right.pack_start(g, False, False, 0)
        right.pack_start(_heading("Related Dates", "folio-bs-cardtitle"), False, False, 8)
        g2 = Gtk.Grid(column_spacing=24, row_spacing=6)

        def fmt(d):
            return d.strftime("%-m/%-d/%Y %-I:%M %p") if d else "Never"
        for i, (k, v) in enumerate((("Last Modified", fmt(props.get("modified"))),
                                    ("Created", fmt(props.get("created"))),
                                    ("Last Printed", fmt(props.get("printed"))))):
            g2.attach(Gtk.Label(label=k, xalign=0), 0, i, 1, 1)
            g2.attach(Gtk.Label(label=v, xalign=0), 1, i, 1, 1)
        right.pack_start(g2, False, False, 0)
        right.pack_start(_heading("Related People", "folio-bs-cardtitle"), False, False, 8)
        g3 = Gtk.Grid(column_spacing=24, row_spacing=6)
        g3.attach(Gtk.Label(label="Author", xalign=0), 0, 0, 1, 1)
        g3.attach(Gtk.Label(label=props.get("author") or self.win.app.user_name(), xalign=0), 1, 0, 1, 1)
        g3.attach(Gtk.Label(label="Last Modified By", xalign=0), 0, 1, 1, 1)
        g3.attach(Gtk.Label(label=props.get("modified_by") or "Not saved yet", xalign=0), 1, 1, 1, 1)
        right.pack_start(g3, False, False, 0)
        cols.pack_start(right, False, False, 0)
        box.pack_start(cols, True, True, 0)
        return box

    def _protect_menu(self):
        from .ribbon import menu_popover
        from . import docprotect
        m = self.win.docmodel
        final = m is not None and docprotect.is_final(m)

        def restrict():
            from .review import RestrictPane
            self.close()
            self.win.show_pane(RestrictPane)
        pop = menu_popover(self.nav_buttons["info"], [
            ("Always Open Read-Only", lambda: self.win.toggle_read_only()),
            ("Encrypt with Password", lambda: self.win.encrypt_dialog()),
            ("Restrict Editing", restrict),
            ("Unmark as Final" if final else "Mark as Final",
             lambda: (self.close(), docprotect.mark_final(self.win, not final)))])
        pop.popup()

    def _manage_menu(self):
        from .ribbon import menu_popover
        from . import docprotect
        pop = menu_popover(self.nav_buttons["info"], [
            ("Recover Unsaved Documents", lambda: (self.close(),
                                                   docprotect.recover_unsaved(self.win)))])
        pop.popup()

    def _inspect(self):
        from .ribbon import menu_popover
        from . import inspector

        def inspect_doc():
            self.close()
            inspector.dialog(self.win)

        def access():
            self.close()
            self.win.run("check-accessibility")
        def compat():
            self.close()
            from . import compat as C
            C.dialog(self.win)
        pop = menu_popover(self.nav_buttons["info"], [
            ("Inspect Document", inspect_doc), ("Check Accessibility", access),
            ("Check Compatibility", compat)])
        pop.popup()

    # ------------------------------------------------------------ Save As
    def page_saveas(self):
        box = self._page("Save As")
        h = Gtk.Box(spacing=30)
        places = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        places.set_size_request(240, -1)
        b = Gtk.Button()
        b.set_relief(Gtk.ReliefStyle.NONE)
        b.get_style_context().add_class("folio-bs-place")
        hb = Gtk.Box(spacing=10)
        hb.pack_start(icons.image("cmd/lc_open", 32), False, False, 0)
        hb.pack_start(Gtk.Label(label="Browse", xalign=0), True, True, 0)
        b.add(hb)
        b.connect("clicked", lambda *_: (self.close(), self.win.save_as()))
        places.pack_start(b, False, False, 0)
        h.pack_start(places, False, False, 0)
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        eng = self.win.engine
        folder = os.path.dirname(eng.path) if eng.path and not eng.is_new else \
            self.win.dialogs.last_dir
        fbtn = Gtk.FileChooserButton(title="Choose a folder", action=Gtk.FileChooserAction.SELECT_FOLDER)
        fbtn.set_current_folder(folder)
        right.pack_start(fbtn, False, False, 0)
        name = Gtk.Entry(text=self.win.doc_name())
        name.set_activates_default(True)
        right.pack_start(name, False, False, 0)
        from .dialogs import SAVE_TYPES
        types = [(e, l) for e, l in SAVE_TYPES if l]
        tcombo = Gtk.ComboBoxText()
        for e, l in types:
            tcombo.append(e, l)
        tcombo.set_active_id(eng.format if eng.format in dict(types) else "docx")
        row = Gtk.Box(spacing=8)
        row.pack_start(tcombo, True, True, 0)
        save = Gtk.Button(label="Save")
        save.get_style_context().add_class("suggested-action")
        save.get_style_context().add_class("folio-default")
        row.pack_start(save, False, False, 0)
        right.pack_start(row, False, False, 0)

        def do_save(*_):
            n = name.get_text().strip()
            if not n:
                return
            ext = tcombo.get_active_id()
            path = os.path.join(fbtn.get_filename() or folder, n + "." + ext)
            if os.path.exists(path) and not self.win.dialogs.confirm(
                    "%s already exists.\nDo you want to replace it?" % os.path.basename(path),
                    yes="Yes", no="No"):
                return
            self.close()
            self.win.save_to(path)
        save.connect("clicked", do_save)
        name.connect("activate", do_save)
        right.pack_start(Gtk.Separator(), False, False, 8)
        lab = Gtk.Label(xalign=0)
        lab.set_markup("<b>Recent folders</b>")
        right.pack_start(lab, False, False, 0)
        folders = []
        for p in self.win.app.recent():
            d = os.path.dirname(p)
            if d not in folders:
                folders.append(d)
        for d in folders[:8]:
            fb = Gtk.Button()
            fb.set_relief(Gtk.ReliefStyle.NONE)
            hb = Gtk.Box(spacing=10)
            hb.pack_start(icons.image("cmd/lc_open", 24), False, False, 0)
            v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            v.pack_start(Gtk.Label(label=os.path.basename(d) or d, xalign=0), False, False, 0)
            sub = Gtk.Label(label=d.replace(os.path.expanduser("~"), "~"), xalign=0)
            sub.get_style_context().add_class("dim-label")
            v.pack_start(sub, False, False, 0)
            hb.pack_start(v, True, True, 0)
            fb.add(hb)
            fb.connect("clicked", lambda _b, d=d: fbtn.set_current_folder(d))
            right.pack_start(fb, False, False, 0)
        h.pack_start(right, True, True, 0)
        box.pack_start(h, True, True, 0)
        GLib.idle_add(lambda: (name.grab_focus(), False)[1])
        return box

    # ------------------------------------------------------------ Export
    def page_export(self):
        box = self._page("Export")
        h = Gtk.Box(spacing=30)
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        left.set_size_request(260, -1)
        stack = Gtk.Stack()

        def opt(label, icon, key):
            b = Gtk.Button()
            b.set_relief(Gtk.ReliefStyle.NONE)
            b.get_style_context().add_class("folio-bs-place")
            hb = Gtk.Box(spacing=10)
            hb.pack_start(icons.image(icon, 32), False, False, 0)
            hb.pack_start(Gtk.Label(label=label, xalign=0), True, True, 0)
            b.add(hb)
            b.connect("clicked", lambda *_: stack.set_visible_child_name(key))
            left.pack_start(b, False, False, 0)
        opt("Create PDF Document", "cmd/lc_exportdirecttopdf", "pdf")
        opt("Change File Type", "cmd/lc_saveas", "type")
        h.pack_start(left, False, False, 0)
        pdf = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        pdf.pack_start(_heading("Create a PDF Document", "folio-bs-cardtitle"), False, False, 0)
        for t in ("Preserves layout, formatting, fonts, and images",
                  "Content can't be easily changed",
                  "Free viewers are available on the web"):
            pdf.pack_start(Gtk.Label(label="• " + t, xalign=0), False, False, 0)
        pb = Gtk.Button()
        pv = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        pv.pack_start(icons.image("cmd/lc_exportdirecttopdf", 32), False, False, 0)
        pv.pack_start(Gtk.Label(label="Create PDF"), False, False, 0)
        pb.add(pv)
        pb.set_size_request(110, 90)
        pb.set_halign(Gtk.Align.START)
        pb.connect("clicked", lambda *_: self._export("pdf"))
        pdf.pack_start(pb, False, False, 8)
        stack.add_named(pdf, "pdf")
        typ = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        typ.pack_start(_heading("Change File Type", "folio-bs-cardtitle"), False, False, 0)
        lb = Gtk.ListBox()
        for ext, title, desc in EXPORT_TYPES:
            row = Gtk.ListBoxRow()
            row.ext = ext
            v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            v.set_border_width(6)
            t = Gtk.Label(xalign=0)
            t.set_markup("<b>%s</b> (*.%s)" % (title, ext))
            v.pack_start(t, False, False, 0)
            dl = Gtk.Label(label=desc, xalign=0)
            dl.get_style_context().add_class("dim-label")
            v.pack_start(dl, False, False, 0)
            row.add(v)
            lb.add(row)
        typ.pack_start(lb, False, False, 0)
        sb = Gtk.Button(label="Save As")
        sb.set_halign(Gtk.Align.START)
        sb.connect("clicked", lambda *_: (lambda r: r and (self.close(), self.win.save_as(r.ext)))(
            lb.get_selected_row()))
        lb.connect("row-activated", lambda _l, r: (self.close(), self.win.save_as(r.ext)))
        typ.pack_start(sb, False, False, 0)
        stack.add_named(typ, "type")
        h.pack_start(stack, True, True, 0)
        box.pack_start(h, True, True, 0)
        return box

    def _export(self, fmt):
        d = Gtk.FileChooserDialog(title="Publish as PDF", transient_for=self.win,
                                  action=Gtk.FileChooserAction.SAVE)
        d.add_button("Cancel", Gtk.ResponseType.CANCEL)
        b = d.add_button("Publish", Gtk.ResponseType.ACCEPT)
        b.get_style_context().add_class("suggested-action")
        d.set_do_overwrite_confirmation(True)
        eng = self.win.engine
        folder = os.path.dirname(eng.path) if eng.path and not eng.is_new else \
            self.win.dialogs.last_dir
        d.set_current_folder(folder)
        d.set_current_name(self.win.doc_name() + ".pdf")
        f = Gtk.FileFilter()
        f.set_name("PDF (*.pdf)")
        f.add_pattern("*.pdf")
        d.add_filter(f)
        extra = Gtk.Box(spacing=16)
        optimize = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        ol = Gtk.Label(label="Optimize for:", xalign=0)
        std = Gtk.RadioButton(label="Standard (publishing online and printing)")
        small = Gtk.RadioButton(label="Minimum size (publishing online)", group=std)
        for w in (ol, std, small):
            optimize.pack_start(w, False, False, 0)
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        openafter = Gtk.CheckButton(label="Open file after publishing")
        openafter.set_active(True)
        optb = Gtk.Button(label="Options...")
        optb.set_halign(Gtk.Align.START)
        opts = {"range": "all", "from": 1, "to": 1, "bookmarks": "headings",
                "tags": True, "pdfa": False}
        optb.connect("clicked", lambda *_: self._pdf_options(d, opts))
        right.pack_start(optb, False, False, 0)
        right.pack_start(openafter, False, False, 0)
        extra.pack_start(optimize, False, False, 0)
        extra.pack_start(right, False, False, 0)
        extra.show_all()
        d.set_extra_widget(extra)
        r = d.run()
        path = d.get_filename() if r == Gtk.ResponseType.ACCEPT else None
        oa = openafter.get_active()
        minimum = small.get_active()
        d.destroy()
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        fd = {"ExportBookmarks": opts["bookmarks"] != "none",
              "ExportBookmarksToPDFDestination": opts["bookmarks"] == "bookmarks",
              "UseTaggedPDF": bool(opts["tags"]),
              "ExportNotes": False,
              "SelectPdfVersion": 2 if opts["pdfa"] else 0}
        if opts["range"] == "current":
            try:
                fd["PageRange"] = str(eng.ed.caret_page() + 1 if getattr(eng, "native", False)
                                      else docapi.read_cursor(eng.model).getPage())
            except Exception:
                pass
        elif opts["range"] == "pages":
            fd["PageRange"] = "%d-%d" % (opts["from"], max(opts["from"], opts["to"]))
        if minimum:
            fd.update({"ReduceImageResolution": True, "MaxImageResolution": 150,
                       "Quality": 70})
        else:
            fd.update({"Quality": 90})
        if eng.save_as(path, "pdf", keep=False, filter_data=fd):
            self.close()
            if oa:
                subprocess.Popen(["xdg-open", path])
        else:
            self.win.dialogs.message("The PDF couldn't be created.")

    def _pdf_options(self, parent, opts):
        from .widgets import FDialog, heading
        d = FDialog(parent, "Options")
        d.add(heading("Page range"))
        r_all = Gtk.RadioButton(label="All")
        r_cur = Gtk.RadioButton(label="Current page", group=r_all)
        r_pg = Gtk.RadioButton(label="Page(s)", group=r_all)
        n = 1
        try:
            n = docapi.statistics(self.win.docmodel).get("PageCount", 1)
        except Exception:
            pass
        fr = Gtk.SpinButton.new_with_range(1, max(1, n), 1)
        to = Gtk.SpinButton.new_with_range(1, max(1, n), 1)
        fr.set_value(opts["from"])
        to.set_value(max(opts["to"], n if opts["range"] != "pages" else opts["to"]))
        {"all": r_all, "current": r_cur, "pages": r_pg}[opts["range"]].set_active(True)
        row = Gtk.Box(spacing=6)
        row.pack_start(r_pg, False, False, 0)
        row.pack_start(Gtk.Label(label="From:"), False, False, 0)
        row.pack_start(fr, False, False, 0)
        row.pack_start(Gtk.Label(label="To:"), False, False, 0)
        row.pack_start(to, False, False, 0)
        for w in (r_all, r_cur, row):
            d.add(w)
        d.add(heading("Include non-printing information"))
        bm = Gtk.CheckButton(label="Create bookmarks using:")
        bm.set_active(opts["bookmarks"] != "none")
        b_head = Gtk.RadioButton(label="Headings")
        b_word = Gtk.RadioButton(label="Bookmarks", group=b_head)
        (b_word if opts["bookmarks"] == "bookmarks" else b_head).set_active(True)
        sub = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        sub.set_margin_start(24)
        sub.pack_start(b_head, False, False, 0)
        sub.pack_start(b_word, False, False, 0)
        bm.connect("toggled", lambda b: sub.set_sensitive(b.get_active()))
        sub.set_sensitive(bm.get_active())
        tags = Gtk.CheckButton(label="Document structure tags for accessibility")
        tags.set_active(opts["tags"])
        d.add(bm)
        d.add(sub)
        d.add(tags)
        d.add(heading("PDF options"))
        pdfa = Gtk.CheckButton(label="PDF/A compliant")
        pdfa.set_active(opts["pdfa"])
        d.add(pdfa)
        if d.ask() == Gtk.ResponseType.OK:
            opts["range"] = "all" if r_all.get_active() else (
                "current" if r_cur.get_active() else "pages")
            opts["from"], opts["to"] = int(fr.get_value()), int(to.get_value())
            opts["bookmarks"] = "none" if not bm.get_active() else (
                "bookmarks" if b_word.get_active() else "headings")
            opts["tags"] = tags.get_active()
            opts["pdfa"] = pdfa.get_active()
        d.done()

    # ------------------------------------------------------------ Print
    def _printers(self):
        out = []
        default = None
        try:
            r = subprocess.run(["lpstat", "-e"], capture_output=True, text=True, timeout=5)
            out = [l.strip() for l in r.stdout.splitlines() if l.strip()]
            r = subprocess.run(["lpstat", "-d"], capture_output=True, text=True, timeout=5)
            if ":" in r.stdout:
                default = r.stdout.split(":", 1)[1].strip()
        except Exception:
            pass
        return out, default

    def _cleanup_preview(self):
        if self.preview_pdf and os.path.exists(self.preview_pdf):
            try:
                shutil.rmtree(os.path.dirname(self.preview_pdf))
            except OSError:
                pass
        self.preview_pdf = None

    def page_print(self):
        outer = Gtk.Box(spacing=0)
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        left.set_border_width(36)
        left.set_size_request(380, -1)
        left.pack_start(_heading("Print"), False, False, 0)
        top = Gtk.Box(spacing=12)
        pbtn = Gtk.Button()
        pv = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        pv.pack_start(icons.image("cmd/lc_print", 32), False, False, 0)
        pv.pack_start(Gtk.Label(label="Print"), False, False, 0)
        pbtn.add(pv)
        pbtn.set_size_request(90, 80)
        pbtn.get_style_context().add_class("folio-bs-printbtn")
        top.pack_start(pbtn, False, False, 0)
        copies = Gtk.SpinButton.new_with_range(1, 999, 1)
        cb = Gtk.Box(spacing=6)
        cb.pack_start(Gtk.Label(label="Copies:"), False, False, 0)
        cb.pack_start(copies, False, False, 0)
        cb.set_valign(Gtk.Align.CENTER)
        top.pack_start(cb, False, False, 0)
        left.pack_start(top, False, False, 0)
        left.pack_start(_heading("Printer", "folio-bs-cardtitle"), False, False, 0)
        printers, default = self._printers()
        pr = Gtk.ComboBoxText()
        for p in printers:
            pr.append(p, p)
        pr.append("__pdf__", "Print to PDF")
        pr.set_active_id(default if default in printers else
                         (printers[0] if printers else "__pdf__"))
        left.pack_start(pr, False, False, 0)
        left.pack_start(_heading("Settings", "folio-bs-cardtitle"), False, False, 0)
        rng = Gtk.ComboBoxText()
        for k, v in (("all", "Print All Pages"), ("current", "Print Current Page"),
                     ("custom", "Custom Print")):
            rng.append(k, v)
        rng.set_active_id("all")
        left.pack_start(rng, False, False, 0)
        pages = Gtk.Entry()
        pages.set_placeholder_text("Pages: e.g. 1-3, 5")
        left.pack_start(pages, False, False, 0)
        sides = Gtk.ComboBoxText()
        for k, v in (("one-sided", "Print One Sided"),
                     ("two-sided-long-edge", "Print on Both Sides (flip on long edge)"),
                     ("two-sided-short-edge", "Print on Both Sides (flip on short edge)")):
            sides.append(k, v)
        sides.set_active_id("one-sided")
        left.pack_start(sides, False, False, 0)
        coll = Gtk.ComboBoxText()
        coll.append("true", "Collated   1,2,3  1,2,3  1,2,3")
        coll.append("false", "Uncollated   1,1,1  2,2,2  3,3,3")
        coll.set_active_id("true")
        left.pack_start(coll, False, False, 0)
        m = self.win.engine.model
        ps = docapi.page_setup(m) if m is not None else None
        orient = Gtk.ComboBoxText()
        orient.append("p", "Portrait Orientation")
        orient.append("l", "Landscape Orientation")
        orient.set_active_id("l" if ps and ps["landscape"] else "p")
        left.pack_start(orient, False, False, 0)
        from .dlg_doc import PAPER
        paper = Gtk.ComboBoxText()
        for name, w, h in PAPER:
            paper.append(name, "%s  %s x %s" % (name, _dim(w), _dim(h)))
        if ps:
            pw, ph = min(ps["width"], ps["height"]), max(ps["width"], ps["height"])
            for name, w, h in PAPER:
                if abs(w - pw) < 60 and abs(h - ph) < 60:
                    paper.set_active_id(name)
        left.pack_start(paper, False, False, 0)
        nup = Gtk.ComboBoxText()
        for n in (1, 2, 4, 6, 8, 16):
            nup.append(str(n), "%d Page%s Per Sheet" % (n, "" if n == 1 else "s"))
        nup.set_active_id("1")
        left.pack_start(nup, False, False, 0)
        scale = Gtk.ComboBoxText()
        scale.append("none", "Scale to Paper Size: No Scaling")
        for name, w, h in PAPER:
            scale.append(name, "Scale to %s  %s x %s" % (name, _dim(w), _dim(h)))
        scale.set_active_id("none")
        left.pack_start(scale, False, False, 0)
        setup = Gtk.LinkButton(label="Page Setup")
        setup.set_halign(Gtk.Align.END)
        setup.connect("activate-link", lambda *_: (self.win.dialogs.page_setup(), self._render_preview(),
                                                   True)[2])
        left.pack_start(setup, False, False, 0)
        lsw = Gtk.ScrolledWindow()
        lsw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        lsw.add(left)
        outer.pack_start(lsw, False, False, 0)
        # preview
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        right.get_style_context().add_class("folio-bs-preview")
        self.pv_area = Gtk.DrawingArea()
        self.pv_area.connect("draw", self._draw_preview)
        right.pack_start(self.pv_area, True, True, 0)
        nav = Gtk.Box(spacing=6)
        nav.set_border_width(6)
        prev = Gtk.Button.new_from_icon_name("go-previous-symbolic", Gtk.IconSize.MENU)
        nxt = Gtk.Button.new_from_icon_name("go-next-symbolic", Gtk.IconSize.MENU)
        self.pv_page = Gtk.Entry(text="1")
        self.pv_page.set_width_chars(3)
        self.pv_of = Gtk.Label(label="of 1")
        nav.pack_start(prev, False, False, 0)
        nav.pack_start(self.pv_page, False, False, 0)
        nav.pack_start(self.pv_of, False, False, 0)
        nav.pack_start(nxt, False, False, 0)
        self.pv_zoom = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0.3, 2.0, 0.1)
        self.pv_zoom.set_value(1.0)
        self.pv_zoom.set_draw_value(False)
        self.pv_zoom.set_size_request(140, -1)
        self.pv_zoom.connect("value-changed", lambda *_: self.pv_area.queue_draw())
        nav.pack_end(self.pv_zoom, False, False, 0)
        right.pack_start(nav, False, False, 0)
        outer.pack_start(right, True, True, 0)
        self.pv_index = 0
        prev.connect("clicked", lambda *_: self._pv_go(self.pv_index - 1))
        nxt.connect("clicked", lambda *_: self._pv_go(self.pv_index + 1))
        self.pv_page.connect("activate", lambda e: self._pv_go(int(e.get_text() or 1) - 1
                                                               if e.get_text().isdigit() else 0))

        def apply_layout(*_):
            mm = self.win.engine.model
            if mm is None:
                return
            name = paper.get_active_id()
            for n, w, h in PAPER:
                if n == name:
                    docapi.set_page(mm, width=w, height=h)
            docapi.set_page(mm, landscape=orient.get_active_id() == "l")
            self._render_preview()
        orient.connect("changed", apply_layout)
        paper.connect("changed", apply_layout)

        def do_print(*_):
            self._print(pr.get_active_id(), int(copies.get_value()), rng.get_active_id(),
                        pages.get_text(), sides.get_active_id(), coll.get_active_id() == "true",
                        int(nup.get_active_id()), scale.get_active_id())
        pbtn.connect("clicked", do_print)
        GLib.idle_add(lambda: (self._render_preview(), False)[1])
        return outer

    def _render_preview(self):
        self._cleanup_preview()
        d = tempfile.mkdtemp(prefix="folio-print-")
        path = os.path.join(d, "preview.pdf")
        if not self.win.engine.save_as(path, "pdf", keep=False):
            return
        self.preview_pdf = path
        try:
            import gi
            gi.require_version("Poppler", "0.18")
            from gi.repository import Poppler
            self.pv_doc = Poppler.Document.new_from_file("file://" + path, None)
            n = self.pv_doc.get_n_pages()
        except Exception:
            self.pv_doc = None
            n = 1
        self.pv_of.set_text("of %d" % n)
        self._pv_go(min(self.pv_index, n - 1))

    def _pv_go(self, i):
        doc = getattr(self, "pv_doc", None)
        n = doc.get_n_pages() if doc else 1
        self.pv_index = max(0, min(n - 1, i))
        self.pv_page.set_text(str(self.pv_index + 1))
        self.pv_area.queue_draw()

    def _draw_preview(self, area, cr):
        a = area.get_allocation()
        cr.set_source_rgb(0.9, 0.9, 0.9)
        cr.paint()
        doc = getattr(self, "pv_doc", None)
        if doc is None:
            return
        page = doc.get_page(self.pv_index)
        pw, ph = page.get_size()
        s = min((a.width - 40) / pw, (a.height - 40) / ph) * self.pv_zoom.get_value()
        x = (a.width - pw * s) / 2
        y = max(20, (a.height - ph * s) / 2)
        cr.set_source_rgba(0, 0, 0, 0.25)
        cr.rectangle(x + 3, y + 3, pw * s, ph * s)
        cr.fill()
        cr.set_source_rgb(1, 1, 1)
        cr.rectangle(x, y, pw * s, ph * s)
        cr.fill()
        cr.save()
        cr.translate(x, y)
        cr.scale(s, s)
        page.render(cr)
        cr.restore()

    CUPS_MEDIA = {"Letter": "Letter", "Legal": "Legal", "Executive": "Executive", "A3": "A3",
                  "A4": "A4", "A5": "A5", "B5 (JIS)": "B5", "Tabloid": "Tabloid",
                  "Envelope #10": "Env10", "Envelope DL": "EnvDL"}

    def _print(self, printer, copies, rng, pages, sides, collate, nup, scale="none"):
        if not self.preview_pdf:
            self._render_preview()
        pdf = self.preview_pdf
        if not pdf:
            self.win.dialogs.message("The document couldn't be prepared for printing.")
            return
        if printer == "__pdf__":
            self._export("pdf")
            return
        args = ["lp", "-d", printer, "-n", str(copies), "-o", "sides=" + sides,
                "-o", "collate=" + ("true" if collate else "false")]
        if nup > 1:
            args += ["-o", "number-up=%d" % nup]
        if scale and scale != "none":
            args += ["-o", "media=" + self.CUPS_MEDIA.get(scale, scale), "-o", "fit-to-page"]
        if rng == "current":
            m = self.win.engine.model
            if getattr(self.win.engine, "native", False):
                cur = self.win.engine.ed.caret_page() + 1
            else:
                cur = docapi.read_cursor(m).getPage() if m is not None else 1
            args += ["-P", str(cur)]
        elif rng == "custom" and pages.strip():
            args += ["-P", pages.replace(" ", "")]
        args.append(pdf)
        try:
            r = subprocess.run(args, capture_output=True, text=True, timeout=30)
            if r.returncode != 0:
                self.win.dialogs.message("Printing failed: " + (r.stderr.strip() or "unknown error"))
                return
        except FileNotFoundError:
            self.win.dialogs.message("No printing system was found on this computer.")
            return
        if getattr(self.win.engine, "native", False):
            import datetime
            from .native import docprops
            docprops.set_core(self.win.engine.ed, lastPrinted=datetime.datetime.now(
                datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
        m = self.win.engine.model
        if m is not None:
            try:
                import time
                from . import bridge
                now = time.localtime()
                dt = bridge.struct("com.sun.star.util.DateTime", Year=now.tm_year, Month=now.tm_mon,
                                   Day=now.tm_mday, Hours=now.tm_hour, Minutes=now.tm_min)
                m.getDocumentProperties().PrintDate = dt
            except Exception:
                pass
        self.close()


def _dim(mm100):
    from .widgets import fmt_len
    return fmt_len(mm100)
