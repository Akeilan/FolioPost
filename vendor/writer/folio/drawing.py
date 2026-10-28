"""Shapes and text boxes: pick a shape, then drag on the page to draw it
(a plain click gives the default 1" size). Built through the document model
so the result is an ordinary shape or text box in the file."""
from gi.repository import Gdk, GLib

from . import bridge, docapi

SHAPES = {
    # name: (service, custom shape type or None)
    "rectangle": ("com.sun.star.drawing.CustomShape", "rectangle"),
    "round-rectangle": ("com.sun.star.drawing.CustomShape", "round-rectangle"),
    "ellipse": ("com.sun.star.drawing.CustomShape", "ellipse"),
    "isosceles-triangle": ("com.sun.star.drawing.CustomShape", "isosceles-triangle"),
    "right-triangle": ("com.sun.star.drawing.CustomShape", "right-triangle"),
    "diamond": ("com.sun.star.drawing.CustomShape", "diamond"),
    "pentagon": ("com.sun.star.drawing.CustomShape", "pentagon"),
    "hexagon": ("com.sun.star.drawing.CustomShape", "hexagon"),
    "right-arrow": ("com.sun.star.drawing.CustomShape", "right-arrow"),
    "left-arrow": ("com.sun.star.drawing.CustomShape", "left-arrow"),
    "up-arrow": ("com.sun.star.drawing.CustomShape", "up-arrow"),
    "down-arrow": ("com.sun.star.drawing.CustomShape", "down-arrow"),
    "star5": ("com.sun.star.drawing.CustomShape", "star5"),
    "heart": ("com.sun.star.drawing.CustomShape", "heart"),
    "smiley": ("com.sun.star.drawing.CustomShape", "smiley"),
    "cloud": ("com.sun.star.drawing.CustomShape", "cloud"),
    "callout": ("com.sun.star.drawing.CustomShape", "round-rectangular-callout"),
    "octagon": ("com.sun.star.drawing.CustomShape", "octagon"),
    "parallelogram": ("com.sun.star.drawing.CustomShape", "parallelogram"),
    "trapezoid": ("com.sun.star.drawing.CustomShape", "trapezoid"),
    "cube": ("com.sun.star.drawing.CustomShape", "cube"),
    "can": ("com.sun.star.drawing.CustomShape", "can"),
    "frame": ("com.sun.star.drawing.CustomShape", "frame"),
    "ring": ("com.sun.star.drawing.CustomShape", "ring"),
    "moon": ("com.sun.star.drawing.CustomShape", "moon"),
    "sun": ("com.sun.star.drawing.CustomShape", "sun"),
    "lightning": ("com.sun.star.drawing.CustomShape", "lightning"),
    "left-right-arrow": ("com.sun.star.drawing.CustomShape", "left-right-arrow"),
    "up-down-arrow": ("com.sun.star.drawing.CustomShape", "up-down-arrow"),
    "notched-right-arrow": ("com.sun.star.drawing.CustomShape", "notched-right-arrow"),
    "chevron": ("com.sun.star.drawing.CustomShape", "chevron"),
    "circular-arrow": ("com.sun.star.drawing.CustomShape", "circular-arrow"),
    "flowchart-process": ("com.sun.star.drawing.CustomShape", "flowchart-process"),
    "flowchart-decision": ("com.sun.star.drawing.CustomShape", "flowchart-decision"),
    "flowchart-terminator": ("com.sun.star.drawing.CustomShape", "flowchart-terminator"),
    "flowchart-document": ("com.sun.star.drawing.CustomShape", "flowchart-document"),
    "flowchart-data": ("com.sun.star.drawing.CustomShape", "flowchart-data"),
    "flowchart-connector": ("com.sun.star.drawing.CustomShape", "flowchart-connector"),
    "star4": ("com.sun.star.drawing.CustomShape", "star4"),
    "star6": ("com.sun.star.drawing.CustomShape", "star6"),
    "star8": ("com.sun.star.drawing.CustomShape", "star8"),
    "star24": ("com.sun.star.drawing.CustomShape", "star24"),
    "horizontal-scroll": ("com.sun.star.drawing.CustomShape", "horizontal-scroll"),
    "rect-callout": ("com.sun.star.drawing.CustomShape", "rectangular-callout"),
    "oval-callout": ("com.sun.star.drawing.CustomShape", "round-callout"),
    "cloud-callout": ("com.sun.star.drawing.CustomShape", "cloud-callout"),
    "line": ("com.sun.star.drawing.LineShape", None),
    "elbow-connector": ("com.sun.star.drawing.ConnectorShape", "STANDARD"),
    "curved-connector": ("com.sun.star.drawing.ConnectorShape", "CURVE"),
    "arrow-line": ("com.sun.star.drawing.LineShape", None),
    "textbox": ("com.sun.star.text.TextFrame", None),
}

