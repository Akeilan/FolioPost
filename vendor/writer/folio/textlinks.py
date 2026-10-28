"""Shape Format > Text: Text Direction, Align Text and Create Link /
Break Link, which makes text that overflows one text box carry on in
another, as in the original."""
from gi.repository import Gdk, GLib

from ._lazy import Lazy, bridge
drawing = Lazy("folio.drawing")

DIRECTIONS = [("Horizontal", 0), ("Rotate all text 90°", 2), ("Rotate all text 270°", 5)]
ALIGN = [("Top", "TOP"), ("Middle", "CENTER"), ("Bottom", "BOTTOM")]


def is_text_box(obj):
    try:
        return obj is not None and obj.supportsService("com.sun.star.text.TextFrame")
    except Exception:
        return False


def _empty(frame):
    try:
        return not frame.getText().getString().strip()
    except Exception:
        return False


def set_direction(obj, mode):
    if is_text_box(obj):
        obj.WritingMode = int(mode)
        return
    # drawing shapes: vertical text or rotated text
    try:
        obj.TextWritingMode = bridge.enum("com.sun.star.text.WritingMode",
                                          "TB_RL" if mode == 2 else "LR_TB")
    except Exception:
        pass
    try:
        geo = list(obj.CustomShapeGeometry)
        geo = [p for p in geo if p.Name != "TextRotateAngle"]
        if mode == 5:
            geo.append(bridge.struct("com.sun.star.beans.PropertyValue",
                                      Name="TextRotateAngle", Value=90.0))
        obj.CustomShapeGeometry = tuple(geo)
    except Exception:
        pass


def set_align(obj, where):
    obj.TextVerticalAdjust = bridge.enum("com.sun.star.drawing.TextVerticalAdjust", where)


class Linker:
    """Create Link: the next click on an empty text box links to it."""

    def __init__(self, win):
        self.win = win
        self.src = None

    @property
    def pending(self):
        return self.src is not None

    def _native(self):
        return getattr(self.win.engine, "native", False)

    def create(self):
        if self._native():
            ed = self.win.engine.ed
            o = ed.selected_object()
            if o is None or o["kind"] != "textbox":
                self.win.dialogs.message("Select a text box first.")
                return
            if ed.textbox_link_state() == "break":
                self.win.dialogs.message("This text box is already linked. Break the link first.")
                return
            self.src = ed.selected_objects()[0][0]
            self._cursor(True)
            self.win.status.flash("Click an empty text box to link to. Press Esc to cancel.")
            return
        m = self.win.engine.model
        obj = drawing.selected_shape(m) if m is not None else None
        if not is_text_box(obj):
            self.win.dialogs.message("Select a text box first.")
            return
        if getattr(obj, "ChainNextName", ""):
            self.win.dialogs.message("This text box is already linked. Break the link first.")
            return
        self.src = obj.Name
        self._cursor(True)
        self.win.status.flash("Click an empty text box to link to. Press Esc to cancel.")

    def cancel(self):
        if self.src is not None:
            self.src = None
            self._cursor(False)
            self.win.status.flash("")

    def _cursor(self, on):
        gw = self.win.engine.view.get_window()
        if gw is None:
            return
        cur = Gdk.Cursor.new_from_name(gw.get_display(), "copy") if on else None
        gw.set_cursor(cur)

    def press(self, event):
        """A click while linking: let the click select, then link."""
        if self.src is None:
            return False
        if event.button != 1:
            self.cancel()
            return False
        src = self.src
        self.src = None
        self._cursor(False)
        GLib.timeout_add(250, lambda: (self._finish(src), False)[1])
        return False

    def _finish(self, src_name):
        if self._native():
            ed = self.win.engine.ed
            o = ed.selected_object()
            if o is None or o["kind"] != "textbox":
                if ed.story() == "textbox":
                    ed.leave_textbox()
                    o = ed.selected_object()
            if o is None or o["kind"] != "textbox":
                self.win.status.flash("")
                return
            msg = ed.link_textboxes(src_name)
            self.win.engine.view.after_edit()
            if msg:
                self.win.dialogs.message(msg)
            else:
                self.win.status.flash("Text boxes linked.")
            self.win.update_object_tabs()
            return
        m = self.win.engine.model
        dst = drawing.selected_shape(m) if m is not None else None
        if not is_text_box(dst):
            self.win.status.flash("")
            return
        frames = m.getTextFrames()
        if not frames.hasByName(src_name):
            return
        src = frames.getByName(src_name)
        if dst.Name == src_name:
            return
        if not _empty(dst):
            self.win.dialogs.message("The text box you want to link to must be empty.")
            return
        if getattr(dst, "ChainPrevName", ""):
            self.win.dialogs.message("That text box is already linked from another one.")
            return
        # no loops
        name = dst.Name
        seen = set()
        while name and name not in seen:
            seen.add(name)
            if name == src_name:
                self.win.dialogs.message("Those text boxes can't be linked in a circle.")
                return
            f = frames.getByName(name) if frames.hasByName(name) else None
            name = getattr(f, "ChainNextName", "") if f is not None else ""
        um = m.getUndoManager()
        um.enterUndoContext("Create Text Box Link")
        try:
            src.ChainNextName = dst.Name
        except Exception as e:
            print("link:", e)
        finally:
            um.leaveUndoContext()
        if src.ChainNextName != dst.Name:
            self.win.dialogs.message("Those text boxes can't be linked.")
            return
        self.win.status.flash("Text boxes linked.")
        self.win.update_object_tabs()

    def break_link(self):
        if self._native():
            ed = self.win.engine.ed
            if ed.unlink_textbox():
                self.win.engine.view.after_edit()
                self.win.status.flash("Link broken.")
                self.win.update_object_tabs()
            return
        m = self.win.engine.model
        obj = drawing.selected_shape(m) if m is not None else None
        if not is_text_box(obj) or not getattr(obj, "ChainNextName", ""):
            return
        um = m.getUndoManager()
        um.enterUndoContext("Break Text Box Link")
        try:
            obj.ChainNextName = ""
        finally:
            um.leaveUndoContext()
        self.win.status.flash("Link broken.")
        self.win.update_object_tabs()

    def state(self):
        """'link' / 'break' / None for the ribbon button."""
        if self._native():
            ed = self.win.engine.ed
            return (ed.textbox_link_state() or None) if ed is not None else None
        m = self.win.engine.model
        obj = drawing.selected_shape(m) if m is not None else None
        if not is_text_box(obj):
            return None
        return "break" if getattr(obj, "ChainNextName", "") else "link"
