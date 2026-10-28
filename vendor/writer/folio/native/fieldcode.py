"""Ctrl+F9 as in the original: field braces at the cursor, the field code
typed between them, then F9 (or Enter, or moving away) makes the field.
Esc takes the braces away again."""
from gi.repository import Gdk


class FieldCodeEntry:
    def __init__(self, win):
        self.win = win
        self.view = win.engine.view
        self.active = False
        self.code = ""
        self.version = None
        self.pos = None
        self.view.connect_after("draw", self._draw)
        self.view.field_code = self

    @property
    def ed(self):
        return self.win.engine.ed

    def start(self):
        ed = self.ed
        if ed is None:
            return
        if ed.has_selection():
            # Word puts the selected text inside the braces
            self.code = " ".join(ed.selected_text().split())
            ed.delete(True, False)
            self.view.after_edit()
        else:
            self.code = ""
        self.active = True
        self.pos = ed.caret_pos()
        self.version = self._snapshot()
        self.win.status.flash("Type the field code, then press F9. Esc cancels.")
        self.view.queue_draw()

    def _snapshot(self):
        ed = self.ed
        try:
            return (tuple(ed.body_blocks()), ed.para_text_of(ed.caret_pos()[0]), len(ed.undo_names()))
        except Exception:
            return None

    def cancel(self):
        self.active = False
        self.code = ""
        self.view.queue_draw()

    def commit(self):
        code = self.code.strip()
        self.cancel()
        ed = self.ed
        if not code or ed is None:
            return
        ed.select_nodes(self.pos[0], self.pos[1], self.pos[0], self.pos[1])
        try:
            ed.insert_field_now(code + (" \\* MERGEFORMAT" if "\\*" not in code and code.split()[0].upper()
                                        in ("PAGE", "NUMPAGES", "DATE", "TIME", "AUTHOR", "TITLE", "FILENAME")
                                        else ""))
        except Exception as e:
            print("field code:", e)
            return
        self.view.after_edit()

    def key(self, event):
        """Keys while the braces are open; False lets the key through."""
        if not self.active:
            return False
        ed = self.ed
        if ed is None or self._snapshot() != self.version or tuple(ed.caret_pos()) != tuple(self.pos):
            # the document moved on without us
            self.cancel()
            return False
        k = event.keyval
        if event.is_modifier or k in (Gdk.KEY_Shift_L, Gdk.KEY_Shift_R, Gdk.KEY_Control_L, Gdk.KEY_Control_R,
                                      Gdk.KEY_Alt_L, Gdk.KEY_Alt_R, Gdk.KEY_Caps_Lock, Gdk.KEY_ISO_Level3_Shift):
            return False
        ctrl = bool(event.state & Gdk.ModifierType.CONTROL_MASK)
        if k == Gdk.KEY_Escape:
            self.cancel()
            return True
        if k in (Gdk.KEY_F9, Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            self.commit()
            return True
        if k == Gdk.KEY_BackSpace:
            self.code = self.code[:-1]
            self.view.queue_draw()
            return True
        if ctrl and k == Gdk.KEY_F9:
            return True
        ch = Gdk.keyval_to_unicode(k)
        if ch and not ctrl and (ch >= 32):
            self.code += chr(ch)
            self.view.queue_draw()
            return True
        # anything else (arrows, clicks): the field is made, the key goes on
        self.commit()
        return False

    def _draw(self, view, cr):
        if not self.active or self.ed is None:
            return False
        r = self.ed.caret_rect()
        if r is None:
            return False
        pg, x, y, h = r
        try:
            ox, oy = view._origins[pg]
        except Exception:
            return False
        s = view.ppp
        px, py = ox + x * s, oy + y * s
        text = "{ %s }" % self.code
        cr.save()
        cr.select_font_face("Sans")
        cr.set_font_size(max(9.0, h * s * 0.72))
        ext = cr.text_extents(text)
        cr.set_source_rgba(0.85, 0.85, 0.85, 0.9)
        cr.rectangle(px - 1, py, ext.x_advance + 2, h * s)
        cr.fill()
        cr.set_source_rgb(0.1, 0.1, 0.1)
        cr.move_to(px, py + h * s * 0.78)
        cr.show_text(text)
        cr.restore()
        return False
