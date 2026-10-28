"""Ribbon and keyboard actions for the new engine. What it can't do yet is
refused with a note in the status bar rather than half-done."""
import re

from ..actions import Actions, HALF_INCH

NOT_YET = "This isn't available with the new engine yet."

# Actions methods that work through the engine interface as they are
INHERITED = {
    "grow_font", "shrink_font", "grow_font_1", "shrink_font_1", "double_underline",
    "highlight", "font_color", "spacing_1", "spacing_15", "spacing_2", "zoom_in", "zoom_out",
    "nbsp", "soft_hyphen", "nb_hyphen", "promote", "demote",
}

# window actions (act_...) that don't need the old engine
WINDOW = {
    "save", "save-as", "new", "close", "toggle-ribbon", "backstage-open", "backstage-print",
    "backstage-info", "help", "search-box", "next-region", "prev-region", "next-window",
    "prev-window", "options", "about", "focus-mode", "zoom-dialog", "zoom-100",
    "one-page", "page-width", "multiple-pages", "side-to-side", "ruler", "print-layout", "font-dialog", "paragraph-dialog",
    "tabs-dialog", "new-style", "modify-style", "date-time", "field-dialog", "caption", "hyperlink", "bookmark", "cross-reference",
    "page-borders", "margins", "paper", "orientation", "columns", "equation", "comment", "prev-comment", "next-comment", "delete-all-comments", "manage-changes",
    "find-pane", "page-setup", "language-dialog", "text-from-file", "selection-pane", "styles-pane", "spelling", "thesaurus", "clipboard-pane", "arrange-all",
    "side-by-side", "sync-scrolling", "reset-window-position", "draft-view", "web-layout", "print-layout",
    "outline-view", "close-outline", "read-mode", "immersive-reader", "close-immersive", "split", "new-window",
    "read-aloud", "check-accessibility", "merge-preview", "find-recipient", "highlight-merge-fields", "paragraph-borders", "zoom-one-page", "zoom-page-width", "toggle-ruler", "drop-cap", "watermark-dialog", "draw-shape",
    "context-menu", "open-dialog", "view-macros", "apply-styles", "field-braces",
}

def split_command(name):
    """'.uno:Cmd?Arg:type=value&Arg2:type=value' (the old engine's URL form)
    -> (name, {arg: value})."""
    from urllib.parse import unquote
    name, _q, query = name.partition("?")
    args = {}
    for part in query.split("&"):
        if not part:
            continue
        k, _e, v = part.partition("=")
        key, _c, typ = k.partition(":")
        v = unquote(v)
        if typ in ("long", "short", "int"):
            try:
                v = int(v)
            except ValueError:
                pass
        elif typ == "boolean":
            v = v.lower() == "true"
        args[key] = v
    return name, args


SECTION_BREAKS = {"next-page": "nextPage", "continuous": "continuous", "even": "evenPage",
                  "odd": "oddPage"}

# LibreOffice underline styles (as the ribbon sends them) -> Word's
UNDERLINES = {0: "none", 1: "single", 2: "double", 3: "dotted", 4: "none", 5: "dash",
              6: "dashLong", 7: "dotDash", 8: "dotDotDash", 9: "wave", 10: "wave",
              11: "wavyDouble", 12: "thick", 13: "dottedHeavy", 14: "dashedHeavy",
              15: "dashLongHeavy", 16: "dashDotHeavy", 17: "dashDotDotHeavy",
              18: "wavyHeavy"}


