"""Charts with the new engine, kept as Word keeps them: a chart part
(c:chartSpace, with the values cached in it) and the workbook holding its
data. A chart is described by a model (type, data, title, legend, axes,
gridlines, labels, colours, style), written to the part whole; a chart made
elsewhere is read into the model when it is first changed."""
import io
import json
import re
import xml.etree.ElementTree as ET
import zipfile
from xml.sax.saxutils import escape

from .. import charts as classic

C = "http://schemas.openxmlformats.org/drawingml/2006/chart"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
EXT_URI = "{5D6B6D2C-6B0E-4F3A-9C0B-F01A0C4A5170}"
FO = "urn:folio:chart"

TYPES = [t[0] for t in classic.TYPES]
HISTOGRAM, WATERFALL, BOX, FUNNEL = classic.HISTOGRAM, classic.WATERFALL, classic.BOX, classic.FUNNEL
SPECIALS = classic.SPECIALS
ACCENTS = ["accent1", "accent2", "accent3", "accent4", "accent5", "accent6"]


def _ed(win):
    return win.engine.ed


class ChartRef:
    """The selected chart: its window and part."""

    def __init__(self, win, part):
        self.win, self.part = win, part

    @property
    def ed(self):
        return _ed(self.win)


def selected(win):
    ed = _ed(win)
    if ed is None:
        return None
    part = ed.selected_chart()
    return ChartRef(win, part) if part else None


# ================================================================ the model
def default_model(type_index=0):
    return {"type": type_index, "data": json.loads(json.dumps(classic.DEFAULT_DATA)),
            "title": "Chart Title", "legend": "bottom", "x_title": None, "y_title": None,
            "axes": [True, True], "grid": [True, False, False, False], "labels": None,
            "data_table": False, "colors": None, "style": 0,
            "hidden": {"series": [], "cats": []}}


def _xml(ref):
    return ref.ed.package_part(ref.part) or ""


def _q(tag):
    p, n = tag.split(":")
    return "{%s}%s" % ({"c": C, "a": A}[p], n)


def _texts(el):
    """The values of a strRef/numRef/strLit/numLit or c:v."""
    if el is None:
        return []
    for x in el:
        tag = x.tag.split("}")[-1]
        if tag in ("strRef", "numRef", "multiLvlStrRef"):
            cache = x.find(_q("c:strCache"))
            if cache is None:
                cache = x.find(_q("c:numCache"))
            if cache is None:
                cache = x.find(_q("c:multiLvlStrCache"))
                if cache is not None:
                    cache = cache.find(_q("c:lvl"))
            return _cache(cache)
        if tag in ("strLit", "numLit"):
            return _cache(x)
        if tag == "v":
            return [x.text or ""]
    return []


def _cache(cache):
    if cache is None:
        return []
    pc = cache.find(_q("c:ptCount"))
    n = int(pc.get("val", "0")) if pc is not None else 0
    out = [""] * n
    for pt in cache.findall(_q("c:pt")):
        i = int(pt.get("idx", "0"))
        v = pt.find(_q("c:v"))
        if i >= len(out):
            out += [""] * (i + 1 - len(out))
        out[i] = v.text if v is not None and v.text else ""
    return out


def _num(t):
    try:
        return float(t)
    except (TypeError, ValueError):
        return 0.0


def _rich(t):
    rich = t.find(_q("c:tx") + "/" + _q("c:rich"))
    if rich is None:
        v = _texts(t.find(_q("c:tx")))
        return " ".join(v) if v else None
    lines = []
    for p in rich.findall(_q("a:p")):
        lines.append("".join((r.findtext(_q("a:t")) or "") for r in p
                             if r.tag in (_q("a:r"), _q("a:fld"))))
    return "\n".join(lines)


