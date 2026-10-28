"""Task panes docked beside the document: Navigation, Styles, Editor
(spelling), Thesaurus, Clipboard, Comments."""
import html

from gi.repository import Gdk, GLib, Gtk, Pango

from . import docapi, icons
from .actions import word_style, engine_style, CHAR_STYLES
from .ribbon import menu_popover


class Pane(Gtk.Box):
    TITLE = ""
    WIDTH = 300

    def __init__(self, win):
        Gtk.Box.__init__(self, orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.win = win
        self.get_style_context().add_class("folio-pane")
        self.set_size_request(self.WIDTH, -1)
        head = Gtk.Box(spacing=4)
        title = Gtk.Label(label=self.TITLE, xalign=0)
        title.get_style_context().add_class("folio-pane-title")
        head.pack_start(title, True, True, 0)
        close = Gtk.Button()
        close.set_relief(Gtk.ReliefStyle.NONE)
        close.add(Gtk.Image.new_from_icon_name("window-close-symbolic", Gtk.IconSize.MENU))
        close.set_tooltip_text("Close")
        close.connect("clicked", lambda *_: self.close())
        head.pack_end(close, False, False, 0)
        self.pack_start(head, False, False, 0)
        self.title_label = title

    @property
    def model(self):
        # the new engine answers the parts of the document interface the panes use
        return self.win.dialogs.model

    def close(self):
        self.win.hide_pane(self)

    def on_shown(self):
        pass


# ======================================================================
class NavigationPane(Pane):
    TITLE = "Navigation"

    def __init__(self, win):
        Pane.__init__(self, win)
        self.entry = Gtk.SearchEntry()
        self.entry.set_placeholder_text("Search document")
        self.entry.connect("activate", lambda *_: self.search())
        self.entry.connect("search-changed", lambda *_: self._schedule())
        self.entry.connect("stop-search", lambda *_: (self.entry.set_text(""), self.win.focus_document()))
        self.pack_start(self.entry, False, False, 0)
        self.switch = Gtk.StackSwitcher()
        self.stack = Gtk.Stack()
        self.switch.set_stack(self.stack)
        self.switch.get_style_context().add_class("folio-navtabs")
        self.pack_start(self.switch, False, False, 0)
        # headings
        self.hstore = Gtk.TreeStore(str, object)
        self.htv = Gtk.TreeView(model=self.hstore)
        self.htv.set_headers_visible(False)
        self.htv.set_enable_search(False)
        cell = Gtk.CellRendererText()
        cell.set_property("ellipsize", Pango.EllipsizeMode.END)
        self.htv.append_column(Gtk.TreeViewColumn("", cell, text=0))
        self.htv.get_selection().connect("changed", self._heading_clicked)
        # drag headings to move their sections
        targets = [Gtk.TargetEntry.new("FOLIO_HEADING", Gtk.TargetFlags.SAME_WIDGET, 0)]
        self.htv.enable_model_drag_source(Gdk.ModifierType.BUTTON1_MASK, targets,
                                          Gdk.DragAction.MOVE)
        self.htv.enable_model_drag_dest(targets, Gdk.DragAction.MOVE)
        self.htv.connect("drag-data-get", self._drag_get)
        self.htv.connect("drag-data-received", self._drag_received)
        self.htv.connect("button-press-event", self._heading_menu)
        hsw = Gtk.ScrolledWindow()
        hsw.add(self.htv)
        self.empty_h = Gtk.Label(label="Create an interactive outline of your document.\n\n"
                                       "It's a great way to keep track of where you are or "
                                       "quickly move your content around.\n\nTo get started, "
                                       "go to the Home tab and apply Heading styles to the "
                                       "headings in your document.", xalign=0)
        self.empty_h.set_line_wrap(True)
        self.empty_h.set_max_width_chars(34)
        self.empty_h.get_style_context().add_class("dim-label")
        hbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        hbox.pack_start(hsw, True, True, 0)
        hbox.pack_start(self.empty_h, False, False, 6)
        self.stack.add_titled(hbox, "headings", "Headings")
        # pages
        pbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.pstore = Gtk.ListStore(str, int)
        self.ptv = Gtk.TreeView(model=self.pstore)
        self.ptv.set_headers_visible(False)
        self.ptv.append_column(Gtk.TreeViewColumn("", Gtk.CellRendererText(), text=0))
        self.ptv.get_selection().connect("changed", self._page_clicked)
        psw = Gtk.ScrolledWindow()
        psw.add(self.ptv)
        pbox.pack_start(psw, True, True, 0)
        self.stack.add_titled(pbox, "pages", "Pages")
        # results
        self.rstore = Gtk.ListStore(str, object)
        self.rtv = Gtk.TreeView(model=self.rstore)
        self.rtv.set_headers_visible(False)
        rc = Gtk.CellRendererText()
        rc.set_property("wrap-mode", Pango.WrapMode.WORD_CHAR)
        rc.set_property("wrap-width", 250)
        self.rtv.append_column(Gtk.TreeViewColumn("", rc, markup=0))
        self.rtv.get_selection().connect("changed", self._result_clicked)
        rsw = Gtk.ScrolledWindow()
        rsw.add(self.rtv)
        self.rcount = Gtk.Label(label="", xalign=0)
        rbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        nav = Gtk.Box(spacing=2)
        nav.pack_start(self.rcount, True, True, 0)
        for icon, d in (("go-up-symbolic", -1), ("go-down-symbolic", 1)):
            b = Gtk.Button()
            b.set_relief(Gtk.ReliefStyle.NONE)
            b.add(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.MENU))
            b.connect("clicked", lambda _b, d=d: self.step(d))
            nav.pack_start(b, False, False, 0)
        rbox.pack_start(nav, False, False, 0)
        rbox.pack_start(rsw, True, True, 0)
        self.stack.add_titled(rbox, "results", "Results")
        self.pack_start(self.stack, True, True, 0)
        self._timer = None
        self._ranges = []
        self._muted = False
        win.engine.connect("state-changed", self._on_state)

    def on_shown(self):
        self.refresh_headings()
        self.refresh_pages()

    def _on_state(self, eng, key, value):
        if key in (".uno:StatePageNumber",) and self.get_mapped():
            self.refresh_pages()
        if key == ".uno:ModifiedStatus" and self.get_mapped():
            GLib.timeout_add(600, lambda: (self.refresh_headings(), False)[1])
        if key == ".uno:StateWordCount" and self.get_mapped() and self.entry.get_text():
            # the text changed: keep the results current, without moving
            # the cursor away from where the user is typing
            if getattr(self, "_requery", None):
                GLib.source_remove(self._requery)

            def again():
                self._requery = None
                self.search(quiet=True)
                return False
            self._requery = GLib.timeout_add(700, again)

    def focus_search(self, text=None):
        if text:
            self.entry.set_text(text)
            self.search()
        self.entry.grab_focus()

    def show_headings(self):
        self.stack.set_visible_child_name("headings")
        self.refresh_headings()

    def _native(self):
        eng = self.win.engine
        return eng.ed if getattr(eng, "native", False) else None

    def refresh_headings(self):
        m = self.model
        ed = self._native()
        if m is None and ed is None:
            return
        self._muted = True
        self.hstore.clear()
        parents = {0: None}
        hs = ed.nav_headings() if ed is not None else docapi.headings(m)
        for lvl, text, par in hs:
            parent = None
            for k in range(lvl - 1, -1, -1):
                if k in parents:
                    parent = parents[k]
                    break
            it = self.hstore.append(parent, [text, par])
            parents[lvl] = it
            for k in list(parents):
                if k > lvl:
                    del parents[k]
        self.htv.expand_all()
        self.empty_h.set_visible(not hs)
        self._muted = False

    def refresh_pages(self):
        m = self.model
        ed = self._native()
        if m is None and ed is None:
            return
        n = ed.page_count() if ed is not None else docapi.statistics(m).get("PageCount", 1)
        if len(self.pstore) != n:
            self._muted = True
            self.pstore.clear()
            for i in range(1, n + 1):
                self.pstore.append(["Page %d" % i, i])
            self._muted = False

    def _heading_clicked(self, sel):
        if self._muted:
            return
        model, it = sel.get_selected()
        ed = self._native()
        if it and ed is not None:
            if ed.goto_node(model[it][1]):
                self.win.engine.view.after_move()
                self.win.engine.view.scroll_to_caret()
            return
        if it and self.model is not None:
            docapi.goto_start(self.model, model[it][1])
            self.win.focus_document()

    def _drag_get(self, tv, ctx, data, info, time):
        model, it = tv.get_selection().get_selected()
        if it is not None:
            data.set(data.get_target(), 8, model.get_string_from_iter(it).encode())

    def _drag_received(self, tv, ctx, x, y, data, info, time):
        tv.stop_emission_by_name("drag-data-received")
        src_path = data.get_data().decode() if data.get_data() else None
        dest = tv.get_dest_row_at_pos(x, y)
        ed = self._native()
        if ed is not None:
            if not src_path or dest is None:
                Gtk.drag_finish(ctx, False, False, time)
                return
            path, pos = dest
            src = self.hstore[Gtk.TreePath.new_from_string(src_path)][1]
            dst = self.hstore[path][1]
            after = pos in (Gtk.TreeViewDropPosition.AFTER, Gtk.TreeViewDropPosition.INTO_OR_AFTER)
            Gtk.drag_finish(ctx, True, False, time)
            nodes = ed.section_paras(src)
            if src == dst or dst in nodes:
                return
            target = ed.section_paras(dst)[-1] if after else dst
            if ed.move_paras(nodes, target, after):
                self.win.engine.view.after_edit()
            GLib.timeout_add(200, lambda: (self.refresh_headings(), False)[1])
            return
        if not src_path or dest is None:
            Gtk.drag_finish(ctx, False, False, time)
            return
        path, pos = dest
        src = self.hstore[Gtk.TreePath.new_from_string(src_path)][1]
        dst = self.hstore[path][1]
        after = pos in (Gtk.TreeViewDropPosition.AFTER,
                        Gtk.TreeViewDropPosition.INTO_OR_AFTER)
        Gtk.drag_finish(ctx, True, False, time)
        if src is dst:
            return
        m = self.model

        def go():
            try:
                docapi.move_section(m, src, dst, after)
            except Exception as e:
                print("move section:", e)
            GLib.timeout_add(300, lambda: (self.refresh_headings(), False)[1])
        self.win.engine.sync(go)

    def _heading_menu(self, tv, ev):
        if ev.button != 3:
            return False
        res = tv.get_path_at_pos(int(ev.x), int(ev.y))
        if not res:
            return False
        path = res[0]
        tv.get_selection().select_path(path)
        par = self.hstore[path][1]
        m = self.model
        menu = Gtk.Menu()
        if self._native() is not None:
            return self._native_heading_menu(ev, par)

        def item(label, fn):
            mi = Gtk.MenuItem(label=label)
            mi.connect("activate", lambda *_: self.win.engine.sync(
                lambda: (fn(), GLib.timeout_add(300, lambda: (self.refresh_headings(),
                                                              False)[1]))))
            menu.append(mi)
        item("Promote", lambda: docapi.set_heading_level(m, par, -1))
        item("Demote", lambda: docapi.set_heading_level(m, par, 1))
        menu.append(Gtk.SeparatorMenuItem())

        def new_heading(before):
            body = m.getText()
            if before:
                cur = body.createTextCursorByRange(par.getStart())
                body.insertControlCharacter(cur, 0, False)
                cur.gotoPreviousParagraph(False)
            else:
                rng, last = docapi.section_range(m, par)
                cur = body.createTextCursorByRange(rng.getEnd())
                body.insertControlCharacter(cur, 0, False)
                if not last:
                    cur.gotoPreviousParagraph(False)
            cur.ParaStyleName = par.ParaStyleName
            docapi.goto(m, cur)
        item("New Heading Before", lambda: new_heading(True))
        item("New Heading After", lambda: new_heading(False))
        def new_sub():
            body = m.getText()
            cur = body.createTextCursorByRange(par.getEnd())
            body.insertControlCharacter(cur, 0, False)
            lvl = min(9, (par.OutlineLevel or 1) + 1)
            cur.ParaStyleName = "Heading %d" % lvl
            docapi.goto(m, cur)
        item("New Subheading", new_sub)
        menu.append(Gtk.SeparatorMenuItem())
        item("Delete", lambda: docapi.delete_section(m, par))
        menu.append(Gtk.SeparatorMenuItem())

        def select_section():
            rng, _l = docapi.section_range(m, par)
            vc = docapi.view_cursor(m)
            vc.gotoRange(rng.getStart(), False)
            vc.gotoRange(rng.getEnd(), True)
        item("Select Heading and Content", select_section)
        expand = Gtk.MenuItem(label="Expand All")
        expand.connect("activate", lambda *_: self.htv.expand_all())
        collapse = Gtk.MenuItem(label="Collapse All")
        collapse.connect("activate", lambda *_: self.htv.collapse_all())
        menu.append(expand)
        menu.append(collapse)
        menu.show_all()
        menu.popup_at_pointer(ev)
        return True

    def _native_heading_menu(self, ev, node):
        ed = self._native()
        menu = Gtk.Menu()

        def level(d):
            if not ed.goto_node(node):
                return
            import re
            st = ed.state().get("style_name") or ed.state().get("style") or ""
            mm = re.search(r"(\d)$", st)
            lvl = int(mm.group(1)) if mm else 1
            self.win.actions.apply_style("Heading %d" % max(1, min(9, lvl + d)))
            GLib.timeout_add(200, lambda: (self.refresh_headings(), False)[1])
        def add(label, fn):
            mi = Gtk.MenuItem(label=label)
            mi.connect("activate", lambda *_: fn())
            menu.append(mi)
        add("Promote", lambda: level(-1))
        add("Demote", lambda: level(1))
        menu.append(Gtk.SeparatorMenuItem())
        view = self.win.engine.view

        def style_of():
            return ed.state().get("style_name") or ed.state().get("style") or "Heading 1"

        def new_heading(before):
            if not ed.goto_node(node):
                return
            st = style_of()
            back = True
            if not before:
                last = ed.section_paras(node)[-1]
                ed.goto_node(last)
                ed.move_caret("para_down", False)
                if ed.caret_pos()[0] == last:
                    back = False            # the end of the document
            ed.type_text("\n")
            if back:
                ed.move_caret("left", False)
            self.win.actions.apply_style(st)
            view.after_edit()
            self.win.focus_document()
            GLib.timeout_add(200, lambda: (self.refresh_headings(), False)[1])

        def new_sub():
            if not ed.goto_node(node):
                return
            import re
            mm = re.search(r"(\d)$", style_of())
            lvl = int(mm.group(1)) if mm else 1
            ed.move_caret("end", False)
            ed.type_text("\n")
            self.win.actions.apply_style("Heading %d" % min(9, lvl + 1))
            view.after_edit()
            self.win.focus_document()
            GLib.timeout_add(200, lambda: (self.refresh_headings(), False)[1])

        def select_section():
            nodes = ed.section_paras(node)
            if not nodes:
                return False
            ed.select_nodes(nodes[0], 0, nodes[-1], len(ed.para_text_of(nodes[-1])))
            view.after_move()
            return True

        def delete_section():
            nodes = ed.section_paras(node)
            if not nodes:
                return
            ed.goto_node(nodes[0])
            nxt = ed.para_text_of(nodes[-1])
            ed.select_nodes(nodes[0], 0, nodes[-1], len(nxt))
            # the paragraph mark at the end goes too, unless it's the document's last
            ed.move_caret("right", True)
            ed.delete(True, False)
            view.after_edit()
            GLib.timeout_add(200, lambda: (self.refresh_headings(), False)[1])
        add("New Heading Before", lambda: new_heading(True))
        add("New Heading After", lambda: new_heading(False))
        add("New Subheading", new_sub)
        menu.append(Gtk.SeparatorMenuItem())
        add("Delete", delete_section)
        menu.append(Gtk.SeparatorMenuItem())
        add("Select Heading and Content", lambda: (select_section(), self.win.focus_document()))
        add("Print Heading and Content", lambda: select_section() and self.win.run("backstage-print"))
        menu.append(Gtk.SeparatorMenuItem())
        for label, fn in (("Expand All", self.htv.expand_all), ("Collapse All", self.htv.collapse_all)):
            mi = Gtk.MenuItem(label=label)
            mi.connect("activate", lambda _m, fn=fn: fn())
            menu.append(mi)
        menu.show_all()
        menu.popup_at_pointer(ev)
        return True

    def _page_clicked(self, sel):
        if self._muted:
            return
        model, it = sel.get_selected()
        ed = self._native()
        if it and ed is not None:
            if ed.goto_page(model[it][1] - 1):
                self.win.engine.view.after_move()
                self.win.engine.view.scroll_to_caret()
            return
        if it and self.model is not None:
            vc = docapi.view_cursor(self.model)
            vc.jumpToPage(model[it][1])
            vc.jumpToStartOfPage()

    def _schedule(self):
        if self._timer:
            GLib.source_remove(self._timer)
        self._timer = GLib.timeout_add(350, self._timed)

    def _timed(self):
        self._timer = None
        self.search()
        return False

    def search(self, quiet=False):
        m = self.model
        text = self.entry.get_text()
        if self._native() is not None:
            from .native import find
            find.nav_search(self, text, quiet)
            return
        self.rstore.clear()
        self._ranges = []
        if not text or m is None:
            self.rcount.set_text("")
            self.win.engine.view.highlight_all("") if hasattr(self.win.engine.view, "highlight_all") else None
            return
        self.stack.set_visible_child_name("results")
        sd = m.createSearchDescriptor()
        sd.SearchString = text
        found = m.findAll(sd)
        n = found.getCount() if found else 0
        for i in range(min(n, 500)):
            r = found.getByIndex(i)
            self._ranges.append(r)
            try:
                c = r.getText().createTextCursorByRange(r.getStart())
                c.gotoStartOfParagraph(True)
                before = c.getString()[-40:]
                c = r.getText().createTextCursorByRange(r.getEnd())
                c.gotoEndOfParagraph(True)
                after = c.getString()[:60]
            except Exception:
                before = after = ""
            self.rstore.append(["%s<b>%s</b>%s" % (html.escape(before), html.escape(r.getString()),
                                                   html.escape(after)), r])
        self.rcount.set_text("%d result%s" % (n, "" if n == 1 else "s") if n else
                             "No results")
        try:
            if not quiet:       # (it moves the cursor to the first match)
                self.win.engine.view.highlight_all(text)
        except Exception:
            pass
        if quiet:
            self._pos = -1
            if n:
                self.rcount.set_text("%d result%s" % (n, "" if n == 1 else "s"))
            return
        self._pos = -1
        if n:
            self.step(1)

    def step(self, d):
        if not self._ranges:
            return
        self._pos = (getattr(self, "_pos", -1) + d) % len(self._ranges)
        self.rtv.get_selection().select_path(Gtk.TreePath(self._pos))
        self.rcount.set_text("Result %d of %d" % (self._pos + 1, len(self._ranges)))

    def _result_clicked(self, sel):
        model, it = sel.get_selected()
        if it and self._native() is not None:
            from .native import find
            self._pos = model.get_path(it)[0]
            find.nav_select(self, model[it][1])
            return
        if it and self.model is not None:
            self._pos = model.get_path(it)[0]
            docapi.select(self.model, model[it][1])


