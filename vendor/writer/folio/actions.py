"""App actions: everything a key, button or menu can do."""
import json
import re

from gi.repository import Gdk, GLib, Gtk

SIZE_STEPS = [8, 9, 10, 10.5, 11, 12, 14, 16, 18, 20, 22, 24, 26, 28, 36, 48, 72]
MM100_PER_INCH = 2540
HALF_INCH = 1270

# Style names: the names shown to the user <-> the engine's names.
TO_ENGINE = {"Normal": "Standard", "Quote": "Quotations", "Body Text": "Text body",
             "TOC Heading": "Contents Heading", "Strong": "Strong Emphasis",
             "Hyperlink": "Internet link", "Footnote Text": "Footnote",
             "Endnote Text": "Endnote", "Caption": "Caption",
             "Table of Figures": "Illustration Index 1"}
FROM_ENGINE = {"Default Paragraph Style": "Normal", "Standard": "Normal",
               "Text body": "Body Text", "Body Text": "Body Text", "Quotations": "Quote",
               "Block Quotation": "Quote", "Contents Heading": "TOC Heading",
               "Strong Emphasis": "Strong", "Internet link": "Hyperlink",
               "Internet Link": "Hyperlink", "Footnote": "Footnote Text",
               "Endnote": "Endnote Text", "Preformatted Text": "HTML Preformatted",
               "No Character Style": "Default Paragraph Font",
               "Illustration Index 1": "Table of Figures", "Figure Index 1": "Table of Figures"}
for i in range(1, 10):
    FROM_ENGINE["Contents %d" % i] = "TOC %d" % i
    TO_ENGINE["TOC %d" % i] = "Contents %d" % i
CHAR_STYLES = {"Subtle Emphasis", "Emphasis", "Intense Emphasis", "Strong",
               "Subtle Reference", "Intense Reference", "Book Title", "Hyperlink"}

HIGHLIGHTS = [("Yellow", 0xFFFF00), ("Bright Green", 0x00FF00), ("Turquoise", 0x00FFFF),
              ("Pink", 0xFF00FF), ("Blue", 0x0000FF), ("Red", 0xFF0000),
              ("Dark Blue", 0x000080), ("Teal", 0x008080), ("Green", 0x008000),
              ("Violet", 0x800080), ("Dark Red", 0x800000), ("Dark Yellow", 0x808000),
              ("Gray 50%", 0x808080), ("Gray 25%", 0xC0C0C0), ("Black", 0x000000)]


def _utf8(raw):
    """Clipboard HTML as UTF-8 (browsers may hand it over as UTF-16)."""
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16").encode("utf-8")
    if len(raw) > 4 and raw[1:2] == b"\x00" and raw[3:4] == b"\x00":
        return raw.decode("utf-16-le", "replace").encode("utf-8")
    return raw


def word_style(engine_name):
    return FROM_ENGINE.get(engine_name, engine_name)


def engine_style(word_name):
    return TO_ENGINE.get(word_name, word_name)


def _float(s, default=0.0):
    try:
        return float(str(s).replace(",", "."))
    except ValueError:
        return default


def para_margins(engine):
    """Current paragraph indents in 1/100 mm: (left, right, first)."""
    m = getattr(engine, "model", None)
    if m is not None:
        try:
            vc = m.getCurrentController().getViewCursor()
            return vc.ParaLeftMargin, vc.ParaRightMargin, vc.ParaFirstLineIndent
        except Exception:
            pass
    raw = engine.get(".uno:LeftRightParaMargin")
    try:
        d = json.loads(raw)
    except ValueError:
        return 0, 0, 0
    f = MM100_PER_INCH if d.get("unit", "inch") == "inch" else 1000
    return (int(round(_float(d.get("left")) * f)), int(round(_float(d.get("right")) * f)),
            int(round(_float(d.get("firstline")) * f)))


