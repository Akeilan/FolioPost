"""Equation > Ink Equation: write an equation by hand, see it recognised as
you write, and insert it. Recognition runs locally: each symbol is matched
against shapes from the Hershey vector fonts (inkfeatures), then fraction
bars, radicals, superscripts and subscripts are worked out from where the
symbols sit."""
import json
import math
import os

from gi.repository import Gdk, GLib, Gtk

from . import SHARE
from .eqn import model as M, render as R
from .inkfeatures import aspect, bbox, features
from .widgets import FDialog

_templates = None
DIGITS = set("0123456789")


def templates():
    global _templates
    if _templates is None:
        _templates = []
        for base in (os.path.join(SHARE, "inkmath"),
                     os.path.join(os.path.dirname(__file__), "..", "..", "share", "inkmath")):
            p = os.path.join(base, "templates.json")
            if os.path.exists(p):
                # the font shapes, then shapes learnt from real handwriting
                prior = {}
                q = os.path.join(base, "prior.json")
                if os.path.exists(q):
                    with open(q) as fh:
                        prior = json.load(fh)
                for name, pen in (("templates.json", 0.05), ("handwriting.json", 0.0)):
                    q = os.path.join(base, name)
                    if os.path.exists(q):
                        with open(q) as fh:
                            for t in json.load(fh):
                                # font shapes a little behind handwritten ones; common
                                # symbols a little ahead of rare look-alikes
                                bias = pen + 0.005 * prior.get(t["c"], 12.0)
                                _templates.append((t["c"], t["n"], t["a"], t["f"], bias))
                break
    return _templates


# ---------------------------------------------------------------- symbols
_cache = {}


def classify(strokes, k=5):
    """[(char, score)] best first (lower score is better)."""
    key = (k, tuple(tuple(map(tuple, s)) for s in strokes))
    hit = _cache.get(key)
    if hit is not None:
        return hit
    if len(_cache) > 512:
        _cache.clear()
    _cache[key] = res = _classify(strokes, k)
    return res


def _classify(strokes, k):
    import operator
    mul = operator.mul
    f = features(strokes)
    a = aspect(strokes)
    n = len(strokes)
    scored = []
    for ch, tn, ta, tf, bias in templates():
        dot = sum(map(mul, f, tf))
        d = (1.0 - dot) + 0.08 * abs(a - ta) + (0.04 * abs(n - tn) if n != tn else 0) + bias
        scored.append((d, ch))
    scored.sort()
    best = {}
    for d, ch in scored[:40]:
        if ch not in best:
            best[ch] = d
    return sorted(((ch, d) for ch, d in best.items()), key=lambda t: t[1])[:k]


class Sym:
    def __init__(self, strokes, ch=None, alts=None):
        self.strokes = strokes
        self.box = bbox(strokes)
        self.ch = ch
        self.alts = alts or []

    @property
    def x0(self):
        return self.box[0]

    @property
    def x1(self):
        return self.box[2]

    @property
    def y0(self):
        return self.box[1]

    @property
    def y1(self):
        return self.box[3]

    @property
    def w(self):
        return self.box[2] - self.box[0]

    @property
    def h(self):
        return self.box[3] - self.box[1]

    @property
    def cx(self):
        return (self.box[0] + self.box[2]) / 2

    @property
    def cy(self):
        return (self.box[1] + self.box[3]) / 2


def _flat(s, unit):
    x0, y0, x1, y1 = bbox([s])
    return (x1 - x0) > 0.25 * unit and (y1 - y0) < 0.3 * (x1 - x0)


def _vertical(s, unit):
    x0, y0, x1, y1 = bbox([s])
    return (y1 - y0) > 0.3 * unit and (x1 - x0) < 0.22 * (y1 - y0)