SHAPE_MENU = [
    ("#", "Lines"), ("Line", "line"), ("Arrow", "arrow-line"),
    ("Connector: Elbow", "elbow-connector"), ("Connector: Curved", "curved-connector"),
    ("Freeform: Scribble", "scribble"),
    ("#", "Rectangles"), ("Rectangle", "rectangle"), ("Rounded Rectangle", "round-rectangle"),
    ("#", "Basic Shapes"), ("Oval", "ellipse"), ("Triangle", "isosceles-triangle"),
    ("Right Triangle", "right-triangle"), ("Parallelogram", "parallelogram"),
    ("Trapezoid", "trapezoid"), ("Diamond", "diamond"), ("Pentagon", "pentagon"),
    ("Hexagon", "hexagon"), ("Octagon", "octagon"), ("Frame", "frame"), ("Donut", "ring"),
    ("Cube", "cube"), ("Can", "can"), ("Heart", "heart"), ("Lightning Bolt", "lightning"),
    ("Sun", "sun"), ("Moon", "moon"), ("Smiley Face", "smiley"), ("Cloud", "cloud"),
    ("#", "Block Arrows"), ("Right Arrow", "right-arrow"), ("Left Arrow", "left-arrow"),
    ("Up Arrow", "up-arrow"), ("Down Arrow", "down-arrow"),
    ("Left-Right Arrow", "left-right-arrow"), ("Up-Down Arrow", "up-down-arrow"),
    ("Notched Right Arrow", "notched-right-arrow"), ("Chevron", "chevron"),
    ("Circular Arrow", "circular-arrow"),
    ("#", "Equation Shapes"), ("Plus Sign", "math-plus"), ("Minus Sign", "math-minus"),
    ("Multiplication Sign", "math-multiply"), ("Division Sign", "math-divide"),
    ("Equal", "math-equal"), ("Not Equal", "math-not-equal"),
    ("#", "Flowchart"), ("Process", "flowchart-process"), ("Decision", "flowchart-decision"),
    ("Terminator", "flowchart-terminator"), ("Document", "flowchart-document"),
    ("Data", "flowchart-data"), ("Connector", "flowchart-connector"),
    ("#", "Stars and Banners"), ("Star: 4 Points", "star4"), ("Star: 5 Points", "star5"),
    ("Star: 6 Points", "star6"), ("Star: 8 Points", "star8"), ("Star: 24 Points", "star24"),
    ("Scroll: Horizontal", "horizontal-scroll"),
    ("#", "Callouts"), ("Speech Bubble: Rectangle", "rect-callout"),
    ("Speech Bubble: Rounded Rectangle", "callout"), ("Speech Bubble: Oval", "oval-callout"),
    ("Thought Bubble: Cloud", "cloud-callout"),
    None, ("Text Box", "textbox"), ("New Drawing Canvas", "canvas"),
]

# the menu's kinds as DrawingML presets (the new engine)
PRST = {
    "line": "line", "arrow-line": "straightConnector1", "elbow-connector": "bentConnector3",
    "curved-connector": "curvedConnector3", "rectangle": "rect", "round-rectangle": "roundRect",
    "ellipse": "ellipse", "isosceles-triangle": "triangle", "right-triangle": "rtTriangle",
    "parallelogram": "parallelogram", "trapezoid": "trapezoid", "diamond": "diamond",
    "pentagon": "pentagon", "hexagon": "hexagon", "octagon": "octagon", "frame": "frame",
    "math-plus": "mathPlus", "math-minus": "mathMinus", "math-multiply": "mathMultiply",
    "math-divide": "mathDivide", "math-equal": "mathEqual", "math-not-equal": "mathNotEqual",
    "ring": "donut", "cube": "cube", "can": "can", "heart": "heart", "lightning": "lightningBolt",
    "sun": "sun", "moon": "moon", "smiley": "smileyFace", "cloud": "cloud",
    "right-arrow": "rightArrow", "left-arrow": "leftArrow", "up-arrow": "upArrow",
    "down-arrow": "downArrow", "left-right-arrow": "leftRightArrow", "up-down-arrow": "upDownArrow",
    "notched-right-arrow": "notchedRightArrow", "chevron": "chevron", "circular-arrow": "circularArrow",
    "flowchart-process": "flowChartProcess", "flowchart-decision": "flowChartDecision",
    "flowchart-terminator": "flowChartTerminator", "flowchart-document": "flowChartDocument",
    "flowchart-data": "flowChartInputOutput", "flowchart-connector": "flowChartConnector",
    "star4": "star4", "star5": "star5", "star6": "star6", "star8": "star8", "star24": "star24",
    "horizontal-scroll": "horizontalScroll", "rect-callout": "wedgeRectCallout",
    "callout": "wedgeRoundRectCallout", "oval-callout": "wedgeEllipseCallout",
    "cloud-callout": "cloudCallout", "textbox": "textbox",
}

