"""Pictures and shapes with the new engine: selecting them in the view,
sizing and moving them with the mouse, Layout Options, and the Picture
Format / Shape Format commands."""
import math

from gi.repository import Gdk, GLib, Gtk

from .. import icons

MM100_PER_PT = 2540.0 / 72.0
HANDLES = ("nw", "n", "ne", "w", "e", "sw", "s", "se")
WRAPS = [("In Line with Text", "inline", "cmd/lc_wrapoff"),
         ("Square", "square", "cmd/lc_wrapon"),
         ("Tight", "tight", "cmd/lc_wrapideal"),
         ("Through", "through", "cmd/lc_wrapcontour"),
         ("Top and Bottom", "topbottom", "cmd/lc_wraptext"),
         ("Behind Text", "behind", "cmd/lc_wrapthrough"),
         ("In Front of Text", "front", "cmd/lc_wrapthrough")]


# ------------------------------------------------------------- commands
def _ed(win):
    return win.engine.ed


def _done(win):
    win.engine.view.after_edit()


def set_wrap(win, how):
    _ed(win).object_set_wrap(how)
    _done(win)


def align(win, where, page=False):
    ed = _ed(win)
    o = ed.selected_object()
    if o is None:
        return
    if o["inline"]:
        ed.object_set_wrap("square")
    ed.object_align(where, page)
    _done(win)


def z_order(win, delta):
    _ed(win).object_z(int(delta))
    _done(win)


def rotate(win, how):
    _ed(win).object_rotate(how)
    _done(win)


def set_size_locked(win, w=None, h=None, lock=True):
    """Width / height in 1/100 mm (the size boxes); the other side follows
    when the proportions are locked."""
    ed = _ed(win)
    o = ed.selected_object()
    if o is None:
        return
    cw, ch = o["w"], o["h"]
    nw = w / MM100_PER_PT if w else None
    nh = h / MM100_PER_PT if h else None
    if lock and cw > 0 and ch > 0:
        if nw is not None and nh is None:
            nh = ch * nw / cw
        elif nh is not None and nw is None:
            nw = cw * nh / ch
    ed.object_resize(nw or cw, nh or ch)
    _done(win)


def reset_picture(win, size=False):
    ed = _ed(win)
    if size:
        n = ed.object_natural_size()
        if n:
            ed.object_resize(*n)
            _done(win)


def delete(win):
    _ed(win).object_delete()
    _done(win)


# ------------------------------------------------------------ effects
EMU = 12700


def _clr(rgb, alpha=None):
    a = '<a:alpha val="%d"/>' % int(alpha * 1000) if alpha is not None else ""
    return '<a:srgbClr val="%06X">%s</a:srgbClr>' % (rgb & 0xFFFFFF, a)


# name -> (element, attributes) as the original's presets
SHADOWS = {
    "Offset: Bottom Right": ("outerShdw", 'blurRad="50800" dist="38100" dir="2700000" algn="tl"'),
    "Offset: Bottom": ("outerShdw", 'blurRad="50800" dist="38100" dir="5400000" algn="t"'),
    "Offset: Bottom Left": ("outerShdw", 'blurRad="50800" dist="38100" dir="8100000" algn="tr"'),
    "Offset: Right": ("outerShdw", 'blurRad="50800" dist="38100" algn="l"'),
    "Offset: Center": ("outerShdw", 'blurRad="63500" sx="102000" sy="102000" algn="ctr"'),
    "Offset: Left": ("outerShdw", 'blurRad="50800" dist="38100" dir="10800000" algn="r"'),
    "Offset: Top Right": ("outerShdw", 'blurRad="50800" dist="38100" dir="18900000" algn="bl"'),
    "Offset: Top": ("outerShdw", 'blurRad="50800" dist="38100" dir="16200000" algn="b"'),
    "Offset: Top Left": ("outerShdw", 'blurRad="50800" dist="38100" dir="13500000" algn="br"'),
    "Inside: Top Left": ("innerShdw", 'blurRad="63500" dist="50800" dir="13500000"'),
    "Inside: Center": ("innerShdw", 'blurRad="114300"'),
    "Inside: Bottom Right": ("innerShdw", 'blurRad="63500" dist="50800" dir="2700000"'),
    "Perspective: Below": ("outerShdw", 'blurRad="152400" dist="317500" dir="5400000" sx="90000" sy="-19000" algn="b"'),
}
REFLECTIONS = {
    "Tight Reflection: Touching": (35000, 0),
    "Half Reflection: Touching": (55000, 0),
    "Full Reflection: Touching": (90000, 0),
    "Tight Reflection: 4 pt Offset": (35000, 50800),
    "Half Reflection: 4 pt Offset": (55000, 50800),
    "Full Reflection: 4 pt Offset": (90000, 50800),
}
BEVELS = ["Circle", "Relaxed Inset", "Cross", "Cool Slant", "Angle", "Soft Round", "Convex",
          "Slope", "Divot", "Riblet", "Hard Edge", "Art Deco"]