def _is_radical(s, unit):
    """A √ stroke: wide, ends high on the right, dips low in the left part."""
    x0, y0, x1, y1 = bbox([s])
    w, h = x1 - x0, y1 - y0
    if w < 1.2 * unit or h < 0.5 * unit or len(s) < 4:
        return False
    end = s[-1]
    if end[1] > y0 + 0.25 * h or end[0] < x1 - 0.15 * w:
        return False
    roof = [p for p in s if p[1] < y0 + 0.18 * h]
    if not roof or max(p[0] for p in roof) - min(p[0] for p in roof) < 0.45 * w:
        return False
    low = [p for p in s if p[1] > y1 - 0.2 * h]
    return bool(low) and min(p[0] for p in low) < x0 + 0.45 * w


def _is_bar(s, strokes, unit):
    """A long flat stroke with writing above and below it, crossed by none."""
    if not _flat(s, unit):
        return False
    x0, y0, x1, y1 = bbox([s])
    if x1 - x0 < 0.9 * unit:
        return False
    y = (y0 + y1) / 2
    above = below = False
    for o in strokes:
        if o is s:
            continue
        ox0, oy0, ox1, oy1 = bbox([o])
        cx = (ox0 + ox1) / 2
        if not (x0 <= cx <= x1):
            continue
        if oy0 < y < oy1:
            return False            # crossed: +, ±, ≠ ...
        if _flat(o, unit) and abs((oy0 + oy1) / 2 - y) < 0.6 * unit:
            return False            # =, ≡
        if oy1 < y and y - oy1 < 2 * unit:
            above = True
        elif oy0 > y and oy0 - y < 2 * unit:
            below = True
    return above and below