FILL = 0x4472C4
LINE = 0x2F528F
TWIP = 2540 / 1440.0     # 1/100 mm per twip


class DrawMode:
    def __init__(self, win):
        self.win = win
        self.kind = None
        self.start = None
        self.cur = None
        view = win.engine.view
        view.connect("button-press-event", self._press)
        view.connect("motion-notify-event", self._motion)
        view.connect("button-release-event", self._release)
        view.connect_after("draw", self._draw)
        view.add_events(Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.BUTTON_MOTION_MASK)

    def begin(self, kind):
        self.kind = kind
        self.start = self.cur = None
        w = self.win.engine.view.get_window()
        if w is not None:
            w.set_cursor(Gdk.Cursor.new_from_name(w.get_display(), "crosshair"))
        self.win.status.flash("Drag on the page to draw. Esc cancels.")

    def cancel(self):
        self.kind = None
        self.start = self.cur = None
        w = self.win.engine.view.get_window()
        if w is not None:
            w.set_cursor(None)
        self.win.engine.view.queue_draw()

    @property
    def active(self):
        return self.kind is not None

    # -------------------------------------------------------------- events
    def _press(self, view, ev):
        if not self.active or ev.button != 1:
            return False
        self.start = (ev.x, ev.y)
        self.cur = (ev.x, ev.y)
        return True

    def _motion(self, view, ev):
        if not self.active or self.start is None:
            return False
        self.cur = (ev.x, ev.y)
        view.queue_draw()
        return True

    def _release(self, view, ev):
        if not self.active or self.start is None or ev.button != 1:
            return False
        x0, y0 = self.start
        x1, y1 = ev.x, ev.y
        kind = self.kind
        self.cancel()
        GLib.idle_add(lambda: (self._create(kind, x0, y0, x1, y1), False)[1])
        return True

    def _draw(self, view, cr):
        if not self.active or self.start is None or self.cur is None:
            return False
        x0, y0 = self.start
        x1, y1 = self.cur
        cr.set_source_rgba(0.27, 0.45, 0.77, 0.25)
        cr.rectangle(min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0))
        cr.fill_preserve()
        cr.set_source_rgb(0.18, 0.32, 0.56)
        cr.set_line_width(1)
        cr.stroke()
        return False

    # -------------------------------------------------------------- create
    def _create_native(self, kind, x0, y0, x1, y1):
        view = self.win.engine.view
        ed = self.win.engine.ed
        a = view.page_at(x0, y0)
        b = view.page_at(x1, y1)
        if a is None:
            return
        pg, px0, py0 = a
        px1, py1 = (b[1], b[2]) if b is not None and b[0] == pg else (px0, py0)
        lines = kind in ("line", "arrow-line", "elbow-connector", "curved-connector")
        w, h = px1 - px0, py1 - py0
        if abs(w) < 4 and abs(h) < 4:      # a click: Word's default size
            w, h = 72.0, (0.0 if kind in ("line", "arrow-line") else 36.0 if kind == "textbox" or lines else 72.0)
        if not lines:
            px0, py0, w, h = min(px0, px0 + w), min(py0, py0 + h), abs(w), abs(h)
        label = next((it[0] for it in SHAPE_MENU if it and it[0] != "#" and it[1] == kind), "Shape")
        label = {"Arrow": "Straight Arrow Connector", "Line": "Straight Connector"}.get(label, label)
        ok = ed.insert_shape(PRST.get(kind, "rect"), pg, px0, py0, w, h, label, kind == "arrow-line")
        if ok:
            view.document_changed()
            view.objs.refresh()
            view.after_move()
            view.grab_focus()

    def _create(self, kind, x0, y0, x1, y1):
        if getattr(self.win, "native", False):
            return self._create_native(kind, x0, y0, x1, y1)
        eng = self.win.engine
        m = eng.model
        if m is None:
            return
        tx0, ty0 = eng.px_to_twips(min(x0, x1), min(y0, y1))
        tx1, ty1 = eng.px_to_twips(max(x0, x1), max(y0, y1))
        drag = (tx1 - tx0) > 90 or (ty1 - ty0) > 90
        if not drag:          # a click: default size
            tx1, ty1 = tx0 + 1440, ty0 + (1440 if kind != "textbox" else 720)
            if kind in ("line", "arrow-line", "elbow-connector", "curved-connector"):
                ty1 = ty0 + (720 if "connector" in kind else 0)
        page_no, px, py = 1, 0, 0
        for i, (rx, ry, rw, rh) in enumerate(eng.page_rects(), start=1):
            if ry <= ty0 < ry + rh:
                page_no, px, py = i, rx, ry
                break
        x = int((tx0 - px) * TWIP)
        y = int((ty0 - py) * TWIP)
        w = max(100, int((tx1 - tx0) * TWIP))
        h = max(100, int((ty1 - ty0) * TWIP))
        if kind in ("line", "arrow-line", "elbow-connector", "curved-connector"):
            # keep the direction the user dragged
            sx, sy = eng.px_to_twips(x0, y0)
            ex, ey = eng.px_to_twips(x1, y1) if drag else (tx1, ty1)
            x, y = int((sx - px) * TWIP), int((sy - py) * TWIP)
            w, h = int((ex - sx) * TWIP), int((ey - sy) * TWIP)
        try:
            insert_shape(m, kind, page_no, x, y, w, h)
        except Exception as e:
            self.win.dialogs.message("The shape couldn't be inserted: %s" % e)