BEVEL_PRST = {"Circle": "circle", "Relaxed Inset": "relaxedInset", "Cross": "cross",
              "Cool Slant": "coolSlant", "Angle": "angle", "Soft Round": "softRound",
              "Convex": "convex", "Slope": "slope", "Divot": "divot", "Riblet": "riblet",
              "Hard Edge": "hardEdge", "Art Deco": "artDeco"}


def set_shadow(win, name=True):
    """A shadow preset by name (True: Offset: Bottom Right; False/None: none)."""
    ed = _ed(win)
    if name is True:
        name = "Offset: Bottom Right"
    if not name or name not in SHADOWS:
        ed.object_effect("a:outerShdw", None)
    else:
        el, attrs = SHADOWS[name]
        alpha = 50 if el == "innerShdw" else (15 if name.startswith("Perspective") else 40)
        xml = "<a:%s %s rotWithShape=\"0\">%s</a:%s>" % (el, attrs, _clr(0, alpha), el)
        if el == "innerShdw":
            xml = xml.replace(' rotWithShape="0"', "")
        ed.object_effect("a:" + el, xml)
    _done(win)


def set_reflection(win, name=None):
    ed = _ed(win)
    if not name or name not in REFLECTIONS:
        ed.object_effect("a:reflection", None)
    else:
        end, dist = REFLECTIONS[name]
        ed.object_effect("a:reflection",
                         '<a:reflection blurRad="6350" stA="52000" endA="300" endPos="%d" dist="%d" '
                         'dir="5400000" sy="-100000" algn="bl" rotWithShape="0"/>' % (end, dist))
    _done(win)


def set_glow(win, pt=0, color=None):
    ed = _ed(win)
    if not pt:
        ed.object_effect("a:glow", None)
    else:
        ed.object_effect("a:glow", '<a:glow rad="%d">%s</a:glow>' % (
            int(pt * EMU), _clr(color if color is not None else 0x4472C4, 40)))
    _done(win)


def set_soft_edges(win, pt=0):
    ed = _ed(win)
    ed.object_effect("a:softEdge", '<a:softEdge rad="%d"/>' % int(pt * EMU) if pt else None)
    _done(win)


def set_bevel(win, name=None):
    ed = _ed(win)
    if not name or name not in BEVEL_PRST:
        ed.object_effect("bevel", None)
    else:
        ed.object_effect("bevel", '<a:scene3d><a:camera prst="orthographicFront"/>'
                         '<a:lightRig rig="threePt" dir="t"/></a:scene3d>'
                         '<a:sp3d><a:bevelT w="76200" h="76200" prst="%s"/></a:sp3d>' % BEVEL_PRST[name])
    _done(win)


# Word's 3-D Rotation gallery: name -> camera preset
ROTATIONS = [
    ("Parallel", None),
    ("Isometric: Left Down", "isometricLeftDown"), ("Isometric: Right Up", "isometricRightUp"),
    ("Isometric: Top Up", "isometricTopUp"), ("Isometric: Bottom Down", "isometricBottomDown"),
    ("Off Axis 1: Left", "isometricOffAxis1Left"), ("Off Axis 1: Right", "isometricOffAxis1Right"),
    ("Off Axis 2: Left", "isometricOffAxis2Left"), ("Off Axis 2: Right", "isometricOffAxis2Right"),
    ("Perspective", None),
    ("Perspective: Left", "perspectiveLeft"), ("Perspective: Right", "perspectiveRight"),
    ("Perspective: Below", "perspectiveBelow"), ("Perspective: Above", "perspectiveAbove"),
    ("Perspective: Relaxed", "perspectiveRelaxed"),
    ("Oblique", None),
    ("Oblique: Top Left", "obliqueTopLeft"), ("Oblique: Top Right", "obliqueTopRight"),
    ("Oblique: Bottom Left", "obliqueBottomLeft"), ("Oblique: Bottom Right", "obliqueBottomRight"),
]