# ======================================================================
class StylesPane(Pane):
    TITLE = "Styles"

    def __init__(self, win):
        Pane.__init__(self, win)
        self.store = Gtk.ListStore(str, str, str)   # display, markup, engine name
        self.tv = Gtk.TreeView(model=self.store)
        self.tv.set_headers_visible(False)
        cell = Gtk.CellRendererText()
        cell.set_property("ellipsize", Pango.EllipsizeMode.END)
        col = Gtk.TreeViewColumn("", cell, markup=1)
        col.set_expand(True)
        self.tv.append_column(col)
        kind = Gtk.CellRendererText()
        kind.set_property("foreground", "#777777")
        self.tv.append_column(Gtk.TreeViewColumn("", kind, text=2))
        self.tv.connect("row-activated", lambda *_: self.apply())
        self.tv.get_selection().connect("changed", lambda *_: self.apply() if not self._muted else None)
        self.tv.connect("button-press-event", self._button)
        sw = Gtk.ScrolledWindow()
        sw.add(self.tv)
        self.pack_start(sw, True, True, 0)
        self.preview = Gtk.CheckButton(label="Show Preview")
        self.preview.set_active(True)
        self.preview.connect("toggled", lambda *_: self.refresh())
        self.used_only = Gtk.CheckButton(label="Show only styles in use")
        self.used_only.connect("toggled", lambda *_: self.refresh())
        self.pack_start(self.preview, False, False, 0)
        self.pack_start(self.used_only, False, False, 0)
        bb = Gtk.Box(spacing=4)
        for icon, tip, cb in (("cmd/sc_stylenewbyexample", "New Style",
                               lambda: win.dialogs.new_style()),
                              ("cmd/sc_styleupdatebyexample", "Update to Match Selection",
                               self.update_selected),
                              ("cmd/sc_editstyle", "Modify Style", self.modify_selected),
                              ("cmd/sc_inspectordeck", "Style Inspector",
                               lambda: win.act_style_inspector()),
                              ("cmd/sc_designerdialog", "Manage Styles",
                               lambda: __import__("folio.styletools", fromlist=["x"])
                               .manage_styles(win))):
            b = Gtk.Button()
            b.add(icons.image(icon, 16))
            b.set_tooltip_text(tip)
            b.connect("clicked", lambda _b, cb=cb: cb())
            bb.pack_start(b, False, False, 0)
        self.pack_start(bb, False, False, 0)
        self._muted = False
        win.engine.connect("state-changed", self._on_state)

    def on_shown(self):
        self.refresh()

    def _on_state(self, eng, key, value):
        if key == ".uno:StyleApply" and self.get_mapped():
            self.select(word_style(value))

    def refresh(self):
        m = self.model
        if m is None:
            return
        self._muted = True
        self.store.clear()
        info = []
        for fam, mark in (("ParagraphStyles", "¶"), ("CharacterStyles", "a")):
            for n, disp in docapi.style_names(m, fam, self.used_only.get_active()):
                wn = word_style(disp)
                if fam == "CharacterStyles" and wn not in CHAR_STYLES and \
                        not docapi.char_styles(m).getByName(n).isUserDefined():
                    continue
                if fam == "ParagraphStyles" and not self.used_only.get_active():
                    st = docapi.para_styles(m).getByName(n)
                    if not (st.isInUse() or st.isUserDefined() or wn in PREFERRED):
                        continue
                info.append((wn, fam, mark, n))
        order = {n: i for i, n in enumerate(PREFERRED)}
        info.sort(key=lambda t: (order.get(t[0], 999), t[0].lower()))
        seen = set()
        for wn, fam, mark, n in info:
            if wn in seen:
                continue
            seen.add(wn)
            markup = html.escape(wn)
            if self.preview.get_active():
                si = docapi.style_info(m, n, fam) or {}
                size = min(16, max(9, si.get("CharHeight") or 11))
                color = si.get("CharColor", -1)
                attrs = 'size="%dpt"' % size
                if si.get("CharWeight", 100) >= 150:
                    attrs += ' weight="bold"'
                if str(getattr(si.get("CharPosture"), "value", "")) == "ITALIC":
                    attrs += ' style="italic"'
                if color is not None and color > 0:
                    attrs += ' foreground="#%06x"' % color
                fam_name = si.get("CharFontName")
                if fam_name:
                    attrs += ' font_family="%s"' % html.escape(fam_name)
                markup = "<span %s>%s</span>" % (attrs, html.escape(wn))
            self.store.append([wn, markup, mark])
        self._muted = False
        self.select(word_style(self.win.engine.get(".uno:StyleApply") or "Normal"))

    def select(self, name):
        self._muted = True
        for row in self.store:
            if row[0] == name:
                self.tv.get_selection().select_iter(row.iter)
                break
        self._muted = False

    def _current(self):
        model, it = self.tv.get_selection().get_selected()
        return model[it][0] if it else None

    def apply(self):
        name = self._current()
        if name:
            self.win.actions.apply_style(name)

    def update_selected(self):
        name = self._current()
        if name and self.model is not None:
            docapi.update_style_to_match(self.model, engine_style(name))
            self.win.design_changed()

    def modify_selected(self):
        name = self._current()
        if name:
            self.win.dialogs.modify_style(name)
            self.refresh()

    def _button(self, tv, ev):
        if ev.button != 3:
            return False
        res = tv.get_path_at_pos(int(ev.x), int(ev.y))
        if not res:
            return False
        self._muted = True
        tv.get_selection().select_path(res[0])
        self._muted = False
        name = self._current()
        from .stylemodify import context_menu
        context_menu(self.win, name, tv, ev)
        return True

    def _delete(self, name):
        m = self.model
        eng = engine_style(name)
        fam = docapi.para_styles(m)
        if fam.hasByName(eng) and fam.getByName(eng).isUserDefined():
            if self.win.dialogs.confirm("Do you want to delete style %s from the document?" % name,
                                        yes="Yes", no="No"):
                fam.removeByName(eng)
                self.refresh()
        else:
            self.win.dialogs.message("Built-in styles can't be deleted.")