def _anchor_page(obj, page_no, x, y):
    obj.AnchorType = bridge.enum("com.sun.star.text.TextContentAnchorType", "AT_PAGE")
    obj.AnchorPageNo = page_no
    obj.HoriOrient = 0
    obj.VertOrient = 0
    obj.HoriOrientRelation = 7     # page frame
    obj.VertOrientRelation = 7
    obj.HoriOrientPosition = x
    obj.VertOrientPosition = y


def _word_name(m, kind):
    label = {"ellipse": "Oval", "round-rectangle": "Rectangle: Rounded Corners",
             "textbox": "Text Box", "arrow-line": "Straight Arrow Connector",
             "line": "Straight Connector"}.get(kind)
    if not label:
        label = next((it[0] for it in SHAPE_MENU if it and it[0] != "#" and it[1] == kind),
                     "Shape")
    names = set()
    dp = m.getDrawPage()
    for i in range(dp.getCount()):
        try:
            names.add(dp.getByIndex(i).Name)
        except Exception:
            pass
    n = max(1, dp.getCount())
    while "%s %d" % (label, n) in names:
        n += 1
    return "%s %d" % (label, n)


def insert_shape(m, kind, page_no, x, y, w, h):
    shape = _insert_shape(m, kind, page_no, x, y, w, h)
    try:
        shape.Name = _word_name(m, kind)
    except Exception:
        pass
    return shape


def _insert_shape(m, kind, page_no, x, y, w, h):
    service, geo = SHAPES[kind]
    um = m.getUndoManager()
    um.enterUndoContext("Insert Shape")
    try:
        if kind == "textbox":
            frame = m.createInstance(service)
            vc = docapi.view_cursor(m)
            text = vc.getText()
            frame.AnchorType = bridge.enum("com.sun.star.text.TextContentAnchorType", "AT_PAGE")
            text.insertTextContent(vc, frame, False)
            _anchor_page(frame, page_no, x, y)
            size = bridge.struct("com.sun.star.awt.Size", Width=w, Height=h)
            frame.Size = size
            frame.SizeType = 1     # fixed
            frame.WidthType = 1
            line = bridge.struct("com.sun.star.table.BorderLine2", Color=0, LineWidth=26,
                                 OuterLineWidth=26)
            for side in ("LeftBorder", "RightBorder", "TopBorder", "BottomBorder"):
                setattr(frame, side, line)
            for side in ("LeftBorderDistance", "RightBorderDistance", "TopBorderDistance",
                         "BottomBorderDistance"):
                setattr(frame, side, 127)
            frame.BackColor = 0xFFFFFF
            try:
                frame.TextWrap = bridge.enum("com.sun.star.text.WrapTextMode", "PARALLEL")
            except Exception:
                pass
            vc.gotoRange(frame.getText().getStart(), False)
            return frame
        shape = m.createInstance(service)
        if service.endswith("ConnectorShape"):
            shape.AnchorType = bridge.enum("com.sun.star.text.TextContentAnchorType", "AT_PAGE")
            m.getDrawPage().add(shape)
            _anchor_page(shape, page_no, min(x, x + w), min(y, y + h))
            shape.StartPosition = bridge.struct("com.sun.star.awt.Point", X=x, Y=y)
            shape.EndPosition = bridge.struct("com.sun.star.awt.Point", X=x + w, Y=y + h)
            shape.EdgeKind = bridge.enum("com.sun.star.drawing.ConnectorType", geo)
            shape.LineColor = 0x4472C4
            shape.LineWidth = 26
            docapi.controller(m).select(shape)
            return shape
        if kind in ("line", "arrow-line"):
            pos = bridge.struct("com.sun.star.awt.Point", X=x if w >= 0 else x + w,
                                Y=y if h >= 0 else y + h)
            shape.Position = pos
            shape.Size = bridge.struct("com.sun.star.awt.Size", Width=abs(w) or 1, Height=abs(h) or 1)
        else:
            shape.Size = bridge.struct("com.sun.star.awt.Size", Width=w, Height=h)
        shape.AnchorType = bridge.enum("com.sun.star.text.TextContentAnchorType", "AT_PAGE")
        m.getDrawPage().add(shape)
        _anchor_page(shape, page_no, x if kind not in ("line", "arrow-line") else
                     (x if w >= 0 else x + w), y if kind not in ("line", "arrow-line") else
                     (y if h >= 0 else y + h))
        if kind in ("line", "arrow-line"):
            pts = [bridge.struct("com.sun.star.awt.Point", X=x, Y=y),
                   bridge.struct("com.sun.star.awt.Point", X=x + w, Y=y + h)]
            import uno
            try:
                uno.invoke(shape, "setPropertyValue", ("PolyPolygon", uno.Any(
                    "[][]com.sun.star.awt.Point", (tuple(pts),))))
                _anchor_page(shape, page_no, min(x, x + w), min(y, y + h))
            except Exception:
                import traceback
                traceback.print_exc()
            shape.LineColor = 0x4472C4
            shape.LineWidth = 26
            if kind == "arrow-line":
                try:
                    shape.LineEndName = "Arrow"
                    shape.LineEndWidth = 300
                except Exception:
                    pass
        else:
            geom = [bridge.prop("Type", geo)]
            import uno
            uno.invoke(shape, "setPropertyValue", ("CustomShapeGeometry", uno.Any(
                "[]com.sun.star.beans.PropertyValue", tuple(geom))))
            shape.FillColor = FILL
            shape.LineColor = LINE
            shape.LineWidth = 35
            try:
                shape.TextWrap = bridge.enum("com.sun.star.text.WrapTextMode", "PARALLEL")
            except Exception:
                pass
        docapi.controller(m).select(shape)
        return shape
    finally:
        um.leaveUndoContext()