def set_rotation(win, prst=None):
    """3-D Rotation: a camera preset (None: no rotation)."""
    ed = _ed(win)
    if not prst:
        ed.object_effect("a:scene3d", None)
    else:
        ed.object_effect("a:scene3d", '<a:scene3d><a:camera prst="%s"/>'
                         '<a:lightRig rig="threePt" dir="t"/></a:scene3d>' % prst)
    _done(win)


def set_adjust(win, bright=0, contrast=0):
    """Corrections: brightness / contrast in percent."""
    ed = _ed(win)
    if not bright and not contrast:
        ed.object_blip("a:lum", None)
    else:
        ed.object_blip("a:lum", '<a:lum bright="%d" contrast="%d"/>' % (bright * 1000, contrast * 1000))
    _done(win)


def set_color_mode(win, mode="color"):
    ed = _ed(win)
    ed.begin_group("Picture Color")
    ed.object_blip("recolor", None)
    if mode == "grayscale":
        ed.object_blip("a:grayscl", "<a:grayscl/>")
    elif mode == "bw":
        ed.object_blip("a:biLevel", '<a:biLevel thresh="50000"/>')
    elif mode == "washout":
        ed.object_blip("a:lum", '<a:lum bright="70000" contrast="-70000"/>')
    elif isinstance(mode, tuple):
        dark, light = mode
        ed.object_blip("a:duotone", "<a:duotone>%s%s</a:duotone>" % (_clr(dark), _clr(light)))
    ed.end_group()
    _done(win)


def set_transparency(win, pct=0):
    ed = _ed(win)
    ed.object_blip("a:alphaModFix", '<a:alphaModFix amt="%d"/>' % ((100 - pct) * 1000) if pct else None)
    _done(win)


def set_outline(win, color=None, width=None, none=False):
    """Picture Border: colour, weight (points), or none."""
    ed = _ed(win)
    if none:
        ed.object_outline(None)
    else:
        o = ed.selected_object()
        cur = getattr(win, "_last_outline", (0x000000, 0.75))
        c = color if color is not None else cur[0]
        w = width if width is not None else cur[1]
        win._last_outline = (c, w)
        ed.object_outline('<a:ln w="%d"><a:solidFill>%s</a:solidFill></a:ln>' % (int(w * EMU), _clr(c)))
    _done(win)


# Picture Styles: (border pt, colour, shadow preset, extra effects)
STYLES = {
    "none": (0, 0, None, None),
    "Simple Frame, White": (7, 0xFFFFFF, "Offset: Bottom Right", None),
    "Simple Frame, Black": (7, 0x000000, None, None),
    "Thick Matte, Black": (14, 0x000000, "Offset: Bottom Right", None),
    "Drop Shadow Rectangle": (0, 0, "Offset: Bottom Right", None),
    "Metal Frame": (6, 0x8C8C8C, "Offset: Bottom Right", "bevel"),
    "Thin Frame, Gray": (1.5, 0x7F7F7F, None, None),
    "Reflected Rounded Rectangle": (0, 0, None, "reflection"),
    "Soft Edge Rectangle": (0, 0, None, "soft"),
}


def set_picture_style(win, name):
    ed = _ed(win)
    w, c, shadow, extra = STYLES.get(name, STYLES["none"])
    ed.begin_group("Picture Style")
    for k in ("a:outerShdw", "a:reflection", "a:softEdge", "a:glow", "bevel"):
        ed.object_effect(k, None)
    if w:
        ed.object_outline('<a:ln w="%d"><a:solidFill>%s</a:solidFill></a:ln>' % (int(w * EMU), _clr(c)))
    else:
        ed.object_outline(None)
    if shadow:
        el, attrs = SHADOWS[shadow]
        ed.object_effect("a:" + el, '<a:%s %s rotWithShape="0">%s</a:%s>' % (el, attrs, _clr(0, 40), el))
    if extra == "reflection":
        ed.object_effect("a:reflection", '<a:reflection blurRad="6350" stA="52000" endA="300" '
                         'endPos="35000" dir="5400000" sy="-100000" algn="bl" rotWithShape="0"/>')
    elif extra == "soft":
        ed.object_effect("a:softEdge", '<a:softEdge rad="112500"/>')
    elif extra == "bevel":
        ed.object_effect("bevel", '<a:scene3d><a:camera prst="orthographicFront"/>'
                         '<a:lightRig rig="threePt" dir="t"/></a:scene3d>'
                         '<a:sp3d><a:bevelT w="63500" h="25400"/></a:sp3d>')
    ed.end_group()
    _done(win)


