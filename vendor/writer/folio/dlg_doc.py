"""Find and Replace, Go To, Word Count, Zoom, Page Setup, Watermark and
the other document-level dialogs."""
import os
import re

from gi.repository import GLib, Gtk

from . import bridge, docapi
from .widgets import (FDialog, LengthSpin, Preview, color_button, combo, combo_text,
                      fmt_len, grid, heading, list_selected, listbox)

PAPER = [("Letter", 21590, 27940), ("Legal", 21590, 35560), ("Executive", 18415, 26670),
         ("A3", 29700, 42000), ("A4", 21000, 29700), ("A5", 14800, 21000),
         ("B5 (JIS)", 18200, 25700), ("Tabloid", 27940, 43180),
         ("Envelope #10", 10477, 24130), ("Envelope DL", 11000, 22000)]

MARGIN_PRESETS = {
    "normal": (2540, 2540, 2540, 2540), "narrow": (1270, 1270, 1270, 1270),
    "moderate": (2540, 2540, 1905, 1905), "wide": (2540, 2540, 5080, 5080),
    "classic": (2540, 2540, 3175, 3175), "mirrored": (2540, 2540, 3175, 2540),
}

SPECIAL_CODES = [("Paragraph Mark", "^p"), ("Tab Character", "^t"), ("Any Character", "^?"),
                 ("Any Digit", "^#"), ("Any Letter", "^$"), ("Caret Character", "^^"),
                 ("Em Dash", "^+"), ("En Dash", "^="), ("Manual Line Break", "^l"),
                 ("Nonbreaking Space", "^s"), ("Optional Hyphen", "^-"),
                 ("White Space", "^w"), ("Find What Text", "^&")]


def special_to_regex(s):
    """Word's ^ codes in a search to a regular expression."""
    codes = {"p": "$", "t": "\\t", "?": ".", "#": "[0-9]", "$": "[A-Za-z]", "^": "\\^",
             "+": "\u2014", "=": "\u2013", "l": "\\n", "s": "\u00a0", "-": "\u00ad",
             "w": "[ \\t\u00a0]+"}
    out, i = [], 0
    while i < len(s):
        ch = s[i]
        if ch == "^" and i + 1 < len(s) and s[i + 1] in codes:
            out.append(codes[s[i + 1]])
            i += 2
            continue
        out.append(re.escape(ch))
        i += 1
    return "".join(out)


def special_to_replacement(s):
    codes = {"p": "\\n", "t": "\\t", "^": "^", "+": "\u2014", "=": "\u2013",
             "l": "\u2028", "s": "\u00a0", "-": "\u00ad", "&": "&"}
    out, i = [], 0
    while i < len(s):
        ch = s[i]
        if ch == "^" and i + 1 < len(s) and s[i + 1] in codes:
            out.append(codes[s[i + 1]])
            i += 2
            continue
        if ch in "\\&$":
            out.append("\\" + ch)
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def count_lines(m, selection=False):
    """Lines of the document (or of the selection), as laid out on the
    pages: the view cursor walks down a line at a time while the screen is
    held still, then goes back."""
    ctl = docapi.controller(m)
    vc = ctl.getViewCursor()
    try:
        sel = ctl.getSelection()
        keep = sel.getByIndex(0) if sel.getCount() else None
    except Exception:
        keep = None
    text = m.getText()
    m.lockControllers()
    n = 0
    try:
        if selection and keep is not None:
            end = keep.getEnd()
            vc.gotoRange(keep.getStart(), False)
            vc.gotoStartOfLine(False)
            n = 1
            for _i in range(200000):
                if not vc.goDown(1, False):
                    break
                vc.gotoStartOfLine(False)
                try:
                    if text.compareRegionStarts(vc.getStart(), end) < 0:
                        break
                except Exception:
                    break
                n += 1
        else:
            vc.gotoStart(False)
            n = 1
            for _i in range(200000):
                if not vc.goDown(1, False):
                    break
                n += 1
    except Exception as e:
        print("lines:", e)
        n = 0
    finally:
        try:
            if keep is not None:
                ctl.select(keep)
        except Exception:
            pass
        m.unlockControllers()
    return n


def set_line_number_starts(m, start=1, each_section=False):
    """Line numbers start at `start`, and again at each section if asked."""
    starts = _section_starts(m)
    text = m.getText()
    for i, r in enumerate(starts):
        try:
            c = text.createTextCursorByRange(r)
            if i == 0:
                c.ParaLineNumberStartValue = start if start != 1 or each_section else 0
            else:
                c.ParaLineNumberStartValue = start if each_section else 0
        except Exception as e:
            print("line numbers:", e)


WATERMARK_NAME = "WordPictureWatermark"


def _header_texts(m, ps):
    out = [ps.HeaderText]
    for attr, cond in (("HeaderTextLeft", not ps.HeaderIsShared),
                       ("HeaderTextFirst", not getattr(ps, "FirstIsShared", True))):
        try:
            if cond:
                out.append(getattr(ps, attr))
        except Exception:
            pass
    return out


def remove_picture_watermarks(m):
    dp = m.getDrawPage()
    for i in reversed(range(dp.getCount())):
        try:
            o = dp.getByIndex(i)
            if (o.Name or "").startswith(WATERMARK_NAME):
                o.getAnchor().getText().removeTextContent(o)
        except Exception:
            pass


def picture_watermark(m, path, pct=None, washout=True):
    """A picture behind the text of every page, in the header, centred on
    the page (as the original stores it)."""
    um = m.getUndoManager()
    um.enterUndoContext("Watermark")
    try:
        remove_picture_watermarks(m)
        ps = docapi.page_style(m)
        docapi.enable_header_footer(m, "header", ps)
        prov = bridge.create("com.sun.star.graphic.GraphicProvider")
        g = prov.queryGraphic((bridge.prop("URL", docapi.uno_url(path)),))
        nat = g.Size100thMM
        w, h = nat.Width or 10000, nat.Height or 10000
        if pct is None:
            avail_w = ps.Width - ps.LeftMargin - ps.RightMargin
            avail_h = ps.Height - ps.TopMargin - ps.BottomMargin - 2540
            r = min(avail_w / float(w), avail_h / float(h))
        else:
            r = pct / 100.0
        w, h = int(w * r), int(h * r)
        for n, text in enumerate(_header_texts(m, ps)):
            o = m.createInstance("com.sun.star.text.TextGraphicObject")
            o.Graphic = g
            o.AnchorType = bridge.enum("com.sun.star.text.TextContentAnchorType",
                                       "AT_PARAGRAPH")
            text.insertTextContent(text.getStart(), o, False)
            o.Size = bridge.struct("com.sun.star.awt.Size", Width=w, Height=h)
            o.TextWrap = bridge.enum("com.sun.star.text.WrapTextMode", "THROUGH")
            o.Opaque = False
            o.HoriOrient, o.HoriOrientRelation = 2, 7       # centre of the page
            o.VertOrient, o.VertOrientRelation = 2, 7
            if washout:
                o.GraphicColorMode = bridge.enum("com.sun.star.drawing.ColorMode",
                                                 "WATERMARK")
            o.Name = "%s%d" % (WATERMARK_NAME, n + 1)
    finally:
        um.leaveUndoContext()


