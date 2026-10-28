"""On-page tools for a selected picture or shape: the Layout Options button
beside it, and cropping by dragging black crop handles."""
import math

from gi.repository import Gdk, GLib, Gtk

from . import bridge, docapi, drawing, icons

MM100_TO_TWIP = 1440.0 / 2540.0


def _parse_pair(s, sep):
    try:
        a, b = [int(float(x.strip().replace(",", "."))) for x in s.split(sep)]
        return a, b
    except Exception:
        return None


_ANCHOR = {}


def anchor_info(win, obj):
    """Where the object's anchor is on the page: the view cursor goes there
    and comes back (the object is selected again), once per selection."""
    try:
        key = (obj.Name, getattr(obj.AnchorType, "value", ""))
    except Exception:
        return None
    if _ANCHOR.get("key") == key:
        return _ANCHOR["info"]
    m = win.engine.model
    try:
        anchor = obj.getAnchor()
        vc = docapi.view_cursor(m)
        vc.gotoRange(anchor.getStart(), False)
        p = vc.getPosition()
        cur = anchor.getText().createTextCursorByRange(anchor.getStart())
        # the paragraph's frame starts above its first line by the spacing
        # before it (the previous paragraph's space after + its own space
        # before) and by the extra of proportional line spacing, which the
        # engine puts above the text
        upper = cur.ParaTopMargin or 0
        try:
            prev = anchor.getText().createTextCursorByRange(anchor.getStart())
            if prev.gotoPreviousParagraph(False):
                same = prev.ParaStyleName == cur.ParaStyleName
                if not (cur.ParaContextMargin and same):
                    upper += prev.ParaBottomMargin or 0
        except Exception:
            pass
        extra = 0
        try:
            ls = cur.ParaLineSpacing
            if ls.Mode == 0 and ls.Height > 100:
                extra = (ls.Height - 100) / 100.0 * (cur.CharHeight or 11) * 1.22 * 35.28
        except Exception:
            pass
        info = {"x": p.X, "y": p.Y, "page": vc.getPage(),
                "ptop": upper + extra, "pprint": extra, "pleft": cur.ParaLeftMargin or 0}
    except Exception:
        info = None
    try:
        docapi.controller(m).select(obj)
    except Exception:
        pass
    _ANCHOR.clear()
    _ANCHOR.update(key=key, info=info)
    return info


def forget_anchor():
    _ANCHOR.clear()


def object_rect(win):
    """(x, y, w, h) of the selected object in view pixels, or None.
    The engine reports the object's position from whatever it is placed
    relative to (page, margin, paragraph, character or line)."""
    eng = win.engine
    pos = _parse_pair(eng.state.get(".uno:Position", ""), "/")
    size = _parse_pair(eng.state.get(".uno:Size", ""), "x")
    m = eng.model
    if not pos or not size or m is None:
        return None
    try:
        rects = eng.page_rects()
        ps = docapi.page_setup(m)
        left, top = ps["left"], ps["top"]
        obj = drawing.selected_shape(m)
    except Exception:
        return None
    if not rects:
        return None
    anchor_type = getattr(getattr(obj, "AnchorType", None), "value", "") if obj is not None \
        else ""
    r0x, r0y = rects[0][0], rects[0][1]
    if anchor_type == "AT_PAGE":
        page = max(0, min((getattr(obj, "AnchorPageNo", 1) or 1) - 1, len(rects) - 1))
        rx, ry = rects[page][0], rects[page][1]
        x = rx + pos[0] * MM100_TO_TWIP
        y = ry + pos[1] * MM100_TO_TWIP
    else:
        info = anchor_info(win, obj) if obj is not None else None
        if info is None:
            try:
                page = docapi.read_cursor(m).getPage() - 1
            except Exception:
                page = 0
            rx, ry = rects[max(0, min(page, len(rects) - 1))][:2]
            x = rx + (left + pos[0]) * MM100_TO_TWIP
            y = ry + (top + pos[1]) * MM100_TO_TWIP
        else:
            # text-area origin of the first page, and of the anchor's page
            tx0 = r0x + left * MM100_TO_TWIP
            ty0 = r0y + top * MM100_TO_TWIP
            page = max(0, min(info["page"] - 1, len(rects) - 1))
            prx, pry = rects[page][0], rects[page][1]
            caret_x = tx0 + info["x"] * MM100_TO_TWIP
            caret_y = ty0 + info["y"] * MM100_TO_TWIP
            if anchor_type == "AS_CHARACTER":
                x, y = caret_x, caret_y
            else:
                try:
                    vrel = int(obj.VertOrientRelation)
                    hrel = int(obj.HoriOrientRelation)
                except Exception:
                    vrel = hrel = 0
                if vrel == 7:                       # page
                    yref = pry
                elif vrel == 8:                     # page text area
                    yref = pry + top * MM100_TO_TWIP
                elif vrel in (2, 9):                # character / line
                    yref = caret_y
                elif vrel == 0:                     # paragraph (with its spacing)
                    yref = caret_y - info["ptop"] * MM100_TO_TWIP
                else:                               # paragraph text
                    yref = caret_y - info["pprint"] * MM100_TO_TWIP
                if hrel in (7, 3, 4):               # page, page left/right
                    xref = prx
                elif hrel == 2:                     # character
                    xref = caret_x
                elif hrel == 1:                     # paragraph text area
                    xref = prx + (left + info["pleft"]) * MM100_TO_TWIP
                else:                               # paragraph area / page text area
                    xref = prx + left * MM100_TO_TWIP
                x = xref + pos[0] * MM100_TO_TWIP
                y = yref + pos[1] * MM100_TO_TWIP
    w = size[0] * MM100_TO_TWIP
    h = size[1] * MM100_TO_TWIP
    x0, y0 = eng.twips_to_px(x, y)
    x1, y1 = eng.twips_to_px(x + w, y + h)
    return x0, y0, x1 - x0, y1 - y0