def set_fill(win, color):
    """Shape Fill: a colour, or None for no fill."""
    ed = _ed(win)
    ed.object_fill('<a:solidFill>%s</a:solidFill>' % _clr(color) if color is not None else "<a:noFill/>")
    _done(win)


def change_shape(win, kind):
    from ..drawing import PRST
    prst = PRST.get(kind)
    if prst and prst != "textbox" and _ed(win).object_geometry(prst):
        _done(win)


def set_shape_style(win, variant, accent):
    """Shape Styles gallery: fill, outline, text colour and shadow."""
    from ..drawing import style_spec
    fill, outline, text, shadow = style_spec(variant, accent)
    ed = _ed(win)
    ed.begin_group("Shape Style")
    ed.object_fill('<a:solidFill>%s</a:solidFill>' % _clr(fill))
    ed.object_outline('<a:ln w="%d"><a:solidFill>%s</a:solidFill></a:ln>' % (EMU, _clr(outline)))
    ed.object_text_prop("w:color", [("w:val", "%06X" % (text & 0xFFFFFF))])
    if shadow:
        el, attrs = SHADOWS["Offset: Bottom Right"]
        ed.object_effect("a:outerShdw", '<a:%s %s><a:srgbClr val="000000"><a:alpha val="40000"/></a:srgbClr></a:%s>'
                         % (el, attrs, el))
    else:
        ed.object_effect("a:outerShdw", None)
    ed.end_group()
    _done(win)


def set_text_color(win, color):
    ed = _ed(win)
    ed.object_text_prop("w:color", [("w:val", "auto" if color is None else "%06X" % (color & 0xFFFFFF))])
    _done(win)


def set_text_outline(win, color):
    ed = _ed(win)
    if color is None:
        ed.object_text_prop("w14:textOutline", None)
    else:
        ed.object_text_prop("w:outline", [])
    _done(win)


def set_direction(win, v):
    """Shape Format > Text Direction (0 across, 2 rotated 90°, 5 rotated 270°)."""
    vert = {0: "horz", 2: "vert", 5: "vert270"}.get(v, "horz")
    if _ed(win).object_body([("vert", vert)]):
        _done(win)


def set_align(win, v):
    anchor = {"TOP": "t", "CENTER": "ctr", "BOTTOM": "b"}.get(v, "t")
    if _ed(win).object_body([("anchor", anchor)]):
        _done(win)


QUOTE = ("[Grab your reader’s attention with a great quote from the document or use this space to "
         "emphasize a key point. To place this text box anywhere on the page, just drag it.]")