def read(xml):
    """The model of a chart part (ours as written, or one made elsewhere)."""
    try:
        root = ET.fromstring(xml.encode() if isinstance(xml, str) else xml)
    except ET.ParseError:
        return default_model()
    if root.tag == "{%s}chartSpace" % "http://schemas.microsoft.com/office/drawing/2014/chartex":
        return _read_ex(root)
    ext = root.find(".//{%s}model" % FO)
    if ext is not None and ext.text:
        try:
            m = json.loads(ext.text)
            base = default_model()
            base.update(m)
            return base
        except ValueError:
            pass
    m = default_model()
    ch = root.find(_q("c:chart"))
    if ch is None:
        return m
    t = ch.find(_q("c:title"))
    if t is not None:
        m["title"] = _rich(t) or "Chart Title"
    else:
        deleted = ch.find(_q("c:autoTitleDeleted"))
        m["title"] = None if deleted is None or deleted.get("val") in ("1", "true") else "Chart Title"
    lg = ch.find(_q("c:legend"))
    if lg is None:
        m["legend"] = "none"
    else:
        pos = lg.find(_q("c:legendPos"))
        m["legend"] = {"r": "right", "t": "top", "l": "left", "b": "bottom", "tr": "right"}.get(
            pos.get("val") if pos is not None else "r", "right")
    pa = ch.find(_q("c:plotArea"))
    plots = [p for p in (pa if pa is not None else []) if p.tag.endswith("Chart")]
    sers = []
    kinds = []
    for p in plots:
        tag = p.tag.split("}")[-1]
        for s in p.findall(_q("c:ser")):
            name = _texts(s.find(_q("c:tx")))
            cats = _texts(s.find(_q("c:cat"))) or _texts(s.find(_q("c:xVal")))
            vals = _texts(s.find(_q("c:val"))) or _texts(s.find(_q("c:yVal")))
            color = None
            fill = s.find(_q("c:spPr") + "/" + _q("a:solidFill") + "/" + _q("a:srgbClr"))
            if fill is None and tag in ("lineChart", "scatterChart", "radarChart"):
                fill = s.find(_q("c:spPr") + "/" + _q("a:ln") + "/" + _q("a:solidFill") + "/" + _q("a:srgbClr"))
            if fill is not None:
                color = int(fill.get("val", "4472C4"), 16)
            sers.append((" ".join(name) if name else "Series %d" % (len(sers) + 1), cats, vals, color))
        kinds.append(p)
    if sers:
        n = max(len(s[2]) for s in sers)
        cats = next((s[1] for s in sers if s[1]), [])
        m["data"] = {"rows": [(cats[i] if i < len(cats) and cats[i] else "Category %d" % (i + 1))
                              for i in range(n)],
                     "cols": [s[0] for s in sers],
                     "values": [[_num(s[2][i]) if i < len(s[2]) else 0.0 for s in sers]
                                for i in range(n)]}
        if all(s[3] is not None for s in sers):
            m["colors"] = [s[3] for s in sers]
    m["type"] = _type_of(kinds)
    # axes, titles, gridlines
    grid = [False, False, False, False]
    for ax in (pa if pa is not None else []):
        tag = ax.tag.split("}")[-1]
        if tag not in ("catAx", "valAx", "dateAx"):
            continue
        pos = (ax.find(_q("c:axPos")).get("val") if ax.find(_q("c:axPos")) is not None else "b")
        vertical = pos in ("l", "r")
        horiz_bars = m["type"] in (2, 10, FUNNEL)
        is_value = tag == "valAx"
        k = 0 if vertical else 1     # gridlines across (horizontal) come from the vertical axis
        if ax.find(_q("c:majorGridlines")) is not None:
            grid[k] = True
        if ax.find(_q("c:minorGridlines")) is not None:
            grid[k + 2] = True
        d = ax.find(_q("c:delete"))
        if d is not None and d.get("val") in ("1", "true"):
            m["axes"][0 if not vertical else 1] = False
        at = ax.find(_q("c:title"))
        if at is not None:
            m["y_title" if vertical else "x_title"] = _rich(at) or ""
        _ = horiz_bars, is_value
    m["grid"] = grid
    lbl = None
    for p in plots:
        for dl in [p.find(_q("c:dLbls"))] + [s.find(_q("c:dLbls")) for s in p.findall(_q("c:ser"))]:
            if dl is None:
                continue
            sv = dl.find(_q("c:showVal"))
            sp = dl.find(_q("c:showPercent"))
            if (sv is not None and sv.get("val") in ("1", "true")) or (sp is not None and sp.get("val") in ("1", "true")):
                pos = dl.find(_q("c:dLblPos"))
                lbl = {"ctr": "center", "inEnd": "inside-end", "inBase": "inside-base",
                       "outEnd": "outside-end"}.get(pos.get("val") if pos is not None else "", "outside-end")
    m["labels"] = lbl
    m["data_table"] = pa is not None and pa.find(_q("c:dTable")) is not None
    return m


def _read_ex(root):
    cx = "{http://schemas.microsoft.com/office/drawing/2014/chartex}"
    ext = root.find(".//{%s}model" % FO)
    if ext is not None and ext.text:
        try:
            m = default_model()
            m.update(json.loads(ext.text))
            return m
        except ValueError:
            pass
    m = default_model(classic.TREEMAP)
    ser = root.find(".//%sseries" % cx)
    if ser is not None and ser.get("layoutId") == "sunburst":
        m["type"] = classic.SUNBURST
    data = root.find(".//%sdata" % cx)
    levels, vals = [], []
    if data is not None:
        for dim in data:
            if dim.tag == cx + "strDim":
                for lv in dim.findall(cx + "lvl"):
                    levels.append({int(p.get("idx", 0)): (p.text or "") for p in lv.findall(cx + "pt")})
            elif dim.tag == cx + "numDim":
                lv = dim.find(cx + "lvl")
                if lv is not None:
                    vals = {int(p.get("idx", 0)): _num(p.text) for p in lv.findall(cx + "pt")}
    levels.reverse()
    n = max(vals) + 1 if vals else 0
    rows = ["/".join(l[i] for l in levels if l.get(i)) for i in range(n)]
    m["data"] = {"rows": rows, "cols": ["Value"], "values": [[vals.get(i, 0.0)] for i in range(n)]}
    t = root.find(".//%stitle//%sv" % (cx, cx))
    m["title"] = t.text if t is not None else None
    lg = root.find(".//%slegend" % cx)
    m["legend"] = "none" if lg is None else {"r": "right", "t": "top", "l": "left", "b": "bottom"}.get(lg.get("pos"), "top")
    return m


def _type_of(plots):
    if not plots:
        return 0
    tags = [p.tag.split("}")[-1] for p in plots]
    p = plots[0]

    def val(el, tag, default=""):
        e = el.find(_q("c:" + tag))
        return e.get("val", default) if e is not None else default
    if len(tags) > 1 and tags[0] == "barChart" and "lineChart" in tags:
        return 13
    t = tags[0]
    if t in ("barChart", "bar3DChart"):
        bar = val(p, "barDir") == "bar"
        g = val(p, "grouping", "clustered")
        if g == "percentStacked":
            return 9
        if g == "stacked":
            return 10 if bar else 1
        return 2 if bar else 0
    if t in ("lineChart", "line3DChart"):
        has_marker = any(val(s.find(_q("c:marker")), "symbol", "auto") != "none"
                         for s in p.findall(_q("c:ser")) if s.find(_q("c:marker")) is not None)
        return 4 if has_marker or val(p, "marker") == "1" else 3
    if t in ("pieChart", "pie3DChart", "ofPieChart"):
        return 5
    if t == "doughnutChart":
        return 6
    if t in ("areaChart", "area3DChart"):
        return 11 if val(p, "grouping") in ("stacked", "percentStacked") else 7
    if t in ("scatterChart", "bubbleChart"):
        return 8
    if t == "radarChart":
        return 12
    if t == "stockChart":
        return BOX
    return 0


