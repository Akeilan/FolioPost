"""Find and Replace, Go To, and the Navigation pane's search with the new
engine: the search runs in folio_core (plain text with ^ codes, or the
original's wildcards)."""
import html

from gi.repository import GLib, Gtk

from ..widgets import grid, heading, listbox, list_selected

SPECIAL = [("Paragraph Mark", "^p"), ("Tab Character", "^t"), ("Any Character", "^?"),
           ("Any Digit", "^#"), ("Any Letter", "^$"), ("Caret Character", "^^"),
           ("Section Character", "^%"), ("Paragraph Character", "^v"),
           ("Column Break", "^n"), ("Em Dash", "^+"), ("En Dash", "^="),
           ("Manual Line Break", "^l"), ("Manual Page Break", "^m"),
           ("Nonbreaking Hyphen", "^~"), ("Nonbreaking Space", "^s"),
           ("Optional Hyphen", "^-"), ("White Space", "^w")]
SPECIAL_REPLACE = [("Paragraph Mark", "^p"), ("Tab Character", "^t"),
                   ("Caret Character", "^^"), ("Find What Text", "^&"),
                   ("Em Dash", "^+"), ("En Dash", "^="), ("Manual Line Break", "^l"),
                   ("Nonbreaking Hyphen", "^~"), ("Nonbreaking Space", "^s"),
                   ("Optional Hyphen", "^-")]
WILD_SPECIAL = [("Any Character", "?"), ("Character in Range", "[-]"),
                ("Beginning of Word", "<"), ("End of Word", ">"), ("Expression", "()"),
                ("Not", "[!]"), ("Num Occurrences", "{,}"), ("Previous 1 or More", "@"),
                ("0 or More Characters", "*"), ("Paragraph Mark", "^p"),
                ("Tab Character", "^t")]
GOTO_KINDS = ["Page", "Section", "Line", "Bookmark", "Comment", "Footnote", "Endnote", "Field",
              "Table", "Graphic", "Equation", "Heading"]
NOT_FOUND = "We couldn't find what you were looking for."


def _ed(win):
    return win.engine.ed


def _after_move(win):
    v = win.engine.view
    v.after_move()
    v.scroll_to_caret()


