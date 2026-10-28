"""Charts: insert a chart object, edit its data in a small sheet window,
change its type, title and legend."""
from gi.repository import Gdk, GLib, Gtk

from . import bridge, docapi

CHART_CLSID = "12DCAE26-281F-416F-A234-C3086127382E"

TYPES = [
    # (label, diagram service, extra properties)
    ("Clustered Column", "com.sun.star.chart.BarDiagram", {"Vertical": False}),
    ("Stacked Column", "com.sun.star.chart.BarDiagram", {"Vertical": False, "Stacked": True}),
    ("Clustered Bar", "com.sun.star.chart.BarDiagram", {"Vertical": True}),
    ("Line", "com.sun.star.chart.LineDiagram", {}),
    ("Line with Markers", "com.sun.star.chart.LineDiagram", {"SymbolType": -3}),
    ("Pie", "com.sun.star.chart.PieDiagram", {}),
    ("Doughnut", "com.sun.star.chart.DonutDiagram", {}),
    ("Area", "com.sun.star.chart.AreaDiagram", {}),
    ("Scatter", "com.sun.star.chart.XYDiagram", {"Lines": False}),
    ("100% Stacked Column", "com.sun.star.chart.BarDiagram", {"Vertical": False,
                                                              "Percent": True}),
    ("Stacked Bar", "com.sun.star.chart.BarDiagram", {"Vertical": True, "Stacked": True}),
    ("Stacked Area", "com.sun.star.chart.AreaDiagram", {"Stacked": True}),
    ("Radar", "com.sun.star.chart.NetDiagram", {}),
    ("Combo: Clustered Column - Line", "com.sun.star.chart.BarDiagram",
     {"Vertical": False, "NumberOfLines": 1}),
    ("Histogram", "com.sun.star.chart.BarDiagram", {"Vertical": False}),
    ("Waterfall", "com.sun.star.chart.BarDiagram", {"Vertical": False, "Stacked": True}),
    ("Box & Whisker", "com.sun.star.chart.StockDiagram", {"UpDown": True, "Volume": False}),
    ("Funnel", "com.sun.star.chart.BarDiagram", {"Vertical": True, "Stacked": True}),
    ("Treemap", "image", {}),
    ("Sunburst", "image", {}),
]
HISTOGRAM = 14
WATERFALL = 15
BOX = 16
FUNNEL = 17
TREEMAP = 18
SUNBURST = 19
SPECIALS = {HISTOGRAM: "histogram", WATERFALL: "waterfall", BOX: "box", FUNNEL: "funnel"}
IMAGE_TYPES = {TREEMAP: "treemap", SUNBURST: "sunburst"}

DEFAULT_DATA = {
    "rows": ["Category 1", "Category 2", "Category 3", "Category 4"],
    "cols": ["Series 1", "Series 2", "Series 3"],
    "values": [[4.3, 2.4, 2.0], [2.5, 4.4, 2.0], [3.5, 1.8, 3.0], [4.5, 2.8, 5.0]],
}

PALETTE = [0x4472C4, 0xED7D31, 0xA5A5A5, 0xFFC000, 0x5B9BD5, 0x70AD47, 0x264478, 0x9E480E]


def is_chart(obj):
    try:
        return obj.CLSID.upper() == CHART_CLSID
    except Exception:
        return False


def is_image(obj):
    from . import imagecharts
    return _MODEL[0] is not None and imagecharts.is_image_chart(_MODEL[0], obj)


def selected_chart(m):
    _MODEL[0] = m
    try:
        from . import drawing, imagecharts
        o = drawing.selected_shape(m)
        if o is not None and imagecharts.is_image_chart(m, o):
            return o
    except Exception:
        pass
    obj = docapi.selected_object(m)
    return obj if obj is not None and is_chart(obj) else None


def chart_doc(obj):
    return obj.getEmbeddedObject()


# ---------------------------------------------------------------- special kinds
# Histogram and waterfall charts are drawn from derived data; the data the
# user typed is kept with the document and shown in the data sheet.
def _kind_key(obj):
    try:
        return "ChartKind:" + obj.Name
    except Exception:
        return None


_MODEL = [None]


def special(obj):
    import json
    m = _MODEL[0]
    key = _kind_key(obj)
    if m is None or not key:
        return None
    try:
        return json.loads(docapi._doc_setting(m, key, "") or "null")
    except ValueError:
        return None


def _set_special(obj, info):
    import json
    m = _MODEL[0]
    key = _kind_key(obj)
    if m is not None and key:
        docapi._set_doc_setting(m, key, json.dumps(info) if info else "")


def histogram_data(d, bins=None):
    vals = [row[0] for row in d["values"] if row]
    if not vals:
        return d
    lo, hi = min(vals), max(vals)
    import math
    n = bins or max(1, min(12, int(math.ceil(math.log(len(vals), 2) + 1))))
    width = (hi - lo) / float(n) or 1.0
    counts = [0] * n
    for v in vals:
        counts[min(n - 1, int((v - lo) / width))] += 1
    fmt = lambda v: ("%g" % round(v, 2))   # noqa: E731
    rows = ["[%s, %s%s" % (fmt(lo + i * width), fmt(lo + (i + 1) * width),
                           "]" if i == n - 1 else ")") for i in range(n)]
    return {"rows": rows, "cols": [d["cols"][0] if d["cols"] else "Frequency"],
            "values": [[c] for c in counts]}


def waterfall_data(d):
    base, up, down = [], [], []
    run = 0.0
    for row in d["values"]:
        v = row[0] if row else 0.0
        if v >= 0:
            base.append(run)
            up.append(v)
            down.append(0.0)
        else:
            base.append(run + v)
            up.append(0.0)
            down.append(-v)
        run += v
    return {"rows": list(d["rows"]), "cols": ["", "Increase", "Decrease"],
            "values": [[b, u, dn] for b, u, dn in zip(base, up, down)]}


def _quartiles(vals):
    v = sorted(vals)
    n = len(v)
    if not n:
        return 0, 0, 0, 0, 0

    def q(p):
        k = (n - 1) * p
        f = int(k)
        c = min(n - 1, f + 1)
        return v[f] + (v[c] - v[f]) * (k - f)
    return v[0], q(0.25), q(0.5), q(0.75), v[-1]


def box_data(d):
    """One box per series: Q1 (open), minimum (low), maximum (high), Q3 (close)."""
    rows, vals = [], []
    for ci, name in enumerate(d["cols"]):
        col = [row[ci] for row in d["values"] if ci < len(row)]
        lo, q1, med, q3, hi = _quartiles(col)
        rows.append(name)
        vals.append([q1, lo, hi, q3])
    return {"rows": rows, "cols": ["Q1", "Minimum", "Maximum", "Q3"], "values": vals}


def funnel_data(d):
    vals = [row[0] if row else 0.0 for row in d["values"]]
    top = max(vals or [0])
    rows = list(reversed(d["rows"]))
    out = [[(top - v) / 2.0, v] for v in reversed(vals)]
    return {"rows": rows, "cols": ["", d["cols"][0] if d["cols"] else "Value"], "values": out}


def _shown(kind, d):
    return {"histogram": histogram_data, "waterfall": waterfall_data, "box": box_data,
            "funnel": funnel_data}[kind](d)