def Gdk_rect(ev):
    from gi.repository import Gdk
    r = Gdk.Rectangle()
    r.x, r.y, r.width, r.height = int(ev.x), int(ev.y), 1, 1
    return r


PREFERRED = ["Normal", "No Spacing", "Heading 1", "Heading 2", "Heading 3", "Heading 4",
             "Title", "Subtitle", "Subtle Emphasis", "Emphasis", "Intense Emphasis", "Strong",
             "Quote", "Intense Quote", "Subtle Reference", "Intense Reference", "Book Title",
             "List Paragraph", "Caption", "TOC Heading", "Hyperlink"]


# ======================================================================
class EditorPane(Pane):
    TITLE = "Editor"

    def __init__(self, win):
        Pane.__init__(self, win)
        self.status = Gtk.Label(label="", xalign=0)
        self.status.set_line_wrap(True)
        self.pack_start(self.status, False, False, 0)
        self.word = Gtk.Label(xalign=0)
        self.word.get_style_context().add_class("folio-editor-word")
        self.pack_start(self.word, False, False, 0)
        self.pack_start(Gtk.Label(label="Suggestions", xalign=0), False, False, 4)
        self.sugg = Gtk.ListBox()
        self.sugg.set_selection_mode(Gtk.SelectionMode.NONE)
        self.sugg.connect("row-activated", lambda lb, row: self.change(row.word))
        self.pack_start(self.sugg, False, False, 0)
        bb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        for label, cb in (("Ignore Once", self.ignore_once), ("Ignore All", self.ignore_all),
                          ("Add to Dictionary", self.add)):
            b = Gtk.Button(label=label)
            b.connect("clicked", lambda _b, cb=cb: cb())
            bb.pack_start(b, False, False, 0)
        self.change_all_btn = Gtk.Button(label="Change All")
        self.change_all_btn.connect("clicked", lambda *_: self.change_all())
        bb.pack_start(self.change_all_btn, False, False, 0)
        self.pack_start(bb, False, False, 6)
        self.current = None

    def start(self):
        self.mode = "spelling"
        self.status.set_text("Checking the document…")
        GLib.idle_add(lambda: (self.next(False), False)[1])

    @property
    def native(self):
        return getattr(self.win.engine, "native", False)

    def next(self, after=True):
        m = self.model
        if m is None and not self.native:
            return
        for c in self.sugg.get_children():
            self.sugg.remove(c)
        w = None
        if getattr(self, "mode", "spelling") == "spelling":
            if self.native:
                from .native import docops
                w = docops.next_misspelling(self.win, after, self.win.ignored_words)
            else:
                w = docapi.next_misspelling(m, after, self.win.ignored_words)
            if w is None:
                self.mode = "grammar"
                after = False
                self._grammar_wrapped = False
        self.current = w
        if w is None:
            self._next_grammar(m, after)
            return
        self.mode = "spelling"
        self.status.set_text("Spelling")
        self.word.set_markup('<span size="large" underline="error">%s</span>' % html.escape(w))
        if self.native:
            sugg = self.win.engine.view.speller.suggestions(w)
        else:
            sugg = docapi.suggestions(w, docapi.doc_locale(m))
        for s in sugg:
            row = Gtk.ListBoxRow()
            row.word = s
            row.add(Gtk.Label(label=s, xalign=0))
            self.sugg.add(row)
        if not sugg:
            row = Gtk.ListBoxRow()
            row.word = None
            row.set_activatable(False)
            row.add(Gtk.Label(label="(No suggestions)", xalign=0))
            self.sugg.add(row)
        self.sugg.show_all()

    def _next_grammar(self, m, after):
        from . import grammar
        if not hasattr(self, "grammar_ignored"):
            self.grammar_ignored = set()
        if self.native:
            from .native import docops
            found = docops.next_grammar(self.win, after, self.grammar_ignored)
        else:
            found = grammar.next_issue(m, after, self.grammar_ignored)
        if found is None:
            self.mode = "spelling"
            self.current = None
            self.word.set_text("")
            self.status.set_text("Spelling and grammar check is complete. You're good to go!")
            self._readability(m)
            return
        msg, sugg, orig, key = found
        self.current = orig
        self._gkey = key
        self.status.set_text("Grammar: " + msg)
        self.word.set_markup('<span size="large" underline="double" underline_color="#2e6b3f">'
                             '%s</span>' % html.escape(orig))
        for s in sugg or []:
            row = Gtk.ListBoxRow()
            row.word = s
            row.add(Gtk.Label(label=s, xalign=0))
            self.sugg.add(row)
        if not sugg:
            row = Gtk.ListBoxRow()
            row.word = None
            row.set_activatable(False)
            row.add(Gtk.Label(label="(No suggestions)", xalign=0))
            self.sugg.add(row)
        self.sugg.show_all()

    def _readability(self, m):
        if not self.win.app.settings.get("readability", True):
            return
        from . import grammar
        try:
            if self.native:
                from .native import docops
                st = docops.readability(self.win)
            else:
                st = grammar.readability(m)
        except Exception as e:
            print("readability:", e)
            return
        row = Gtk.ListBoxRow()
        row.word = None
        row.set_activatable(False)
        g = Gtk.Grid(column_spacing=12, row_spacing=2)
        g.attach(Gtk.Label(label="Readability Statistics", xalign=0), 0, 0, 2, 1)
        for i, (k, v) in enumerate(st.items(), start=1):
            g.attach(Gtk.Label(label=k, xalign=0), 0, i, 1, 1)
            g.attach(Gtk.Label(label=str(v), xalign=1), 1, i, 1, 1)
        row.add(g)
        self.sugg.add(row)
        self.sugg.show_all()

    def change(self, word):
        if word is None or (self.model is None and not self.native):
            return
        if self.native:
            from .native import docops
            docops.replace_selection(self.win, word)
        else:
            docapi.replace_selection_text(self.model, word)
        self.next()

    def change_all(self):
        rows = self.sugg.get_children()
        if not rows or self.current is None or getattr(rows[0], "word", None) is None:
            return
        if self.native:
            from .native import docops
            docops.replace_all(self.win, self.current, rows[0].word)
            self.next()
            return
        m = self.model
        sd = m.createReplaceDescriptor()
        sd.SearchString = self.current
        sd.SearchWords = True
        sd.SearchCaseSensitive = True
        sd.ReplaceString = rows[0].word
        m.replaceAll(sd)
        self.next()

    def ignore_once(self):
        if getattr(self, "mode", "") == "grammar" and getattr(self, "_gkey", None):
            if not hasattr(self, "grammar_ignored"):
                self.grammar_ignored = set()
            self.grammar_ignored.add(self._gkey)
        self.next()

    def ignore_all(self):
        if self.current:
            self.win.ignored_words.add(self.current)
            if self.native:
                sp = self.win.engine.view.speller
                sp.cache.clear()
                sp.invalidate()
            else:
                docapi.ignore_all(self.current)
        self.next()

    def add(self):
        if self.current:
            if self.native:
                from .native import spell
                spell.add_to_dictionary(self.current)
                sp = self.win.engine.view.speller
                sp.cache.clear()
                sp.invalidate()
            else:
                docapi.add_to_dictionary(self.current)
        self.next()