class FindDialog:
    """The Find and Replace window (Find, Replace and Go To tabs)."""

    def __init__(self, win):
        self.win = win
        self.last_focus = "find"
        d = self.dlg = Gtk.Window(title="Find and Replace", transient_for=win)
        d.set_type_hint(1)
        d.set_resizable(False)
        d.get_style_context().add_class("folio-dialog")
        d.connect("delete-event", lambda *_: (d.hide(), True)[1])
        d.connect("key-press-event", self._key)
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        outer.set_border_width(12)
        d.add(outer)
        nb = self.nb = Gtk.Notebook()
        outer.pack_start(nb, True, True, 0)

        def page(with_replace):
            b = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            b.set_border_width(10)
            f = Gtk.ComboBoxText.new_with_entry()
            f.get_child().set_width_chars(40)
            f.get_child().set_activates_default(True)
            rows = [["Fi_nd what:", f]]
            r = None
            if with_replace:
                r = Gtk.ComboBoxText.new_with_entry()
                r.get_child().set_width_chars(40)
                rows.append(["Replace w_ith:", r])
            b.pack_start(grid(rows), False, False, 0)
            return b, f, r
        p_find, self.f1, _ = page(False)
        p_rep, self.f2, self.rep = page(True)
        for a, b in ((self.f1, self.f2), (self.f2, self.f1)):
            a.get_child().connect("changed", lambda e, b=b: b.get_child().get_text() != e.get_text()
                                  and b.get_child().set_text(e.get_text()))
        for w, name in ((self.f1, "find"), (self.f2, "find"), (self.rep, "rep")):
            w.get_child().connect("focus-in-event",
                                  lambda *_a, n=name: setattr(self, "last_focus", n) or False)
        # search options
        opts = self.opts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        opts.set_margin_top(4)
        opts.pack_start(heading("Search Options"), False, False, 0)
        self.direction = Gtk.ComboBoxText()
        for t in ("All", "Down", "Up"):
            self.direction.append_text(t)
        self.direction.set_active(0)
        opts.pack_start(grid([["Search:", self.direction]]), False, False, 0)
        self.checks = {}
        og = Gtk.Grid(column_spacing=40, row_spacing=2)
        left = [("match_case", "Matc_h case"), ("whole_word", "Find whole words onl_y"),
                ("wildcards", "_Use wildcards"), ("sounds", "Sounds li_ke (English)"),
                ("forms", "Find all _word forms (English)")]
        right = [("prefix", "Match prefi_x"), ("suffix", "Match _suffix"),
                 ("ignore_punct", "Ignore punctuation charac_ters"),
                 ("ignore_space", "Ignore _white-space characters")]
        for col, items in enumerate((left, right)):
            for i, (k, label) in enumerate(items):
                cb = Gtk.CheckButton.new_with_mnemonic(label)
                cb.connect("toggled", self._sens)
                self.checks[k] = cb
                og.attach(cb, col, i, 1, 1)
        opts.pack_start(og, False, False, 0)
        special = Gtk.MenuButton(label="Sp_ecial", use_underline=True)
        special.connect("pressed", lambda b: b.set_popup(self._special_menu()))
        special.set_popup(self._special_menu())
        sb = Gtk.Box(spacing=6)
        self.fmt = {"find": {}, "rep": {}}
        fmt_btn = Gtk.MenuButton(label="F_ormat", use_underline=True)
        fm = Gtk.Menu()
        for label, key in (("Bold", "bold"), ("Italic", "italic"), ("Underline", "underline"),
                           ("Highlight", "highlight")):
            it = Gtk.MenuItem(label=label)
            it.connect("activate", lambda _i, key=key: self.toggle_format(key))
            fm.append(it)
        fm.show_all()
        fmt_btn.set_popup(fm)
        self.no_fmt = Gtk.Button(label="No Formatt_ing", use_underline=True)
        self.no_fmt.connect("clicked", lambda *_: self.clear_format())
        self.fmt_lab = Gtk.Label(label="", xalign=0)
        sb.pack_start(fmt_btn, False, False, 0)
        sb.pack_start(special, False, False, 0)
        sb.pack_start(self.no_fmt, False, False, 0)
        opts.pack_start(self.fmt_lab, False, False, 0)
        opts.pack_start(heading("Find"), False, False, 2)
        opts.pack_start(sb, False, False, 4)
        opts.set_no_show_all(True)
        # go to
        p_goto = Gtk.Box(spacing=12)
        p_goto.set_border_width(10)
        sw, self.kinds, _s = listbox(GOTO_KINDS, height=170, width=140)
        self.kinds.get_selection().select_path(Gtk.TreePath(0))
        rbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.what_lab = Gtk.Label(label="Enter page number:", xalign=0)
        self.what = Gtk.ComboBoxText.new_with_entry()
        self.what.get_child().set_width_chars(30)
        self.what.get_child().set_activates_default(True)
        hint = Gtk.Label(label="Enter + and - to move relative to the current location. "
                               "Example: +4 will move forward four items.", xalign=0)
        hint.set_line_wrap(True)
        hint.set_max_width_chars(40)
        hint.get_style_context().add_class("dim-label")
        rbox.pack_start(self.what_lab, False, False, 0)
        rbox.pack_start(self.what, False, False, 0)
        rbox.pack_start(hint, False, False, 0)
        p_goto.pack_start(Gtk.Label(label="G_o to what:", xalign=0, use_underline=True), False,
                          False, 0)
        p_goto.pack_start(sw, False, False, 0)
        p_goto.pack_start(rbox, True, True, 0)
        self.kinds.get_selection().connect("changed", self._kind_changed)
        self.what.get_child().connect("changed", lambda *_: self._buttons())
        nb.append_page(p_find, Gtk.Label(label="Fin_d", use_underline=True))
        nb.append_page(p_rep, Gtk.Label(label="Re_place", use_underline=True))
        nb.append_page(p_goto, Gtk.Label(label="_Go To", use_underline=True))
        # buttons
        bb = Gtk.Box(spacing=6)
        self.more = Gtk.Button(label="_More >>", use_underline=True)
        self.more.connect("clicked", self._toggle_more)
        bb.pack_start(self.more, False, False, 0)
        self.hl_btn = Gtk.MenuButton(label="Reading Highlig_ht", use_underline=True)
        m = Gtk.Menu()
        for label, fn in (("Highlight All", self.highlight_all),
                          ("Clear Highlighting", self.clear_highlight)):
            it = Gtk.MenuItem(label=label)
            it.connect("activate", lambda _i, fn=fn: fn())
            m.append(it)
        m.show_all()
        self.hl_btn.set_popup(m)
        self.in_btn = Gtk.MenuButton(label="Find _In", use_underline=True)
        mi = Gtk.Menu()
        it = Gtk.MenuItem(label="Main Document")
        it.connect("activate", lambda _i: self.find_in())
        mi.append(it)
        mi.show_all()
        self.in_btn.set_popup(mi)
        self.b_rep = Gtk.Button(label="_Replace", use_underline=True)
        self.b_all = Gtk.Button(label="Replace _All", use_underline=True)
        self.b_prev = Gtk.Button(label="Find Pre_vious", use_underline=True)
        self.b_next = Gtk.Button(label="_Find Next", use_underline=True)
        self.b_go = Gtk.Button(label="Go _To", use_underline=True)
        self.b_goprev = Gtk.Button(label="Pre_vious", use_underline=True)
        self.b_goprev.connect("clicked", lambda *_: self.go(step="-1"))
        self.b_close = Gtk.Button(label="Cancel")
        self.b_next.set_can_default(True)
        self.b_go.set_can_default(True)
        self.b_close.connect("clicked", lambda *_: self.dlg.hide())
        self.b_next.connect("clicked", lambda *_: self.find(True))
        self.b_prev.connect("clicked", lambda *_: self.find(False))
        self.b_rep.connect("clicked", lambda *_: self.replace())
        self.b_all.connect("clicked", lambda *_: self.replace_all())
        self.b_go.connect("clicked", lambda *_: self.go())
        bb.pack_end(self.b_close, False, False, 0)
        for w in (self.b_go, self.b_goprev, self.b_next, self.b_prev, self.b_all, self.b_rep, self.in_btn, self.hl_btn):
            bb.pack_end(w, False, False, 0)
        outer.pack_start(bb, False, False, 0)
        outer.pack_start(opts, False, False, 0)
        self.status = Gtk.Label(label="", xalign=0)
        self.status.get_style_context().add_class("dim-label")
        outer.pack_start(self.status, False, False, 0)
        nb.connect("switch-page", lambda *_: GLib.idle_add(self._buttons))
        outer.show_all()

    # ------------------------------------------------------------ widgets
    def _key(self, w, ev):
        from gi.repository import Gdk
        if ev.keyval == Gdk.KEY_Escape:
            self.dlg.hide()
            return True
        return False

    def _sens(self, *_):
        c = self.checks
        wild = c["wildcards"].get_active()
        word = c["sounds"].get_active() or c["forms"].get_active()
        for k in ("prefix", "suffix", "ignore_punct", "ignore_space"):
            c[k].set_sensitive(not wild and not word)
        c["wildcards"].set_sensitive(not word)
        c["sounds"].set_sensitive(not wild and not c["forms"].get_active())
        c["forms"].set_sensitive(not wild and not c["sounds"].get_active())
        c["whole_word"].set_sensitive(not wild and not c["prefix"].get_active()
                                      and not c["suffix"].get_active())

    def _special_menu(self):
        menu = Gtk.Menu()
        rep = self.last_focus == "rep" and self.nb.get_current_page() == 1
        items = SPECIAL_REPLACE if rep else (
            WILD_SPECIAL if self.checks["wildcards"].get_active() else SPECIAL)
        for label, code in items:
            it = Gtk.MenuItem(label=label)
            it.connect("activate", lambda _i, code=code: self._insert_code(code))
            menu.append(it)
        menu.show_all()
        return menu

    def _insert_code(self, code):
        if self.last_focus == "rep" and self.nb.get_current_page() == 1:
            e = self.rep.get_child()
        else:
            e = (self.f2 if self.nb.get_current_page() == 1 else self.f1).get_child()
        pos = e.get_position()
        e.insert_text(code, pos)
        e.set_position(pos + len(code))

    def _toggle_more(self, *_):
        show = not self.opts.get_visible()
        if show:
            self.opts.show_all()
            self.opts.show()
        else:
            self.opts.hide()
        self.more.set_label("<< _Less" if show else "_More >>")

    def _buttons(self):
        p = self.nb.get_current_page()
        self.b_rep.set_visible(p == 1)
        self.b_all.set_visible(p == 1)
        self.b_next.set_visible(p in (0, 1))
        self.b_prev.set_visible(p in (0, 1))
        self.b_go.set_visible(p == 2)
        self.b_goprev.set_visible(p == 2)
        self.hl_btn.set_visible(p == 0)
        self.in_btn.set_visible(p == 0)
        self.more.set_visible(p in (0, 1))
        if p == 2:
            self.opts.hide()
            k = list_selected(self.kinds) or "Page"
            self.b_go.set_label("_Go To" if self.what.get_child().get_text().strip() else "_Next")
            self.b_go.grab_default()
        else:
            if self.more.get_label().startswith("<<"):
                self.opts.show()
            self.b_next.grab_default()
        return False

    def _kind_changed(self, _s):
        k = list_selected(self.kinds) or "Page"
        ed = _ed(self.win)
        self.what.remove_all()
        items = []
        if k == "Bookmark" and ed is not None:
            items = list(ed.bookmark_names())
            self.what_lab.set_text("Enter bookmark name:")
        elif k == "Heading" and ed is not None:
            self.what_lab.set_text("Enter heading number:")
        else:
            self.what_lab.set_text("Enter %s number:" % k.lower())
        for it in items:
            self.what.append_text(it)
        self.what.get_child().set_text(items[0] if items else "")
        self._buttons()

    # ------------------------------------------------------------ actions
    def show(self, tab=0, text=None):
        ed = _ed(self.win)
        if text is None and ed is not None:
            sel = ed.selected_text()
            if sel and "\n" not in sel and len(sel) < 80:
                text = sel
        if text:
            self.f1.get_child().set_text(text)
        self.nb.set_current_page(tab)
        self._buttons()
        self.status.set_text("")
        self.dlg.present()
        e = (self.f1, self.f2, self.what)[tab].get_child()
        e.grab_focus()
        e.select_region(0, -1)

    def query(self):
        return self.f1.get_child().get_text()

    def options(self):
        return {k: (b.get_active() and b.get_sensitive()) for k, b in self.checks.items()}

    def engine_options(self):
        return {k: v for k, v in self.options().items() if k not in ("sounds", "forms")}

    def _remember(self, combo, text):
        if not text:
            return
        model = combo.get_model()
        if any(r[0] == text for r in model):
            return
        combo.prepend_text(text)

    def find(self, forward=True):
        ed = _ed(self.win)
        q = self.query()
        if ed is None or not q:
            return None
        self._remember(self.f1, q)
        self._remember(self.f2, q)
        dirn = self.direction.get_active()
        if dirn == 2:
            forward = False
        if self._own_search():
            return self._find_own(q, forward, dirn == 0)
        try:
            r = ed.find(q, self.engine_options(), forward, dirn == 0)
        except (ValueError, OSError) as e:
            self.win.dialogs.message("The Find What box contains a pattern that isn't "
                                     "valid.\n\n%s" % e, title="Find and Replace")
            return None
        if r is None and dirn != 0:
            if self.win.dialogs.confirm(
                    "We reached the %s of the document. Do you want to continue searching "
                    "at the %s?" % (("end", "beginning") if forward else ("beginning", "end")),
                    yes="Yes", no="No"):
                r = ed.find(q, self.engine_options(), forward, True)
            else:
                return None
        if r is None:
            self.status.set_text("")
            self.win.dialogs.message(NOT_FOUND, title="Find and Replace")
            return None
        self.status.set_text("The search wrapped around the document." if r else "")
        _after_move(self.win)
        return True

    # ------------------------------------------------------------ word matching and formatting
    def _own_search(self):
        o = self.options()
        return o.get("sounds") or o.get("forms") or bool(self.fmt["find"])

    def hits(self, q=None):
        """Every match, done here: Sounds like, word forms, formatting."""
        ed = _ed(self.win)
        q = self.query() if q is None else q
        o = self.options()
        if o.get("sounds") or o.get("forms"):
            out = word_hits(ed, q, "sounds" if o.get("sounds") else "forms")
        else:
            try:
                out = ed.find_all(q, {k: v for k, v in o.items() if k not in ("sounds", "forms")})
            except (ValueError, OSError):
                out = []
        want = self.fmt["find"]
        if want:
            keep = []
            caret = ed.selection_range()
            for h in out:
                ed.select_nodes(h[0], h[1], h[2], h[3])
                st = ed.state() or {}
                if all(bool(st.get(k)) == v for k, v in want.items()):
                    keep.append(h)
            ed.select_nodes(*caret)
            out = keep
        return out

    def _find_own(self, q, forward, wrap):
        ed = _ed(self.win)
        hits = self.hits(q)
        if not hits:
            self.win.dialogs.message(NOT_FOUND, title="Find and Replace")
            return None
        from . import docops
        order = {p: i for i, (p, _t, _l) in enumerate(docops.paragraphs(ed))}
        pa, a, pb, b = ed.selection_range()
        key = lambda h: (order.get(h[0], 0), h[1])  # noqa: E731
        start = (order.get(pa, 0), a)
        if forward:
            nxt = [x for x in hits if (key(x) > start if ed.has_selection() else key(x) >= start)]
            h = nxt[0] if nxt else (hits[0] if wrap else None)
        else:
            prv = [x for x in hits if key(x) < start]
            h = prv[-1] if prv else (hits[-1] if wrap else None)
        if h is None:
            self.win.dialogs.message(NOT_FOUND, title="Find and Replace")
            return None
        ed.select_nodes(h[0], h[1], h[2], h[3])
        _after_move(self.win)
        return True

    def toggle_format(self, key):
        which = "rep" if self.nb.get_current_page() == 1 and self.last_focus == "rep" else "find"
        f = self.fmt[which]
        f[key] = not f.get(key, False)
        self._show_format()

    def clear_format(self):
        which = "rep" if self.nb.get_current_page() == 1 and self.last_focus == "rep" else "find"
        self.fmt[which] = {}
        self._show_format()

    def _show_format(self):
        def words(f):
            return ", ".join(("" if v else "Not ") + k.capitalize() for k, v in f.items())
        parts = []
        if self.fmt["find"]:
            parts.append("Find format: " + words(self.fmt["find"]))
        if self.fmt["rep"]:
            parts.append("Replace format: " + words(self.fmt["rep"]))
        self.fmt_lab.set_text("   ".join(parts))

    def _apply_rep_format(self, ed):
        for key, on in self.fmt["rep"].items():
            cur = bool((ed.state() or {}).get(key))
            if cur == on:
                continue
            if key in ("bold", "italic"):
                ed.toggle("w:b" if key == "bold" else "w:i")
            elif key == "underline":
                ed.set_underline("single" if on else "none")
            elif key == "highlight":
                ed.set_highlight("yellow" if on else "none")

    def find_in(self):
        """Find In > Main Document: every match selected."""
        ed = _ed(self.win)
        hits = self.hits()
        if not hits:
            self.win.dialogs.message(NOT_FOUND, title="Find and Replace")
            return
        ed.select_ranges([(h[0], h[1], h[2], h[3]) for h in hits])
        _after_move(self.win)
        self.status.set_text("%d item%s matching this criteria" % (len(hits), "" if len(hits) == 1 else "s"))

    def replace(self):
        ed = _ed(self.win)
        q = self.query()
        if ed is None or not q:
            return
        rep = self.rep.get_child().get_text()
        self._remember(self.rep, rep)
        try:
            ed.replace_one(q, rep, self.engine_options())
        except (ValueError, OSError) as e:
            self.win.dialogs.message(str(e), title="Find and Replace")
            return
        self.win.engine.view.after_edit()
        _after_move(self.win)

    def replace_all(self):
        ed = _ed(self.win)
        q = self.query()
        if ed is None or not q:
            return
        rep = self.rep.get_child().get_text()
        self._remember(self.rep, rep)
        if self._own_search() or self.fmt["rep"]:
            hits = self.hits(q)
            ed.begin_group("Replace All")
            try:
                for h in reversed(hits):
                    ed.select_nodes(h[0], h[1], h[2], h[3])
                    if rep:
                        new = rep.replace("^&", ed.selected_text())
                        ed.type_text(new)
                        ed.select_nodes(h[0], h[1], h[0], h[1] + len(new))
                    # an empty Replace box with a format: the text stays, the format goes on
                    if self.fmt["rep"]:
                        self._apply_rep_format(ed)
            finally:
                ed.end_group()
            n = len(hits)
            self.win.engine.view.after_edit()
            self.win.dialogs.message("All done. We made %d replacement%s." % (n, "" if n == 1 else "s")
                                     if n else NOT_FOUND, title="Find and Replace")
            return
        try:
            n = ed.replace_all(q, rep, self.engine_options())
        except (ValueError, OSError) as e:
            self.win.dialogs.message(str(e), title="Find and Replace")
            return
        self.win.engine.view.after_edit()
        if n:
            self.win.dialogs.message("All done. We made %d replacement%s." %
                                     (n, "" if n == 1 else "s"), title="Find and Replace")
        else:
            self.win.dialogs.message(NOT_FOUND, title="Find and Replace")

    def highlight_all(self):
        ed = _ed(self.win)
        q = self.query()
        if ed is None or not q:
            return
        try:
            hits = self.hits(q)
        except (ValueError, OSError):
            hits = []
        set_highlights(self.win, hits)
        n = len(hits)
        self.status.set_text("%d item%s highlighted" % (n, "" if n == 1 else "s") if n else "")
        if not n:
            self.win.dialogs.message(NOT_FOUND, title="Find and Replace")

    def clear_highlight(self):
        set_highlights(self.win, [])
        self.status.set_text("")

    def go(self, step=None):
        ed = _ed(self.win)
        if ed is None:
            return
        k = list_selected(self.kinds) or "Page"
        what = step if step is not None else self.what.get_child().get_text().strip()
        if k == "Page" and not what:
            what = "+1"
        if k == "Bookmark" and not what:
            return
        if not ed.goto(k, what):
            self.win.dialogs.message("Folio can't find the %s." % k.lower()
                                     if k != "Bookmark" else
                                     "This bookmark doesn't exist.", title="Find and Replace")
            return
        _after_move(self.win)