def _apply_special(obj, kind, d):
    cd = chart_doc(obj)
    shown = _shown(kind, d)
    data = cd.getData()
    data.setData(tuple(tuple(float(v) for v in row) for row in shown["values"]))
    data.setRowDescriptions(tuple(shown["rows"]))
    data.setColumnDescriptions(tuple(shown["cols"]))
    _colors(cd)
    dg = cd.getDiagram()
    for ax in ("getXAxis", "getYAxis"):
        try:
            a = getattr(dg, ax)()
            a.GapWidth = {"histogram": 0, "funnel": 20}.get(kind, 60)
            a.Overlap = 100 if kind in ("waterfall", "funnel") else 0
        except Exception:
            pass
    if kind == "funnel":
        try:
            p = dg.getDataRowProperties(0)
            p.FillStyle = bridge.enum("com.sun.star.drawing.FillStyle", "NONE")
            p.LineStyle = bridge.enum("com.sun.star.drawing.LineStyle", "NONE")
            p.DataCaption = 0
            q = dg.getDataRowProperties(1)
            q.FillColor = 0x4472C4
            q.DataCaption = 1
            q.LabelPlacement = 1
            dg.HasYAxis = False
            dg.HasYAxisGrid = False
            cd.HasLegend = False
        except Exception as e:
            print("funnel:", e)
    elif kind == "box":
        cd.HasLegend = False
        for i in range(4):
            try:
                p = dg.getDataRowProperties(i)
                p.LineStyle = bridge.enum("com.sun.star.drawing.LineStyle", "SOLID")
                p.LineColor = 0x404040
                p.LineWidth = 26
            except Exception:
                pass
        try:
            ml = dg.getMinMaxLine()
            ml.LineStyle = bridge.enum("com.sun.star.drawing.LineStyle", "SOLID")
            ml.LineColor = 0x404040
            ml.LineWidth = 26
        except Exception as e:
            print("whiskers:", e)
        for bar in ("getUpBar", "getDownBar"):
            try:
                b = getattr(dg, bar)()
                b.FillColor = 0x4472C4
                b.LineColor = 0x2F528F
            except Exception:
                pass
    if kind == "waterfall":
        try:
            p = dg.getDataRowProperties(0)
            p.FillStyle = bridge.enum("com.sun.star.drawing.FillStyle", "NONE")
            p.LineStyle = bridge.enum("com.sun.star.drawing.LineStyle", "NONE")
            p.DataCaption = 0
            dg.getDataRowProperties(1).FillColor = 0x5B9BD5
            dg.getDataRowProperties(2).FillColor = 0xED7D31
        except Exception:
            pass
        _waterfall_labels(dg, shown)
    elif kind == "histogram":
        try:
            p = dg.getDataRowProperties(0)
            p.LineColor = 0xFFFFFF
            p.LineStyle = bridge.enum("com.sun.star.drawing.LineStyle", "SOLID")
        except Exception:
            pass


def _waterfall_labels(dg, shown):
    """Labels only on the visible piece of each bar."""
    try:
        on = dg.getDataRowProperties(1).DataCaption or dg.getDataRowProperties(2).DataCaption
    except Exception:
        return
    for k, row in enumerate(shown["values"]):
        for sidx in (0, 1, 2):
            try:
                dp = dg.getDataPointProperties(k, sidx)
                dp.DataCaption = 1 if (on and sidx and row[sidx]) else 0
            except Exception:
                pass


def _replace_object(old, make):
    """Swap a chart object for another kind of chart at the same place."""
    m = _MODEL[0]
    anchor = old.getAnchor()
    vc = docapi.view_cursor(m)
    vc.gotoRange(anchor.getStart(), False)
    data = get_data(old)
    text = anchor.getText()
    text.removeTextContent(old)
    return make(m, data)


def set_type(obj, index):
    label, service, props = TYPES[index]
    from . import imagecharts
    if index in IMAGE_TYPES:
        if is_image(obj):
            imagecharts.set_kind(_MODEL[0], obj, IMAGE_TYPES[index])
            return obj
        d = get_data(obj)
        rows_ok = any("/" in str(r) for r in d["rows"])
        return _replace_object(obj, lambda m, data: imagecharts.insert(
            m, IMAGE_TYPES[index], data if rows_ok or len(data["rows"]) > 4 else None))
    if is_image(obj):
        def make(m, data):
            new = insert_chart(m, 0)
            set_data(new, data)
            set_type(new, index)
            return new
        return _replace_object(obj, make)
    cd = chart_doc(obj)
    info = special(obj)
    if index in SPECIALS and index not in (HISTOGRAM, WATERFALL):
        kind = SPECIALS[index]
        d = info["data"] if info else get_data(obj)
        if not info and kind == "box" and d == DEFAULT_DATA:
            d = {"rows": ["%d" % (i + 1) for i in range(8)], "cols": ["Series 1", "Series 2",
                                                                     "Series 3"],
                 "values": [[12, 18, 7], [15, 21, 9], [19, 25, 14], [22, 24, 16],
                            [25, 29, 18], [28, 33, 21], [34, 35, 25], [41, 38, 30]]}
        if not info and kind == "funnel" and d == DEFAULT_DATA:
            d = {"rows": ["Prospects", "Qualified", "Proposals", "Negotiation", "Closed"],
                 "cols": ["Value"], "values": [[500], [425], [200], [150], [100]]}
        _set_special(obj, {"kind": kind, "data": d})
    elif index in (HISTOGRAM, WATERFALL):
        kind = "histogram" if index == HISTOGRAM else "waterfall"
        d = info["data"] if info else get_data(obj)
        if not info and kind == "histogram":
            d = {"rows": ["%d" % (i + 1) for i in range(12)], "cols": ["Value"],
                 "values": [[v] for v in (12, 15, 21, 22, 25, 28, 31, 33, 34, 38, 44, 52)]} \
                if d == DEFAULT_DATA or len(d["values"]) < 5 else d
        if not info and kind == "waterfall" and (d == DEFAULT_DATA):
            d = {"rows": ["Start", "Sales", "Services", "Costs", "Tax"],
                 "cols": ["Amount"], "values": [[100], [60], [25], [-45], [-20]]}
        _set_special(obj, {"kind": kind, "data": d})
    elif info:
        _set_special(obj, None)
        _write(obj, info["data"])
    cd = chart_doc(obj)
    cd.setDiagram(cd.createInstance(service))
    d = cd.getDiagram()
    for k, v in props.items():
        try:
            setattr(d, k, v)
        except Exception:
            pass
    _colors(cd)
    for ax in ("getXAxis", "getYAxis"):
        try:
            a = getattr(d, ax)()
            a.GapWidth = 219
            a.Overlap = 100 if props.get("Stacked") or props.get("Percent") else -27
        except Exception:
            pass
    info = special(obj)
    if info:
        _apply_special(obj, info["kind"], info["data"])
        if info["kind"] == "waterfall":
            cd.HasLegend = False