# ================================================================ writing
def _col(i):
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def _str_cache(vals):
    return '<c:strCache><c:ptCount val="%d"/>%s</c:strCache>' % (
        len(vals), "".join('<c:pt idx="%d"><c:v>%s</c:v></c:pt>' % (i, escape(str(v)))
                           for i, v in enumerate(vals)))


def _num_cache(vals, fmt="General"):
    return '<c:numCache><c:formatCode>%s</c:formatCode><c:ptCount val="%d"/>%s</c:numCache>' % (
        escape(fmt), len(vals), "".join('<c:pt idx="%d"><c:v>%s</c:v></c:pt>' % (i, _numtext(v))
                                        for i, v in enumerate(vals) if v is not None))


def _numtext(v):
    v = float(v)
    return str(int(v)) if v == int(v) and abs(v) < 1e15 else repr(v)


def _solid(c, alpha=None):
    a = '<a:alpha val="%d"/>' % int(alpha * 1000) if alpha is not None else ""
    if isinstance(c, str):
        return '<a:solidFill><a:schemeClr val="%s">%s</a:schemeClr></a:solidFill>' % (c, a)
    return '<a:solidFill><a:srgbClr val="%06X">%s</a:srgbClr></a:solidFill>' % (c & 0xFFFFFF, a)


def _txpr(size=900, color="595959", bold=False):
    return ('<c:txPr><a:bodyPr/><a:lstStyle/><a:p><a:pPr><a:defRPr sz="%d" b="%d">'
            '<a:solidFill><a:srgbClr val="%s"/></a:solidFill></a:defRPr></a:pPr>'
            '<a:endParaRPr lang="en-US"/></a:p></c:txPr>' % (size, int(bold), color))


def _title(text, size=1400, color="595959", rot=None):
    paras = "".join('<a:p><a:pPr><a:defRPr sz="%d" b="0"><a:solidFill><a:srgbClr val="%s"/>'
                    '</a:solidFill></a:defRPr></a:pPr><a:r><a:rPr lang="en-US" sz="%d"/>'
                    '<a:t>%s</a:t></a:r></a:p>' % (size, color, size, escape(line))
                    for line in (text or "").split("\n"))
    body = '<a:bodyPr rot="%d" vert="horz"/>' % rot if rot is not None else "<a:bodyPr/>"
    return ('<c:title><c:tx><c:rich>%s<a:lstStyle/>%s</c:rich></c:tx><c:overlay val="0"/>'
            '</c:title>' % (body, paras))


def shown_data(m):
    """The data the chart draws: filters applied, special kinds derived."""
    d = m["data"]
    hs = set(m.get("hidden", {}).get("series", []))
    hc = set(m.get("hidden", {}).get("cats", []))
    ci = [i for i, c in enumerate(d["cols"]) if c not in hs] or [0]
    ri = [i for i, r in enumerate(d["rows"]) if r not in hc] or [0]
    d = {"rows": [d["rows"][i] for i in ri], "cols": [d["cols"][i] for i in ci],
         "values": [[d["values"][r][c] if c < len(d["values"][r]) else 0.0 for c in ci] for r in ri]}
    kind = SPECIALS.get(m["type"])
    if kind:
        d = classic._shown(kind, d)
    return d


def _palette(m, i, n=6):
    cols = m.get("colors")
    if cols:
        return cols[i % len(cols)]
    acc = ACCENTS[i % 6]
    return acc


def _ser_sppr(m, kind, i, color):
    style = m.get("style", 0)
    if m["type"] == BOX:
        return '<c:spPr><a:ln w="28575" cap="rnd"><a:noFill/></a:ln></c:spPr>'
    if kind in ("line", "radar", "scatter"):
        line = '<a:ln w="28575" cap="rnd">%s<a:round/></a:ln>' % _solid(color)
        if kind == "scatter" and m["type"] == 8:
            line = "<a:ln w=\"25400\"><a:noFill/></a:ln>"
        return "<c:spPr>%s</c:spPr>" % line
    fill = _solid(color, 60 if style == 4 else None)
    ln = '<a:ln w="12700">%s</a:ln>' % _solid(0xFFFFFF) if style == 3 or kind in ("pie", "doughnut") \
        else "<a:ln><a:noFill/></a:ln>"
    return "<c:spPr>%s%s</c:spPr>" % (fill, ln)


def _dlbls(m, kind, on=None, dark=False):
    where = m.get("labels") if on is None else on
    if not where:
        return ('<c:dLbls><c:showLegendKey val="0"/><c:showVal val="0"/><c:showCatName val="0"/>'
                '<c:showSerName val="0"/><c:showPercent val="0"/><c:showBubbleSize val="0"/></c:dLbls>')
    pos = {"center": "ctr", "inside-end": "inEnd", "inside-base": "inBase",
           "outside-end": "outEnd"}.get(where, "outEnd")
    if kind in ("line", "scatter", "radar", "area"):
        pos = {"ctr": "ctr", "outEnd": "t", "inEnd": "t", "inBase": "b"}[pos] if kind != "area" else None
    if kind in ("pie", "doughnut"):
        pos = {"outEnd": "bestFit", "inBase": "inEnd"}.get(pos, pos) if kind == "pie" else None
    if m["type"] in (1, 9, 10, 11) and pos in ("outEnd", "inBase"):
        pos = "ctr" if pos == "outEnd" else "inBase"
    pct = kind in ("pie", "doughnut")
    return ('<c:dLbls>%s%s<c:showLegendKey val="0"/><c:showVal val="%d"/><c:showCatName val="0"/>'
            '<c:showSerName val="0"/><c:showPercent val="%d"/><c:showBubbleSize val="0"/></c:dLbls>'
            % (_txpr(900, "FFFFFF" if dark else "404040"), '<c:dLblPos val="%s"/>' % pos if pos else "",
               int(not pct), int(pct)))


