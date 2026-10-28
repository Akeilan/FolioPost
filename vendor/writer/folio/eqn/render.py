"""Lays out and draws the editable equation tree (eqn.model) with cairo.

layout() returns a Box tree; every slot (Seq) gets a box that knows the x
offset of each caret position, which is what the editor uses for the caret,
mouse clicks and up/down movement.
"""
import gi

gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Pango, PangoCairo  # noqa: E402

import cairo  # noqa: E402

from . import symbols as S  # noqa: E402
from .unicodemath import (Accent, Atom, Brace, Delim, EqArray, Fact, Frac, Func,  # noqa: E402
                          Limit, Matrix, Nary, Prime, Root, Script, Seq)

FAMILY = "Caladea"
SYMBOL_FAMILY = "DejaVu Serif"
BIG_LIMITS = set("∑∏∐⋃⋂⋁⋀")
SCRIPT_SCALE = (1.0, 0.71, 0.55, 0.5)

ACCENT_GLYPH = {"̂": "ˆ", "̌": "ˇ", "̃": "˜", "́": "´", "̀": "`", "̇": "˙", "̈": "¨",
                "⃛": "⋯", "̆": "˘"}

DISPLAY_OP = {"-": "−", "*": "∗", "'": "′"}

_surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 4, 4)
_cr = cairo.Context(_surface)
_cache = {}


def set_family(name):
    global FAMILY
    if name and name != FAMILY:
        FAMILY = name
        _cache.clear()


class Box:
    def __init__(self, w=0.0, asc=0.0, desc=0.0, paint=None):
        self.w, self.asc, self.desc = w, asc, desc
        self.kids = []
        self.paint = paint
        self.seq = None        # slot boxes: the Seq they show
        self.xs = None         # slot boxes: caret x offsets (len(items)+1)
        self.size = 0
        self.node = None
        self.ax = self.ay = 0.0

    def add(self, box, dx, dy):
        self.kids.append((box, dx, dy))
        return box

    def place(self, x, y):
        self.ax, self.ay = x, y
        for b, dx, dy in self.kids:
            b.place(x + dx, y + dy)

    def draw(self, cr):
        if self.paint is not None:
            self.paint(cr, self.ax, self.ay)
        for b, _dx, _dy in self.kids:
            b.draw(cr)

    def walk(self):
        yield self
        for b, _dx, _dy in self.kids:
            yield from b.walk()

    @property
    def h(self):
        return self.asc + self.desc


# ---------------------------------------------------------------- text
def _layout(text, size, italic=False, bold=False, family=None):
    key = (text, round(size, 2), italic, bold, family or FAMILY)
    hit = _cache.get(key)
    if hit is not None:
        return hit
    lay = PangoCairo.create_layout(_cr)
    fd = Pango.FontDescription()
    fd.set_family((family or FAMILY) + "," + SYMBOL_FAMILY + ",OpenSymbol,serif")
    fd.set_absolute_size(size * Pango.SCALE)
    if italic:
        fd.set_style(Pango.Style.ITALIC)
    if bold:
        fd.set_weight(Pango.Weight.BOLD)
    lay.set_font_description(fd)
    lay.set_text(text, -1)
    ink, logical = lay.get_pixel_extents()
    base = lay.get_baseline() / Pango.SCALE
    hit = (lay, logical.width, base, base - ink.y, ink.y + ink.height - base, ink.x,
           ink.width)
    _cache[key] = hit
    return hit


def text_box(text, size, italic=False, color=None, family=None, tight=False):
    lay, w, base, iasc, idesc, _ix, _iw = _layout(text, size, italic, family=family)
    asc = iasc if tight else max(iasc, 0.72 * size)
    desc = idesc if tight else max(idesc, 0.22 * size)

    def paint(cr, x, y):
        cr.save()
        if color:
            cr.set_source_rgb(*color)
        cr.move_to(x, y - base)
        PangoCairo.show_layout(cr, lay)
        cr.restore()
    return Box(w, asc, desc, paint)


def _rule(x0, y0, x1, y1, width):
    def paint(cr, x, y):
        cr.set_line_width(width)
        cr.move_to(x + x0, y + y0)
        cr.line_to(x + x1, y + y1)
        cr.stroke()
    return paint