def type_index(obj):
    """Best guess of the TYPES entry the chart currently uses."""
    if is_image(obj):
        from . import imagecharts
        k = (imagecharts.info(_MODEL[0], obj) or {}).get("kind")
        return SUNBURST if k == "sunburst" else TREEMAP
    info = special(obj)
    if info:
        return {v: k for k, v in SPECIALS.items()}.get(info["kind"], 0)
    try:
        d = chart_doc(obj).getDiagram()
        svc = d.getDiagramType()
    except Exception:
        return 0
    for i, (_l, service, props) in enumerate(TYPES):
        if service != svc or i in SPECIALS or i in IMAGE_TYPES:
            continue
        ok = True
        for k, v in props.items():
            try:
                if getattr(d, k) != v:
                    ok = False
            except Exception:
                pass
        if ok:
            return i
    return 0


def refresh(obj):
    """Make the page show the chart's new look (the picture of an embedded
    object is only redrawn when it is activated)."""
    if is_image(obj):
        return
    try:
        xo = obj.getExtendedControlOverEmbeddedObject()
        xo.changeState(2)
        xo.changeState(1)
    except Exception as e:
        print("chart refresh:", e)


def _colors(cd):
    """A clean, modern look: palette colours, white wall, light grid."""
    d = cd.getDiagram()
    try:
        if d.getDiagramType() in ("com.sun.star.chart.PieDiagram",
                                  "com.sun.star.chart.DonutDiagram"):
            for k in range(len(cd.getData().getRowDescriptions())):
                for sidx in range(max(1, len(cd.getData().getColumnDescriptions()))):
                    try:
                        dp = d.getDataPointProperties(k, sidx)
                        dp.FillColor = PALETTE[k % len(PALETTE)]
                        dp.LineColor = 0xFFFFFF
                    except Exception:
                        pass
    except Exception:
        pass
    try:
        n = len(cd.getData().getColumnDescriptions())
    except Exception:
        n = 0
    for i in range(n):
        try:
            p = d.getDataRowProperties(i)
        except Exception:
            continue
        for prop in ("FillColor", "LineColor"):
            try:
                setattr(p, prop, PALETTE[i % len(PALETTE)])
            except Exception:
                pass
        try:
            p.FillStyle = bridge.enum("com.sun.star.drawing.FillStyle", "SOLID")
            if d.getDiagramType() in ("com.sun.star.chart.BarDiagram",
                                      "com.sun.star.chart.PieDiagram",
                                      "com.sun.star.chart.DonutDiagram",
                                      "com.sun.star.chart.AreaDiagram"):
                if not (d.getDiagramType().endswith("BarDiagram") and
                        i >= n - getattr(d, "NumberOfLines", 0)):
                    p.LineStyle = bridge.enum("com.sun.star.drawing.LineStyle", "NONE")
            else:
                p.LineStyle = bridge.enum("com.sun.star.drawing.LineStyle", "SOLID")
        except Exception:
            pass
    for setter in (lambda: setattr(d.getWall(), "FillStyle",
                                   bridge.enum("com.sun.star.drawing.FillStyle", "NONE")),
                   lambda: setattr(d.getWall(), "LineStyle",
                                   bridge.enum("com.sun.star.drawing.LineStyle", "NONE")),
                   lambda: setattr(d.getYMainGrid(), "LineColor", 0xD9D9D9),
                   lambda: setattr(cd.getArea(), "LineStyle",
                                   bridge.enum("com.sun.star.drawing.LineStyle", "NONE")),
                   lambda: setattr(cd.getLegend(), "LineStyle",
                                   bridge.enum("com.sun.star.drawing.LineStyle", "NONE")),
                   lambda: setattr(cd.getLegend(), "FillStyle",
                                   bridge.enum("com.sun.star.drawing.FillStyle", "NONE"))):
        try:
            setter()
        except Exception:
            pass


# ---------------------------------------------------------------- filters
def _full_key(obj):
    return "ChartFull:" + obj.Name


def filters(obj):
    import json
    m = _MODEL[0]
    try:
        f = json.loads(docapi._doc_setting(m, "ChartFilter:" + obj.Name, "") or "{}")
    except ValueError:
        f = {}
    return {"series": f.get("series", []), "cats": f.get("cats", [])}


def _full(obj):
    import json
    try:
        return json.loads(docapi._doc_setting(_MODEL[0], _full_key(obj), "") or "null")
    except ValueError:
        return None


def _filtered(d, f):
    keep_c = [i for i, c in enumerate(d["cols"]) if c not in f["series"]] or [0]
    keep_r = [i for i, r in enumerate(d["rows"]) if r not in f["cats"]] or [0]
    return {"cols": [d["cols"][i] for i in keep_c], "rows": [d["rows"][i] for i in keep_r],
            "values": [[d["values"][r][c] for c in keep_c] for r in keep_r]}


def set_filter(obj, hidden_series, hidden_cats):
    import json
    m = _MODEL[0]
    full = _full(obj) or get_data(obj)
    f = {"series": list(hidden_series), "cats": list(hidden_cats)}
    if f["series"] or f["cats"]:
        docapi._set_doc_setting(m, _full_key(obj), json.dumps(full))
        docapi._set_doc_setting(m, "ChartFilter:" + obj.Name, json.dumps(f))
        _write(obj, _filtered(full, f))
    else:
        docapi._set_doc_setting(m, _full_key(obj), "")
        docapi._set_doc_setting(m, "ChartFilter:" + obj.Name, "")
        _write(obj, full)


def get_data(obj):
    if not is_image(obj) and not special(obj):
        full = _full(obj)
        if full:
            return full
    if is_image(obj):
        from . import imagecharts
        return (imagecharts.info(_MODEL[0], obj) or {}).get("data") or imagecharts.DEFAULT
    info = special(obj)
    if info:
        return info["data"]
    data = chart_doc(obj).getData()
    return {"rows": list(data.getRowDescriptions()), "cols": list(data.getColumnDescriptions()),
            "values": [list(r) for r in data.getData()]}


def set_data(obj, d):
    if not is_image(obj) and not special(obj) and _full(obj):
        import json
        docapi._set_doc_setting(_MODEL[0], _full_key(obj), json.dumps(d))
        _write(obj, _filtered(d, filters(obj)))
        return
    if is_image(obj):
        from . import imagecharts
        imagecharts.set_data(_MODEL[0], obj, d)
        return
    info = special(obj)
    if info:
        info["data"] = d
        _set_special(obj, info)
        _apply_special(obj, info["kind"], d)
        return
    _write(obj, d)


def _write(obj, d):
    data = chart_doc(obj).getData()
    data.setData(tuple(tuple(float(v) for v in row) for row in d["values"]))
    data.setRowDescriptions(tuple(d["rows"]))
    data.setColumnDescriptions(tuple(d["cols"]))
    _colors(chart_doc(obj))


def set_title(obj, text):
    if is_image(obj):
        from . import imagecharts
        imagecharts.set_title(_MODEL[0], obj, text)
        return
    cd = chart_doc(obj)
    cd.HasMainTitle = bool(text)
    if text:
        cd.getTitle().String = text


def title_of(obj):
    if is_image(obj):
        from . import imagecharts
        return (imagecharts.info(_MODEL[0], obj) or {}).get("title", "")
    cd = chart_doc(obj)
    return cd.getTitle().String if cd.HasMainTitle else ""