def _series(m, d, kind, idxs, first=0, dark=False):
    out = []
    nrow = len(d["rows"])
    for k, ci in enumerate(idxs):
        i = first + k
        color = _palette(m, ci)
        col = _col(ci + 1)
        name = '<c:tx><c:strRef><c:f>Sheet1!$%s$1</c:f>%s</c:strRef></c:tx>' % (col, _str_cache([d["cols"][ci]]))
        cats = '<c:strRef><c:f>Sheet1!$A$2:$A$%d</c:f>%s</c:strRef>' % (nrow + 1, _str_cache(d["rows"]))
        vals = '<c:numRef><c:f>Sheet1!$%s$2:$%s$%d</c:f>%s</c:numRef>' % (
            col, col, nrow + 1, _num_cache([row[ci] for row in d["values"]]))
        sp = _ser_sppr(m, kind, ci, color)
        special = SPECIALS.get(m["type"])
        if special in ("waterfall", "funnel") and ci == 0:
            sp = "<c:spPr><a:noFill/><a:ln><a:noFill/></a:ln></c:spPr>"
        elif special == "funnel":
            sp = "<c:spPr>%s</c:spPr>" % _solid(_palette(m, 0))
        elif special == "waterfall":
            sp = "<c:spPr>%s</c:spPr>" % _solid(0x5B9BD5 if ci == 1 else 0xED7D31)
        lbl = _dlbls(m, kind, False if (special in ("waterfall", "funnel") and ci == 0) else None, dark)
        parts = ['<c:ser><c:idx val="%d"/><c:order val="%d"/>' % (i, i), name, sp]
        if kind == "bar":
            parts.append('<c:invertIfNegative val="0"/>')
        if kind in ("line", "radar"):
            parts.append('<c:marker><c:symbol val="%s"/><c:size val="5"/></c:marker>'
                         % ("circle" if m["type"] == 4 else "none"))
        if kind == "scatter":
            parts.append('<c:marker><c:symbol val="circle"/><c:size val="5"/>'
                         '<c:spPr>%s<a:ln w="9525">%s</a:ln></c:spPr></c:marker>' % (_solid(color), _solid(color)))
        if kind in ("pie", "doughnut"):
            for p in range(nrow):
                pc = _palette(m, p)
                parts.append('<c:dPt><c:idx val="%d"/><c:bubble3D val="0"/><c:spPr>%s'
                             '<a:ln w="19050">%s</a:ln></c:spPr></c:dPt>' % (p, _solid(pc), _solid(0xFFFFFF)))
        parts.append(lbl)
        if kind == "scatter":
            try:
                xv = [float(r) for r in d["rows"]]
            except (TypeError, ValueError):
                xv = list(range(1, nrow + 1))
            xs = '<c:numRef><c:f>Sheet1!$A$2:$A$%d</c:f>%s</c:numRef>' % (nrow + 1, _num_cache(xv))
            parts.append("<c:xVal>%s</c:xVal><c:yVal>%s</c:yVal>" % (xs, vals))
            parts.append('<c:smooth val="0"/>')
        else:
            parts.append("<c:cat>%s</c:cat><c:val>%s</c:val>" % (cats, vals))
            if kind == "line":
                parts.append('<c:smooth val="0"/>')
        parts.append("</c:ser>")
        out.append("".join(parts))
    return "".join(out)


def _axes(m, kind, horizontal, dark, ids=("111111111", "222222222")):
    text = "D9D9D9" if dark else "595959"
    grid_c = "595959" if dark else "D9D9D9"
    gl = lambda on, minor=False: ('<c:%sGridlines><c:spPr><a:ln w="9525">%s</a:ln></c:spPr></c:%sGridlines>'
                                  % ("minor" if minor else "major", _solid(int(grid_c, 16)),
                                     "minor" if minor else "major")) if on else ""
    g = m.get("grid", [True, False, False, False])
    xa, ya = m.get("axes", [True, True])
    cat_pos, val_pos = ("l", "b") if horizontal else ("b", "l")
    # horizontal gridlines belong to the vertical axis
    cat_grid = (g[1], g[3]) if not horizontal else (g[0], g[2])
    val_grid = (g[0], g[2]) if not horizontal else (g[1], g[3])
    xt = m.get("x_title")
    yt = m.get("y_title")
    cat_title = (xt if not horizontal else yt)
    val_title = (yt if not horizontal else xt)
    cat_del = not (xa if not horizontal else ya)
    val_del = not (ya if not horizontal else xa)
    if SPECIALS.get(m["type"]) == "funnel":
        val_del = True
    cat_tag = "valAx" if kind == "scatter" else "catAx"
    cat = ('<c:%s><c:axId val="%s"/><c:scaling><c:orientation val="minMax"/></c:scaling>'
           '<c:delete val="%d"/><c:axPos val="%s"/>%s%s%s'
           '<c:numFmt formatCode="General" sourceLinked="1"/><c:majorTickMark val="none"/>'
           '<c:minorTickMark val="none"/><c:tickLblPos val="nextTo"/>'
           '<c:spPr><a:noFill/><a:ln w="9525" cap="flat">%s</a:ln></c:spPr>%s'
           '<c:crossAx val="%s"/><c:crosses val="autoZero"/>%s</c:%s>'
           % (cat_tag, ids[0], int(cat_del), cat_pos, gl(cat_grid[0]), gl(cat_grid[1], True),
              _title(cat_title, 1000, text, -5400000 if cat_pos == "l" else None) if cat_title else "",
              _solid(int(grid_c, 16)), _txpr(900, text), ids[1],
              '<c:crossBetween val="midCat"/>' if kind == "scatter" else
              '<c:auto val="1"/><c:lblAlgn val="ctr"/><c:lblOffset val="100"/><c:noMultiLvlLbl val="0"/>',
              cat_tag))
    val = ('<c:valAx><c:axId val="%s"/><c:scaling><c:orientation val="minMax"/></c:scaling>'
           '<c:delete val="%d"/><c:axPos val="%s"/>%s%s%s'
           '<c:numFmt formatCode="%s" sourceLinked="%d"/><c:majorTickMark val="none"/>'
           '<c:minorTickMark val="none"/><c:tickLblPos val="nextTo"/>'
           '<c:spPr><a:noFill/><a:ln><a:noFill/></a:ln></c:spPr>%s'
           '<c:crossAx val="%s"/><c:crosses val="autoZero"/><c:crossBetween val="%s"/></c:valAx>'
           % (ids[1], int(val_del), val_pos, gl(val_grid[0]), gl(val_grid[1], True),
              _title(val_title, 1000, text, -5400000 if val_pos == "l" else None) if val_title else "",
              "0%" if m["type"] == 9 else "General", int(m["type"] != 9), _txpr(900, text), ids[0],
              "midCat" if kind == "scatter" else "between"))
    return cat + val