# ---------------------------------------------------------------- formatting
def selected_shape(m):
    """The selected shape / text box / picture (not equations), or None."""
    try:
        sel = docapi.controller(m).getSelection()
    except Exception:
        return None
    if sel is None:
        return None
    try:
        if sel.supportsService("com.sun.star.text.TextRanges"):
            return None
    except Exception:
        pass
    obj = sel
    try:
        if hasattr(sel, "getCount") and not hasattr(sel, "getAnchor"):
            if sel.getCount() != 1:
                return None
            obj = sel.getByIndex(0)
    except Exception:
        return None
    try:
        if obj.supportsService("com.sun.star.text.TextEmbeddedObject"):
            return None if docapi.selected_formula_object(m) is not None else obj
    except Exception:
        pass
    return obj


def kind_of(obj):
    try:
        if obj.supportsService("com.sun.star.text.TextGraphicObject"):
            return "picture"
        if obj.supportsService("com.sun.star.text.TextFrame"):
            return "textbox"
        if obj.supportsService("com.sun.star.text.TextEmbeddedObject"):
            return "object"
    except Exception:
        pass
    return "shape"


def set_fill(obj, color):
    k = kind_of(obj)
    if k in ("textbox", "picture"):
        obj.BackColor = -1 if color is None else color
        if k == "textbox":
            try:
                obj.BackTransparent = color is None
            except Exception:
                pass
    else:
        if color is None:
            obj.FillStyle = bridge.enum("com.sun.star.drawing.FillStyle", "NONE")
        else:
            obj.FillStyle = bridge.enum("com.sun.star.drawing.FillStyle", "SOLID")
            obj.FillColor = color


def set_outline(obj, color=None, width_pt=None, none=False):
    k = kind_of(obj)
    if k in ("textbox", "picture"):
        cur = obj.TopBorder
        w = cur.OuterLineWidth or 26
        c = cur.Color
        if width_pt is not None:
            w = int(round(width_pt * 2540 / 72))
        if color is not None:
            c = color
        line = bridge.struct("com.sun.star.table.BorderLine2", Color=c, LineWidth=0 if none else w,
                             OuterLineWidth=0 if none else w)
        for side in ("LeftBorder", "RightBorder", "TopBorder", "BottomBorder"):
            setattr(obj, side, line)
        return
    if none:
        obj.LineStyle = bridge.enum("com.sun.star.drawing.LineStyle", "NONE")
        return
    obj.LineStyle = bridge.enum("com.sun.star.drawing.LineStyle", "SOLID")
    if color is not None:
        obj.LineColor = color
    if width_pt is not None:
        obj.LineWidth = int(round(width_pt * 2540 / 72))