def set_legend(obj, where):
    cd = chart_doc(obj)
    if where == "none":
        cd.HasLegend = False
        return
    cd.HasLegend = True
    cd.getLegend().Alignment = bridge.enum("com.sun.star.chart.ChartLegendPosition",
                                           {"bottom": "BOTTOM", "right": "RIGHT", "top": "TOP",
                                            "left": "LEFT"}[where])


# ---------------------------------------------------------------- chart elements
def _rows(cd):
    try:
        return len(cd.getData().getColumnDescriptions())
    except Exception:
        return 0


def set_axis_titles(obj, x=None, y=None):
    d = chart_doc(obj).getDiagram()
    if x is not None:
        d.HasXAxisTitle = bool(x)
        if x:
            d.getXAxisTitle().String = x if isinstance(x, str) else "Axis Title"
    if y is not None:
        d.HasYAxisTitle = bool(y)
        if y:
            d.getYAxisTitle().String = y if isinstance(y, str) else "Axis Title"


def axis_titles(obj):
    d = chart_doc(obj).getDiagram()
    try:
        return (d.getXAxisTitle().String if d.HasXAxisTitle else "",
                d.getYAxisTitle().String if d.HasYAxisTitle else "")
    except Exception:
        return "", ""


def set_axes(obj, x=None, y=None):
    d = chart_doc(obj).getDiagram()
    if x is not None:
        d.HasXAxis = x
    if y is not None:
        d.HasYAxis = y


def set_gridlines(obj, major_h=None, major_v=None, minor_h=None, minor_v=None):
    d = chart_doc(obj).getDiagram()
    for prop, v in (("HasYAxisGrid", major_h), ("HasXAxisGrid", major_v),
                    ("HasYAxisHelpGrid", minor_h), ("HasXAxisHelpGrid", minor_v)):
        if v is not None:
            try:
                setattr(d, prop, v)
            except Exception:
                pass
    for g in ("getYMainGrid", "getXMainGrid", "getYHelpGrid", "getXHelpGrid"):
        try:
            getattr(d, g)().LineColor = 0xD9D9D9 if "Main" in g else 0xF0F0F0
        except Exception:
            pass


def gridlines(obj):
    d = chart_doc(obj).getDiagram()
    out = []
    for prop in ("HasYAxisGrid", "HasXAxisGrid", "HasYAxisHelpGrid", "HasXAxisHelpGrid"):
        try:
            out.append(bool(getattr(d, prop)))
        except Exception:
            out.append(False)
    return out


LABEL_PLACES = {"center": 1, "inside-end": 10, "inside-base": 12, "outside-end": 11,
                "above": 2, "below": 6, "left": 4, "right": 8, "best-fit": 0}


def set_data_labels(obj, where):
    """where: None (off) or a key of LABEL_PLACES."""
    cd = chart_doc(obj)
    d = cd.getDiagram()
    caption = 0 if where is None else 1
    for i in range(_rows(cd)):
        try:
            p = d.getDataRowProperties(i)
        except Exception:
            continue
        try:
            p.DataCaption = caption
            if where is not None:
                p.LabelPlacement = LABEL_PLACES.get(where, 0)
        except Exception:
            pass
    info = special(obj)
    if info and info["kind"] == "waterfall":
        _apply_special(obj, "waterfall", info["data"])


def set_data_table(obj, on):
    d = chart_doc(obj).getDiagram()
    try:
        d.DataTableHBorder = on
        d.DataTableVBorder = on
        d.DataTableOutline = on
    except Exception:
        pass


QUICK_LAYOUTS = [
    # (name, title, legend, axis titles, data labels, major gridlines)
    ("Layout 1", True, "right", False, None, True),
    ("Layout 2", True, "top", False, "outside-end", False),
    ("Layout 3", True, "bottom", False, None, True),
    ("Layout 4", False, "bottom", False, "outside-end", False),
    ("Layout 5", True, "none", True, None, True),
    ("Layout 6", True, "none", True, None, True),
    ("Layout 7", False, "right", True, None, True),
    ("Layout 8", True, "none", True, None, False),
    ("Layout 9", True, "right", True, None, True),
    ("Layout 10", True, "right", False, "inside-end", False),
    ("Layout 11", False, "right", False, None, False),
]


def quick_layout(obj, index):
    name, title, legend, axt, labels, grid = QUICK_LAYOUTS[index]
    if title:
        if not chart_doc(obj).HasMainTitle:
            set_title(obj, "Chart Title")
    else:
        set_title(obj, "")
    set_legend(obj, legend)
    set_axis_titles(obj, axt, axt)
    set_data_labels(obj, labels)
    set_gridlines(obj, major_h=grid, major_v=False)


# colour sets for Change Colors
COLORFUL = [
    ("Colorful Palette 1", PALETTE),
    ("Colorful Palette 2", [0xED7D31, 0xFFC000, 0x70AD47, 0x9E480E, 0x997300, 0x43682B]),
    ("Colorful Palette 3", [0xA5A5A5, 0x5B9BD5, 0x264478, 0x636363, 0x255E91, 0x698ED0]),
    ("Colorful Palette 4", [0x70AD47, 0x4472C4, 0xFFC000, 0x43682B, 0x264478, 0x997300]),
]


def _mono(base):
    from .drawing import _tint, _shade
    return [_shade(base, 0.25), base, _tint(base, 0.3), _tint(base, 0.5), _shade(base, 0.5),
            _tint(base, 0.7)]


MONOCHROMATIC = [("Monochromatic Palette %d" % (i + 1), _mono(c)) for i, c in enumerate(
    [0x4472C4, 0xED7D31, 0xA5A5A5, 0xFFC000, 0x5B9BD5, 0x70AD47])]


def set_colors(obj, colors):
    global PALETTE
    cd = chart_doc(obj)
    d = cd.getDiagram()
    info = special(obj)
    start = 1 if info and info["kind"] == "waterfall" else 0
    for i in range(start, _rows(cd)):
        try:
            p = d.getDataRowProperties(i)
            c = colors[(i - start) % len(colors)]
            p.FillColor = c
            p.LineColor = c
        except Exception:
            pass
    try:
        if d.getDiagramType() in ("com.sun.star.chart.PieDiagram",
                                  "com.sun.star.chart.DonutDiagram"):
            n = len(cd.getData().getRowDescriptions())
            for k in range(n):
                d.getDataPointProperties(k, 0).FillColor = colors[k % len(colors)]
    except Exception:
        pass


CHART_STYLES = ["Style 1", "Style 2", "Style 3", "Style 4", "Style 5", "Style 6",
                "Style 7", "Style 8"]