def insert_builtin_textbox(win, kind):
    """Insert > Text Box gallery: a ready-made text box with sample text."""
    ed = _ed(win)
    pg = ed.caret_page()
    ps = ed.page_setup(ed.current_section()) or {}
    tw = lambda v: v / 20.0  # noqa: E731
    pw, left, right, top = tw(ps.get("width", 12240)), tw(ps.get("left", 1440)), tw(ps.get("right", 1440)), \
        tw(ps.get("top", 1440))
    width = pw - left - right
    if kind == "sidebar":
        box = (pw - right - 158.0, top, 158.0, 255.0)
    elif kind == "quote":
        box = (left + width / 6.0, top + 85.0, width * 2.0 / 3.0, 74.0)
    elif kind == "banded":
        box = (left, top + 57.0, width, 62.0)
    else:
        box = (left + 28.0, top + 28.0, 180.0, 72.0)
    ed.begin_group("Insert Text Box")
    if not ed.insert_shape("textbox", pg, box[0], box[1], box[2], box[3], "Text Box"):
        ed.end_group()
        return
    if kind == "sidebar":
        ed.type_text("[Sidebar Title]\n[Sidebars are great for calling out important points from your text "
                     "or adding additional info for quick reference, such as a schedule.]")
        ed.move_caret("doc_start", False)
        ed.move_caret("end", True)
        ed.toggle("w:b")
        ed.set_size(14.0)
        ed.set_color("2F5496")
        ed.move_caret("doc_end", False)
    else:
        ed.type_text(QUOTE)
    tmp = ed.select_story_textbox()
    if kind == "sidebar":
        ed.object_fill('<a:solidFill>%s</a:solidFill>' % _clr(0xD9E2F3))
        ed.object_outline("<a:ln><a:noFill/></a:ln>")
    elif kind == "quote":
        ed.object_fill("<a:noFill/>")
        ed.object_outline('<a:ln w="%d"><a:solidFill>%s</a:solidFill></a:ln>' % (EMU * 2, _clr(0x4472C4)))
        ed.object_text_prop("w:i", [])
        ed.object_text_prop("w:color", [("w:val", "4472C4")])
    elif kind == "banded":
        ed.object_fill('<a:solidFill>%s</a:solidFill>' % _clr(0x4472C4))
        ed.object_outline("<a:ln><a:noFill/></a:ln>")
        ed.object_text_prop("w:color", [("w:val", "FFFFFF")])
    if tmp:
        ed.deselect_object()
    ed.end_group()
    win.engine.view.document_changed()
    win.engine.view.after_move()


DISPATCH = {"set_direction": set_direction, "set_align": set_align, "set_fill": set_fill,
            "change_shape": change_shape, "set_shape_style": set_shape_style,
            "set_text_color": set_text_color, "set_text_outline": set_text_outline,
            "set_wrap": set_wrap, "align": align, "z_order": z_order, "rotate": rotate,
            "set_size_locked": set_size_locked, "reset_picture": reset_picture,
            "set_shadow": set_shadow, "set_reflection": set_reflection, "set_glow": set_glow,
            "set_soft_edges": set_soft_edges, "set_bevel": set_bevel, "set_rotation": set_rotation, "set_adjust": set_adjust,
            "set_color_mode": set_color_mode, "set_transparency": set_transparency,
            "set_outline": set_outline, "set_picture_style": set_picture_style}


def _arr(name):
    def f(win, *a):
        from . import arrange
        return getattr(arrange, name)(win, *a)
    return f


for _n in ("set_anchor_mode", "crop_to_ratio", "aspect_fill", "aspect_fit", "crop_to_shape"):
    DISPATCH[_n] = _arr(_n)
DISPATCH["crop"] = _arr("crop_mm100")
# applied to every selected object
EACH = {"set_wrap", "z_order", "rotate", "set_fill", "set_outline", "set_shadow", "set_reflection",
        "set_glow", "set_soft_edges", "set_bevel", "set_rotation", "set_shape_style", "set_text_color",
        "set_text_outline", "set_anchor_mode", "set_transparency", "set_color_mode", "set_adjust",
        "set_picture_style", "change_shape"}


def call(win, fname, *args):
    """Picture Format / Shape Format commands; False for ones not done yet."""
    f = DISPATCH.get(fname)
    ed = _ed(win)
    if f is None or ed is None:
        return False
    tmp = False
    if ed.selected_object() is None and ed.story() == "textbox":
        # typing in a text box: the commands work on its shape
        tmp = ed.select_story_textbox()
    if ed.selected_object() is None:
        # as Word: these work on a selected picture or shape
        try:
            win.status.flash("Select a picture or shape first.")
        except Exception:
            pass
        return True
    try:
        sel = ed.selected_objects()
        if fname in EACH and len(sel) > 1:
            ed.begin_group("Format Objects")
            try:
                for o in sel:
                    ed.select_object_node(o[0])
                    f(win, *args)
            finally:
                ed.end_group()
                ed.select_object_nodes([o[0] for o in sel])
                win.engine.view.objs.refresh()
        else:
            f(win, *args)
    finally:
        if tmp:
            ed.deselect_object()
            win.engine.view.objs.refresh()
    return True


