"""In-place equation editing, as in the original: the equation is edited
right where it sits on the page, in built-up (Professional) form or as one
line of linear text (Linear), inside a light grey frame with a drop-down tab.

The engine keeps the real formula object; while you edit, this module draws
the equation over it (with its own layout, eqn.render) and writes the
formula markup back after every change, so the page reflows as you type.
"""
import copy
import os
import unicodedata

from gi.repository import Gdk, GLib, Gtk

from . import docapi
from .eqn import latex, model as M, render as R, unicodemath as U
from .eqn import symbols as S
from .eqn.unicodemath import Atom, Seq

LINEAR_MARK = "%% folio:linear"
OP_CHARS = set(S.OPERATORS) | set("←↔↦⟶⟵,;:!") | S.RELATIONS
BUILD_TRIGGERS = set(" ") | OP_CHARS | set(")]}⟩|")
FRAME = (0.62, 0.62, 0.62)
FRAME_BG = (0.95, 0.95, 0.95)
TAB_W = 14


def _kind(ch):
    if ch.isdigit() or ch == ".":
        return "num"
    if ch in OP_CHARS:
        return "op"
    if ch.isalpha():
        return "ident"
    if ch == " ":
        return "space"
    return "sym"


def is_linear_markup(markup):
    return (markup or "").rstrip().endswith(LINEAR_MARK)


def linear_markup(text):
    t = text.replace("\\", "\\\\").replace('"', '\\"')
    return 'nitalic "%s" %s' % (t, LINEAR_MARK)


def linear_of_markup(markup):
    m = (markup or "").rstrip()[:-len(LINEAR_MARK)].strip()
    if m.startswith("nitalic"):
        m = m[len("nitalic"):].strip()
    if m.startswith('"') and m.endswith('"'):
        m = m[1:-1]
    return m.replace('\\"', '"').replace("\\\\", "\\")


def _dbg(*a):
    if os.environ.get("FOLIO_EQ_DEBUG"):
        print("EQ", *a, flush=True)


def _complete(text):
    """Build up only when the linear text is finished: brackets balanced and
    no operator still waiting for its operand."""
    depth = 0
    for ch in text:
        if ch in S.OPEN_BRACKETS and ch not in "├":
            depth += 1
        elif ch in S.CLOSE_BRACKETS and ch not in "┤":
            depth -= 1
    if depth > 0:
        return False
    t = text.rstrip()
    return bool(t) and t[-1] not in S.STRUCTURE and t[-1] not in S.NARY and \
        t[-1] not in "√∛∜"


