"""Treemap and sunburst charts, drawn as vector pictures from the chart's data
(the data and options stay with the document, so Edit Data and the Chart
Design tab redraw them)."""
import json
import math
import os
import subprocess
import tempfile

from . import bridge, docapi

PALETTE = [0x4472C4, 0xED7D31, 0xA5A5A5, 0xFFC000, 0x5B9BD5, 0x70AD47, 0x264478, 0x9E480E,
           0x636363, 0x997300]
DEFAULT = {"rows": ["Branch 1/Leaf A", "Branch 1/Leaf B", "Branch 1/Leaf C",
                    "Branch 2/Leaf D", "Branch 2/Leaf E", "Branch 3/Leaf F",
                    "Branch 3/Leaf G", "Branch 3/Leaf H"],
           "cols": ["Value"], "values": [[22], [12], [18], [87], [88], [17], [14], [25]]}
PREFIX = "FolioChart "


def _font(size):
    from PIL import ImageFont
    try:
        path = subprocess.run(["fc-match", "-f", "%{file}", "Carlito"], capture_output=True,
                              text=True, timeout=3).stdout.strip()
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()


def _rgb(c, f=1.0):
    r, g, b = (c >> 16) & 255, (c >> 8) & 255, c & 255
    return (int(r + (255 - r) * (1 - f)), int(g + (255 - g) * (1 - f)), int(b + (255 - b) * (1 - f)))


def _items(d):
    """[(group, label, value)] from 'Group/Label' row names."""
    out = []
    nested = any("/" in str(n) for n in d["rows"])
    for name, row in zip(d["rows"], d["values"]):
        try:
            v = float(row[0]) if row else 0.0
        except (TypeError, ValueError):
            v = 0.0
        if v <= 0:
            continue
        g, _, leaf = str(name).partition("/")
        if nested:
            out.append((g if leaf else "", leaf or g, v))
        else:
            out.append((str(name), str(name), v))      # each item its own colour
    return out


def _squarify(values, x, y, w, h):
    """Rectangles for values (sorted large to small) filling the box."""
    rects = []
    vals = list(values)
    total = float(sum(vals)) or 1.0
    vals = [v * w * h / total for v in vals]

    def worst(row, side):
        s = sum(row)
        return max(max(side * side * r / (s * s), (s * s) / (side * side * r)) for r in row)
    while vals:
        side = min(w, h)
        row = [vals.pop(0)]
        while vals and worst(row + [vals[0]], side) <= worst(row, side):
            row.append(vals.pop(0))
        s = sum(row)
        if w >= h:
            cw = s / h
            yy = y
            for r in row:
                rh = r / cw
                rects.append((x, yy, cw, rh))
                yy += rh
            x += cw
            w -= cw
        else:
            rh = s / w
            xx = x
            for r in row:
                cw = r / rh
                rects.append((xx, y, cw, rh))
                xx += cw
            y += rh
            h -= rh
    return rects


def _hex(c):
    return "#%02x%02x%02x" % c