def set_highlights(win, hits):
    """Reading Highlight: the matches shaded yellow until cleared."""
    view = win.engine.view
    ed = _ed(win)
    rects = []
    if ed is not None:
        for (pa, a, pb, b, _ctx) in hits[:2000]:
            rects.extend(ed.range_rects(pa, a, pb, b))
    view.highlights = rects
    view.queue_draw()


def dialog(win, tab=0, text=None):
    fd = getattr(win, "_native_find", None)
    if fd is None:
        fd = win._native_find = FindDialog(win)
    fd.show(tab, text)
    return fd


# ---------------------------------------------------------- navigation
def nav_search(pane, text, quiet=False):
    """The Navigation pane's search box: results with context, matches
    highlighted, the first one selected."""
    win = pane.win
    ed = _ed(win)
    pane.rstore.clear()
    pane._ranges = []
    if not text or ed is None:
        pane.rcount.set_text("")
        set_highlights(win, [])
        return
    pane.stack.set_visible_child_name("results")
    try:
        hits = ed.find_all(text, {})
    except (ValueError, OSError):
        hits = []
    for h in hits[:500]:
        pre, rest = h[4].split("\x01", 1)
        mid, post = rest.split("\x02", 1)
        pane._ranges.append(h)
        pane.rstore.append(["%s<b>%s</b>%s" % (html.escape(pre), html.escape(mid),
                                               html.escape(post)), h])
    n = len(hits)
    pane.rcount.set_text("%d result%s" % (n, "" if n == 1 else "s") if n else "No results")
    set_highlights(win, hits)
    pane._pos = -1
    if n and not quiet:
        pane.step(1)