def write(m):
    """The chart part for a model."""
    d = shown_data(m)
    t = m["type"]
    style = m.get("style", 0)
    dark = style in (5, 7)
    text = "D9D9D9" if dark else "595959"
    ncol = len(d["cols"])
    allc = list(range(ncol))
    ids = ('<c:axId val="111111111"/><c:axId val="222222222"/>')
    gap = '<c:gapWidth val="%d"/>' % ({"histogram": 0, "funnel": 20, "waterfall": 60}.get(
        SPECIALS.get(t), 50 if style in (2, 7) else 219))
    plot = ""
    kind = "bar"
    horizontal = t in (2, 10, FUNNEL)
    if t in (0, 1, 2, 9, 10, HISTOGRAM, WATERFALL, FUNNEL):
        grouping = {1: "stacked", 10: "stacked", 9: "percentStacked", WATERFALL: "stacked",
                    FUNNEL: "stacked"}.get(t, "clustered")
        overlap = 100 if grouping != "clustered" else -27
        if t == HISTOGRAM:
            overlap = 0
        plot = ('<c:barChart><c:barDir val="%s"/><c:grouping val="%s"/><c:varyColors val="0"/>%s'
                '%s<c:overlap val="%d"/>%s</c:barChart>'
                % ("bar" if horizontal else "col", grouping, _series(m, d, "bar", allc, dark=dark),
                   gap, overlap, ids))
    elif t == 13:
        bars = allc[:-1] or allc
        line = allc[-1:] if ncol > 1 else []
        plot = ('<c:barChart><c:barDir val="col"/><c:grouping val="clustered"/><c:varyColors val="0"/>'
                '%s%s<c:overlap val="-27"/>%s</c:barChart>' % (_series(m, d, "bar", bars, dark=dark), gap, ids))
        if line:
            plot += ('<c:lineChart><c:grouping val="standard"/><c:varyColors val="0"/>%s'
                     '<c:marker val="1"/>%s</c:lineChart>' % (_series(m, d, "line", line, len(bars), dark), ids))
    elif t in (3, 4):
        kind = "line"
        plot = ('<c:lineChart><c:grouping val="standard"/><c:varyColors val="0"/>%s'
                '<c:marker val="1"/>%s</c:lineChart>' % (_series(m, d, "line", allc, dark=dark), ids))
    elif t in (5, 6):
        kind = "pie" if t == 5 else "doughnut"
        one = [0]
        plot = ('<c:%sChart><c:varyColors val="1"/>%s<c:firstSliceAng val="0"/>%s</c:%sChart>'
                % (kind, _series(m, d, kind, one, dark=dark), '<c:holeSize val="75"/>' if t == 6 else "", kind))
    elif t in (7, 11):
        kind = "area"
        plot = ('<c:areaChart><c:grouping val="%s"/><c:varyColors val="0"/>%s%s</c:areaChart>'
                % ("stacked" if t == 11 else "standard", _series(m, d, "area", allc, dark=dark), ids))
    elif t == 8:
        kind = "scatter"
        plot = ('<c:scatterChart><c:scatterStyle val="lineMarker"/><c:varyColors val="0"/>%s%s'
                '</c:scatterChart>' % (_series(m, d, "scatter", allc, dark=dark), ids))
    elif t == 12:
        kind = "radar"
        plot = ('<c:radarChart><c:radarStyle val="marker"/><c:varyColors val="0"/>%s%s</c:radarChart>'
                % (_series(m, d, "radar", allc, dark=dark), ids))
    elif t == BOX:
        kind = "line"
        plot = ('<c:stockChart>%s<c:hiLowLines><c:spPr><a:ln w="9525">%s</a:ln></c:spPr></c:hiLowLines>'
                '<c:upDownBars><c:gapWidth val="150"/><c:upBars><c:spPr>%s<a:ln w="9525">%s</a:ln></c:spPr></c:upBars>'
                '<c:downBars><c:spPr>%s<a:ln w="9525">%s</a:ln></c:spPr></c:downBars></c:upDownBars>%s</c:stockChart>'
                % (_series(m, d, "line", allc, dark=dark), _solid(0x404040), _solid(0x4472C4),
                   _solid(0x2F528F), _solid(0x4472C4), _solid(0x2F528F), ids))
    axes = "" if kind in ("pie", "doughnut") else _axes(m, kind, horizontal, dark)
    dtable = ('<c:dTable><c:showHorzBorder val="1"/><c:showVertBorder val="1"/><c:showOutline val="1"/>'
              '<c:showKeys val="1"/>%s</c:dTable>' % _txpr(900, text)) if m.get("data_table") and axes else ""
    title = m.get("title")
    legend = m.get("legend", "bottom")
    if SPECIALS.get(t) in ("waterfall", "funnel", "box", "histogram"):
        legend = "none" if legend == "bottom" and SPECIALS.get(t) != "waterfall" else legend
    leg = "" if legend == "none" else (
        '<c:legend><c:legendPos val="%s"/>%s<c:overlay val="0"/>%s</c:legend>'
        % ({"right": "r", "top": "t", "left": "l", "bottom": "b"}.get(legend, "b"),
           '<c:legendEntry><c:idx val="0"/><c:delete val="1"/></c:legendEntry>'
           if SPECIALS.get(t) == "waterfall" else "", _txpr(900, text)))
    bg = {5: 0x404040, 7: 0x404040, 6: 0xF2F2F2}.get(style, 0xFFFFFF)
    model = json.dumps(m)
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<c:chartSpace xmlns:c="%s" xmlns:a="%s" xmlns:r="%s">'
            '<c:date1904 val="0"/><c:lang val="en-US"/><c:roundedCorners val="0"/>'
            '<c:chart>%s%s<c:plotArea><c:layout/>%s%s%s<c:spPr><a:noFill/><a:ln><a:noFill/></a:ln></c:spPr>'
            '</c:plotArea>%s<c:plotVisOnly val="1"/><c:dispBlanksAs val="gap"/></c:chart>'
            '<c:spPr>%s<a:ln w="9525" cap="flat">%s</a:ln></c:spPr>%s'
            '<c:externalData r:id="rId1"><c:autoUpdate val="0"/></c:externalData>'
            '<c:extLst><c:ext uri="%s"><fo:model xmlns:fo="%s">%s</fo:model></c:ext></c:extLst>'
            '</c:chartSpace>'
            % (C, A, R, _title(title, 1400, text) if title else "",
               '<c:autoTitleDeleted val="%d"/>' % int(not title), plot, axes, dtable, leg,
               _solid(bg), _solid(0xD9D9D9) if not dark else "<a:noFill/>", _txpr(1000, text),
               EXT_URI, FO, escape(model)))