def set_chart_style(obj, index):
    """Chart Styles gallery: background, outlines, labels and gridlines."""
    cd = chart_doc(obj)
    d = cd.getDiagram()
    fs = lambda v: bridge.enum("com.sun.star.drawing.FillStyle", v)   # noqa: E731
    ls = lambda v: bridge.enum("com.sun.star.drawing.LineStyle", v)   # noqa: E731
    dark = index in (5, 7)
    try:
        area = cd.getArea()
        area.FillStyle = fs("SOLID")
        area.FillColor = 0x404040 if dark else (0xF2F2F2 if index == 6 else 0xFFFFFF)
        area.LineStyle = ls("NONE")
    except Exception:
        pass
    text = 0xFFFFFF if dark else 0x595959
    for getter in (lambda: cd.getTitle(), lambda: cd.getLegend(),
                   lambda: d.getXAxis(), lambda: d.getYAxis()):
        try:
            getter().CharColor = text
        except Exception:
            pass
    try:
        d.getXAxis().LineColor = 0xA6A6A6 if not dark else 0x808080
        d.getYAxis().LineStyle = ls("NONE")
    except Exception:
        pass
    set_gridlines(obj, major_h=index not in (2, 4), major_v=index == 3)
    try:
        d.getYMainGrid().LineColor = 0x595959 if dark else 0xD9D9D9
    except Exception:
        pass
    set_data_labels(obj, "outside-end" if index in (1, 2, 4) else
                    ("inside-end" if index == 7 else None))
    for i in range(_rows(cd)):
        try:
            p = d.getDataRowProperties(i)
            if index == 3:
                p.LineStyle = ls("SOLID")
                p.LineColor = 0xFFFFFF
            elif index == 4:
                p.FillTransparence = 40
            else:
                p.FillTransparence = 0
            p.CharColor = text
        except Exception:
            pass
    for ax in ("getXAxis", "getYAxis"):
        try:
            getattr(d, ax)().GapWidth = 50 if index in (2, 7) else 219
        except Exception:
            pass
    info = special(obj)
    if info:
        _apply_special(obj, info["kind"], info["data"])


def insert_chart(m, type_index=0):
    _MODEL[0] = m
    if type_index in IMAGE_TYPES:
        from . import imagecharts
        return imagecharts.insert(m, IMAGE_TYPES[type_index])
    um = m.getUndoManager()
    um.enterUndoContext("Insert Chart")
    try:
        obj = m.createInstance("com.sun.star.text.TextEmbeddedObject")
        obj.CLSID = CHART_CLSID
        obj.AnchorType = bridge.enum("com.sun.star.text.TextContentAnchorType", "AS_CHARACTER")
        vc = docapi.view_cursor(m)
        vc.getText().insertTextContent(vc, obj, False)
        obj.Size = bridge.struct("com.sun.star.awt.Size", Width=15240, Height=8890)  # 6" x 3.5"
        cd = chart_doc(obj)
        if not cd.hasInternalDataProvider():
            cd.createInternalDataProvider(False)
        cd.setDiagram(cd.createInstance("com.sun.star.chart.BarDiagram"))
        _write(obj, DEFAULT_DATA)
        set_type(obj, type_index)
        set_title(obj, "Chart Title")
        if type_index not in (BOX, FUNNEL, WATERFALL):
            set_legend(obj, "bottom")
        return obj
    finally:
        um.leaveUndoContext()


# ---------------------------------------------------------------- dialogs
CATEGORIES = [("Column", [0, 1, 9]), ("Line", [3, 4]), ("Pie", [5, 6]), ("Bar", [2, 10]),
              ("Area", [7, 11]), ("X Y (Scatter)", [8]), ("Radar", [12]),
              ("Treemap", [18]), ("Sunburst", [19]), ("Histogram", [14]),
              ("Box & Whisker", [16]), ("Waterfall", [15]), ("Funnel", [17]),
              ("Combo", [13])]