# ======================================================================
class ThesaurusPane(Pane):
    TITLE = "Thesaurus"

    def __init__(self, win):
        Pane.__init__(self, win)
        self.entry = Gtk.SearchEntry()
        self.entry.connect("activate", lambda *_: self.lookup(self.entry.get_text()))
        self.pack_start(self.entry, False, False, 0)
        self.store = Gtk.TreeStore(str, str)
        self.tv = Gtk.TreeView(model=self.store)
        self.tv.set_headers_visible(False)
        self.tv.append_column(Gtk.TreeViewColumn("", Gtk.CellRendererText(), markup=0))
        self.tv.connect("row-activated", self._activated)
        self.tv.connect("button-press-event", self._button)
        sw = Gtk.ScrolledWindow()
        sw.add(self.tv)
        self.pack_start(sw, True, True, 0)
        hint = Gtk.Label(label="Double-click a word to look it up. Right-click to insert it.",
                         xalign=0)
        hint.set_line_wrap(True)
        hint.get_style_context().add_class("dim-label")
        self.pack_start(hint, False, False, 0)

    def lookup_selection(self):
        if getattr(self.win.engine, "native", False):
            from .native import docops
            self.lookup(docops.select_word_at_caret(self.win))
            return
        m = self.model
        if m is None:
            return
        vc = docapi.view_cursor(m)
        word = vc.getString().strip()
        if not word:
            c = vc.getText().createTextCursorByRange(vc)
            c.gotoStartOfWord(False)
            c.gotoEndOfWord(True)
            word = c.getString().strip()
            if word:
                docapi.select(m, c)
        self.lookup(word)

    def lookup(self, word):
        self.entry.set_text(word or "")
        self.store.clear()
        native = getattr(self.win.engine, "native", False)
        if not word or (self.model is None and not native):
            return
        if native:
            from .native import docops
            res = docops.synonyms(word)
        else:
            res = docapi.synonyms(word, docapi.doc_locale(self.model))
        if not res:
            self.store.append(None, ["<i>No results found.</i>", ""])
            return
        for meaning, syns in res:
            it = self.store.append(None, ["<b>%s</b>" % html.escape(meaning), meaning])
            for s in syns:
                self.store.append(it, [html.escape(s), s])
        self.tv.expand_all()

    def _activated(self, tv, path, col):
        w = self.store[path][1]
        if w:
            self.lookup(w.split(" (")[0])

    def _button(self, tv, ev):
        if ev.button != 3:
            return False
        res = tv.get_path_at_pos(int(ev.x), int(ev.y))
        if not res:
            return True
        w = self.store[res[0]][1].split(" (")[0]
        def insert():
            if getattr(self.win.engine, "native", False):
                from .native import docops
                docops.replace_selection(self.win, w)
            else:
                docapi.replace_selection_text(self.model, w)
        pop = menu_popover(tv, [("Insert", insert),
                                ("Copy", lambda: Gtk.Clipboard.get(
                                    __import__("gi.repository.Gdk", fromlist=["Gdk"]).SELECTION_CLIPBOARD
                                ).set_text(w, -1))])
        pop.set_pointing_to(Gdk_rect(ev))
        pop.popup()
        return True


