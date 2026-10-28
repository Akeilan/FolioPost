"""Dialogs, popovers and menus. Dialogs is the one object the window talks
to; its methods are named after the actions that open them."""
import os

from gi.repository import Gdk, GLib, Gtk, Pango

from . import APP_NAME, VERSION, docapi
from .widgets import FDialog
from .dlg_text import TextDialogs
from .dlg_doc import DocDialogs
from .dlg_insert import InsertDialogs
from .dlg_table import TableDialogs

SAVE_TYPES = [
    ("docx", "Document (*.docx)"),
    ("docm", None),
    ("dotx", "Document Template (*.dotx)"),
    ("doc", "Document 97-2003 (*.doc)"),
    ("odt", "OpenDocument Text (*.odt)"),
    ("rtf", "Rich Text Format (*.rtf)"),
    ("txt", "Plain Text (*.txt)"),
    ("pdf", "PDF (*.pdf)"),
    ("html", "Web Page (*.html)"),
    ("epub", "EPUB (*.epub)"),
]
OPEN_PATTERNS = ["*.docx", "*.docm", "*.dotx", "*.dotm", "*.doc", "*.dot", "*.odt", "*.ott",
                 "*.rtf", "*.txt", "*.htm", "*.html", "*.xml", "*.wpd", "*.wps", "*.fodt"]


# dialogs that are the new engine's own (the classic ones need the old engine)
NATIVE_ROUTES = {"word_count": "do_word_count", "toc_dialog": "do_toc_dialog",
                 "line_numbers_dialog": "do_line_numbers", "sort_dialog": "do_sort_dialog",
                 "insert_index": "do_insert_index", "table_of_figures": "do_table_of_figures",
                 "goto": "do_goto"}