WRAPS = {"inline": None, "square": "PARALLEL", "tight": "DYNAMIC", "through": "THROUGH",
         "topbottom": "NONE", "behind": "THROUGH", "front": "THROUGH"}


def set_wrap(obj, how):
    if how == "inline":
        obj.AnchorType = bridge.enum("com.sun.star.text.TextContentAnchorType", "AS_CHARACTER")
        return
    try:
        if getattr(obj.AnchorType, "value", "") == "AS_CHARACTER":
            obj.AnchorType = bridge.enum("com.sun.star.text.TextContentAnchorType", "AT_PARAGRAPH")
    except Exception:
        pass
    obj.TextWrap = bridge.enum("com.sun.star.text.WrapTextMode", WRAPS[how])
    try:
        obj.Opaque = how != "behind"
    except Exception:
        pass
    try:
        obj.SurroundContour = how in ("tight", "through")
    except Exception:
        pass


def z_order(obj, delta):
    try:
        obj.ZOrder = max(0, obj.ZOrder + delta)
    except Exception:
        pass


def set_size(obj, width=None, height=None):
    s = obj.Size
    if width:
        s.Width = int(width)
    if height:
        s.Height = int(height)
    obj.Size = s


def delete(m, obj):
    try:
        anchor = obj.getAnchor()
        anchor.getText().removeTextContent(obj)
    except Exception:
        try:
            m.getDrawPage().remove(obj)
        except Exception:
            pass


# ---------------------------------------------------------------- pictures
def is_picture(obj):
    return kind_of(obj) == "picture"


def set_adjust(obj, brightness=None, contrast=None):
    """Corrections: brightness/contrast in percent (-100..100)."""
    if brightness is not None:
        obj.AdjustLuminance = int(brightness)
    if contrast is not None:
        obj.AdjustContrast = int(contrast)


COLOR_MODES = {"color": "STANDARD", "grayscale": "GREYS", "bw": "MONO", "washout": "WATERMARK"}


def set_color_mode(obj, mode):
    obj.GraphicColorMode = bridge.enum("com.sun.star.drawing.ColorMode", COLOR_MODES[mode])


def set_transparency(obj, pct):
    k = kind_of(obj)
    if k == "picture":
        obj.Transparency = int(pct)
    elif k == "shape":
        obj.FillTransparence = int(pct)
    else:
        try:
            obj.BackColorTransparency = int(pct)
        except Exception:
            pass


def rotate(obj, how):
    """how: 'right' / 'left' (90 degrees), 'flipv', 'fliph'."""
    k = kind_of(obj)
    if k == "picture":
        if how in ("right", "left"):
            cur = obj.GraphicRotation          # 1/10 degree, counter-clockwise
            step = -900 if how == "right" else 900
            obj.GraphicRotation = (cur + step) % 3600
            s = obj.Size
            obj.Size = bridge.struct("com.sun.star.awt.Size", Width=s.Height, Height=s.Width)
        elif how == "flipv":
            obj.VertMirrored = not obj.VertMirrored
        elif how == "fliph":
            v = not obj.HoriMirroredOnEvenPages
            obj.HoriMirroredOnEvenPages = v
            obj.HoriMirroredOnOddPages = v
        return
    if k == "shape" and how in ("right", "left"):
        try:
            cur = obj.RotateAngle
            obj.RotateAngle = (cur + (-9000 if how == "right" else 9000)) % 36000
        except Exception:
            pass
    elif k == "shape":
        try:
            geo = list(obj.CustomShapeGeometry)
            key = "MirroredY" if how == "flipv" else "MirroredX"
            found = False
            for p in geo:
                if p.Name == key:
                    p.Value = not p.Value
                    found = True
            if not found:
                geo.append(bridge.prop(key, True))
            import uno
            uno.invoke(obj, "setPropertyValue", ("CustomShapeGeometry", uno.Any(
                "[]com.sun.star.beans.PropertyValue", tuple(geo))))
        except Exception as e:
            print("flip:", e)


def align(obj, where, page=False):
    """Align relative to the margins (or the page): left/center/right/top/
    middle/bottom."""
    try:
        if getattr(obj.AnchorType, "value", "") == "AS_CHARACTER":
            obj.AnchorType = bridge.enum("com.sun.star.text.TextContentAnchorType",
                                         "AT_PARAGRAPH")
            obj.TextWrap = bridge.enum("com.sun.star.text.WrapTextMode", "PARALLEL")
    except Exception:
        pass
    if where in ("left", "center", "right"):
        obj.HoriOrient = {"left": 3, "center": 2, "right": 1}[where]
        obj.HoriOrientRelation = 7 if page else 8     # page frame / page text area
    else:
        try:
            obj.VertOrient = {"top": 1, "middle": 2, "bottom": 3}[where]
            obj.VertOrientRelation = 7 if page else 8
        except Exception as e:
            print("align:", e)