def draw_type(cr, idx, W, H, big=False):
    """A small picture of a chart type."""
    import math
    cols = [(0.27, 0.45, 0.77), (0.93, 0.49, 0.19), (0.65, 0.65, 0.65)]
    data = [[4.3, 2.4, 2.0], [2.5, 4.4, 2.0], [3.5, 1.8, 3.0], [4.5, 2.8, 5.0]]
    pad = 6 if not big else 24
    x0, y0, w, h = pad, pad, W - 2 * pad, H - 2 * pad
    cr.set_source_rgb(1, 1, 1)
    cr.paint()
    label, service, props = TYPES[idx]
    cr.set_line_width(1.2 if not big else 2.5)

    def axis():
        cr.set_source_rgb(0.75, 0.75, 0.75)
        cr.move_to(x0, y0 + h)
        cr.line_to(x0 + w, y0 + h)
        cr.stroke()
    if idx in (5, 6):
        cx, cy, rad = x0 + w / 2, y0 + h / 2, min(w, h) / 2
        vals = [8.2, 3.2, 1.4, 1.2]
        a = -math.pi / 2
        pal = [(0.27, 0.45, 0.77), (0.93, 0.49, 0.19), (0.65, 0.65, 0.65), (1.0, 0.75, 0.0)]
        for i, v in enumerate(vals):
            b = a + v / sum(vals) * 2 * math.pi
            cr.set_source_rgb(*pal[i])
            cr.move_to(cx, cy)
            cr.arc(cx, cy, rad, a, b)
            cr.close_path()
            cr.fill()
            a = b
        if idx == 6:
            cr.set_source_rgb(1, 1, 1)
            cr.arc(cx, cy, rad * 0.5, 0, 2 * math.pi)
            cr.fill()
        return
    if idx == TREEMAP:
        pal = [(0.27, 0.45, 0.77), (0.93, 0.49, 0.19), (0.65, 0.65, 0.65), (1.0, 0.75, 0.0)]
        rects = [(0, 0, 0.55, 1, 0), (0.55, 0, 0.45, 0.55, 1), (0.55, 0.55, 0.25, 0.45, 2),
                 (0.8, 0.55, 0.2, 0.45, 3)]
        for rx, ry, rw, rh, ci in rects:
            cr.set_source_rgb(*pal[ci])
            cr.rectangle(x0 + rx * w + 1, y0 + ry * h + 1, rw * w - 2, rh * h - 2)
            cr.fill()
        return
    if idx == SUNBURST:
        cx, cy, rad = x0 + w / 2, y0 + h / 2, min(w, h) / 2
        pal = [(0.27, 0.45, 0.77), (0.93, 0.49, 0.19), (0.65, 0.65, 0.65)]
        a = -math.pi / 2
        for i, f in enumerate((0.45, 0.35, 0.2)):
            b = a + f * 2 * math.pi
            for rr, alpha in ((rad, 0.6), (rad * 0.6, 1.0)):
                cr.set_source_rgba(pal[i][0], pal[i][1], pal[i][2], alpha)
                cr.move_to(cx, cy)
                cr.arc(cx, cy, rr, a, b)
                cr.close_path()
                cr.fill()
            a = b
        cr.set_source_rgb(1, 1, 1)
        cr.arc(cx, cy, rad * 0.22, 0, 2 * math.pi)
        cr.fill()
        return
    if idx == BOX:
        cr.set_source_rgb(0.75, 0.75, 0.75)
        cr.move_to(x0, y0 + h)
        cr.line_to(x0 + w, y0 + h)
        cr.stroke()
        for i, (lo, q1, q3, hi) in enumerate(((0.1, 0.3, 0.6, 0.85), (0.2, 0.4, 0.75, 0.95),
                                              (0.05, 0.25, 0.5, 0.7))):
            bx = x0 + (i + 0.5) * w / 3.0
            bw = w / 7.0
            cr.set_source_rgb(0.27, 0.45, 0.77)
            cr.move_to(bx, y0 + h - lo * h)
            cr.line_to(bx, y0 + h - hi * h)
            cr.stroke()
            cr.rectangle(bx - bw / 2, y0 + h - q3 * h, bw, (q3 - q1) * h)
            cr.fill()
        return
    if idx == FUNNEL:
        for i, f in enumerate((1.0, 0.8, 0.55, 0.35)):
            bh = h / 4.0
            bw = w * f
            cr.set_source_rgb(0.27, 0.45, 0.77)
            cr.rectangle(x0 + (w - bw) / 2, y0 + i * bh + 1, bw, bh - 2)
            cr.fill()
        return
    if idx == 12:
        cx, cy, rad = x0 + w / 2, y0 + h / 2, min(w, h) / 2
        cr.set_source_rgb(0.8, 0.8, 0.8)
        for k in range(5):
            a = -math.pi / 2 + k * 2 * math.pi / 5
            cr.move_to(cx, cy)
            cr.line_to(cx + rad * math.cos(a), cy + rad * math.sin(a))
        cr.stroke()
        for si, scale in enumerate(([0.9, 0.6, 0.8, 0.5, 0.7], [0.5, 0.9, 0.4, 0.8, 0.6])):
            cr.set_source_rgb(*cols[si])
            for k, f in enumerate(scale + scale[:1]):
                a = -math.pi / 2 + k * 2 * math.pi / 5
                (cr.move_to if k == 0 else cr.line_to)(cx + rad * f * math.cos(a),
                                                        cy + rad * f * math.sin(a))
            cr.stroke()
        return
    axis()
    vmax = 6.0
    if idx in (0, 1, 9, 2, 10, 13, 14, 15):
        horizontal = idx in (2, 10)
        n = len(data)
        group = (w if not horizontal else h) / float(n)
        for gi, row in enumerate(data):
            if idx == 14:
                vals = [[2, 4, 5, 3][gi]]
            elif idx == 15:
                vals = None
            else:
                vals = row
            if idx == 15:
                steps = [3.0, 1.5, -1.0, 2.0]
                run = sum(steps[:gi])
                v = steps[gi]
                lo, hi = (run, run + v) if v >= 0 else (run + v, run)
                cr.set_source_rgb(*(cols[0] if v >= 0 else cols[1]))
                bw = group * 0.6
                cr.rectangle(x0 + gi * group + (group - bw) / 2, y0 + h - hi / vmax * h, bw,
                             (hi - lo) / vmax * h)
                cr.fill()
                continue
            stacked = props.get("Stacked") or props.get("Percent")
            total = sum(vals)
            k = len(vals) if not stacked and idx != 14 else 1
            gap = 0.0 if idx == 14 else 0.25
            bw = group * (1 - gap) / k
            base = 0.0
            for si, v in enumerate(vals):
                if idx == 13 and si == len(vals) - 1:
                    continue
                if props.get("Percent"):
                    v = v / total * vmax
                cr.set_source_rgb(*cols[si % 3])
                if horizontal:
                    yy = y0 + gi * group + group * gap / 2 + (0 if stacked else si * bw)
                    cr.rectangle(x0 + base / vmax * w * (0.6 if stacked else 1), yy,
                                 v / vmax * w * (0.6 if stacked else 1), bw)
                else:
                    xx = x0 + gi * group + group * gap / 2 + (0 if stacked else si * bw)
                    scale = 0.45 if stacked and not props.get("Percent") else 1
                    if props.get("Percent"):
                        scale = 1
                    cr.rectangle(xx, y0 + h - (base + v) / vmax * h * scale, bw,
                                 v / vmax * h * scale)
                cr.fill()
                if stacked:
                    base += v
            if idx == 14:
                cr.set_source_rgb(1, 1, 1)
                cr.rectangle(x0 + gi * group, y0, 1, h)
                cr.fill()
        if idx == 13:
            cr.set_source_rgb(*cols[2])
            for gi, row in enumerate(data):
                px = x0 + gi * group + group / 2
                py = y0 + h - row[2] / vmax * h
                (cr.move_to if gi == 0 else cr.line_to)(px, py)
            cr.stroke()
        return
    n = len(data)
    step = w / float(n - 1)
    for si in range(3):
        pts = []
        for gi, row in enumerate(data):
            v = row[si]
            if props.get("Stacked"):
                v = sum(row[:si + 1]) * 0.5
            pts.append((x0 + gi * step, y0 + h - v / vmax * h))
        cr.set_source_rgb(*cols[si])
        if idx in (7, 11):
            stack_idx = 2 - si if idx == 7 else si
            pts = []
            for gi, row in enumerate(data):
                v = row[stack_idx] if idx == 7 else sum(row[:si + 1]) * 0.5
                pts.append((x0 + gi * step, y0 + h - v / vmax * h))
            cr.set_source_rgb(*cols[stack_idx if idx == 7 else si])
            cr.move_to(x0, y0 + h)
            for p in pts:
                cr.line_to(*p)
            cr.line_to(x0 + w, y0 + h)
            cr.close_path()
            cr.fill()
            continue
        if idx == 8:
            for px, py in pts:
                cr.arc(px, py, 2 if not big else 5, 0, 6.3)
                cr.fill()
            continue
        cr.move_to(*pts[0])
        for p in pts[1:]:
            cr.line_to(*p)
        cr.stroke()
        if idx == 4:
            for px, py in pts:
                cr.arc(px, py, 1.8 if not big else 4, 0, 6.3)
                cr.fill()


def type_dialog(win, current=0, title="Insert Chart"):
    from .widgets import FDialog
    d = FDialog(win, title)
    state = {"idx": current}
    outer = Gtk.Box(spacing=0)
    cats = Gtk.ListBox()
    cats.set_size_request(170, -1)
    cats.get_style_context().add_class("folio-navlist")
    right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin=10)
    subs = Gtk.Box(spacing=6)
    name = Gtk.Label(xalign=0)
    preview = Gtk.DrawingArea()
    preview.set_size_request(460, 300)
    preview.connect("draw", lambda a, cr: draw_type(cr, state["idx"], a.get_allocated_width(),
                                                    a.get_allocated_height(), big=True))
    frame = Gtk.Frame()
    frame.add(preview)
    right.pack_start(subs, False, False, 0)
    right.pack_start(name, False, False, 0)
    right.pack_start(frame, True, True, 0)

    def choose(idx):
        state["idx"] = idx
        name.set_markup("<b>%s</b>" % TYPES[idx][0])
        for b in subs.get_children():
            b.set_relief(Gtk.ReliefStyle.NORMAL if b.idx == idx else Gtk.ReliefStyle.NONE)
        preview.queue_draw()

    def show_cat(ci):
        for c in subs.get_children():
            subs.remove(c)
        for idx in CATEGORIES[ci][1]:
            b = Gtk.Button()
            b.idx = idx
            b.set_tooltip_text(TYPES[idx][0])
            a = Gtk.DrawingArea()
            a.set_size_request(44, 36)
            a.connect("draw", lambda ar, cr, i=idx: draw_type(
                cr, i, ar.get_allocated_width(), ar.get_allocated_height()))
            b.add(a)
            b.connect("clicked", lambda _b, i=idx: choose(i))
            subs.pack_start(b, False, False, 0)
        subs.show_all()
        choose(state["idx"] if state["idx"] in CATEGORIES[ci][1] else CATEGORIES[ci][1][0])

    cur_cat = 0
    for ci, (label, members) in enumerate(CATEGORIES):
        row = Gtk.Box(spacing=8, margin=4)
        a = Gtk.DrawingArea()
        a.set_size_request(22, 18)
        a.connect("draw", lambda ar, cr, i=members[0]: draw_type(
            cr, i, ar.get_allocated_width(), ar.get_allocated_height()))
        row.pack_start(a, False, False, 0)
        row.pack_start(Gtk.Label(label=label, xalign=0), True, True, 0)
        cats.add(row)
        if current in members:
            cur_cat = ci
    cats.connect("row-selected", lambda lb, row: row is not None and show_cat(row.get_index()))
    outer.pack_start(cats, False, False, 0)
    outer.pack_start(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL), False, False, 0)
    outer.pack_start(right, True, True, 0)
    d.add(outer, expand=True)
    cats.select_row(cats.get_row_at_index(cur_cat))
    show_cat(cur_cat)
    choose(current)
    r = d.ask()
    idx = state["idx"]
    d.done()
    return idx if r == Gtk.ResponseType.OK else None