class InlineEditor:
    def __init__(self, win, bar):
        self.win = win
        self.bar = bar
        self.obj = None
        self.root = Seq([])
        self.caret = (self.root, 0)
        self.anchor = None          # selection anchor index in caret seq
        self.picked = None          # a structure selected as a whole
        self.mode = "professional"
        self.lin = ""
        self.lin_pos = 0
        self.lin_anchor = None
        self.box = None
        self.frame = None           # (x, y, w, h) in view pixels
        self._display_cached = True
        self.obj_rect = None        # twips (x, y, w, h) of the object
        self.blink_on = True
        self._blink = 0
        self._push = 0
        self._last_markup = None
        self.undo_stack = []
        self.redo_stack = []
        self.drag = False
        self._pending_click = None
        view = win.engine.view
        view.connect_after("draw", self._draw)
        view.connect("motion-notify-event", self._motion)
        view.connect("button-release-event", self._release)

    # ------------------------------------------------------------ settings
    def opts(self):
        o = self.win.app.settings.get("eq_options")
        return o if isinstance(o, dict) else {}

    @property
    def active(self):
        return self.obj is not None

    # ------------------------------------------------------------ start / stop
    def start(self, obj, click=None, at=None):
        if self.obj is not None:
            if self._same(obj, self.obj):
                if click:
                    self.click(*click)
                return
            self.stop()
        m = self.win.engine.model
        markup = docapi.formula_of(obj) or ""
        self.obj = obj
        self.undo_stack, self.redo_stack = [], []
        self.picked = None
        self.anchor = None
        R.set_family(self.opts().get("font", "Caladea"))
        if is_linear_markup(markup):
            self.mode = "linear"
            self.lin = linear_of_markup(markup)
            self.lin_pos = len(self.lin)
            self.lin_anchor = None
            self.root = Seq([])
        else:
            self.mode = "professional"
            try:
                self.root = M.from_starmath(markup) if markup.strip() not in (
                    "", '"Type equation here."', "<?>") else Seq([])
            except Exception:
                self.root = Seq([])
            self.caret = (self.root, len(self.root.items))
            empty = M.first_empty(self.root)
            if at == "start":
                self.caret = (self.root, 0)
            elif empty is not None and at is None:
                self.caret = (empty, 0)
        if at == "start" and self.mode == "linear":
            self.lin_pos = 0
        self._last_markup = markup
        try:
            from . import grammar
            grammar.refresh_gaps(m)
        except Exception:
            pass
        self._ensure_fonts()
        self._number_load()
        # park the engine's own cursor after the equation; its position
        # tells us where the equation is on the page
        try:
            vc = docapi.view_cursor(m)
            vc.gotoRange(obj.getAnchor().getStart(), False)
            vc.goRight(1, False)
        except Exception:
            pass
        self.frame = None
        self._pending_click = click
        GLib.timeout_add(60, self._locate)
        self._start_blink()
        self.win.ribbon.show_contextual("Equation", True)
        tab = self.win.ribbon.tab_by_name("Equation")
        if tab is not None:
            self.win.ribbon.select(tab)
        self.bar.sync_input_buttons()
        self.win.focus_document()
        if not self.root.items and self.mode == "professional":
            self._push_now()

    @staticmethod
    def _same(a, b):
        try:
            return a.getName() == b.getName()
        except Exception:
            return a == b

    def stop(self, move_cursor=True):
        if self.obj is None:
            return
        obj = self.obj
        if self.mode == "professional" and self.opts().get("autobuild", True):
            # Enter / leaving the equation builds up what is still linear
            try:
                self.build_up()
                k = next((i for i, it in enumerate(self.root.items)
                          if isinstance(it, Atom) and it.value == "#"), len(self.root.items))
                self.caret = (self.root, k)
                self.build_up()
            except Exception as e:
                print("build-up:", e)
        _dbg("stop: number")
        self._number_save(obj)
        _dbg("stop: push")
        self._push_now(final=True)
        _dbg("stop: pushed")
        try:
            from . import grammar
            grammar.refresh_gaps(self.win.engine.model)
        except Exception:
            pass
        empty = (self.mode == "professional" and not self.root.items) or \
            (self.mode == "linear" and not self.lin.strip())
        self.obj = None
        self.frame = None
        if self._blink:
            GLib.source_remove(self._blink)
            self._blink = 0
        self.win.ribbon.show_contextual("Equation", False)
        m = self.win.engine.model
        if m is not None:
            try:
                anchor = obj.getAnchor()
                if empty:
                    anchor.getText().removeTextContent(obj)
                elif move_cursor:
                    vc = docapi.view_cursor(m)
                    vc.gotoRange(anchor.getStart(), False)
                    vc.goRight(1, False)
            except Exception:
                pass
        self.win.engine.view.queue_draw()

    # ------------------------------------------------------------ geometry
    def _locate(self):
        if self.obj is None:
            return False
        eng = self.win.engine
        r = getattr(self.win, "_follow_rect", None)
        try:
            size = self.obj.Size
            ow = size.Width * 1440 / 2540.0
            oh = size.Height * 1440 / 2540.0
        except Exception:
            return False
        if r is None:
            return False
        cx, cy, _cw, ch = r
        self.obj_rect = (cx - ow, cy + max(0, ch - oh), ow, oh)
        if self._pending_click is not None:
            x, y = self._pending_click
            self._pending_click = None
            self._layout()
            self.click(x, y)
        self._layout()
        eng.view.queue_draw()
        return False

    def cursor_moved(self):
        """The engine's cursor moved (after a reflow): follow the object."""
        if self.obj is not None:
            GLib.idle_add(self._locate)

    def _base_px(self):
        try:
            pt = float(self.obj.getEmbeddedObject().BaseFontHeight or 11)
        except Exception:
            pt = 11.0
        z = self.win.engine.view.get_zoom() or 1.0
        return pt * 96.0 / 72.0 * z

    def _display(self):
        try:
            if self.obj.getAnchor().ParaAdjust in (3, 2) or self._alone():
                return True
            from . import eqnumber
            return eqnumber.current(self.obj) is not None
        except Exception:
            return True

    def _alone(self):
        try:
            anchor = self.obj.getAnchor()
            cur = anchor.getText().createTextCursorByRange(anchor)
            cur.gotoStartOfParagraph(False)
            cur.gotoEndOfParagraph(True)
            return cur.getString().strip() in ("", "￼")
        except Exception:
            return False

    def _layout(self):
        if self.obj is None or self.obj_rect is None:
            return
        size = self._base_px()
        if self.mode == "linear":
            self.box = self._linear_box(size)
        else:
            self.box = R.layout(self.root, size, display=self._display(),
                                small_fractions=self.opts().get("small_fractions", True))
        eng = self.win.engine
        ox, oy, ow, oh = self.obj_rect
        x0, y0 = eng.twips_to_px(ox, oy)
        x1, y1 = eng.twips_to_px(ox + ow, oy + oh)
        self._display_cached = self._display()
        b = self.box
        pad = 2
        w = max(b.w + 2 * pad, x1 - x0)
        h = max(b.h + 2 * pad, y1 - y0)
        cx = (x0 + x1) / 2
        if self._display():
            fx = cx - w / 2
        else:
            fx = x0
        # put our baseline where the page's equation has its baseline (which
        # the engine lines up with the text): the same share of the height
        oh_px = max(1.0, y1 - y0)
        base = y0 + oh_px * (b.asc / max(1.0, b.h))
        fy = min(y0, base - b.asc - pad)
        h = max(y1, base + b.desc + pad) - fy
        self.frame = (fx, fy, w, h)
        b.place(fx + (w - b.w) / 2 if self._display_cached else fx + pad, base)

    def _linear_box(self, size):
        b = R.text_box(self.lin or " ", size)
        b.seq = None
        lay = R._layout(self.lin, size)[0] if self.lin else None
        xs = [0.0]
        if lay is not None:
            raw = self.lin.encode("utf-8")
            for i in range(1, len(self.lin) + 1):
                idx = len(self.lin[:i].encode("utf-8"))
                pos = lay.index_to_pos(min(idx, len(raw)))
                xs.append(pos.x / 1024.0)
        b.xs = xs
        b.size = size
        if not self.lin:
            b.w = 0.6 * size
        return b

    # ------------------------------------------------------------ drawing
    def _draw(self, view, cr):
        if self.obj is None or self.frame is None or self.box is None:
            return False
        fx, fy, w, h = self.frame
        cr.save()
        # cover the engine's own rendering and its cursor
        cr.set_source_rgb(1, 1, 1)
        disp = self._display_cached
        if disp:
            cr.rectangle(fx - 3, fy - 3, w + 6 + TAB_W, h + 6)
        else:
            # inline: keep the following text visible; the tab hangs below
            cr.rectangle(fx - 2, fy - 2, w + 4, h + 4)
        cr.fill()
        cr.set_source_rgb(*FRAME_BG)
        cr.rectangle(fx, fy, w, h)
        cr.fill()
        cr.set_source_rgb(*FRAME)
        cr.set_line_width(1)
        cr.rectangle(int(fx) + 0.5, int(fy) + 0.5, int(w), int(h))
        cr.stroke()
        # the drop-down tab: on the right of display equations, under the
        # right end of inline ones
        tx, ty, th = self._tab_rect()
        cr.set_source_rgb(0.86, 0.86, 0.86)
        cr.rectangle(tx, ty, TAB_W, th)
        cr.fill_preserve()
        cr.set_source_rgb(*FRAME)
        cr.stroke()
        cr.set_source_rgb(0.3, 0.3, 0.3)
        my = ty + th - 9 if disp else ty + 3
        cr.move_to(tx + 3.5, my)
        cr.line_to(tx + TAB_W - 3.5, my)
        cr.line_to(tx + TAB_W / 2, my + 4)
        cr.close_path()
        cr.fill()
        # selection
        self._draw_selection(cr)
        cr.set_source_rgb(0, 0, 0)
        if self.mode == "linear":
            self.box.place(self.box.ax, self.box.ay)
        self.box.draw(cr)
        if self.blink_on:
            c = self._caret_rect()
            if c is not None:
                x, y0, y1 = c
                cr.set_source_rgb(0, 0, 0)
                cr.set_line_width(max(1.0, self.box.size / 16 if self.box.size else 1))
                cr.move_to(int(x) + 0.5, y0)
                cr.line_to(int(x) + 0.5, y1)
                cr.stroke()
        cr.restore()
        return False

    def _slot_box(self, seq):
        if self.box is None:
            return None
        for b in getattr(self.box, "slots", []):
            if b.seq is seq:
                return b
        return None

    def _caret_rect(self):
        if self.mode == "linear":
            b = self.box
            x = b.ax + b.xs[min(self.lin_pos, len(b.xs) - 1)]
            return x, b.ay - 0.8 * b.size, b.ay + 0.25 * b.size
        if self.picked is not None:
            return None
        seq, i = self.caret
        b = self._slot_box(seq)
        if b is None:
            return None
        if getattr(b, "empty", False):
            x = b.ax + b.w * 0.5
            return x, b.ay - b.asc * 0.8, b.ay + b.desc
        x = b.ax + b.xs[min(i, len(b.xs) - 1)]
        return x, b.ay - max(b.asc, 0.8 * b.size), b.ay + max(b.desc, 0.22 * b.size)

    def _draw_selection(self, cr):
        cr.set_source_rgba(0.6, 0.75, 0.95, 0.6)
        if self.mode == "linear":
            if self.lin_anchor is not None and self.lin_anchor != self.lin_pos:
                b = self.box
                a, z = sorted((self.lin_anchor, self.lin_pos))
                cr.rectangle(b.ax + b.xs[a], b.ay - b.asc, b.xs[z] - b.xs[a], b.h)
                cr.fill()
            return
        if self.picked is not None:
            for bb in self.box.walk():
                if bb.node is self.picked:
                    cr.rectangle(bb.ax, bb.ay - bb.asc, bb.w, bb.h)
                    cr.fill()
                    return
            return
        seq, i = self.caret
        if self.anchor is None or self.anchor == i:
            return
        b = self._slot_box(seq)
        if b is None:
            return
        a, z = sorted((self.anchor, i))
        cr.rectangle(b.ax + b.xs[a], b.ay - b.asc, b.xs[z] - b.xs[a], b.h)
        cr.fill()

    def _start_blink(self):
        if self._blink:
            GLib.source_remove(self._blink)
        self.blink_on = True

        def tick():
            if self.obj is None:
                self._blink = 0
                return False
            self.blink_on = not self.blink_on
            self._redraw()
            return True
        self._blink = GLib.timeout_add(530, tick)

    def _redraw(self):
        if self.frame is not None:
            fx, fy, w, h = self.frame
            self.win.engine.view.queue_draw_area(int(fx) - 4, int(fy) - 4,
                                                 int(w) + 10 + TAB_W, int(h) + 10)
        else:
            self.win.engine.view.queue_draw()

    def changed(self, push=True):
        self.blink_on = True
        self._start_blink()
        self._layout()
        self.win.engine.view.queue_draw()
        if push:
            if self._push:
                GLib.source_remove(self._push)
            self._push = GLib.timeout_add(250, self._push_now)

    # ------------------------------------------------------------ write back
    def markup(self):
        if self.mode == "linear":
            return linear_markup(self.lin) if self.lin.strip() else '"Type equation here."'
        if not self.root.items:
            return '"Type equation here."'
        root, _num = self._split_number(self.root)
        try:
            return M.to_starmath(root)
        except Exception:
            return '"%s"' % M.to_linear(root).replace('"', "'")

    def _push_now(self, final=False):
        self._push = 0
        if self.obj is None:
            return False
        mk = self.markup()
        if os.environ.get("FOLIO_EQ_DEBUG"):
            print("EQ PUSH", repr(mk), flush=True)
        if mk != self._last_markup:
            try:
                docapi.set_formula(self.obj, mk)
                self._last_markup = mk
            except Exception as e:
                print("equation:", e)
        return False

    def _ensure_fonts(self):
        font = self.opts().get("font", "Caladea")
        try:
            emb = self.obj.getEmbeddedObject()
            for p in ("FontNameVariables", "FontNameFunctions", "FontNameNumbers",
                      "FontNameText"):
                if getattr(emb, p) != font:
                    setattr(emb, p, font)
            if not emb.FontVariablesIsItalic:
                emb.FontVariablesIsItalic = True
        except Exception:
            pass

    # ------------------------------------------------------------ numbering
    def _split_number(self, root):
        """'E=mc^2#(1)': the part after # is the equation number."""
        for i, it in enumerate(root.items):
            if isinstance(it, Atom) and it.value == "#":
                return Seq(root.items[:i]), Seq(root.items[i + 1:])
        return root, None

    def _number_save(self, obj):
        if self.mode != "professional":
            return
        _eq, num = self._split_number(self.root)
        try:
            from . import eqnumber
            eqnumber.apply(self.win, obj, M.to_linear(num) if num is not None and
                           num.items else None)
        except Exception as e:
            print("equation number:", e)

    def _number_load(self):
        if self.mode != "professional" or self.obj is None:
            return
        try:
            from . import eqnumber
            num = eqnumber.current(self.obj)
        except Exception:
            num = None
        if num:
            try:
                tail = M.from_linear(num).items
            except Exception:
                tail = [Atom("text", ch) for ch in num]
            self.root.items.extend([Atom("op", "#")] + tail)

    # ------------------------------------------------------------ undo
    def _snap(self):
        if self.mode == "linear":
            return ("lin", self.lin, self.lin_pos)
        path = self._path(self.caret[0])
        return ("pro", copy.deepcopy(self.root), path, self.caret[1])

    def _restore(self, snap):
        if snap[0] == "lin":
            self.mode = "linear"
            _k, self.lin, self.lin_pos = snap
            self.lin_anchor = None
            return
        self.mode = "professional"
        self.root = copy.deepcopy(snap[1])
        seq = self._follow(snap[2]) or self.root
        self.caret = (seq, min(snap[3], len(seq.items)))
        self.anchor = None
        self.picked = None

    def _path(self, seq):
        """A path of slot indexes from the root to seq."""
        path = []
        par = M.parents(self.root)
        while seq is not self.root and id(seq) in par:
            node, owner = par[id(seq)]
            path.append((owner.items.index(node), M.slots(node).index(seq)))
            seq = owner
        return list(reversed(path))

    def _follow(self, path):
        seq = self.root
        try:
            for i, j in path:
                seq = M.slots(seq.items[i])[j]
        except (IndexError, AttributeError):
            return None
        return seq

    def remember(self):
        self.undo_stack.append(self._snap())
        del self.undo_stack[:-200]
        self.redo_stack = []

    def undo(self):
        if not self.undo_stack:
            return
        self.redo_stack.append(self._snap())
        self._restore(self.undo_stack.pop())
        self.changed()

    def redo(self):
        if not self.redo_stack:
            return
        self.undo_stack.append(self._snap())
        self._restore(self.redo_stack.pop())
        self.changed()

    # ------------------------------------------------------------ caret moves
    def _parents(self):
        return M.parents(self.root)

    def move_right(self, extend=False):
        seq, i = self.caret
        if extend:
            if self.anchor is None:
                self.anchor = i
            self.caret = (seq, min(len(seq.items), i + 1))
            return
        if self._collapse_selection(right=True):
            return
        if self.picked is not None:
            node = self.picked
            self.picked = None
            owner = self._owner(node)
            if owner is not None:
                self.caret = (owner, owner.items.index(node) + 1)
            return
        if i < len(seq.items):
            it = seq.items[i]
            if M.is_struct(it) and M.first_slot(it) is not None:
                self.caret = (M.first_slot(it), 0)
            else:
                self.caret = (seq, i + 1)
            return
        par = self._parents()
        if id(seq) not in par:
            return
        node, owner = par[id(seq)]
        ss = M.slots(node)
        k = ss.index(seq)
        if k + 1 < len(ss):
            self.caret = (ss[k + 1], 0)
        else:
            self.caret = (owner, owner.items.index(node) + 1)

    def move_left(self, extend=False):
        seq, i = self.caret
        if extend:
            if self.anchor is None:
                self.anchor = i
            self.caret = (seq, max(0, i - 1))
            return
        if self._collapse_selection(right=False):
            return
        if self.picked is not None:
            node = self.picked
            self.picked = None
            owner = self._owner(node)
            if owner is not None:
                self.caret = (owner, owner.items.index(node))
            return
        if i > 0:
            it = seq.items[i - 1]
            if M.is_struct(it) and M.last_slot(it) is not None:
                s = M.last_slot(it)
                self.caret = (s, len(s.items))
            else:
                self.caret = (seq, i - 1)
            return
        par = self._parents()
        if id(seq) not in par:
            return
        node, owner = par[id(seq)]
        ss = M.slots(node)
        k = ss.index(seq)
        if k > 0:
            self.caret = (ss[k - 1], len(ss[k - 1].items))
        else:
            self.caret = (owner, owner.items.index(node))

    def _collapse_selection(self, right):
        seq, i = self.caret
        if self.anchor is not None and self.anchor != i:
            a, z = sorted((self.anchor, i))
            self.caret = (seq, z if right else a)
            self.anchor = None
            return True
        self.anchor = None
        return False

    def _owner(self, node):
        if node in self.root.items:
            return self.root
        for sid, (n, owner) in self._parents().items():
            if node in owner.items:
                return owner
        return None

    def move_vert(self, d):
        """Up / down: to the slot above or below in the same structure."""
        self.anchor = None
        self.picked = None
        c = self._caret_rect()
        if c is None or self.box is None:
            return
        cx, cy0, cy1 = c
        cy = (cy0 + cy1) / 2
        seq = self.caret[0]
        par = self._parents()
        while id(seq) in par:
            node, owner = par[id(seq)]
            best = None
            for s in M.slots(node):
                b = self._slot_box(s)
                if b is None or s is seq:
                    continue
                by = b.ay - b.asc / 2 + b.desc / 2
                if (d < 0 and by < cy - 2) or (d > 0 and by > cy + 2):
                    dy = abs(by - cy)
                    dx = 0 if b.ax <= cx <= b.ax + b.w else min(abs(b.ax - cx),
                                                                abs(b.ax + b.w - cx))
                    score = dy + dx * 2
                    if best is None or score < best[0]:
                        best = (score, s, b)
            if best is not None:
                _sc, s, b = best
                xs = b.xs or [0]
                k = min(range(len(xs)), key=lambda j: abs(b.ax + xs[j] - cx))
                self.caret = (s, k)
                return
            seq = owner

    def home(self, extend=False):
        seq, i = self.caret
        if extend:
            if self.anchor is None:
                self.anchor = i
            self.caret = (seq, 0)
            return
        self.anchor = None
        self.picked = None
        self.caret = (seq, 0) if i > 0 or seq is self.root else (self.root, 0)

    def end(self, extend=False):
        seq, i = self.caret
        if extend:
            if self.anchor is None:
                self.anchor = i
            self.caret = (seq, len(seq.items))
            return
        self.anchor = None
        self.picked = None
        n = len(seq.items)
        self.caret = (seq, n) if i < n or seq is self.root else (self.root,
                                                                  len(self.root.items))

    # ------------------------------------------------------------ editing
    def _take_selection(self):
        """Remove and return the selected items (or the picked structure)."""
        if self.picked is not None:
            owner = self._owner(self.picked)
            node = self.picked
            self.picked = None
            if owner is None:
                return []
            k = owner.items.index(node)
            del owner.items[k]
            self.caret = (owner, k)
            return [node]
        seq, i = self.caret
        if self.anchor is None or self.anchor == i:
            self.anchor = None
            return []
        a, z = sorted((self.anchor, i))
        taken = seq.items[a:z]
        del seq.items[a:z]
        self.caret = (seq, a)
        self.anchor = None
        return taken

    def insert_items(self, items, enter=True):
        """Insert at the caret; the caret goes to the first empty slot of what
        was inserted, or after it."""
        seq, i = self.caret
        # typing over a placeholder replaces it
        if i < len(seq.items) and isinstance(seq.items[i], Atom) and \
                seq.items[i].kind == "placeholder":
            del seq.items[i]
        elif i > 0 and isinstance(seq.items[i - 1], Atom) and \
                seq.items[i - 1].kind == "placeholder":
            del seq.items[i - 1]
            i -= 1
        # typed text takes the formatting of the text before it
        near = seq.items[i - 1] if i > 0 else (seq.items[i] if i < len(seq.items) else None)
        if isinstance(near, Atom):
            for it in items:
                if isinstance(it, Atom) and getattr(it, "wrpr", None) is None:
                    M._fmt(near, it)
        seq.items[i:i] = items
        self.caret = (seq, i + len(items))
        if enter:
            tmp = Seq(items)
            empty = M.first_empty(tmp)
            if empty is not None:
                self.caret = (empty, 0)

    def type_char(self, ch):
        if self.mode == "linear":
            self._lin_insert(ch)
            return
        if ch == " " or (ch in BUILD_TRIGGERS and self.opts().get("autobuild", True)):
            built = self.build_up()
            if ch == " ":
                if not built:
                    # a space only separates words of normal text
                    seq, i = self.caret
                    if i > 0 and isinstance(seq.items[i - 1], Atom) and \
                            seq.items[i - 1].kind == "text":
                        self.insert_items([Atom("text", " ")], enter=False)
                return
        taken = self._take_selection()
        k = "text" if self.bar.normal_text else _kind(ch)
        self.insert_items([Atom(k, ch)], enter=False)
        if taken:
            pass
        self._auto_pairs()

    def _auto_pairs(self):
        seq, i = self.caret
        for a, b in S.AUTO_PAIRS:
            n = len(a)
            if i >= n and all(isinstance(x, Atom) for x in seq.items[i - n:i]) and \
                    "".join(x.value for x in seq.items[i - n:i]) == a:
                seq.items[i - n:i] = [Atom(_kind(b), b)]
                self.caret = (seq, i - n + 1)
                return

    def build_up(self):
        """Convert the linear text before the caret into structures (on a
        space or an operator), as in the original. Returns True if anything
        changed."""
        seq, i = self.caret
        head = seq.items[:i]
        plain = "".join(x.value for x in head if isinstance(x, Atom))
        if not plain:
            return False
        needs = any(c in S.STRUCTURE or c in "\\()[]{}⟨⟩|" or c == '"' for c in plain)
        word = self._trailing_word(head)
        if word and (word in S.FUNCTIONS or word in self._user_functions()):
            needs = True
        if not needs:
            return False
        changed = self._control_word()
        if changed:
            seq, i = self.caret
            head = seq.items[:i]
            plain = "".join(x.value for x in head if isinstance(x, Atom))
        text = M.raw_linear(head)
        if not _complete(text):
            return changed
        try:
            items = M.unfence(M.from_linear(text)).items
        except Exception:
            return changed
        if M.to_linear(Seq(items)) == M.to_linear(Seq(head)) and \
                len(items) == len(head):
            return changed
        seq.items[:i] = items
        self.caret = (seq, len(items))
        # a fresh structure with an empty slot: go there
        for it in reversed(items):
            if M.is_struct(it):
                e = M.first_empty(Seq([it]))
                if e is not None:
                    self.caret = (e, 0)
                break
        return True

    def _control_word(self):
        """\\alpha before the caret -> α."""
        seq, i = self.caret
        k = i
        while k > 0 and isinstance(seq.items[k - 1], Atom) and seq.items[k - 1].kind == "ident" \
                and seq.items[k - 1].value.isalpha():
            k -= 1
        if k == i or k == 0 or not (isinstance(seq.items[k - 1], Atom) and
                                     seq.items[k - 1].value == "\\"):
            return False
        word = "".join(x.value for x in seq.items[k:i])
        sym = S.CONTROL_WORDS.get(word) or self.opts().get("autocorrect", {}).get(word)
        if not sym:
            return False
        try:
            new = M.from_linear(sym).items if len(sym) > 1 else [Atom(_kind(sym), sym)]
        except Exception:
            new = [Atom("sym", sym)]
        if len(sym) == 1 and sym in S.NARY or sym in S.STRUCTURE:
            new = [Atom("sym", sym)]
        seq.items[k - 1:i] = new
        self.caret = (seq, k - 1 + len(new))
        return True

    @staticmethod
    def _trailing_word(items):
        w = []
        for x in reversed(items):
            if isinstance(x, Atom) and x.kind == "ident" and x.value.isalpha():
                w.append(x.value)
            else:
                break
        return "".join(reversed(w))

    def _user_functions(self):
        return set(self.opts().get("functions", []))

    def backspace(self):
        if self.mode == "linear":
            self._lin_delete(-1)
            return
        if self._take_selection():
            return
        seq, i = self.caret
        if i > 0:
            it = seq.items[i - 1]
            if M.is_struct(it):
                if all(not s.items for s in M.slots(it)):
                    del seq.items[i - 1]
                    self.caret = (seq, i - 1)
                else:
                    # first backspace selects the structure, the next deletes it
                    self.picked = it
                return
            del seq.items[i - 1]
            self.caret = (seq, i - 1)
            return
        par = self._parents()
        if id(seq) not in par:
            return
        node, owner = par[id(seq)]
        if all(not s.items for s in M.slots(node)):
            k = owner.items.index(node)
            del owner.items[k]
            self.caret = (owner, k)
            return
        if seq is M.first_slot(node):
            # at the start of the first slot: step out to the left
            self.caret = (owner, owner.items.index(node))
        else:
            self.move_left()

    def delete(self):
        if self.mode == "linear":
            self._lin_delete(1)
            return
        if self._take_selection():
            return
        seq, i = self.caret
        if i < len(seq.items):
            it = seq.items[i]
            if M.is_struct(it):
                if all(not s.items for s in M.slots(it)):
                    del seq.items[i]
                else:
                    self.picked = it
                return
            del seq.items[i]
            return
        par = self._parents()
        if id(seq) in par:
            node, owner = par[id(seq)]
            if all(not s.items for s in M.slots(node)):
                k = owner.items.index(node)
                del owner.items[k]
                self.caret = (owner, k)

    def insert_linear(self, linear):
        """A structure or symbol from the ribbon (linear text, ⬚ = slot)."""
        if self.mode == "linear":
            self.remember()
            self._lin_insert(linear)
            self.changed()
            return
        self.remember()
        try:
            items = M.from_linear(linear).items
        except Exception:
            items = [Atom(_kind(c), c) for c in linear]
        taken = self._take_selection()
        if taken:
            # the selection goes into the new structure's first slot
            tmp = Seq(items)
            e = M.first_empty(tmp)
            if e is not None:
                e.items[:] = taken
        self.insert_items(items)
        self.changed()

    def select_all(self):
        if self.mode == "linear":
            self.lin_anchor, self.lin_pos = 0, len(self.lin)
            return
        self.picked = None
        self.caret = (self.root, len(self.root.items))
        self.anchor = 0

    # ------------------------------------------------------------ linear mode
    def _lin_sel(self):
        if self.lin_anchor is None or self.lin_anchor == self.lin_pos:
            return None
        return sorted((self.lin_anchor, self.lin_pos))

    def _lin_insert(self, text):
        sel = self._lin_sel()
        if sel:
            a, z = sel
            self.lin = self.lin[:a] + self.lin[z:]
            self.lin_pos = a
        self.lin_anchor = None
        self.lin = self.lin[:self.lin_pos] + text + self.lin[self.lin_pos:]
        self.lin_pos += len(text)
        if "\\" in self.lin and self.bar.input_format == "unicode":
            new = U.expand_control_words(self.lin, final=False)
            if new != self.lin:
                self.lin_pos = max(0, self.lin_pos - (len(self.lin) - len(new)))
                self.lin = new

    def _lin_delete(self, d):
        sel = self._lin_sel()
        if sel:
            a, z = sel
            self.lin = self.lin[:a] + self.lin[z:]
            self.lin_pos = a
        elif d < 0 and self.lin_pos > 0:
            self.lin = self.lin[:self.lin_pos - 1] + self.lin[self.lin_pos:]
            self.lin_pos -= 1
        elif d > 0 and self.lin_pos < len(self.lin):
            self.lin = self.lin[:self.lin_pos] + self.lin[self.lin_pos + 1:]
        self.lin_anchor = None

    def _lin_move(self, d, extend, word=False):
        if extend:
            if self.lin_anchor is None:
                self.lin_anchor = self.lin_pos
        else:
            sel = self._lin_sel()
            self.lin_anchor = None
            if sel:
                self.lin_pos = sel[1] if d > 0 else sel[0]
                return
        p = self.lin_pos + d
        if word:
            while 0 < p < len(self.lin) and self.lin[p].isalnum():
                p += d
        self.lin_pos = max(0, min(len(self.lin), p))

    # ------------------------------------------------------------ conversions
    def linear_text(self):
        if self.mode == "linear":
            return self.lin
        if self.bar.input_format == "latex":
            return M.to_latex(self.root)
        return M.to_linear(self.root)

    def to_professional(self):
        if self.mode == "professional":
            return
        self.remember()
        text = self.lin
        try:
            if self.bar.input_format == "latex":
                self.root = M.from_latex(text)
            else:
                self.root = M.from_linear(U.expand_control_words(text, final=True))
        except Exception:
            self.root = Seq([Atom("text", ch) for ch in text])
        self.mode = "professional"
        self.caret = (self.root, len(self.root.items))
        self.anchor = None
        self.picked = None
        self.changed()

    def to_linear_mode(self):
        if self.mode == "linear":
            return
        self.remember()
        self.lin = self.linear_text()
        self.lin_pos = len(self.lin)
        self.lin_anchor = None
        self.mode = "linear"
        self.changed()

    def load_linear(self, text):
        """Replace the whole equation with linear text (built up)."""
        self.remember()
        if self.mode == "linear":
            self.lin = text
            self.lin_pos = len(text)
        else:
            try:
                if self.bar.input_format == "latex":
                    self.root = M.from_latex(text)
                else:
                    self.root = M.from_linear(U.expand_control_words(text, final=True))
            except Exception:
                self.root = Seq([Atom(_kind(c), c) for c in text])
            self.caret = (self.root, len(self.root.items))
            self.anchor = None
            self.picked = None
        self.changed()

    # ------------------------------------------------------------ clipboard
    def copy(self, cut=False):
        if self.mode == "linear":
            sel = self._lin_sel()
            text = self.lin[sel[0]:sel[1]] if sel else ""
        else:
            if self.picked is not None:
                text = M.to_linear(Seq([self.picked]))
            else:
                seq, i = self.caret
                if self.anchor is None or self.anchor == i:
                    return False
                a, z = sorted((self.anchor, i))
                text = M.to_linear(Seq(seq.items[a:z]))
        if not text:
            return False
        Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(text, -1)
        if cut:
            self.remember()
            if self.mode == "linear":
                self._lin_delete(0)
            else:
                self._take_selection()
            self.changed()
        return True

    def paste(self):
        text = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).wait_for_text()
        if not text:
            return
        text = text.strip()
        if self.mode == "linear":
            self.remember()
            self._lin_insert(text)
            self.changed()
            return
        if self.bar.input_format == "latex" and "\\" in text:
            try:
                text = latex.to_linear(text)
            except Exception:
                pass
        self.insert_linear(text)

    # ------------------------------------------------------------ keys
    def key(self, event):
        """Window key handler; True when the key was used here."""
        if self.obj is None:
            return False
        st = event.state
        ctrl = bool(st & Gdk.ModifierType.CONTROL_MASK)
        shift = bool(st & Gdk.ModifierType.SHIFT_MASK)
        alt = bool(st & Gdk.ModifierType.MOD1_MASK)
        kv = event.keyval
        name = (Gdk.keyval_name(Gdk.keyval_to_lower(kv)) or "").lower()
        lin = self.mode == "linear"
        if name in ("shift_l", "shift_r", "control_l", "control_r", "alt_l", "alt_r",
                    "caps_lock", "iso_level3_shift", "super_l", "super_r"):
            return False
        if kv == Gdk.KEY_Escape or (alt and kv == Gdk.KEY_equal):
            self.bar.finish()
            return True
        if ctrl and not alt:
            if name == "z":
                self.undo()
                return True
            if name == "y":
                self.redo()
                return True
            if name == "a":
                self.select_all()
                self.changed(push=False)
                return True
            if name in ("c", "insert"):
                self.copy()
                return True
            if name == "x":
                self.copy(cut=True)
                return True
            if name == "v":
                self.paste()
                return True
            if name == "equal":
                # Ctrl+= : subscript structure
                self.insert_linear("⬚_⬚")
                return True
            if name == "plus":
                self.insert_linear("⬚^⬚")
                return True
            if name in ("left", "right") and lin:
                self._lin_move(-1 if name == "left" else 1, shift, word=True)
                self.changed(push=False)
                return True
            if name not in ("left", "right", "home", "end", "backspace", "delete"):
                # anything else (Save, Print ...) leaves the equation first
                self.bar.finish()
                return False
        if name in ("left", "right", "up", "down", "home", "end", "kp_left", "kp_right"):
            if lin:
                if name in ("left", "kp_left"):
                    self._lin_move(-1, shift)
                elif name in ("right", "kp_right"):
                    self._lin_move(1, shift)
                elif name == "home":
                    self._lin_move(-len(self.lin), shift)
                elif name == "end":
                    self._lin_move(len(self.lin), shift)
                else:
                    self.bar.finish()
                    return False
                self.changed(push=False)
                return True
            if name in ("left", "kp_left"):
                if not shift and self.caret == (self.root, 0) and self.anchor is None:
                    self.bar.finish(cursor="before")
                    return True
                self.move_left(shift)
            elif name in ("right", "kp_right"):
                if not shift and self.caret == (self.root, len(self.root.items)) and \
                        self.anchor is None and self.picked is None:
                    self.bar.finish()
                    return True
                self.move_right(shift)
            elif name == "up":
                before = self.caret
                self.move_vert(-1)
                if self.caret == before:
                    self.bar.finish()
                    return False
            elif name == "down":
                before = self.caret
                self.move_vert(1)
                if self.caret == before:
                    self.bar.finish()
                    return False
            elif name == "home":
                self.home(shift)
            elif name == "end":
                self.end(shift)
            self.changed(push=False)
            return True
        if name == "backspace":
            self.remember()
            self.backspace()
            self.changed()
            return True
        if name == "delete":
            self.remember()
            self.delete()
            self.changed()
            return True
        if name in ("return", "kp_enter"):
            if lin:
                self.bar.finish()
                return True
            if self._in_matrix_or_array():
                self.remember()
                self._add_array_row()
                self.changed()
                return True
            # Enter ends the equation and starts a new paragraph after it
            self.bar.finish()
            return False
        if name in ("tab", "iso_left_tab"):
            if lin:
                return True
            self._next_slot(-1 if (shift or name == "iso_left_tab") else 1)
            self.changed(push=False)
            return True
        ch = chr(Gdk.keyval_to_unicode(kv)) if Gdk.keyval_to_unicode(kv) else ""
        if ch and (unicodedata.category(ch)[0] != "C") and not (ctrl and not alt):
            self.remember()
            if self.mode == "professional":
                if ch == "\\" and False:
                    pass
                self.type_char(ch)
                self._control_word_check(ch)
            else:
                self._lin_insert(ch)
            self.changed()
            return True
        return True

    def _control_word_check(self, ch):
        """\\alpha + space/operator -> α (already handled by build-up when it
        fires); handle the plain-word case here."""
        pass

    def _next_slot(self, d):
        """Tab: the next (or previous) empty slot, then the next slot."""
        order = []

        def walk(seq):
            for it in seq.items:
                if M.is_struct(it):
                    for s in M.slots(it):
                        order.append(s)
                        walk(s)
        walk(self.root)
        if not order:
            return
        cur = self.caret[0]
        try:
            k = [id(s) for s in order].index(id(cur))
        except ValueError:
            k = -1 if d > 0 else len(order)
        k = (k + d) % len(order)
        self.caret = (order[k], 0 if d < 0 else len(order[k].items))
        if not order[k].items:
            self.caret = (order[k], 0)
        self.anchor = None
        self.picked = None

    def _in_matrix_or_array(self):
        par = self._parents()
        seq = self.caret[0]
        while id(seq) in par:
            node, owner = par[id(seq)]
            if isinstance(node, U.EqArray):
                return True
            seq = owner
        return False

    def _add_array_row(self):
        par = self._parents()
        seq = self.caret[0]
        while id(seq) in par:
            node, owner = par[id(seq)]
            if isinstance(node, U.EqArray):
                for k, row in enumerate(node.rows):
                    if any(c is seq for c in row):
                        new = [Seq([]) for _c in row]
                        node.rows.insert(k + 1, new)
                        self.caret = (new[0], 0)
                        return
            seq = owner

    # ------------------------------------------------------------ structure menu
    def _enclosing(self):
        """[(node, owner_seq, slot_seq)] from the innermost structure out."""
        par = self._parents()
        out = []
        seq = self.caret[0]
        while id(seq) in par:
            node, owner = par[id(seq)]
            out.append((node, owner, seq))
            seq = owner
        return out

    def _edit_struct(self, fn):
        self.remember()
        fn()
        par = self._parents()
        if self.caret[0] is not self.root and id(self.caret[0]) not in par:
            self.caret = (self.root, len(self.root.items))
        self.caret = (self.caret[0], min(self.caret[1], len(self.caret[0].items)))
        self.anchor = None
        self.picked = None
        self.changed()

    def _replace(self, node, owner, items):
        """Put items where node was; the caret goes after them."""
        i = owner.items.index(node)
        owner.items[i:i + 1] = items
        self.caret = (owner, i + len(items))

    def structure_menu(self):
        """(label, callback, radio_state or None) groups for the structures
        around the caret, as in the original's right-click menu."""
        if self.mode != "professional":
            return []
        groups = []
        seen = set()
        for node, owner, seq in self._enclosing():
            t = type(node)
            if t in seen:
                continue
            seen.add(t)
            g = []
            if isinstance(node, U.Frac):
                for kind, label in (("bar", "Change to Stacked Fraction"),
                                    ("skew", "Change to Skewed Fraction"),
                                    ("linear", "Change to Linear Fraction"),
                                    ("stack", "Remove Fraction Bar")):
                    if kind == "stack" and node.kind == "stack":
                        label = "Add Fraction Bar"
                        kind = "bar"
                    elif kind == node.kind:
                        continue
                    g.append((label, lambda n=node, k=kind: self._edit_struct(
                        lambda: setattr(n, "kind", k)), None))
            elif isinstance(node, U.Script):
                def drop(n=node, o=owner, which="sub"):
                    def f():
                        setattr(n, which, None)
                        if n.sub is None and n.sup is None:
                            self._replace(n, o, list(n.base.items))
                    self._edit_struct(f)
                if node.sub is not None and node.sup is not None:
                    g.append(("Remove Subscript", lambda: drop(which="sub"), None))
                    g.append(("Remove Superscript", lambda: drop(which="sup"), None))
                else:
                    g.append(("Remove Script", lambda w="sub" if node.sub is not None
                              else "sup": drop(which=w), None))
                if node.sub is None:
                    g.append(("Add Subscript", lambda n=node: self._edit_struct(
                        lambda: (setattr(n, "sub", Seq([])),
                                 setattr(self, "caret", (n.sub, 0)))), None))
                if node.sup is None:
                    g.append(("Add Superscript", lambda n=node: self._edit_struct(
                        lambda: (setattr(n, "sup", Seq([])),
                                 setattr(self, "caret", (n.sup, 0)))), None))
                g.append(("Change to Postscript" if node.pre else "Change to Prescript",
                          lambda n=node: self._edit_struct(
                              lambda: setattr(n, "pre", not n.pre)), None))
            elif isinstance(node, U.Root):
                if node.index is None:
                    g.append(("Show Degree", lambda n=node: self._edit_struct(
                        lambda: (setattr(n, "index", Seq([])),
                                 setattr(self, "caret", (n.index, 0)))), None))
                else:
                    g.append(("Hide Degree", lambda n=node: self._edit_struct(
                        lambda: setattr(n, "index", None)), None))
            elif isinstance(node, U.Nary):
                for attr, label in (("sub", "Lower Limit"), ("sup", "Upper Limit")):
                    present = getattr(node, attr) is not None
                    g.append((("Hide " if present else "Show ") + label,
                              lambda n=node, a=attr, p=present: self._edit_struct(
                                  lambda: setattr(n, a, None if p else Seq([]))), None))
            elif isinstance(node, U.Delim) and (node.open or node.close):
                g.append(("Remove Enclosing Characters", lambda n=node, o=owner:
                          self._edit_struct(lambda: self._replace(n, o, list(n.body.items))),
                          None))
            elif isinstance(node, (U.Matrix, U.EqArray)):
                r, c = next(((ri, row.index(seq)) for ri, row in enumerate(node.rows)
                             if any(x is seq for x in row)), (0, 0))
                ncols = max(len(row) for row in node.rows)
                if isinstance(node, U.EqArray):
                    g.append(("Insert Equation Before", lambda n=node: self._edit_struct(
                        lambda: self._rows(n, r, 0)), None))
                    g.append(("Insert Equation After", lambda n=node, r=r: self._edit_struct(
                        lambda: self._rows(n, r, 1)), None))
                    if len(node.rows) > 1:
                        g.append(("Delete Equation", lambda n=node, r=r: self._edit_struct(
                            lambda: self._del_row(n, r)), None))
                else:
                    g.append(("Insert Row Above", lambda n=node: self._edit_struct(
                        lambda: self._rows(n, r, 0)), None))
                    g.append(("Insert Row Below", lambda n=node, r=r: self._edit_struct(
                        lambda: self._rows(n, r, 1)), None))
                    g.append(("Insert Column Before", lambda n=node, c=c: self._edit_struct(
                        lambda: self._cols(n, c, 0)), None))
                    g.append(("Insert Column After", lambda n=node, c=c: self._edit_struct(
                        lambda: self._cols(n, c, 1)), None))
                    if len(node.rows) > 1:
                        g.append(("Delete Row", lambda n=node, r=r: self._edit_struct(
                            lambda: self._del_row(n, r)), None))
                    if ncols > 1:
                        g.append(("Delete Column", lambda n=node, c=c: self._edit_struct(
                            lambda: self._del_col(n, c)), None))
            if g:
                groups.append(g)
        return groups

    def _rows(self, node, r, after):
        ncols = max(len(row) for row in node.rows)
        new = [Seq([]) for _c in range(ncols)]
        node.rows.insert(r + after, new)
        self.caret = (new[0], 0)

    def _cols(self, node, c, after):
        first = None
        for row in node.rows:
            s = Seq([])
            row.insert(min(len(row), c + after), s)
            first = first or s
        self.caret = (node.rows[0][min(len(node.rows[0]) - 1, c + after)], 0)

    def _del_row(self, node, r):
        node.rows.pop(r)
        row = node.rows[min(r, len(node.rows) - 1)]
        self.caret = (row[0], 0)

    def _del_col(self, node, c):
        for row in node.rows:
            if c < len(row) and len(row) > 1:
                row.pop(c)
        row = node.rows[0]
        self.caret = (row[min(c, len(row) - 1)], 0)

    # ------------------------------------------------------------ mouse
    def inside(self, x, y):
        if self.frame is None:
            return False
        fx, fy, w, h = self.frame
        if self.on_tab(x, y):
            return True
        right = fx + w + (TAB_W if self._display_cached else 0)
        return fx - 2 <= x <= right + 2 and fy - 2 <= y <= fy + h + 2

    def _tab_rect(self):
        fx, fy, w, h = self.frame
        if self._display_cached:
            return int(fx + w) + 0.5, int(fy) + 0.5, int(h)
        return int(fx + w - TAB_W) + 0.5, int(fy + h) + 0.5, 9

    def on_tab(self, x, y):
        tx, ty, th = self._tab_rect()
        return tx <= x <= tx + TAB_W and ty <= y <= ty + th

    def press(self, event):
        """Button press on the document view while editing."""
        if self.obj is None:
            return False
        x, y = event.x, event.y
        if not self.inside(x, y):
            self.bar.finish(cursor=None)
            return False
        if event.button == 3 or self.on_tab(x, y):
            self.bar.options_menu(event)
            return True
        if event.button == 1:
            if event.type == Gdk.EventType._2BUTTON_PRESS:
                self.click(x, y)
                self._select_word()
            else:
                self.click(x, y, extend=bool(event.state & Gdk.ModifierType.SHIFT_MASK))
                self.drag = True
            self.changed(push=False)
            return True
        return True

    def _motion(self, view, event):
        if self.obj is not None and self.drag and event.state & Gdk.ModifierType.BUTTON1_MASK:
            self.click(event.x, event.y, extend=True)
            self.changed(push=False)
            return True
        return False

    def _release(self, view, event):
        if self.drag:
            self.drag = False
            return True
        return False

    def click(self, x, y, extend=False):
        if self.box is None:
            return
        if self.mode == "linear":
            b = self.box
            xs = b.xs
            k = min(range(len(xs)), key=lambda j: abs(b.ax + xs[j] - x))
            if extend:
                if self.lin_anchor is None:
                    self.lin_anchor = self.lin_pos
            else:
                self.lin_anchor = None
            self.lin_pos = k
            return
        best = None
        for b in getattr(self.box, "slots", []):
            x0, x1 = b.ax, b.ax + b.w
            y0, y1 = b.ay - b.asc, b.ay + b.desc
            inside = x0 - 1 <= x <= x1 + 1 and y0 <= y <= y1
            if inside:
                area = (x1 - x0) * (y1 - y0)
                if best is None or best[0] > 0 or area < best[1]:
                    best = (0, area, b)
            else:
                dx = max(x0 - x, 0, x - x1)
                dy = max(y0 - y, 0, y - y1)
                d = dx + dy * 1.5
                if best is None or (best[0] > 0 and d < best[0]):
                    best = (d, 0, b)
        if best is None:
            return
        b = best[2]
        xs = b.xs or [0.0]
        k = min(range(len(xs)), key=lambda j: abs(b.ax + xs[j] - x))
        self.picked = None
        if extend and self.caret[0] is b.seq:
            if self.anchor is None:
                self.anchor = self.caret[1]
        elif extend:
            pass
        else:
            self.anchor = None
        if extend and self.caret[0] is not b.seq:
            return
        self.caret = (b.seq, k)

    def _select_word(self):
        if self.mode == "linear":
            p = self.lin_pos
            a = p
            while a > 0 and self.lin[a - 1].isalnum():
                a -= 1
            z = p
            while z < len(self.lin) and self.lin[z].isalnum():
                z += 1
            self.lin_anchor, self.lin_pos = a, z
            return
        seq, i = self.caret
        a = i
        while a > 0 and isinstance(seq.items[a - 1], Atom) and seq.items[a - 1].kind in (
                "ident", "num", "text"):
            a -= 1
        z = i
        while z < len(seq.items) and isinstance(seq.items[z], Atom) and \
                seq.items[z].kind in ("ident", "num", "text"):
            z += 1
        if a == z:
            a, z = 0, len(seq.items)
        self.anchor, self.caret = a, (seq, z)