def para_spacing(engine):
    m = getattr(engine, "model", None)
    if m is not None:
        try:
            vc = m.getCurrentController().getViewCursor()
            return vc.ParaTopMargin, vc.ParaBottomMargin
        except Exception:
            pass
    return _para_spacing_state(engine)


def _para_spacing_state(engine):
    raw = engine.get(".uno:ULSpacing")
    try:
        d = json.loads(raw)
    except ValueError:
        return 0, 0
    f = MM100_PER_INCH if d.get("unit", "inch") == "inch" else 1000
    return int(round(_float(d.get("upper")) * f)), int(round(_float(d.get("lower")) * f))


class Actions:
    def __init__(self, window):
        self.win = window
        self.format_copy = None

    @property
    def eng(self):
        return self.win.engine

    def cmd(self, name, args=None):
        if name == ".uno:FormatPaintbrush" and getattr(self.win, "painter", None) is not None:
            self.win.painter.toggle()
            return
        if name == ".uno:TrackChanges" and getattr(self.win, "track_locked", False) and \
                self.eng.get(".uno:TrackChanges") == "true":
            self.win.dialogs.message("Track Changes is locked: this document only allows "
                                     "tracked changes. (Review > Restrict Editing)")
            return
        if getattr(self.win, "restricted", False) and name not in (
                ".uno:Copy", ".uno:SelectAll", ".uno:ControlCodes", ".uno:ShowTrackedChanges",
                ".uno:ShowChangesInMargin") and not name.startswith((".uno:GoTo", ".uno:Go",
                                                                      ".uno:JumpTo")):
            self.win.status.flash("This modification is not allowed because the document "
                                  "is protected.")
            return
        self.eng.command(name, args)

    # ------------------------------------------------------------ dispatch
    def run(self, action):
        if action is None:
            return
        if callable(action):
            action()
            return
        if isinstance(action, tuple):
            kind, arg = action[0], action[1]
            if kind == "style":
                self.apply_style(arg)
            elif kind == "text":
                self.insert_text(arg)
            elif kind == "model":
                rest = action[2:]
                self.eng.sync(lambda: self.win.model_call(arg, *rest))
            elif isinstance(kind, str) and kind.startswith(".uno:"):
                self.cmd(kind, arg)
            else:
                self.win.run_window_action(kind, arg)
            return
        if action.startswith(".uno:"):
            self.cmd(action)
            return
        fn = getattr(self, "do_" + action.replace("-", "_"), None)
        if fn is not None:
            fn()
        else:
            self.win.run_window_action(action)

    # ------------------------------------------------------------ editing
    def insert_text(self, text):
        self.cmd(".uno:InsertText", {"Text": text})

    # Undo/redo run in "repair" mode so changes the app made through the
    # document model (equations, page setup, captions...) undo like typing.
    REPAIR = {"Repair": ("boolean", "true")}

    def do_undo(self):
        n = 1
        m = self.eng.model
        styles = False
        if m is not None:
            try:
                titles = m.getUndoManager().getAllUndoActionTitles()
                styles = bool(titles) and ("Style" in titles[0] or "style" in titles[0])
                # object re-sizes after an equation edit aren't user actions
                while n < len(titles) and titles[n - 1].startswith("Change style: Object"):
                    n += 1
            except Exception:
                pass
        if m is not None and n == 1:
            # a space typed after a word is its own engine step; the original
            # undoes the word and the space together
            try:
                titles = m.getUndoManager().getAllUndoActionTitles()
                if len(titles) >= 2 and titles[0].startswith("Typing") and \
                        titles[1].startswith("Typing") and \
                        not titles[0].split(":", 1)[-1].strip(" \"“”'‘’"):
                    n = 2
            except Exception:
                pass
        for _ in range(n):
            self.cmd(".uno:Undo", self.REPAIR)
        if styles:
            self.eng.sync(self.win.design_changed)

    def do_redo_repeat(self):
        if self.eng.get(".uno:Redo") == "enabled" or self._can_redo():
            self.cmd(".uno:Redo", self.REPAIR)
        else:
            self.cmd(".uno:Repeat")

    def _can_redo(self):
        m = self.eng.model
        try:
            return bool(m and m.getUndoManager().isRedoPossible())
        except Exception:
            return False

    def do_repeat(self):
        self.cmd(".uno:Repeat")

    def do_nbsp(self):
        self.insert_text(" ")

    def do_soft_hyphen(self):
        self.insert_text("­")

    def do_nb_hyphen(self):
        self.insert_text("‑")

    # clipboard: keep the desktop clipboard in sync with the document
    def _clipboard(self):
        return Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)

    def do_copy(self, cut=False):
        view = self.eng.view
        try:
            html, _ = view.copy_selection("text/html")
        except Exception:
            html = None
        try:
            text, _ = view.copy_selection("text/plain;charset=utf-8")
        except Exception:
            text = None
        if not cut:
            from . import pastelink
            pastelink.remember_copy(self.win, text)
        self.cmd(".uno:Cut" if cut else ".uno:Copy")   # engine's own copy too
        if text is None and html is None:
            return
        self._clip_data = (html, text or "")
        hist = self.win.app.clip_history
        if (html, text or "") not in hist:
            hist.insert(0, (html, text or ""))
            del hist[24:]
        self.win.app.clipboard().set(html, text or "")

    def _smart_mark(self):
        """Smart paste: where a paste lands right after a space, remember it
        (the engine's word-wise cut keeps the space before the word)."""
        from . import docapi
        m = self.eng.model
        clip = getattr(self, "_clip_data", None)
        if m is None or not clip or not clip[1] or clip[1][:1].isspace():
            return None
        try:
            vc = docapi.view_cursor(m)
            if not vc.isCollapsed():
                return None
            c = vc.getText().createTextCursorByRange(vc.getStart())
            if not c.goLeft(1, True) or c.getString() not in (" ", "\u00a0"):
                return None
            c.collapseToStart()      # before the space: stays put on insertion
            return c
        except Exception:
            return None

    def _smart_fix(self, mark):
        try:
            c = mark.getText().createTextCursorByRange(mark.getStart())
            c.goRight(1, False)          # past the space that was there
            if c.goRight(1, True) and c.getString() == " ":
                nxt = mark.getText().createTextCursorByRange(c.getEnd())
                if nxt.goRight(1, True) and not nxt.getString().isspace():
                    c.setString("")
        except Exception as e:
            print("smart paste:", e)

    def do_cut(self):
        self.do_copy(cut=True)

    def default_paste_mode(self):
        st = self.win.app.settings
        key = "paste_within" if self.win.clipboard_owned else "paste_other"
        return st.get(key, "source")

    def do_paste(self, text_only=False):
        mode = "text" if text_only else self.default_paste_mode()
        self._paste(mode)
        po = getattr(self.win, "paste_options", None)
        if po is not None:
            self.eng.sync(lambda: po.after_paste(mode))

    def _clipboard_html(self):
        if self.win.clipboard_owned and getattr(self, "_clip_data", None):
            return self._clip_data[0]
        sel = self._clipboard().wait_for_contents(Gdk.Atom.intern("text/html", False))
        if sel is not None and sel.get_length() > 0:
            return _utf8(bytes(sel.get_data())).decode("utf-8", "replace")
        return None

    def _paste(self, mode="source"):
        if mode is True:
            mode = "text"
        elif mode is False:
            mode = "source"
        if mode == "merge":
            html_src = self._clipboard_html()
            if html_src:
                from .pasteopts import merge_html
                self.eng.paste_data("text/html", merge_html(html_src).encode("utf-8"))
                return
            mode = "text"
        text_only = mode == "text"
        if self.win.clipboard_owned and not text_only:
            # our own copy: let the engine paste with full formatting
            mark = self._smart_mark()
            self.cmd(".uno:Paste")
            if mark is not None:
                self.eng.sync(lambda: self._smart_fix(mark))
            return
        cb = self._clipboard()
        if not text_only:
            sel = cb.wait_for_contents(Gdk.Atom.intern("text/html", False))
            if sel is not None and sel.get_length() > 0:
                self.eng.paste_data("text/html", _utf8(bytes(sel.get_data())))
                return
            sel = cb.wait_for_contents(Gdk.Atom.intern("text/rtf", False))
            if sel is not None and sel.get_length() > 0:
                self.eng.paste_data("text/rtf", bytes(sel.get_data()))
                return
            img = cb.wait_for_image()
            if img is not None:
                ok, buf = img.save_to_bufferv("png", [], [])
                if ok:
                    self.eng.paste_data("image/png", bytes(buf))
                    return
        text = cb.wait_for_text()
        if text:
            self.eng.paste_data("text/plain;charset=utf-8", text)

    def paste_primary(self):
        """Middle-click: paste the text selected in any program (the desktop's
        selection), as on every Linux desktop."""
        cb = Gtk.Clipboard.get(Gdk.SELECTION_PRIMARY)
        text = cb.wait_for_text()
        if text:
            self.eng.paste_data("text/plain;charset=utf-8", text)

    def do_paste_text(self):
        self.do_paste(text_only=True)

    def do_paste_special(self):
        self.win.dialogs.paste_special()

    # format painter (Ctrl+Shift+C / Ctrl+Shift+V)
    CHAR_PROPS = ("CharStyleName", "CharFontName", "CharFontNameAsian", "CharFontNameComplex",
                  "CharHeight", "CharWeight", "CharPosture", "CharUnderline",
                  "CharUnderlineColor", "CharUnderlineHasColor", "CharStrikeout", "CharColor",
                  "CharBackColor", "CharHighlight", "CharEscapement",
                  "CharEscapementHeight", "CharCaseMap", "CharKerning", "CharScaleWidth",
                  "CharShadowed", "CharContoured", "CharRelief", "CharHidden", "CharLocale",
                  "CharTransparence")
    PARA_PROPS = ("ParaAdjust", "ParaLastLineAdjust", "ParaLeftMargin", "ParaRightMargin",
                  "ParaFirstLineIndent", "ParaTopMargin", "ParaBottomMargin",
                  "ParaLineSpacing", "ParaContextMargin", "ParaBackColor", "ParaTabStops",
                  "TopBorder", "BottomBorder", "LeftBorder", "RightBorder",
                  "TopBorderDistance", "BottomBorderDistance", "LeftBorderDistance",
                  "RightBorderDistance", "ParaKeepTogether", "ParaSplit", "ParaWidows",
                  "ParaOrphans", "OutlineLevel")

    def do_copy_format(self):
        data = self.copy_format_data()
        if data is not None:
            self.format_copy = data

    def copy_format_data(self):
        from . import docapi
        m = self.eng.model
        if m is None:
            return None
        vc = docapi.view_cursor(m)
        text = vc.getText()
        c = text.createTextCursorByRange(vc.getStart())
        if vc.isCollapsed():
            # the formatting at the cursor (the character before it, as typing)
            if not c.goLeft(1, True):
                c.goRight(1, True)
        else:
            c.goRight(1, True)
        chars = {}
        for k in self.CHAR_PROPS:
            try:
                chars[k] = c.getPropertyValue(k)
            except Exception:
                pass
        p = text.createTextCursorByRange(vc.getStart())
        paras = {}
        for k in ("ParaStyleName",) + self.PARA_PROPS:
            try:
                paras[k] = p.getPropertyValue(k)
            except Exception:
                pass
        # the paragraph's formatting comes along when the cursor is just
        # in it, or the selection takes in whole paragraphs
        whole = vc.isCollapsed()
        if not whole:
            s = text.createTextCursorByRange(vc.getStart())
            e = text.createTextCursorByRange(vc.getEnd())
            whole = s.isStartOfParagraph() and (e.isEndOfParagraph() or e.isStartOfParagraph())
        return {"chars": chars, "paras": paras, "with_para": whole}

    def do_paste_format(self):
        f = self.format_copy
        if not f or self.eng.model is None:
            self.do_paste_text()
            return
        self.apply_format_data(f)

    def apply_format_data(self, f):
        from . import docapi
        m = self.eng.model
        if not f or m is None or "chars" not in f:
            return
        um = m.getUndoManager()
        um.enterUndoContext("Paste Formatting")
        try:
            vc = docapi.view_cursor(m)
            text = vc.getText()
            if f.get("with_para"):
                c = text.createTextCursorByRange(vc.getStart())
                c.gotoStartOfParagraph(False)
                c.gotoRange(vc.getEnd(), True)
                c.gotoEndOfParagraph(True)
                paras = dict(f["paras"])
                st = paras.pop("ParaStyleName", None)
                if st:
                    try:
                        c.ParaStyleName = st
                    except Exception:
                        pass
                for k, v in paras.items():
                    try:
                        c.setPropertyValue(k, v)
                    except Exception:
                        pass
            if vc.isCollapsed():
                rng = text.createTextCursorByRange(vc.getStart())
                if not rng.isStartOfWord() or not rng.isEndOfWord():
                    rng.gotoStartOfWord(False)
                    rng.gotoEndOfWord(True)
                if not rng.getString():
                    rng = vc         # the formatting for what's typed next
            else:
                rng = vc
            chars = dict(f["chars"])
            cs = chars.pop("CharStyleName", None)
            try:
                rng.CharStyleName = cs or ""
            except Exception:
                pass
            for k, v in chars.items():
                try:
                    rng.setPropertyValue(k, v)
                except Exception:
                    pass
        finally:
            um.leaveUndoContext()

    def do_format_painter(self):
        self.cmd(".uno:FormatPaintbrush")

    # ------------------------------------------------------------ characters
    def font_name(self, name):
        self.cmd(".uno:CharFontName", {"CharFontName.FamilyName": name})

    def font_size(self, size):
        try:
            v = float(str(size).replace(",", "."))
        except ValueError:
            return
        v = max(1.0, min(1638.0, v))
        self.cmd(".uno:FontHeight", {"FontHeight.Height": ("float", repr(v))})

    def _cur_size(self):
        return _float(self.eng.get(".uno:FontHeight"), 11.0) or 11.0

    def do_grow_font(self):
        s = self._cur_size()
        nxt = next((x for x in SIZE_STEPS if x > s + 0.01), (int(s) // 10 + 1) * 10)
        self.font_size(nxt)

    def do_shrink_font(self):
        s = self._cur_size()
        prv = next((x for x in reversed(SIZE_STEPS) if x < s - 0.01), max(1, s - 1))
        self.font_size(prv)

    def do_grow_font_1(self):
        self.font_size(self._cur_size() + 1)

    def do_shrink_font_1(self):
        self.font_size(max(1, self._cur_size() - 1))

    def _selection_html(self):
        try:
            html, _ = self.eng.view.copy_selection("text/html")
            return html or ""
        except Exception:
            return ""

    def _has_selection(self):
        return self.eng.get(".uno:StateWordCount").startswith("Selected")

    def _vc(self):
        m = self.eng.model
        if m is None:
            return None
        try:
            return m.getCurrentController().getViewCursor()
        except Exception:
            return None

    def _toggle_casemap(self, value, css):
        vc = self._vc()
        if vc is not None:
            if vc.isCollapsed():
                self.cmd(".uno:SelectWord")
                GLib.timeout_add(60, lambda: (self._set_casemap(value), False)[1])
            else:
                self._set_casemap(value)
            return
        if not self._has_selection():
            self.cmd(".uno:SelectWord")
        on = css in self._selection_html().replace(" ", "")
        self.cmd(".uno:CaseMap", {"CaseMap": ("short", 0 if on else value)})

    def _set_casemap(self, value):
        vc = self._vc()
        try:
            vc.CharCaseMap = 0 if vc.CharCaseMap == value else value
        except Exception:
            pass

    def do_all_caps(self):
        self._toggle_casemap(1, "text-transform:uppercase")

    def do_small_caps(self):
        self._toggle_casemap(4, "font-variant:small-caps")

    def do_hidden(self):
        vc = self._vc()
        if vc is not None and not vc.isCollapsed():
            vc.CharHidden = not vc.CharHidden
            return
        if not self._has_selection():
            self.cmd(".uno:SelectWord")
        on = "display:none" in self._selection_html().replace(" ", "")
        self.cmd(".uno:CharHidden", {"CharHidden": ("boolean", "false" if on else "true")})

    def do_double_underline(self):
        self.cmd(".uno:UnderlineDouble")

    def do_word_underline(self):
        vc = self._vc()
        if vc is not None:
            on = vc.CharWordMode and vc.CharUnderline == 1
            vc.CharUnderline = 0 if on else 1
            vc.CharWordMode = not on
            return
        self.cmd(".uno:Underline", {"Underline.LineStyle": ("short", 1)})

    def underline_style(self, style):
        self.cmd(".uno:Underline", {"Underline.LineStyle": ("short", style)})

    def do_clear_char_format(self):
        self.cmd(".uno:ResetAttributes")

    def do_clear_all_formatting(self):
        self.cmd(".uno:ResetAttributes")
        self.apply_style("Normal")

    CASE_CYCLE = [".uno:ChangeCaseToLower", ".uno:ChangeCaseToUpper",
                  ".uno:ChangeCaseToTitleCase"]

    def do_change_case_cycle(self):
        """Shift+F3: lowercase -> Capitalize Each Word -> UPPERCASE -> lowercase,
        decided by the text itself so every press changes something."""
        vc = self._vc()
        txt = ""
        try:
            if vc is not None and not vc.isCollapsed():
                txt = vc.getString()
            elif vc is not None:
                c = vc.getText().createTextCursorByRange(vc.getStart())
                c.gotoStartOfWord(False)
                c.gotoEndOfWord(True)
                txt = c.getString()
        except Exception:
            pass
        letters = [ch for ch in txt if ch.isalpha()]
        if letters and all(ch.isupper() for ch in letters):
            nxt = ".uno:ChangeCaseToLower"
        elif letters and all(ch.islower() for ch in letters):
            nxt = ".uno:ChangeCaseToTitleCase"
        elif letters:
            nxt = ".uno:ChangeCaseToUpper"
        else:
            self._case_i = (getattr(self, "_case_i", -1) + 1) % 3
            nxt = self.CASE_CYCLE[self._case_i]
        self.cmd(nxt)

    # ------------------------------------------------------------ Alt+X
    def do_unicode_toggle(self):
        """Alt+X: hex code before the cursor -> character, or the character
        before the cursor -> its hex code."""
        vc = self._vc()
        if vc is None:
            return
        try:
            text = vc.getText()
            if not vc.isCollapsed():
                r = text.createTextCursorByRange(vc)
                s = r.getString()
                if s and all(c in "0123456789abcdefABCDEF" for c in s.replace("U+", "").replace("u+", "")):
                    r.setString(chr(int(s.replace("U+", "").replace("u+", ""), 16)))
                elif len(s) == 1:
                    r.setString("%04X" % ord(s))
                return
            c = text.createTextCursorByRange(vc.getStart())
            hexs = ""
            for n in range(1, 9):
                if not c.goLeft(1, True):
                    break
                s = c.getString()
                if s[0] in "0123456789abcdefABCDEF":
                    hexs = s
                    continue
                if s[0] == "+" and hexs and c.goLeft(1, True) and \
                        c.getString()[:2].upper() == "U+":
                    hexs = c.getString()
                break
            core = hexs[2:] if hexs[:2].upper() == "U+" else hexs
            if core and len(core) <= 6 and int(core, 16) <= 0x10FFFF:
                r = text.createTextCursorByRange(vc.getStart())
                r.goLeft(len(hexs), True)
                r.setString(chr(int(core, 16)))
                return
            r = text.createTextCursorByRange(vc.getStart())
            if r.goLeft(1, True) and r.getString():
                ch = r.getString()
                r.setString("%04X" % ord(ch))
        except Exception as e:
            print("alt+x:", e)

    # ------------------------------------------------------------ table rows
    def _table_cell(self):
        vc = self._vc()
        try:
            t, cell = vc.TextTable, vc.Cell
        except Exception:
            return None, None
        return t, cell

    def do_move_up(self):
        self._move_row_or_para(-1)

    def do_move_down(self):
        self._move_row_or_para(1)

    def _move_row_or_para(self, d):
        """Alt+Shift+Up/Down: in a table the row moves, as in the original."""
        t, cell = self._table_cell()
        if t is None or cell is None:
            self.cmd(".uno:MoveUp" if d < 0 else ".uno:MoveDown")
            return
        import re as _re
        name = cell.CellName
        mm = _re.match(r"([A-Z]+)(\d+)$", name)
        if not mm:
            return
        col, row = mm.group(1), int(mm.group(2)) - 1
        nrows = t.getRows().getCount()
        other = row + d
        if other < 0 or other >= nrows:
            return
        m = self.eng.model
        ctl = m.getCurrentController()
        names = t.getCellNames()
        try:
            ncols = t.getColumns().getCount()
            a = [t.getCellByPosition(c, row) for c in range(ncols)]
            b = [t.getCellByPosition(c, other) for c in range(ncols)]
        except Exception:
            return      # merged cells: leave it
        um = m.getUndoManager()
        um.enterUndoContext("Move Row")
        try:
            def grab(cl):
                tx = cl.getText()
                cur = tx.createTextCursor()
                cur.gotoStart(False)
                cur.gotoEnd(True)
                ctl.select(cur)
                return ctl.getTransferable(), bool(cur.getString())
            da = [grab(cl) for cl in a]
            db = [grab(cl) for cl in b]

            def put(cl, data):
                tx = cl.getText()
                cur = tx.createTextCursor()
                cur.gotoStart(False)
                cur.gotoEnd(True)
                cur.setString("")
                ctl.select(cur)
                if data[1]:
                    ctl.insertTransferable(data[0])
            for cl, data in zip(a, db):
                put(cl, data)
            for cl, data in zip(b, da):
                put(cl, data)
            target = t.getCellByName(col + str(other + 1))
            cur = target.getText().createTextCursor()
            cur.gotoStart(False)
            ctl.getViewCursor().gotoRange(cur, False)
        finally:
            um.leaveUndoContext()

    def font_color(self, color):
        self.cmd(".uno:Color", {"Color": ("long", color)})

    def highlight(self, color):
        self.cmd(".uno:CharBackColor", {"CharBackColor.Color": ("long", color)})

    def do_highlight(self):
        self.highlight(getattr(self.win, "last_highlight", 0xFFFF00))

    def do_font_color(self):
        self.font_color(getattr(self.win, "last_font_color", 0xC00000))

    # ------------------------------------------------------------ paragraphs
    def set_indents(self, left=None, right=None, first=None):
        l, r, f = para_margins(self.eng)
        l = l if left is None else left
        r = r if right is None else right
        f = f if first is None else first
        vc = self._vc()
        if vc is not None:
            try:
                vc.ParaLeftMargin = max(0, l)
                vc.ParaRightMargin = max(0, r)
                vc.ParaFirstLineIndent = f
                return
            except Exception:
                pass
        self.cmd(".uno:LeftRightParaMargin", {
            "LRSpace.TextLeftMargin": ("long", max(0, l)),
            "LRSpace.RightMargin": ("long", max(0, r)),
            "LRSpace.FirstLineIndent": ("long", f)})

    def do_indent(self):
        l, r, f = para_margins(self.eng)
        self.set_indents(left=(l // HALF_INCH + 1) * HALF_INCH)

    def do_outdent(self):
        l, r, f = para_margins(self.eng)
        self.set_indents(left=max(0, ((l - 1) // HALF_INCH) * HALF_INCH))

    def do_hanging_indent(self):
        l, r, f = para_margins(self.eng)
        hang = max(0, -f)
        self.set_indents(left=l + HALF_INCH, first=-(hang + HALF_INCH))

    def do_unhang(self):
        l, r, f = para_margins(self.eng)
        hang = max(0, -f)
        step = min(HALF_INCH, hang, l)
        if step > 0:
            self.set_indents(left=l - step, first=-(hang - step))

    def line_spacing(self, factor):
        self.cmd(".uno:LineSpacing", {"LineSpacing.Mode": ("short", 0),
                                      "LineSpacing.Height": ("short", int(round(factor * 100)))})

    def do_spacing_1(self):
        self.line_spacing(1.0)

    def do_spacing_15(self):
        self.line_spacing(1.5)

    def do_spacing_2(self):
        self.line_spacing(2.0)

    def set_spacing(self, before=None, after=None):
        b, a = para_spacing(self.eng)
        vc = self._vc()
        if vc is not None:
            try:
                vc.ParaTopMargin = b if before is None else before
                vc.ParaBottomMargin = a if after is None else after
                return
            except Exception:
                pass
        self.cmd(".uno:ULSpacing", {"ULSpace.Upper": ("long", b if before is None else before),
                                    "ULSpace.Lower": ("long", a if after is None else after)})

    def do_space_before_toggle(self):
        b, a = para_spacing(self.eng)
        self.set_spacing(before=0 if b else 423)

    def do_reset_paragraph(self):
        style = word_style(self.eng.get(".uno:StyleApply") or "Normal")
        self.apply_style(style)

    def apply_style(self, name):
        family = "CharacterStyles" if name in CHAR_STYLES else "ParagraphStyles"
        self.cmd(".uno:StyleApply", {"Style": engine_style(name), "FamilyName": family})
        if name == "List Bullet":
            if self.eng.get(".uno:DefaultBullet") != "true":
                self.cmd(".uno:DefaultBullet")

    def _para_style_now(self):
        """The paragraph style at the cursor, from the document itself (the
        engine's reported state can lag a moment behind a style change)."""
        vc = self._vc()
        try:
            return word_style(vc.ParaStyleName)
        except Exception:
            return word_style(self.eng.get(".uno:StyleApply"))

    def do_promote(self):
        self.eng.sync(lambda: self._heading_step(-1))

    def do_demote(self):
        self.eng.sync(lambda: self._heading_step(1))

    def _heading_step(self, d):
        """Alt+Shift+Left/Right: a heading moves a level; other paragraphs
        change list level. (Run once the engine has caught up, so a style
        applied just before is seen.)"""
        st = self._para_style_now()
        m = re.match(r"Heading (\d)", st)
        if m:
            self.apply_style("Heading %d" % max(1, min(9, int(m.group(1)) + d)))
        else:
            self.cmd(".uno:DecrementLevel" if d < 0 else ".uno:IncrementLevel")

    def do_bullets(self):
        self.cmd(".uno:DefaultBullet")
        GLib.timeout_add(150, self._list_style_fix)

    def do_numbering(self):
        self.cmd(".uno:DefaultNumbering")
        GLib.timeout_add(150, self._list_style_fix)

    def _list_style_fix(self):
        listed = self.eng.is_on(".uno:DefaultBullet") or self.eng.is_on(".uno:DefaultNumbering")
        cur = word_style(self.eng.get(".uno:StyleApply"))
        if listed and cur == "Normal":
            self.apply_style("List Paragraph")
        elif not listed and cur == "List Paragraph":
            self.apply_style("Normal")
        return False

    # ------------------------------------------------------------ view
    def do_zoom_in(self):
        self.win.status.step_zoom(10)

    def do_zoom_out(self):
        self.win.status.step_zoom(-10)