def insert_chart_dialog(win):
    m = win.engine.model
    if m is None:
        return
    idx = type_dialog(win)
    if idx is None:
        return
    obj = insert_chart(m, idx)
    DataSheet(win, obj).present()


def edit_chart(win, obj):
    DataSheet(win, obj).present()


class DataSheet(Gtk.Window):
    """'Chart in <document>': a small grid to edit the chart's numbers."""
    def __init__(self, win, obj):
        Gtk.Window.__init__(self, title="Chart in %s" % win.doc_name())
        self.set_transient_for(win)
        self.set_default_size(560, 300)
        self.win = win
        self.obj = obj
        self.data = get_data(obj)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_border_width(8)
        self.add(box)
        bar = Gtk.Box(spacing=6)
        self.set_default_size(720, 380)
        for label, cb in (("Add Row", self.add_row), ("Add Series", self.add_col),
                          ("Remove Row", self.del_row), ("Remove Series", self.del_col),
                          ("Switch Row/Column", self.switch), ("Paste", self.paste),
                          ("Import...", self.import_file)):
            b = Gtk.Button(label=label)
            b.connect("clicked", lambda _b, cb=cb: cb())
            bar.pack_start(b, False, False, 0)
        box.pack_start(bar, False, False, 0)
        self.sw = Gtk.ScrolledWindow()
        box.pack_start(self.sw, True, True, 0)
        hint = Gtk.Label(label="Changes appear in the chart as you type.", xalign=0)
        hint.get_style_context().add_class("dim-label")
        box.pack_start(hint, False, False, 0)
        self.build()
        self.show_all()

    def build(self):
        for c in self.sw.get_children():
            self.sw.remove(c)
        ncol = len(self.data["cols"])
        self.store = Gtk.ListStore(*([str] * (ncol + 1)))
        self.store.append([""] + self.data["cols"])
        for name, vals in zip(self.data["rows"], self.data["values"]):
            self.store.append([name] + [("%g" % v) for v in vals])
        tv = Gtk.TreeView(model=self.store)
        tv.set_grid_lines(Gtk.TreeViewGridLines.BOTH)
        for c in range(ncol + 1):
            cell = Gtk.CellRendererText(editable=True)
            cell.connect("edited", self.edited, c)
            col = Gtk.TreeViewColumn("ABCDEFGHIJKLMNOPQRSTUVWXYZ"[c], cell, text=c)
            col.set_min_width(90)
            tv.append_column(col)
        self.tv = tv
        self.sw.add(tv)
        tv.show()

    def edited(self, cell, path, text, col):
        r = int(path)
        self.store[path][col] = text
        if r == 0 and col > 0:
            self.data["cols"][col - 1] = text
        elif col == 0 and r > 0:
            self.data["rows"][r - 1] = text
        elif r > 0:
            try:
                self.data["values"][r - 1][col - 1] = float(text.replace(",", "."))
            except ValueError:
                return
        self.push()

    def push(self):
        try:
            set_data(self.obj, self.data)
        except Exception as e:
            print("chart data:", e)
        if getattr(self, "_rt", None):
            GLib.source_remove(self._rt)
        self._rt = GLib.timeout_add(350, self._refresh)

    def _refresh(self):
        self._rt = None
        refresh(self.obj)
        return False

    def switch(self):
        d = self.data
        self.data = {"rows": list(d["cols"]), "cols": list(d["rows"]),
                     "values": [[d["values"][r][c] for r in range(len(d["rows"]))]
                                for c in range(len(d["cols"]))]}
        self.build()
        self.push()

    def _load_table(self, rows):
        rows = [r for r in rows if any(x.strip() for x in r)]
        if len(rows) < 2 or len(rows[0]) < 2:
            self.win.dialogs.message("The data needs a header row and a label column.")
            return
        cols = [c.strip() or "Series %d" % (i + 1) for i, c in enumerate(rows[0][1:])]
        names, vals = [], []
        for r in rows[1:]:
            names.append(r[0].strip())
            line = []
            for x in r[1:len(cols) + 1]:
                try:
                    line.append(float(x.replace(",", "").strip() or 0))
                except ValueError:
                    line.append(0.0)
            line += [0.0] * (len(cols) - len(line))
            vals.append(line)
        self.data = {"rows": names, "cols": cols, "values": vals}
        self.build()
        self.push()

    def paste(self):
        """Paste a block of cells copied from a spreadsheet (tab separated)."""
        cb = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        text = cb.wait_for_text() or ""
        if not text.strip():
            return
        sep = "\t" if "\t" in text else ","
        self._load_table([line.split(sep) for line in text.splitlines()])

    def import_file(self):
        import csv
        d = Gtk.FileChooserDialog(title="Import Data", transient_for=self,
                                  action=Gtk.FileChooserAction.OPEN)
        d.add_button("Cancel", Gtk.ResponseType.CANCEL)
        d.add_button("Open", Gtk.ResponseType.ACCEPT)
        f = Gtk.FileFilter()
        f.set_name("Text data (*.csv, *.tsv, *.txt)")
        for p in ("*.csv", "*.tsv", "*.txt"):
            f.add_pattern(p)
        d.add_filter(f)
        path = d.get_filename() if d.run() == Gtk.ResponseType.ACCEPT else None
        d.destroy()
        if not path:
            return
        with open(path, newline="", encoding="utf-8", errors="replace") as fh:
            sample = fh.read(4096)
            fh.seek(0)
            try:
                dialect = csv.Sniffer().sniff(sample, ",;\t")
            except csv.Error:
                dialect = csv.excel
            self._load_table(list(csv.reader(fh, dialect)))

    def add_row(self):
        n = len(self.data["rows"]) + 1
        self.data["rows"].append("Category %d" % n)
        self.data["values"].append([0.0] * len(self.data["cols"]))
        self.build()
        self.push()

    def add_col(self):
        n = len(self.data["cols"]) + 1
        self.data["cols"].append("Series %d" % n)
        for row in self.data["values"]:
            row.append(0.0)
        self.build()
        self.push()

    def del_row(self):
        if len(self.data["rows"]) > 1:
            self.data["rows"].pop()
            self.data["values"].pop()
            self.build()
            self.push()

    def del_col(self):
        if len(self.data["cols"]) > 1:
            self.data["cols"].pop()
            for row in self.data["values"]:
                row.pop()
            self.build()
            self.push()