class NativeActions(Actions):
    @property
    def ed(self):
        return self.eng.ed

    def _not_yet(self):
        try:
            self.win.status.flash(NOT_YET)
        except Exception:
            print(NOT_YET)

    def _edit(self, fn, *a):
        if self.ed is None:
            return
        fn(*a)
        self.eng.view.after_edit()

    def cmd(self, name, args=None):
        if "?" in name and args is None:
            name, args = split_command(name)
        if name == ".uno:FormatPaintbrush" and getattr(self.win, "painter", None) is not None:
            self.win.painter.toggle()
            return
        if not self.eng.command(name, args):
            self._not_yet()

    # what F4 (Repeat) may run again: formatting and inserting, not moving or undoing
    NO_REPEAT = {"undo", "redo-repeat", "repeat", "copy", "cut", "paste", "find-pane", "goto", "go-back",
                 "save", "save-as", "extend-selection", "context-menu", "select-all", "spike", "spike-paste"}

    def run(self, action):
        if action is None:
            return
        name = action if isinstance(action, str) else (action[0] if isinstance(action, tuple) else None)
        if name is not None and not callable(action) and name not in self.NO_REPEAT and \
                not (isinstance(name, str) and name.startswith((".uno:Go", ".uno:Jump", ".uno:Select", ".uno:Undo", ".uno:Redo"))) \
                and (name in self.WINDOW_REPEAT or not (isinstance(name, str) and name in WINDOW)):
            self.last_action = action
            self.last_state = None
        self._run(action)
        if name is not None and getattr(self, "last_action", None) is action and isinstance(action, str) \
                and action in self.TOGGLES:
            # Repeat gives the same formatting again, not the opposite
            self.last_state = self._toggle_on(action)

    def _toggle_on(self, cmd):
        try:
            st = self.ed.state()
        except Exception:
            return None
        k = {".uno:Bold": "bold", ".uno:Italic": "italic", ".uno:Strikeout": "strike"}.get(cmd)
        if k:
            return bool(st.get(k))
        if cmd == ".uno:Underline":
            return st.get("underline", "none") != "none"
        if cmd in (".uno:SuperScript", ".uno:SubScript"):
            return st.get("vert_align") == ("superscript" if cmd == ".uno:SuperScript" else "subscript")
        return None

    WINDOW_REPEAT = set()
    TOGGLES = {".uno:Bold", ".uno:Italic", ".uno:Underline", ".uno:Strikeout", ".uno:SuperScript",
               ".uno:SubScript", ".uno:SmallCaps", ".uno:Shadowed", ".uno:OutlineFont"}

    def _run(self, action):
        if action is None:
            return
        if callable(action):
            try:
                action()
            except Exception as e:
                print("action:", e)
                self._not_yet()
            return
        if isinstance(action, tuple):
            kind, arg = action[0], action[1]
            if kind == "style":
                self.apply_style(arg)
            elif kind == "table-style2":
                from . import tables
                tables.apply_style(self.win, arg[0], arg[1])
            elif kind == "table-option":
                from . import tables
                tables.set_option(self.win, arg)
            elif kind == "text":
                self.insert_text(arg)
            elif kind == "model":
                self.win.model_call(arg, *action[2:])
            elif kind == "add-text":
                self.add_text(arg)
            elif kind == "hf-option":
                self.hf_option(arg)
            elif kind == "hf-position":
                self.hf_position(*arg)
            elif kind in ("doc-theme", "doc-colors", "doc-fonts"):
                from . import design
                {"doc-theme": design.theme, "doc-colors": design.colors,
                 "doc-fonts": design.fonts}[kind](self.win, arg)
            elif kind == "watermark":
                self.win.dialogs.watermark(arg)
            elif kind == "page-color":
                self.ed.set_page_color(None if arg is None or (isinstance(arg, int) and arg < 0)
                                       else "%06X" % (int(arg) & 0xFFFFFF))
                self.eng.view.after_edit()
            elif kind == "line-numbers":
                from . import layoutopts
                layoutopts.line_numbers(self.win, arg)
            elif kind == "hyphenation":
                from . import layoutopts
                layoutopts.hyphenation(self.win, arg)
            elif kind == "section-break":
                if self.ed.insert_break(SECTION_BREAKS.get(arg, "nextPage")):
                    self.eng.view.after_edit()
                else:
                    self.win.status.flash("A section break can't go here.")
            elif isinstance(kind, str) and kind.startswith(".uno:"):
                self.cmd(kind, arg)
            elif kind in WINDOW:
                self.win.run_window_action(kind, arg)
            else:
                self._not_yet()
            return
        if action.startswith(".uno:"):
            self.cmd(action)
            return
        key = action.replace("-", "_")
        own = type(self).__dict__.get("do_" + key)
        if own is not None or key in INHERITED:
            getattr(self, "do_" + key)()
        elif action in WINDOW:
            self.win.run_window_action(action)
        else:
            self._not_yet()

    # ------------------------------------------------------------ fields
    def do_update_fields(self):
        n = self.ed.update_fields(False)
        from . import refs
        refs.refresh_citations(self.win)
        self.eng.view.after_edit()
        if n == 0:
            self.win.status.flash("Nothing to update.") if hasattr(self.win, "status") else None

    def add_text(self, level):
        if level:
            self.apply_style("Heading %d" % level)
        else:
            self.ed.apply_para([("w:outlineLvl", [("w:val", "9")])], "Add Text")
            self.eng.view.after_edit()

    def do_insert_toc(self):
        self.ed.insert_toc("Contents")
        self.eng.view.after_edit()

    def do_insert_toc_2(self):
        self.ed.insert_toc("Table of Contents")
        self.eng.view.after_edit()

    def do_update_toc(self):
        from . import refs
        if not refs.update_tables(self.win) and not refs.fields(self.win, "BIBLIOGRAPHY"):
            self.win.dialogs.message("This document doesn't have a table of contents.")
        self.eng.view.after_edit()

    # ------------------------------------------------------------ references
    def do_toc_dialog(self):
        from . import refs
        refs.toc_dialog(self.win)

    def do_table_of_figures(self):
        from . import refs
        labels = ["Equation", "Figure", "Table"] + list(self.win.app.settings.get("caption_labels", []))
        refs.figures_dialog(self.win, labels)

    def do_insert_index(self):
        from . import refs
        refs.index_dialog(self.win)

    def do_mark_entry(self):
        from . import refs
        refs.mark_entry(self.win)

    def do_mark_citation(self):
        from . import refs
        refs.mark_citation(self.win)

    def do_insert_toa(self):
        from . import refs
        refs.toa_dialog(self.win)

    def do_update_toa(self):
        self.do_update_toc()

    def do_footnote_dialog(self):
        from .. import notes
        notes.dialog(self.win)

    def do_show_notes(self):
        from . import refs
        refs.show_notes(self.win)

    def do_next_footnote(self):
        from . import refs
        refs.goto_note(self.win, False, True)

    def do_prev_footnote(self):
        from . import refs
        refs.goto_note(self.win, False, False)

    def do_next_endnote(self):
        from . import refs
        refs.goto_note(self.win, True, True)

    def do_prev_endnote(self):
        from . import refs
        refs.goto_note(self.win, True, False)

    def do_object_size(self):
        from . import arrange
        if self.ed.selected_object() is None:
            self.win.status.flash("Select a picture or shape first.")
            return
        arrange.layout_dialog(self.win, 2)

    def do_manage_sources(self):
        from .. import dlg_cite
        dlg_cite.manage_sources(self.win)

    def do_remove_header(self):
        from . import covers
        if not covers.remove_hf(self.win, "header"):
            self.win.status.flash("This page doesn't have a header.")

    def do_remove_footer(self):
        from . import covers
        if not covers.remove_hf(self.win, "footer"):
            self.win.status.flash("This page doesn't have a footer.")

    def do_remove_page_numbers(self):
        """Insert > Page Number > Remove Page Numbers: the page numbers in the
        current section's header and footer."""
        import re
        ed = self.ed
        pg = ed.caret_page()
        n = 0
        ed.begin_group("Remove Page Numbers")
        try:
            for footer in (False, True):
                if not ed.page_hf(pg)[1 if footer else 0]:
                    continue
                ed.edit_header_footer(pg, footer)
                ed.move_caret("doc_start", False)
                for _i in range(50):
                    p = ed.caret_pos()[0]
                    t = ed.para_text_of(p)
                    if re.fullmatch(r"\s*(Page\s+)?\d+(\s+of\s+\d+)?\s*|\s*-\s*\d+\s*-\s*", t or ""):
                        ed.select_nodes(p, 0, p, len(t))
                        ed.delete(True, False)
                        n += 1
                    before = ed.caret_pos()
                    ed.move_caret("para_down", False)
                    if ed.caret_pos() == before:
                        break
            ed.edit_header_footer(None)
        finally:
            ed.end_group()
        self.eng.view.after_edit()
        if not n:
            self.win.status.flash("There are no page numbers in this section's header or footer.")

    def do_remove_toc(self):
        self.ed.remove_toc()
        self.eng.view.after_edit()

    # ------------------------------------------------------------ headers
    def _hf(self, footer):
        self.cmd(".uno:JumpToFooter" if footer else ".uno:JumpToHeader")

    def do_header(self):
        self._hf(False)

    def do_footer(self):
        self._hf(True)

    def hf_option(self, key):
        ed = self.ed
        sec = ed.current_section()
        info = ed.section_info(sec) or {}
        if key == "first":
            ed.section_flag(sec, "w:titlePg", not info.get("title_pg"), "Different First Page")
        elif key == "odd_even":
            ed.set_setting("evenAndOddHeaders", not ed.setting("evenAndOddHeaders"))
        elif key == "show_text":
            v = self.eng.view
            v.hide_body = not getattr(v, "hide_body", False)
            v.queue_draw()
            return
        else:
            self._not_yet()
            return
        # the header being edited may now be another kind: go to that one
        pg = ed.story_page()
        if pg is not None:
            footer = ed.story_is_footer() if hasattr(ed, "story_is_footer") else False
            if not ed.page_hf(pg)[1 if footer else 0]:
                ed.ensure_header_footer_kind(ed.page_section(pg), footer, ed.page_hf_kind(pg))
            ed.edit_header_footer(pg, footer)
        self.eng.view.document_changed()

    def hf_position(self, key, mm100):
        tw = str(int(round(mm100 * 1440.0 / 2540.0)))
        attr = "w:header" if key == "header_top" else "w:footer"
        self.ed.section_attr(self.ed.current_section(), "w:pgMar", attr, tw, "Header Position")
        self.eng.view.after_edit()

    def do_close_header_footer(self):
        self.ed.edit_header_footer(None)
        self.eng.view.document_changed()
        self.eng.view.scroll_to_caret()

    # ------------------------------------------------------------ pictures
    def do_insert_picture(self):
        from . import objects
        objects.insert_picture(self.win)

    # ------------------------------------------------------------ editing
    def do_undo(self):
        self.cmd(".uno:Undo")

    def do_redo_repeat(self):
        self.cmd(".uno:Redo")

    def do_copy(self, cut=False):
        self.eng.copy(cut)

    def do_cut(self):
        self.eng.copy(True)

    def do_paste(self, text_only=False):
        self.eng.paste(plain=text_only)

    def do_paste_text(self):
        self.eng.paste(plain=True)

    def paste_primary(self):
        from gi.repository import Gdk, Gtk
        t = Gtk.Clipboard.get(Gdk.SELECTION_PRIMARY).wait_for_text()
        if t:
            self.eng.paste_data("text/plain;charset=utf-8", t)

    def do_select_all(self):
        self.cmd(".uno:SelectAll")

    # ------------------------------------------------------------ keyboard (W-04)
    def do_repeat(self):
        """F4: the last formatting or insertion again, here."""
        a = getattr(self, "last_action", None)
        if a is None:
            self.win.status.flash("There's nothing to repeat.")
            return
        want = getattr(self, "last_state", None)
        if isinstance(a, str) and a in self.TOGGLES and want is not None and self._toggle_on(a) == want:
            return
        self._run(a)

    def do_extend_selection(self):
        self.win.extend_selection()

    def do_move_up(self):
        if self.ed.move_block(True):
            self.eng.view.after_edit()

    def do_move_down(self):
        if self.ed.move_block(False):
            self.eng.view.after_edit()

    def do_go_back(self):
        """Shift+F5: back to the places last edited."""
        v = self.eng.view
        spots = getattr(v, "edit_spots", [])
        if not spots:
            return
        cur = tuple(self.ed.caret_pos())
        # the newest spot that isn't where the caret is; pressed again, the one before
        k = getattr(self, "_back_i", -1) if getattr(self, "_back_spots", None) == list(spots) else -1
        self._back_spots = list(spots)
        for _ in range(len(spots)):
            k = (k + 1) % len(spots)
            p, off = spots[-1 - k]
            if (p, off) != cur:
                break
        self._back_i = k
        try:
            n = len(self.ed.para_text_of(p))
            self.ed.select_nodes(p, min(off, n), p, min(off, n))
        except Exception:
            return
        v.after_move()

    def do_unicode_toggle(self):
        """Alt+X: the hex code before the caret becomes its character, or the
        character before the caret its hex code."""
        ed = self.ed
        hexd = "0123456789abcdefABCDEF"
        if ed.has_selection():
            pa, a, pb, b = ed.selection_range()
            if pa != pb:
                return
            s = ed.para_text_of(pa)[a:b]
            core = s[2:] if s[:2] in ("U+", "u+") else s
            if core and all(c in hexd for c in core) and int(core, 16) <= 0x10FFFF:
                ed.type_text(chr(int(core, 16)))
            elif len(s) == 1:
                ed.type_text("%04X" % ord(s))
            self.eng.view.after_edit()
            return
        p, off = ed.caret_pos()
        text = ed.para_text_of(p)[:off]
        k = off
        while k > 0 and off - k < 6 and text[k - 1] in hexd:
            k -= 1
        if k < off:
            start = k
            if start >= 2 and text[start - 2:start] in ("U+", "u+"):
                start -= 2
            code = int(text[k:off], 16)
            # "x00e9": the x isn't hex, so the code is 00e9
            if code <= 0x10FFFF and code > 0:
                ed.select_nodes(p, start, p, off)
                ed.type_text(chr(code))
                self.eng.view.after_edit()
                return
        if off > 0:
            ch = text[-1]
            ed.select_nodes(p, off - 1, p, off)
            ed.type_text("%04X" % ord(ch))
            self.eng.view.after_edit()

    def do_spike(self):
        """Ctrl+F3: cut the selection onto the Spike."""
        if not self.ed.has_selection():
            self.win.status.flash("Select something to put on the Spike.")
            return
        frag = self.ed.copy_fragment()
        if frag is None:
            return
        spike = getattr(self.win.app, "spike", None)
        if spike is None:
            spike = self.win.app.spike = []
        spike.append(frag)
        self.ed.delete(False, False)
        self.eng.view.after_edit()

    def do_spike_paste(self):
        """Ctrl+Shift+F3: everything on the Spike, which is then empty."""
        spike = getattr(self.win.app, "spike", None) or []
        if not spike:
            self.win.status.flash("The Spike is empty.")
            return
        self.ed.begin_group("Paste Spike")
        try:
            for k, frag in enumerate(spike):
                if k:
                    self.ed.type_text("\n")
                self.ed.paste_fragment(frag, True)
        finally:
            self.ed.end_group()
        self.win.app.spike = []
        self.eng.view.after_edit()

    # ------------------------------------------------------------ characters
    def do_all_caps(self):
        self._edit(self.ed.toggle, "w:caps")

    def do_small_caps(self):
        self._edit(self.ed.toggle, "w:smallCaps")

    def do_word_underline(self):
        st = self.ed.state()
        self._edit(self.ed.set_underline, "none" if st["underline"] == "words" else "words")

    def underline_style(self, style):
        self._edit(self.ed.set_underline, UNDERLINES.get(int(style), "single"))

    def do_clear_char_format(self):
        self.cmd(".uno:ResetAttributes")

    def do_clear_all_formatting(self):
        self.cmd(".uno:ResetAttributes")
        self.apply_style("Normal")

    def do_hidden(self):
        self._edit(self.ed.toggle, "w:vanish")

    # ------------------------------------------------------------ paragraphs
    def _para(self):
        return self.ed.state()

    def set_indents(self, left=None, right=None, first=None):
        """Indents in 1/100 mm, as the ribbon's spin buttons give them."""
        tw = lambda v: None if v is None else int(round(v * 1440 / 2540.0))
        self._edit(self.ed.set_indent, tw(left), tw(right), tw(first))

    def _indents_twips(self):
        s = self._para()
        return s.get("ind_left", 0), s.get("ind_right", 0), s.get("ind_first", 0)

    def do_indent(self):
        l, r, f = self._indents_twips()
        self._edit(self.ed.set_indent, (l // 720 + 1) * 720, None, None)

    def do_outdent(self):
        l, r, f = self._indents_twips()
        self._edit(self.ed.set_indent, max(0, ((l - 1) // 720) * 720), None, None)

    def do_hanging_indent(self):
        l, r, f = self._indents_twips()
        hang = max(0, -f)
        self._edit(self.ed.set_indent, l + 720, None, -(hang + 720))

    def do_unhang(self):
        l, r, f = self._indents_twips()
        hang = max(0, -f)
        step = min(720, hang, l)
        if step > 0:
            self._edit(self.ed.set_indent, l - step, None, -(hang - step))

    def line_spacing(self, factor):
        self._edit(self.ed.set_line_spacing, "auto", int(round(factor * 240)))

    def set_spacing(self, before=None, after=None):
        tw = lambda v: None if v is None else int(round(v * 1440 / 2540.0))
        self._edit(self.ed.set_para_spacing, tw(before), tw(after))

    def do_space_before_toggle(self):
        b = self._para().get("space_before", 0)
        self._edit(self.ed.set_para_spacing, 0 if b else 240, None)

    def do_reset_paragraph(self):
        self._edit(self.ed.reset_para_formatting)

    def apply_style(self, name):
        self.eng.apply_style(name)

    def _para_style_now(self):
        return self._para()["style"]

    def do_bullets(self):
        self.cmd(".uno:DefaultBullet")

    def do_numbering(self):
        self.cmd(".uno:DefaultNumbering")

    def _heading_step(self, d):
        st = self._para_style_now()
        m = re.match(r"Heading (\d)", st)
        if m:
            self.apply_style("Heading %d" % max(1, min(9, int(m.group(1)) + d)))
        else:
            self.cmd(".uno:DecrementLevel" if d < 0 else ".uno:IncrementLevel")


    # ------------------------------------------------------------ select
    def do_select_similar(self):
        ed = self.ed
        if ed is None:
            return
        n = ed.select_style_instances(ed.para_style_id())
        self.eng.view.after_move()
        self.win.status.flash("%d paragraph%s selected." % (n, "" if n == 1 else "s")) if n else None

    # ------------------------------------------------------------ clipboard
    def do_paste_special(self):
        self.win.dialogs.paste_special()

    def do_paste_text_only(self):
        self.eng.paste(plain=True)

    # ------------------------------------------------------------ find
    def do_replace(self):
        from . import find
        self.win.remember_position()
        find.dialog(self.win, 1)

    def do_goto(self):
        from . import find
        find.dialog(self.win, 2)

    def do_advanced_find(self):
        from . import find
        find.dialog(self.win, 0)

    # ------------------------------------------------------------ breaks
    def do_blank_page(self):
        if self.ed.insert_blank_page():
            self.eng.view.after_edit()

    # ------------------------------------------------------------ painter
    def copy_format_data(self):
        ed = self.ed
        if ed is None:
            return None
        ed.copy_format()
        return True

    def apply_format_data(self, _data):
        ed = self.ed
        if ed is None:
            return
        if ed.paste_format():
            self.eng.view.after_edit()

    def do_copy_format(self):
        self.copy_format_data()

    def do_paste_format(self):
        if self.ed is not None and self.ed.has_format():
            self.apply_format_data(True)
        else:
            self.do_paste_text()

    # ------------------------------------------------------------ text tools
    def do_change_case_cycle(self):
        """Shift+F3: lowercase -> Capitalize Each Word -> UPPERCASE."""
        ed = self.ed
        txt = ed.selected_text()
        if not txt:
            ed.change_case("lower")   # nothing to read: start the cycle
            self.eng.view.after_edit()
            return
        letters = [c for c in txt if c.isalpha()]
        if letters and all(c.isupper() for c in letters):
            mode = "lower"
        elif letters and all(c.islower() for c in letters):
            mode = "title"
        else:
            words = [w for w in txt.split() if w[:1].isalpha()]
            mode = "upper" if words and all(w[0].isupper() for w in words) else "lower"
        self._edit(ed.change_case, mode)

    def _para_style_now(self):
        """The paragraph style at the caret, from the document (not the
        reported state, which follows a moment later)."""
        try:
            st = self.ed.state()
            name = st.get("style_name") or st.get("style")
            if name:
                from ..actions import word_style
                return word_style(name)
        except Exception:
            pass
        return super()._para_style_now()

    def do_sort_dialog(self):
        from .. import sortdlg
        sortdlg.dialog(self.win)

    def do_select_cell(self):
        from . import tables
        tables.select(self.win, "cell")

    def do_split_cells(self):
        from . import tables
        tables.split_cells_dialog(self.win)

    def do_split_table(self):
        from . import tables
        tables.split_table(self.win)

    def do_table_properties(self):
        from . import tables
        tables.properties_dialog(self.win)

    def do_insert_cells(self):
        from . import tables
        tables.insert_cells_dialog(self.win)

    # ------------------------------------------------------------ design
    def _spacing(self, preset):
        from . import design
        design.spacing(self.win, preset)

    def do_doc_spacing_default(self):
        self._spacing("default")

    def do_doc_spacing_none(self):
        self._spacing("none")

    def do_doc_spacing_compact(self):
        self._spacing("compact")

    def do_doc_spacing_tight(self):
        self._spacing("tight")

    def do_doc_spacing_open(self):
        self._spacing("open")

    def do_doc_spacing_relaxed(self):
        self._spacing("relaxed")

    def do_doc_spacing_double(self):
        self._spacing("double")

    def do_set_as_default(self):
        from . import design
        design.set_as_default(self.win)

    def do_line_numbers(self):
        from . import layoutopts
        layoutopts.line_numbers_dialog(self.win)

    def do_word_count(self):
        from . import tools
        tools.word_count(self.win)


assert HALF_INCH
