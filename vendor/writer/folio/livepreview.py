"""Live Preview, as in the original: resting the pointer on a style, font,
size, colour, table style or picture style shows it in the document; moving
away puts things back. Nothing is changed until you click.

A preview is applied as one undo step and taken back with undo, so it never
reaches the undo list, and the document's "changed" flag is restored."""
from gi.repository import GLib

from . import docapi

TITLE = "Live Preview"
DELAY = 280          # ms of hovering before the preview shows (as the original)


class LivePreview:
    def __init__(self, win):
        self.win = win
        self.key = None
        self.active = False
        self._was_modified = False
        self._timer = 0
        self._end_timer = 0

    def enabled(self):
        return self.win.app.settings.get("live_preview", True)

    # ------------------------------------------------------------ hover API
    def hover(self, key, apply_fn):
        """The pointer rests on something previewable."""
        if not self.enabled():
            return
        if self._end_timer:
            GLib.source_remove(self._end_timer)
            self._end_timer = 0
        if key == self.key and self.active:
            return
        if self._timer:
            GLib.source_remove(self._timer)
        self._timer = GLib.timeout_add(DELAY, self._start, key, apply_fn)

    def unhover(self):
        """The pointer left: put the document back (a moment later, so moving
        from one item to the next doesn't flicker)."""
        if self._timer:
            GLib.source_remove(self._timer)
            self._timer = 0
        if self.active and not self._end_timer:
            self._end_timer = GLib.timeout_add(120, self._end_later)

    def commit(self):
        """A click: take the preview back first; the real command follows."""
        if self._timer:
            GLib.source_remove(self._timer)
            self._timer = 0
        self.end()

    # ------------------------------------------------------------ internals
    def _end_later(self):
        self._end_timer = 0
        self.end()
        return False

    def _start(self, key, apply_fn):
        self._timer = 0
        self.end()
        if getattr(self.win.engine, "native", False):
            return self._start_native(key, apply_fn)
        m = self.win.engine.model
        if m is None or self.win.read_only:
            return False
        try:
            self._was_modified = m.isModified()
            um = m.getUndoManager()
            um.enterUndoContext(TITLE)
            try:
                apply_fn(m)
            finally:
                um.leaveUndoContext()
            self.active = True
            self.key = key
        except Exception as e:
            print("live preview:", e)
            self._take_back(m)
        return False

    def _take_back(self, m):
        try:
            um = m.getUndoManager()
            titles = um.getAllUndoActionTitles()
            if titles and titles[0] == TITLE:
                um.undo()
                try:
                    um.clearRedo()
                except Exception:
                    pass
            if not self._was_modified and m.isModified():
                m.setModified(False)
        except Exception as e:
            print("live preview undo:", e)

    def _start_native(self, key, apply_fn):
        ed = self.win.engine.ed
        fn = getattr(apply_fn, "native", None)
        if ed is None or fn is None or self.win.read_only:
            return False
        self._was_modified = ed.modified
        ed.begin_group(TITLE)
        try:
            fn(self.win)
        except Exception as e:
            print("live preview:", e)
        finally:
            ed.end_group()
        self.active = True
        self.key = key
        self.win.engine.view.document_changed()
        return False

    def _take_back_native(self):
        ed = self.win.engine.ed
        if ed is None:
            return
        try:
            names = ed.undo_names()
            if names and names[-1] == TITLE or names and names[0] == TITLE:
                sel = ed.selection_range()
                ed.undo()
                ed.select_nodes(*sel)
            if not self._was_modified and ed.modified:
                ed.mark_saved()
        except Exception as e:
            print("live preview undo:", e)
        self.win.engine.view.document_changed()

    def end(self):
        if not self.active:
            return
        self.active = False
        self.key = None
        if getattr(self.win.engine, "native", False):
            self._take_back_native()
            return
        m = self.win.engine.model
        if m is not None:
            self._take_back(m)


# ---------------------------------------------------------------- helpers
def attach(win, widget, key, apply_fn):
    """Preview apply_fn(model) while the pointer rests on widget."""
    lp = win.live_preview
    widget.connect("enter-notify-event", lambda *_: (lp.hover(key, apply_fn), False)[1])
    widget.connect("leave-notify-event", lambda *_: (lp.unhover(), False)[1])
    # clicking: drop the preview before the real command runs
    widget.connect("button-press-event", lambda *_: (lp.commit(), False)[1])


def _targets(m):
    """Text ranges the preview applies to: the selection, or the word at the
    cursor for character formatting."""
    vc = docapi.view_cursor(m)
    return vc


def para_style(name):
    from .actions import engine_style, CHAR_STYLES

    def apply(m):
        vc = docapi.view_cursor(m)
        if name in CHAR_STYLES:
            rng = _word_or_selection(vc)
            rng.CharStyleName = engine_style(name)
        else:
            vc.ParaStyleName = engine_style(name)

    def native(win):
        if name in CHAR_STYLES:
            _native_word(win, lambda: win.actions.apply_style(name))
        else:
            win.actions.apply_style(name)
    apply.native = native
    return apply


def _native_word(win, fn):
    """Run fn on the selection, or on the word at the caret (caret kept)."""
    ed = win.engine.ed
    if ed.has_selection():
        fn()
        return
    from .native.units import word_bounds
    p, off = ed.caret_pos()
    t = ed.para_text_of(p)
    a, b = word_bounds(t, off)
    while b > a and t[b - 1] == " ":
        b -= 1
    if b <= a:
        return
    ed.select_nodes(p, a, p, b)
    try:
        fn()
    finally:
        ed.select_nodes(p, off, p, off)


def _hex(c):
    return "%06X" % (int(c) & 0xFFFFFF)


def _native_run_edits(props):
    out = []
    for k, v in props.items():
        if k == "CharColor":
            out.append(("w:color", [("w:val", "auto" if v is None or v < 0 else _hex(v))]))
        elif k == "CharBackColor":
            out.append(("w:shd", None if v is None or v < 0 else
                        [("w:val", "clear"), ("w:color", "auto"), ("w:fill", _hex(v))]))
        elif k == "CharHeight":
            out.append(("w:sz", [("w:val", str(int(round(float(v) * 2))))]))
            out.append(("w:szCs", [("w:val", str(int(round(float(v) * 2))))]))
        elif k == "CharFontName":
            out.append(("w:rFonts", [("w:ascii", v), ("w:hAnsi", v), ("w:cs", v), ("w:eastAsia", v)]))
    return out


def _word_or_selection(vc):
    if not vc.isCollapsed():
        return vc
    c = vc.getText().createTextCursorByRange(vc.getStart())
    c.gotoStartOfWord(False)
    c.gotoEndOfWord(True)
    return c


def char_prop(**props):
    def apply(m):
        rng = _word_or_selection(docapi.view_cursor(m))
        for k, v in props.items():
            rng.setPropertyValue(k, v)

    def native(win):
        edits = _native_run_edits(props)
        if edits:
            _native_word(win, lambda: win.engine.ed.apply_run(edits, TITLE))
    apply.native = native
    return apply
