"""Horizontal and vertical rulers: margins shaded, measurements counted from
the margin, and the paragraph indent markers (first line, hanging, left,
right) and tab stops, all draggable."""
import json
import math

from gi.repository import Gdk, GLib, Gtk

from . import docapi
from .actions import para_margins
from .widgets import ruler_units

SIZE = 20
MARKER = 5


def tab_glyph(cr, x, base, align):
    """The original's tab marks: L, inverted T, reversed L, T with a dot."""
    cr.set_line_width(1.5)
    top = base - 5
    if align == "LEFT":
        cr.move_to(x, top)
        cr.line_to(x, base)
        cr.line_to(x + 5, base)
    elif align == "RIGHT":
        cr.move_to(x, top)
        cr.line_to(x, base)
        cr.line_to(x - 5, base)
    else:           # CENTER / DECIMAL
        cr.move_to(x, top)
        cr.line_to(x, base)
        cr.move_to(x - 4, base)
        cr.line_to(x + 4, base)
    cr.stroke()
    if align == "DECIMAL":
        cr.arc(x + 3, base - 3, 1.1, 0, 6.3)
        cr.fill()


SELECTOR = [("LEFT", "Left Tab"), ("CENTER", "Center Tab"), ("RIGHT", "Right Tab"),
            ("DECIMAL", "Decimal Tab"), ("first", "First Line Indent"),
            ("hanging", "Hanging Indent")]


class TabSelector(Gtk.EventBox):
    """The box where the rulers meet: click to choose what a click on the
    ruler sets."""

    def __init__(self, win):
        Gtk.EventBox.__init__(self)
        self.win = win
        self.i = 0
        self.set_size_request(SIZE, SIZE)
        self.get_style_context().add_class("folio-ruler")
        self.area = Gtk.DrawingArea()
        self.area.connect("draw", self._draw)
        self.add(self.area)
        self.connect("button-press-event", self._press)
        self._tip()

    @property
    def kind(self):
        return SELECTOR[self.i][0]

    def _tip(self):
        self.set_tooltip_text(SELECTOR[self.i][1])

    def _press(self, w, ev):
        if ev.button == 1:
            self.i = (self.i + 1) % len(SELECTOR)
        elif ev.button == 3:
            self.i = (self.i - 1) % len(SELECTOR)
        self._tip()
        self.area.queue_draw()
        return True

    def _draw(self, w, cr):
        a = w.get_allocation()
        cr.set_source_rgb(0.97, 0.97, 0.97)
        cr.rectangle(3, 3, a.width - 6, a.height - 6)
        cr.fill_preserve()
        cr.set_source_rgb(0.65, 0.65, 0.65)
        cr.set_line_width(1)
        cr.stroke()
        cr.set_source_rgb(0.15, 0.15, 0.15)
        cx, cy = a.width / 2.0, a.height / 2.0
        k = self.kind
        if k in ("LEFT", "CENTER", "RIGHT", "DECIMAL"):
            x = cx - 2 if k == "LEFT" else cx + 2 if k == "RIGHT" else cx
            tab_glyph(cr, x, cy + 3, k)
        else:
            cr.new_path()
            if k == "first":
                cr.move_to(cx - MARKER, cy - 4)
                cr.line_to(cx + MARKER, cy - 4)
                cr.line_to(cx, cy + 3)
            else:
                cr.move_to(cx, cy - 4)
                cr.line_to(cx + MARKER, cy + 3)
                cr.line_to(cx - MARKER, cy + 3)
            cr.close_path()
            cr.set_source_rgb(0.96, 0.96, 0.96)
            cr.fill_preserve()
            cr.set_source_rgb(0.3, 0.3, 0.3)
            cr.stroke()
        return False