def _unit(strokes):
    hs = sorted(bbox([s])[3] - bbox([s])[1] for s in strokes
                if bbox([s])[3] - bbox([s])[1] > 3)
    return hs[(len(hs) * 3) // 4] if hs else 30.0


def _group(strokes, unit):
    """Strokes -> symbols (strokes of one symbol overlap horizontally)."""
    order = sorted(range(len(strokes)), key=lambda i: bbox([strokes[i]])[0])
    groups = []
    for i in order:
        s = strokes[i]
        x0, y0, x1, y1 = bbox([s])
        placed = False
        for g in reversed(groups[-3:]):
            gx0, gy0, gx1, gy1 = bbox(g)
            ov = min(x1, gx1) - max(x0, gx0)
            small = min(x1 - x0, gx1 - gx0)
            dot = (x1 - x0) < 0.2 * unit and (y1 - y0) < 0.2 * unit
            vgap = max(y0 - gy1, gy0 - y1)
            # thin strokes (|, the bar of +) count as a little wider
            pad = 0.08 * unit
            ov = min(x1 + pad, gx1 + pad) - max(x0 - pad, gx0 - pad)
            small = min(x1 - x0, gx1 - gx0) + 2 * pad
            both_flat = _flat(s, unit) and all(_flat(o, unit) for o in g)
            limit = 0.7 * unit if (both_flat or dot) else 0.3 * unit
            if (ov > 0.45 * small or (dot and ov > -0.1 * unit)) and vgap < limit:
                g.append(s)
                placed = True
                break
        if not placed:
            groups.append([s])
    return groups


def _name(group, unit):
    """Recognise one symbol, with the shapes no template handles well."""
    x0, y0, x1, y1 = bbox(group)
    w, h = x1 - x0, y1 - y0
    if w < 0.18 * unit and h < 0.18 * unit:
        return "·", []
    if len(group) == 1 and _flat(group[0], unit):
        return "−", []
    if len(group) == 2 and all(_flat(s, unit) for s in group):
        return "=", []
    if len(group) == 1 and _vertical(group[0], unit) and w < 0.18 * h:
        return "1", ["l", "|"]
    if len(group) == 2 and any(_vertical(s, unit) for s in group) and \
            any((bbox([s])[2] - bbox([s])[0]) < 0.2 * unit and
                (bbox([s])[3] - bbox([s])[1]) < 0.2 * unit for s in group):
        dot = [s for s in group if (bbox([s])[3] - bbox([s])[1]) < 0.2 * unit][0]
        stem = [s for s in group if s is not dot][0]
        return ("i" if bbox([dot])[1] < bbox([stem])[1] else "!"), ["j"]
    res = classify(group)
    if not res:
        return "?", []
    ch = res[0][0]
    return ch, [c for c, _d in res[1:]]


# ---------------------------------------------------------------- layout
def _parse(syms, unit):
    """Symbols (already recognised) -> linear text."""
    if not syms:
        return ""
    syms = sorted(syms, key=lambda s: s.x0)
    # fraction bars: a long flat line with symbols above and below it
    for bar in sorted((s for s in syms if s.ch == "−" and s.w > 0.9 * unit),
                      key=lambda s: -s.w):
        above = [s for s in syms if s is not bar and bar.x0 - 0.1 * unit <= s.cx <= bar.x1 +
                 0.1 * unit and s.cy < bar.cy and bar.cy - s.y1 < 2.2 * unit]
        below = [s for s in syms if s is not bar and bar.x0 - 0.1 * unit <= s.cx <= bar.x1 +
                 0.1 * unit and s.cy > bar.cy and s.y0 - bar.cy < 2.2 * unit]
        if above and below:
            rest = [s for s in syms if s is not bar and s not in above and s not in below]
            frac = Sym(bar.strokes)
            frac.ch = "frac"
            frac.box = (bar.x0, min(s.y0 for s in above), bar.x1, max(s.y1 for s in below))
            frac.text = "%s/%s" % (_wrap(_parse(above, unit)), _wrap(_parse(below, unit)))
            return _parse(rest + [frac], unit)
    # radicals: what sits under the roof is the radicand
    for rad in [s for s in syms if s.ch == "√" and s.w > 1.2 * unit]:
        inside = [s for s in syms if s is not rad and rad.x0 + 0.3 * rad.w <= s.cx <= rad.x1 +
                  0.1 * unit and s.cy > rad.y0]
        if inside:
            rest = [s for s in syms if s is not rad and s not in inside]
            r = Sym(rad.strokes)
            r.ch = "rad"
            r.box = rad.box
            r.text = "√(%s)" % _parse(inside, unit)
            return _parse(rest + [r], unit)
    # baseline, superscripts, subscripts
    out = []
    prev = None
    i = 0
    while i < len(syms):
        s = syms[i]
        txt = getattr(s, "text", None) or s.ch
        if prev is not None and prev.ch not in OPS and s.ch not in ("·", "−") and \
                s.h < 1.5 * max(prev.h, unit):
            if s.y1 < prev.cy and s.cy < prev.y0 + 0.2 * prev.h:
                # superscript: gather the following raised symbols too
                grp = [s]
                j = i + 1
                while j < len(syms) and syms[j].y1 < prev.cy:
                    grp.append(syms[j])
                    j += 1
                out.append("^" + _wrap(_parse(grp, unit * 0.7)))
                i = j
                continue
            if s.y0 > prev.cy and s.cy > prev.y1 - 0.2 * prev.h and prev.ch not in DIGITS:
                grp = [s]
                j = i + 1
                while j < len(syms) and syms[j].y0 > prev.cy:
                    grp.append(syms[j])
                    j += 1
                out.append("_" + _wrap(_parse(grp, unit * 0.7)))
                i = j
                continue
        if s.ch == "·" and prev is not None and s.cy > prev.cy + 0.2 * unit:
            txt = "."
        out.append(txt)
        prev = s
        i += 1
    text = "".join(out)
    # digits beside letters that look alike
    return text.replace("(1)", "(1)")


OPS = set("−+=·×÷±<>≤≥≠,") | {"frac"}


def _wrap(t):
    return t if len(t) == 1 else "(" + t + ")"


def recognise(strokes):
    """All strokes -> (linear text, [Sym])."""
    strokes = [s for s in strokes if len(s) >= 1]
    if not strokes:
        return "", []
    unit = _unit(strokes)
    syms = []
    rest = []
    for s in strokes:
        if _is_radical(s, unit):
            sym = Sym([s], "√")
            syms.append(sym)
        else:
            rest.append(s)
    # fraction bars stay single strokes
    bars = [s for s in rest if _is_bar(s, rest, unit)]
    rest = [s for s in rest if not any(s is b for b in bars)]
    for b in bars:
        syms.append(Sym([b], "−"))
    for g in _group(rest, unit):
        ch, alts = _name(g, unit)
        syms.append(Sym(g, ch, alts))
    _context(syms)
    return _parse(syms, unit), syms


def _context(syms):
    """Prefer digits next to digits, letters next to letters."""
    pairs = {"o": "0", "O": "0", "l": "1", "I": "1", "s": "5", "S": "5", "z": "2", "Z": "2",
             "g": "9", "b": "6", "q": "9"}
    order = sorted(syms, key=lambda s: s.x0)
    for i, s in enumerate(order):
        nb = [order[j].ch for j in (i - 1, i + 1) if 0 <= j < len(order)]
        if s.ch in pairs and any(c in DIGITS for c in nb):
            s.ch = pairs[s.ch]
        # a cross is mostly the letter x; a times sign sits between numbers
        if s.ch == "×":
            both = i > 0 and i + 1 < len(order)
            num = both and order[i - 1].ch in DIGITS | {")"} and order[i + 1].ch in DIGITS | {"("}
            if not num:
                s.ch = "x"
        # a t between two operands is a plus written with a short stem
        if s.ch in ("t", "f") and "+" in s.alts[:3] and 0 < i < len(order) - 1:
            s.ch = "+"


# ---------------------------------------------------------------- dialog
class InkDialog:
    def __init__(self, win):
        self.win = win
        self.strokes = []
        self.cur = None
        self.erase = False
        self.text = ""
        self.timer = 0
        d = FDialog(win, "Math Input Control", buttons=(("Insert", Gtk.ResponseType.OK),
                                                         ("Cancel", Gtk.ResponseType.CANCEL)))
        d.set_resizable(True)
        self.d = d
        self.preview = Gtk.DrawingArea()
        self.preview.set_size_request(640, 110)
        self.preview.connect("draw", self._draw_preview)
        pf = Gtk.Frame()
        pf.add(self.preview)
        d.add(pf)
        self.pad = Gtk.DrawingArea()
        self.pad.set_size_request(640, 300)
        self.pad.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK |
                            Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.TOUCH_MASK)
        self.pad.connect("draw", self._draw_pad)
        self.pad.connect("button-press-event", self._press)
        self.pad.connect("motion-notify-event", self._motion)
        self.pad.connect("button-release-event", self._release)
        fr = Gtk.Frame()
        fr.add(self.pad)
        d.add(fr, expand=True)
        tools = Gtk.Box(spacing=6)
        self.write_b = Gtk.RadioButton.new_with_label(None, "Write")
        self.erase_b = Gtk.RadioButton.new_with_label_from_widget(self.write_b, "Erase")
        for b in (self.write_b, self.erase_b):
            b.set_mode(False)
            tools.pack_start(b, False, False, 0)
        self.erase_b.connect("toggled", lambda b: setattr(self, "erase", b.get_active()))
        undo = Gtk.Button(label="Undo")
        undo.connect("clicked", lambda *_: self._undo())
        clear = Gtk.Button(label="Clear")
        clear.connect("clicked", lambda *_: self._clear())
        tools.pack_start(undo, False, False, 0)
        tools.pack_start(clear, False, False, 0)
        self.alts = Gtk.Box(spacing=2)
        tools.pack_end(self.alts, False, False, 0)
        d.add(tools)
        self.syms = []

    def run(self):
        r = self.d.ask()
        text = self.text
        self.d.done()
        if r == Gtk.ResponseType.OK and text:
            bar = self.win.eqbar
            if bar.ed.active:
                bar.ed.insert_linear(text)
            else:
                bar.new_equation(text)

    # drawing input
    def _press(self, w, ev):
        if ev.button != 1:
            return False
        if self.erase:
            self._erase_at(ev.x, ev.y)
            return True
        self.cur = [(ev.x, ev.y)]
        return True

    def _motion(self, w, ev):
        if self.erase and ev.state & Gdk.ModifierType.BUTTON1_MASK:
            self._erase_at(ev.x, ev.y)
            return True
        if self.cur is not None:
            last = self.cur[-1]
            if math.hypot(ev.x - last[0], ev.y - last[1]) >= 1.5:
                self.cur.append((ev.x, ev.y))
                self.pad.queue_draw()
        return True

    def _release(self, w, ev):
        if self.cur is not None:
            self.strokes.append(self.cur)
            self.cur = None
            self._schedule()
        return True

    def _erase_at(self, x, y):
        for s in list(self.strokes):
            if any(math.hypot(px - x, py - y) < 7 for px, py in s):
                self.strokes.remove(s)
                self._schedule()
                return

    def _undo(self):
        if self.strokes:
            self.strokes.pop()
            self._schedule()

    def _clear(self):
        self.strokes = []
        self._schedule()

    def _schedule(self):
        self.pad.queue_draw()
        if self.timer:
            GLib.source_remove(self.timer)
        self.timer = GLib.timeout_add(250, self._recognise)

    def _recognise(self):
        self.timer = 0
        try:
            self.text, self.syms = recognise(self.strokes)
        except Exception as e:
            print("ink:", e)
            self.text, self.syms = "", []
        self.preview.queue_draw()
        self._show_alts()
        return False

    def _show_alts(self):
        for c in self.alts.get_children():
            self.alts.remove(c)
        last = max(self.syms, key=lambda s: s.x1, default=None) if self.syms else None
        if last is None or not last.alts:
            return
        self.alts.pack_start(Gtk.Label(label="Last symbol:"), False, False, 0)
        for ch in [last.ch] + last.alts[:4]:
            b = Gtk.Button(label=ch)

            def pick(_b, ch=ch, s=last):
                s.alts = [c for c in [s.ch] + s.alts if c != ch]
                s.ch = ch
                unit = _unit(self.strokes)
                self.text = _parse(list(self.syms), unit)
                self.preview.queue_draw()
                self._show_alts()
            b.connect("clicked", pick)
            self.alts.pack_start(b, False, False, 0)
        self.alts.show_all()

    def _draw_pad(self, w, cr):
        cr.set_source_rgb(1, 1, 1)
        cr.paint()
        cr.set_source_rgb(0.85, 0.85, 0.85)
        lab = "Write here"
        if not self.strokes and self.cur is None:
            cr.select_font_face("Sans")
            cr.set_font_size(28)
            ext = cr.text_extents(lab)
            cr.move_to((w.get_allocated_width() - ext.width) / 2,
                       w.get_allocated_height() / 2)
            cr.show_text(lab)
        cr.set_source_rgb(0.1, 0.2, 0.55)
        cr.set_line_width(2.6)
        cr.set_line_cap(1)
        cr.set_line_join(1)
        for s in self.strokes + ([self.cur] if self.cur else []):
            cr.move_to(*s[0])
            if len(s) == 1:
                cr.line_to(s[0][0] + 0.5, s[0][1])
            for p in s[1:]:
                cr.line_to(*p)
            cr.stroke()
        return False

    def _draw_preview(self, w, cr):
        cr.set_source_rgb(1, 1, 1)
        cr.paint()
        if not self.text:
            return False
        try:
            tree = M.from_linear(self.text)
        except Exception:
            tree = M.Seq([M.Atom("text", c) for c in self.text])
        box = R.layout(tree, 30)
        W, H = w.get_allocated_width(), w.get_allocated_height()
        box.place(max(8, (W - box.w) / 2), (H - box.h) / 2 + box.asc)
        cr.set_source_rgb(0, 0, 0)
        box.draw(cr)
        return False


def dialog(win):
    if not templates():
        win.dialogs.message("Handwriting recognition data is missing.")
        return
    InkDialog(win).run()