def nav_select(pane, h):
    win = pane.win
    ed = _ed(win)
    if ed is not None and ed.select_nodes(h[0], h[1], h[2], h[3]):
        _after_move(win)


# ---------------------------------------------------------- Sounds like, word forms
def soundex(w):
    w = "".join(c for c in w.upper() if c.isalpha())
    if not w:
        return ""
    codes = {**dict.fromkeys("BFPV", "1"), **dict.fromkeys("CGJKQSXZ", "2"), **dict.fromkeys("DT", "3"),
             "L": "4", **dict.fromkeys("MN", "5"), "R": "6"}
    out = w[0]
    last = codes.get(w[0], "")
    for c in w[1:]:
        d = codes.get(c, "")
        if d and d != last:
            out += d
        if c not in "HW":
            last = d
    return (out + "000")[:4]


IRREGULAR = {
    "ran": "run", "running": "run", "went": "go", "gone": "go", "goes": "go", "was": "be", "were": "be",
    "is": "be", "are": "be", "am": "be", "been": "be", "being": "be", "had": "have", "has": "have",
    "did": "do", "done": "do", "does": "do", "said": "say", "made": "make", "took": "take", "taken": "take",
    "came": "come", "saw": "see", "seen": "see", "knew": "know", "known": "know", "got": "get",
    "gotten": "get", "gave": "give", "given": "give", "found": "find", "thought": "think", "told": "tell",
    "became": "become", "left": "leave", "felt": "feel", "brought": "bring", "began": "begin",
    "begun": "begin", "kept": "keep", "held": "hold", "wrote": "write", "written": "write", "stood": "stand",
    "heard": "hear", "meant": "mean", "met": "meet", "paid": "pay", "sat": "sit", "spoke": "speak",
    "spoken": "speak", "led": "lead", "grew": "grow", "grown": "grow", "lost": "lose", "fell": "fall",
    "fallen": "fall", "sent": "send", "built": "build", "understood": "understand", "drew": "draw",
    "drawn": "draw", "broke": "break", "broken": "break", "spent": "spend", "rose": "rise", "risen": "rise",
    "drove": "drive", "driven": "drive", "bought": "buy", "wore": "wear", "worn": "wear", "chose": "choose",
    "chosen": "choose", "ate": "eat", "eaten": "eat", "flew": "fly", "flown": "fly", "sang": "sing",
    "sung": "sing", "swam": "swim", "swum": "swim", "children": "child", "men": "man", "women": "woman",
    "feet": "foot", "teeth": "tooth", "mice": "mouse", "people": "person",
}


