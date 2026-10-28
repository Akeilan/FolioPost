"""Insert-tab dialogs and pop-ups: pictures, links, bookmarks, references,
captions, fields, date & time, header/footer, tables, symbols, equations,
table of contents; plus the side panes."""
import datetime
import os
import unicodedata

from gi.repository import Gdk, GLib, Gtk, Pango

from . import bridge, docapi, icons
from .widgets import FDialog, combo, combo_text, grid, heading, list_select, list_selected, listbox

SPECIAL_CHARS = [
    ("—", "Em Dash", "Alt+Ctrl+Num -"), ("–", "En Dash", "Ctrl+Num -"),
    ("‑", "Nonbreaking Hyphen", "Ctrl+Shift+_"), ("­", "Optional Hyphen", "Ctrl+-"),
    (" ", "Em Space", ""), (" ", "En Space", ""), (" ", "1/4 Em Space", ""),
    (" ", "Nonbreaking Space", "Ctrl+Shift+Space"), ("©", "Copyright", "Alt+Ctrl+C"),
    ("®", "Registered", "Alt+Ctrl+R"), ("™", "Trademark", "Alt+Ctrl+T"),
    ("§", "Section", ""), ("¶", "Paragraph", ""), ("…", "Ellipsis", "Alt+Ctrl+."),
    ("‘", "Single Opening Quote", "Ctrl+`,`"), ("’", "Single Closing Quote", "Ctrl+',''"),
    ("“", "Double Opening Quote", "Ctrl+`,\""), ("”", "Double Closing Quote", "Ctrl+',\""),
    ("​", "No-Width Optional Break", ""), ("‍", "No-Width Non Break", ""),
]

COMMON_SYMBOLS = "€£¥©®™±≠≤≥÷×∞µαβπΩ∑√°¢§¶•…–—‘’“”←→↑↓"

UNICODE_BLOCKS = [
    ("Basic Latin", 0x20, 0x7E), ("Latin-1 Supplement", 0xA0, 0xFF),
    ("Latin Extended-A", 0x100, 0x17F), ("Latin Extended-B", 0x180, 0x24F),
    ("Spacing Modifier Letters", 0x2B0, 0x2FF), ("Greek and Coptic", 0x370, 0x3FF),
    ("Cyrillic", 0x400, 0x4FF), ("Hebrew", 0x590, 0x5FF), ("Arabic", 0x600, 0x6FF),
    ("General Punctuation", 0x2000, 0x206F), ("Superscripts and Subscripts", 0x2070, 0x209F),
    ("Currency Symbols", 0x20A0, 0x20CF), ("Letterlike Symbols", 0x2100, 0x214F),
    ("Number Forms", 0x2150, 0x218F), ("Arrows", 0x2190, 0x21FF),
    ("Mathematical Operators", 0x2200, 0x22FF), ("Miscellaneous Technical", 0x2300, 0x23FF),
    ("Box Drawing", 0x2500, 0x257F), ("Block Elements", 0x2580, 0x259F),
    ("Geometric Shapes", 0x25A0, 0x25FF), ("Miscellaneous Symbols", 0x2600, 0x26FF),
    ("Dingbats", 0x2700, 0x27BF), ("Supplemental Arrows-A", 0x27F0, 0x27FF),
    ("Alphabetic Presentation Forms", 0xFB00, 0xFB4F),
]

DATE_FORMATS = [
    ("%-m/%-d/%Y", "M/D/YYYY"), ("%A, %B %-d, %Y", "NNNNMMMM D, YYYY"),
    ("%B %-d, %Y", "MMMM D, YYYY"), ("%-m/%-d/%y", "M/D/YY"), ("%Y-%m-%d", "YYYY-MM-DD"),
    ("%-d-%b-%y", "D-MMM-YY"), ("%-m.%-d.%Y", "M.D.YYYY"), ("%b. %-d, %y", "MMM. D, YY"),
    ("%-d %B %Y", "D MMMM YYYY"), ("%B %y", "MMMM YY"), ("%b-%y", "MMM-YY"),
    ("%-m/%-d/%Y %-I:%M %p", "M/D/YYYY H:MM AM/PM"),
    ("%-m/%-d/%Y %-I:%M:%S %p", "M/D/YYYY H:MM:SS AM/PM"),
    ("%-I:%M %p", "H:MM AM/PM"), ("%-I:%M:%S %p", "H:MM:SS AM/PM"), ("%H:%M", "HH:MM"),
    ("%H:%M:%S", "HH:MM:SS"),
]

# the same formats as Word date pictures (\@ switch)
WORD_DATE_PICTURES = [
    "M/d/yyyy", "dddd, MMMM d, yyyy", "MMMM d, yyyy", "M/d/yy", "yyyy-MM-dd", "d-MMM-yy",
    "M.d.yyyy", "MMM. d, yy", "d MMMM yyyy", "MMMM yy", "MMM-yy", "M/d/yyyy h:mm AM/PM",
    "M/d/yyyy h:mm:ss AM/PM", "h:mm AM/PM", "h:mm:ss AM/PM", "HH:mm", "HH:mm:ss"]

FIELDS = [("Author", "author", "The name of the document's author"),
          ("CreateDate", "created", "The date the document was created"),
          ("Date", "date", "Today's date"),
          ("FileName", "filename", "The document's name"),
          ("NumPages", "pages", "The number of pages in the document"),
          ("NumWords", "words", "The number of words in the document"),
          ("Page", "page", "The number of the current page"),
          ("SaveDate", "saved", "The date the document was last saved"),
          ("Subject", "subject", "The document's subject"),
          ("Time", "time", "The current time"),
          ("Title", "title", "The document's title")]