# ---------------------------------------------------------------- atoms
def _italic(atom):
    if atom.kind != "ident":
        return False
    ch = atom.value
    if ch in S.GREEK_NAMES:
        return ch.islower()
    return ch.isalpha()


def atom_box(atom, size, prev, nxt):
    v = atom.value
    if atom.kind == "placeholder":
        return placeholder(size)
    if atom.kind == "space":
        w = {" ": 0.17, " ": 0.22, " ": 0.28, " ": 1.0,
             " ": 0.28}.get(v, 0.28)
        return Box(w * size, 0.72 * size, 0.22 * size)
    if atom.kind == "op":
        b = text_box(DISPLAY_OP.get(v, v), size)
        rel = v in S.RELATIONS
        leading = prev is None or (isinstance(prev, Atom) and prev.kind == "op")
        if v in ",;":
            lpad, rpad = 0, 0.17
        elif v in "!":
            lpad = rpad = 0
        elif rel:
            lpad = rpad = 0.2
        elif leading:
            lpad = rpad = 0.0
            rpad = 0.05
        else:
            lpad = rpad = 0.1
        out = Box(b.w + (lpad + rpad) * size, b.asc, b.desc)
        out.add(b, lpad * size, 0)
        return out
    if atom.kind == "fn":
        return text_box(v, size)
    if atom.kind == "text":
        return text_box(v, size)
    return text_box(v, size, italic=_italic(atom))


def placeholder(size):
    w, a, d = 0.55 * size, 0.62 * size, 0.08 * size

    def paint(cr, x, y):
        cr.save()
        cr.set_source_rgb(0.45, 0.45, 0.45)
        cr.set_line_width(max(0.8, size / 18.0))
        cr.set_dash([max(1.0, size / 14.0), max(1.0, size / 14.0)])
        cr.rectangle(x + 0.08 * size, y - a, w - 0.16 * size, a + d - 0.02 * size)
        cr.stroke()
        cr.restore()
    return Box(w, max(a, 0.72 * size), max(d, 0.22 * size), paint)