# ================================================================ treemap, sunburst
CX = "http://schemas.microsoft.com/office/drawing/2014/chartex"
TREEMAP, SUNBURST = classic.TREEMAP, classic.SUNBURST
EX_TYPES = {TREEMAP: "treemap", SUNBURST: "sunburst"}


def _paths(d):
    return [str(r).split("/") for r in d["rows"]]


def write_ex(m):
    """An Office 2016 chart part (cx:chartSpace) for a treemap or sunburst:
    the categories as levels (innermost first, as Word writes them)."""
    d = m["data"]
    paths = _paths(d)
    depth = max((len(p) for p in paths), default=1)
    n = len(paths)
    vals = [row[0] if row else 0 for row in d["values"]]
    lvls = []
    for k in range(depth - 1, -1, -1):
        pts = "".join('<cx:pt idx="%d">%s</cx:pt>' % (i, escape(p[k])) for i, p in enumerate(paths) if k < len(p))
        lvls.append('<cx:lvl ptCount="%d">%s</cx:lvl>' % (n, pts))
    last_col = _col(depth - 1)
    val_col = _col(depth)
    lay = EX_TYPES[m["type"]]
    title = m.get("title")
    legend = m.get("legend", "top")
    leg = "" if legend == "none" else '<cx:legend pos="%s" align="ctr" overlay="0"/>' % (
        {"right": "r", "top": "t", "left": "l", "bottom": "b"}.get(legend, "t"))
    lbl = m.get("labels")
    show_val = lbl not in (None, "center")
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<cx:chartSpace xmlns:a="%s" xmlns:r="%s" xmlns:cx="%s">'
            '<cx:chartData><cx:externalData r:id="rId1" cx:autoUpdate="0"/><cx:data id="0">'
            '<cx:strDim type="cat"><cx:f>Sheet1!$A$2:$%s$%d</cx:f>%s</cx:strDim>'
            '<cx:numDim type="size"><cx:f>Sheet1!$%s$2:$%s$%d</cx:f><cx:lvl ptCount="%d" formatCode="General">%s</cx:lvl></cx:numDim>'
            '</cx:data></cx:chartData><cx:chart>%s<cx:plotArea><cx:plotAreaRegion>'
            '<cx:series layoutId="%s" uniqueId="{00000001-6C1A-4E3D-9B8A-F01A0C4A5170}">'
            '<cx:tx><cx:txData><cx:f>Sheet1!$%s$1</cx:f><cx:v>%s</cx:v></cx:txData></cx:tx>'
            '<cx:dataLabels pos="%s"><cx:visibility seriesName="0" categoryName="1" value="%d"/></cx:dataLabels>'
            '<cx:dataId val="0"/>%s</cx:series></cx:plotAreaRegion></cx:plotArea>%s</cx:chart>'
            '<cx:extLst><cx:ext uri="%s"><fo:model xmlns:fo="%s">%s</fo:model></cx:ext></cx:extLst>'
            '</cx:chartSpace>'
            % (A, R, CX, last_col, n + 1, "".join(lvls), val_col, val_col, n + 1, n,
               "".join('<cx:pt idx="%d">%s</cx:pt>' % (i, _numtext(v)) for i, v in enumerate(vals)),
               ('<cx:title pos="t" align="ctr" overlay="0"><cx:tx><cx:txData><cx:v>%s</cx:v></cx:txData></cx:tx></cx:title>'
                % escape(title)) if title else "",
               lay, val_col, escape(d["cols"][0] if d["cols"] else "Value"),
               "inEnd" if lay == "treemap" else "ctr", int(show_val),
               '<cx:layoutPr><cx:parentLabelLayout val="overlapping"/></cx:layoutPr>' if lay == "treemap" else "",
               leg, EXT_URI, FO, escape(json.dumps(m))))