UNO = {".uno:WrapOff": ("set_wrap", "inline"), ".uno:WrapOn": ("set_wrap", "square"),
       ".uno:WrapIdeal": ("set_wrap", "tight"), ".uno:WrapThrough": ("set_wrap", "behind"),
       ".uno:BringToFront": ("z_order", 1000), ".uno:SendToBack": ("z_order", -1000),
       ".uno:ObjectForwardOne": ("z_order", 1), ".uno:ObjectBackOne": ("z_order", -1),
       ".uno:ObjectAlignLeft": ("align", "left"), ".uno:AlignCenter": ("align", "center"),
       ".uno:ObjectAlignRight": ("align", "right"), ".uno:AlignUp": ("align", "top"),
       ".uno:AlignMiddle": ("align", "middle"), ".uno:AlignDown": ("align", "bottom")}


UNO.update({k: None for k in (".uno:FormatGroup", ".uno:FormatUngroup", ".uno:Regroup", ".uno:SelectObject")})


def uno_command(win, cmd):
    if cmd in (".uno:FormatGroup", ".uno:FormatUngroup", ".uno:Regroup", ".uno:SelectObject"):
        from . import arrange
        if cmd == ".uno:SelectObject":
            win.select_objects.begin()
        elif cmd == ".uno:FormatGroup":
            arrange.group(win)
        elif cmd == ".uno:Regroup":
            arrange.regroup(win)
        else:
            arrange.ungroup(win)
        return True
    if cmd not in UNO:
        return False
    fname, arg = UNO[cmd]
    return call(win, fname, arg)


def insert_picture_path(win, path, size_pt=None):
    """Insert a picture file at the caret (SVG drawn to a PNG first); True when it went in."""
    import os
    import tempfile
    ed = _ed(win)
    tmp = None
    try:
        if path.lower().endswith((".svg", ".svgz", ".emf", ".wmf")):
            from gi.repository import GdkPixbuf
            px = int((size_pt or 96) * 2)
            pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, px, px, True)
            fd, tmp = tempfile.mkstemp(suffix=".png", prefix="folio-pic-")
            os.close(fd)
            pb.savev(tmp, "png", [], [])
            path = tmp
        ok = ed.insert_picture(path)
        if ok and size_pt:
            o = ed.selected_object()
            if o and o["w"] > 0:
                k = size_pt / max(o["w"], o["h"])
                ed.object_resize(o["w"] * k, o["h"] * k)
        _done(win)
        win.update_object_tabs()
        return ok
    except Exception as e:
        print("insert picture:", e)
        return False
    finally:
        if tmp:
            os.unlink(tmp)


def insert_picture(win):
    path = win.dialogs.pick_file("Insert Picture", ["*.png", "*.jpg", "*.jpeg", "*.gif", "*.bmp",
                                                    "*.tif", "*.tiff", "*.webp"], "All Pictures")
    if not path:
        return
    ed = _ed(win)
    try:
        ok = ed.insert_picture(path)
    except Exception as e:
        ok = False
        print("insert picture:", e)
    if not ok:
        win.dialogs.message("That picture couldn't be read.")
        return
    _done(win)