# ======================================================================
class ClipboardPane(Pane):
    TITLE = "Clipboard"

    def __init__(self, win):
        Pane.__init__(self, win)
        top = Gtk.Box(spacing=6)
        pa = Gtk.Button(label="Paste All")
        ca = Gtk.Button(label="Clear All")
        pa.connect("clicked", lambda *_: [self._paste(t) for t in reversed(win.app.clip_history)])
        ca.connect("clicked", lambda *_: (win.app.clip_history.clear(), self.refresh()))
        top.pack_start(pa, False, False, 0)
        top.pack_start(ca, False, False, 0)
        self.pack_start(top, False, False, 0)
        self.pack_start(Gtk.Label(label="Click an Item to Paste:", xalign=0), False, False, 0)
        self.list = Gtk.ListBox()
        self.list.connect("row-activated", lambda lb, row: self._paste(row.item))
        sw = Gtk.ScrolledWindow()
        sw.add(self.list)
        self.pack_start(sw, True, True, 0)

    def on_shown(self):
        self.refresh()

    def refresh(self):
        for c in self.list.get_children():
            self.list.remove(c)
        for item in self.win.app.clip_history:
            row = Gtk.ListBoxRow()
            row.item = item
            lab = Gtk.Label(label=item[1][:200], xalign=0)
            lab.set_line_wrap(True)
            lab.set_lines(3)
            lab.set_ellipsize(Pango.EllipsizeMode.END)
            lab.set_max_width_chars(34)
            row.add(lab)
            self.list.add(row)
        self.list.show_all()

    def _paste(self, item):
        html_data, text = item
        if html_data:
            self.win.engine.paste_data("text/html", html_data)
        else:
            self.win.engine.paste_data("text/plain;charset=utf-8", text)