# ---------------------------------------------------------------- layout options
WRAPS = [("In Line with Text", "inline", "cmd/lc_wrapoff"),
         ("Square", "square", "cmd/lc_wrapon"),
         ("Tight", "tight", "cmd/lc_wrapideal"),
         ("Through", "through", "cmd/lc_wrapcontour"),
         ("Top and Bottom", "topbottom", "cmd/lc_wraptext"),
         ("Behind Text", "behind", "cmd/lc_wrapthrough"),
         ("In Front of Text", "front", "cmd/lc_wrapthrough")]


class LayoutOptions:
    def __init__(self, win, overlay):
        self.win = win
        self.overlay = overlay
        b = Gtk.Button()
        b.get_style_context().add_class("folio-layoutopts")
        b.add(icons.image("cmd/sc_wrapon", 16))
        b.set_tooltip_text("Layout Options")
        b.set_halign(Gtk.Align.START)
        b.set_valign(Gtk.Align.START)
        b.set_no_show_all(True)
        b.set_focus_on_click(False)
        b.connect("clicked", lambda *_: self.open())
        overlay.add_overlay(b)
        self.btn = b
        self.visible = False
        sw = win.canvas
        sw.get_vadjustment().connect("value-changed", lambda *_: self.place())
        sw.get_hadjustment().connect("value-changed", lambda *_: self.place())
        win.engine.connect("zoom-changed", lambda *_: GLib.timeout_add(200, self._later))
        win.engine.connect("state-changed", self._state)
        win.engine.view.connect_after("draw", self._draw_handles)
        win.engine.view.connect("button-press-event", self.press)
        win.engine.view.connect("motion-notify-event", self.motion)
        win.engine.view.connect("button-release-event", self.release)

    rect = None
    drag = None
    _ghost = None

    def refresh_rect(self):
        self.rect = object_rect(self.win) if self.visible else None
        self.win.engine.view.queue_draw()
        return False

    def _draw_handles(self, view, cr):
        """Round white sizing handles over the engine's square ones; while
        resizing or moving, the object follows the mouse."""
        if not self.visible or self.win.crop_mode.active or not (self.handles_ok or
                                                                 self.rotatable):
            return False
        if getattr(self.win, "edit_points", None) is not None and self.win.edit_points.active:
            return False
        r = self.rect
        if r is None:
            return False
        if self.drag is not None and self.drag.get("moved") and \
                self.drag["handle"] == "rotate":
            x, y, w, h = r
            cx, cy = x + w / 2, y + h / 2
            cr.save()
            cr.translate(cx, cy)
            cr.rotate(self.drag.get("angle", 0))
            if self._ghost is not None:
                cr.set_source_surface(self._ghost, -w / 2, -h / 2)
                cr.paint_with_alpha(0.7)
            cr.set_source_rgb(0.4, 0.4, 0.4)
            cr.set_line_width(1)
            cr.rectangle(-w / 2, -h / 2, w, h)
            cr.stroke()
            cr.restore()
            return False
        self._draw_rotate_handle(cr, r)
        if not self.handles_ok:
            return False
        if self.drag is not None and self.drag.get("moved"):
            r = self.drag["rect"]
            ox, oy, ow, oh = self.rect
            if self._ghost is not None:
                sw, sh = self._ghost.get_width(), self._ghost.get_height()
                cr.save()
                cr.rectangle(*r)
                cr.clip()
                cr.translate(r[0], r[1])
                cr.scale(max(1, r[2]) / float(sw), max(1, r[3]) / float(sh))
                cr.set_source_surface(self._ghost, 0, 0)
                cr.paint_with_alpha(0.7)
                cr.restore()
        x, y, w, h = r
        pts = [(x, y), (x + w / 2, y), (x + w, y), (x, y + h / 2), (x + w, y + h / 2),
               (x, y + h), (x + w / 2, y + h), (x + w, y + h)]
        cr.set_line_width(1)
        cr.set_source_rgb(0.53, 0.53, 0.53)
        cr.rectangle(x + 0.5, y + 0.5, w - 1, h - 1)
        cr.stroke()
        for px, py in pts:
            cr.arc(px, py, 6.5, 0, 2 * math.pi)
            cr.set_source_rgb(1, 1, 1)
            cr.fill_preserve()
            cr.set_source_rgb(0.4, 0.4, 0.4)
            cr.stroke()
        return False

    def _later(self):
        self.refresh_rect()
        self.place()
        return False

    def _state(self, eng, key, value):
        if key in (".uno:Position", ".uno:Size") and self.visible and self.drag is None:
            GLib.idle_add(self._later)

    handles_ok = True
    rotatable = True

    def show(self, on):
        if not on:
            forget_anchor()
        self.visible = on
        self.handles_ok = True
        self.rotatable = True
        if on:
            try:
                obj = drawing.selected_shape(self.win.engine.model)
                t = obj.getShapeType() if hasattr(obj, "getShapeType") else ""
                self.rotatable = not any(k in t for k in ("LineShape", "ConnectorShape",
                                                          "PolyLineShape", "OpenBezierShape"))
                if not self.rotatable or (getattr(obj, "RotateAngle", 0) or 0) != 0 or \
                        (getattr(obj, "GraphicRotation", 0) or 0) != 0:
                    self.handles_ok = False
            except Exception:
                pass
        self.drag = None
        self.refresh_rect()
        if on:
            GLib.timeout_add(120, self._later)
        else:
            self.btn.hide()

    # ------------------------------------------------------------ resize / move
    HANDLES = ["nw", "n", "ne", "w", "e", "sw", "s", "se"]

    def _rot_point(self, r):
        x, y, w, h = r
        return x + w / 2, y - 22

    def _draw_rotate_handle(self, cr, r):
        if not self.rotatable:
            return
        px, py = self._rot_point(r)
        cr.save()
        cr.set_line_width(1.6)
        cr.set_source_rgb(0.35, 0.35, 0.35)
        cr.arc(px, py, 6, math.radians(-60), math.radians(240))
        cr.stroke()
        # arrow head at the open end
        ax, ay = px + 6 * math.cos(math.radians(-60)), py + 6 * math.sin(math.radians(-60))
        cr.move_to(ax + 3.5, ay - 1)
        cr.line_to(ax, ay)
        cr.line_to(ax + 0.5, ay + 3.5)
        cr.stroke()
        cr.restore()

    def _handle_points(self, r):
        x, y, w, h = r
        return dict(zip(self.HANDLES, [(x, y), (x + w / 2, y), (x + w, y), (x, y + h / 2),
                                       (x + w, y + h / 2), (x, y + h), (x + w / 2, y + h),
                                       (x + w, y + h)]))

    def _active(self):
        w = self.win
        if not self.visible or not (self.handles_ok or self.rotatable) or self.rect is None:
            return False
        for mode in ("crop_mode", "edit_points", "ink", "draw", "table_draw"):
            o = getattr(w, mode, None)
            if o is not None and getattr(o, "active", False):
                return False
        return True

    def press(self, view, ev):
        if ev.button == 1 and getattr(self.win, "bg_state", None) and \
                self.win.bg_state.get("mode"):
            if self.win.bg_click(ev.x, ev.y):
                return True
        if ev.button != 1 or not self._active() or \
                ev.type != Gdk.EventType.BUTTON_PRESS:
            return False
        r = self.rect
        hit = None
        if self.rotatable:
            rx, ry = self._rot_point(r)
            if math.hypot(ev.x - rx, ev.y - ry) <= 9:
                hit = "rotate"
        if hit is None and not self.handles_ok:
            return False
        if hit is None:
            for name, (px, py) in self._handle_points(r).items():
                if abs(ev.x - px) <= 8 and abs(ev.y - py) <= 8:
                    hit = name
                    break
        x, y, w, h = r
        if hit is None and not (x <= ev.x <= x + w and y <= ev.y <= y + h):
            return False
        self.drag = {"handle": hit or "move", "x0": ev.x, "y0": ev.y, "rect": r,
                     "moved": False, "shift": bool(ev.state & Gdk.ModifierType.SHIFT_MASK)}
        return True

    def motion(self, view, ev):
        d = self.drag
        if d is None:
            if self._active():
                self._set_cursor(view, ev)
            return False
        dx, dy = ev.x - d["x0"], ev.y - d["y0"]
        if not d["moved"]:
            if abs(dx) < 4 and abs(dy) < 4:
                return True
            d["moved"] = True
            self._grab_ghost()
        x, y, w, h = self.rect
        hnd = d["handle"]
        if hnd == "rotate":
            cx, cy = x + w / 2, y + h / 2
            a0 = math.atan2(d["y0"] - cy, d["x0"] - cx)
            a = math.atan2(ev.y - cy, ev.x - cx) - a0
            if ev.state & Gdk.ModifierType.SHIFT_MASK:
                step = math.radians(15)
                a = round(a / step) * step
            d["angle"] = a
            view.queue_draw()
            return True
        if hnd == "move":
            d["rect"] = (x + dx, y + dy, w, h)
        else:
            nx, ny, nw, nh = x, y, w, h
            if "e" in hnd:
                nw = w + dx
            if "w" in hnd:
                nw = w - dx
                nx = x + dx
            if "s" in hnd:
                nh = h + dy
            if "n" in hnd:
                nh = h - dy
                ny = y + dy
            nw, nh = max(8, nw), max(8, nh)
            corner = len(hnd) == 2
            shift = bool(ev.state & Gdk.ModifierType.SHIFT_MASK)
            keep = corner and (self._is_picture() != shift)
            if keep and w > 0 and h > 0:
                ratio = w / float(h)
                if abs(nw - w) / w >= abs(nh - h) / h:
                    nh = nw / ratio
                else:
                    nw = nh * ratio
                if "w" in hnd:
                    nx = x + w - nw
                if "n" in hnd:
                    ny = y + h - nh
            if "w" in hnd:
                nx = min(nx, x + w - 8)
            if "n" in hnd:
                ny = min(ny, y + h - 8)
            d["rect"] = (nx, ny, nw, nh)
        view.queue_draw()
        return True

    def release(self, view, ev):
        d = self.drag
        if d is None or ev.button != 1:
            return False
        self.drag = None
        self._ghost = None
        if d["moved"]:
            GLib.idle_add(lambda: (self._apply(d), False)[1])
        view.queue_draw()
        return True

    def _is_picture(self):
        try:
            return drawing.kind_of(drawing.selected_shape(self.win.engine.model)) == "picture"
        except Exception:
            return False

    def _grab_ghost(self):
        eng = self.win.engine
        x, y, w, h = self.rect
        z = eng.view.get_zoom() or 1.0
        try:
            self._ghost = eng.render(x * 15 / z, y * 15 / z, w * 15 / z, h * 15 / z, w)
        except Exception as e:
            print("ghost:", e)
            self._ghost = None

    def _set_cursor(self, view, ev):
        names = {"nw": "nw-resize", "se": "se-resize", "ne": "ne-resize", "sw": "sw-resize",
                 "n": "n-resize", "s": "s-resize", "e": "e-resize", "w": "w-resize"}
        cur = None
        if self.rotatable:
            rx, ry = self._rot_point(self.rect)
            if math.hypot(ev.x - rx, ev.y - ry) <= 9:
                cur = "grab"
        for name, (px, py) in (self._handle_points(self.rect).items()
                               if self.handles_ok and cur is None else []):
            if abs(ev.x - px) <= 8 and abs(ev.y - py) <= 8:
                cur = names[name]
                break
        if cur is None:
            x, y, w, h = self.rect
            if x <= ev.x <= x + w and y <= ev.y <= y + h:
                cur = "move"
        win = view.get_window()
        if win is None or cur == getattr(self, "_cur", None):
            return
        self._cur = cur
        try:
            win.set_cursor(Gdk.Cursor.new_from_name(win.get_display(), cur) if cur else None)
        except Exception:
            pass

    def _apply(self, d):
        """Hand the finished drag to the engine as one smooth mouse drag, so it
        resizes or moves the object exactly as its own handles would."""
        forget_anchor()         # a move can give it a new anchor
        m = self.win.engine.model
        obj = drawing.selected_shape(m) if m is not None else None
        if obj is None:
            return
        eng = self.win.engine
        ox, oy, ow, oh = self.rect
        nx, ny, nw, nh = d["rect"]
        inline = getattr(getattr(obj, "AnchorType", None), "value", "") == "AS_CHARACTER"
        if d["handle"] == "rotate":
            self._rotate(m, obj, d.get("angle", 0))
            return
        if d["handle"] == "move":
            if inline:
                self._move_inline(m, obj, d)
                return
            start = (d["x0"], d["y0"])
            end = (d["x0"] + nx - ox, d["y0"] + ny - oy)
            mods = 0
        else:
            pts_old = self._handle_points(self.rect)
            pts_new = self._handle_points(d["rect"])
            start, end = pts_old[d["handle"]], pts_new[d["handle"]]
            mods = 0x1000 if (d.get("shift") and not self._is_picture()) else 0
        doc = eng._doc_ptr()
        if doc is None:
            return
        post = doc.contents.pClass.contents.postMouseEvent
        sx, sy = eng.px_to_twips(*start)
        ex, ey = eng.px_to_twips(*end)
        post(doc, 0, int(sx), int(sy), 1, 1, mods)
        for i in range(1, 9):
            f = i / 8.0
            post(doc, 2, int(sx + (ex - sx) * f), int(sy + (ey - sy) * f), 1, 1, mods)
        post(doc, 1, int(ex), int(ey), 1, 1, mods)
        self.rect = d["rect"]
        self.win.engine.view.queue_draw()
        GLib.timeout_add(200, self._later)
        GLib.timeout_add(250, lambda: (self.win.update_object_tabs(), False)[1])

    def _rotate(self, m, obj, angle):
        """Clockwise on screen = negative in the document's convention."""
        deg = -math.degrees(angle)
        um = m.getUndoManager()
        um.enterUndoContext("Rotate")
        try:
            if drawing.kind_of(obj) == "picture":
                obj.GraphicRotation = int(round(obj.GraphicRotation + deg * 10)) % 3600
            else:
                obj.RotateAngle = int(round((obj.RotateAngle or 0) + deg * 100)) % 36000
        except Exception as e:
            print("rotate:", e)
        finally:
            um.leaveUndoContext()
        GLib.timeout_add(200, self._later)
        GLib.timeout_add(250, lambda: (self.win.update_object_tabs(), False)[1])

    def _move_inline(self, m, obj, d):
        """An in-line picture dragged to another place in the text: it goes
        where the mouse was released."""
        eng = self.win.engine
        ox, oy, ow, oh = self.rect
        nx, ny, nw, nh = d["rect"]
        px, py = d["x0"] + nx - ox, d["y0"] + ny - oy
        if ox <= px <= ox + ow and oy <= py <= oy + oh:
            return                      # dropped on itself
        if not obj.supportsService("com.sun.star.text.TextGraphicObject"):
            return
        tx, ty = eng.px_to_twips(px, py)
        eng.click_at(tx, ty)

        def finish():
            um = m.getUndoManager()
            um.enterUndoContext("Move Picture")
            try:
                vc = docapi.view_cursor(m)
                new = m.createInstance("com.sun.star.text.TextGraphicObject")
                new.AnchorType = obj.AnchorType
                vc.getText().insertTextContent(vc.getStart(), new, False)
                for p in ("Graphic", "Size", "GraphicCrop", "Title", "Description",
                          "VertOrient", "AdjustLuminance", "AdjustContrast", "GraphicColorMode",
                          "Transparency", "LeftBorder", "RightBorder", "TopBorder",
                          "BottomBorder", "ShadowFormat", "HoriMirroredOnEvenPages",
                          "HoriMirroredOnOddPages", "VertMirrored", "GraphicRotation"):
                    try:
                        setattr(new, p, getattr(obj, p))
                    except Exception:
                        pass
                name = obj.Name
                obj.getAnchor().getText().removeTextContent(obj)
                try:
                    new.Name = name
                except Exception:
                    pass
                docapi.controller(m).select(new)
            except Exception as e:
                print("move inline:", e)
            finally:
                um.leaveUndoContext()
            GLib.timeout_add(200, self._later)
            GLib.timeout_add(250, lambda: (self.win.update_object_tabs(), False)[1])
            return False
        GLib.timeout_add(150, finish)

    def place(self):
        if not self.visible:
            return
        r = self.rect or object_rect(self.win)
        if r is None:
            self.btn.hide()
            return
        x, y, w, h = r
        res = self.win.engine.view.translate_coordinates(self.overlay, int(x + w) + 8, int(y))
        if not res:
            return
        ox, oy = res
        if oy < 0 or oy > self.overlay.get_allocated_height() - 20 or \
                ox > self.overlay.get_allocated_width() - 24:
            self.btn.hide()
            return
        self.btn.set_margin_start(max(0, ox))
        self.btn.set_margin_top(max(0, oy))
        self.btn.get_child().show_all()
        self.btn.show()

    def open(self):
        pop = Gtk.Popover.new(self.btn)
        pop.set_position(Gtk.PositionType.RIGHT)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_border_width(8)
        title = Gtk.Label(xalign=0)
        title.set_markup("<b>Layout Options</b>")
        box.pack_start(title, False, False, 0)
        cur = self._current_wrap()

        def tile(label, key, icon):
            b = Gtk.Button()
            b.add(icons.image(icon, 32))
            b.set_tooltip_text(label)
            b.get_style_context().add_class("folio-btn")
            if key == cur:
                b.get_style_context().add_class("checked")
            b.connect("clicked", lambda *_: (pop.popdown(),
                                             self.win.object_call("set_wrap", key),
                                             GLib.timeout_add(150, self._later)))
            return b
        box.pack_start(Gtk.Label(label="In Line with Text", xalign=0), False, False, 0)
        box.pack_start(tile(*WRAPS[0]), False, False, 0)
        box.pack_start(Gtk.Label(label="With Text Wrapping", xalign=0), False, False, 0)
        g = Gtk.Grid(column_spacing=4, row_spacing=4)
        for i, w in enumerate(WRAPS[1:]):
            g.attach(tile(*w), i % 3, i // 3, 1, 1)
        box.pack_start(g, False, False, 0)
        move = Gtk.RadioButton.new_with_mnemonic(None, "_Move with text")
        fix = Gtk.RadioButton.new_with_mnemonic_from_widget(move, "_Fix position on page")
        try:
            obj = drawing.selected_shape(self.win.engine.model)
            fix.set_active(getattr(obj.AnchorType, "value", "") == "AT_PAGE")
        except Exception:
            pass
        move.connect("toggled", lambda b: b.get_active() and self.win.object_call(
            "set_anchor_mode", "paragraph"))
        fix.connect("toggled", lambda b: b.get_active() and self.win.object_call(
            "set_anchor_mode", "page"))
        box.pack_start(move, False, False, 0)
        box.pack_start(fix, False, False, 0)
        more = Gtk.Button(label="See more...")
        more.set_relief(Gtk.ReliefStyle.NONE)
        more.connect("clicked", lambda *_: (pop.popdown(), self.win.dialogs.object_size()))
        box.pack_start(more, False, False, 0)
        box.show_all()
        pop.add(box)
        pop.popup()

    def _current_wrap(self):
        try:
            obj = drawing.selected_shape(self.win.engine.model)
            if getattr(obj.AnchorType, "value", "") == "AS_CHARACTER":
                return "inline"
            mode = getattr(obj.TextWrap, "value", "")
            if mode == "THROUGH":
                return "behind" if not obj.Opaque else "front"
            return {"PARALLEL": "square", "DYNAMIC": "tight", "NONE": "topbottom"}.get(mode)
        except Exception:
            return None


# ---------------------------------------------------------------- crop
class CropMode:
    """Black crop handles on the picture's edges; drag them, then press Enter
    or click outside the picture to apply (Esc cancels)."""
    H = 14          # handle length (px)

    def __init__(self, win):
        self.win = win
        self.active = False
        self.rect = None
        self.cut = [0, 0, 0, 0]          # left, top, right, bottom (px)
        self.drag = None
        view = win.engine.view
        view.connect("button-press-event", self._press)
        view.connect("motion-notify-event", self._motion)
        view.connect("button-release-event", self._release)
        view.connect_after("draw", self._draw)

    def begin(self):
        r = object_rect(self.win)
        if r is None:
            self.win.dialogs.crop()
            return
        self.rect = r
        self.cut = [0, 0, 0, 0]
        self.active = True
        self.win.status.flash("Drag the black handles to crop. Enter applies, Esc cancels.")
        self.win.engine.view.queue_draw()

    def cancel(self):
        self.active = False
        self.drag = None
        self.win.engine.view.queue_draw()

    def apply(self):
        if not self.active:
            return
        x, y, w, h = self.rect
        z = self.win.engine.view.get_zoom() or 1.0
        to_mm100 = lambda px: int(px * 15 / z * 2540 / 1440)   # noqa: E731
        vals = [to_mm100(v) for v in self.cut]
        self.cancel()
        if any(vals):
            self.win.object_call("crop", vals[0], vals[1], vals[2], vals[3])

    def _edges(self):
        x, y, w, h = self.rect
        l, t, r, b = self.cut
        return x + l, y + t, x + w - r, y + h - b

    def _hit(self, ex, ey):
        x0, y0, x1, y1 = self._edges()
        tol = 8
        near = lambda a, b: abs(a - b) <= tol   # noqa: E731
        xs = {"l": near(ex, x0), "r": near(ex, x1)}
        ys = {"t": near(ey, y0), "b": near(ey, y1)}
        inside_x = x0 - tol <= ex <= x1 + tol
        inside_y = y0 - tol <= ey <= y1 + tol
        sides = []
        if xs["l"] and inside_y:
            sides.append(0)
        if xs["r"] and inside_y:
            sides.append(2)
        if ys["t"] and inside_x:
            sides.append(1)
        if ys["b"] and inside_x:
            sides.append(3)
        return sides

    def _press(self, view, ev):
        if not self.active:
            return False
        if ev.button != 1:
            return True
        sides = self._hit(ev.x, ev.y)
        if not sides:
            self.apply()
            return True
        self.drag = (sides, ev.x, ev.y, list(self.cut))
        return True

    def _motion(self, view, ev):
        if not self.active or self.drag is None:
            return False
        sides, sx, sy, start = self.drag
        x, y, w, h = self.rect
        dx, dy = ev.x - sx, ev.y - sy
        cut = list(start)
        for s in sides:
            if s == 0:
                cut[0] = max(0, min(w - cut[2] - 10, start[0] + dx))
            elif s == 2:
                cut[2] = max(0, min(w - cut[0] - 10, start[2] - dx))
            elif s == 1:
                cut[1] = max(0, min(h - cut[3] - 10, start[1] + dy))
            elif s == 3:
                cut[3] = max(0, min(h - cut[1] - 10, start[3] - dy))
        self.cut = cut
        view.queue_draw()
        return True

    def _release(self, view, ev):
        if not self.active:
            return False
        self.drag = None
        return True

    def _draw(self, view, cr):
        if not self.active or self.rect is None:
            return False
        x, y, w, h = self.rect
        x0, y0, x1, y1 = self._edges()
        # dim the parts that will be cut away
        cr.set_source_rgba(0.2, 0.2, 0.2, 0.45)
        cr.rectangle(x, y, w, h)
        cr.rectangle(x0, y0, x1 - x0, y1 - y0)
        cr.set_fill_rule(1)          # even-odd
        cr.fill()
        cr.set_fill_rule(0)
        cr.set_source_rgb(0.6, 0.6, 0.6)
        cr.set_line_width(1)
        cr.rectangle(x0 + 0.5, y0 + 0.5, x1 - x0 - 1, y1 - y0 - 1)
        cr.stroke()
        # the black handles: corners (L shapes) and edge bars
        cr.set_source_rgb(0, 0, 0)
        L, T = self.H, 4
        for cx, cy, sx, sy in ((x0, y0, 1, 1), (x1, y0, -1, 1), (x0, y1, 1, -1),
                               (x1, y1, -1, -1)):
            cr.rectangle(cx if sx > 0 else cx - L, cy if sy > 0 else cy - T, L, T)
            cr.rectangle(cx if sx > 0 else cx - T, cy if sy > 0 else cy - L, T, L)
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        cr.rectangle(mx - L / 2, y0, L, T)
        cr.rectangle(mx - L / 2, y1 - T, L, T)
        cr.rectangle(x0, my - L / 2, T, L)
        cr.rectangle(x1 - T, my - L / 2, T, L)
        cr.fill()
        return False

    def key(self, event):
        if not self.active:
            return False
        if event.keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            self.apply()
            return True
        if event.keyval == Gdk.KEY_Escape:
            self.cancel()
            return True
        return True


# ---------------------------------------------------------------- edit points
class EditPoints:
    """Shape Format > Edit Shape > Edit Points: black squares on the shape's
    vertices; drag them to reshape. Click outside or press Esc to finish."""
    S = 7

    def __init__(self, win):
        self.win = win
        self.active = False
        self.shape = None
        self.prop = None
        self.coords = []          # [[ [x, y], ... ], ...]
        self.flags = None
        self.map = None           # (ox, oy, X0, Y0, scale px per mm100)
        self.drag = None
        view = win.engine.view
        view.connect("button-press-event", self._press)
        view.connect("motion-notify-event", self._motion)
        view.connect("button-release-event", self._release)
        view.connect_after("draw", self._draw)

    def begin(self):
        from . import drawing
        m = self.win.engine.model
        obj = drawing.selected_shape(m) if m is not None else None
        if obj is None:
            return
        try:
            shape = _editable(m, obj)
        except Exception as e:
            print("edit points:", e)
            shape = None
        if shape is None:
            self.win.status.flash("Points can't be edited on this object.")
            return
        self.shape, self.prop = shape
        val = getattr(self.shape, self.prop)
        if self.prop == "PolyPolygonBezier":
            self.coords = [[[p.X, p.Y] for p in poly] for poly in val.Coordinates]
            self.flags = [list(f) for f in val.Flags]
        else:
            self.coords = [[[p.X, p.Y] for p in poly] for poly in val]
            self.flags = None
        self.active = True
        self.win.status.flash("Drag a point to reshape. Esc or click outside to finish.")
        self.win.engine.view.queue_draw()

    def stop(self):
        self.active = False
        self.drag = None
        self.win.engine.view.queue_draw()

    def _to_px(self, p):
        # shape geometry is in layout coordinates (mm100)
        return self.win.engine.twips_to_px(p[0] * MM100_TO_TWIP, p[1] * MM100_TO_TWIP)

    def _scale(self):
        """view pixels per mm100"""
        z = self.win.engine.view.get_zoom() or 1.0
        return z / 15.0 * MM100_TO_TWIP

    def _vertices(self):
        for i, poly in enumerate(self.coords):
            for j, p in enumerate(poly):
                if self.flags is None or str(getattr(self.flags[i][j], "value",
                                                     self.flags[i][j])) in ("NORMAL", "SMOOTH",
                                                                            "SYMMETRIC"):
                    yield i, j, p

    def _press(self, view, ev):
        if not self.active:
            return False
        if ev.button != 1:
            return True
        for i, j, p in self._vertices():
            px, py = self._to_px(p)
            if abs(px - ev.x) <= self.S and abs(py - ev.y) <= self.S:
                self.drag = (i, j, ev.x, ev.y, [list(q) for q in self.coords[i]])
                return True
        self.stop()
        return False

    def _motion(self, view, ev):
        if not self.active or self.drag is None:
            return False
        i, j, sx, sy, orig = self.drag
        s = self._scale()
        dx, dy = (ev.x - sx) / s, (ev.y - sy) / s
        poly = self.coords[i]
        moved = [j]
        if self.flags is not None:           # control points travel with their vertex
            for k in (j - 1, j + 1):
                if 0 <= k < len(poly) and str(getattr(self.flags[i][k], "value",
                                                      self.flags[i][k])) == "CONTROL":
                    moved.append(k)
        for k in moved:
            poly[k] = [int(orig[k][0] + dx), int(orig[k][1] + dy)]
        closed = len(poly) > 2 and orig[0] == orig[-1]
        if closed and j in (0, len(poly) - 1):
            other = len(poly) - 1 if j == 0 else 0
            poly[other] = list(poly[j])
        view.queue_draw()
        return True

    def _release(self, view, ev):
        if not self.active or self.drag is None:
            return False
        self.drag = None
        self._apply()
        return True

    def _apply(self):
        from . import bridge
        import uno
        Pt = lambda p: bridge.struct("com.sun.star.awt.Point", X=p[0], Y=p[1])  # noqa: E731
        pts = tuple(tuple(Pt(p) for p in poly) for poly in self.coords)
        m = self.win.engine.model
        um = m.getUndoManager()
        um.enterUndoContext("Edit Points")
        try:
            if self.prop == "PolyPolygonBezier":
                coords = bridge.struct("com.sun.star.drawing.PolyPolygonBezierCoords")
                coords.Coordinates = pts
                coords.Flags = tuple(tuple(f) for f in self.flags)
                uno.invoke(self.shape, "setPropertyValue", ("PolyPolygonBezier", uno.Any(
                    "com.sun.star.drawing.PolyPolygonBezierCoords", coords)))
            else:
                uno.invoke(self.shape, "setPropertyValue", ("PolyPolygon", uno.Any(
                    "[][]com.sun.star.awt.Point", pts)))
        except Exception as e:
            print("edit points apply:", e)
        finally:
            um.leaveUndoContext()

    def _draw(self, view, cr):
        if not self.active:
            return False
        cr.set_source_rgb(0.85, 0.1, 0.1)
        cr.set_line_width(1)
        cr.set_dash([3, 2])
        for i, poly in enumerate(self.coords):
            verts = [p for (a, _b, p) in self._vertices() if a == i]
            if verts:
                cr.move_to(*self._to_px(verts[0]))
                for p in verts[1:]:
                    cr.line_to(*self._to_px(p))
                cr.stroke()
        cr.set_dash([])
        for _i, _j, p in self._vertices():
            px, py = self._to_px(p)
            cr.set_source_rgb(0, 0, 0)
            cr.rectangle(px - 3.5, py - 3.5, 7, 7)
            cr.fill()
        return False

    def key(self, event):
        if self.active and event.keyval in (Gdk.KEY_Escape, Gdk.KEY_Return):
            self.stop()
            return True
        return False


def _editable(m, obj):
    """(shape, property) whose points can be edited; a preset shape is
    turned into a freeform first, keeping its look."""
    from . import bridge
    t = obj.getShapeType() if hasattr(obj, "getShapeType") else ""
    if t.endswith("ClosedBezierShape") or t.endswith("OpenBezierShape"):
        return obj, "PolyPolygonBezier"
    if t.endswith("PolyLineShape") or t.endswith("PolyPolygonShape") or t.endswith("LineShape"):
        return obj, "PolyPolygon"
    if not t.endswith("CustomShape"):
        return None
    import uno
    eng = bridge.create("com.sun.star.drawing.EnhancedCustomShapeEngine",
                        bridge.prop("CustomShape", obj))
    rendered = uno.invoke(eng, "render", ())
    coords, flags = [], []

    def collect(sh):
        if hasattr(sh, "getCount"):
            for k in range(sh.getCount()):
                collect(sh.getByIndex(k))
            return
        try:
            b = sh.PolyPolygonBezier
        except Exception:
            return
        for c, f in zip(b.Coordinates, b.Flags):
            if len(c) > 1:
                coords.append(tuple(c))
                flags.append(tuple(f))
    collect(rendered)
    if not coords:
        return None
    geo = bridge.struct("com.sun.star.drawing.PolyPolygonBezierCoords")
    geo.Coordinates = tuple(coords)
    geo.Flags = tuple(flags)
    um = m.getUndoManager()
    um.enterUndoContext("Edit Points")
    try:
        new = m.createInstance("com.sun.star.drawing.ClosedBezierShape")
        new.AnchorType = obj.AnchorType
        m.getDrawPage().add(new)
        uno.invoke(new, "setPropertyValue", ("PolyPolygonBezier", uno.Any(
            "com.sun.star.drawing.PolyPolygonBezierCoords", geo)))
        for p in ("AnchorPageNo", "HoriOrient", "VertOrient", "HoriOrientRelation",
                  "VertOrientRelation", "HoriOrientPosition", "VertOrientPosition",
                  "FillStyle", "FillColor", "FillTransparence", "LineStyle", "LineColor",
                  "LineWidth", "Shadow", "ShadowColor", "ShadowXDistance", "ShadowYDistance",
                  "TextWrap", "Opaque", "Name"):
            try:
                setattr(new, p, getattr(obj, p))
            except Exception:
                pass
        try:
            m.getDrawPage().remove(obj)
        except Exception:
            pass
        docapi.controller(m).select(new)
    finally:
        um.leaveUndoContext()
    return new, "PolyPolygonBezier"