def _section_starts(m):
    """Where each section begins: the document start, then every page style
    change (a section break)."""
    out = [m.getText().getStart()]
    en = m.getText().createEnumeration()
    first = True
    while en.hasMoreElements():
        p = en.nextElement()
        try:
            if not first and p.supportsService("com.sun.star.text.Paragraph") and \
                    p.PageDescName:
                out.append(p.getStart())
        except Exception:
            pass
        first = False
    try:
        secs = m.getTextSections()
        for i in range(secs.getCount()):
            a = secs.getByIndex(i).getAnchor()
            if a.getText() == m.getText():
                out.append(a.getStart())
    except Exception:
        pass

    def key(r):
        c = m.getText().createTextCursorByRange(m.getText().getStart())
        c.gotoRange(r, True)
        return len(c.getString())
    try:
        out.sort(key=key)
    except Exception:
        pass
    return out


def _fields(m):
    out = []
    en = m.getTextFields().createEnumeration()
    while en.hasMoreElements():
        f = en.nextElement()
        try:
            if f.supportsService("com.sun.star.text.textfield.Annotation"):
                continue
            if f.getAnchor().getText().getImplementationName() == "SwXHeadFootText":
                continue
            out.append(f)
        except Exception:
            pass

    def key(f):
        try:
            c = m.getText().createTextCursorByRange(m.getText().getStart())
            c.gotoRange(f.getAnchor().getStart(), True)
            return len(c.getString())
        except Exception:
            return 0
    out.sort(key=key)
    return out


FIELD_NAMES = {"PageNumber": "Page", "PageCount": "NumPages", "DateTime": "Date",
               "SetExpression": "Seq", "GetReference": "Ref", "Bookmark": "Ref",
               "Author": "Author", "FileName": "FileName", "DocInfo.Title": "Title",
               "WordCount": "NumWords", "CharacterCount": "NumChars", "URL": "Hyperlink",
               "Input": "Fillin", "Macro": "MacroButton", "JumpEdit": "MacroButton",
               "TableOfContents": "TOC"}


def _field_name(f):
    for svc in f.getSupportedServiceNames():
        if svc.startswith("com.sun.star.text.textfield.") or \
                svc.startswith("com.sun.star.text.TextField."):
            kind = svc.split(".")[-1]
            if kind in ("TextField", "TextContent"):
                continue
            return FIELD_NAMES.get(kind, kind)
    return "Field"


def _comment_authors(m):
    out = []
    en = m.getTextFields().createEnumeration()
    while en.hasMoreElements():
        f = en.nextElement()
        try:
            if f.supportsService("com.sun.star.text.textfield.Annotation"):
                out.append(f.Author)
        except Exception:
            pass
    return out


def _goto_comment_by(m, author):
    vc = docapi.view_cursor(m)
    found = []
    en = m.getTextFields().createEnumeration()
    while en.hasMoreElements():
        f = en.nextElement()
        try:
            if f.supportsService("com.sun.star.text.textfield.Annotation") and \
                    f.Author == author:
                found.append(f.getAnchor())
        except Exception:
            pass
    for a in found:
        try:
            if m.getText().compareRegionStarts(vc.getEnd(), a.getStart()) > 0:
                vc.gotoRange(a.getStart(), False)
                return True
        except Exception:
            pass
    if found:
        vc.gotoRange(found[0].getStart(), False)
        return True
    return False


GOTO_KINDS = ["Page", "Section", "Line", "Bookmark", "Comment", "Footnote", "Endnote",
              "Field", "Table", "Graphic", "Equation", "Object", "Heading"]