class Dialogs(TextDialogs, DocDialogs, InsertDialogs, TableDialogs):
    def __getattribute__(self, name):
        if name in NATIVE_ROUTES:
            win = object.__getattribute__(self, "win")
            if getattr(getattr(win, "engine", None), "native", False):
                acts = getattr(win, "actions", None)
                fn = getattr(type(acts), NATIVE_ROUTES[name], None) if acts is not None else None
                if fn is not None:
                    return lambda *a, **k: fn(acts)
        return object.__getattribute__(self, name)

    def crop(self):
        from .native import arrange
        arrange.crop_dialog(self.win)

    def __init__(self, win):
        self.win = win
        self.last_dir = os.path.expanduser("~/Documents")
        if not os.path.isdir(self.last_dir):
            self.last_dir = os.path.expanduser("~")

    @property
    def eng(self):
        return self.win.engine

    @property
    def model(self):
        eng = self.win.engine
        if getattr(eng, "native", False):
            from .native.uno_model import NativeModel
            return NativeModel(eng)
        return eng.model

    def _model_or_warn(self):
        m = self.model
        if m is None:
            self.message("The document is still opening. Try again in a moment.")
        return m

    # ------------------------------------------------------------ basics
    def message(self, text, title=None, kind="info"):
        d = FDialog(self.win, title or APP_NAME, buttons=(("OK", Gtk.ResponseType.OK),))
        box = Gtk.Box(spacing=14)
        icon = {"info": "dialog-information", "warning": "dialog-warning",
                "error": "dialog-error"}.get(kind, "dialog-information")
        box.pack_start(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.DIALOG), False, False, 0)
        lab = Gtk.Label(label=text, xalign=0)
        lab.set_line_wrap(True)
        lab.set_max_width_chars(60)
        box.pack_start(lab, True, True, 0)
        d.add(box)
        d.ask()
        d.done()

    def confirm(self, text, yes="OK", no="Cancel", title=None):
        d = FDialog(self.win, title or APP_NAME,
                    buttons=((yes, Gtk.ResponseType.YES), (no, Gtk.ResponseType.NO)))
        lab = Gtk.Label(label=text, xalign=0)
        lab.set_line_wrap(True)
        lab.set_max_width_chars(60)
        d.add(lab)
        r = d.ask()
        d.done()
        return r == Gtk.ResponseType.YES

    def ask_text(self, title, label, value=""):
        d = FDialog(self.win, title)
        d.add(Gtk.Label(label=label, xalign=0))
        e = Gtk.Entry(text=value, activates_default=True)
        e.set_width_chars(36)
        d.add(e)
        r = d.ask()
        txt = e.get_text()
        d.done()
        return txt if r == Gtk.ResponseType.OK else None

    def ask_password(self, title, label):
        d = FDialog(self.win, title)
        lab = Gtk.Label(label=label, xalign=0)
        lab.set_line_wrap(True)
        d.add(lab)
        e = Gtk.Entry(visibility=False, activates_default=True)
        e.set_width_chars(30)
        d.add(e)
        r = d.ask()
        pw = e.get_text()
        d.done()
        return pw if r == Gtk.ResponseType.OK and pw else None

    def ask_save(self, name):
        """'save' | 'dont' | 'cancel'"""
        d = Gtk.Dialog(title=APP_NAME, transient_for=self.win, modal=True)
        d.get_style_context().add_class("folio-dialog")
        d.set_resizable(False)
        box = d.get_content_area()
        box.set_border_width(18)
        box.set_spacing(10)
        lab = Gtk.Label(xalign=0)
        lab.set_markup('<span size="large">Want to save your changes to “%s”?</span>'
                       % GLib.markup_escape_text(name))
        box.pack_start(lab, False, False, 0)
        hint = Gtk.Label(label="If you don't save, your changes will be lost.", xalign=0)
        hint.get_style_context().add_class("dim-label")
        box.pack_start(hint, False, False, 0)
        save = d.add_button("Save", 1)
        save.get_style_context().add_class("suggested-action")
        save.get_style_context().add_class("folio-default")
        d.add_button("Don't Save", 2)
        d.add_button("Cancel", 3)
        d.set_default_response(1)
        d.show_all()
        r = d.run()
        d.destroy()
        return {1: "save", 2: "dont"}.get(r, "cancel")

    # ------------------------------------------------------------ files
    def save_file(self, name, fmt=None):
        fmt = fmt or self.eng.format or "docx"
        d = Gtk.FileChooserDialog(title="Save As", transient_for=self.win,
                                  action=Gtk.FileChooserAction.SAVE)
        d.add_button("Cancel", Gtk.ResponseType.CANCEL)
        b = d.add_button("Save", Gtk.ResponseType.ACCEPT)
        b.get_style_context().add_class("suggested-action")
        d.set_default_response(Gtk.ResponseType.ACCEPT)
        d.set_do_overwrite_confirmation(True)
        folder = os.path.dirname(self.eng.path) if self.eng.path and not self.eng.is_new \
            else self.last_dir
        d.set_current_folder(folder)
        filters = {}
        for ext, label in SAVE_TYPES:
            if not label:
                continue
            f = Gtk.FileFilter()
            f.set_name(label)
            f.add_pattern("*." + ext)
            d.add_filter(f)
            filters[ext] = f
            if ext == fmt:
                d.set_filter(f)
        d.set_current_name(name + "." + (fmt if fmt in filters else "docx"))

        def filter_changed(*_):
            f = d.get_filter()
            for ext, ff in filters.items():
                if ff == f:
                    cur = d.get_current_name() or name
                    base = os.path.splitext(cur)[0]
                    d.set_current_name(base + "." + ext)
        d.connect("notify::filter", filter_changed)
        r = d.run()
        path = d.get_filename() if r == Gtk.ResponseType.ACCEPT else None
        chosen = d.get_filter()
        d.destroy()
        if not path:
            return None
        ext = os.path.splitext(path)[1].lower().lstrip(".")
        if ext not in dict(SAVE_TYPES):
            for e, ff in filters.items():
                if ff == chosen:
                    path += "." + e
                    break
        self.last_dir = os.path.dirname(path)
        return path

    def open_file(self):
        d = Gtk.FileChooserDialog(title="Open", transient_for=self.win,
                                  action=Gtk.FileChooserAction.OPEN)
        d.add_button("Cancel", Gtk.ResponseType.CANCEL)
        b = d.add_button("Open", Gtk.ResponseType.ACCEPT)
        b.get_style_context().add_class("suggested-action")
        d.set_default_response(Gtk.ResponseType.ACCEPT)
        d.set_current_folder(self.last_dir)
        f = Gtk.FileFilter()
        f.set_name("All Documents")
        for p in OPEN_PATTERNS:
            f.add_pattern(p)
            f.add_pattern(p.upper())
        d.add_filter(f)
        for label, pats in (("Documents (*.docx)", ["*.docx", "*.docm"]),
                            ("Documents 97-2003 (*.doc)", ["*.doc"]),
                            ("OpenDocument Text (*.odt)", ["*.odt"]),
                            ("Rich Text Format (*.rtf)", ["*.rtf"]),
                            ("Text Files (*.txt)", ["*.txt"]),
                            ("All Files", ["*"])):
            ff = Gtk.FileFilter()
            ff.set_name(label)
            for p in pats:
                ff.add_pattern(p)
            d.add_filter(ff)
        r = d.run()
        path = d.get_filename() if r == Gtk.ResponseType.ACCEPT else None
        d.destroy()
        if path:
            self.last_dir = os.path.dirname(path)
        return path

    def pick_file(self, title, patterns, label="Files"):
        d = Gtk.FileChooserDialog(title=title, transient_for=self.win,
                                  action=Gtk.FileChooserAction.OPEN)
        d.add_button("Cancel", Gtk.ResponseType.CANCEL)
        b = d.add_button("Insert", Gtk.ResponseType.ACCEPT)
        b.get_style_context().add_class("suggested-action")
        d.set_default_response(Gtk.ResponseType.ACCEPT)
        pics = os.path.expanduser("~/Pictures")
        d.set_current_folder(pics if os.path.isdir(pics) else self.last_dir)
        f = Gtk.FileFilter()
        f.set_name(label)
        for p in patterns:
            f.add_pattern(p)
            f.add_pattern(p.upper())
        d.add_filter(f)
        r = d.run()
        path = d.get_filename() if r == Gtk.ResponseType.ACCEPT else None
        d.destroy()
        return path

    def pick_color(self, on_pick, initial=0x000000):
        d = Gtk.ColorChooserDialog(title="Colors", transient_for=self.win)
        rgba = Gdk.RGBA()
        rgba.parse("#%06x" % initial)
        d.set_rgba(rgba)
        d.set_use_alpha(False)
        r = d.run()
        c = d.get_rgba()
        d.destroy()
        if r == Gtk.ResponseType.OK:
            v = (int(round(c.red * 255)) << 16) | (int(round(c.green * 255)) << 8) | \
                int(round(c.blue * 255))
            on_pick(v)

    # ------------------------------------------------------------ paste
    def paste_special(self):
        cb = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        options = []
        if cb.wait_is_target_available(Gdk.Atom.intern("text/html", False)) or \
                self.win.clipboard_owned:
            options.append(("Formatted Text (HTML)", "html"))
        if cb.wait_is_target_available(Gdk.Atom.intern("text/rtf", False)):
            options.append(("Formatted Text (RTF)", "rtf"))
        if cb.wait_is_image_available():
            options.append(("Picture (PNG)", "png"))
        if cb.wait_is_text_available():
            options.append(("Unformatted Text", "text"))
            options.append(("Unformatted Unicode Text", "text"))
        if not options:
            self.message("There's nothing on the clipboard to paste.")
            return
        from . import pastelink
        can_link = pastelink.available(self.win, cb.wait_for_text())
        d = FDialog(self.win, "Paste Special")
        src = pastelink.SOURCE.get("win")
        if self.win.clipboard_owned and src is not None:
            name = src.engine.path or (src.get_title() or "Document").split(" - ")[0]
            d.add(Gtk.Label(label="Source:   Folio Writer Document\n               %s" % name,
                            xalign=0))
        else:
            d.add(Gtk.Label(label="Source:   Unknown", xalign=0))
        row = Gtk.Box(spacing=12)
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        r_paste = Gtk.RadioButton.new_with_mnemonic(None, "_Paste:")
        r_link = Gtk.RadioButton.new_with_mnemonic_from_widget(r_paste, "Paste _link:")
        r_link.set_sensitive(can_link)
        left.pack_start(r_paste, False, False, 0)
        left.pack_start(r_link, False, False, 0)
        row.pack_start(left, False, False, 0)
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        right.pack_start(Gtk.Label(label="As:", xalign=0), False, False, 0)
        sw, tv, store = __import__("folio.widgets", fromlist=["listbox"]).listbox(
            [o[0] for o in options], height=150, width=320,
            on_activate=lambda *_: d.response(Gtk.ResponseType.OK))
        tv.get_selection().select_path(Gtk.TreePath(0))
        right.pack_start(sw, True, True, 0)
        row.pack_start(right, True, True, 0)
        icon_cb = Gtk.CheckButton.new_with_mnemonic("_Display as icon")
        icon_cb.set_sensitive(False)
        icon_cb.set_valign(Gtk.Align.START)
        row.pack_start(icon_cb, False, False, 0)
        d.add(row)
        result = Gtk.Label(xalign=0)
        result.set_line_wrap(True)
        result.set_max_width_chars(50)

        def explain(*_):
            if r_link.get_active():
                result.set_text("Inserts the contents of the clipboard and creates a link to "
                                "the source, so changes there are reflected in your document.")
            else:
                result.set_text("Inserts the contents of the clipboard.")
        r_link.connect("toggled", explain)
        explain()
        fr = Gtk.Frame(label="Result")
        result.set_margin_start(8)
        result.set_margin_end(8)
        result.set_margin_bottom(6)
        fr.add(result)
        d.add(fr)
        r = d.ask()
        model, it = tv.get_selection().get_selected()
        idx = model.get_path(it)[0] if it else 0
        as_link = r_link.get_active()
        d.done()
        if r != Gtk.ResponseType.OK:
            return
        if as_link:
            pastelink.paste(self.win)
            return
        kind = options[idx][1]
        if kind == "html":
            if self.win.clipboard_owned:
                self.eng.command(".uno:Paste")
                return
            sel = cb.wait_for_contents(Gdk.Atom.intern("text/html", False))
            if sel is not None:
                from .actions import _utf8
                self.eng.paste_data("text/html", _utf8(bytes(sel.get_data())))
        elif kind == "rtf":
            sel = cb.wait_for_contents(Gdk.Atom.intern("text/rtf", False))
            if sel is not None:
                self.eng.paste_data("text/rtf", bytes(sel.get_data()))
        elif kind == "png":
            img = cb.wait_for_image()
            ok, buf = img.save_to_bufferv("png", [], [])
            if ok:
                self.eng.paste_data("image/png", bytes(buf))
        else:
            t = cb.wait_for_text()
            if t:
                self.eng.paste_data("text/plain;charset=utf-8", t)

    # ------------------------------------------------------------ context menu
    def context_menu(self, event=None):
        menu = Gtk.Menu()
        menu.get_style_context().add_class("folio-menu")
        run = self.win.run
        has_sel = self.eng.get(".uno:StateWordCount").startswith("Selected")
        in_table = bool(self.eng.get(".uno:StateTableCell"))
        m = self.model
        link = docapi.selected_link(m) if m is not None else ""
        word = ""
        misspelled = None
        ned = getattr(self.eng, "ed", None) if getattr(self.eng, "native", False) else None
        if ned is not None:
            has_sel = ned.has_selection()
            in_table = bool(ned.cell_name())
            if has_sel:
                word = " ".join(ned.selected_text().split())
        if m is not None and ned is None:
            # the engine's table state can lag behind a click; ask the cursor
            try:
                vc = docapi.view_cursor(m)
                in_table = vc.TextTable is not None
                if has_sel:
                    word = " ".join(vc.getString().split())
            except Exception:
                pass
        if m is not None and not has_sel:
            try:
                vc = docapi.view_cursor(m)
                cur = vc.getText().createTextCursorByRange(vc)
                cur.gotoStartOfWord(False)
                cur.gotoEndOfWord(True)
                word = cur.getString().strip()
                if word and docapi.WORD_RE.fullmatch(word):
                    loc = docapi.doc_locale(m)
                    if not docapi.spell_ok(word, loc):
                        misspelled = (cur, docapi.suggestions(word, loc, 6))
            except Exception:
                pass

        def item(label, action, sensitive=True, icon=None):
            mi = Gtk.MenuItem()
            box = Gtk.Box(spacing=8)
            from . import icons
            img = icons.image(icon, 16) if icon else Gtk.Box()
            img.set_size_request(16, 16)
            box.pack_start(img, False, False, 0)
            box.pack_start(Gtk.Label(label=label, xalign=0, use_underline=True), True, True, 0)
            mi.add(box)
            mi.set_sensitive(sensitive)
            mi.connect("activate", lambda *_: GLib.idle_add(
                lambda: (run(action) if not callable(action) else action(), False)[1]))
            menu.append(mi)
            return mi

        def sep():
            menu.append(Gtk.SeparatorMenuItem())

        native_hit = None
        if getattr(self.eng, "native", False) and event is not None:
            view = self.eng.view
            sp = getattr(view, "speller", None)
            try:
                hit = view.page_at(event.x, event.y) if event.window == view.get_window() else None
            except Exception:
                hit = None
            if sp is not None and hit is not None:
                native_hit = sp.at(*hit)
            misspelled = None
        if native_hit is not None:
            from .native import spell
            for it in spell.menu_items(self.win, native_hit):
                if it is None:
                    sep()
                elif it[1] is None:
                    item(it[0], None, sensitive=False)
                else:
                    mi = item(it[0], it[1])
                    if it[0] not in ("Ignore All", "Add to Dictionary"):
                        mi.get_child().get_children()[1].set_markup("<b>%s</b>" % GLib.markup_escape_text(it[0]))
        if misspelled is not None:
            cur, sugg = misspelled
            for s in sugg:
                mi = item(s, lambda s=s, c=cur: (c.setString(s)))
                mi.get_child().get_children()[1].set_markup(
                    "<b>%s</b>" % GLib.markup_escape_text(s))
            if not sugg:
                item("(No Spelling Suggestions)", None, sensitive=False)
            item("Ignore All", lambda w=word: self._ignore_word(w))
            item("Add to Dictionary", lambda w=word: docapi.add_to_dictionary(w))
            sep()
        item("Cu_t", "cut", has_sel, "cmd/sc_cut")
        item("_Copy", "copy", has_sel, "cmd/sc_copy")
        item("Paste Options:", None, False, "cmd/sc_paste")
        pbox = Gtk.MenuItem()
        hb = Gtk.Box(spacing=4)
        hb.set_margin_start(24)
        from . import icons
        for icon, tip, act in (("cmd/sc_paste", "Keep Source Formatting", "paste"),
                               ("cmd/sc_pasteunformatted", "Keep Text Only", "paste-text")):
            b = Gtk.Button()
            b.set_relief(Gtk.ReliefStyle.NONE)
            b.add(icons.image(icon, 16))
            b.set_tooltip_text(tip)
            b.connect("clicked", lambda _b, a=act: (menu.popdown(), run(a)))
            hb.pack_start(b, False, False, 0)
        pbox.add(hb)
        menu.append(pbox)
        sep()
        if in_table:
            sub = Gtk.Menu()
            for label, cmd in (("Insert Columns to the Left", ".uno:InsertColumnsBefore"),
                               ("Insert Columns to the Right", ".uno:InsertColumnsAfter"),
                               ("Insert Rows Above", ".uno:InsertRowsBefore"),
                               ("Insert Rows Below", ".uno:InsertRowsAfter")):
                mi = Gtk.MenuItem(label=label)
                mi.connect("activate", lambda _m, c=cmd: run(c))
                sub.append(mi)
            mi = Gtk.MenuItem(label="Insert")
            mi.set_submenu(sub)
            menu.append(mi)
            sub = Gtk.Menu()
            for label, cmd in (("Delete Columns", ".uno:DeleteColumns"),
                               ("Delete Rows", ".uno:DeleteRows"),
                               ("Delete Table", ".uno:DeleteTable")):
                mi = Gtk.MenuItem(label=label)
                mi.connect("activate", lambda _m, c=cmd: run(c))
                sub.append(mi)
            mi = Gtk.MenuItem(label="Delete Cells")
            mi.set_submenu(sub)
            menu.append(mi)
            item("Merge Cells", ".uno:MergeCells")
            item("Split Cells...", "split-cells")
            item("Table Properties...", "table-properties")
            sep()
        if getattr(self.eng, "native", False):
            from .native import lists as nl
            if nl.in_list(self.win):
                item("Adjust List _Indents...", lambda: nl.adjust_indents(self.win))
                if nl.in_numbered_list(self.win):
                    item("_Restart at 1", lambda: nl.restart_at(self.win, 1))
                    item("_Continue Numbering", lambda: nl.continue_numbering(self.win))
                    item("Set Numbering _Value...", lambda: nl.set_numbering_value(self.win))
                sep()
        else:
            from . import lists
            if m is not None and lists.in_list(m):
                numbered = lists.in_numbered_list(m)
                item("Adjust List _Indents...", lambda: lists.adjust_indents(self.win))
                if numbered:
                    item("_Restart at 1", lambda: lists.restart_at(m, 1))
                    item("_Continue Numbering", lambda: lists.continue_numbering(m))
                    item("Set Numbering _Value...", lambda: lists.set_numbering_value(self.win))
                sep()
        lvl, par = 0, None
        try:
            vc = docapi.read_cursor(m)
            cur = vc.getText().createTextCursorByRange(vc.getStart())
            cur.gotoStartOfParagraph(False)
            cur.gotoEndOfParagraph(True)
            en = cur.createEnumeration()
            par = en.nextElement() if en.hasMoreElements() else None
            lvl = (getattr(par, "OutlineLevel", 0) or 0) if par is not None else 0
        except Exception:
            lvl = 0
        if m is not None and lvl:
            folds = self.win.folds
            mi = Gtk.MenuItem(label="Expand/Collapse")
            sub = Gtk.Menu()
            for label, cb in (
                    ("Expand Heading", lambda: folds.toggle(par, lvl)
                     if folds._is_collapsed(par) is not None else None),
                    ("Collapse Heading", lambda: folds.toggle(par, lvl)
                     if folds._is_collapsed(par) is None else None),
                    ("Expand All Headings", folds.expand_all),
                    ("Collapse All Headings", folds.collapse_all)):
                si = Gtk.MenuItem(label=label)
                si.connect("activate", lambda _i, cb=cb: GLib.idle_add(lambda: (cb(), False)[1]))
                sub.append(si)
            mi.set_submenu(sub)
            menu.append(mi)
            sep()
        from . import pastelink
        if m is not None and pastelink.section_at_cursor(m) is not None:
            item("Update _Link", lambda: pastelink.update(self.win), True,
                 "cmd/sc_updatecurindex")
            sep()
        item("_Font...", "font-dialog", True, "cmd/sc_fontdialog")
        item("_Paragraph...", "paragraph-dialog", True, "cmd/sc_paragraphdialog")
        sep()
        if word or has_sel:
            shown = (word or "selection").replace("_", "__")
            shown = shown[:24] + ("…" if len(shown) > 24 else "")
            item("_Search “%s”" % shown,
                 lambda: self.find_pane(word or None), True, "cmd/sc_recsearch")
            item("S_ynonyms", "thesaurus", True, "cmd/sc_thesaurusdialog")
        if link:
            item("_Edit Link...", "hyperlink", True, "cmd/sc_hyperlinkdialog")
            item("_Open Link", lambda: Gtk.show_uri_on_window(self.win, link,
                                                              Gtk.get_current_event_time()))
            item("Copy Link", lambda: Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(link, -1))
            item("_Remove Link", lambda: docapi.remove_link(self.model), True,
                 "cmd/sc_removehyperlink")
        else:
            item("L_ink", "hyperlink", True, "cmd/sc_hyperlinkdialog")
        try:
            from . import citations
            if self.eng.model is not None and citations.citation_at_cursor(self.eng.model):
                from . import dlg_cite
                menu.append(Gtk.SeparatorMenuItem())
                ci = Gtk.MenuItem.new_with_mnemonic("Edit _Citation...")
                ci.connect("activate", lambda *_: dlg_cite.edit_citation(self.win))
                menu.append(ci)
                cs = Gtk.MenuItem.new_with_mnemonic("Edit _Source...")

                def edit_src(*_):
                    m = self.eng.model
                    tag, _o = citations.citation_info(m, citations.citation_at_cursor(m))
                    src = [x for x in citations.doc_sources(m) if x.get("tag") == tag]
                    if src:
                        out = dlg_cite.source_dialog(self.win, src[0], "Edit Source")
                        if out:
                            citations.add_source(m, out)
                cs.connect("activate", edit_src)
                menu.append(cs)
        except Exception as e:
            print("citation menu:", e)
        item("_New Comment", "comment", True, "cmd/sc_insertannotation")
        menu.show_all()
        menu.attach_to_widget(self.eng.view, None)
        if event is not None:
            menu.popup_at_pointer(event)
        else:
            # Shift+F10 / Menu key: open at the text cursor
            from gi.repository import Gdk
            rect = Gdk.Rectangle()
            cur = getattr(self.win.paste_options, "cursor", None)
            if cur:
                px, py = self.eng.twips_to_px(cur[0], cur[1] + cur[3])
                rect.x, rect.y = int(px), int(py)
            else:
                rect.x, rect.y = 100, 100
            rect.width = rect.height = 1
            menu.popup_at_rect(self.eng.view.get_window(), rect, Gdk.Gravity.NORTH_WEST,
                               Gdk.Gravity.NORTH_WEST, None)

    def _ignore_word(self, w):
        self.win.ignored_words.add(w)
        docapi.ignore_all(w)

    # ------------------------------------------------------------ search box
    def autocorrect_options(self, tab=0):
        from . import options
        options.autocorrect_options(self.win, tab)

    def command_search(self, text):
        text = text.strip().lower()
        if not text:
            return
        hits = []
        seen = set()
        for c in self.win.ribbon.all_controls():
            label = (getattr(c, "label_text", "") or "").replace("\n", " ").replace("_", "")
            tip = getattr(c, "tooltip_text", "") or ""
            hay = (label + " " + tip).lower()
            if text in hay and label and label not in seen:
                seen.add(label)
                hits.append((label, c))
        pop = Gtk.Popover.new(self.win.search)
        pop.set_position(Gtk.PositionType.BOTTOM)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.set_margin_top(6)
        box.set_margin_bottom(6)
        head = Gtk.Label(xalign=0)
        head.set_markup("<b>Actions</b>")
        head.set_margin_start(10)
        box.pack_start(head, False, False, 2)
        for label, c in hits[:10]:
            b = Gtk.Button(label=label)
            b.set_relief(Gtk.ReliefStyle.NONE)
            b.get_child().set_xalign(0)
            b.connect("clicked", lambda _b, c=c: (pop.popdown(), c.press()))
            box.pack_start(b, False, False, 0)
        if not hits:
            box.pack_start(Gtk.Label(label="No actions match “%s”" % text), False, False, 6)
        sep = Gtk.Separator()
        box.pack_start(sep, False, False, 4)
        fb = Gtk.Button(label="Find “%s” in Document" % text)
        fb.set_relief(Gtk.ReliefStyle.NONE)
        fb.get_child().set_xalign(0)
        fb.connect("clicked", lambda *_: (pop.popdown(), self.find_pane(text)))
        box.pack_start(fb, False, False, 0)
        hb = Gtk.Button(label="Get Help on “%s”" % text)
        hb.set_relief(Gtk.ReliefStyle.NONE)
        hb.get_child().set_xalign(0)
        hb.connect("clicked", lambda *_: (pop.popdown(), self.help(text)))
        box.pack_start(hb, False, False, 0)
        box.show_all()
        pop.add(box)
        pop.popup()

    # ------------------------------------------------------------ help / about
    def help(self, query=None):
        from .helpwin import HelpWindow
        HelpWindow.show_for(self.win, query)

    def about(self):
        d = FDialog(self.win, "About " + APP_NAME, buttons=(("OK", Gtk.ResponseType.OK),))
        from . import icons
        img = icons.image("folio-writer", 64)
        d.add(img)
        t = Gtk.Label()
        t.set_markup('<span size="x-large"><b>%s</b></span>\nVersion %s' % (APP_NAME, VERSION))
        t.set_justify(Gtk.Justification.CENTER)
        d.add(t)
        info = Gtk.Label(label="A word processor for the Linux desktop.\n\n"
                               "Built on open-source components; their licenses and notices\n"
                               "are in /usr/share/doc/folio-writer/copyright.")
        info.set_justify(Gtk.Justification.CENTER)
        info.get_style_context().add_class("dim-label")
        d.add(info)
        d.ask()
        d.done()

    # ------------------------------------------------------------ options
    def options(self, page=None):
        from .options import OptionsDialog
        OptionsDialog(self.win).run_dialog(page)