# ---------------------------------------------------------------- format pane
def filter_popover(win, obj):
    return filter_popover_for(win, obj, None)


def filter_popover_for(win, obj, mod):
    """Chart Filters (mod: the module that answers for the chart)."""
    import sys
    mod = mod or sys.modules[__name__]
    d = mod.get_data(obj)
    f = mod.filters(obj)
    pop = Gtk.Popover()
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, margin=10)
    checks = {"series": {}, "cats": {}}
    for kind, title, names in (("series", "SERIES", d["cols"]),
                               ("cats", "CATEGORIES", d["rows"])):
        lab = Gtk.Label(xalign=0)
        lab.set_markup("<b>%s</b>" % title)
        box.pack_start(lab, False, False, 0)
        for n in names:
            cb = Gtk.CheckButton(label=str(n))
            cb.set_active(n not in f[kind])
            checks[kind][n] = cb
            box.pack_start(cb, False, False, 0)
    apply = Gtk.Button(label="Apply")

    def go(*_):
        hs = [n for n, cb in checks["series"].items() if not cb.get_active()]
        hc = [n for n, cb in checks["cats"].items() if not cb.get_active()]
        pop.popdown()
        mod.set_filter(obj, hs, hc)
        mod.refresh(obj)
    apply.connect("clicked", go)
    box.pack_start(apply, False, False, 4)
    box.show_all()
    pop.add(box)
    return pop


ELEMENTS = ["Chart Area", "Plot Area", "Chart Title", "Legend", "Horizontal (Category) Axis",
            "Vertical (Value) Axis"]


def element(obj, name):
    cd = chart_doc(obj)
    d = cd.getDiagram()
    if name == "Chart Area":
        return cd.getArea()
    if name == "Plot Area":
        return d.getWall()
    if name == "Chart Title":
        return cd.getTitle() if cd.HasMainTitle else None
    if name == "Legend":
        return cd.getLegend() if cd.HasLegend else None
    if name.startswith("Horizontal"):
        return d.getXAxis()
    if name.startswith("Vertical"):
        return d.getYAxis()
    if name.startswith("Series "):
        try:
            idx = [c for c in cd.getData().getColumnDescriptions()].index(name[7:].strip('"'))
        except ValueError:
            return None
        return d.getDataRowProperties(idx)
    return None


class ChartFormatPane(Gtk.Box):
    """Format Chart Area / Plot Area / Title / Legend / Axes / Series: fill,
    border and text."""

    def __init__(self, win):
        Gtk.Box.__init__(self, orientation=Gtk.Orientation.VERTICAL, spacing=8)
        from .panes import Pane
        self.win = win

    @staticmethod
    def make(win):
        from .panes import Pane
        from .widgets import color_button, grid, heading

        class P(Pane):
            TITLE = "Format Chart"
            WIDTH = 280

            def __init__(self, w):
                Pane.__init__(self, w)
                self.combo = Gtk.ComboBoxText()
                self.combo.connect("changed", lambda *_: self.load())
                self.pack_start(self.combo, False, False, 0)
                self.pack_start(heading("Fill"), False, False, 0)
                self.fill = color_button(-1, on_change=lambda c: self.set("FillColor", c),
                                         auto_label="No fill")
                self.trans = Gtk.SpinButton.new_with_range(0, 100, 5)
                self.trans.connect("value-changed", lambda s: self.set(
                    "FillTransparence", int(s.get_value())))
                self.pack_start(grid([["Color:", self.fill], ["Transparency (%):", self.trans]]),
                                False, False, 0)
                self.pack_start(heading("Border"), False, False, 0)
                self.line = color_button(-1, on_change=lambda c: self.set("LineColor", c),
                                         auto_label="No line")
                self.width = Gtk.SpinButton.new_with_range(0, 20, 0.25)
                self.width.set_digits(2)
                self.width.connect("value-changed", lambda s: self.set(
                    "LineWidth", int(s.get_value() * 35.28)))
                self.pack_start(grid([["Color:", self.line], ["Width (pt):", self.width]]),
                                False, False, 0)
                self.pack_start(heading("Text"), False, False, 0)
                self.size = Gtk.SpinButton.new_with_range(4, 72, 1)
                self.size.connect("value-changed", lambda s: self.set(
                    "CharHeight", float(s.get_value())))
                self.tcolor = color_button(-1, on_change=lambda c: self.set("CharColor", c))
                self.pack_start(grid([["Size:", self.size], ["Color:", self.tcolor]]),
                                False, False, 0)
                self._busy = False

            def chart(self):
                m = self.win.engine.model
                return selected_chart(m) if m is not None else getattr(self, "obj", None)

            def on_shown(self):
                obj = self.chart()
                if obj is None or is_image(obj):
                    return
                self.obj = obj
                self._busy = True
                self.combo.remove_all()
                names = list(ELEMENTS) + ['Series "%s"' % c for c in
                                          chart_doc(obj).getData().getColumnDescriptions()]
                for n in names:
                    self.combo.append_text(n)
                self.combo.set_active(0)
                self._busy = False
                self.load()

            def load(self):
                obj = getattr(self, "obj", None)
                name = self.combo.get_active_text()
                if obj is None or not name:
                    return
                el = element(obj, name.replace('Series "', "Series ").rstrip('"'))
                self._busy = True
                for w in (self.fill, self.line, self.tcolor):
                    w.color = -1
                for key, w in (("FillColor", self.fill), ("LineColor", self.line),
                               ("CharColor", self.tcolor)):
                    try:
                        w.color = getattr(el, key)
                    except Exception:
                        pass
                    w.queue_draw()
                for key, w, f in (("FillTransparence", self.trans, 1),
                                  ("LineWidth", self.width, 1 / 35.28),
                                  ("CharHeight", self.size, 1)):
                    try:
                        w.set_value(getattr(el, key) * f)
                        w.set_sensitive(True)
                    except Exception:
                        w.set_sensitive(False)
                self._busy = False

            def set(self, key, value):
                if self._busy:
                    return
                obj = getattr(self, "obj", None)
                name = self.combo.get_active_text()
                if obj is None or not name:
                    return
                el = element(obj, name.replace('Series "', "Series ").rstrip('"'))
                if el is None:
                    return
                try:
                    if key == "FillColor":
                        el.FillStyle = bridge.enum("com.sun.star.drawing.FillStyle",
                                                   "NONE" if value is None or value < 0
                                                   else "SOLID")
                        if value is not None and value >= 0:
                            el.FillColor = value
                    elif key == "LineColor":
                        el.LineStyle = bridge.enum("com.sun.star.drawing.LineStyle",
                                                   "NONE" if value is None or value < 0
                                                   else "SOLID")
                        if value is not None and value >= 0:
                            el.LineColor = value
                    else:
                        setattr(el, key, -1 if value is None else value)
                except Exception as e:
                    print("format chart:", e)
                refresh(obj)
        return P