def _esc(t):
    return (str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def _text_w(t, size):
    return len(str(t)) * size * 0.52


def render(kind, d, title, w=900, h=525, opts=None):
    """The chart as an SVG file (vector: crisp at any zoom and in print).
    opts: colors, legend (none/right/left/top/bottom), labels (bool),
    values (bool), style (0-7)."""
    o = opts or {}
    pal = o.get("colors") or PALETTE
    style = int(o.get("style", 0))
    dark = style in (5, 7)
    bg = (64, 64, 64) if dark else (255, 255, 255)
    fg = (242, 242, 242) if dark else (89, 89, 89)
    gap = {0: 2, 1: 2, 2: 4, 3: 0, 4: 1, 5: 2, 6: 3, 7: 1}.get(style, 2)
    show_labels = o.get("labels", True)
    show_values = o.get("values", style in (1, 4))
    out = ['<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" '
           'viewBox="0 0 %d %d" font-family="Carlito, Calibri, sans-serif">' % (w, h, w, h),
           '<rect width="%d" height="%d" fill="%s"/>' % (w, h, _hex(bg))]
    top, left, right, bottom = 10, 20, w - 20, h - 20
    if title:
        out.append('<text x="%g" y="48" font-size="32" text-anchor="middle" fill="%s">%s'
                   '</text>' % (w / 2, _hex(fg), _esc(title)))
        top = 66
    items = _items(d)
    groups = []
    for g, _l, _v in items:
        if g not in groups:
            groups.append(g)
    nested = any("/" in str(n) for n in d["rows"])
    legend = o.get("legend", "top" if nested and kind == "treemap" else
                   ("right" if kind == "sunburst" and not nested else "none"))
    names = groups if nested else [lab for _g, lab, _v in items]
    if legend in ("top", "bottom") and names:
        y = top + 16 if legend == "top" else bottom - 6
        total_w = sum(_text_w(n, 20) + 36 for n in names)
        x = max(left, (w - total_w) / 2)
        for i, n in enumerate(names):
            c = _rgb(pal[i % len(pal)])
            out.append('<rect x="%g" y="%g" width="14" height="14" fill="%s"/>' % (
                x, y - 12, _hex(c)))
            out.append('<text x="%g" y="%g" font-size="20" fill="%s">%s</text>' % (
                x + 20, y + 1, _hex(fg), _esc(n)))
            x += _text_w(n, 20) + 36
        if legend == "top":
            top += 34
        else:
            bottom -= 34
    elif legend in ("left", "right") and names:
        lw = max(_text_w(n, 20) for n in names) + 40
        x = right - lw + 10 if legend == "right" else left
        y = top + (bottom - top - 30 * len(names)) / 2
        for i, n in enumerate(names):
            c = _rgb(pal[i % len(pal)])
            out.append('<rect x="%g" y="%g" width="14" height="14" fill="%s"/>' % (
                x, y + 30 * i, _hex(c)))
            out.append('<text x="%g" y="%g" font-size="20" fill="%s">%s</text>' % (
                x + 20, y + 30 * i + 13, _hex(fg), _esc(n)))
        if legend == "right":
            right -= lw
        else:
            left += lw

    def label(x, y, lab, v, size=22, anchor="start"):
        lines = []
        if show_labels:
            lines.append(lab)
        if show_values:
            lines.append(("%g" % v))
        for k, t in enumerate(lines):
            out.append('<text x="%g" y="%g" font-size="%d" fill="#ffffff" text-anchor="%s">'
                       '%s</text>' % (x, y + k * (size + 4), size, anchor, _esc(t)))

    if kind == "treemap":
        area = (left, top + 4, right - left, bottom - top - 4)
        gvals = [(g, sum(v for gg, _l, v in items if gg == g)) for g in groups]
        gvals.sort(key=lambda t: -t[1])
        grects = _squarify([v for _g, v in gvals], *area)
        for (g, _gv), (gx, gy, gw, gh) in zip(gvals, grects):
            leaves = sorted([(lab, v) for gg, lab, v in items if gg == g], key=lambda t: -t[1])
            lr = _squarify([v for _l, v in leaves], gx, gy, gw, gh)
            for (lab, v), (lx, ly, lw_, lh) in zip(leaves, lr):
                k = groups.index(g) if nested else names.index(lab)
                col = _rgb(pal[k % len(pal)])
                out.append('<rect x="%g" y="%g" width="%g" height="%g" fill="%s" '
                           'stroke="%s" stroke-width="%d"/>' % (lx, ly, lw_, lh, _hex(col),
                                                                 _hex(bg), gap))
                if lw_ > 60 and lh > 34:
                    label(lx + 8, ly + 26, lab, v)
    else:
        cx, cy = (left + right) / 2, top + (bottom - top) / 2
        r_out = min(right - left, bottom - top) / 2 - 6
        r_mid = r_out * (0.55 if nested else 0.35)
        r_in = r_out * 0.18 if nested else r_mid
        total = sum(v for _g, _l, v in items) or 1.0

        def arc(r0, r1, a0, a1, col):
            if a1 - a0 >= 359.99:
                a1 = a0 + 359.99
            p = []
            for r_, aa in ((r1, a0), (r1, a1)):
                p.append((cx + r_ * math.cos(math.radians(aa)),
                          cy + r_ * math.sin(math.radians(aa))))
            q = [(cx + r0 * math.cos(math.radians(a1)), cy + r0 * math.sin(math.radians(a1))),
                 (cx + r0 * math.cos(math.radians(a0)), cy + r0 * math.sin(math.radians(a0)))]
            large = 1 if a1 - a0 > 180 else 0
            out.append('<path d="M%g %g A%g %g 0 %d 1 %g %g L%g %g A%g %g 0 %d 0 %g %g Z" '
                       'fill="%s" stroke="%s" stroke-width="%d"/>' % (
                           p[0][0], p[0][1], r1, r1, large, p[1][0], p[1][1],
                           q[0][0], q[0][1], r0, r0, large, q[1][0], q[1][1],
                           _hex(col), _hex(bg), gap + 1))
        a = -90.0
        for g in groups:
            gv = sum(v for gg, _l, v in items if gg == g)
            ga = 360.0 * gv / total
            base = pal[groups.index(g) % len(pal)]
            if nested:
                arc(r_in, r_mid, a, a + ga, _rgb(base))
            la = a
            for gg, lab, v in items:
                if gg != g:
                    continue
                sa = 360.0 * v / total
                c = base if nested else pal[names.index(lab) % len(pal)]
                arc(r_mid if nested else r_in, r_out, la, la + sa,
                    _rgb(c, 0.75 if nested else 1.0))
                mid = math.radians(la + sa / 2)
                rr = (r_out + r_mid) / 2
                if sa > 12:
                    label(cx + rr * math.cos(mid), cy + rr * math.sin(mid) + 7, lab, v,
                          20, "middle")
                la += sa
            if nested and g and ga > 12 and show_labels:
                mid = math.radians(a + ga / 2)
                rr = (r_mid + r_in) / 2
                out.append('<text x="%g" y="%g" font-size="20" fill="#ffffff" '
                           'text-anchor="middle">%s</text>' % (
                               cx + rr * math.cos(mid), cy + rr * math.sin(mid) + 7, _esc(g)))
            a += ga
    out.append("</svg>")
    path = tempfile.mktemp(prefix="folio-chart-", suffix=".svg")
    with open(path, "w") as fh:
        fh.write("\n".join(out))
    return path


# ------------------------------------------------------------ storage
def _key(name):
    return "ImageChart:" + name


def info(m, obj):
    try:
        return json.loads(docapi._doc_setting(m, _key(obj.Name), "") or "null")
    except Exception:
        return None


def is_image_chart(m, obj):
    try:
        return obj.supportsService("com.sun.star.text.TextGraphicObject") and \
            obj.Name.startswith(PREFIX) and info(m, obj) is not None
    except Exception:
        return False


def _save(m, obj, data):
    docapi._set_doc_setting(m, _key(obj.Name), json.dumps(data))


def redraw(m, obj):
    from .pictools import load_graphic
    i = info(m, obj)
    if i is None:
        return
    path = render(i["kind"], i["data"], i.get("title", "Chart Title"), opts=i.get("opts"))
    size = obj.Size
    obj.Graphic = load_graphic(path)
    obj.Size = size
    os.remove(path)


def insert(m, kind, data=None, title="Chart Title"):
    from .pictools import load_graphic
    data = data or DEFAULT
    path = render(kind, data, title)
    vc = docapi.view_cursor(m)
    um = m.getUndoManager()
    um.enterUndoContext("Insert Chart")
    try:
        g = m.createInstance("com.sun.star.text.TextGraphicObject")
        g.AnchorType = bridge.enum("com.sun.star.text.TextContentAnchorType", "AS_CHARACTER")
        vc.getText().insertTextContent(vc, g, False)
        g.Graphic = load_graphic(path)
        g.Size = bridge.struct("com.sun.star.awt.Size", Width=15240, Height=8890)
        n = 1
        names = set(m.getGraphicObjects().getElementNames())
        while PREFIX + str(n) in names:
            n += 1
        g.Name = PREFIX + str(n)
        g.Description = "%s chart" % kind.capitalize()
        _save(m, g, {"kind": kind, "data": data, "title": title})
        docapi.controller(m).select(g)
        return g
    finally:
        um.leaveUndoContext()
        os.remove(path)


def set_data(m, obj, data):
    i = info(m, obj) or {"kind": "treemap"}
    i["data"] = data
    _save(m, obj, i)
    redraw(m, obj)


def set_kind(m, obj, kind):
    i = info(m, obj) or {"data": DEFAULT}
    i["kind"] = kind
    _save(m, obj, i)
    redraw(m, obj)


def set_option(m, obj, **kw):
    """Chart Design on a treemap or sunburst: colours, legend, labels,
    style."""
    i = info(m, obj)
    if i is None:
        return
    i.setdefault("opts", {}).update(kw)
    _save(m, obj, i)
    redraw(m, obj)


def set_title(m, obj, title):
    i = info(m, obj)
    if i is not None:
        i["title"] = title
        _save(m, obj, i)
        redraw(m, obj)