# ======================================================================
class CommentsPane(Pane):
    TITLE = "Comments"

    def __init__(self, win):
        Pane.__init__(self, win)
        self.list = Gtk.ListBox()
        self.list.connect("row-activated", self._go)
        sw = Gtk.ScrolledWindow()
        sw.add(self.list)
        self.pack_start(sw, True, True, 0)
        b = Gtk.Button(label="New Comment")
        b.connect("clicked", lambda *_: (win.dialogs.comment(), self.refresh()))
        self.pack_start(b, False, False, 0)

    def on_shown(self):
        self.refresh()

    def refresh(self):
        for c in self.list.get_children():
            self.list.remove(c)
        m = self.model
        if m is None:
            return
        cs = docapi.comments(m)
        if not cs:
            lab = Gtk.Label(label="There are no comments in this document.")
            lab.get_style_context().add_class("dim-label")
            self.list.add(lab)
        for c in cs:
            row = Gtk.ListBoxRow()
            row.field = c["field"]
            row.comment_id = c.get("id")
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            box.set_border_width(6)
            a = Gtk.Label(xalign=0)
            a.set_markup("<b>%s</b>" % html.escape(c["author"] or "Author"))
            t = Gtk.Label(label=c["text"], xalign=0)
            t.set_line_wrap(True)
            t.set_max_width_chars(34)
            box.pack_start(a, False, False, 0)
            box.pack_start(t, False, False, 0)
            row.add(box)
            row.get_style_context().add_class("folio-comment-card")
            self.list.add(row)
        self.list.show_all()

    def _go(self, lb, row):
        f = getattr(row, "field", None)
        if f is not None:
            docapi.goto(self.model, f.getAnchor().getStart())


