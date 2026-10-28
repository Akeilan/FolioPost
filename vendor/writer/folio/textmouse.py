"""Mouse gestures on document text that the engine's tiled view doesn't do
on its own, as in the original:

- triple-click selects the paragraph;
- Ctrl+click selects the sentence (links still follow with Ctrl+click);
- dragging selected text moves it (Ctrl+drag copies it).
"""
from gi.repository import Gdk, GLib, Gtk

from . import docapi

DRAG_THRESHOLD = 5


def _model(win):
    return win.engine.model


def select_paragraph(win):
    m = _model(win)
    if m is None:
        return False
    try:
        vc = docapi.view_cursor(m)
        c = vc.getText().createTextCursorByRange(vc.getStart())
        c.gotoStartOfParagraph(False)
        c.gotoEndOfParagraph(True)
        # the paragraph mark comes with it, unless it's the last paragraph
        if not c.gotoNextParagraph(True):
            pass
        docapi.controller(m).select(c)
    except Exception as e:
        print("select paragraph:", e)
    return False


def select_sentence(win):
    m = _model(win)
    if m is None:
        return False
    try:
        vc = docapi.view_cursor(m)
        if getattr(vc, "HyperLinkURL", ""):
            return False
        c = vc.getText().createTextCursorByRange(vc.getStart())
        c.gotoStartOfSentence(False)
        c.gotoEndOfSentence(True)
        # with the space after it, as in the original
        end = c.getText().createTextCursorByRange(c.getEnd())
        while end.goRight(1, True) and end.getString().endswith(" "):
            c.gotoRange(end.getEnd(), True)
            end.collapseToEnd()
        docapi.controller(m).select(c)
    except Exception as e:
        print("select sentence:", e)
    return False


def _later(win, fn, ms=60):
    win.engine.sync(lambda: GLib.timeout_add(ms, fn, win))


def _is_selected_pixel(px):
    r, g, b = px[:3]
    return 170 <= r <= 225 and 205 <= g <= 245 and b >= 235 and b - r >= 25


def point_in_selection(view, x, y):
    """Is (x, y) on the selection highlight? (sampled from the screen)"""
    gw = view.get_window()
    if gw is None:
        return False
    x0, y0 = int(x) - 3, int(y) - 3
    try:
        pb = Gdk.pixbuf_get_from_window(gw, max(0, x0), max(0, y0), 7, 7)
    except Exception:
        return False
    if pb is None:
        return False
    data = pb.get_pixels()
    n, stride = pb.get_n_channels(), pb.get_rowstride()
    hits = 0
    for j in range(pb.get_height()):
        for i in range(pb.get_width()):
            o = j * stride + i * n
            if _is_selected_pixel(data[o:o + 3]):
                hits += 1
    return hits >= 4