def workbook_ex(d):
    """The workbook for a treemap / sunburst: a column per level, then the sizes."""
    paths = _paths(d)
    depth = max((len(p) for p in paths), default=1)
    cols = ["Level %d" % (k + 1) for k in range(depth)]
    rows = [p + [""] * (depth - len(p)) for p in paths]
    flat = {"rows": [r[0] for r in rows], "cols": cols[1:] + [d["cols"][0] if d["cols"] else "Value"],
            "values": [r[1:] + [v[0] if v else 0] for r, v in zip(rows, d["values"])]}
    return workbook(flat)


def is_ex(ref):
    return (ref.part or "").split("/")[-1].startswith("chartEx")


# ================================================================ the workbook
def workbook(d):
    """An .xlsx holding the data (Sheet1: categories down A, series across)."""
    rows = [[""] + list(d["cols"])] + [[r] + list(v) for r, v in zip(d["rows"], d["values"])]
    strings = []

    def sidx(s):
        if s not in strings:
            strings.append(s)
        return strings.index(s)
    xr = []
    for ri, row in enumerate(rows):
        cells = []
        for ci, v in enumerate(row):
            ref = "%s%d" % (_col(ci), ri + 1)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                cells.append('<c r="%s"><v>%s</v></c>' % (ref, _numtext(v)))
            elif v != "":
                cells.append('<c r="%s" t="s"><v>%d</v></c>' % (ref, sidx(str(v))))
        xr.append('<row r="%d">%s</row>' % (ri + 1, "".join(cells)))
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    rns = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
    files = {
        "[Content_Types].xml": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>'
        '</Types>',
        "_rels/.rels": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        '</Relationships>',
        "xl/workbook.xml": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook %s %s><sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>' % (ns, rns),
        "xl/_rels/workbook.xml.rels": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings" Target="sharedStrings.xml"/>'
        '</Relationships>',
        "xl/worksheets/sheet1.xml": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet %s><sheetData>%s</sheetData></worksheet>' % (ns, "".join(xr)),
    }
    files["xl/sharedStrings.xml"] = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                                     '<sst %s count="%d" uniqueCount="%d">%s</sst>'
                                     % (ns, len(strings), len(strings),
                                        "".join("<si><t xml:space=\"preserve\">%s</t></si>" % escape(s)
                                                for s in strings)))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for k in ("[Content_Types].xml", "_rels/.rels", "xl/workbook.xml", "xl/_rels/workbook.xml.rels",
                  "xl/worksheets/sheet1.xml", "xl/sharedStrings.xml"):
            z.writestr(k, files[k])
    return buf.getvalue()


# ================================================================ operations
def model_of(ref):
    return read(_xml(ref))


def save(ref, m, data_changed=False):
    ed = ref.ed
    ex = m["type"] in EX_TYPES
    if ex != is_ex(ref):
        return _replace(ref, m)
    ed.begin_group("Chart")
    try:
        ed.set_chart_xml(ref.part, write_ex(m) if ex else write(m))
        if data_changed:
            ed.set_chart_workbook(ref.part, workbook_ex(m["data"]) if ex else workbook(m["data"]))
    finally:
        ed.end_group()
    ref.win.engine.view.after_edit()


def _replace(ref, m):
    """A chart of the other family (treemap / sunburst or not) in the old one's place."""
    ed = ref.ed
    o = ed.selected_object()
    if o is None:
        return
    ed.begin_group("Change Chart Type")
    try:
        ed.object_delete()
        ed.select_nodes(o["para"], o["off"], o["para"], o["off"])
        part = _insert_model(ref.win, m, o["w"], o["h"])
    finally:
        ed.end_group()
    ref.part = part
    ref.win.engine.view.after_edit()


def _insert_model(win, m, w=432.0, h=252.0):
    ed = _ed(win)
    if m["type"] in EX_TYPES:
        return ed.insert_chart(write_ex(m), workbook_ex(m["data"]), w, h, True)
    return ed.insert_chart(write(m), workbook(m["data"]), w, h)


def insert(win, type_index=0, data=None):
    ed = _ed(win)
    m = default_model(type_index)
    if data:
        m["data"] = data
    if type_index in EX_TYPES and not data:
        m["data"] = json.loads(json.dumps(__import__("folio.imagecharts", fromlist=["x"]).DEFAULT))
        m["legend"] = "top" if type_index == TREEMAP else "none"
    if type_index in SPECIALS and not data:
        m["data"] = _special_default(type_index, m["data"])
    if type_index in (5, 6):
        m["legend"] = "bottom"
    if SPECIALS.get(type_index) in ("histogram", "box", "funnel"):
        m["legend"] = "none"
    part = _insert_model(win, m)
    win.engine.view.after_edit()
    try:
        win.update_object_tabs()
    except Exception:
        pass
    return ChartRef(win, part) if part else None