class _Base(Gtk.DrawingArea):
    def __init__(self, win, horizontal):
        Gtk.DrawingArea.__init__(self)
        self.win = win
        self.horizontal = horizontal
        if horizontal:
            self.set_size_request(-1, SIZE)
        else:
            self.set_size_request(SIZE, -1)
        self.get_style_context().add_class("folio-ruler")
        self.connect("draw", self._draw)
        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK |
                        Gdk.EventMask.POINTER_MOTION_MASK)

    # page geometry in this widget's pixels ----------------------------
    def page_box(self):
        """(left, top, right, bottom) of the current page in widget px, plus
        the page setup dict; None if unknown."""
        eng = self.win.engine
        rects = eng.page_rects()
        if not rects:
            return None
        ps = self.win.ruler_state.get("page")
        if ps is None:
            return None
        page_i = self.win.ruler_state.get("page_index", 0)
        if not self.horizontal:
            # the vertical ruler follows the top-most visible page
            page_i = self.win.ruler_state.get("visible_page", page_i)
        page_i = max(0, min(page_i, len(rects) - 1))
        x, y, w, h = rects[page_i]
        x0, y0 = eng.twips_to_px(x, y)
        x1, y1 = eng.twips_to_px(x + w, y + h)
        res0 = eng.view.translate_coordinates(self, int(x0), int(y0))
        res1 = eng.view.translate_coordinates(self, int(x1), int(y1))
        if not res0 or not res1:
            return None
        return res0[0], res0[1], res1[0], res1[1], ps

    def px_per_mm100(self):
        z = self.win.engine.view.get_zoom() or 1.0
        return z * 96 / 2540.0

    def _draw(self, w, cr):
        a = self.get_allocation()
        cr.set_source_rgb(0.95, 0.95, 0.95)
        cr.paint()
        box = self.page_box()
        if box is None:
            return False
        self.paint(cr, a, box)
        return False

    def ticks(self, cr, origin, start, end, along, across0, across1, reverse=False):
        """Ticks counted from `origin` (a margin edge) in both directions."""
        name, per = ruler_units()
        k = self.px_per_mm100()
        unit_px = per * k
        sub = 8 if name == "in" else 4
        step = unit_px / sub
        if step <= 1:
            return
        cr.set_source_rgb(0.35, 0.35, 0.35)
        cr.set_line_width(1)
        cr.select_font_face("Sans")
        cr.set_font_size(9)
        n0 = int(math.floor((start - origin) / step))
        n1 = int(math.ceil((end - origin) / step))
        mid = (across0 + across1) / 2.0
        for n in range(n0, n1 + 1):
            pos = origin + n * step
            if pos < start or pos > end:
                continue
            if n % sub == 0:
                if n == 0:
                    continue
                label = str(abs(n // sub))
                ext = cr.text_extents(label)
                if self.horizontal:
                    cr.move_to(pos - ext.width / 2 - ext.x_bearing, mid + ext.height / 2)
                    cr.show_text(label)
                else:
                    cr.move_to(mid - ext.width / 2 - ext.x_bearing, pos + ext.height / 2)
                    cr.show_text(label)
                continue
            length = 4 if n % (sub // 2) == 0 else 2
            if self.horizontal:
                cr.move_to(int(pos) + 0.5, mid - length / 2.0)
                cr.line_to(int(pos) + 0.5, mid + length / 2.0)
            else:
                cr.move_to(mid - length / 2.0, int(pos) + 0.5)
                cr.line_to(mid + length / 2.0, int(pos) + 0.5)
        cr.stroke()


class HRuler(_Base):
    def __init__(self, win):
        _Base.__init__(self, win, True)
        self.drag = None
        self._tab_index = 0
        self.connect("button-press-event", self._press)
        self.connect("motion-notify-event", self._motion)
        self.connect("button-release-event", self._release)

    _preview_page = None

    def geometry(self, box):
        left, top, right, bottom, ps = box
        ps = self._preview_page or ps
        k = self.px_per_mm100()
        mleft = left + ps["left"] * k
        mright = right - ps["right"] * k
        l, r, f = self.win.ruler_state.get("indents", (0, 0, 0))
        if self.drag is not None:
            l, r, f = self.drag["vals"]
        return {"mleft": mleft, "mright": mright, "k": k,
                "left": mleft + l * k, "first": mleft + (l + f) * k, "right": mright - r * k,
                "page_l": left, "page_r": right}

    def paint(self, cr, a, box):
        g = self.geometry(box)
        h = a.height
        # page strip: white text area, grey margins
        cr.set_source_rgb(0.80, 0.80, 0.80)
        cr.rectangle(g["page_l"], 3, g["page_r"] - g["page_l"], h - 6)
        cr.fill()
        cr.set_source_rgb(1, 1, 1)
        cr.rectangle(g["mleft"], 3, g["mright"] - g["mleft"], h - 6)
        cr.fill()
        self.ticks(cr, g["mleft"], g["page_l"], g["page_r"], True, 3, h - 3)
        # tab stops
        cr.set_source_rgb(0.15, 0.15, 0.15)
        tabs = self.win.ruler_state.get("tabs", [])
        if self.drag is not None and self.drag["what"] == "tab":
            tabs = [t for i, t in enumerate(tabs) if i != self.drag["index"]]
            if not self.drag.get("off"):
                tabs = tabs + [(self.drag["pos"], self.drag["align"])]
        for pos, align in tabs:
            tab_glyph(cr, g["mleft"] + pos * g["k"], h - 4, align)
        # indent markers
        self._marker(cr, g["first"], 2, down=True)
        self._marker(cr, g["left"], h - 2 - 2 * MARKER - 4, down=False)
        cr.set_source_rgb(0.96, 0.96, 0.96)
        cr.rectangle(g["left"] - MARKER, h - 6, 2 * MARKER, 5)
        cr.fill_preserve()
        cr.set_source_rgb(0.4, 0.4, 0.4)
        cr.set_line_width(1)
        cr.stroke()
        self._marker(cr, g["right"], h - 2 - 2 * MARKER - 4, down=False)

    def _marker(self, cr, x, y, down):
        cr.new_path()
        if down:
            cr.move_to(x - MARKER, y)
            cr.line_to(x + MARKER, y)
            cr.line_to(x + MARKER, y + 3)
            cr.line_to(x, y + 3 + MARKER)
            cr.line_to(x - MARKER, y + 3)
        else:
            cr.move_to(x, y)
            cr.line_to(x + MARKER, y + MARKER)
            cr.line_to(x + MARKER, y + MARKER + 3)
            cr.line_to(x - MARKER, y + MARKER + 3)
            cr.line_to(x - MARKER, y + MARKER)
        cr.close_path()
        cr.set_source_rgb(0.96, 0.96, 0.96)
        cr.fill_preserve()
        cr.set_source_rgb(0.4, 0.4, 0.4)
        cr.set_line_width(1)
        cr.stroke()

    # -------------------------------------------------------------- dragging
    def _hit(self, ev):
        box = self.page_box()
        if box is None:
            return None, None
        g = self.geometry(box)
        h = self.get_allocated_height()
        x, y = ev.x, ev.y
        cands = []
        if abs(x - g["first"]) <= MARKER + 1 and y < h / 2 - 1:
            cands.append("first")
        if abs(x - g["left"]) <= MARKER + 1 and y >= h - 7:
            cands.append("left")
        elif abs(x - g["left"]) <= MARKER + 1 and y >= h / 2 + 1:
            cands.append("hanging")
        if abs(x - g["right"]) <= MARKER + 1 and y >= h / 2:
            cands.append("right")
        if not cands and y >= h / 2:
            for i, (pos, align) in enumerate(self.win.ruler_state.get("tabs", [])):
                if abs(x - (g["mleft"] + pos * g["k"])) <= 4:
                    self._tab_index = i
                    cands.append("tab")
                    break
        if not cands:
            # the edge between the grey margin and the white text area
            if abs(x - g["mleft"]) <= 3:
                cands.append("margin-left")
            elif abs(x - g["mright"]) <= 3:
                cands.append("margin-right")
        return (cands[0] if cands else None), g

    def _press(self, w, ev):
        if ev.button != 1:
            return False
        what, g = self._hit(ev)
        if g is None:
            return False
        vals = self.win.ruler_state.get("indents", (0, 0, 0))
        if ev.type == Gdk.EventType._2BUTTON_PRESS:
            # double-click the ruler: the Tabs dialog, as in the original
            self.drag = None
            GLib.idle_add(lambda: (self.win.dialogs.tabs_dialog(), False)[1])
            return True
        if what is None:
            # click in the text area: set what the tab selector shows
            if g["mleft"] - 2 < ev.x < g["mright"] + 2:
                pos = self._snap(int((ev.x - g["mleft"]) / g["k"]))
                kind = self.win.rulers.selector.kind
                if kind == "first":
                    l, r, f = vals
                    self.win.actions.set_indents(first=pos - l)
                elif kind == "hanging":
                    l, r, f = vals
                    self.win.actions.set_indents(left=pos, first=(l + f) - pos)
                elif pos > 0:
                    self.win.ruler_add_tab(pos, kind)
            return True
        if what == "tab":
            pos, align = self.win.ruler_state["tabs"][self._tab_index]
            self.drag = {"what": "tab", "index": self._tab_index, "x0": ev.x, "pos": pos,
                         "orig": pos, "align": align, "vals": vals, "start": vals}
            return True
        if what.startswith("margin"):
            ps = self.win.ruler_state.get("page") or {}
            self.drag = {"what": what, "x0": ev.x, "vals": vals, "start": vals,
                         "margin0": ps.get("left" if what == "margin-left" else "right", 0)}
            return True
        self.drag = {"what": what, "x0": ev.x, "start": vals, "vals": vals}
        return True

    def _snap(self, v):
        name, per = ruler_units()
        snap = 2540 / 16.0 if name == "in" else 100
        return int(round(v / snap) * snap)

    def _motion(self, w, ev):
        if self.drag is None:
            what, _g = self._hit(ev)
            tips = {"first": "First Line Indent", "hanging": "Hanging Indent",
                    "left": "Left Indent", "right": "Right Indent",
                    "margin-left": "Left Margin", "margin-right": "Right Margin"}
            if what == "tab":
                tip = {"LEFT": "Left Tab", "CENTER": "Center Tab", "RIGHT": "Right Tab",
                       "DECIMAL": "Decimal Tab"}.get(
                    self.win.ruler_state["tabs"][self._tab_index][1])
            else:
                tip = tips.get(what)
            self.set_tooltip_text(tip)
            gw = self.get_window()
            if gw is not None:
                gw.set_cursor(Gdk.Cursor.new_from_name(self.get_display(), "col-resize")
                              if what and what.startswith("margin") else None)
            return False
        if self.drag["what"] == "tab":
            k = self.px_per_mm100()
            self.drag["pos"] = max(0, self._snap(self.drag["orig"] +
                                                 (ev.x - self.drag["x0"]) / k))
            h = self.get_allocated_height()
            # dragged off the ruler: it goes when you let go
            self.drag["off"] = ev.y > h + 12 or ev.y < -12
            self.queue_draw()
            return True
        if self.drag["what"].startswith("margin"):
            k = self.px_per_mm100()
            d = (ev.x - self.drag["x0"]) / k
            m0 = self.drag["margin0"]
            self.drag["margin"] = max(0, self._snap(m0 + d if self.drag["what"] == "margin-left"
                                                    else m0 - d))
            ps = self.win.ruler_state.get("page")
            if ps:
                ps = dict(ps)
                ps["left" if self.drag["what"] == "margin-left" else "right"] = \
                    self.drag["margin"]
                self._preview_page = ps
            self.queue_draw()
            return True
        box = self.page_box()
        if box is None:
            return True
        k = self.px_per_mm100()
        d = int((ev.x - self.drag["x0"]) / k)
        # snap to 1/16" (or 1 mm)
        name, per = ruler_units()
        snap = 2540 / 16.0 if name == "in" else 100
        l, r, f = self.drag["start"]
        what = self.drag["what"]
        if what == "first":
            f = int(round((l + f + d) / snap) * snap) - l
        elif what == "hanging":
            first_abs = l + f
            l = int(round((l + d) / snap) * snap)
            f = first_abs - l
        elif what == "left":
            l = int(round((l + d) / snap) * snap)
        elif what == "right":
            r = int(round((r - d) / snap) * snap)
        self.drag["vals"] = (l, r, f)
        self.queue_draw()
        return True

    def _release(self, w, ev):
        if self.drag is None:
            return False
        what = self.drag["what"]
        if what == "tab":
            d = self.drag
            self.drag = None
            self.win.ruler_move_tab(d["orig"], None if d.get("off") else d["pos"], d["align"])
            self.queue_draw()
            self.win.focus_document()
            return True
        if what.startswith("margin"):
            d = self.drag
            self.drag = None
            self._preview_page = None
            if "margin" in d:
                m = self.win.engine.model
                if m is not None:
                    key = "left" if what == "margin-left" else "right"
                    docapi.set_page(m, **{key: d["margin"]})
                    self.win.rulers.refresh()
            self.win.focus_document()
            return True
        l, r, f = self.drag["vals"]
        self.drag = None
        self.win.actions.set_indents(left=l, right=r, first=f)
        self.win.ruler_state["indents"] = (l, r, f)
        self.queue_draw()
        self.win.focus_document()
        return True


class VRuler(_Base):
    """Top and bottom margins can be dragged here."""

    def __init__(self, win):
        _Base.__init__(self, win, False)
        self.drag = None
        self._preview = None
        self.connect("button-press-event", self._press)
        self.connect("motion-notify-event", self._motion)
        self.connect("button-release-event", self._release)

    def _edges(self):
        box = self.page_box()
        if box is None:
            return None
        left, top, right, bottom, ps = box
        k = self.px_per_mm100()
        return top + ps["top"] * k, bottom - ps["bottom"] * k, ps, k

    def _which(self, y):
        e = self._edges()
        if e is None:
            return None
        if abs(y - e[0]) <= 3:
            return "top"
        if abs(y - e[1]) <= 3:
            return "bottom"
        return None

    def _press(self, w, ev):
        if ev.button != 1:
            return False
        which = self._which(ev.y)
        if which is None:
            return False
        e = self._edges()
        self.drag = {"which": which, "y0": ev.y, "m0": e[2][which], "k": e[3]}
        return True

    def _motion(self, w, ev):
        if self.drag is None:
            which = self._which(ev.y)
            self.set_tooltip_text({"top": "Top Margin", "bottom": "Bottom Margin"}.get(which))
            gw = self.get_window()
            if gw is not None:
                gw.set_cursor(Gdk.Cursor.new_from_name(self.get_display(), "row-resize")
                              if which else None)
            return False
        d = (ev.y - self.drag["y0"]) / self.drag["k"]
        name, per = ruler_units()
        snap = 2540 / 16.0 if name == "in" else 100
        v = self.drag["m0"] + (d if self.drag["which"] == "top" else -d)
        self.drag["v"] = max(0, int(round(v / snap) * snap))
        self._preview = dict(self.win.ruler_state.get("page") or {})
        self._preview[self.drag["which"]] = self.drag["v"]
        self.queue_draw()
        return True

    def _release(self, w, ev):
        if self.drag is None:
            return False
        d, self.drag = self.drag, None
        self._preview = None
        if "v" in d and self.win.engine.model is not None:
            docapi.set_page(self.win.engine.model, **{d["which"]: d["v"]})
            self.win.rulers.refresh()
        self.win.focus_document()
        return True

    def paint(self, cr, a, box):
        left, top, right, bottom, ps = box
        ps = self._preview or ps
        k = self.px_per_mm100()
        mtop = top + ps["top"] * k
        mbottom = bottom - ps["bottom"] * k
        w = a.width
        cr.set_source_rgb(0.80, 0.80, 0.80)
        cr.rectangle(3, top, w - 6, bottom - top)
        cr.fill()
        cr.set_source_rgb(1, 1, 1)
        cr.rectangle(3, mtop, w - 6, mbottom - mtop)
        cr.fill()
        self.ticks(cr, mtop, max(0, top), min(a.height, bottom), False, 3, w - 3)


class Rulers:
    """Owns both rulers and keeps their data current."""
    def __init__(self, win, hbox_parent, vbox_parent):
        self.win = win
        win.ruler_state = {}
        self.h = HRuler(win)
        self.v = VRuler(win)
        self.selector = TabSelector(win)
        self.corner = self.selector
        self._pending = None
        eng = win.engine
        eng.connect("state-changed", self._state)
        eng.connect("zoom-changed", lambda *_: self.redraw())
        eng.connect("model-ready", lambda *_: self.refresh())
        sw = win.canvas
        sw.get_vadjustment().connect("value-changed", lambda *_: self._scrolled())
        sw.get_hadjustment().connect("value-changed", lambda *_: self.redraw())
        win.canvas.connect("size-allocate", lambda *_: self.redraw())

    def set_visible(self, on):
        for w in (self.h, self.v, self.corner):
            w.set_visible(on)

    def _state(self, eng, key, value):
        if key == ".uno:LeftRightParaMargin":
            self.win.ruler_state["indents"] = para_margins(eng)
            self.h.queue_draw()
        elif key in (".uno:StatePageNumber", ".uno:ModifiedStatus", ".uno:Size",
                     ".uno:PageStyleName", ".uno:StyleApply"):
            self.schedule()

    def schedule(self):
        if self._pending is None:
            self._pending = GLib.timeout_add(150, self.refresh)

    def refresh(self):
        self._pending = None
        m = self.win.engine.model
        if m is None:
            return False
        try:
            self.win.ruler_state["page"] = docapi.page_setup(m)
            vc = docapi.read_cursor(m)
            self.win.ruler_state["page_index"] = max(0, vc.getPage() - 1)
            self.win.ruler_state["tabs"] = [(t.Position, t.Alignment.value)
                                            for t in (vc.ParaTabStops or ())
                                            if getattr(t.Alignment, "value", "") != "DEFAULT"]
        except Exception:
            pass
        self._scrolled()
        return False

    def _scrolled(self):
        eng = self.win.engine
        rects = eng.page_rects()
        sw = self.win.canvas
        top = sw.get_vadjustment().get_value()
        z = eng.view.get_zoom() or 1.0
        idx = 0
        for i, (x, y, w, h) in enumerate(rects):
            if (y + h) * z / 15.0 > top + 10:
                idx = i
                break
        self.win.ruler_state["visible_page"] = idx
        self.redraw()

    def redraw(self):
        self.h.queue_draw()
        self.v.queue_draw()