class DragMove:
    """Drag-and-drop text editing."""

    def __init__(self, win):
        self.win = win
        self.state = None        # None / "pressed" / "dragging"
        self.start = (0, 0)
        self.src = None
        self.data = None
        view = win.engine.view
        view.connect("motion-notify-event", self.motion)
        view.connect("button-release-event", self.release)
        view.connect("drag-data-get", self._out_get)
        self.out = None          # (html, text) offered to other programs

    def press(self, event):
        win = self.win
        m = _model(win)
        if m is None or event.button != 1 or event.type != Gdk.EventType.BUTTON_PRESS:
            return False
        if event.state & (Gdk.ModifierType.SHIFT_MASK | Gdk.ModifierType.MOD1_MASK):
            return False
        if win.engine.selection_type() != 1:      # a text selection
            return False
        if not point_in_selection(win.engine.view, event.x, event.y):
            return False
        try:
            ctl = docapi.controller(m)
            sel = ctl.getSelection()
            if sel.getCount() != 1:
                return False
            r = sel.getByIndex(0)
            if not r.getString():
                return False
            self.src = r.getText().createTextCursorByRange(r)
            self.data = ctl.getTransferable()
            try:
                html, _ = win.engine.view.copy_selection("text/html")
            except Exception:
                html = None
            self.out = (html, r.getString())
        except Exception as e:
            print("drag:", e)
            return False
        self.state = "pressed"
        self.start = (event.x, event.y)
        return True

    def motion(self, view, event):
        if self.state is None:
            return False
        if self.state == "pressed":
            dx, dy = event.x - self.start[0], event.y - self.start[1]
            if dx * dx + dy * dy >= DRAG_THRESHOLD * DRAG_THRESHOLD:
                self.state = "dragging"
        if self.state == "dragging":
            a = view.get_allocation()
            if not (0 <= event.x < a.width and 0 <= event.y < a.height):
                # left the page: hand the text to whatever it's dropped on
                self.state = None
                gw = view.get_window()
                if gw is not None:
                    gw.set_cursor(None)
                tl = Gtk.TargetList.new([Gtk.TargetEntry.new("text/html", 0, 0),
                                         Gtk.TargetEntry.new("UTF8_STRING", 0, 1),
                                         Gtk.TargetEntry.new("text/plain;charset=utf-8", 0, 1),
                                         Gtk.TargetEntry.new("text/plain", 0, 1)])
                view.drag_begin_with_coordinates(tl, Gdk.DragAction.COPY, 1, event,
                                                 int(event.x), int(event.y))
                return True
            copy = bool(event.state & Gdk.ModifierType.CONTROL_MASK)
            gw = view.get_window()
            if gw is not None:
                gw.set_cursor(Gdk.Cursor.new_from_name(view.get_display(),
                                                       "copy" if copy else "move"))
        return True

    def _out_get(self, view, ctx, data, info, time):
        if not self.out:
            return
        html, text = self.out
        if info == 0 and html:
            data.set(Gdk.Atom.intern("text/html", False), 8, html.encode("utf-8"))
        else:
            data.set_text(text or "", -1)

    def release(self, view, event):
        if self.state is None or event.button != 1:
            return False
        state, self.state = self.state, None
        gw = view.get_window()
        if gw is not None:
            gw.set_cursor(None)
        tx, ty = self.win.engine.px_to_twips(event.x, event.y)
        if state == "pressed":
            # a plain click inside the selection: put the cursor there
            self.win.engine.click_at(tx, ty)
            return True
        copy = bool(event.state & Gdk.ModifierType.CONTROL_MASK)
        self.win.engine.click_at(tx, ty)
        _later(self.win, lambda w: self._drop(copy), 80)
        return True

    def _drop(self, copy):
        m = _model(self.win)
        src, data = self.src, self.data
        self.src = self.data = None
        if m is None or src is None or data is None:
            return False
        try:
            vc = docapi.view_cursor(m)
            dest = vc.getStart()
            text = src.getText()
            inside = False
            try:
                if dest.getText() == text:
                    inside = text.compareRegionStarts(src, dest) >= 0 and \
                        text.compareRegionEnds(src, dest) <= 0
            except Exception:
                pass
            if inside:
                docapi.controller(m).select(src)
                return False
            mark = dest.getText().createTextCursorByRange(dest)
            um = m.getUndoManager()
            um.enterUndoContext("Copy" if copy else "Move")
            try:
                if not copy:
                    src.setString("")
                ctl = docapi.controller(m)
                ctl.select(mark)
                ctl.insertTransferable(data)
            finally:
                um.leaveUndoContext()
        except Exception as e:
            print("drop:", e)
        return False


def press(win, event):
    """Called from the view's button press; True when handled here."""
    if event.button != 1:
        return False
    if event.type == Gdk.EventType._3BUTTON_PRESS:
        _later(win, select_paragraph, 30)
        return True
    if event.type == Gdk.EventType.BUTTON_PRESS and \
            event.state & Gdk.ModifierType.CONTROL_MASK and \
            not event.state & (Gdk.ModifierType.SHIFT_MASK | Gdk.ModifierType.MOD1_MASK):
        # the click places the cursor; then the sentence around it is selected
        _later(win, select_sentence, 120)
        return False
    return win.drag_move.press(event)