class ReviewingPane(Pane):
    """Reviewing Pane: every tracked change and comment, newest edits first
    in document order, with Accept / Reject."""
    TITLE = "Revisions"

    def __init__(self, win):
        Pane.__init__(self, win)
        self.summary = Gtk.Label(xalign=0)
        self.summary.get_style_context().add_class("dim-label")
        self.pack_start(self.summary, False, False, 0)
        self.list = Gtk.ListBox()
        self.list.connect("row-activated", self._go)
        sw = Gtk.ScrolledWindow()
        sw.add(self.list)
        self.pack_start(sw, True, True, 0)
        bar = Gtk.Box(spacing=4)
        for label, fn in (("Accept", self._accept), ("Reject", self._reject),
                          ("Refresh", self.refresh)):
            b = Gtk.Button(label=label)
            b.connect("clicked", lambda _b, fn=fn: fn())
            bar.pack_start(b, True, True, 0)
        self.pack_start(bar, False, False, 0)

    def on_shown(self):
        self.refresh()

    def refresh(self):
        for c in self.list.get_children():
            self.list.remove(c)
        m = self.model
        eng = self.win.engine
        native = getattr(eng, "native", False)
        if m is None and not native:
            return
        if native:
            from .native import review as NR
            rs = NR.pane_changes(eng) if eng.ed else []
            cs = [{"author": c["author"], "text": c["text"], "field": None, "id": c["id"]}
                  for c in (eng.ed.comments() if eng.ed else []) if c["anchor"] is not None]
        else:
            rs = docapi.redlines(m)
            cs = docapi.comments(m)
        ins = sum(1 for r in rs if r["type"].startswith("Insert"))
        dels = sum(1 for r in rs if r["type"].startswith("Delet"))
        self.summary.set_text("%d revision%s  (%d insertion%s, %d deletion%s, %d comment%s)" % (
            len(rs), "" if len(rs) == 1 else "s", ins, "" if ins == 1 else "s",
            dels, "" if dels == 1 else "s", len(cs), "" if len(cs) == 1 else "s"))
        for r in rs:
            row = Gtk.ListBoxRow()
            row.redline = r
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            box.set_border_width(6)
            head = Gtk.Label(xalign=0)
            head.set_markup("<b>%s</b> %s" % (html.escape(r["author"] or "Author"),
                                              html.escape(r["type"])))
            when = Gtk.Label(label=r["date"], xalign=0)
            when.get_style_context().add_class("dim-label")
            body = Gtk.Label(xalign=0)
            t = html.escape((r["text"] or "")[:200])
            if r["type"].startswith("Delet"):
                body.set_markup("<span strikethrough='true' foreground='#c00000'>%s</span>" % t)
            elif r["type"].startswith("Insert"):
                body.set_markup("<span underline='single' foreground='#2e6b3f'>%s</span>" % t)
            else:
                body.set_text(r["text"][:200])
            body.set_line_wrap(True)
            body.set_max_width_chars(34)
            for w in (head, when, body):
                box.pack_start(w, False, False, 0)
            row.add(box)
            self.list.add(row)
        for c in cs:
            row = Gtk.ListBoxRow()
            row.field = c["field"]
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            box.set_border_width(6)
            head = Gtk.Label(xalign=0)
            head.set_markup("<b>%s</b> Commented" % html.escape(c["author"] or "Author"))
            t = Gtk.Label(label=c["text"], xalign=0)
            t.set_line_wrap(True)
            t.set_max_width_chars(34)
            box.pack_start(head, False, False, 0)
            box.pack_start(t, False, False, 0)
            row.add(box)
            self.list.add(row)
        if not rs and not cs:
            lab = Gtk.Label(label="No revisions or comments.")
            lab.get_style_context().add_class("dim-label")
            self.list.add(lab)
        self.list.show_all()

    def _go(self, lb, row):
        m = self.model
        eng = self.win.engine
        if getattr(eng, "native", False):
            r = getattr(row, "redline", None)
            if r is not None and r.get("para") is not None:
                eng.ed.select_range(r["para"], r["start"], r["para"], r["end"])
                eng.view.after_move()
            return
        if getattr(row, "redline", None) is not None:
            docapi.select_range(m, row.redline["start"], row.redline["end"])
        elif getattr(row, "field", None) is not None:
            docapi.goto(m, row.field.getAnchor().getStart())

    def _act(self, cmd):
        row = self.list.get_selected_row()
        if row is not None and getattr(row, "redline", None) is not None:
            self._go(self.list, row)
        self.win.engine.command(cmd)
        self.win.engine.sync(self.refresh)

    def _accept(self):
        self._act(".uno:AcceptTrackedChange")

    def _reject(self):
        self._act(".uno:RejectTrackedChange")


