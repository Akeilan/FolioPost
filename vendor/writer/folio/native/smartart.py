"""SmartArt with the new engine: the graphic is a group of shapes (wpg:wgp
with wps:wsp members, each holding its text), as Word draws it when a file
leaves out the diagram parts; what it was made from (layout, lines, colour,
style) is kept as a custom document property so it can be laid out again."""
import json
import math
import re
from xml.sax.saxutils import escape

from .. import insertmore as IM

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
WPS = "http://schemas.microsoft.com/office/word/2010/wordprocessingShape"
WPG = "http://schemas.microsoft.com/office/word/2010/wordprocessingGroup"
PRST = {"rectangle": "rect", "round-rectangle": "roundRect", "right-arrow": "rightArrow",
        "left-arrow": "leftArrow", "ellipse": "ellipse", "isosceles-triangle": "triangle",
        "trapezoid": "trapezoid", "chevron": "chevron", "pentagon": "homePlate", "line": "line",
        "matrix": "rect"}
EMU_PER_MM100 = 360


def _ed(win):
    return win.engine.ed


def _props(win):
    from .docprops import UserProps
    return UserProps(_ed(win))


def _key(name):
    return "SmartArt:" + name


def selected_name(win):
    x = _ed(win).selected_drawing_xml() or ""
    m = re.search(r'<wp:docPr\b[^>]*\bname="([^"]*)"', x)
    return m.group(1) if m else None


def info(win, name=None):
    name = name or selected_name(win)
    if not name or not name.startswith("SmartArt "):
        return None
    try:
        return json.loads(_props(win).getPropertyValue(_key(name)) or "null")
    except Exception:
        return None


def selected(win):
    """The selected SmartArt graphic's name (None: none is selected)."""
    name = selected_name(win)
    return name if info(win, name) is not None else None


def _fill(c, alpha=0):
    a = '<a:alpha val="%d"/>' % ((100 - alpha) * 1000) if alpha else ""
    return '<a:solidFill><a:srgbClr val="%06X">%s</a:srgbClr></a:solidFill>' % (c & 0xFFFFFF, a)


