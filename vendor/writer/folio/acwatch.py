"""The AutoCorrect Options button, as in the original: after AutoCorrect
changes what you typed, a small button appears under the change; its menu
changes it back, stops that correction from happening again, or opens the
AutoCorrect options.

Also the AutoCorrect features the engine lacks: capitalizing the names of
days, and leaving the first letter of table cells alone when that option is
off."""
import time

from gi.repository import GLib, Gtk, Pango, PangoCairo

from . import docapi, icons

TRIGGERS = {"space", "return", "kp_enter", "tab", "period", "comma", "semicolon", "colon",
            "exclam", "question", "parenright", "quotedbl", "apostrophe"}
DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


class ACWatch:
    def __init__(self, win, overlay):
        self.win = win
        self.overlay = overlay
        self.last = None
        self.pending = None
        btn = Gtk.Button()
        btn.get_style_context().add_class("folio-acbutton")
        btn.add(icons.image("cmd/sc_autocorrectdlg" if icons.exists("cmd/sc_autocorrectdlg")
                            else "cmd/sc_spellingandgrammardialog", 16))
        btn.set_tooltip_text("AutoCorrect Options")
        btn.set_halign(Gtk.Align.START)
        btn.set_valign(Gtk.Align.START)
        btn.set_no_show_all(True)
        btn.set_focus_on_click(False)
        btn.connect("clicked", lambda *_: self.menu())
        overlay.add_overlay(btn)
        self.btn = btn
        self.keys_since = 0
        win.engine.view.connect("button-press-event",
                                lambda *_: (self.hide(), setattr(self, "typed", ""), False)[2])
        win.canvas.get_vadjustment().connect("value-changed", lambda *_: self.hide())

    def settings(self):
        return self.win.app.settings

    # ------------------------------------------------------------ indents
    def native(self):
        return getattr(self.win.engine, "native", False)

    def tab_indent(self, keyname, mods):
        """Tab at the start of a paragraph sets its first-line indent;
        Backspace there takes it away (AutoFormat As You Type)."""
        if mods or keyname not in ("tab", "backspace") or \
                not self.settings().get("ac_tab_indent", True):
            return False
        if self.native():
            return self._tab_indent_native(keyname)
        m = self.win.engine.model
        if m is None:
            return False
        try:
            vc = docapi.view_cursor(m)
            if not vc.isCollapsed() or vc.Cell is not None:
                return False
            c = vc.getText().createTextCursorByRange(vc.getStart())
            if not c.isStartOfParagraph():
                return False
            if getattr(c, "NumberingIsNumber", False):
                return False
            p = c.getText().createTextCursorByRange(c.getStart())
            p.gotoEndOfParagraph(True)
            if keyname == "tab":
                if not p.getString().strip():
                    return False
                if c.ParaFirstLineIndent < 1270:
                    c.ParaFirstLineIndent = 1270
                    return True
                c.ParaLeftMargin = c.ParaLeftMargin + 1270
                return True
            if c.ParaFirstLineIndent > 0:
                c.ParaFirstLineIndent = 0
                return True
            if c.ParaLeftMargin > 0 and c.ParaFirstLineIndent == 0:
                c.ParaLeftMargin = max(0, c.ParaLeftMargin - 1270)
                return True
        except Exception:
            return False
        return False

    def _tab_indent_native(self, keyname):
        eng = self.win.engine
        ed = eng.ed
        if ed is None or ed.has_selection() or ed.cell_name() or ed.list_info() is not None:
            return False
        p, off = ed.caret_pos()
        if off != 0:
            return False
        d = ed.state() or {}
        first = d.get("ind_first", 0) or 0
        left = d.get("ind_left", 0) or 0
        if keyname == "tab":
            if not ed.para_text_of(p).strip():
                return False
            if first < 720:
                ed.set_indent(None, None, 720)
            else:
                ed.set_indent(left + 720, None, None)
            eng.view.after_edit()
            return True
        if first > 0:
            ed.set_indent(None, None, 0)
        elif left > 0:
            ed.set_indent(max(0, left - 720), None, None)
        else:
            return False
        eng.view.after_edit()
        return True

    def note(self, old, new, kind):
        """The new engine's AutoCorrect made a change: the button goes under it."""
        self.last = {"native": True, "old": old, "new": new, "kind": kind}
        if not self.settings().get("ac_buttons", True):
            return
        self.keys_since = 0
        GLib.timeout_add(60, self._place_native, new)

    def _place_native(self, new):
        eng = self.win.engine
        ed = eng.ed
        if ed is None or self.last is None:
            return False
        r = ed.caret_rect()
        if not r:
            return False
        v = eng.view
        x, y = v.to_widget(r[0], r[1], r[2])
        h = r[3] * v.ppp
        try:
            back = self._text_px(new + " ")
        except Exception:
            back = len(new) * 7
        res = v.translate_coordinates(self.overlay, int(x - back), int(y + h) + 1)
        if not res:
            return False
        ox, oy = res
        self.btn.set_margin_start(max(0, ox))
        self.btn.set_margin_top(max(0, oy))
        self.btn.get_child().show_all()
        self.btn.show()
        return False

    # ------------------------------------------------------------ keys
    typed = ""
    enters = 0

    def before_key(self, keyname, mods, event=None):
        """Called for every key the document gets. What was typed is
        followed here (the engine may still be catching up)."""
        if self.btn.get_visible():
            self.keys_since += 1
            if self.keys_since > 12:
                self.hide()
        if self.native():
            return False
        if mods:
            self.typed = ""
            return False
        ch = event.string if event is not None else ""
        if keyname == "backspace":
            self.typed = self.typed[:-1]
            return False
        if keyname in ("return", "kp_enter"):
            trig = "\n"
        elif keyname == "tab":
            trig = "\t"
        elif ch and ch.isprintable() and len(ch) == 1:
            trig = ch if keyname in TRIGGERS or not (ch.isalnum() or ch in "'’-") else None
            if trig is None:
                self.typed += ch
                return False
        else:
            self.typed = ""          # moving around: start afresh
            return False
        word = self.typed
        k = len(word)
        while k > 0 and not word[k - 1].isspace():
            k -= 1
        word = word[k:]
        self.typed += trig
        if trig == "\n":
            self.typed = ""
            self.enters += 1
            mark = self.enters
            GLib.timeout_add(200, self._no_drop_cap)
            from . import langdetect
            GLib.timeout_add(400, langdetect.check_paragraph, self.win)
        if word and self.win.engine.model is not None:
            GLib.timeout_add(150, self._check, word, trig,
                             mark if trig == "\n" else len(self.typed), 0)
        return False

    def _no_drop_cap(self):
        """A paragraph started with Enter after a drop cap doesn't get one
        (in the original the drop cap belongs to its paragraph alone)."""
        m = self.win.engine.model
        if m is None:
            return False
        try:
            vc = docapi.view_cursor(m)
            c = vc.getText().createTextCursorByRange(vc.getStart())
            if c.DropCapFormat.Lines < 2:
                return False
            prev = c.getText().createTextCursorByRange(c.getStart())
            if not prev.gotoPreviousParagraph(False) or prev.DropCapFormat.Lines < 2:
                return False
            from . import bridge
            c.DropCapFormat = bridge.struct("com.sun.star.style.DropCapFormat")
        except Exception:
            pass
        return False

    def _check(self, word, trig, mark, tries):
        self._cur_trig = trig
        m = self.win.engine.model
        if m is None:
            return False
        later = self.typed[mark:] if trig != "\n" else ""
        try:
            vc = docapi.view_cursor(m)
            c = vc.getText().createTextCursorByRange(vc.getStart())
            if trig == "\n":
                # back to the paragraph Enter ended (more may have been typed)
                for _i in range(1 + self.enters - mark):
                    c.gotoPreviousParagraph(False)
                c.gotoEndOfParagraph(False)
            c.gotoStartOfParagraph(True)
            P = c.getString()
        except Exception:
            return False
        tail = (trig if trig != "\n" else "") + later
        if not P.endswith(tail):
            if tries < 8:
                GLib.timeout_add(120, self._check, word, trig, mark, tries + 1)
            return False
        R = P[:len(P) - len(tail)]
        if trig == "\n" and not R.endswith(word) and \
                not R.endswith(self._replacements().get(word, "\0")) and \
                not R.lower().endswith(word.lower()):
            return False
        exp = self._replacements().get(word)
        if exp and R.endswith(exp) and exp != word:
            new = exp
        else:
            j = len(R)
            while j > 0 and not R[j - 1].isspace():
                j -= 1
            new = R[j:]
        start = len(R) - len(new)
        if not new:
            return False
        try:
            r = c.getText().createTextCursorByRange(c.getStart())
            r.goRight(start, False)
            r.goRight(len(new), True)
        except Exception:
            return False
        if new == word and trig == "\n" and start == 0 and word[:1].islower() and \
                word.isalpha() and self.settings().get("ac_caps_first", True):
            # the first word of a paragraph ended by Enter (the engine waits
            # for a space)
            try:
                if vc.Cell is None or self.settings().get("ac_caps_cells", True):
                    r.setString(word[0].upper() + word[1:])
                    r2 = c.getText().createTextCursorByRange(c.getStart())
                    r2.goRight(len(word), True)
                    self._remember(r2, word, word[0].upper() + word[1:], "caps", mark)
            except Exception:
                pass
            return False
        if new == word:
            # names of days (the engine has no such option)
            if self.settings().get("ac_days", True) and word.lower() in DAYS and \
                    word == word.lower():
                try:
                    r.setString(word.capitalize())
                    r2 = c.getText().createTextCursorByRange(c.getStart())
                    r2.goRight(start, False)
                    r2.goRight(len(word), True)
                    self._remember(r2, word, word.capitalize(), "days", mark)
                except Exception:
                    pass
            return False
        if new in ("“", "”", "‘", "’"):
            return False
        kind = "caps" if word.lower() == new.lower() else "replace"
        import re as _re
        if kind == "replace" and _re.fullmatch(r"\d+/\d+", word) and \
                not self.settings().get("ac_fractions", True):
            r.setString(word)
            return False
        if kind == "caps" and not self.settings().get("ac_caps_cells", True):
            try:
                cell = vc.Cell
                if cell is not None and start == 0:
                    first = cell.getText().createTextCursor()
                    first.gotoStart(False)
                    if cell.getText().compareRegionStarts(first, c.getStart()) == 0:
                        r.setString(word)
                        return False
            except Exception:
                pass
        self._remember(r, word, new, kind, mark)
        return False

    _repl = None

    def _replacements(self):
        if ACWatch._repl is None:
            try:
                from . import autocorrect, options
                _lang, path = options._ac_lang_path(self.win)
                ACWatch._repl = dict(autocorrect.read_list(path)) if path else {}
            except Exception:
                ACWatch._repl = {}
        return ACWatch._repl

    def _remember(self, rng, old, new, kind, mark=None):
        self.last = {"range": rng, "old": old, "new": new, "kind": kind}
        if not self.settings().get("ac_buttons", True):
            return
        self.keys_since = 0
        # typing has moved on (another line, more words): the button would
        # land in the wrong place, so it isn't shown
        if mark is not None and getattr(self, "_cur_trig", "") == "\n":
            if self.enters != mark or self.typed:
                return
        elif mark is not None and len(self.typed) > mark + 1:
            return
        GLib.timeout_add(60, self._place, len(new))

    # ------------------------------------------------------------ button
    def _text_px(self, text):
        import cairo
        eng = self.win.engine
        try:
            size = float(eng.get(".uno:FontHeight") or 11)
        except ValueError:
            size = 11.0
        font = eng.get(".uno:CharFontName") or "Carlito"
        layout = PangoCairo.create_layout(cairo.Context(
            cairo.ImageSurface(cairo.FORMAT_ARGB32, 1, 1)))
        layout.set_font_description(Pango.FontDescription("%s %spx" % (font, size * 96 / 72.0)))
        layout.set_text(text, -1)
        w, _h = layout.get_pixel_size()
        return w * (eng.view.get_zoom() or 1.0)

    def _place(self, nchars):
        cur = getattr(self.win, "_follow_rect", None)
        if cur is None or self.last is None:
            return False
        x, y, w, h = cur
        eng = self.win.engine
        px, py = eng.twips_to_px(x, y + h)
        try:
            back = self._text_px(self.last["new"] + " ")
        except Exception:
            back = nchars * 7
        res = eng.view.translate_coordinates(self.overlay, int(px - back), int(py) + 1)
        if not res:
            return False
        ox, oy = res
        if oy < 0 or oy > self.overlay.get_allocated_height() - 10:
            return False
        self.btn.set_margin_start(max(0, ox))
        self.btn.set_margin_top(max(0, oy))
        self.btn.get_child().show_all()
        self.btn.show()
        return False

    def hide(self):
        self.btn.hide()

    def menu(self):
        last = self.last
        if last is None:
            return
        from .ribbon import menu_popover
        old, new, kind = last["old"], last["new"], last["kind"]
        if kind == "caps":
            items = [("Undo Automatic Capitalization", lambda: self.change_back()),
                     ("Stop Auto-capitalizing First Letter of Sentences",
                      lambda: self.stop("ac_caps_first"))]
        elif kind == "days":
            items = [("Undo Automatic Capitalization", lambda: self.change_back()),
                     ("Stop Capitalizing Names of Days", lambda: self.stop("ac_days"))]
        else:
            items = [("Change back to “%s”" % old, lambda: self.change_back()),
                     ("Stop Automatically Correcting “%s”" % old, lambda: self.stop_word())]
        items += [None, ("Control AutoCorrect Options...",
                         lambda: GLib.idle_add(lambda: (self.win.dialogs.autocorrect_options(),
                                                        False)[1]))]
        pop = menu_popover(self.btn, items)
        pop.popup()

    def change_back(self):
        last, self.last = self.last, None
        self.hide()
        if last is None:
            return
        if last.get("native"):
            ac = getattr(self.win.engine.view, "autocorrect", None)
            if ac is not None and ac.undo_last():
                self.win.engine.view.after_edit()
            self.win.focus_document()
            return
        m = self.win.engine.model
        um = m.getUndoManager()
        um.enterUndoContext("Undo AutoCorrect")
        try:
            if last["range"].getString() == last["new"]:
                last["range"].setString(last["old"])
        finally:
            um.leaveUndoContext()
        self.win.focus_document()

    def stop(self, key):
        self.change_back()
        self.settings()[key] = False
        self.win.app.save_settings()
        from .app import apply_engine_config
        apply_engine_config(self.settings())

    def stop_word(self):
        last = self.last
        self.change_back()
        if last is None:
            return
        try:
            from . import options
            options.remove_autocorrect_entry(self.win, last["old"])
        except Exception as e:
            print("autocorrect stop:", e)