class AltTextPane(Pane):
    """Alt Text: a description of the selected picture or shape for people who
    can't see it."""
    TITLE = "Alt Text"

    def __init__(self, win):
        Pane.__init__(self, win)
        lab = Gtk.Label(xalign=0)
        lab.set_markup("How would you describe this object and its context to someone "
                       "who is blind or low vision?")
        lab.set_line_wrap(True)
        lab.set_max_width_chars(36)
        self.pack_start(lab, False, False, 0)
        self.view = Gtk.TextView()
        self.view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.view.set_size_request(-1, 120)
        frame = Gtk.Frame()
        frame.add(self.view)
        self.pack_start(frame, False, False, 0)
        hint = Gtk.Label(label="(1-2 sentences recommended)", xalign=0)
        hint.get_style_context().add_class("dim-label")
        self.pack_start(hint, False, False, 0)
        self.decorative = Gtk.CheckButton(label="Mark as decorative")
        self.pack_start(self.decorative, False, False, 0)
        self.view.get_buffer().connect("changed", lambda *_: self._save())
        self.decorative.connect("toggled", lambda *_: self._save())
        self._loading = False
        self.obj = None

    def on_shown(self):
        from . import drawing
        m = self.model
        self.obj = drawing.selected_shape(m) if m is not None else None
        self._loading = True
        self.view.get_buffer().set_text(drawing.alt_text(self.obj) if self.obj else "")
        try:
            self.decorative.set_active(bool(getattr(self.obj, "Decorative", False)))
        except Exception:
            self.decorative.set_active(False)
        self.view.set_sensitive(self.obj is not None and not self.decorative.get_active())
        self._loading = False

    def _save(self):
        if self._loading or self.obj is None:
            return
        from . import drawing
        b = self.view.get_buffer()
        text = b.get_text(b.get_start_iter(), b.get_end_iter(), False)
        try:
            drawing.set_alt_text(self.obj, text, self.decorative.get_active())
        except Exception as e:
            print("alt text:", e)
        self.view.set_sensitive(not self.decorative.get_active())