def _member(i, kind, x, y, w, h, fill, text, alpha, style, rtl_flip=False):
    e = lambda v: str(int(round(v * EMU_PER_MM100)))   # noqa: E731
    flip = ' flipH="1"' if w < 0 else ""
    if w < 0:
        x, w = x + w, -w
    flipv = ' flipV="1"' if h < 0 else ""
    if h < 0:
        y, h = y + h, -h
    prst = PRST.get(kind, "rect")
    xfrm = '<a:xfrm%s%s><a:off x="%s" y="%s"/><a:ext cx="%s" cy="%s"/></a:xfrm>' % (flip, flipv, e(x), e(y), e(w), e(h))
    if kind == "line":
        return ('<wps:wsp><wps:cNvPr id="0" name="Connector %d"/><wps:cNvCnPr/><wps:spPr>%s'
                '<a:prstGeom prst="line"><a:avLst/></a:prstGeom><a:ln w="12700">%s</a:ln></wps:spPr>'
                '<wps:bodyPr/></wps:wsp>' % (i, xfrm, _fill(fill)))
    ln = ('<a:ln w="%d">%s</a:ln>' % (int(style.get("lw", 12) * 360 // 1 if style.get("lw") else 12700),
                                     _fill(style.get("line", 0xFFFFFF))))
    eff = ('<a:effectLst><a:outerShdw blurRad="38100" dist="25400" dir="5400000" rotWithShape="0">'
           '<a:srgbClr val="000000"><a:alpha val="35000"/></a:srgbClr></a:outerShdw></a:effectLst>'
           if style.get("shadow") else "")
    txt = ""
    if text:
        color = "FFFFFF" if not alpha else "262626"
        txt = ('<wps:txbx><w:txbxContent><w:p><w:pPr><w:spacing w:after="0" w:line="240" w:lineRule="auto"/>'
               '<w:jc w:val="center"/></w:pPr><w:r><w:rPr><w:color w:val="%s"/><w:sz w:val="28"/></w:rPr>'
               '<w:t xml:space="preserve">%s</w:t></w:r></w:p></w:txbxContent></wps:txbx>' % (color, escape(text)))
    return ('<wps:wsp><wps:cNvPr id="0" name="Shape %d"/><wps:cNvSpPr/><wps:spPr>%s'
            '<a:prstGeom prst="%s"><a:avLst/></a:prstGeom>%s%s%s</wps:spPr>%s'
            '<wps:bodyPr rot="0" vert="horz" wrap="square" lIns="45720" tIns="45720" rIns="45720" bIns="45720" '
            'anchor="ctr" anchorCtr="0"><a:noAutofit/></wps:bodyPr></wps:wsp>'
            % (i, xfrm, prst, _fill(fill, alpha), ln, eff, txt))


def build_xml(name, layout, lines, color, extra):
    style = IM.STYLES[extra.get("style", 0) % len(IM.STYLES)][1]
    rtl = extra.get("rtl", False)
    colorful = extra.get("colorful", False)
    members = []
    k_item = 0
    width, height = 14000, 8000
    for i, (kind, x, y, w, h, fill, text, alpha) in enumerate(IM._build(None, layout, lines, color)):
        if rtl:
            x = width - x - w if kind != "line" else width - x
            if kind == "line":
                w = -w
            if kind == "right-arrow":
                kind = "left-arrow"
        if colorful and text and fill == color:
            fill = IM.SMART_COLORS[k_item % len(IM.SMART_COLORS)]
        if text:
            k_item += 1
        if style.get("alpha") and not alpha:
            alpha = style["alpha"]
        members.append(_member(i + 1, kind, x, y, w, h, fill, text, alpha, style))
    cx, cy = width * EMU_PER_MM100, height * EMU_PER_MM100
    return ('<w:r xmlns:w="%s" xmlns:wp="%s" xmlns:a="%s" xmlns:wps="%s" xmlns:wpg="%s"><w:rPr><w:noProof/></w:rPr>'
            '<w:drawing><wp:anchor distT="0" distB="0" distL="114300" distR="114300" simplePos="0" '
            'relativeHeight="{Z}" behindDoc="0" locked="0" layoutInCell="1" allowOverlap="1">'
            '<wp:simplePos x="0" y="0"/><wp:positionH relativeFrom="page"><wp:posOffset>{X}</wp:posOffset></wp:positionH>'
            '<wp:positionV relativeFrom="page"><wp:posOffset>{Y}</wp:posOffset></wp:positionV>'
            '<wp:extent cx="%d" cy="%d"/><wp:effectExtent l="0" t="0" r="0" b="0"/><wp:wrapTopAndBottom/>'
            '<wp:docPr id="{ID}" name="%s"/><wp:cNvGraphicFramePr/>'
            '<a:graphic><a:graphicData uri="%s"><wpg:wgp><wpg:cNvGrpSpPr/><wpg:grpSpPr><a:xfrm>'
            '<a:off x="0" y="0"/><a:ext cx="%d" cy="%d"/><a:chOff x="0" y="0"/><a:chExt cx="%d" cy="%d"/>'
            '</a:xfrm></wpg:grpSpPr>%s</wpg:wgp></a:graphicData></a:graphic></wp:anchor></w:drawing></w:r>'
            % (W, WP, A, WPS, WPG, cx, cy, escape(name, {'"': "&quot;"}), WPG, cx, cy, cx, cy,
               "".join(members)))


def _new_name(win):
    names = set(re.findall(r'<wp:docPr\b[^>]*\bname="(SmartArt \d+)"', _ed(win).package_part("word/document.xml") or ""))
    for k in _props(win).getPropertySetInfo().getProperties():
        if k.Name.startswith("SmartArt:"):
            names.add(k.Name[9:])
    n = 1
    while "SmartArt %d" % n in names:
        n += 1
    return "SmartArt %d" % n


def insert(win, layout, lines=None, color=None, extra=None, replace=None):
    ed = _ed(win)
    lines = lines or IM.DEFAULT_LINES[layout]
    color = color or IM.SMART_COLORS[0]
    extra = dict(extra or {})
    ed.begin_group("SmartArt")
    try:
        if replace is not None:
            o = ed.selected_object()
            pg, x, y = (o["page"], o["x"], o["y"]) if o else (ed.caret_page(), 72.0, 100.0)
            name = replace
            ed.object_delete()
        else:
            pg = ed.caret_page()
            top, _r, _b, left = ed.page_margins(pg)
            name = _new_name(win)
            x, y = left, top + 28.0
        ok = ed.insert_anchor_xml(build_xml(name, layout, lines, color, extra), pg, x, y)
        _props(win).setPropertyValue(_key(name), json.dumps(dict(extra, layout=layout, lines=lines, color=color)))
    finally:
        ed.end_group()
    win.engine.view.after_edit()
    try:
        win.update_object_tabs()
    except Exception:
        pass
    return name if ok else None


def text_pane(win, name):
    from gi.repository import Gdk, Gtk
    from ..widgets import FDialog
    inf = info(win, name)
    if inf is None:
        return
    d = FDialog(win, "Type your text here")
    tv = Gtk.TextView()
    tv.set_size_request(360, 220)
    tv.get_buffer().set_text("\n".join(inf["lines"]))
    fr = Gtk.Frame()
    fr.add(tv)
    d.add(Gtk.Label(label="One line per item. Press Tab at the start of a line to make it "
                          "a level below.", xalign=0))
    d.add(fr, expand=True)
    tv.connect("key-press-event", lambda w, e: (
        w.get_buffer().insert_at_cursor("\t"), True)[1] if e.keyval == Gdk.KEY_Tab else False)
    if d.ask() == Gtk.ResponseType.OK:
        b = tv.get_buffer()
        lines = b.get_text(*b.get_bounds(), False).split("\n")
        insert(win, inf["layout"], lines, inf["color"], IM._extra(inf), replace=name)
    d.done()


def change_layout(win, name, layout=None, color=None, **extra):
    inf = info(win, name)
    if inf is None:
        return
    ex = IM._extra(inf)
    ex.update(extra)
    if color is not None:
        ex["colorful"] = False
    insert(win, layout or inf["layout"], inf["lines"], color or inf["color"], ex, replace=name)


def edit_graphic(win, name, op):
    inf = info(win, name)
    if inf is None:
        return
    lines = IM.edit_items(inf["lines"], op, None)
    insert(win, inf["layout"], lines, inf["color"], IM._extra(inf), replace=name)


def reset_graphic(win, name):
    inf = info(win, name)
    if inf is not None:
        insert(win, inf["layout"], inf["lines"], IM.SMART_COLORS[0], replace=name)


def convert_to_text(win, name):
    inf = info(win, name)
    if inf is None:
        return
    ed = _ed(win)
    ed.begin_group("Convert to Text")
    try:
        ed.object_delete()
        _props(win).removeProperty(_key(name))
        items = IM._items(inf["lines"])
        p, start = ed.caret_pos()
        for _lvl, t in items:
            ed.type_text(t + "\n")
        p2, end = ed.caret_pos()
        ed.select_nodes(p, start, p2, end)
    finally:
        ed.end_group()
    win.engine.view.after_edit()
    win.actions.do_bullets()


def convert_to_shapes(win, name):
    _props(win).removeProperty(_key(name))
    win.update_object_tabs()
    win.engine._schedule_state()