# ------------------------------------------------------------- the view
class ObjectHandles:
    """The selected object's frame and handles in the view, and dragging
    them: corners and sides size it, the frame moves a floating object."""

    def __init__(self, view):
        self.view = view
        self.drag = None
        self.info = None
        self._cursor = None
        self.btn = None

    @property
    def ed(self):
        return self.view.ed

    def refresh(self):
        self.info = self.ed.selected_object() if self.ed is not None else None
        self._place_button()
        return self.info

    def active(self):
        return self.info is not None

    # geometry in widget pixels
    def rect(self):
        o = self.info
        if o is None:
            return None
        x, y = self.view.to_widget(o["page"], o["x"], o["y"])
        s = self.view.ppp
        return x, y, o["w"] * s, o["h"] * s

    def handle_points(self, r):
        x, y, w, h = r
        return dict(zip(HANDLES, [(x, y), (x + w / 2, y), (x + w, y), (x, y + h / 2),
                                  (x + w, y + h / 2), (x, y + h), (x + w / 2, y + h),
                                  (x + w, y + h)]))

    def hit(self, ex, ey):
        r = self.rect()
        if r is None:
            return None
        for name, (px, py) in self.handle_points(r).items():
            if abs(ex - px) <= 7 and abs(ey - py) <= 7:
                return name
        x, y, w, h = r
        if x <= ex <= x + w and y <= ey <= y + h:
            return "move"
        return None

    def others(self):
        """The other selected objects' boxes (widget pixels)."""
        out = []
        ed = self.ed
        if ed is None or self.info is None:
            return out
        try:
            sel = ed.selected_objects()
        except Exception:
            return out
        s = self.view.ppp
        for node, page, x, y, w, h, _inl, _k in sel[1:]:
            px, py = self.view.to_widget(page, x, y)
            out.append((px, py, w * s, h * s))
        return out

    def draw(self, cr):
        r = self.rect()
        if r is None:
            return
        for (x, y, w, h) in self.others():
            cr.save()
            cr.set_line_width(1)
            cr.set_source_rgb(0.53, 0.53, 0.53)
            cr.rectangle(x + 0.5, y + 0.5, w - 1, h - 1)
            cr.stroke()
            for px, py in self.handle_points((x, y, w, h)).values():
                cr.arc(px, py, 4.5, 0, 2 * math.pi)
                cr.set_source_rgb(1, 1, 1)
                cr.fill_preserve()
                cr.set_source_rgb(0.4, 0.4, 0.4)
                cr.stroke()
            cr.restore()
        d = self.drag
        if d is not None and d.get("moved"):
            nx, ny, nw, nh = d["rect"]
            cr.save()
            cr.set_source_rgba(0.3, 0.3, 0.3, 0.9)
            cr.set_line_width(1)
            cr.set_dash([4, 3])
            cr.rectangle(nx + 0.5, ny + 0.5, nw - 1, nh - 1)
            cr.stroke()
            cr.restore()
        x, y, w, h = r
        cr.save()
        cr.set_line_width(1)
        cr.set_source_rgb(0.53, 0.53, 0.53)
        cr.rectangle(x + 0.5, y + 0.5, w - 1, h - 1)
        cr.stroke()
        for px, py in self.handle_points(r).values():
            cr.arc(px, py, 5.5, 0, 2 * math.pi)
            cr.set_source_rgb(1, 1, 1)
            cr.fill_preserve()
            cr.set_source_rgb(0.4, 0.4, 0.4)
            cr.stroke()
        cr.restore()

    # mouse
    def press(self, ex, ey, shift):
        what = self.hit(ex, ey)
        if what is None:
            return False
        if what == "move" and self.info["inline"]:
            # an inline picture moves with the text: nothing to drag
            self.drag = None
            return True
        self.drag = {"what": what, "x0": ex, "y0": ey, "rect": self.rect(), "moved": False}
        return True

    def motion(self, ev):
        d = self.drag
        if d is None:
            self.set_cursor(self.hit(ev.x, ev.y))
            return False
        dx, dy = ev.x - d["x0"], ev.y - d["y0"]
        if not d["moved"] and abs(dx) < 3 and abs(dy) < 3:
            return True
        d["moved"] = True
        x, y, w, h = self.rect()
        what = d["what"]
        if what == "move":
            d["rect"] = (x + dx, y + dy, w, h)
        else:
            nx, ny, nw, nh = x, y, w, h
            if "e" in what:
                nw = w + dx
            if "w" in what:
                nw, nx = w - dx, x + dx
            if "s" in what:
                nh = h + dy
            if "n" in what:
                nh, ny = h - dy, y + dy
            nw, nh = max(6, nw), max(6, nh)
            shift = bool(ev.state & Gdk.ModifierType.SHIFT_MASK)
            # pictures keep their proportions at the corners (Shift: free)
            keep = len(what) == 2 and ((self.info["kind"] == "picture") != shift)
            if keep and w > 0 and h > 0:
                ratio = w / float(h)
                if abs(nw - w) / w >= abs(nh - h) / h:
                    nh = nw / ratio
                else:
                    nw = nh * ratio
                if "w" in what:
                    nx = x + w - nw
                if "n" in what:
                    ny = y + h - nh
            d["rect"] = (nx, ny, nw, nh)
        self.view.queue_draw()
        return True

    def release(self):
        d, self.drag = self.drag, None
        if d is None:
            return False
        if d["moved"]:
            s = self.view.ppp
            ox, oy, ow, oh = self.rect()
            nx, ny, nw, nh = d["rect"]
            o = self.info
            ed = self.ed
            ed.begin_group("Move" if d["what"] == "move" else "Size")
            if d["what"] != "move":
                ed.object_resize(nw / s, nh / s)
            if not o["inline"] and (abs(nx - ox) > 0.5 or abs(ny - oy) > 0.5):
                ed.object_move(o["x"] + (nx - ox) / s, o["y"] + (ny - oy) / s)
            ed.end_group()
            self.view.after_edit()
        self.view.queue_draw()
        return True

    def set_cursor(self, what):
        names = {"nw": "nw-resize", "se": "se-resize", "ne": "ne-resize", "sw": "sw-resize",
                 "n": "n-resize", "s": "s-resize", "e": "e-resize", "w": "w-resize"}
        cur = names.get(what) or ("move" if what == "move" and self.info and
                                  not self.info["inline"] else
                                  "default" if what == "move" else None)
        win = self.view.get_window()
        if win is None or cur == self._cursor:
            return
        self._cursor = cur
        self.view._ibeam = False
        try:
            win.set_cursor(Gdk.Cursor.new_from_name(win.get_display(), cur) if cur else
                           Gdk.Cursor.new_for_display(win.get_display(), Gdk.CursorType.XTERM))
        except Exception:
            pass

    def nudge(self, dx, dy):
        o = self.info
        if o is None or o["inline"]:
            return False
        self.ed.object_move(o["x"] + dx, o["y"] + dy)
        self.view.after_edit()
        return True

    # Layout Options: a small button beside the object
    def attach_button(self, overlay):
        b = Gtk.Button()
        b.get_style_context().add_class("folio-layoutopts")
        b.add(icons.image("cmd/sc_wrapon", 16))
        b.set_tooltip_text("Layout Options")
        b.set_halign(Gtk.Align.START)
        b.set_valign(Gtk.Align.START)
        b.set_no_show_all(True)
        b.set_focus_on_click(False)
        b.connect("clicked", lambda *_: self.open_layout_options())
        overlay.add_overlay(b)
        self.btn = b

    def _place_button(self):
        b = self.btn
        if b is None:
            return
        r = self.rect()
        if r is None:
            b.hide()
            return
        x, y, w, h = r
        overlay = b.get_parent()
        pos = self.view.translate_coordinates(overlay, int(x + w + 10), int(y)) if overlay else None
        if not pos:
            b.hide()
            return
        ox, oy = pos
        alloc = overlay.get_allocation()
        if ox < 0 or oy < 0 or ox > alloc.width - 30 or oy > alloc.height - 30:
            b.hide()
            return
        b.set_margin_start(int(ox))
        b.set_margin_top(int(oy))
        b.get_child().show()
        b.show()

    def open_layout_options(self):
        if self.info is None:
            return
        pop = Gtk.Popover.new(self.btn)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        for side in ("start", "end", "top", "bottom"):
            getattr(box, "set_margin_" + side)(10)
        lab = Gtk.Label(xalign=0)
        lab.set_markup("<b>Layout Options</b>")
        box.pack_start(lab, False, False, 0)
        cur = self.info["wrap"]
        for title, sub in (("In Line with Text", WRAPS[:1]), ("With Text Wrapping", WRAPS[1:])):
            box.pack_start(Gtk.Label(label=title, xalign=0), False, False, 0)
            row = Gtk.FlowBox()
            row.set_selection_mode(Gtk.SelectionMode.NONE)
            row.set_max_children_per_line(3)
            for name, how, icon in sub:
                t = Gtk.ToggleButton()
                t.add(icons.image(icon, 24))
                t.set_tooltip_text(name)
                t.set_active(how == cur)
                t.connect("clicked", lambda _b, how=how: (pop.popdown(),
                                                          self._set_wrap(how)))
                row.add(t)
            box.pack_start(row, False, False, 0)
        box.show_all()
        pop.add(box)
        pop.popup()

    def _set_wrap(self, how):
        self.ed.object_set_wrap(how)
        self.view.after_edit()


def scroll_hook(view, handles):
    """Keep the Layout Options button beside the object while scrolling."""
    sw = view.get_parent()
    while sw is not None and not isinstance(sw, Gtk.ScrolledWindow):
        sw = sw.get_parent()
    if sw is None:
        return
    for adj in (sw.get_vadjustment(), sw.get_hadjustment()):
        adj.connect("value-changed", lambda *_: GLib.idle_add(
            lambda: (handles._place_button(), False)[1]))