class InsertDialogs:
    # ============================================================ pictures
    def insert_picture(self):
        path = self.pick_file("Insert Picture", ["*.png", "*.jpg", "*.jpeg", "*.gif", "*.bmp",
                                                 "*.svg", "*.tif", "*.tiff", "*.webp", "*.emf",
                                                 "*.wmf"], "All Pictures")
        if path:
            m = self._model_or_warn()
            if m is None:
                return
            try:
                docapi.insert_picture(m, path)
                from . import captions
                captions.after_insert(self.win, "picture")
                self.win.update_object_tabs()
                self.win.select_tab("Picture Format")
            except Exception as e:
                self.message("This picture couldn't be inserted. (%s)" % e, kind="error")

    # ============================================================ links
    def hyperlink(self):
        m = self._model_or_warn()
        if m is None:
            return
        if getattr(self.win, "native", False):
            from .native.links import LinkApi
            api = LinkApi(self.win)
        else:
            api = docapi
        vc = api.view_cursor(m)
        cur_url = api.selected_link(m)
        sel = vc.getString() if not vc.isCollapsed() else ""
        d = FDialog(self.win, "Edit Hyperlink" if cur_url else "Insert Hyperlink")
        text = Gtk.Entry(text=sel)
        text.set_width_chars(46)
        if sel and "\n" in sel:
            text.set_text("<<Selection in Document>>")
            text.set_sensitive(False)
        tip_btn = Gtk.Button(label="ScreenTi_p...", use_underline=True)
        tip = [""]
        tip_btn.connect("clicked", lambda *_: tip.__setitem__(
            0, self.ask_text("Set Hyperlink ScreenTip", "ScreenTip text:", tip[0]) or tip[0]))
        top = Gtk.Box(spacing=8)
        top.pack_start(Gtk.Label(label="_Text to display:", use_underline=True), False, False, 0)
        top.pack_start(text, True, True, 0)
        top.pack_start(tip_btn, False, False, 0)
        d.add(top)
        body = Gtk.Box(spacing=8)
        side = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        side.get_style_context().add_class("folio-linkbar")
        stack = Gtk.Stack()
        kinds = [("web", "Existing File\nor Web Page", "cmd/lc_hyperlinkdialog"),
                 ("place", "Place in This\nDocument", "cmd/lc_insertbookmark"),
                 ("new", "Create New\nDocument", "cmd/lc_adddirect"),
                 ("mail", "E-mail\nAddress", "cmd/lc_sendmail")]
        grp = None
        rbs = {}
        for key, label, icon in kinds:
            rb = Gtk.RadioButton.new_from_widget(grp)
            rb.set_mode(False)
            grp = grp or rb
            inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            inner.pack_start(icons.image(icon, 32), False, False, 0)
            lab = Gtk.Label(label=label)
            lab.set_justify(Gtk.Justification.CENTER)
            inner.pack_start(lab, False, False, 0)
            rb.add(inner)
            rb.connect("toggled", lambda w, k=key: w.get_active() and stack.set_visible_child_name(k))
            rbs[key] = rb
            side.pack_start(rb, False, False, 0)
        body.pack_start(side, False, False, 0)
        # web / file
        web = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        addr = Gtk.Entry(text=cur_url if cur_url and not cur_url.startswith(("#", "mailto:")) else "")
        addr.set_width_chars(46)
        addr.set_activates_default(True)
        browse = Gtk.Button(label="Browse for File...")

        def pick(*_):
            dd = Gtk.FileChooserDialog(title="Link to File", transient_for=d,
                                       action=Gtk.FileChooserAction.OPEN)
            dd.add_button("Cancel", Gtk.ResponseType.CANCEL)
            dd.add_button("OK", Gtk.ResponseType.ACCEPT)
            if dd.run() == Gtk.ResponseType.ACCEPT:
                addr.set_text("file://" + dd.get_filename())
                if not text.get_text():
                    text.set_text(os.path.basename(dd.get_filename()))
            dd.destroy()
        browse.connect("clicked", pick)
        recent = Gtk.ListStore(str)
        for p in self.win.app.recent()[:12]:
            recent.append([p])
        rtv = Gtk.TreeView(model=recent)
        rtv.set_headers_visible(False)
        rtv.append_column(Gtk.TreeViewColumn("", Gtk.CellRendererText(), text=0))
        rtv.get_selection().connect("changed", lambda s: (
            lambda r: r and addr.set_text("file://" + r))(list_selected(rtv)))
        rsw = Gtk.ScrolledWindow()
        rsw.set_size_request(380, 150)
        rsw.set_shadow_type(Gtk.ShadowType.IN)
        rsw.add(rtv)
        web.pack_start(Gtk.Label(label="Recent Files:", xalign=0), False, False, 0)
        web.pack_start(rsw, True, True, 0)
        web.pack_start(grid([["Addr_ess:", addr, browse]]), False, False, 0)
        wbb = Gtk.Box(spacing=6)
        wbb.set_halign(Gtk.Align.END)
        bm_btn = Gtk.Button(label="Boo_kmark...", use_underline=True)
        tf_btn = Gtk.Button(label="Tar_get Frame...", use_underline=True)
        wbb.pack_start(bm_btn, False, False, 0)
        wbb.pack_start(tf_btn, False, False, 0)
        web.pack_start(wbb, False, False, 0)
        target = [self.win.app.settings.get("link_target", "")]
        try:
            if cur_url:
                target[0] = vc.HyperLinkTarget or target[0]
        except Exception:
            pass

        def pick_bookmark(*_):
            names = api.bookmarks(m)
            dd = FDialog(d, "Select Place in Document")
            dd.add(Gtk.Label(label="Select an existing place in the document:", xalign=0))
            bsw, btv, _bs = listbox(["Top of the Document"] + names, height=180, width=300)
            dd.add(bsw)
            if dd.ask() == Gtk.ResponseType.OK:
                n = list_selected(btv)
                if n:
                    base = addr.get_text().split("#")[0]
                    addr.set_text(base + "#" + ("top" if n == "Top of the Document" else n))
            dd.destroy()

        def pick_target(*_):
            frames = [("Page Default (none)", ""), ("Same frame", "_self"),
                      ("Whole page", "_top"), ("New window", "_blank"),
                      ("Parent frame", "_parent")]
            dd = FDialog(d, "Set Target Frame")
            dd.add(Gtk.Label(label="Select the frame where you want the document to appear:",
                             xalign=0))
            cb = combo([n for n, _v in frames],
                       next((i for i, (_n, v) in enumerate(frames) if v == target[0]), 0))
            dd.add(cb)
            setdef = Gtk.CheckButton.new_with_mnemonic("_Set as default for all hyperlinks")
            dd.add(setdef)
            if dd.ask() == Gtk.ResponseType.OK:
                target[0] = frames[max(0, cb.get_active())][1]
                if setdef.get_active():
                    self.win.app.settings["link_target"] = target[0]
                    self.win.app.save_settings()
            dd.destroy()
        bm_btn.connect("clicked", pick_bookmark)
        tf_btn.connect("clicked", pick_target)
        stack.add_named(web, "web")
        # create new document
        newdoc = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        nd_name = Gtk.Entry()
        nd_name.set_width_chars(40)
        folder = [os.path.dirname(self.win.engine.path) if self.win.engine.path
                  else os.path.expanduser("~/Documents") if
                  os.path.isdir(os.path.expanduser("~/Documents")) else os.path.expanduser("~")]
        full = Gtk.Label(xalign=0)
        full.get_style_context().add_class("dim-label")

        def show_full(*_):
            n = nd_name.get_text().strip()
            if n and not n.lower().endswith((".docx", ".doc", ".odt", ".rtf")):
                n += ".docx"
            full.set_text(os.path.join(folder[0], n) if n else folder[0])
        nd_name.connect("changed", show_full)
        change = Gtk.Button(label="_Change...", use_underline=True)

        def pick_folder(*_):
            dd = Gtk.FileChooserDialog(title="Create New Document", transient_for=d,
                                       action=Gtk.FileChooserAction.SELECT_FOLDER)
            dd.add_button("Cancel", Gtk.ResponseType.CANCEL)
            dd.add_button("OK", Gtk.ResponseType.ACCEPT)
            dd.set_current_folder(folder[0])
            if dd.run() == Gtk.ResponseType.ACCEPT:
                folder[0] = dd.get_filename()
                show_full()
            dd.destroy()
        change.connect("clicked", pick_folder)
        newdoc.pack_start(Gtk.Label(label="Name of new _document:", xalign=0,
                                    use_underline=True), False, False, 0)
        newdoc.pack_start(nd_name, False, False, 0)
        fb = Gtk.Box(spacing=8)
        fb.pack_start(Gtk.Label(label="Full path:"), False, False, 0)
        fb.pack_start(full, True, True, 0)
        fb.pack_start(change, False, False, 0)
        newdoc.pack_start(fb, False, False, 0)
        newdoc.pack_start(heading("When to edit"), False, False, 0)
        later = Gtk.RadioButton.new_with_mnemonic(None, "Edit the new document _later")
        now = Gtk.RadioButton.new_with_mnemonic_from_widget(later, "Edit the new document _now")
        now.set_active(True)
        newdoc.pack_start(later, False, False, 0)
        newdoc.pack_start(now, False, False, 0)
        show_full()
        stack.add_named(newdoc, "new")
        # place in document
        place = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        place.pack_start(Gtk.Label(label="Select a place in this document:", xalign=0), False, False, 0)
        pstore = Gtk.TreeStore(str, str)
        top_it = pstore.append(None, ["Top of the Document", "#top"])
        h_it = pstore.append(None, ["Headings", ""])
        for _l, t, _p in api.headings(m):
            pstore.append(h_it, [t, "#" + t + "|outline"])
        b_it = pstore.append(None, ["Bookmarks", ""])
        for b in api.bookmarks(m):
            pstore.append(b_it, [b, "#" + b])
        ptv = Gtk.TreeView(model=pstore)
        ptv.set_headers_visible(False)
        ptv.append_column(Gtk.TreeViewColumn("", Gtk.CellRendererText(), text=0))
        ptv.expand_all()
        psw = Gtk.ScrolledWindow()
        psw.set_size_request(380, 200)
        psw.set_shadow_type(Gtk.ShadowType.IN)
        psw.add(ptv)
        place.pack_start(psw, True, True, 0)
        stack.add_named(place, "place")
        # mail
        mail = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        maddr = Gtk.Entry(text=cur_url[7:].split("?")[0] if cur_url.startswith("mailto:")
                          else "")
        msubj = Gtk.Entry()
        mail.pack_start(grid([["E-_mail address:", maddr], ["_Subject:", msubj]]), False, False, 0)
        mail.pack_start(Gtk.Label(label="Recently used e-mail addresses:", xalign=0),
                        False, False, 0)
        msw, mtv, _ms = listbox(self.win.app.settings.get("recent_mail", []), height=110,
                                width=380)
        mtv.get_selection().connect("changed", lambda *_: list_selected(mtv) and
                                    maddr.set_text(list_selected(mtv)))
        mail.pack_start(msw, True, True, 0)
        stack.add_named(mail, "mail")
        body.pack_start(stack, True, True, 0)
        d.add(body, expand=True)
        remove_btn = None
        if cur_url:
            remove_btn = Gtk.Button(label="_Remove Link", use_underline=True)
            d.get_action_area().pack_start(remove_btn, False, False, 0)
            d.get_action_area().reorder_child(remove_btn, 0)
            remove_btn.connect("clicked", lambda *_: d.response(77))
        d.show_all()
        if cur_url.startswith("#"):
            rbs["place"].set_active(True)
        elif cur_url.startswith("mailto:"):
            rbs["mail"].set_active(True)
        addr.grab_focus()
        r = d.run()
        if r == 77:
            api.remove_link(m)
        elif r == Gtk.ResponseType.OK:
            page = stack.get_visible_child_name()
            if page == "web":
                url = addr.get_text().strip()
                if url and "://" not in url and not url.startswith(("mailto:", "#", "/")):
                    url = "https://" + url if "." in url and " " not in url else url
                if url.startswith("/"):
                    url = "file://" + url
            elif page == "place":
                model, it = ptv.get_selection().get_selected()
                url = model[it][1] if it else ""
            elif page == "new":
                path = full.get_text()
                url = ""
                if nd_name.get_text().strip():
                    if not os.path.exists(path):
                        self._create_blank(path)
                    url = "file://" + path
                    if now.get_active():
                        GLib.idle_add(lambda: (self.win.app.open_path(path)
                                               if hasattr(self.win.app, "open_path")
                                               else self.win.open_file(path), False)[1])
            else:
                url = "mailto:" + maddr.get_text().strip()
                if msubj.get_text().strip():
                    url += "?subject=" + GLib.uri_escape_string(msubj.get_text().strip(), None, True)
                if maddr.get_text().strip():
                    rm = [a for a in self.win.app.settings.get("recent_mail", [])
                          if a != maddr.get_text().strip()]
                    self.win.app.settings["recent_mail"] = [maddr.get_text().strip()] + rm[:9]
            shown = text.get_text() if text.get_sensitive() else None
            if url:
                if shown == "" or shown is None and vc.isCollapsed():
                    shown = addr.get_text() if page == "web" else (
                        maddr.get_text() if page == "mail" else
                        nd_name.get_text().strip() if page == "new" else
                        url.lstrip("#").split("|")[0])
                api.set_link(m, url, shown if text.get_sensitive() else None, tip[0],
                                target[0] if page == "web" else "")
        d.destroy()

    def _create_blank(self, path):
        """An empty document in the format the name asks for."""
        from .engine import file_url
        desktop = bridge.create("com.sun.star.frame.Desktop")
        doc = desktop.loadComponentFromURL("private:factory/swriter", "_blank", 0,
                                           (bridge.prop("Hidden", True),))
        filt = {".odt": "writer8", ".rtf": "Rich Text Format",
                ".doc": "MS Word 97"}.get(os.path.splitext(path)[1].lower(),
                                          "MS Word 2007 XML")
        try:
            doc.storeToURL(file_url(path), (bridge.prop("FilterName", filt),))
        finally:
            doc.close(True)

    # ============================================================ bookmarks
    def bookmark(self):
        m = self._model_or_warn()
        if m is None:
            return
        if getattr(self.win, "native", False):
            from .native.links import LinkApi
            api = LinkApi(self.win)
        else:
            api = docapi
        d = FDialog(self.win, "Bookmark", buttons=(("Add", 1), ("Close", Gtk.ResponseType.CANCEL)))
        name = Gtk.Entry()
        name.set_activates_default(True)
        d.add(Gtk.Label(label="_Bookmark name:", xalign=0, use_underline=True))
        d.add(name)
        sw, tv, store = listbox(api.bookmarks(m), height=160, width=320)
        tv.get_selection().connect("changed", lambda s: name.set_text(list_selected(tv) or name.get_text()))
        d.add(sw)
        sort_name = Gtk.RadioButton.new_with_mnemonic(None, "_Name")
        sort_loc = Gtk.RadioButton.new_with_mnemonic_from_widget(sort_name, "_Location")
        sb = Gtk.Box(spacing=12)
        sb.pack_start(Gtk.Label(label="Sort by:"), False, False, 0)
        sb.pack_start(sort_name, False, False, 0)
        sb.pack_start(sort_loc, False, False, 0)
        d.add(sb)
        hidden = Gtk.CheckButton.new_with_mnemonic("_Hidden bookmarks")
        d.add(hidden)

        def refill(*_):
            names = api.bookmarks(m)
            if hidden.get_active() and getattr(self.eng, "native", False):
                names = list(self.eng.ed.bookmark_names())
            names = [n for n in names if hidden.get_active() or not n.startswith("_")]
            if sort_name.get_active():
                names.sort(key=str.lower)
            store.clear()
            for n in names:
                store.append([n])
        sort_name.connect("toggled", refill)
        hidden.connect("toggled", refill)
        refill()
        bb = Gtk.Box(spacing=6)
        delb = Gtk.Button(label="_Delete", use_underline=True)
        gob = Gtk.Button(label="_Go To", use_underline=True)
        bb.pack_end(gob, False, False, 0)
        bb.pack_end(delb, False, False, 0)
        d.add(bb)
        delb.connect("clicked", lambda *_: (api.delete_bookmark(m, name.get_text()), refill()))
        gob.connect("clicked", lambda *_: api.goto_bookmark(m, name.get_text()))
        name.connect("changed", lambda e: d.buttons[1].set_sensitive(
            bool(e.get_text()) and (e.get_text()[0].isalpha()) and " " not in e.get_text()))
        d.buttons[1].set_sensitive(False)
        if d.ask() == 1:
            api.add_bookmark(m, name.get_text().strip())
        d.done()

    # ====================================================== cross-reference
    def cross_reference(self):
        m = self._model_or_warn()
        if m is None:
            return
        if getattr(self.win, "native", False):
            from .native.links import LinkApi
            api = LinkApi(self.win)
        else:
            api = docapi
        refs = api.references(m)
        types = [k for k in ("Heading", "Bookmark", "Figure", "Table", "Equation") if k in refs] + \
            [k for k in refs if k not in ("Heading", "Bookmark", "Figure", "Table", "Equation")]
        d = FDialog(self.win, "Cross-reference", buttons=(("Insert", Gtk.ResponseType.OK),
                                                          ("Close", Gtk.ResponseType.CANCEL)))
        rtype = combo(types, 0)
        part = combo([], 0)
        d.add(grid([["Reference _type:", "Insert _reference to:"], [rtype, part]]))
        d.add(Gtk.Label(label="F_or which:", xalign=0, use_underline=True))
        store = Gtk.ListStore(str, str)
        tv = Gtk.TreeView(model=store)
        tv.set_headers_visible(False)
        tv.append_column(Gtk.TreeViewColumn("", Gtk.CellRendererText(), text=0))
        sw = Gtk.ScrolledWindow()
        sw.set_size_request(420, 180)
        sw.set_shadow_type(Gtk.ShadowType.IN)
        sw.add(tv)
        d.add(sw)
        parts = {"Heading": [("Heading text", "text"), ("Page number", "page"),
                             ("Heading number", "number"),
                             ("Heading number (no context)", "number-no-context"),
                             ("Heading number (full context)", "number-full"),
                             ("Above/below", "above")],
                 "Bookmark": [("Bookmark text", "text"), ("Page number", "page"),
                              ("Paragraph number", "number"),
                              ("Paragraph number (no context)", "number-no-context"),
                              ("Paragraph number (full context)", "number-full"),
                              ("Above/below", "above")]}
        seq_parts = [("Entire caption", "text"), ("Only label and number", "label-number"),
                     ("Only caption text", "caption-only"), ("Page number", "page"),
                     ("Above/below", "above")]
        link = Gtk.CheckButton.new_with_mnemonic("Insert as _hyperlink")
        link.set_active(True)
        above = Gtk.CheckButton.new_with_mnemonic("Include above/_below")
        d.add(grid([[link, above]]))
        sep_on = Gtk.CheckButton.new_with_mnemonic("Separate numbers _with")
        sep_e = Gtk.Entry(text=".")
        sep_e.set_width_chars(4)
        d.add(grid([[sep_on, sep_e]]))

        def sep_sens(*_):
            ok = (rtype.get_active_text() or "") == "Numbered item" and "number" in (part.get_active_text() or "").lower()
            sep_on.set_sensitive(ok)
            sep_e.set_sensitive(ok and sep_on.get_active())
        sep_on.connect("toggled", sep_sens)
        part.connect("changed", lambda c: above.set_sensitive(
            "Above" not in (c.get_active_text() or "")))

        def type_changed(*_):
            k = rtype.get_active_text() or "Heading"
            part.remove_all()
            for lab, _v in parts.get(k, seq_parts):
                part.append_text(lab)
            part.set_active(0)
            store.clear()
            for item in refs.get(k, []):
                label, target = item
                store.append([str(label), str(target)])
            if len(store):
                tv.get_selection().select_path(Gtk.TreePath(0))
        rtype.connect("changed", type_changed)
        type_changed()
        part.connect("changed", sep_sens)
        sep_sens()
        if d.ask() == Gtk.ResponseType.OK:
            model, it = tv.get_selection().get_selected()
            if it:
                k = rtype.get_active_text()
                pv = parts.get(k, seq_parts)[max(0, part.get_active())][1]
                sep = sep_e.get_text() if sep_on.get_active() and sep_on.get_sensitive() else None
                if sep is not None and getattr(self.win, "native", False):
                    api.insert_cross_reference(m, k, model[it][1], pv, link.get_active(),
                                               above.get_active() and above.get_sensitive(), sep=sep)
                else:
                    api.insert_cross_reference(m, k, model[it][1], pv, link.get_active(),
                                               above.get_active() and above.get_sensitive())
        d.done()

    # ============================================================ captions
    def caption(self):
        m = self._model_or_warn()
        if m is None:
            return
        from . import captions
        captions.dialog(self.win)

    # ============================================================ TOC
    def insert_toc(self, title="Contents"):
        m = self._model_or_warn()
        if m is None:
            return
        if docapi.tocs(m):
            if not self.confirm("Do you want to replace the selected table of contents?",
                                yes="Yes", no="No"):
                return
            docapi.remove_toc(m)
        if not docapi.headings(m, 3):
            self.message("No table of contents entries found.\n\nApply heading styles "
                         "(Heading 1, Heading 2, ...) to the text you want in the table of "
                         "contents.")
        docapi.insert_toc(m, title=title)

    def insert_toc_2(self):
        self.insert_toc("Table of Contents")

    def remove_toc(self):
        m = self._model_or_warn()
        if m is not None:
            docapi.remove_toc(m)

    def update_toc(self):
        m = self._model_or_warn()
        if m is not None:
            docapi.update_indexes(m)

    def toc_dialog(self):
        if self._model_or_warn() is not None:
            from . import tocdlg
            tocdlg.toc_dialog(self.win)

    def add_text(self, level):
        m = self._model_or_warn()
        if m is not None:
            docapi.add_text_to_toc(m, int(level))

    # ============================================================ comments, notes
    def comment(self):
        m = self.model
        if getattr(self.eng, "native", False):
            sel = self.eng.ed.selected_text() if self.eng.ed else ""
        else:
            sel = docapi.selection_text(m) if m else ""
        d = FDialog(self.win, "New Comment", buttons=(("Post", Gtk.ResponseType.OK),
                                                      ("Cancel", Gtk.ResponseType.CANCEL)))
        author = self.win.app.user_name()
        head = Gtk.Label(xalign=0)
        head.set_markup("<b>%s</b>" % GLib.markup_escape_text(author))
        d.add(head)
        if sel:
            q = Gtk.Label(label="“%s”" % (sel[:80] + ("…" if len(sel) > 80 else "")),
                          xalign=0)
            q.get_style_context().add_class("dim-label")
            q.set_line_wrap(True)
            d.add(q)
        tv = Gtk.TextView()
        tv.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        tv.set_size_request(360, 90)
        tv.get_style_context().add_class("folio-comment-edit")
        fr = Gtk.Frame()
        fr.add(tv)
        d.add(fr)
        hint = Gtk.Label(label="Ctrl+Enter to post", xalign=1)
        hint.get_style_context().add_class("dim-label")
        d.add(hint)

        def key(w, ev):
            if ev.keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) and \
                    ev.state & Gdk.ModifierType.CONTROL_MASK:
                d.response(Gtk.ResponseType.OK)
                return True
            return False
        tv.connect("key-press-event", key)
        d.show_all()
        tv.grab_focus()
        r = d.run()
        buf = tv.get_buffer()
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
        d.destroy()
        if r == Gtk.ResponseType.OK and text.strip():
            self.eng.command(".uno:InsertAnnotation", {"Text": text, "Author": author})

    def next_comment(self):
        if getattr(self.eng, "native", False):
            self.eng.command(".uno:NextAnnotation")
            return
        m = self.model
        if m is not None and not docapi.goto_next(m, "comment", True):
            self.message("There are no more comments.")

    def prev_comment(self):
        if getattr(self.eng, "native", False):
            self.eng.command(".uno:PreviousAnnotation")
            return
        m = self.model
        if m is not None and not docapi.goto_next(m, "comment", False):
            self.message("There are no more comments.")

    def delete_all_comments(self):
        if getattr(self.eng, "native", False):
            self.eng.command(".uno:DeleteAllNotes")
            return
        m = self.model
        if m is not None:
            docapi.delete_comments(m)

    def next_footnote(self):
        m = self.model
        if m is not None and not docapi.goto_next(m, "footnote", True):
            docapi.goto_next(m, "endnote", True)

    def prev_footnote(self):
        m = self.model
        if m is not None and not docapi.goto_next(m, "footnote", False):
            docapi.goto_next(m, "endnote", False)

    def next_endnote(self):
        m = self.model
        if m is not None:
            docapi.goto_next(m, "endnote", True)

    def prev_endnote(self):
        m = self.model
        if m is not None:
            docapi.goto_next(m, "endnote", False)

    # ============================================================ header / footer
    def header(self, kind="blank"):
        m = self._model_or_warn()
        if m is None:
            return
        docapi.enable_header_footer(m, "header")
        self.eng.command(".uno:JumpToHeader")
        self.eng.sync(self.win.refresh_hf)

    def footer(self, kind="blank"):
        m = self._model_or_warn()
        if m is None:
            return
        docapi.enable_header_footer(m, "footer")
        self.eng.command(".uno:JumpToFooter")
        self.eng.sync(self.win.refresh_hf)

    def remove_header(self):
        m = self.model
        if m is not None:
            docapi.remove_header_footer(m, "header")

    def remove_footer(self):
        m = self.model
        if m is not None:
            docapi.remove_header_footer(m, "footer")

    def hf_option(self, key):
        m = self.model
        if m is None:
            return
        cb = self.win.hf_checks.get(key)
        if key == "show_text":
            ov = getattr(self.win, "hf_overlay", None)
            if ov is not None:
                ov.show_body = cb.get_active() if cb is not None else not ov.show_body
                self.win.engine.view.queue_draw()
            return
        docapi.set_hf_option(m, key, cb.get_active() if cb is not None else True)

    def hf_position(self, spec):
        m = self.model
        if m is not None:
            key, value = spec
            docapi.set_hf_option(m, key, value)

    def close_header_footer(self):
        self.eng.command(".uno:JumpToEndOfDoc") if False else None
        m = self.model
        if m is not None:
            vc = docapi.view_cursor(m)
            try:
                vc.gotoRange(m.getText().getStart(), False)
            except Exception:
                pass
        self.eng.sync(self.win.refresh_hf)
        self.win.focus_document()

    def page_number_top(self, align="right"):
        m = self._model_or_warn()
        if m is not None:
            docapi.insert_header_footer(m, "header", page_numbers="plain", align=align)

    def page_number_bottom(self, align="center"):
        m = self._model_or_warn()
        if m is not None:
            docapi.insert_header_footer(m, "footer", page_numbers="plain", align=align)

    def page_number_x_of_y(self):
        m = self._model_or_warn()
        if m is not None:
            docapi.insert_header_footer(m, "footer", page_numbers="page-x-of-y", align="center")

    def page_number_current(self):
        m = self._model_or_warn()
        if m is not None:
            docapi.insert_field(m, "page")

    def remove_page_numbers(self):
        m = self._model_or_warn()
        if m is not None:
            docapi.remove_page_numbers(m)

    # ============================================================ date, fields
    def date_time(self):
        m = self._model_or_warn()
        if m is None:
            return
        now = datetime.datetime.now()
        d = FDialog(self.win, "Date and Time")
        shown = [now.strftime(f) for f, _c in DATE_FORMATS]
        sw, tv, _ = listbox(shown, height=260, width=280,
                            on_activate=lambda *_: d.response(Gtk.ResponseType.OK))
        default = self.win.app.settings.get("date_format", 0)
        tv.get_selection().select_path(Gtk.TreePath(min(default, len(shown) - 1)))
        lang = combo(["English (United States)"], 0)
        auto = Gtk.CheckButton.new_with_mnemonic("_Update automatically")
        box = Gtk.Box(spacing=12)
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        left.pack_start(Gtk.Label(label="_Available formats:", xalign=0, use_underline=True),
                        False, False, 0)
        left.pack_start(sw, True, True, 0)
        box.pack_start(left, True, True, 0)
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        right.pack_start(Gtk.Label(label="_Language:", xalign=0, use_underline=True), False, False, 0)
        right.pack_start(lang, False, False, 0)
        box.pack_start(right, False, False, 0)
        d.add(box)
        d.add(auto)
        setdef = Gtk.Button(label="Set As _Default", use_underline=True)
        d.get_action_area().pack_start(setdef, False, False, 0)
        d.get_action_area().reorder_child(setdef, 0)

        def sel_index():
            model, it = tv.get_selection().get_selected()
            return model.get_path(it)[0] if it else 0
        setdef.connect("clicked", lambda *_: (self.win.app.settings.__setitem__(
            "date_format", sel_index()), self.win.app.save_settings()))
        if d.ask() == Gtk.ResponseType.OK:
            i = sel_index()
            fmt, code = DATE_FORMATS[i]
            if getattr(self.win, "native", False):
                pic = WORD_DATE_PICTURES[i]
                ed = self.win.engine.ed
                is_time = not any(c in pic for c in "dMy")
                if auto.get_active():
                    ed.insert_field_now('%s \\@ "%s"' % ("TIME" if is_time else "DATE", pic))
                else:
                    ed.type_text(ed.format_now(pic))
                self.win.engine.view.after_edit()
                d.done()
                return
            if auto.get_active():
                is_time = "%" in fmt and "%Y" not in fmt and "%y" not in fmt and "%B" not in fmt
                try:
                    docapi.insert_field(m, "time" if is_time else "date", False, code)
                except Exception:
                    self.win.actions.insert_text(now.strftime(fmt))
            else:
                self.win.actions.insert_text(now.strftime(fmt))
        d.done()

    def field_dialog(self):
        if self._model_or_warn() is not None:
            from . import fielddlg
            fielddlg.dialog(self.win)

    def update_fields(self):
        m = self.model
        if m is not None:
            docapi.update_indexes(m)

    # ============================================================ pages
    def blank_page(self):
        self.eng.command(".uno:InsertPagebreak")
        self.eng.command(".uno:InsertPagebreak")
        self.eng.command(".uno:GoUp")

    def cover_page(self, style="simple"):
        from . import covers
        if not getattr(self.win.engine, "native", False):
            m = self._model_or_warn()
            if m is None:
                return
        names = {n.lower(): n for n, _s in covers.COVERS}
        covers.insert_cover(self.win, names.get(str(style).lower(), "Simple"))

    def remove_cover_page(self):
        from . import covers
        if getattr(self.win.engine, "native", False):
            if not covers.remove_current(self.win):
                self.message("This document doesn't have a cover page.")
            return
        m = self.model
        if m is not None and not covers.remove_cover(m):
            self.message("This document doesn't have a cover page.")

    # ============================================================ tables
    def table_grid_popover(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.set_border_width(6)
        title = Gtk.Label(label="Insert Table", xalign=0)
        title.get_style_context().add_class("folio-popover-title")
        box.pack_start(title, False, False, 0)
        cols, rows = 10, 8
        g = Gtk.Grid(column_spacing=2, row_spacing=2)
        cells = {}
        state = {"r": 0, "c": 0}

        def mark(r, c):
            state["r"], state["c"] = r, c
            for (rr, cc), w in cells.items():
                ctx = w.get_style_context()
                if rr <= r and cc <= c:
                    ctx.add_class("on")
                else:
                    ctx.remove_class("on")
            title.set_text("%dx%d Table" % (c + 1, r + 1) if r >= 0 else "Insert Table")
        for r in range(rows):
            for c in range(cols):
                ev = Gtk.EventBox()
                cell = Gtk.Box()
                cell.set_size_request(16, 16)
                cell.get_style_context().add_class("folio-gridcell")
                ev.add(cell)
                ev.connect("enter-notify-event", lambda w, e, r=r, c=c: mark(r, c))
                ev.connect("button-release-event", lambda w, e, r=r, c=c: insert(r + 1, c + 1))
                g.attach(ev, c, r, 1, 1)
                cells[(r, c)] = cell
        box.pack_start(g, False, False, 0)
        box.pack_start(Gtk.Separator(), False, False, 2)
        holder = {}

        def insert(r, c):
            if "pop" in holder:
                holder["pop"].popdown()
            self.eng.sync(lambda: self._new_table(r, c))
        def quick_menu():
            from . import insertmore
            menu = Gtk.Menu()
            for name in insertmore.QUICK_TABLES:
                it = Gtk.MenuItem(label=name)
                it.connect("activate", lambda _i, n=name: self.eng.sync(
                    lambda: insertmore.quick_table(self.model, n)))
                menu.append(it)
            menu.show_all()
            menu.popup_at_pointer(None)
        for label, cb, icon in (("_Insert Table...", self.insert_table_dialog, "cmd/sc_inserttable"),
                                ("D_raw Table", lambda: self.win.table_draw.begin("draw"),
                                 "pen-black"),
                                ("Con_vert Text to Table...", lambda: self.text_to_table(),
                                 "cmd/sc_inserttable"),
                                ("_Quick Tables", quick_menu, "cmd/sc_inserttable")):
            b = Gtk.Button()
            b.set_relief(Gtk.ReliefStyle.NONE)
            ib = Gtk.Box(spacing=8)
            ib.pack_start(icons.image(icon, 16), False, False, 0)
            ib.pack_start(Gtk.Label(label=label, xalign=0, use_underline=True), True, True, 0)
            b.add(ib)
            b.connect("clicked", lambda _b, cb=cb: (holder["pop"].popdown(), GLib.idle_add(
                lambda: (cb(), False)[1])))
            box.pack_start(b, False, False, 0)
        pop = Gtk.Popover()
        holder["pop"] = pop
        box.show_all()
        pop.add(box)
        return pop

    def _new_table(self, rows, cols):
        m = self.model
        if m is None:
            return
        from . import tablestyles
        try:
            tablestyles.insert_table(m, rows, cols)
            from . import captions
            captions.after_insert(self.win, "table")
        except Exception as e:
            print("insert table:", e)
            self.eng.command(".uno:InsertTable", {"Columns": ("long", cols),
                                                  "Rows": ("long", rows)})

    def insert_table_dialog(self):
        from .widgets import LengthSpin
        st = self.win.app.settings
        mem = st.get("table_dims") or {}
        d = FDialog(self.win, "Insert Table")
        d.add(heading("Table size"))
        cols = Gtk.SpinButton.new_with_range(1, 63, 1)
        rows = Gtk.SpinButton.new_with_range(1, 32767, 1)
        cols.set_value(mem.get("cols", 5))
        rows.set_value(mem.get("rows", 2))
        d.add(grid([["Number of _columns:", cols], ["Number of _rows:", rows]]))
        d.add(heading("AutoFit behavior"))
        fixed = Gtk.RadioButton.new_with_mnemonic(None, "Fi_xed column width:")
        contents = Gtk.RadioButton.new_with_mnemonic_from_widget(fixed, "Auto_Fit to contents")
        window = Gtk.RadioButton.new_with_mnemonic_from_widget(fixed, "AutoFit to win_dow")
        {"contents": contents, "window": window}.get(mem.get("fit"), fixed).set_active(True)
        width = Gtk.ComboBoxText.new_with_entry()
        width.append_text("Auto")
        width.get_child().set_text(mem.get("width_text", "Auto"))
        width.get_child().set_width_chars(10)
        d.add(grid([[fixed, width], [contents, None], [window, None]]))
        fixed.connect("toggled", lambda b: width.set_sensitive(b.get_active()))
        width.set_sensitive(fixed.get_active())
        remember = Gtk.CheckButton.new_with_mnemonic("Remember dimen_sions for new tables")
        remember.set_active(bool(mem))
        d.add(remember)
        if d.ask() == Gtk.ResponseType.OK:
            nr, nc = int(rows.get_value()), int(cols.get_value())
            fit = "contents" if contents.get_active() else \
                "window" if window.get_active() else "fixed"
            wtext = width.get_child().get_text().strip() or "Auto"
            if remember.get_active():
                st["table_dims"] = {"rows": nr, "cols": nc, "fit": fit, "width_text": wtext}
            elif "table_dims" in st:
                del st["table_dims"]
            self.win.app.save_settings()
            self._new_table(nr, nc)
            m = self.model
            if m is not None:
                from . import tablelayout
                try:
                    t, _c = tablelayout.current(m)
                    if t is not None and fit == "fixed" and wtext.lower() != "auto":
                        from .widgets import parse_len
                        cw = parse_len(wtext)
                        if cw:
                            t.HoriOrient = 0
                            t.Width = int(cw * nc)
                    elif t is not None and fit == "contents":
                        def go():
                            self.win.actions.cmd(".uno:SelectTable")
                            self.win.actions.cmd(".uno:SetOptimalColumnWidth")
                            self.eng.sync(lambda: docapi.view_cursor(m).gotoRange(
                                t.getCellByPosition(0, 0).getStart(), False))
                        self.eng.sync(go)
                    elif t is not None:
                        t.HoriOrient = 6
                except Exception as e:
                    print("table autofit:", e)
        d.done()

    def table_style2(self, spec):
        m = self.model
        if m is None:
            return
        from . import tablestyles
        kind, accent = spec
        tablestyles.apply(m, kind, accent)
        self.win.refresh_table_design()

    def table_option(self, key):
        m = self.model
        if m is None:
            return
        from . import tablestyles
        cb = self.win.table_opt_checks.get(key)
        tablestyles.set_option(m, key, cb.get_active() if cb is not None else True)
        self.win.refresh_table_design()

    def table_style(self, scheme):
        m = self.model
        if m is None:
            return
        schemes = {"plain": (-1, -1, 0x000000, 0x000000), "grid": (0xFFFFFF, -1, 0x000000, 0x000000),
                   "blue": (0x4472C4, 0xD9E2F3, 0x8EAADB, 0xFFFFFF),
                   "orange": (0xED7D31, 0xFBE4D5, 0xF4B083, 0xFFFFFF),
                   "gray": (0xA5A5A5, 0xEDEDED, 0xC9C9C9, 0xFFFFFF),
                   "green": (0x70AD47, 0xE2EFD9, 0xA8D08D, 0xFFFFFF)}
        h, b, br, f = schemes.get(scheme, schemes["blue"])
        docapi.table_style(m, h, b, br, f if h != -1 else 0)

    # ============================================================ symbols
    def symbol_popover(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.set_border_width(6)
        recent = self.win.app.settings.get("recent_symbols", [])
        syms = (recent + [c for c in COMMON_SYMBOLS if c not in recent])[:20]
        g = Gtk.Grid(column_spacing=2, row_spacing=2)
        pop = Gtk.Popover()
        for i, ch in enumerate(syms):
            b = Gtk.Button(label=ch)
            b.get_style_context().add_class("folio-symbol")
            b.set_tooltip_text(unicodedata.name(ch, "").title())
            b.connect("clicked", lambda _b, ch=ch: (pop.popdown(), self._insert_symbol(ch)))
            g.attach(b, i % 5, i // 5, 1, 1)
        box.pack_start(g, False, False, 0)
        more = Gtk.Button()
        more.set_relief(Gtk.ReliefStyle.NONE)
        mb = Gtk.Box(spacing=8)
        mb.pack_start(icons.image("cmd/sc_charmapcontrol", 16), False, False, 0)
        mb.pack_start(Gtk.Label(label="More Symbols...", xalign=0), True, True, 0)
        more.add(mb)
        more.connect("clicked", lambda *_: (pop.popdown(), GLib.idle_add(
            lambda: (self.symbol_dialog(), False)[1])))
        box.pack_start(more, False, False, 0)
        box.show_all()
        pop.add(box)
        return pop

    def _insert_symbol(self, ch):
        self.win.actions.insert_text(ch)
        rec = [c for c in self.win.app.settings.get("recent_symbols", []) if c != ch]
        rec.insert(0, ch)
        self.win.app.settings["recent_symbols"] = rec[:20]
        self.win.app.save_settings()

    def symbol_dialog(self):
        d = FDialog(self.win, "Symbol", buttons=(("Insert", Gtk.ResponseType.OK),
                                                 ("Cancel", Gtk.ResponseType.CANCEL)))
        d.set_resizable(True)
        nb = Gtk.Notebook()
        d.add(nb, expand=True)
        p1 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        p1.set_border_width(8)
        fonts = ["(normal text)"] + (self.eng.fonts(all_fonts=True) or [])
        font = combo(fonts, 0)
        subset = combo([b[0] for b in UNICODE_BLOCKS], 1)
        p1.pack_start(grid([["_Font:", font, "S_ubset:", subset]]), False, False, 0)
        store = Gtk.ListStore(str, str)
        iv = Gtk.IconView(model=store)
        iv.set_text_column(0)
        iv.set_columns(16)
        iv.set_item_width(24)
        iv.set_item_padding(2)
        iv.set_spacing(0)
        iv.set_row_spacing(0)
        iv.set_column_spacing(0)
        iv.set_margin(2)
        iv.get_style_context().add_class("folio-charmap")
        sw = Gtk.ScrolledWindow()
        sw.set_size_request(560, 230)
        sw.set_shadow_type(Gtk.ShadowType.IN)
        sw.add(iv)
        p1.pack_start(sw, True, True, 0)
        p1.pack_start(Gtk.Label(label="_Recently used symbols:", xalign=0, use_underline=True),
                      False, False, 0)
        rb = Gtk.Box(spacing=2)
        for ch in self.win.app.settings.get("recent_symbols", [])[:16]:
            b = Gtk.Button(label=ch)
            b.get_style_context().add_class("folio-symbol")
            b.connect("clicked", lambda _b, ch=ch: select_char(ch))
            rb.pack_start(b, False, False, 0)
        p1.pack_start(rb, False, False, 0)
        name = Gtk.Label(label="", xalign=0)
        code = Gtk.Entry()
        code.set_width_chars(8)
        p1.pack_start(grid([[name, None, "_Character code:", code, "from: Unicode (hex)"]]),
                      False, False, 0)
        chosen = {"ch": None}

        def fill(*_):
            store.clear()
            b = UNICODE_BLOCKS[subset.get_active()]
            for cp in range(b[1], b[2] + 1):
                ch = chr(cp)
                if unicodedata.category(ch) in ("Cc", "Cn", "Co", "Cs"):
                    continue
                store.append([ch, "%04X" % cp])

        def select_char(ch):
            chosen["ch"] = ch
            name.set_text(unicodedata.name(ch, "").title())
            code.set_text("%04X" % ord(ch))
            for blk_i, b in enumerate(UNICODE_BLOCKS):
                if b[1] <= ord(ch) <= b[2]:
                    if subset.get_active() != blk_i:
                        subset.set_active(blk_i)
                    break
            for row in store:
                if row[0] == ch:
                    iv.select_path(row.path)
                    iv.scroll_to_path(row.path, False, 0, 0)

        def on_sel(_iv):
            items = iv.get_selected_items()
            if items:
                ch = store[items[0]][0]
                chosen["ch"] = ch
                name.set_text(unicodedata.name(ch, "").title())
                if code.get_text() != "%04X" % ord(ch):
                    code.set_text("%04X" % ord(ch))

        def font_changed(*_):
            f = font.get_active_text()
            css = Gtk.CssProvider()
            fam = "inherit" if f == "(normal text)" else '"%s"' % f
            css.load_from_data(("iconview { font-family: %s; font-size: 15px; }" % fam).encode())
            iv.get_style_context().add_provider(css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 2)

        def code_changed(e):
            try:
                cp = int(e.get_text(), 16)
                if 0x20 <= cp <= 0x10FFFF and chosen["ch"] != chr(cp):
                    select_char(chr(cp))
            except ValueError:
                pass
        subset.connect("changed", fill)
        font.connect("changed", font_changed)
        iv.connect("selection-changed", on_sel)
        iv.connect("item-activated", lambda *_: d.response(Gtk.ResponseType.OK))
        code.connect("changed", code_changed)
        fill()
        font_changed()
        # special characters
        p2 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        p2.set_border_width(8)
        sstore = Gtk.ListStore(str, str, str)
        for ch, nm, key in SPECIAL_CHARS:
            sstore.append([ch if ch.strip() else "·", nm, key])
        stv = Gtk.TreeView(model=sstore)
        for i, t in enumerate(("Character", "", "Shortcut key:")):
            col = Gtk.TreeViewColumn(t, Gtk.CellRendererText(), text=i)
            col.set_expand(i == 1)
            stv.append_column(col)
        ssw = Gtk.ScrolledWindow()
        ssw.set_size_request(560, 300)
        ssw.set_shadow_type(Gtk.ShadowType.IN)
        ssw.add(stv)
        p2.pack_start(ssw, True, True, 0)
        stv.connect("row-activated", lambda *_: d.response(Gtk.ResponseType.OK))
        nb.append_page(p1, Gtk.Label(label="Symbols"))
        nb.append_page(p2, Gtk.Label(label="Special Characters"))
        sk_lab = Gtk.Label(xalign=0)
        ab = Gtk.Box(spacing=6)
        acb = Gtk.Button(label="_AutoCorrect...", use_underline=True)
        skb = Gtk.Button(label="Shortcut _Key...", use_underline=True)
        ab.pack_start(acb, False, False, 0)
        ab.pack_start(skb, False, False, 0)
        ab.pack_start(sk_lab, False, False, 6)
        p1.pack_start(ab, False, False, 4)

        def cur_char():
            if nb.get_current_page() == 1:
                model, it = stv.get_selection().get_selected()
                return SPECIAL_CHARS[model.get_path(it)[0]][0] if it else None
            return chosen["ch"]

        def show_key(*_):
            ch = cur_char()
            keys = [k for k, v in (self.win.app.settings.get("symbol_keys") or {}).items()
                    if v == ch]
            sk_lab.set_text(("Shortcut key: " + ", ".join(
                "+".join(p.capitalize() for p in k.split("+")) for k in keys)) if keys else "")
        iv.connect("selection-changed", show_key)

        def do_autocorrect(*_):
            ch = cur_char()
            if ch:
                from .options import autocorrect_options
                autocorrect_options(self.win, 0, with_text=ch)

        def do_shortcut(*_):
            ch = cur_char()
            if not ch:
                return
            from .stylemodify import shortcut_dialog
            st = self.win.app.settings
            # the style-key dialog, storing into the symbol keys
            saved = st.get("style_keys")
            st["style_keys"] = {k: v for k, v in (st.get("symbol_keys") or {}).items()
                                if v == ch}
            try:
                shortcut_dialog(d, self.win, ch)
                new = st.get("style_keys") or {}
            finally:
                st["style_keys"] = saved if saved is not None else {}
            sym = {k: v for k, v in (st.get("symbol_keys") or {}).items() if v != ch}
            sym.update({k: v for k, v in new.items() if v == ch})
            st["symbol_keys"] = sym
            self.win.app.save_settings()
            for w in self.win.app.windows:
                w.keymap.set_style_keys(st.get("style_keys") or {})
                w.keymap.set_symbol_keys(sym)
            show_key()
        acb.connect("clicked", do_autocorrect)
        skb.connect("clicked", do_shortcut)
        while True:
            r = d.ask()
            if r != Gtk.ResponseType.OK:
                break
            if nb.get_current_page() == 1:
                model, it = stv.get_selection().get_selected()
                if it:
                    idx = model.get_path(it)[0]
                    self.win.actions.insert_text(SPECIAL_CHARS[idx][0])
            elif chosen["ch"]:
                f = font.get_active_text()
                if f and f != "(normal text)":
                    self.win.actions.font_name(f)
                self._insert_symbol(chosen["ch"])
            # Insert keeps the dialog open; the window behind updates live
            d.buttons[Gtk.ResponseType.CANCEL].set_label("Close")
        d.done()

    # ============================================================ equations
    def equation_gallery_popover(self):
        from .eqbar import equation_gallery
        return equation_gallery(self.win)

    def equation(self, linear=None):
        self.win.eqbar.new_equation(linear)

    def ink_equation(self):
        self.equation()

    # ============================================================ panes
    def find_pane(self, text=None):
        from .panes import NavigationPane
        pane = self.win.show_pane(NavigationPane, "left")
        pane.focus_search(text)

    def outline_view(self):
        from .panes import NavigationPane
        pane = self.win.show_pane(NavigationPane, "left")
        pane.show_headings()
        self.win.ribbon.show_contextual("Outlining", True)
        self.win.select_tab("Outlining")

    def close_outline(self):
        from .panes import NavigationPane
        self.win.ribbon.show_contextual("Outlining", False)
        p = self.win.panes.get(NavigationPane)
        if p is not None and p.get_parent() is not None:
            self.win.hide_pane(p)
        self.win.select_tab("Home")

    def styles_pane(self):
        from .panes import StylesPane
        self.win.show_pane(StylesPane, "right")

    def spelling(self):
        from .panes import EditorPane
        pane = self.win.show_pane(EditorPane, "right")
        pane.start()

    def thesaurus(self):
        from .panes import ThesaurusPane
        pane = self.win.show_pane(ThesaurusPane, "right")
        pane.lookup_selection()

    def clipboard_pane(self):
        from .panes import ClipboardPane
        self.win.show_pane(ClipboardPane, "left")

    def comments_pane(self):
        from .panes import CommentsPane
        self.win.show_pane(CommentsPane, "right")

    # ============================================================ misc
    def draft_view(self):
        self.win.act_web_layout()

    def go_back(self):
        self.win.go_back()

    def extend_selection(self):
        self.win.extend_selection()

    # ============================================================ sections / files
    def section_break(self, kind):
        m = self._model_or_warn()
        if m is not None:
            before = docapi.read_cursor(m).PageStyleName or "Standard"
            docapi.insert_section_break(m, kind)
            if kind != "continuous":
                # the new section's header and footer start linked to these
                from . import hfedit
                for part in ("header", "footer"):
                    try:
                        hfedit.propagate(self.win, before, part)
                    except Exception as e:
                        print("section header:", e)

    def text_from_file(self):
        path = self.pick_file("Insert File", ["*.docx", "*.doc", "*.odt", "*.rtf", "*.txt",
                                              "*.htm", "*.html", "*.dotx", "*.ott"],
                              "All Documents")
        if not path:
            return
        if getattr(self.eng, "native", False):
            from .native import insertfile
            try:
                insertfile.insert(self.win, path)
            except Exception as e:
                self.message("This file couldn't be inserted. (%s)" % e, kind="error")
            return
        m = self._model_or_warn()
        if m is None:
            return
        try:
            docapi.insert_text_from_file(m, path)
        except Exception as e:
            self.message("This file couldn't be inserted. (%s)" % e, kind="error")

    # ============================================================ figures / index
    def table_of_figures(self):
        if self._model_or_warn() is None:
            return
        from . import tocdlg
        labels = ["Equation", "Figure", "Table"] + \
            self.win.app.settings.get("caption_labels", [])
        tocdlg.figures_dialog(self.win, labels)

    def mark_entry(self):
        """Mark Index Entry: modeless, like the original, so several entries
        can be marked in a row."""
        m = self._model_or_warn()
        if m is None:
            return
        if getattr(self, "_mark_dlg", None) is not None:
            self._mark_dlg.present()
            self._mark_fill()
            return
        win = Gtk.Window(title="Mark Index Entry", transient_for=self.win)
        win.set_type_hint(1)
        win.set_position(Gtk.WindowPosition.CENTER_ON_PARENT)
        win.get_style_context().add_class("folio-dialog")
        win.set_resizable(False)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_border_width(12)
        win.add(box)
        main = Gtk.Entry()
        main.set_width_chars(36)
        sub = Gtk.Entry()
        box.pack_start(heading("Index"), False, False, 0)
        box.pack_start(grid([["_Main entry:", main], ["_Subentry:", sub]]), False, False, 0)
        box.pack_start(heading("Page number format"), False, False, 0)
        bold = Gtk.CheckButton.new_with_mnemonic("_Bold")
        box.pack_start(bold, False, False, 0)
        note = Gtk.Label(label="This dialog box stays open so that you can mark multiple "
                               "index entries.", xalign=0)
        note.set_line_wrap(True)
        note.set_max_width_chars(44)
        box.pack_start(note, False, False, 0)
        btns = Gtk.Box(spacing=6)
        btns.set_halign(Gtk.Align.END)
        mark = Gtk.Button(label="_Mark", use_underline=True)
        mark_all = Gtk.Button(label="Mark _All", use_underline=True)
        close = Gtk.Button(label="Close")
        for b in (mark, mark_all, close):
            btns.pack_start(b, False, False, 0)
        box.pack_start(btns, False, False, 0)

        def entry_text():
            t = main.get_text().strip()
            if sub.get_text().strip():
                t = t + ":" + sub.get_text().strip()
            return t

        def do_mark(*_):
            mm = self.eng.model
            if mm is None or not main.get_text().strip():
                return
            mk = docapi.mark_index_entry(mm, entry_text(), bold.get_active())
            if sub.get_text().strip():
                try:
                    mk.AlternativeText = main.get_text().strip()
                    mk.PrimaryKey = ""
                    mk.AlternativeText = sub.get_text().strip()
                    mk.PrimaryKey = main.get_text().strip()
                except Exception:
                    pass
            self.win.focus_document()

        def do_mark_all(*_):
            mm = self.eng.model
            word = docapi.view_cursor(mm).getString() if mm is not None else ""
            if not word:
                return
            sd = mm.createSearchDescriptor()
            sd.SearchString = word
            sd.SearchCaseSensitive = True
            found = mm.findAll(sd)
            for i in range(found.getCount()):
                r = found.getByIndex(i)
                mk = mm.createInstance("com.sun.star.text.DocumentIndexMark")
                if entry_text() != word:
                    mk.AlternativeText = entry_text()
                try:
                    mk.IsMainEntry = bold.get_active()
                except Exception:
                    pass
                r.getText().insertTextContent(r, mk, True)

        def fill():
            mm = self.eng.model
            if mm is not None:
                main.set_text(docapi.view_cursor(mm).getString()[:200])
                sub.set_text("")
        self._mark_fill = fill
        mark.connect("clicked", do_mark)
        mark_all.connect("clicked", do_mark_all)

        def on_close(*_):
            self._mark_dlg = None
            win.destroy()
            return True
        close.connect("clicked", on_close)
        win.connect("delete-event", on_close)
        self._mark_dlg = win
        fill()
        win.show_all()

    def insert_index(self):
        if self._model_or_warn() is not None:
            from . import tocdlg
            tocdlg.index_dialog(self.win)

    # ============================================================ language
    def language_dialog(self):
        native = getattr(self.eng, "native", False)
        m = None if native else self._model_or_warn()
        if m is None and not native:
            return
        if native:
            tag = (self.eng.ed.state().get("lang") or "-".join(self.win.app.settings.get("language") or ["en", "US"]))
            cur_l, _s, cur_c = tag.replace("_", "-").partition("-")
        else:
            cur_l, cur_c = docapi.current_language(m)
        d = FDialog(self.win, "Language")
        d.set_default_size(380, 420)
        d.add(Gtk.Label(label="Mark selected text as:", xalign=0))
        store = Gtk.ListStore(str, str, str, str)
        sel_row = 0
        for i, (name, l, c) in enumerate(docapi.LANGUAGES):
            store.append(["ABC" if docapi.has_dictionary(l, c) else "", name, l, c])
            if (l, c) == (cur_l, cur_c):
                sel_row = i
        tv = Gtk.TreeView(model=store)
        tv.set_headers_visible(False)
        tv.append_column(Gtk.TreeViewColumn("", Gtk.CellRendererText(scale=0.7), text=0))
        tv.append_column(Gtk.TreeViewColumn("", Gtk.CellRendererText(), text=1))
        tv.get_selection().select_path(Gtk.TreePath(sel_row))
        tv.connect("row-activated", lambda *_: d.response(Gtk.ResponseType.OK))
        sw = Gtk.ScrolledWindow()
        sw.set_size_request(340, 260)
        sw.add(tv)
        d.add(sw, expand=True)
        GLib.idle_add(lambda: tv.scroll_to_cell(Gtk.TreePath(sel_row), None, True, 0.3, 0))
        note = Gtk.Label(label="The speller and other proofing tools automatically use "
                               "dictionaries of the selected language, if available.",
                         xalign=0)
        note.set_line_wrap(True)
        note.set_max_width_chars(48)
        note.get_style_context().add_class("dim-label")
        d.add(note)
        noproof = Gtk.CheckButton.new_with_mnemonic("_Do not check spelling or grammar")
        noproof.set_active(cur_l == "zxx")
        d.add(noproof)
        detect = Gtk.CheckButton.new_with_mnemonic("Detect _language automatically")
        detect.set_active(self.win.app.settings.get("detect_language", True))
        d.add(detect)
        sd = d.add_button("Set As _Default", 1)
        sd.set_use_underline(True)
        d.get_action_area().reorder_child(sd, 0)
        r = d.ask()
        model, it = tv.get_selection().get_selected()
        if it is not None and r in (Gtk.ResponseType.OK, 1):
            l, c = model[it][2], model[it][3]
            name = model[it][1]
            if r == 1 and not self.confirm(
                    "Do you want to change the default language to %s?\n\nThis change will "
                    "affect all new documents based on the Normal template." % name,
                    yes="Yes", no="No"):
                d.done()
                return
            self.win.app.settings["detect_language"] = detect.get_active()
            if native:
                from .native import proofing
                proofing.set_language(self.win, l, c, noproof.get_active(), default=r == 1)
                if r == 1:
                    self.win.app.settings["language"] = [l, c]
                    self.win.app.save_settings()
                d.done()
                return
            docapi.set_language(m, l, c, noproof.get_active())
            if r == 1:
                docapi.set_language(m, l, c, default=True, whole=True)
                self.win.app.settings["language"] = [l, c]
                self.win.app.save_settings()
            self.win.status.lang.set_label(name if not noproof.get_active()
                                           else "Do not check")
            self.win.status.schedule_proof()
        d.done()


# ================================================================ pictures
def _sel_obj(self):
    from . import drawing
    m = self.model
    return (m, drawing.selected_shape(m)) if m is not None else (None, None)


def _change_picture(self):
    m, obj = _sel_obj(self)
    if obj is None:
        return
    path = self.pick_file("Insert Picture", ["*.png", "*.jpg", "*.jpeg", "*.gif", "*.bmp",
                                             "*.svg", "*.tif", "*.tiff", "*.webp"],
                          "All Pictures")
    if path:
        self.win.object_call("change_picture", path)


def _alt_text(self):
    from .panes import AltTextPane
    self.win.show_pane(AltTextPane, "right")


def _crop(self):
    from . import drawing
    from .widgets import LengthSpin
    m, obj = _sel_obj(self)
    if obj is None or not drawing.is_picture(obj):
        return
    d = FDialog(self.win, "Crop")
    spins = {k: LengthSpin(0, 0, 558800) for k in ("left", "right", "top", "bottom")}
    d.add(heading("Crop from"))
    d.add(grid([["_Left:", spins["left"], "_Top:", spins["top"]],
                ["_Right:", spins["right"], "_Bottom:", spins["bottom"]]]))
    if d.ask() == Gtk.ResponseType.OK:
        self.win.object_call("crop", *(spins[k].mm100 for k in ("left", "top", "right",
                                                                "bottom")))
    d.done()


def _picture_corrections(self):
    from . import drawing
    m, obj = _sel_obj(self)
    if obj is None or not drawing.is_picture(obj):
        return
    d = FDialog(self.win, "Format Picture")
    b0, c0 = obj.AdjustLuminance, obj.AdjustContrast
    vals = {}
    rows = []
    for key, label, v in (("b", "_Brightness:", b0), ("c", "_Contrast:", c0)):
        sc = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, -100, 100, 1)
        sc.set_value(v)
        sc.set_size_request(260, -1)
        sc.set_value_pos(Gtk.PositionType.RIGHT)
        sc.connect("format-value", lambda s, x: "%+d%%" % x)
        sc.connect("value-changed", lambda s: drawing.set_adjust(
            obj, int(vals["b"].get_value()), int(vals["c"].get_value())))
        vals[key] = sc
        rows.append([label, sc])
    d.add(heading("Picture Corrections"))
    d.add(grid(rows))
    reset = Gtk.Button(label="_Reset", use_underline=True)
    reset.set_halign(Gtk.Align.START)
    reset.connect("clicked", lambda *_: (vals["b"].set_value(0), vals["c"].set_value(0)))
    d.add(reset)
    if d.ask() != Gtk.ResponseType.OK:
        drawing.set_adjust(obj, b0, c0)
    d.done()


InsertDialogs.change_picture = _change_picture
InsertDialogs.alt_text = _alt_text
InsertDialogs.crop = _crop
InsertDialogs.picture_corrections = _picture_corrections
