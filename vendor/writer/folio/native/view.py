"""The document view for the new engine: pages drawn by folio_core, the
caret, selection, keyboard, input methods and the mouse."""
import time

import cairo
from gi.repository import Gdk, GLib, GObject, Gtk

PAGE_GAP = 16          # pixels between pages (and above the first)
CARET_BLINK = 530      # ms, the desktop's usual rate
BG = (0.902, 0.902, 0.902)


class NativeView(Gtk.DrawingArea):
    __gsignals__ = {
        # the same signals LOKDocView has, so the window can connect to them
        "cursor-changed": (GObject.SignalFlags.RUN_LAST, None, (int, int, int, int)),
        "hyperlink-clicked": (GObject.SignalFlags.RUN_LAST, None, (str,)),
        "password-required": (GObject.SignalFlags.RUN_LAST, None, (str, bool)),
        "comment": (GObject.SignalFlags.RUN_LAST, None, (str,)),
        # the document changed (text or formatting)
        "changed": (GObject.SignalFlags.RUN_LAST, None, ()),
        # caret or selection moved
        "selection-changed": (GObject.SignalFlags.RUN_LAST, None, ()),
        "zoom-changed": (GObject.SignalFlags.RUN_LAST, None, (float,)),
    }

    def __init__(self):
        super().__init__()
        self.ed = None
        self.zoom = 1.0
        self.set_can_focus(True)
        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK |
                        Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.KEY_PRESS_MASK |
                        Gdk.EventMask.KEY_RELEASE_MASK | Gdk.EventMask.SCROLL_MASK |
                        Gdk.EventMask.SMOOTH_SCROLL_MASK | Gdk.EventMask.FOCUS_CHANGE_MASK)
        self._cache = {}             # page -> (key, surface)
        self.highlights = []         # Reading Highlight: (page, x, y, w, h)
        self.marks = False           # Show/Hide ¶
        self.gridlines = True        # View Gridlines (tables without borders)
        self._origins = []           # page -> (x, y) in pixels
        self._caret_on = True
        self._blink_id = 0
        self._dragging = False
        self._last_click = (0, 0.0)
        self.im = Gtk.IMMulticontext()
        self.im.connect("commit", self._on_commit)
        self.im.connect("preedit-changed", lambda *_: self.queue_draw())
        self.connect("draw", self._draw)
        self.connect("button-press-event", self._press)
        self.connect("button-release-event", self._release)
        self.connect("motion-notify-event", self._motion)
        self.connect("key-press-event", self._key)
        self.connect("key-release-event", lambda w, e: self.im.filter_keypress(e))
        self.connect("focus-in-event", self._focus_in)
        self.connect("focus-out-event", self._focus_out)
        self.connect("realize", lambda *_: self.im.set_client_window(self.get_window()))
        self.connect("size-allocate", lambda *_: self._relayout_pages())
        from .objects import ObjectHandles
        self.objs = ObjectHandles(self)
        # modal tools (crop, edit points, select objects...): first say on the mouse
        self.tools = []
        self.speller = None          # spelling as you type (set by the window)
        self.typing = False
        self._typing_id = 0

    editable = True
    autocorrect = None          # the window's AutoCorrect (set by the window)

    def set_edit(self, on):
        """Read-only (restricted editing, the Original display) or not."""
        self.editable = bool(on)

    def get_edit(self):
        return self.editable

    # LOKDocView calls other parts of the app make
    def get_command_values(self, cmd):
        return ""

    def post_command(self, *a):
        pass

    def copy_selection(self, mime):
        return "", None

    # ------------------------------------------------------------ document
    def set_editor(self, ed):
        self.ed = ed
        self._cache.clear()
        self._relayout_pages()
        self.queue_draw()
        self._notify_selection()

    def get_zoom(self):
        return self.zoom

    def set_zoom(self, z):
        z = max(0.1, min(5.0, z))
        if abs(z - self.zoom) < 1e-6:
            return
        # keep the caret's place on screen
        self.zoom = z
        self._cache.clear()
        self._relayout_pages()
        self.queue_draw()
        self.emit("zoom-changed", z)
        GLib.idle_add(lambda: (self.scroll_to_caret(), False)[1])

    @property
    def ppp(self):
        """Pixels per point (100% shows a 96 dpi page, as the original)."""
        return self.zoom * 96.0 / 72.0

    # pages per row (1: the usual column of pages; more: Multiple Pages);
    # side: Side to Side, every page in one row, turned like a book's
    columns = 1
    side = False

    def set_page_layout(self, columns=1, side=False):
        """Pages one under another, several to a row, or side to side
        (still editable)."""
        self.columns = max(1, int(columns))
        self.side = bool(side)
        self._cache.clear()
        self._relayout_pages()
        self.queue_draw()

    # Draft / Web Layout: the strips the engine lays the text out in, edge to edge
    continuous = False

    def _relayout_pages(self):
        if self.ed is None:
            return
        n = self.ed.page_count()
        sizes = [self.ed.page_size(i) for i in range(n)]
        s = self.ppp
        self._origins = []
        if self.continuous:
            if self.ed.view_mode() == 2:
                want = max(144.0, self.get_allocated_width() / s)
                if abs(want - (sizes[0][0] if sizes else want)) > 2 and self.get_allocated_width() > 50:
                    GLib.idle_add(self._web_width, want)
            y = 0.0
            x = 0.0 if self.ed.view_mode() == 2 else PAGE_GAP
            wmax = 0.0
            for w, h in sizes:
                self._origins.append((x, y))
                y += h * s
                wmax = max(wmax, w * s)
            self.set_size_request(int(wmax + x), int(y))
            return
        if self.side:
            # one row: page 1 alone on the right of the first spread, as the
            # original's book view, then pairs
            x = PAGE_GAP
            hmax = max([h for _w, h in sizes] or [792]) * s
            for w, h in sizes:
                self._origins.append((x, PAGE_GAP + (hmax - h * s) / 2.0))
                x += w * s + PAGE_GAP
            self.set_size_request(int(x), int(hmax + 2 * PAGE_GAP))
            return
        cols = max(1, min(self.columns, n or 1))
        colw = max([w for w, _h in sizes] or [612]) * s
        width = cols * colw + (cols + 1) * PAGE_GAP
        avail = max(self.get_allocated_width(), int(width))
        x0 = (avail - width) / 2.0 + PAGE_GAP
        y = PAGE_GAP
        rowh = 0.0
        for i, (w, h) in enumerate(sizes):
            c = i % cols
            if c == 0 and i > 0:
                y += rowh + PAGE_GAP
                rowh = 0.0
            x = x0 + c * (colw + PAGE_GAP) + (colw - w * s) / 2.0
            self._origins.append((x, y))
            rowh = max(rowh, h * s)
        y += rowh + PAGE_GAP
        self.set_size_request(int(width), int(y))

    def _web_width(self, want):
        if self.ed is not None and self.continuous and self.ed.view_mode() == 2:
            self.ed.set_view_mode(2, want)
            self.document_changed()
        return False

    def page_at(self, x, y):
        """(page, x pt, y pt) under a widget point (the nearest page)."""
        if not self._origins:
            return None
        s = self.ppp
        best, bd = 0, None
        for i, (ox, oy) in enumerate(self._origins):
            pw, ph = self.ed.page_size(i)
            dx = 0 if ox <= x <= ox + pw * s else min(abs(x - ox), abs(x - ox - pw * s))
            dy = 0 if oy <= y <= oy + ph * s else min(abs(y - oy), abs(y - oy - ph * s))
            d = dx * dx + dy * dy
            if bd is None or d < bd - 1e-6:
                best, bd = i, d
        ox, oy = self._origins[best]
        return best, (x - ox) / s, (y - oy) / s

    def zone(self, pg, y):
        """'header', 'footer' or 'body' for a point of a page."""
        top, bottom = self.ed.page_body(pg)
        if y < top:
            return "header"
        if y > bottom:
            return "footer"
        return "body"

    def to_widget(self, page, x, y):
        if page >= len(self._origins):
            return 0, 0
        ox, oy = self._origins[page]
        return ox + x * self.ppp, oy + y * self.ppp

    def set_gridlines(self, on):
        self.gridlines = bool(on)
        self.queue_draw()

    def set_marks(self, on):
        """Show/Hide ¶."""
        self.marks = bool(on)
        self.queue_draw()

    def document_changed(self):
        """Text or formatting changed: pages are drawn again."""
        self._cache.clear()
        self.highlights = []
        self._relayout_pages()
        self.queue_draw()
        self.emit("changed")
        self._notify_selection()

    # ------------------------------------------------------------- drawing
    def _page_surface(self, i):
        sf = self.get_scale_factor() or 1
        key = (self.ed.version, self.zoom, sf, self.marks, self.gridlines)
        hit = self._cache.get(i)
        if hit and hit[0] == key:
            return hit[1]
        w, h, stride, data = self.ed.render_page(i, self.ppp * sf, self.gridlines, self.marks)
        surf = cairo.ImageSurface.create_for_data(bytearray(data), cairo.FORMAT_ARGB32, w, h,
                                                  stride)
        surf.set_device_scale(sf, sf)
        self._cache[i] = (key, surf)
        # keep memory in check: only pages near the screen stay
        if len(self._cache) > 16:
            for k in sorted(self._cache, key=lambda k: abs(k - i))[16:]:
                self._cache.pop(k, None)
        return surf

    def _draw(self, widget, cr):
        cr.set_source_rgb(*((1, 1, 1) if self.continuous else BG))
        cr.paint()
        if self.ed is None:
            return False
        x1, y1, x2, y2 = cr.clip_extents()
        s = self.ppp
        rects = {}
        for (pg, x, y, w, h) in self.ed.selection_rects():
            rects.setdefault(pg, []).append((x, y, w, h))
        hl = {}
        for (pg, x, y, w, h) in self.highlights:
            hl.setdefault(pg, []).append((x, y, w, h))
        caret = None
        if self.has_focus() and self._caret_on and not self.ed.has_selection() and \
                not self.objs.active():
            caret = self.ed.caret_rect()
        for i, (ox, oy) in enumerate(self._origins):
            pw, ph = self.ed.page_size(i)
            if oy > y2 or oy + ph * s < y1 or ox > x2 or ox + pw * s < x1:
                continue
            # the page's shadow
            if not self.continuous:
                cr.set_source_rgba(0, 0, 0, 0.16)
                cr.rectangle(ox + 1, oy + 1, pw * s + 1, ph * s + 1)
                cr.fill()
            surf = self._page_surface(i)
            cr.set_source_surface(surf, ox, oy)
            cr.paint()
            self._dim(cr, i, ox, oy, pw, ph)
            if self.speller is not None:
                from . import spell
                spell.draw(cr, self.speller.page_marks(i), ox, oy, s)
            if i in hl:
                cr.save()
                cr.set_operator(cairo.OPERATOR_MULTIPLY)
                cr.set_source_rgb(1.0, 1.0, 0.0)
                for (x, y, w, h) in hl[i]:
                    cr.rectangle(ox + x * s, oy + y * s, w * s, h * s)
                cr.fill()
                cr.restore()
            for (x, y, w, h) in self._control_frame().get(i, ()):
                # the content control the caret is in: a frame, as Word draws it
                cr.save()
                cr.set_source_rgb(0.55, 0.55, 0.55)
                cr.set_line_width(1)
                cr.rectangle(round(ox + x * s) - 1.5, round(oy + y * s) - 0.5, round(w * s) + 3, round(h * s) + 1)
                cr.stroke()
                cr.restore()
            shade = [r for r in getattr(self, "merge_shading", ()) if r[0] == i]
            if shade:
                cr.save()
                cr.set_operator(cairo.OPERATOR_MULTIPLY)
                cr.set_source_rgb(0.82, 0.82, 0.82)
                for (_p, x, y, w, h) in shade:
                    cr.rectangle(ox + x * s, oy + y * s, w * s, h * s)
                cr.fill()
                cr.restore()
            if i in rects:
                cr.set_source_rgba(0.0, 0.33, 0.8, 0.28)
                for (x, y, w, h) in rects[i]:
                    cr.rectangle(ox + x * s, oy + y * s, w * s, h * s)
                cr.fill()
            if caret and caret[0] == i:
                _pg, x, y, h = caret
                cx = round(ox + x * s) + 0.5
                cr.set_source_rgb(0, 0, 0)
                cr.set_line_width(max(1.0, round(s * 0.75)))
                cr.move_to(cx, oy + y * s)
                cr.line_to(cx, oy + (y + h) * s)
                cr.stroke()
        self.objs.draw(cr)
        for t in self.tools:
            if t.active:
                t.draw(cr)
        return False

    def _dim(self, cr, i, ox, oy, pw, ph):
        """Headers and footers show faded while the body is edited, and the
        body while they are."""
        s = self.ppp
        top, bottom = self.ed.page_body(i)
        cr.save()
        if self.ed.story() == "hf":
            cr.set_source_rgba(1, 1, 1, 1.0 if getattr(self, "hide_body", False) else 0.55)
            cr.rectangle(ox, oy + top * s, pw * s, (bottom - top) * s)
            cr.fill()
            if self.ed.story_page() is not None:
                # the header and footer's edges, and their names
                cr.set_source_rgb(0.18, 0.45, 0.85)
                cr.set_line_width(1)
                cr.set_dash([4, 3])
                kind = self.ed.page_hf_kind(i)
                odd_even = self.ed.setting("evenAndOddHeaders")
                pre = ("First Page " if kind == 1 else "Even Page " if kind == 2 else
                       "Odd Page " if odd_even else "")
                nsec = self.ed.section_count() if hasattr(self.ed, "section_count") else 1
                suffix = (" -Section %d-" % (self.ed.page_section(i) + 1)) if nsec > 1 else ""
                for yy, name in ((top, pre + "Header" + suffix), (bottom, pre + "Footer" + suffix)):
                    y = round(oy + yy * s) + 0.5
                    cr.move_to(ox, y)
                    cr.line_to(ox + pw * s, y)
                    cr.stroke()
                    cr.set_dash([])
                    cr.select_font_face("Sans")
                    cr.set_font_size(11)
                    ext = cr.text_extents(name)
                    bx, by = ox + 8, (y if "Header" in name else y - ext.height - 8)
                    cr.set_source_rgb(0.85, 0.9, 0.98)
                    cr.rectangle(bx, by, ext.width + 10, ext.height + 8)
                    cr.fill()
                    cr.set_source_rgb(0.18, 0.45, 0.85)
                    cr.move_to(bx + 5, by + ext.height + 3)
                    cr.show_text(name)
                    cr.set_dash([4, 3])
        else:
            cr.set_source_rgba(1, 1, 1, 0.45)
            cr.rectangle(ox, oy, pw * s, top * s)
            cr.rectangle(ox, oy + bottom * s, pw * s, (ph - bottom) * s)
            cr.fill()
        cr.restore()

    # ---------------------------------------------------------------- caret
    def _restart_blink(self):
        self._caret_on = True
        if self._blink_id:
            GLib.source_remove(self._blink_id)
        self._blink_id = GLib.timeout_add(CARET_BLINK, self._blink)

    def _blink(self):
        self._caret_on = not self._caret_on
        r = self.ed.caret_rect() if self.ed else None
        if r:
            x, y = self.to_widget(r[0], r[1], r[2])
            self.queue_draw_area(int(x) - 3, int(y) - 2, 7, int(r[3] * self.ppp) + 4)
        return True

    def _focus_in(self, *a):
        self.im.focus_in()
        self._restart_blink()
        self.queue_draw()
        return False

    def _focus_out(self, *a):
        self.im.focus_out()
        if self._blink_id:
            GLib.source_remove(self._blink_id)
            self._blink_id = 0
        self.queue_draw()
        return False

    def _notify_selection(self):
        self.objs.refresh()
        self._restart_blink()
        self.queue_draw()
        r = self.ed.caret_rect() if self.ed else None
        if r:
            x, y = self.to_widget(r[0], r[1], r[2])
            h = r[3] * self.ppp
            loc = Gdk.Rectangle()
            loc.x, loc.y, loc.width, loc.height = int(x), int(y), 1, int(h)
            self.im.set_cursor_location(loc)
            self.emit("cursor-changed", int(x), int(y), 1, int(h))
        self.emit("selection-changed")

    def scroll_to_caret(self):
        r = self.ed.caret_rect() if self.ed else None
        if not r:
            return
        x, y = self.to_widget(r[0], r[1], r[2])
        h = r[3] * self.ppp
        sw = self.get_parent()
        while sw is not None and not isinstance(sw, Gtk.ScrolledWindow):
            sw = sw.get_parent()
        if sw is None:
            return
        va = sw.get_vadjustment()
        ha = sw.get_hadjustment()
        margin = 24
        if y < va.get_value() + margin:
            va.set_value(max(0, y - margin))
        elif y + h > va.get_value() + va.get_page_size() - margin:
            va.set_value(y + h - va.get_page_size() + margin)
        if x < ha.get_value() + margin:
            ha.set_value(max(0, x - margin))
        elif x > ha.get_value() + ha.get_page_size() - margin:
            ha.set_value(x - ha.get_page_size() + margin)

    def after_move(self):
        self._notify_selection()
        self.scroll_to_caret()

    def after_edit(self):
        self.document_changed()
        self.scroll_to_caret()
        # Shift+F5 goes back to these
        try:
            pos = tuple(self.ed.caret_pos())
            spots = self.__dict__.setdefault("edit_spots", [])
            if not spots or spots[-1][0] != pos[0]:
                spots.append(pos)
            else:
                spots[-1] = pos
            del spots[:-4]
        except Exception:
            pass

    # ---------------------------------------------------------------- input
    def _on_commit(self, im, text):
        if self.ed is None or not text or not self.editable:
            return
        if self.objs.active():
            self.ed.deselect_object()
        self.ed.type_text(text)
        if self.autocorrect is not None and len(text) == 1:
            self.autocorrect.typed(text)
        # the word being typed isn't marked until the typing pauses or leaves it
        self.typing = text.isalnum() or text in "'’"
        if self._typing_id:
            GLib.source_remove(self._typing_id)
        self._typing_id = GLib.timeout_add(1500, self._typing_done)
        self.after_edit()

    def _typing_done(self):
        self._typing_id = 0
        if self.typing:
            self.typing = False
            if self.speller is not None:
                self.speller.invalidate()
            self.queue_draw()
        return False

    MOVES = {
        Gdk.KEY_Left: ("left", "word_left"), Gdk.KEY_KP_Left: ("left", "word_left"),
        Gdk.KEY_Right: ("right", "word_right"), Gdk.KEY_KP_Right: ("right", "word_right"),
        Gdk.KEY_Up: ("up", "para_up"), Gdk.KEY_KP_Up: ("up", "para_up"),
        Gdk.KEY_Down: ("down", "para_down"), Gdk.KEY_KP_Down: ("down", "para_down"),
        Gdk.KEY_Home: ("home", "doc_start"), Gdk.KEY_KP_Home: ("home", "doc_start"),
        Gdk.KEY_End: ("end", "doc_end"), Gdk.KEY_KP_End: ("end", "doc_end"),
    }

    def _key(self, widget, event):
        if self.ed is None:
            return False
        mods = event.state & Gtk.accelerator_get_default_mod_mask()
        ctrl = bool(mods & Gdk.ModifierType.CONTROL_MASK)
        shift = bool(mods & Gdk.ModifierType.SHIFT_MASK)
        alt = bool(mods & Gdk.ModifierType.MOD1_MASK)
        k = event.keyval
        if k == Gdk.KEY_Escape and self.ed.story() == "textbox":
            self.ed.leave_textbox()
            self.document_changed()
            self.objs.refresh()
            return True
        if self.objs.active() and not alt:
            if k in (Gdk.KEY_Delete, Gdk.KEY_KP_Delete, Gdk.KEY_BackSpace):
                self.ed.object_delete()
                self.after_edit()
                return True
            if k == Gdk.KEY_Escape:
                self.ed.deselect_object()
                self.after_move()
                return True
            steps = {Gdk.KEY_Left: (-1, 0), Gdk.KEY_Right: (1, 0), Gdk.KEY_Up: (0, -1),
                     Gdk.KEY_Down: (0, 1)}
            if k in steps and not self.objs.info["inline"]:
                d = 1.0 if ctrl else 7.2
                self.objs.nudge(steps[k][0] * d, steps[k][1] * d)
                return True
            if k in self.MOVES:
                self.ed.deselect_object()
        if k == Gdk.KEY_Escape and self.ed.story() == "textbox":
            self.ed.leave_textbox()
            self.document_changed()
            self.objs.refresh()
            return True
        if k == Gdk.KEY_Escape and self.ed.story() in ("hf", "notes"):
            self.ed.edit_header_footer(None)
            self.document_changed()
            self.scroll_to_caret()
            return True
        if k in self.MOVES and not alt:
            plain, with_ctrl = self.MOVES[k]
            self.ed.move_caret(with_ctrl if ctrl else plain, shift)
            self.after_move()
            return True
        if k in (Gdk.KEY_Page_Up, Gdk.KEY_Page_Down, Gdk.KEY_KP_Page_Up, Gdk.KEY_KP_Page_Down):
            sw = self.get_parent()
            while sw is not None and not isinstance(sw, Gtk.ScrolledWindow):
                sw = sw.get_parent()
            page = (sw.get_vadjustment().get_page_size() if sw else 600) / self.ppp
            down = k in (Gdk.KEY_Page_Down, Gdk.KEY_KP_Page_Down)
            self.ed.move_by(page if down else -page, shift)
            if sw:
                va = sw.get_vadjustment()
                va.set_value(va.get_value() + (1 if down else -1) * va.get_page_size())
            self.after_move()
            return True
        if not self.editable and k in (Gdk.KEY_BackSpace, Gdk.KEY_Delete, Gdk.KEY_KP_Delete,
                                       Gdk.KEY_Return, Gdk.KEY_KP_Enter, Gdk.KEY_Tab,
                                       Gdk.KEY_ISO_Left_Tab):
            return True
        if k == Gdk.KEY_BackSpace and not alt:
            self.ed.delete(False, ctrl)
            self.after_edit()
            return True
        if k in (Gdk.KEY_Delete, Gdk.KEY_KP_Delete) and not alt:
            self.ed.delete(True, ctrl)
            self.after_edit()
            return True
        if k in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) and not alt and not ctrl:
            if not shift and self.ed.cell_name() and self.ed.para_before_table():
                self.after_edit()
                return True
            if self.autocorrect is not None and self.autocorrect.before_break() in ("table", "handled"):
                self.after_edit()
                return True
            self.ed.type_text("\u000b" if shift else "\n")
            self.after_edit()
            return True
        if k == Gdk.KEY_Tab and ctrl and not alt and self.ed.cell_name():
            # Ctrl+Tab in a table: a tab character
            self.ed.type_text("\t")
            self.after_edit()
            return True
        if k in (Gdk.KEY_Tab, Gdk.KEY_ISO_Left_Tab) and not ctrl and not alt and \
                self.ed.cell_name():
            # in a table, Tab goes to the next cell (a new row after the last)
            self.ed.cell_step(shift or k == Gdk.KEY_ISO_Left_Tab)
            self.after_edit()
            return True
        if k in (Gdk.KEY_Tab, Gdk.KEY_ISO_Left_Tab) and not ctrl and not alt:
            # in a list, Tab and Shift+Tab change the level
            if (self.ed.at_list_item_start() or self.ed.has_selection()) and \
                    self.ed.change_list_level(-1 if shift or k == Gdk.KEY_ISO_Left_Tab else 1):
                self.after_edit()
                return True
            if k == Gdk.KEY_ISO_Left_Tab or shift:
                return True
            self.ed.type_text("\t")
            self.after_edit()
            return True
        if ctrl and not alt:
            name = (Gdk.keyval_name(Gdk.keyval_to_lower(k)) or "").lower()
            if name == "a":
                self.ed.select_all()
                self.after_move()
                return True
            if name == "z":
                self.ed.undo()
                self.after_edit()
                return True
            if name == "y":
                self.ed.redo()
                self.after_edit()
                return True
            return False
        if self.im.filter_keypress(event):
            return True
        return False

    # the window's equation editor and the like see clicks first
    press_hook = None

    def _press(self, widget, event):
        if self.ed is None:
            return False
        if self.press_hook is not None and self.press_hook(event):
            return True
        self.grab_focus()
        for t in self.tools:
            if t.active and t.press(event):
                self.queue_draw()
                return True
        if event.button != 1:
            return False
        hit = self.page_at(event.x, event.y)
        if hit is None:
            return True
        pg, x, y = hit
        shift = bool(event.state & Gdk.ModifierType.SHIFT_MASK)
        ctrl = bool(event.state & Gdk.ModifierType.CONTROL_MASK)
        if event.type == Gdk.EventType.BUTTON_PRESS and (shift or ctrl) and self.ed.story() == "body" \
                and self.ed.object_at(pg, x, y):
            # Shift/Ctrl+click: more objects in the selection
            if not self.objs.active() and not self.ed.selected_object():
                self.ed.select_object_at(pg, x, y)
            else:
                self.ed.toggle_object_at(pg, x, y)
            self.objs.refresh()
            self.after_move()
            self.queue_draw()
            return True
        if event.type == Gdk.EventType.BUTTON_PRESS and not shift:
            # pictures and shapes: their handles, or select one
            if self.objs.active() and self.objs.press(event.x, event.y, shift):
                self.queue_draw()
                return True
            # a text box's text: the caret goes in
            story = self.ed.story()
            if story in ("body", "textbox") and self.ed.textbox_at(pg, x, y):
                if self.objs.active():
                    self.ed.deselect_object()
                    self.objs.refresh()
                self.ed.edit_textbox(pg, x, y)
                self.document_changed()
                self._dragging = True
                self.after_move()
                return True
            if story == "textbox":
                # out of the text box: back to the body text
                self.ed.edit_header_footer(None)
                self.document_changed()
            if self.ed.select_object_at(pg, x, y):
                self.after_move()
                self.objs.press(event.x, event.y, shift)
                return True
        if self.objs.active():
            self.ed.deselect_object()
            self.objs.refresh()
        zone = self.zone(pg, y)
        story = self.ed.story()
        # footnotes: a click on one edits it, a click on the text goes back
        if event.type == Gdk.EventType.BUTTON_PRESS and story != "hf":
            on_note = self.ed.note_at(pg, y)
            if on_note and (story != "notes" or self.ed.story_page() != pg):
                self.ed.edit_notes(pg)
                self.ed.click(pg, x, y, False)
                self.document_changed()
                return True
            if story == "notes" and not on_note:
                self.ed.edit_notes(None)
                if zone == "body":
                    self.ed.click(pg, x, y, False)
                self.document_changed()
                return True
        in_hf = self.ed.story() == "hf"
        if event.type == Gdk.EventType._2BUTTON_PRESS and (zone != "body") != in_hf:
            # double-click a margin: its header / footer; the body: back
            if zone == "body":
                self.ed.edit_header_footer(None)
            else:
                footer = zone == "footer"
                has = self.ed.page_hf(pg)[1 if footer else 0]
                if not has:
                    self.ed.ensure_header_footer(self.ed.page_section(pg), footer)
                self.ed.edit_header_footer(pg, footer)
                if zone != "body":
                    self.ed.click(pg, x, y, False)
            self.document_changed()
            return True
        if in_hf and (zone == "body" or self.ed.story_page() != pg):
            # while in a header or footer, clicks on the body do nothing
            return True
        if not in_hf and zone != "body" and event.type == Gdk.EventType.BUTTON_PRESS \
                and self.ed.story() == "body":
            return True
        if not in_hf and self.ed.story() == "body" and zone == "body" and self._in_selection_bar(pg, x):
            # the selection bar in the left margin: the line, the paragraph, everything
            self.bar_select = True
            left = self.ed.page_margins(pg)[3]
            if event.type == Gdk.EventType._3BUTTON_PRESS or (event.type == Gdk.EventType.BUTTON_PRESS and ctrl):
                self.ed.select_all()
            elif event.type == Gdk.EventType._2BUTTON_PRESS:
                self.ed.select_paragraph_at(pg, left + 2.0, y)
            elif shift:
                self.ed.click(pg, left + 2.0, y, True)
                self.ed.move_caret("end", True)
            else:
                self.ed.click(pg, left + 2.0, y, False)
                self.ed.move_caret("home", False)
                self.ed.move_caret("end", True)
            self.after_move()
            return True
        self.bar_select = False
        if event.type in (Gdk.EventType._2BUTTON_PRESS, Gdk.EventType._3BUTTON_PRESS):
            self._dnd = None
        if event.type == Gdk.EventType._2BUTTON_PRESS:
            self.ed.select_word_at(pg, x, y)
        elif event.type == Gdk.EventType._3BUTTON_PRESS:
            self.ed.select_paragraph_at(pg, x, y)
        elif event.type == Gdk.EventType.BUTTON_PRESS:
            link = self.ed.link_at(pg, x, y) if event.state & Gdk.ModifierType.CONTROL_MASK else None
            if link and not shift:
                # Ctrl+click follows a link
                if link.startswith("#"):
                    self.ed.goto_bookmark(link[1:])
                    self.after_move()
                else:
                    self.emit("hyperlink-clicked", link)
                return True
            if not shift and not (event.state & Gdk.ModifierType.CONTROL_MASK) and self.ed.has_selection() \
                    and self._in_selection(pg, x, y):
                # a press on the selection: dragging it moves it (Ctrl copies)
                self._dnd = (self.ed.selection_range(), event.x, event.y)
                return True
            if event.state & Gdk.ModifierType.CONTROL_MASK and not shift:
                # Ctrl+click selects the sentence
                self.ed.click(pg, x, y, False)
                from .units import select_unit
                select_unit(self.ed, "sentence")
            else:
                self.ed.click(pg, x, y, shift)
            self._dragging = True
        self.after_move()
        return True

    def _drag_out(self, event):
        """Dragging the selection out of the window: other programs get it
        (as text and formatted text); the document keeps it."""
        top = self.get_toplevel()
        gw = top.get_window() if top is not None else None
        if gw is None:
            return False
        ox, oy = gw.get_origin()[1:3]
        w, h = gw.get_width(), gw.get_height()
        if ox <= event.x_root < ox + w and oy <= event.y_root < oy + h:
            return False
        text = self.ed.selected_text()
        html = None
        try:
            from . import htmlexport
            frag = self.ed.copy_fragment()
            html = htmlexport.fragment_to_html(frag, self.ed.paragraph_styles()) if frag else None
        except Exception:
            html = None
        self._dnd = None
        self._out_data = (text, html)
        if not getattr(self, "_out_hooked", False):
            self.connect("drag-data-get", self._out_get)
            self._out_hooked = True
        tl = Gtk.TargetList.new([])
        if html:
            tl.add(Gdk.Atom.intern("text/html", False), 0, 2)
        tl.add_text_targets(1)
        self.drag_begin_with_coordinates(tl, Gdk.DragAction.COPY, 1, event, -1, -1)
        return True

    def _out_get(self, widget, ctx, data, info, time):
        text, html = getattr(self, "_out_data", ("", None))
        if info == 2 and html:
            data.set(Gdk.Atom.intern("text/html", False), 8, html.encode("utf-8"))
        else:
            data.set_text(text or "", -1)

    def _motion(self, widget, event):
        if self._dnd is not None and self.ed is not None and event.state & Gdk.ModifierType.BUTTON1_MASK:
            if self._drag_out(event):
                return True
        for t in self.tools:
            if t.active and t.motion(event):
                self.queue_draw()
                return True
        if self.objs.drag is not None or self.objs.active():
            if self.objs.motion(event):
                return True
            if self.objs._cursor is not None and self.objs.drag is None:
                return False
        if self._dragging and event.state & Gdk.ModifierType.BUTTON1_MASK and self.ed:
            hit = self.page_at(event.x, event.y)
            if hit:
                self.ed.click(hit[0], hit[1], hit[2], True)
                self.after_move()
        win = self.get_window()
        if win is not None and not getattr(self, "_ibeam", False):
            win.set_cursor(Gdk.Cursor.new_for_display(self.get_display(), Gdk.CursorType.XTERM))
            self._ibeam = True
        return False

    def _control_frame(self):
        ed = self.ed
        if ed is None:
            return {}
        key = (ed.version, ed.caret_pos())
        if getattr(self, "_cc_key", None) == key:
            return self._cc_frame
        frame = {}
        try:
            cid = ed.control_at_caret() if ed.content_controls() else None
            if cid is not None:
                r = ed.control_range(cid)
                if r and r[2] != 2 ** 64 - 1 and r[2] < 10 ** 9:
                    p, a, b = r
                    for (pg, x, y, w, h) in ed.range_rects(p, a, p, b) or ():
                        frame.setdefault(pg, []).append((x, y, max(w, 2.0), h))
        except Exception as e:
            print("control frame:", e)
        self._cc_key, self._cc_frame = key, frame
        return frame

    _dnd = None

    def _in_selection_bar(self, pg, x):
        try:
            left = self.ed.page_margins(pg)[3]
        except Exception:
            return False
        return 4.0 < x < left - 6.0

    def _in_selection(self, pg, x, y):
        for (p, rx, ry, rw, rh) in self.ed.selection_rects():
            if p == pg and rx <= x <= rx + rw and ry <= y <= ry + rh:
                return True
        return False

    def _para_order(self):
        ed = self.ed
        out = []
        for kind, node, ti in ed.body_blocks():
            if kind == "p":
                out.append(node)
            else:
                for row in ed.table_cells(ti):
                    for cell in row:
                        out.extend(cell)
        return {p: i for i, p in enumerate(out)}

    def _drop(self, event):
        """The end of a drag of the selection: the text moves (Ctrl: is copied) there."""
        (pa, a, pb, b), x0, y0 = self._dnd
        self._dnd = None
        ed = self.ed
        hit = self.page_at(event.x, event.y)
        if hit is None or (abs(event.x - x0) < 3 and abs(event.y - y0) < 3):
            # a plain click on the selection: the caret goes there
            if hit is not None:
                ed.click(hit[0], hit[1], hit[2], False)
            self.after_move()
            return True
        copy = bool(event.state & Gdk.ModifierType.CONTROL_MASK)
        frag = ed.copy_fragment()
        ed.click(hit[0], hit[1], hit[2], False)
        pd, od = ed.caret_pos()
        order = self._para_order()
        key = lambda p, o: (order.get(p, -1), o)  # noqa: E731
        if key(pa, a) <= key(pd, od) <= key(pb, b) or frag is None:
            self.after_move()
            return True
        after = key(pd, od) > key(pb, b)
        ed.begin_group("Copy" if copy else "Move")
        try:
            if after or copy:
                ed.select_nodes(pd, od, pd, od)
                ed.paste_fragment(frag, True)
                if not copy:
                    end = ed.caret_pos()
                    ed.select_nodes(pa, a, pb, b)
                    ed.delete(True, False)
                    # the caret after the moved text, as it was
                    if end[0] == pb and pa == pb:
                        ed.select_nodes(end[0], end[1] - (b - a), end[0], end[1] - (b - a))
            else:
                ed.select_nodes(pa, a, pb, b)
                ed.delete(True, False)
                ed.select_nodes(pd, od, pd, od)
                ed.paste_fragment(frag, True)
        finally:
            ed.end_group()
        self.after_edit()
        return True

    def _release(self, widget, event):
        self._dragging = False
        if self._dnd is not None and self.ed is not None:
            return self._drop(event)
        for t in self.tools:
            if t.active and t.release(event):
                self.queue_draw()
                return True
        if self.objs.drag is not None:
            self.objs.release()
            return True
        return False