def lemma(w):
    w = w.lower().strip("'’")
    if w in IRREGULAR:
        return IRREGULAR[w]
    for suf, rep in (("ies", "y"), ("ied", "y"), ("ying", "y"), ("ing", ""), ("ed", ""), ("es", ""), ("s", "")):
        if w.endswith(suf) and len(w) - len(suf) >= 2:
            base = w[:len(w) - len(suf)] + rep
            # running -> run, stopped -> stop
            if suf in ("ing", "ed") and len(base) >= 3 and base[-1] == base[-2] and base[-1] not in "lsz":
                base = base[:-1]
            if suf == "es" and not base.endswith(("s", "x", "z", "ch", "sh", "o")):
                base = w[:-1]
            return base
    return w


def word_hits(ed, q, kind):
    """Words like q (Sounds like) or forms of it (Find all word forms)."""
    import re
    from . import docops
    q = q.strip()
    if not q:
        return []
    if kind == "sounds":
        key = soundex(q)
        same = lambda w: soundex(w) == key  # noqa: E731
    else:
        key = lemma(q)
        same = lambda w: lemma(w) == key  # noqa: E731
    out = []
    for p, text, _l in docops.paragraphs(ed):
        for m in re.finditer(r"[A-Za-z][A-Za-z'’]*", text):
            if same(m.group()):
                ctx = text[max(0, m.start() - 30):m.start()] + "\x01" + m.group() + "\x02" + text[m.end():m.end() + 30]
                out.append((p, m.start(), p, m.end(), ctx))
    return out