class DocDialogs:
    # ====================================================== Find and Replace
    def replace(self):
        self.find_replace(1)

    def goto(self):
        self.find_replace(2)

    def find_replace(self, tab=0, text=None):
        if getattr(self.win.engine, "native", False):
            from .native import find
            return find.dialog(self.win, tab, text)
        m = self._model_or_warn()
        if m is None:
            return
        if getattr(self, "_fr", None) is not None:
            self._fr["nb"].set_current_page(tab)
            self._fr["dlg"].present()
            return
        dlg = Gtk.Window(title="Find and Replace", transient_for=self.win)
        dlg.set_type_hint(1)   # dialog
        dlg.set_resizable(False)
        dlg.get_style_context().add_class("folio-dialog")
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        outer.set_border_width(12)
        dlg.add(outer)
        nb = Gtk.Notebook()
        outer.pack_start(nb, True, True, 0)
        st = {"dlg": dlg, "nb": nb}
        self._fr = st
        sel = docapi.selection_text(m)
        initial = text or (sel if sel and "\n" not in sel and len(sel) < 80 else
                           getattr(self, "_last_find", ""))

        def page(with_replace):
            b = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            b.set_border_width(10)
            f = Gtk.ComboBoxText.new_with_entry()
            f.get_child().set_text(initial)
            f.get_child().set_width_chars(40)
            rows = [["Fi_nd what:", f]]
            r = None
            if with_replace:
                r = Gtk.ComboBoxText.new_with_entry()
                rows.append(["Replace w_ith:", r])
            b.pack_start(grid(rows), False, False, 0)
            return b, f, r
        p_find, f1, _ = page(False)
        p_rep, f2, rep = page(True)
        # keep the two "find what" boxes in step
        f1.get_child().connect("changed", lambda e: f2.get_child().get_text() != e.get_text()
                               and f2.get_child().set_text(e.get_text()))
        f2.get_child().connect("changed", lambda e: f1.get_child().get_text() != e.get_text()
                               and f1.get_child().set_text(e.get_text()))
        # options (shared): the original's "More >>" part
        from . import findopts
        ffmt, rfmt = findopts.Format(), findopts.Format()
        st["ffmt"], st["rfmt"] = ffmt, rfmt
        opts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        opts.set_margin_top(4)
        opts.pack_start(heading("Search Options"), False, False, 0)
        direction = combo(["All", "Down", "Up"], 0)
        opts.pack_start(grid([["Search:", direction]]), False, False, 0)
        case = Gtk.CheckButton.new_with_mnemonic("Matc_h case")
        whole = Gtk.CheckButton.new_with_mnemonic("Find whole words onl_y")
        wild = Gtk.CheckButton.new_with_mnemonic("_Use wildcards")
        sounds = Gtk.CheckButton.new_with_mnemonic("Sounds li_ke (English)")
        forms = Gtk.CheckButton.new_with_mnemonic("Find all _word forms (English)")
        prefix = Gtk.CheckButton.new_with_mnemonic("Match prefi_x")
        suffix = Gtk.CheckButton.new_with_mnemonic("Match _suffix")
        ign_p = Gtk.CheckButton.new_with_mnemonic("Ignore punctuation charac_ters")
        ign_w = Gtk.CheckButton.new_with_mnemonic("Ignore _white-space characters")
        og = Gtk.Grid(column_spacing=40, row_spacing=2)
        for i, w in enumerate((case, whole, wild, sounds, forms)):
            og.attach(w, 0, i, 1, 1)
        for i, w in enumerate((prefix, suffix, None, ign_p, ign_w)):
            if w is not None:
                og.attach(w, 1, i, 1, 1)
        opts.pack_start(og, False, False, 0)
        st["checks"] = {"case": case, "whole": whole, "wild": wild, "sounds": sounds,
                        "forms": forms, "prefix": prefix, "suffix": suffix,
                        "ign_punct": ign_p, "ign_space": ign_w}

        def opt_sens(*_):
            w_, s_, f_ = wild.get_active(), sounds.get_active(), forms.get_active()
            exclusive = w_ or s_ or f_
            for b in (prefix, suffix, ign_p, ign_w):
                b.set_sensitive(not exclusive)
            whole.set_sensitive(not exclusive and not prefix.get_active() and
                                not suffix.get_active())
            case.set_sensitive(not (w_ or s_ or f_))
            wild.set_sensitive(not (s_ or f_))
            sounds.set_sensitive(not (w_ or f_))
            forms.set_sensitive(not (w_ or s_))
        for b in st["checks"].values():
            b.connect("toggled", opt_sens)
        # Format / Special / No Formatting
        fmt_btn = Gtk.MenuButton(label="F_ormat", use_underline=True)
        special = Gtk.MenuButton(label="Sp_ecial", use_underline=True)
        nofmt = Gtk.Button(label="No Formatt_ing", use_underline=True)
        nofmt.set_sensitive(False)
        smenu = Gtk.Menu()
        for label, code in SPECIAL_CODES:
            it = Gtk.MenuItem(label=label)

            def ins(_i, code=code):
                entry = rep.get_child() if getattr(self, "_fr_last_focus", "") == "rep" \
                    else (f2.get_child() if nb.get_current_page() == 1 else f1.get_child())
                pos = entry.get_position()
                entry.insert_text(code, pos)
                entry.set_position(pos + len(code))
            it.connect("activate", ins)
            smenu.append(it)
        smenu.show_all()
        special.set_popup(smenu)
        rep.get_child().connect("focus-in-event", lambda *_: setattr(
            self, "_fr_last_focus", "rep") or False)
        for fbox in (f1, f2):
            fbox.get_child().connect("focus-in-event", lambda *_: setattr(
                self, "_fr_last_focus", "find") or False)

        def cur_fmt():
            return rfmt if getattr(self, "_fr_last_focus", "") == "rep" and \
                nb.get_current_page() == 1 else ffmt

        fmt_labels = []

        def fmt_changed():
            for lab, f in fmt_labels:
                lab.set_text(("Format:    " + f.text()) if not f.empty() else "")
                lab.set_visible(not f.empty())
            nofmt.set_sensitive(not cur_fmt().empty())

        def fmt_popup(*_):
            fmt_btn.set_popup(findopts.format_menu(dlg, cur_fmt(), fmt_changed))
        fmt_btn.connect("pressed", fmt_popup)
        fmt_popup()
        nofmt.connect("clicked", lambda *_: (cur_fmt().clear(), fmt_changed()))
        for fbox in (f1, f2, rep):
            fbox.get_child().connect("focus-in-event",
                                     lambda *_: (GLib.idle_add(fmt_changed), False)[1])
        sb = Gtk.Box(spacing=6)
        sb.pack_start(fmt_btn, False, False, 0)
        sb.pack_start(special, False, False, 0)
        sb.pack_start(nofmt, False, False, 0)
        opts.pack_start(heading("Find"), False, False, 2)
        opts.pack_start(sb, False, False, 4)
        for parent, f in ((p_find, ffmt), (p_rep, ffmt), (p_rep, rfmt)):
            lab = Gtk.Label(xalign=0)
            lab.set_no_show_all(True)
            lab.get_style_context().add_class("dim-label")
            fmt_labels.append((lab, f))
            parent.pack_start(lab, False, False, 0)
        more = Gtk.Button(label="_More >>", use_underline=True)
        opts.set_no_show_all(True)

        def toggle_more(*_):
            show = not opts.get_visible()
            if show:
                opts.show_all()
                opts.show()
            else:
                opts.hide()
            more.set_label("<< _Less" if show else "_More >>")
        more.connect("clicked", toggle_more)
        exp = opts
        # Go To page
        p_goto = Gtk.Box(spacing=12)
        p_goto.set_border_width(10)
        sw, kinds, _store = listbox(GOTO_KINDS, height=150, width=140)
        kinds.get_selection().select_path(Gtk.TreePath(0))
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        what_lab = Gtk.Label(label="Enter page number:", xalign=0)
        what = Gtk.ComboBoxText.new_with_entry()
        what.get_child().set_width_chars(30)
        hint = Gtk.Label(label="Enter + and - to move relative to the current location. "
                               "Example: +4 will move forward four items.", xalign=0)
        hint.set_line_wrap(True)
        hint.set_max_width_chars(40)
        hint.get_style_context().add_class("dim-label")
        right.pack_start(what_lab, False, False, 0)
        right.pack_start(what, False, False, 0)
        right.pack_start(hint, False, False, 0)
        p_goto.pack_start(Gtk.Label(label="G_o to what:", xalign=0, use_underline=True),
                          False, False, 0)
        p_goto.pack_start(sw, False, False, 0)
        p_goto.pack_start(right, True, True, 0)

        def kind_changed(_s):
            k = list_selected(kinds) or "Page"
            what.remove_all()
            items = []
            if k == "Bookmark":
                items = docapi.bookmarks(m)
                what_lab.set_text("Enter bookmark name:")
            elif k == "Heading":
                items = [t for _l, t, _p in docapi.headings(m)]
                what_lab.set_text("Enter heading:")
            elif k == "Comment":
                items = ["Any reviewer"] + sorted({a for a in _comment_authors(m)})
                what_lab.set_text("Enter reviewer's name:")
            elif k == "Field":
                items = ["Any field"] + sorted({_field_name(f) for f in _fields(m)})
                what_lab.set_text("Enter field name:")
            else:
                what_lab.set_text("Enter %s number:" % k.lower())
            for it in items:
                what.append_text(it)
            what.get_child().set_text(items[0] if items and k not in ("Comment", "Field")
                                      else "")
            upd_buttons()
        kinds.get_selection().connect("changed", kind_changed)

        nb.append_page(p_find, Gtk.Label(label="Find", use_underline=True))
        nb.append_page(p_rep, Gtk.Label(label="Replace"))
        nb.append_page(p_goto, Gtk.Label(label="Go To"))
        bb = Gtk.Box(spacing=6)
        bb.pack_start(more, False, False, 0)
        hl_btn = Gtk.MenuButton(label="Reading Highlig_ht", use_underline=True)
        hl_menu = Gtk.Menu()
        for label, fn in (("Highlight All", lambda: do_highlight()),
                          ("Clear Highlighting", lambda: self.win.reading_hl.clear())):
            it = Gtk.MenuItem(label=label)
            it.connect("activate", lambda _i, fn=fn: fn())
            hl_menu.append(it)
        hl_menu.show_all()
        hl_btn.set_popup(hl_menu)
        in_btn = Gtk.MenuButton(label="Find _In", use_underline=True)
        in_menu = Gtk.Menu()
        for label, where in (("Main Document", "main"), ("Headers and Footers", "hf")):
            it = Gtk.MenuItem(label=label)
            it.connect("activate", lambda _i, w=where: find_in(w))
            in_menu.append(it)
        in_menu.show_all()
        in_btn.set_popup(in_menu)
        b_rep = Gtk.Button(label="_Replace", use_underline=True)
        b_all = Gtk.Button(label="Replace _All", use_underline=True)
        b_next = Gtk.Button(label="_Find Next", use_underline=True)
        b_prev = Gtk.Button(label="Find Pre_vious", use_underline=True)
        b_go = Gtk.Button(label="Go _To", use_underline=True)
        b_close = Gtk.Button(label="Cancel")
        b_next.get_style_context().add_class("suggested-action")
        bb.pack_end(b_close, False, False, 0)
        for w in (b_go, b_next, b_prev, b_all, b_rep, in_btn, hl_btn):
            bb.pack_end(w, False, False, 0)
        outer.pack_start(bb, False, False, 0)
        outer.pack_start(exp, False, False, 0)
        status = Gtk.Label(label="", xalign=0)
        status.get_style_context().add_class("dim-label")
        outer.pack_start(status, False, False, 0)

        def upd_buttons(*_):
            p = nb.get_current_page()
            b_rep.set_visible(p == 1)
            b_all.set_visible(p == 1)
            b_next.set_visible(p in (0, 1))
            b_prev.set_visible(p in (0, 1))
            b_go.set_visible(p == 2)
            hl_btn.set_visible(p == 0)
            in_btn.set_visible(p == 0)
            more.set_visible(p in (0, 1))
            if p == 2:
                exp.hide()
            elif more.get_label().startswith("<<"):
                exp.show()
            if p == 2:
                k = list_selected(kinds) or "Page"
                b_go.set_label("_Go To" if what.get_child().get_text().strip() else
                               ("_Next" if k != "Page" else "_Go To"))
        nb.connect("switch-page", lambda nb, pg, n: GLib.idle_add(upd_buttons))
        what.get_child().connect("changed", upd_buttons)

        def opt_values():
            return {k: (b.get_active() and b.get_sensitive()) for k, b in st["checks"].items()}

        def descriptor(repl=None, use_format=True):
            sd = m.createReplaceDescriptor()
            s = f1.get_child().get_text()
            self._last_find = s
            o = opt_values()
            regex = False
            if o["wild"] or o["sounds"] or o["forms"] or o["prefix"] or o["suffix"] or \
                    o["ign_punct"] or o["ign_space"]:
                s, regex = findopts.search_pattern(
                    s, o, m.getText().getString() if o["sounds"] else "")
                if repl is not None and "^" in repl:
                    repl = special_to_replacement(repl)
            elif "^" in s:
                s, regex = special_to_regex(s), True
                if repl is not None:
                    repl = special_to_replacement(repl)
            elif repl is not None and "^" in repl:
                s, regex = re.escape(s), True
                repl = special_to_replacement(repl)
            if not s and use_format and not ffmt.empty():
                if ffmt.style and not ffmt.attrs:
                    sd.SearchStyles = True
                    s = ffmt.style
                else:
                    sd.setSearchAttributes(ffmt.props())
                    sd.ValueSearch = True
            sd.SearchString = s
            sd.SearchCaseSensitive = o["case"] or o["wild"]
            sd.SearchWords = o["whole"] and not regex
            sd.SearchRegularExpression = regex
            if repl is not None:
                sd.ReplaceString = repl
            return sd

        def searching():
            return bool(f1.get_child().get_text()) or not ffmt.empty()

        def find(forward=True):
            if not searching():
                return None
            dirn = direction.get_active()
            if dirn == 2:
                forward = False
            sd = descriptor()
            sd.SearchBackwards = not forward
            vc = docapi.view_cursor(m)
            start = vc.getEnd() if forward else vc.getStart()
            wrapped = False
            found = m.findNext(start, sd)
            for _i in range(500):
                if found is None and dirn == 0 and not wrapped:
                    # wrap around
                    cur = m.getText().createTextCursor()
                    if forward:
                        cur.gotoStart(False)
                    else:
                        cur.gotoEnd(False)
                    found = m.findNext(cur.getStart(), sd)
                    wrapped = True
                if found is None or findopts.matches_format(found, ffmt) or \
                        not f1.get_child().get_text():
                    break
                found = m.findNext(found.getEnd() if forward else found.getStart(), sd)
            status.set_text("The search wrapped around the document." if wrapped and found
                            else "")
            if found is None:
                status.set_text("")
                if dirn == 0 or not self.confirm(
                        "We reached the %s of the document. Do you want to continue "
                        "searching at the %s?" % (("end", "beginning") if forward else
                                                  ("beginning", "end")), yes="Yes", no="No"):
                    if dirn == 0:
                        self.message("We couldn't find what you were looking for.",
                                     title="Find and Replace")
                    return None
                cur = m.getText().createTextCursor()
                cur.gotoStart(False) if forward else cur.gotoEnd(False)
                found = m.findNext(cur.getStart(), sd)
                if found is None:
                    self.message("We couldn't find what you were looking for.",
                                 title="Find and Replace")
                    return None
            docapi.select(m, found)
            return found

        def all_matches(where="main"):
            sd = descriptor()
            res = m.findAll(sd)
            out = []
            for i in range(res.getCount()):
                r = res.getByIndex(i)
                try:
                    in_main = r.getText().getImplementationName() != "SwXHeadFootText"
                except Exception:
                    in_main = True
                if (where == "main") != in_main:
                    continue
                if f1.get_child().get_text() and not findopts.matches_format(r, ffmt):
                    continue
                out.append(r)
            return out

        def do_highlight():
            if not searching():
                return
            n = self.win.reading_hl.highlight(all_matches("main"))
            status.set_text("%d item%s highlighted" % (n, "" if n == 1 else "s")
                            if n else "")
            if not n:
                self.message("We couldn't find what you were looking for.",
                             title="Find and Replace")

        def find_in(where):
            if not searching():
                return
            found = all_matches(where)
            if not found:
                self.message("We couldn't find what you were looking for.",
                             title="Find and Replace")
                return
            try:
                if len(found) == 1:
                    docapi.select(m, found[0])
                else:
                    sd = descriptor()
                    res = m.findAll(sd)
                    docapi.controller(m).select(res)
            except Exception as e:
                print("find in:", e)
            status.set_text("Folio found %d item%s matching this criteria."
                            % (len(found), "" if len(found) == 1 else "s"))

        def do_replace(*_):
            s = f1.get_child().get_text()
            if not searching():
                return
            vc = docapi.view_cursor(m)
            cur_sel = vc.getString()
            matches = cur_sel == s if case.get_active() else cur_sel.lower() == s.lower()
            if wild.get_active() and cur_sel:
                import re
                try:
                    matches = re.fullmatch(s, cur_sel, 0 if case.get_active() else re.I) \
                        is not None
                except re.error:
                    matches = False
            if not s and not ffmt.empty() and not vc.isCollapsed():
                matches = findopts.matches_format(vc, ffmt)
            elif any(b.get_active() and b.get_sensitive() for k, b in st["checks"].items()
                     if k not in ("case", "whole")) and cur_sel:
                matches = True       # what Find Next selected
            if matches and not vc.isCollapsed():
                r = vc.getText().createTextCursorByRange(vc)
                if rep.get_child().get_text() or (s and rfmt.empty()):
                    r.setString(rep.get_child().get_text())
                findopts.apply_format(r, rfmt)
                vc.collapseToEnd()
            find(True)

        def do_all(*_):
            s = f1.get_child().get_text()
            if not searching():
                return
            if ffmt.empty() and rfmt.empty():
                n = m.replaceAll(descriptor(rep.get_child().get_text()))
            else:
                found = all_matches("main")
                um = m.getUndoManager()
                um.enterUndoContext("Replace All")
                try:
                    for r in found:
                        c = r.getText().createTextCursorByRange(r)
                        if rep.get_child().get_text() or (s and rfmt.empty()):
                            c.setString(rep.get_child().get_text())
                        findopts.apply_format(c, rfmt)
                finally:
                    um.leaveUndoContext()
                n = len(found)
            if n:
                self.message("All done. We made %d replacement%s." % (n, "" if n == 1 else "s"),
                             title="Find and Replace")
            else:
                self.message("We couldn't find what you were looking for.",
                             title="Find and Replace")

        def do_goto(*_):
            k = list_selected(kinds) or "Page"
            val = what.get_child().get_text().strip()
            self._goto(m, k, val)
        b_next.connect("clicked", lambda *_: find(True))
        b_prev.connect("clicked", lambda *_: find(False))
        b_rep.connect("clicked", do_replace)
        b_all.connect("clicked", do_all)
        b_go.connect("clicked", do_goto)
        b_close.connect("clicked", lambda *_: dlg.destroy())
        f1.get_child().connect("activate", lambda *_: find(True))
        f2.get_child().connect("activate", lambda *_: find(True))
        what.get_child().connect("activate", do_goto)

        def on_key(w, ev):
            from gi.repository import Gdk
            if ev.keyval == Gdk.KEY_Escape:
                dlg.destroy()
                return True
            return False
        dlg.connect("key-press-event", on_key)
        dlg.connect("destroy", lambda *_: setattr(self, "_fr", None))
        dlg.show_all()
        nb.set_current_page(tab)
        upd_buttons()
        kind_changed(None)
        if tab == 2:
            what.get_child().grab_focus()
        else:
            (f1 if tab == 0 else f2).get_child().grab_focus()

    def _goto(self, m, kind, val):
        vc = docapi.view_cursor(m)
        rel = val[:1] in "+-" and val[1:].isdigit()
        if kind == "Page":
            try:
                cur = vc.getPage()
                n = int(val) if not rel else cur + int(val)
            except ValueError:
                n = vc.getPage() + 1
            pages = docapi.statistics(m).get("PageCount", 1)
            vc.jumpToPage(max(1, min(pages, n)))
            vc.jumpToStartOfPage()
            return
        if kind == "Line":
            try:
                n = int(val) if val else 1
            except ValueError:
                return
            if rel or not val:
                if n < 0:
                    vc.goUp(-n, False)
                else:
                    vc.goDown(n or 1, False)
                vc.gotoStartOfLine(False)
                return
            vc.gotoStart(False)
            vc.goDown(max(0, n - 1), False)
            return
        if kind == "Section":
            starts = _section_starts(m)
            if len(starts) <= 1 and val and not rel and val != "1":
                self.message("There's only one section in this document.")
            cur = 0
            for i, r in enumerate(starts):
                try:
                    if m.getText().compareRegionStarts(r, vc.getStart()) >= 0:
                        cur = i
                except Exception:
                    pass
            try:
                n = int(val) - 1 if val and not rel else cur + (int(val) if rel else 1)
            except ValueError:
                n = cur + 1
            n = max(0, min(len(starts) - 1, n))
            vc.gotoRange(starts[n], False)
            return
        if kind == "Comment" and val and val != "Any reviewer" and not rel:
            if not _goto_comment_by(m, val):
                self.message("There are no more comments by %s." % val)
            return
        if kind == "Field":
            fields = _fields(m)
            if val and val != "Any field" and not rel:
                fields = [f for f in fields if _field_name(f) == val]
            if not fields:
                self.message("There are no fields in this document.")
                return
            idx = getattr(self, "_goto_idx", {}).get("Field", -1)
            idx = (idx + (int(val) if rel else 1)) % len(fields)
            self._goto_idx = dict(getattr(self, "_goto_idx", {}), Field=idx)
            a = fields[idx].getAnchor()
            vc.gotoRange(a.getStart(), False)
            vc.gotoRange(a.getEnd(), True)
            return
        if kind in ("Footnote", "Endnote") and val.isdigit():
            coll = m.getFootnotes() if kind == "Footnote" else m.getEndnotes()
            n = int(val)
            if not 1 <= n <= coll.getCount():
                self.message("There's no %s %d." % (kind.lower(), n))
                return
            vc.gotoRange(coll.getByIndex(n - 1).getAnchor().getStart(), False)
            return
        if kind == "Bookmark":
            if not docapi.goto_bookmark(m, val):
                self.message("There's no bookmark called “%s”." % val)
            return
        if kind == "Heading":
            for _l, t, p in docapi.headings(m):
                if t == val or not val:
                    docapi.goto_start(m, p)
                    return
            return
        if kind in ("Comment", "Footnote", "Endnote"):
            back = val.startswith("-")
            if not docapi.goto_next(m, kind.lower(), forward=not back):
                self.message("There are no more %ss." % kind.lower())
            return
        coll = {"Table": m.getTextTables, "Graphic": m.getGraphicObjects,
                "Equation": None, "Object": m.getEmbeddedObjects}.get(kind)
        items = []
        if kind == "Equation":
            items = docapi.formulas(m)
        elif kind == "Graphic":
            dp = m.getDrawPage()
            items = [dp.getByIndex(i) for i in range(dp.getCount())]
            items = [x for x in items if not x.supportsService(
                "com.sun.star.text.TextEmbeddedObject")]
        elif coll is not None:
            c = coll()
            items = [c.getByName(n) for n in c.getElementNames()]
        if not items:
            self.message("There are no %ss in this document." % kind.lower())
            return
        try:
            n = int(val) if val and not rel else None
        except ValueError:
            n = None
        idx = getattr(self, "_goto_idx", {}).get(kind, -1)
        idx = (n - 1) if n else (idx + (int(val) if rel else 1))
        idx %= len(items)
        self._goto_idx = dict(getattr(self, "_goto_idx", {}), **{kind: idx})
        try:
            anchor = items[idx].getAnchor()
            vc.gotoRange(anchor.getStart(), False)
            docapi.select(m, items[idx])
        except Exception:
            pass

    # ============================================================ Word count
    def word_count(self):
        m = self._model_or_warn()
        if m is None:
            return
        sel = docapi.selection_text(m)
        stats = docapi.statistics(m)
        if sel:
            c = docapi.count_text(sel)
            pages = stats.get("PageCount", 1)
        else:
            c = {"words": stats.get("WordCount", 0), "chars": stats.get("CharacterCount", 0),
                 "nospace": stats.get("NonWhitespaceCharacterCount", 0),
                 "paras": stats.get("ParagraphCount", 0)}
            pages = stats.get("PageCount", 1)
        d = FDialog(self.win, "Word Count", buttons=(("Close", Gtk.ResponseType.CLOSE),))
        d.add(Gtk.Label(label="Statistics:", xalign=0))
        rows = []
        if pages is not None:
            rows.append(("Pages", pages))
        rows += [("Words", c["words"]), ("Characters (no spaces)", c["nospace"]),
                 ("Characters (with spaces)", c["chars"]), ("Paragraphs", c["paras"])]
        lines = count_lines(m, bool(sel))
        if lines:
            rows.append(("Lines", lines))
        g = Gtk.Grid(column_spacing=40, row_spacing=4)
        for i, (k, v) in enumerate(rows):
            g.attach(Gtk.Label(label=k, xalign=0), 0, i, 1, 1)
            g.attach(Gtk.Label(label="{:,}".format(v), xalign=1), 1, i, 1, 1)
        g.set_margin_start(12)
        d.add(g)
        inc = Gtk.CheckButton(label="Include textboxes, footnotes and endnotes")
        inc.set_active(True)
        d.add(inc)
        d.ask()
        d.done()

    # ================================================================== Zoom
    def zoom_dialog(self):
        cur = int(round(self.eng.view.get_zoom() * 100))
        d = FDialog(self.win, "Zoom")
        d.add(heading("Zoom to"))
        g = Gtk.Grid(column_spacing=24, row_spacing=4)
        grp = None
        opts = [("200%", 200), ("100%", 100), ("75%", 75), ("Page width", "width"),
                ("Text width", "text"), ("Whole page", "page")]
        radios = []
        for i, (label, val) in enumerate(opts):
            rb = Gtk.RadioButton.new_with_label_from_widget(grp, label)
            grp = grp or rb
            radios.append((rb, val))
            g.attach(rb, i // 3, i % 3, 1, 1)
            if val == cur:
                rb.set_active(True)
        d.add(g)
        many = Gtk.RadioButton.new_with_mnemonic_from_widget(grp, "_Many pages:")
        many_n = [2]
        many_btn = Gtk.MenuButton()
        many_lab = Gtk.Label(label="2 pages")
        many_btn.add(many_lab)
        mpop = Gtk.Popover.new(many_btn)
        mg = Gtk.Grid(column_spacing=2, row_spacing=2)
        mg.set_border_width(6)
        for i in range(8):
            b = Gtk.Button(label="▯")
            b.set_tooltip_text("%d page%s" % (i + 1, "" if i == 0 else "s"))

            def pick(_b, n=i + 1):
                many_n[0] = n
                many_lab.set_text("%d page%s" % (n, "" if n == 1 else "s"))
                many.set_active(True)
                mpop.popdown()
                prev.queue_draw()
            b.connect("clicked", pick)
            mg.attach(b, i % 4, i // 4, 1, 1)
        mg.show_all()
        mpop.add(mg)
        many_btn.set_popover(mpop)
        g.attach(many, 2, 0, 1, 1)
        g.attach(many_btn, 2, 1, 1, 1)
        radios.append((many, "many"))
        pct = Gtk.SpinButton.new_with_range(10, 500, 1)
        pct.set_value(cur)
        d.add(grid([["P_ercent:", pct, Gtk.Label(label="%")]]))

        def pdraw(cr, W, H):
            cr.set_source_rgb(1, 1, 1)
            cr.paint()
            choice = next((v for rb, v in radios if rb.get_active()), None)
            if choice == "many":
                n = many_n[0]
                pw = min((W - 10) / n - 6, (H - 10) * 0.77)
                for i in range(n):
                    x = 5 + i * (pw + 6)
                    cr.set_source_rgb(0.4, 0.4, 0.4)
                    cr.rectangle(x, 5, pw, pw / 0.77)
                    cr.stroke()
                return
            cr.set_source_rgb(0, 0, 0)
            cr.select_font_face("Sans")
            cr.set_font_size(max(4, 11 * pct.get_value() / 100.0))
            cr.move_to(8, H / 2 + 5)
            cr.show_text("AaBbCcDdEeXxYyZz")
        d.add(heading("Preview"))
        prev = Preview(pdraw, 300, 70)
        d.add(prev)
        pct.connect("value-changed", lambda *_: prev.queue_draw())

        def on_rb(rb, val):
            if rb.get_active() and isinstance(val, int):
                pct.set_value(val)
            prev.queue_draw()
        for rb, val in radios:
            rb.connect("toggled", on_rb, val)
        if d.ask() == Gtk.ResponseType.OK:
            choice = next((v for rb, v in radios if rb.get_active()), None)
            if choice == "width":
                self.zoom_page_width()
            elif choice == "text":
                self.zoom_page_width(text=True)
            elif choice == "page":
                self.zoom_one_page()
            elif choice == "many":
                self.zoom_pages(many_n[0])
            else:
                self.win.status.set_zoom(pct.get_value() / 100.0)
        d.done()

    def zoom_100(self):
        self.win.status.set_zoom(1.0)

    def _page_px(self):
        """Page width/height in document pixels at zoom 1.0."""
        ed = getattr(self.eng, "ed", None) if getattr(self.eng, "native", False) else None
        if ed is not None and ed.page_count():
            w, h = ed.page_size(0)
            return w * 96 / 72.0, h * 96 / 72.0, None
        m = self.model
        if m is not None:
            ps = docapi.page_setup(m)
            return ps["width"] / 2540.0 * 96, ps["height"] / 2540.0 * 96, ps
        return 816, 1056, None

    def _single_column(self):
        v = self.eng.view
        if getattr(self.eng, "native", False) and (v.columns > 1 or v.side):
            v.set_page_layout(1)

    def zoom_page_width(self, text=False):
        self._single_column()
        w, h, ps = self._page_px()
        if text and ps:
            w = (ps["width"] - ps["left"] - ps["right"]) / 2540.0 * 96
        avail = self.win.canvas.get_allocation().width - 40
        self.win.status.set_zoom(max(0.1, min(5.0, avail / w)))

    def zoom_one_page(self):
        self._single_column()
        w, h, _ = self._page_px()
        a = self.win.canvas.get_allocation()
        self.win.status.set_zoom(max(0.1, min(5.0, min((a.width - 40) / w, (a.height - 30) / h))))

    def zoom_pages(self, n):
        """n pages in view at once (the engine lays pages out one under
        another, so they are fitted top to bottom)."""
        if getattr(self.eng, "native", False) and n > 1:
            # the new engine puts them side by side
            w, h, _ = self._page_px()
            a = self.win.canvas.get_allocation()
            self.eng.view.set_page_layout(n)
            z = min((a.width - 20 * (n + 1)) / (w * n), (a.height - 30) / h)
            self.win.status.set_zoom(max(0.1, min(5.0, z)))
            return
        self._single_column()
        w, h, _ = self._page_px()
        a = self.win.canvas.get_allocation()
        z = min((a.width - 40) / w, (a.height - 30) / (h * n + 20 * (n - 1)))
        self.win.status.set_zoom(max(0.1, min(5.0, z)))

    def zoom_multiple(self):
        if getattr(self.eng, "native", False):
            self.win.act_multiple_pages()
            return
        self.zoom_one_page()
        self.win.status.set_zoom(self.eng.view.get_zoom() / 2)

    # ============================================================ Page setup
    def page_setup(self, tab=0):
        if getattr(self.eng, "native", False) or self._model_or_warn() is not None:
            from . import pagesetup
            pagesetup.dialog(self.win, tab)

    def margins(self, preset):
        if getattr(self.eng, "native", False):
            from .native import pagesetup as NP
            vals = MARGIN_PRESETS[preset] if isinstance(preset, str) else preset
            NP.margins(self.win, *vals, mirrored=preset == "mirrored")
            return
        m = self._model_or_warn()
        if m is None:
            return
        from . import pagesetup
        if preset == "mirrored":
            pagesetup.mirrored_margins(m)
            return
        if isinstance(preset, str):
            t, b, l, r = MARGIN_PRESETS[preset]
        else:
            t, b, l, r = preset
        docapi.set_page(m, top=t, bottom=b, left=l, right=r)
        ps = docapi.page_style(m)
        if pagesetup._layout(ps) == "MIRRORED":
            pagesetup._set_layout(ps, "ALL")

    def orientation(self, landscape):
        if getattr(self.eng, "native", False):
            from .native import pagesetup as NP
            NP.orientation(self.win, landscape)
            return
        m = self._model_or_warn()
        if m is not None:
            docapi.set_page(m, landscape=bool(landscape))

    def paper(self, size):
        if getattr(self.eng, "native", False):
            from .native import pagesetup as NP
            NP.paper(self.win, size[0], size[1])
            return
        m = self._model_or_warn()
        if m is not None:
            docapi.set_page(m, width=size[0], height=size[1])

    def columns(self, n):
        if getattr(self.eng, "native", False) and n != "more":
            from .native import pagesetup as NP
            NP.columns(self.win, int(n))
            return
        m = self._model_or_warn()
        if m is None:
            return
        if n == "more":
            self.page_setup(2)
            return
        docapi.set_columns(m, int(n))

    def page_color(self, color):
        m = self._model_or_warn()
        if m is not None:
            docapi.page_color(m, color)

    # ============================================================== Watermark
    def watermark(self, text):
        if getattr(self.eng, "native", False):
            ed = self.eng.ed
            if text:
                ed.set_watermark("text", text=text, font="Calibri")
            else:
                ed.set_watermark("none")
            self.eng.view.document_changed()
            return
        if not text:
            self.eng.command(".uno:Watermark", {"Text": ""})
            m = self.model
            if m is not None:
                remove_picture_watermarks(m)
            return
        self.eng.command(".uno:Watermark", {"Text": text, "Font": "Carlito",
                                            "Angle": ("short", 45), "Transparency": ("short", 50),
                                            "Color": ("long", 0xC0C0C0)})

    def watermark_dialog(self):
        d = FDialog(self.win, "Printed Watermark", buttons=(
            ("OK", Gtk.ResponseType.OK), ("Apply", Gtk.ResponseType.APPLY),
            ("Cancel", Gtk.ResponseType.CANCEL)))
        none = Gtk.RadioButton.new_with_mnemonic(None, "_No watermark")
        picw = Gtk.RadioButton.new_with_mnemonic_from_widget(none, "Pi_cture watermark")
        textw = Gtk.RadioButton.new_with_mnemonic_from_widget(none, "Te_xt watermark")
        textw.set_active(True)
        d.add(none)
        d.add(picw)
        pic_path = [None]
        sel_btn = Gtk.Button(label="Select _Picture...", use_underline=True)
        pic_lab = Gtk.Label(xalign=0)
        pic_lab.set_ellipsize(3)
        pic_lab.set_max_width_chars(30)
        scale = combo(["Auto", "500%", "200%", "150%", "100%", "50%"], 0, entry=True)
        wash = Gtk.CheckButton.new_with_mnemonic("_Washout")
        wash.set_active(True)
        pbody = grid([[sel_btn, pic_lab], ["Sc_ale:", scale, wash]])
        pbody.set_margin_start(20)
        d.add(pbody)

        def pick_pic(*_):
            path = self.pick_file("Insert Picture", ["*.png", "*.jpg", "*.jpeg", "*.gif",
                                                     "*.bmp", "*.svg", "*.tif", "*.tiff"],
                                  "All Pictures")
            if path:
                pic_path[0] = path
                pic_lab.set_text(os.path.basename(path))
                picw.set_active(True)
        sel_btn.connect("clicked", pick_pic)
        picw.connect("toggled", lambda w: pbody.set_sensitive(w.get_active()))
        pbody.set_sensitive(False)
        d.add(textw)
        presets = {
            "English (United States)": ["ASAP", "CONFIDENTIAL", "COPY", "DO NOT COPY", "DRAFT", "ORIGINAL",
                                        "PERSONAL", "SAMPLE", "TOP SECRET", "URGENT"],
            "English (United Kingdom)": ["ASAP", "CONFIDENTIAL", "COPY", "DO NOT COPY", "DRAFT", "ORIGINAL",
                                         "PERSONAL", "SAMPLE", "TOP SECRET", "URGENT"],
            "French (France)": ["BROUILLON", "CONFIDENTIEL", "COPIE", "ÉCHANTILLON", "ORIGINAL", "PERSONNEL",
                                "SECRET", "URGENT"],
            "German (Germany)": ["ENTWURF", "KOPIE", "MUSTER", "NICHT KOPIEREN", "ORIGINAL", "PERSÖNLICH",
                                 "STRENG GEHEIM", "VERTRAULICH", "DRINGEND"],
            "Spanish (Spain)": ["BORRADOR", "CONFIDENCIAL", "COPIA", "MUESTRA", "NO COPIAR", "ORIGINAL",
                                "PERSONAL", "SECRETO", "URGENTE"],
        }
        lang = combo(list(presets), 0)
        text = combo(presets["English (United States)"], "CONFIDENTIAL", entry=True)

        def lang_changed(*_):
            items = presets.get(lang.get_active_text() or "", presets["English (United States)"])
            cur = combo_text(text)
            text.remove_all()
            for t in items:
                text.append_text(t)
            text.get_child().set_text(cur if cur in items else items[0])
        lang.connect("changed", lang_changed)
        dflt_font = "Calibri" if getattr(self.eng, "native", False) else "Carlito"
        font = combo(self.eng.fonts() or [dflt_font], dflt_font, entry=True)
        color = color_button(0xC0C0C0)
        semi = Gtk.CheckButton.new_with_mnemonic("S_emitransparent")
        semi.set_active(True)
        diag = Gtk.RadioButton.new_with_mnemonic(None, "_Diagonal")
        horiz = Gtk.RadioButton.new_with_mnemonic_from_widget(diag, "_Horizontal")
        lay = Gtk.Box(spacing=12)
        lay.pack_start(diag, False, False, 0)
        lay.pack_start(horiz, False, False, 0)
        size = combo(["Auto", "36", "40", "44", "48", "54", "60", "66", "72", "80", "90", "96",
                      "105", "120", "144"], 0, entry=True)
        body = grid([["_Language:", lang], ["_Text:", text], ["_Font:", font], ["_Size:", size], ["_Color:", color, semi],
                     ["Layout:", lay]])
        body.set_margin_start(20)
        d.add(body)
        textw.connect("toggled", lambda w: body.set_sensitive(w.get_active()))

        def apply():
            if none.get_active():
                self.watermark("")
                return
            if getattr(self.eng, "native", False):
                ed = self.eng.ed
                if picw.get_active():
                    if not pic_path[0]:
                        return
                    st = combo_text(scale).strip().rstrip("%")
                    try:
                        k = None if st.lower() == "auto" else float(st) / 100.0
                    except ValueError:
                        k = None
                    ed.set_watermark("picture", path=pic_path[0], scale=k, washout=wash.get_active())
                else:
                    c = color.color if color.color is not None and color.color >= 0 else 0xC0C0C0
                    sz = combo_text(size).strip()
                    try:
                        sz = None if sz.lower() == "auto" else float(sz)
                    except ValueError:
                        sz = None
                    ed.set_watermark("text", text=combo_text(text), font=combo_text(font) or "Calibri",
                                     size=sz, color=c, semi=semi.get_active(),
                                     diagonal=not horiz.get_active())
                self.eng.view.document_changed()
                return
            if picw.get_active():
                if pic_path[0]:
                    self.eng.command(".uno:Watermark", {"Text": ""})
                    st = combo_text(scale).strip().rstrip("%")
                    try:
                        pct = None if st.lower() == "auto" else float(st)
                    except ValueError:
                        pct = None
                    picture_watermark(self.model, pic_path[0], pct, wash.get_active())
                return
            remove_picture_watermarks(self.model)
            c = color.color if color.color is not None and color.color >= 0 else 0xC0C0C0
            self.eng.command(".uno:Watermark", {
                "Text": combo_text(text), "Font": combo_text(font) or "Carlito",
                "Angle": ("short", 0 if horiz.get_active() else 45),
                "Transparency": ("short", 50 if semi.get_active() else 0),
                "Color": ("long", c)})
        while True:
            r = d.ask()
            if r == Gtk.ResponseType.APPLY:
                apply()
                continue
            if r == Gtk.ResponseType.OK:
                apply()
            break
        d.done()

    # ========================================================= Line numbers
    def line_numbers(self, mode=None):
        m = self._model_or_warn()
        if m is None:
            return
        if mode is None:
            self.line_numbers_dialog()
            return
        docapi.line_numbering(m, mode)

    def line_numbers_dialog(self):
        m = self._model_or_warn()
        if m is None:
            return
        ln = m.getLineNumberingProperties()
        d = FDialog(self.win, "Line Numbers")
        on = Gtk.CheckButton.new_with_mnemonic("Add _line numbering")
        on.set_active(bool(ln.IsOn))
        d.add(on)
        start = Gtk.SpinButton.new_with_range(1, 9999, 1)
        start.set_value(1)
        dist = LengthSpin(ln.Distance or 635, 0, 25400)
        count = Gtk.SpinButton.new_with_range(1, 100, 1)
        count.set_value(ln.Interval or 1)
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        body.pack_start(grid([["Start _at:", start], ["From _text:", dist],
                              ["Count _by:", count]]), False, False, 0)
        restart = Gtk.RadioButton.new_with_mnemonic(None, "Restart each _page")
        restart_sec = Gtk.RadioButton.new_with_mnemonic_from_widget(restart,
                                                                    "Restart each _section")
        cont = Gtk.RadioButton.new_with_mnemonic_from_widget(restart, "_Continuous")
        starts = _section_starts(m)
        first_val = 0
        try:
            c = m.getText().createTextCursorByRange(starts[0])
            first_val = c.ParaLineNumberStartValue or 0
        except Exception:
            pass
        sec_mode = False
        if len(starts) > 1:
            try:
                c = m.getText().createTextCursorByRange(starts[1])
                sec_mode = (c.ParaLineNumberStartValue or 0) > 0
            except Exception:
                pass
        if first_val:
            start.set_value(first_val)
        (restart if ln.RestartAtEachPage else restart_sec if sec_mode else cont).set_active(True)
        body.pack_start(Gtk.Label(label="Numbering:", xalign=0), False, False, 0)
        body.pack_start(restart, False, False, 0)
        body.pack_start(restart_sec, False, False, 0)
        body.pack_start(cont, False, False, 0)
        body.set_margin_start(20)
        d.add(body)
        on.connect("toggled", lambda w: body.set_sensitive(w.get_active()))
        body.set_sensitive(on.get_active())
        if d.ask() == Gtk.ResponseType.OK:
            ln.IsOn = on.get_active()
            if on.get_active():
                ln.Distance = dist.mm100
                ln.Interval = int(count.get_value())
                ln.RestartAtEachPage = restart.get_active()
                ln.CountEmptyLines = False
                set_line_number_starts(m, int(start.get_value()), restart_sec.get_active())
        d.done()

    def hyphenation_options(self):
        if getattr(self.eng, "native", False):
            from .native import layoutopts
            layoutopts.options_dialog(self.win)
            return
        if self._model_or_warn() is not None:
            from . import hyphen
            hyphen.options_dialog(self.win)

    def manual_hyphenation(self):
        if getattr(self.eng, "native", False):
            from .native import layoutopts
            layoutopts.manual_dialog(self.win)
            return
        if self._model_or_warn() is not None:
            from . import hyphen
            hyphen.manual_dialog(self.win)

    def hyphenation(self, auto=None):
        m = self._model_or_warn()
        if m is None:
            return
        if auto is None:
            auto = not docapi.para_styles(m).getByName("Standard").ParaIsHyphenation
        docapi.hyphenation(m, auto)

    # ===================================================== Document spacing
    def doc_spacing(self, preset):
        m = self._model_or_warn()
        if m is not None:
            docapi.doc_spacing(m, preset)

    def doc_spacing_none(self):
        self.doc_spacing("none")

    def doc_spacing_compact(self):
        self.doc_spacing("compact")

    def doc_spacing_tight(self):
        self.doc_spacing("tight")

    def doc_spacing_open(self):
        self.doc_spacing("open")

    def doc_spacing_relaxed(self):
        self.doc_spacing("relaxed")

    def doc_spacing_double(self):
        self.doc_spacing("double")

    def doc_spacing_default(self):
        self.doc_spacing("default")

    def doc_fonts(self, pair):
        m = self._model_or_warn()
        if m is not None:
            docapi.apply_fonts(m, pair)
            self.win.design_changed()

    def doc_colors(self, name):
        m = self._model_or_warn()
        if m is not None:
            docapi.apply_colors(m, name)
            self.win.design_changed()

    def doc_theme(self, name):
        m = self._model_or_warn()
        if m is not None:
            docapi.apply_theme(m, name)
            self.win.design_changed()

    def style_set(self, name):
        m = self._model_or_warn()
        if m is not None:
            docapi.apply_style_set(m, name)
            self.win.design_changed()

    def set_as_default(self):
        m = self._model_or_warn()
        if m is None:
            return
        if self.confirm("Do you want to set the current style set and theme as the default?\n\n"
                        "New documents will use these settings.", yes="Yes", no="No"):
            self.win.app.save_styles_as_default(self.win.engine)