# ---------------------------------------------------------------- layout
class Layout:
    """layout(seq, base_px) -> Box; display=True for display equations."""
    def __init__(self, base_px, display=True, small_fractions=False):
        self.base = base_px
        self.display = display
        self.small_fractions = small_fractions
        self.slot_boxes = []

    def size(self, level):
        return self.base * SCRIPT_SCALE[min(level, len(SCRIPT_SCALE) - 1)]

    def seq(self, seq, level, frac_depth=0):
        size = self.size(level)
        box = Box()
        box.seq = seq
        box.size = size
        xs = [0.0]
        x = 0.0
        items = seq.items
        if not items:
            ph = placeholder(size)
            box.add(ph, 0, 0)
            box.w, box.asc, box.desc = ph.w, ph.asc, ph.desc
            box.xs = [0.0]
            box.empty = True
            self.slot_boxes.append(box)
            return box
        asc, desc = 0.72 * size, 0.22 * size
        prev = None
        for i, it in enumerate(items):
            nxt = items[i + 1] if i + 1 < len(items) else None
            if isinstance(it, Atom):
                b = atom_box(it, size, prev, nxt)
            else:
                b = self.node(it, level, frac_depth)
                if isinstance(prev, Atom) and prev.kind == "fn":
                    x += 0.17 * size
            b.node = it
            box.add(b, x, 0)
            x += b.w
            xs.append(x)
            asc, desc = max(asc, b.asc), max(desc, b.desc)
            prev = it
        box.w, box.asc, box.desc = x, asc, desc
        box.xs = xs
        box.empty = False
        self.slot_boxes.append(box)
        return box

    def node(self, n, level, fd):
        size = self.size(level)
        axis = 0.27 * size
        thick = max(1.0, 0.055 * size)
        if isinstance(n, Frac):
            if n.kind == "linear":
                a = self.seq(n.num, level, fd)
                sl = text_box("/", size)
                b = self.seq(n.den, level, fd)
                box = Box(a.w + sl.w + b.w, max(a.asc, sl.asc, b.asc),
                          max(a.desc, sl.desc, b.desc))
                box.add(a, 0, 0)
                box.add(sl, a.w, 0)
                box.add(b, a.w + sl.w, 0)
                return box
            if n.kind == "skew":
                a = self.seq(n.num, level, fd)
                b = self.seq(n.den, level, fd)
                sl = text_box("\u2215", size * 1.7)
                up = 0.5 * size
                down = 0.42 * size
                box = Box()
                box.add(a, 0, -up)
                box.add(sl, a.w + 0.02 * size, 0.2 * size)
                box.add(b, a.w + sl.w + 0.04 * size, down)
                box.w = a.w + sl.w + b.w + 0.06 * size
                box.asc = max(sl.asc, up + a.asc)
                box.desc = max(sl.desc + 0.2 * size, down + b.desc)
                return box
            # same size as the page draws it (the engine doesn't shrink fractions)
            sub = level
            a = self.seq(n.num, sub, fd + 1)
            b = self.seq(n.den, sub, fd + 1)
            gap = 0.14 * size
            pad = 0.06 * size
            w = max(a.w, b.w) + 2 * pad
            box = Box(w, axis + thick / 2 + gap + a.h, b.h + gap + thick / 2 - axis)
            box.add(a, (w - a.w) / 2, -(axis + thick / 2 + gap + a.desc))
            box.add(b, (w - b.w) / 2, -axis + thick / 2 + gap + b.asc)
            if n.kind != "stack":
                box.paint = _rule(pad * 0.5, -axis, w - pad * 0.5, -axis, thick)
            else:
                return self._wrap_brackets(box, "(", ")", size)
            return box
        if isinstance(n, Script):
            base = self.seq(n.base, level, fd)
            box = Box()
            box.add(base, 0, 0)
            ss = self.size(level + 1)
            subb = self.seq(n.sub, level + 1, fd) if n.sub is not None else None
            supb = self.seq(n.sup, level + 1, fd) if n.sup is not None else None
            up = max(0.42 * size, base.asc - 0.38 * size)
            down = max(0.2 * size, base.desc - 0.05 * size)
            if supb is not None:
                up = max(up, supb.desc + 0.22 * size)
            if subb is not None:
                down = max(down, subb.asc - 0.42 * size)
            if supb is not None and subb is not None:
                # keep the two apart
                gap = (up - supb.desc) - (subb.asc - down)
                if gap < 0.18 * ss:
                    down += 0.18 * ss - gap
            if n.pre:
                w = max(supb.w if supb is not None else 0, subb.w if subb is not None else 0)
                box = Box()
                asc, desc = base.asc, base.desc
                if supb is not None:
                    box.add(supb, w - supb.w, -up)
                    asc = max(asc, up + supb.asc)
                if subb is not None:
                    box.add(subb, w - subb.w, down)
                    desc = max(desc, down + subb.desc)
                x = w + 0.06 * size
                box.add(base, x, 0)
                box.w, box.asc, box.desc = x + base.w, asc, desc
                return box
            x = base.w + 0.04 * size
            w = 0
            asc, desc = base.asc, base.desc
            if supb is not None:
                box.add(supb, x, -up)
                w = max(w, supb.w)
                asc = max(asc, up + supb.asc)
            if subb is not None:
                box.add(subb, x, down)
                w = max(w, subb.w)
                desc = max(desc, down + subb.desc)
            box.w, box.asc, box.desc = x + w + 0.03 * size, asc, desc
            return box
        if isinstance(n, Prime):
            base = self.seq(n.base, level, fd)
            p = text_box("′" * n.count, size)
            box = Box(base.w + p.w, max(base.asc, p.asc), base.desc)
            box.add(base, 0, 0)
            box.add(p, base.w, 0)
            return box
        if isinstance(n, Fact):
            base = self.seq(n.base, level, fd)
            p = text_box("!", size)
            box = Box(base.w + p.w, max(base.asc, p.asc), base.desc)
            box.add(base, 0, 0)
            box.add(p, base.w, 0)
            return box
        if isinstance(n, Root):
            body = self.seq(n.body, level, fd)
            gap = 0.12 * size
            sw = 0.62 * size
            top = body.asc + gap + thick
            bot = body.desc
            idx = None
            ix = 0.0
            if n.index is not None:
                idx = self.seq(n.index, level + 2, fd)
                ix = max(0.0, idx.w - 0.3 * size)
            box = Box(ix + sw + body.w + 0.1 * size, top + thick, bot)
            if idx is not None:
                box.add(idx, 0, -(top * 0.45) - idx.desc)
                box.asc = max(box.asc, top * 0.45 + idx.h)
            box.add(body, ix + sw, 0)
            x0 = ix
            bw = body.w

            def paint(cr, x, y, x0=x0, top=top, bot=bot, bw=bw):
                cr.save()
                cr.set_line_width(thick)
                cr.set_line_join(cairo.LINE_JOIN_ROUND)
                cr.move_to(x + x0, y - 0.3 * size)
                cr.line_to(x + x0 + 0.14 * size, y - 0.38 * size)
                cr.line_to(x + x0 + 0.32 * size, y + bot)
                cr.line_to(x + x0 + sw - 0.04 * size, y - top)
                cr.line_to(x + x0 + sw + bw + 0.06 * size, y - top)
                cr.stroke()
                cr.restore()
            box.paint = paint
            return box
        if isinstance(n, Nary):
            big = size * (2.0 if self.display and level == 0 else 1.35)
            op = text_box(n.op, big, italic=False, tight=True)
            # centre the operator on the axis
            mid = (op.asc - op.desc) / 2
            shift = mid - axis
            body = self.seq(n.body, level, fd)
            subb = self.seq(n.sub, level + 1, fd) if n.sub is not None else None
            supb = self.seq(n.sup, level + 1, fd) if n.sup is not None else None
            box = Box()
            oasc, odesc = op.asc - shift, op.desc + shift
            under = n.op in BIG_LIMITS and self.display
            if under:
                w = max(op.w, subb.w if subb else 0, supb.w if supb else 0)
                box.add(op, (w - op.w) / 2, shift)
                asc, desc = oasc, odesc
                if supb is not None:
                    box.add(supb, (w - supb.w) / 2, -(oasc + 0.1 * size + supb.desc))
                    asc = oasc + 0.1 * size + supb.h
                if subb is not None:
                    box.add(subb, (w - subb.w) / 2, odesc + 0.1 * size + subb.asc)
                    desc = odesc + 0.1 * size + subb.h
                x = w
            else:
                box.add(op, 0, shift)
                asc, desc = oasc, odesc
                sx = op.w + 0.02 * size
                w = 0
                if supb is not None:
                    box.add(supb, sx, -(oasc - supb.asc * 0.6))
                    asc = max(asc, oasc + supb.desc * 0.4)
                    w = supb.w
                if subb is not None:
                    box.add(subb, sx - 0.12 * size * (n.op in "∫∬∭∮"), odesc - subb.desc * 0.2)
                    desc = max(desc, odesc + subb.h * 0.8)
                    w = max(w, subb.w)
                x = sx + w
            x += 0.17 * size
            box.add(body, x, 0)
            box.w = x + body.w
            box.asc, box.desc = max(asc, body.asc), max(desc, body.desc)
            return box
        if isinstance(n, Delim):
            body = self.seq(n.body, level, fd)
            return self._wrap_brackets(body, n.open, n.close, size)
        if isinstance(n, (Matrix, EqArray)):
            rows = n.rows
            cells = [[self.seq(c, level, fd) for c in r] for r in rows]
            ncol = max((len(r) for r in cells), default=0)
            colw = [max((r[j].w for r in cells if j < len(r)), default=0) for j in range(ncol)]
            cgap = (0.8 if isinstance(n, Matrix) else 0.0) * size
            rgap = 0.22 * size
            heights = [(max((c.asc for c in r), default=0.72 * size),
                        max((c.desc for c in r), default=0.22 * size)) for r in cells]
            total = sum(a + d for a, d in heights) + rgap * max(0, len(cells) - 1)
            box = Box()
            y = -(total / 2 + axis)
            for r, (a, d) in zip(cells, heights):
                y += a
                x = 0
                for j, c in enumerate(r):
                    if isinstance(n, Matrix):
                        dx = (colw[j] - c.w) / 2
                    else:
                        dx = colw[j] - c.w if j % 2 == 0 else 0
                    box.add(c, x + dx, y)
                    x += colw[j] + cgap
                y += d + rgap
            box.w = sum(colw) + cgap * max(0, ncol - 1)
            box.asc = total / 2 + axis
            box.desc = total / 2 - axis
            return box
        if isinstance(n, Accent):
            body = self.seq(n.body, level, fd)
            gap = 0.06 * size
            box = Box(body.w, body.asc, body.desc)
            box.add(body, 0, 0)
            m = n.mark
            top = body.asc + gap
            if m in ("̅", "̄", "̿"):
                box.paint = _rule(0.04 * size, -top - thick, body.w - 0.04 * size, -top - thick,
                                  thick)
                box.asc = top + 2 * thick
            elif m in ("⃗", "⃑", "⃡"):
                y0 = -top - 0.12 * size

                def paint(cr, x, y, w=body.w, y0=y0):
                    cr.save()
                    cr.set_line_width(thick)
                    cr.move_to(x + 0.05 * size, y + y0)
                    cr.line_to(x + w, y + y0)
                    cr.stroke()
                    cr.move_to(x + w - 0.16 * size, y + y0 - 0.09 * size)
                    cr.line_to(x + w, y + y0)
                    cr.line_to(x + w - 0.16 * size, y + y0 + 0.09 * size)
                    cr.stroke()
                    cr.restore()
                box.paint = paint
                box.asc = top + 0.25 * size
            else:
                g = text_box(ACCENT_GLYPH.get(m, "^"), size * 0.9, tight=True)
                box.add(g, (body.w - g.w) / 2 + 0.06 * size * _slant(n.body),
                        -top - g.desc)
                box.asc = top + g.h
            return box
        if isinstance(n, Func):
            name = self.seq(n.name, level, fd)
            box = Box()
            box.add(name, 0, 0)
            asc, desc = name.asc, name.desc
            fname = "".join(a.value for a in n.name.items if isinstance(a, Atom))
            x = name.w
            if n.sub is not None and fname in S.LIMIT_FUNCTIONS:
                sub = self.seq(n.sub, level + 1, fd)
                w = max(name.w, sub.w)
                box.kids = []
                box.add(name, (w - name.w) / 2, 0)
                box.add(sub, (w - sub.w) / 2, name.desc + 0.05 * size + sub.asc)
                desc = name.desc + 0.05 * size + sub.h
                x = w
                if n.sup is not None:
                    sup = self.seq(n.sup, level + 1, fd)
                    box.add(sup, x, -0.42 * size)
                    asc = max(asc, 0.42 * size + sup.asc)
                    x += sup.w
            else:
                sw = 0
                if n.sup is not None:
                    sup = self.seq(n.sup, level + 1, fd)
                    box.add(sup, x, -0.42 * size)
                    asc = max(asc, 0.42 * size + sup.asc)
                    sw = sup.w
                if n.sub is not None:
                    sub = self.seq(n.sub, level + 1, fd)
                    box.add(sub, x, 0.2 * size)
                    desc = max(desc, 0.2 * size + sub.desc)
                    sw = max(sw, sub.w)
                x += sw
            x += 0.17 * size
            arg = self.seq(n.arg, level, fd)
            box.add(arg, x, 0)
            box.w = x + arg.w
            box.asc, box.desc = max(asc, arg.asc), max(desc, arg.desc)
            return box
        if isinstance(n, Limit):
            base = self.seq(n.base, level, fd)
            lab = self.seq(n.label, level + 1, fd)
            w = max(base.w, lab.w)
            box = Box(w, base.asc, base.desc)
            box.add(base, (w - base.w) / 2, 0)
            if n.above:
                box.add(lab, (w - lab.w) / 2, -(base.asc + 0.04 * size + lab.desc))
                box.asc = base.asc + 0.04 * size + lab.h
            else:
                box.add(lab, (w - lab.w) / 2, base.desc + 0.04 * size + lab.asc)
                box.desc = base.desc + 0.04 * size + lab.h
            return box
        if isinstance(n, Brace):
            body = self.seq(n.body, level, fd)
            m = n.mark
            box = Box(body.w, body.asc, body.desc)
            box.add(body, 0, 0)
            if m in ("¯", "▁"):
                yy = -(body.asc + thick) if m == "¯" else body.desc + thick
                box.paint = _rule(0, yy, body.w, yy, thick)
                if m == "¯":
                    box.asc += 2 * thick
                else:
                    box.desc += 2 * thick
                return box
            if m in ("□", "▭"):
                pad = 0.1 * size
                box = Box(body.w + 2 * pad, body.asc + pad, body.desc + pad)
                box.add(body, pad, 0)

                def paint(cr, x, y, bw=body.w, a=body.asc, d=body.desc):
                    cr.set_line_width(thick)
                    cr.rectangle(x + thick / 2, y - a - pad + thick / 2, bw + 2 * pad - thick,
                                 a + d + 2 * pad - thick)
                    cr.stroke()
                box.paint = paint
                return box
            over = m in "⏞⏜"
            bh = 0.28 * size
            yy = -(body.asc + 0.06 * size) if over else body.desc + 0.06 * size

            def paint(cr, x, y, bw=body.w, yy=yy, over=over, curly=m in "⏞⏟"):
                s = -1 if over else 1
                cr.save()
                cr.set_line_width(thick)
                cr.move_to(x, y + yy)
                if curly:
                    cr.curve_to(x, y + yy + s * bh * 0.6, x + bw * 0.1, y + yy + s * bh * 0.5,
                                x + bw * 0.45, y + yy + s * bh * 0.5)
                    cr.line_to(x + bw / 2, y + yy + s * bh)
                    cr.line_to(x + bw * 0.55, y + yy + s * bh * 0.5)
                    cr.curve_to(x + bw * 0.9, y + yy + s * bh * 0.5, x + bw,
                                y + yy + s * bh * 0.6, x + bw, y + yy)
                else:
                    cr.curve_to(x + bw * 0.2, y + yy + s * bh, x + bw * 0.8, y + yy + s * bh,
                                x + bw, y + yy)
                cr.stroke()
                cr.restore()
            box.paint = paint
            if over:
                box.asc += bh + 0.08 * size
            else:
                box.desc += bh + 0.08 * size
            if n.label is not None:
                lab = self.seq(n.label, level + 1, fd)
                lx = (body.w - lab.w) / 2
                if over:
                    box.add(lab, lx, -(box.asc + lab.desc))
                    box.asc += lab.h
                else:
                    box.add(lab, lx, box.desc + lab.asc)
                    box.desc += lab.h
                box.w = max(box.w, lab.w)
            return box
        return text_box("?", size)

    def _wrap_brackets(self, body, open_, close, size):
        axis = 0.27 * size
        need = max(body.asc - axis, body.desc + axis) * 2
        box = Box()
        x = 0.0
        asc, desc = body.asc, body.desc
        parts = []
        for ch in (open_, close):
            if ch in ("", "├", "┤"):
                parts.append(None)
                continue
            parts.append(_bracket(ch, need, size, axis))
        lb, rb = parts
        if lb is not None:
            box.add(lb, x, 0)
            x += lb.w
            asc, desc = max(asc, lb.asc), max(desc, lb.desc)
        box.add(body, x, 0)
        x += body.w
        if rb is not None:
            box.add(rb, x, 0)
            x += rb.w
            asc, desc = max(asc, rb.asc), max(desc, rb.desc)
        box.w, box.asc, box.desc = x, asc, desc
        return box


def _slant(seq):
    it = seq.items[0] if seq.items else None
    return 1 if isinstance(it, Atom) and _italic(it) else 0


def _bracket(ch, need, size, axis):
    """A bracket tall enough for `need` (total height), centred on the axis."""
    lay, w, base, iasc, idesc, ix, iw = _layout(ch, size, family=FAMILY)
    ih = iasc + idesc
    scale = max(1.0, need / max(1.0, ih) * 1.04)
    if scale <= 1.15:
        b = text_box(ch, size)
        return b
    # stretch vertically around the glyph's own centre
    gmid = (iasc - idesc) / 2
    hw = w * min(1.5, 1 + (scale - 1) * 0.12)

    def paint(cr, x, y):
        cr.save()
        cr.translate(x + (hw - w) / 2, y - axis)
        cr.scale(1.0, scale)
        cr.move_to(0, -base + gmid)
        PangoCairo.show_layout(cr, lay)
        cr.restore()
    half = ih * scale / 2
    return Box(hw, axis + half, half - axis, paint)


def layout(seq, base_px, display=True, small_fractions=False):
    L = Layout(base_px, display, small_fractions)
    box = L.seq(seq, 0)
    box.slots = L.slot_boxes
    return box