def _special_default(index, d):
    kind = SPECIALS[index]
    if kind == "box":
        return {"rows": ["%d" % (i + 1) for i in range(8)], "cols": ["Series 1", "Series 2", "Series 3"],
                "values": [[12, 18, 7], [15, 21, 9], [19, 25, 14], [22, 24, 16],
                           [25, 29, 18], [28, 33, 21], [34, 35, 25], [41, 38, 30]]}
    if kind == "funnel":
        return {"rows": ["Prospects", "Qualified", "Proposals", "Negotiation", "Closed"],
                "cols": ["Value"], "values": [[500], [425], [200], [150], [100]]}
    if kind == "histogram":
        return {"rows": ["%d" % (i + 1) for i in range(12)], "cols": ["Value"],
                "values": [[v] for v in (12, 15, 21, 22, 25, 28, 31, 33, 34, 38, 44, 52)]}
    if kind == "waterfall":
        return {"rows": ["Start", "Sales", "Services", "Costs", "Tax"],
                "cols": ["Amount"], "values": [[100], [60], [25], [-45], [-20]]}
    return d


def get_data(ref):
    return model_of(ref)["data"]


def set_data(ref, d):
    m = model_of(ref)
    m["data"] = {"rows": list(d["rows"]), "cols": list(d["cols"]),
                 "values": [list(map(float, r)) for r in d["values"]]}
    save(ref, m, True)


def _set(ref, **kw):
    m = model_of(ref)
    m.update(kw)
    save(ref, m)


def type_index(ref):
    return model_of(ref)["type"]


def set_type(ref, index):
    m = model_of(ref)
    old = m["type"]
    m["type"] = index
    if (index in EX_TYPES) != (old in EX_TYPES):
        if index in EX_TYPES and not any("/" in str(r) for r in m["data"]["rows"]) and m["data"] == classic.DEFAULT_DATA:
            m["data"] = json.loads(json.dumps(__import__("folio.imagecharts", fromlist=["x"]).DEFAULT))
        elif index in EX_TYPES:
            m["data"] = {"rows": m["data"]["rows"], "cols": m["data"]["cols"][:1],
                         "values": [r[:1] for r in m["data"]["values"]]}
        save(ref, m)
        return
    if index in SPECIALS and old not in SPECIALS and m["data"] == classic.DEFAULT_DATA:
        m["data"] = _special_default(index, m["data"])
        save(ref, m, True)
        return
    save(ref, m)


def title_of(ref):
    return model_of(ref).get("title") or ""


def set_title(ref, text):
    _set(ref, title=text or None)


def set_legend(ref, where):
    _set(ref, legend=where or "none")


def axis_titles(ref):
    m = model_of(ref)
    return m.get("x_title") or "", m.get("y_title") or ""


def set_axis_titles(ref, x=None, y=None):
    m = model_of(ref)
    for k, v in (("x_title", x), ("y_title", y)):
        if v is False:
            m[k] = None
        elif v is True:
            m[k] = m.get(k) or "Axis Title"
        elif v is not None:
            m[k] = v
    save(ref, m)


def set_axes(ref, x=None, y=None):
    m = model_of(ref)
    ax = list(m.get("axes", [True, True]))
    if x is not None:
        ax[0] = bool(x)
    if y is not None:
        ax[1] = bool(y)
    m["axes"] = ax
    save(ref, m)


def gridlines(ref):
    return list(model_of(ref).get("grid", [True, False, False, False]))


def set_gridlines(ref, major_h=None, major_v=None, minor_h=None, minor_v=None):
    m = model_of(ref)
    g = list(m.get("grid", [True, False, False, False]))
    for i, v in enumerate((major_h, major_v, minor_h, minor_v)):
        if v is not None:
            g[i] = bool(v)
    m["grid"] = g
    save(ref, m)


def set_data_labels(ref, where):
    _set(ref, labels=where)


def set_data_table(ref, on):
    _set(ref, data_table=bool(on))


def quick_layout(ref, index):
    name, title, legend, axt, labels, grid = classic.QUICK_LAYOUTS[index]
    m = model_of(ref)
    m["title"] = (m.get("title") or "Chart Title") if title else None
    m["legend"] = legend
    m["x_title"] = (m.get("x_title") or "Axis Title") if axt else None
    m["y_title"] = (m.get("y_title") or "Axis Title") if axt else None
    m["labels"] = labels
    m["grid"] = [bool(grid), False, False, False]
    save(ref, m)


def set_colors(ref, colors):
    _set(ref, colors=list(colors))


def set_chart_style(ref, index):
    m = model_of(ref)
    m["style"] = index
    m["grid"] = [index not in (2, 4), index == 3, False, False]
    m["labels"] = "outside-end" if index in (1, 2, 4) else ("inside-end" if index == 7 else None)
    save(ref, m)


def filters(ref):
    h = model_of(ref).get("hidden") or {}
    return {"series": list(h.get("series", [])), "cats": list(h.get("cats", []))}


def set_filter(ref, hidden_series, hidden_cats):
    _set(ref, hidden={"series": list(hidden_series), "cats": list(hidden_cats)})


def refresh(ref):
    ref.win.engine.view.after_edit()


def special(ref):
    k = SPECIALS.get(type_index(ref))
    return {"kind": k} if k else None


def is_image(ref):
    return False


type_dialog = classic.type_dialog
QUICK_LAYOUTS = classic.QUICK_LAYOUTS


# ================================================================ the data sheet
class DataSheet(classic.DataSheet):
    """The data sheet, on the chart part."""

    def __init__(self, win, ref):
        saved = classic.get_data
        classic.get_data = get_data
        try:
            classic.DataSheet.__init__(self, win, ref)
        finally:
            classic.get_data = saved

    def push(self):
        try:
            set_data(self.obj, self.data)
        except Exception as e:
            print("chart data:", e)

    def _refresh(self):
        self._rt = None
        return False


def edit_chart(win, ref):
    DataSheet(win, ref).present()


def insert_chart_dialog(win):
    idx = classic.type_dialog(win)
    if idx is None:
        return
    ref = insert(win, idx)
    if ref is not None:
        edit_chart(win, ref)