def crop(obj, left=0, top=0, right=0, bottom=0):
    """Crop amounts in 1/100 mm of the shown size; the picture's frame shrinks
    by the same amounts."""
    c = obj.GraphicCrop
    s = obj.Size
    orig = obj.ActualSize
    # crop values are in original-size units: scale from the displayed size
    shown_w = orig.Width - c.Left - c.Right
    shown_h = orig.Height - c.Top - c.Bottom
    fx = shown_w / float(s.Width) if s.Width and shown_w > 0 else 1.0
    fy = shown_h / float(s.Height) if s.Height and shown_h > 0 else 1.0
    new_w = max(100, s.Width - left - right)
    new_h = max(100, s.Height - top - bottom)
    c.Left += int(left * fx)
    c.Right += int(right * fx)
    c.Top += int(top * fy)
    c.Bottom += int(bottom * fy)
    obj.GraphicCrop = c
    obj.Size = bridge.struct("com.sun.star.awt.Size", Width=new_w, Height=new_h)


def crop_to_ratio(obj, rw, rh):
    s = obj.Size
    target = rw / float(rh)
    cur = s.Width / float(s.Height)
    if cur > target:          # too wide: trim the sides
        cut = s.Width - int(s.Height * target)
        crop(obj, left=cut // 2, right=cut - cut // 2)
    elif cur < target:
        cut = s.Height - int(s.Width / target)
        crop(obj, top=cut // 2, bottom=cut - cut // 2)


def reset_picture(obj, size=True):
    obj.GraphicCrop = bridge.struct("com.sun.star.text.GraphicCrop", Top=0, Bottom=0,
                                    Left=0, Right=0)
    for prop, v in (("AdjustLuminance", 0), ("AdjustContrast", 0), ("Transparency", 0),
                    ("GraphicRotation", 0), ("VertMirrored", False),
                    ("HoriMirroredOnEvenPages", False), ("HoriMirroredOnOddPages", False)):
        try:
            setattr(obj, prop, v)
        except Exception:
            pass
    set_color_mode(obj, "color")
    set_picture_style(obj, "none")
    if size:
        try:
            a = obj.ActualSize
            if a.Width and a.Height:
                s = obj.Size
                # keep the current width, restore the natural proportions
                obj.Size = bridge.struct("com.sun.star.awt.Size", Width=s.Width,
                                         Height=int(s.Width * a.Height / float(a.Width)))
        except Exception:
            pass


def change_picture(obj, path):
    from . import docapi as _d
    prov = bridge.create("com.sun.star.graphic.GraphicProvider")
    g = prov.queryGraphic((bridge.prop("URL", _d.uno_url(path)),))
    s = obj.Size
    obj.Graphic = g
    try:
        a = g.Size100thMM
        if a.Width and a.Height:
            obj.Size = bridge.struct("com.sun.star.awt.Size", Width=s.Width,
                                     Height=int(s.Width * a.Height / float(a.Width)))
    except Exception:
        pass


def alt_text(obj):
    return getattr(obj, "Description", "") or ""


def set_alt_text(obj, text, decorative=False):
    obj.Description = "" if decorative else text
    try:
        obj.Decorative = bool(decorative)
    except Exception:
        pass


PICTURE_STYLES = [
    # (name, border pt, border colour, shadow)
    ("none", 0, 0, False),
    ("Simple Frame, White", 7, 0xFFFFFF, True),
    ("Simple Frame, Black", 7, 0x000000, False),
    ("Thick Matte, Black", 14, 0x000000, True),
    ("Drop Shadow Rectangle", 0, 0, True),
    ("Metal Frame", 6, 0x8C8C8C, True),
    ("Thin Frame, Gray", 1.5, 0x7F7F7F, False),
]


def set_picture_style(obj, name):
    style = {n: (w, c, sh) for n, w, c, sh in PICTURE_STYLES}.get(name, (0, 0, False))
    w, c, shadow = style
    wid = int(round(w * 2540 / 72))
    line = bridge.struct("com.sun.star.table.BorderLine2", Color=c, LineWidth=wid,
                         OuterLineWidth=wid)
    for side in ("LeftBorder", "RightBorder", "TopBorder", "BottomBorder"):
        try:
            setattr(obj, side, line)
        except Exception:
            pass
    set_shadow(obj, shadow)


def set_shadow(obj, on, color=0x808080):
    k = kind_of(obj)
    if k == "shape":
        obj.Shadow = bool(on)
        if on:
            obj.ShadowColor = color
            obj.ShadowXDistance = obj.ShadowYDistance = 150
            obj.ShadowTransparence = 50
        return
    sf = bridge.struct("com.sun.star.table.ShadowFormat",
                       Location=bridge.enum("com.sun.star.table.ShadowLocation",
                                            "BOTTOM_RIGHT" if on else "NONE"),
                       ShadowWidth=150 if on else 0, Color=color, IsTransparent=False)
    try:
        obj.ShadowFormat = sf
    except Exception as e:
        print("shadow:", e)


def size_of(obj):
    s = obj.Size
    return s.Width, s.Height


def set_size_locked(obj, width=None, height=None, lock=True):
    s = obj.Size
    w, h = s.Width, s.Height
    if width and lock and w:
        h = int(h * width / float(w))
        w = int(width)
    elif height and lock and h:
        w = int(w * height / float(h))
        h = int(height)
    else:
        w = int(width or w)
        h = int(height or h)
    obj.Size = bridge.struct("com.sun.star.awt.Size", Width=max(50, w), Height=max(50, h))


def set_anchor_mode(obj, mode):
    """'page': fixed position on the page; 'paragraph': moves with text."""
    try:
        if getattr(obj.AnchorType, "value", "") == "AS_CHARACTER":
            return
        obj.AnchorType = bridge.enum("com.sun.star.text.TextContentAnchorType",
                                     "AT_PAGE" if mode == "page" else "AT_PARAGRAPH")
    except Exception as e:
        print("anchor:", e)


# ---------------------------------------------------------------- shape styles
ACCENTS = [0x000000, 0x4472C4, 0xED7D31, 0xA5A5A5, 0xFFC000, 0x5B9BD5, 0x70AD47]


def _tint(c, t):
    r, g, b = (c >> 16) & 255, (c >> 8) & 255, c & 255
    return (int(r + (255 - r) * t) << 16) | (int(g + (255 - g) * t) << 8) | int(b + (255 - b) * t)


def _shade(c, t):
    r, g, b = (c >> 16) & 255, (c >> 8) & 255, c & 255
    return (int(r * (1 - t)) << 16) | (int(g * (1 - t)) << 8) | int(b * (1 - t))


STYLE_VARIANTS = ["Colored Outline", "Colored Fill", "Colored Fill, Light Outline",
                  "Subtle Effect", "Moderate Effect", "Intense Effect"]


def style_spec(variant, accent):
    """(fill, outline, text colour, shadow) for a shape style."""
    a = accent
    if variant == 0:
        return 0xFFFFFF, a, 0x000000, False
    if variant == 1:
        return a, _shade(a, 0.3), 0xFFFFFF, False
    if variant == 2:
        return a, 0xFFFFFF, 0xFFFFFF, False
    if variant == 3:
        return _tint(a, 0.8), a, _shade(a, 0.3) if a else 0x000000, False
    if variant == 4:
        return _tint(a, 0.35), _shade(a, 0.2), 0xFFFFFF, True
    return a, a, 0xFFFFFF, True


def set_shape_style(obj, variant, accent):
    fill, outline, text, shadow = style_spec(variant, accent)
    set_fill(obj, fill)
    set_outline(obj, outline, 1.0)
    try:
        obj.CharColor = text
    except Exception:
        pass
    set_shadow(obj, shadow)


def change_shape(obj, kind):
    """Edit Shape > Change Shape: keep size, position and format."""
    service, geo = SHAPES.get(kind, (None, None))
    if service != "com.sun.star.drawing.CustomShape":
        return
    import uno
    geom = [bridge.prop("Type", geo)]
    uno.invoke(obj, "setPropertyValue", ("CustomShapeGeometry", uno.Any(
        "[]com.sun.star.beans.PropertyValue", tuple(geom))))


def set_text_color(obj, color):
    try:
        if obj.supportsService("com.sun.star.text.TextFrame"):
            c = obj.getText().createTextCursor()
            c.gotoEnd(True)
            c.CharColor = -1 if color is None else color
            return
    except Exception:
        pass
    if obj.getShapeType().endswith("CustomShape") and _is_fontwork(obj):
        obj.FillColor = 0xFFFFFF if color is None else color
        return
    obj.CharColor = -1 if color is None else color


def set_text_outline(obj, color):
    if _is_fontwork(obj):
        if color is None:
            obj.LineStyle = bridge.enum("com.sun.star.drawing.LineStyle", "NONE")
        else:
            obj.LineStyle = bridge.enum("com.sun.star.drawing.LineStyle", "SOLID")
            obj.LineColor = color
        return
    try:
        target = obj.getText().createTextCursor() if obj.supportsService(
            "com.sun.star.text.TextFrame") else obj
        if hasattr(target, "gotoEnd"):
            target.gotoEnd(True)
        target.CharContoured = color is not None
    except Exception:
        pass


def _is_fontwork(obj):
    try:
        return any(p.Name == "TextPath" for p in obj.CustomShapeGeometry)
    except Exception:
        return False
