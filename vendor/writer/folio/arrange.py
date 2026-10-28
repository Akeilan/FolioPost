"""Arrange tools: the Selection Pane, aligning and distributing several
objects, and helpers for multi-object selections."""
from gi.repository import Gdk, GLib, Gtk, Pango

from . import bridge, docapi, icons
from .panes import Pane

MATH_CLSID = "078B7ABA-54FC-457F-8551-6147E776A997"


def all_objects(m):
    """Every floating or in-line object (shapes, pictures, text boxes, charts),
    front-most first, as (object, display name, kind)."""
    seen, out = set(), []
    for coll in (m.getDrawPage(),):
        for i in range(coll.getCount()):
            o = coll.getByIndex(i)
            try:
                name = o.Name or ""
            except Exception:
                name = ""
            try:
                if o.supportsService("com.sun.star.text.TextEmbeddedObject") and \
                        o.CLSID.upper() == MATH_CLSID:
                    continue
            except Exception:
                pass
            if name in seen and name:
                continue
            seen.add(name)
            out.append(o)
    try:
        out.sort(key=lambda o: -(o.ZOrder or 0))
    except Exception:
        pass
    return out


def display_name(o, i=0):
    try:
        n = o.Name
    except Exception:
        n = ""
    if n:
        return n
    try:
        t = o.getShapeType().split(".")[-1].replace("Shape", "")
    except Exception:
        t = "Object"
    return "%s %d" % (t or "Object", i + 1)


def selected_objects(m):
    """The selected objects (one or several), or []."""
    try:
        sel = docapi.controller(m).getSelection()
    except Exception:
        return []
    if sel is None:
        return []
    try:
        if sel.supportsService("com.sun.star.text.TextRanges"):
            return []
    except Exception:
        pass
    if hasattr(sel, "getCount") and not hasattr(sel, "getAnchor"):
        try:
            return [sel.getByIndex(i) for i in range(sel.getCount())]
        except Exception:
            return []
    return [sel]


def select(m, objs):
    ctl = docapi.controller(m)
    if not objs:
        return
    if len(objs) == 1:
        ctl.select(objs[0])
        return
    coll = bridge.create("com.sun.star.drawing.ShapeCollection")
    for o in objs:
        coll.add(o)
    ctl.select(coll)


# ------------------------------------------------------------ align / distribute
def _box(o):
    """(x, y, w, h) of a floating object, mm100 in its anchor's coordinates."""
    s = o.Size
    return o.HoriOrientPosition, o.VertOrientPosition, s.Width, s.Height


def _make_free(o):
    """Positions become explicit numbers (as after dragging)."""
    try:
        if getattr(o.AnchorType, "value", "") == "AS_CHARACTER":
            o.AnchorType = bridge.enum("com.sun.star.text.TextContentAnchorType",
                                       "AT_PARAGRAPH")
            o.TextWrap = bridge.enum("com.sun.star.text.WrapTextMode", "PARALLEL")
    except Exception:
        pass
    x, y = o.HoriOrientPosition, o.VertOrientPosition
    o.HoriOrient = 0
    o.VertOrient = 0
    o.HoriOrientPosition = x
    o.VertOrientPosition = y


def align_objects(m, objs, where):
    """Align several objects to each other (Align Selected Objects)."""
    if len(objs) < 2:
        return False
    um = m.getUndoManager()
    um.enterUndoContext("Align Objects")
    try:
        for o in objs:
            _make_free(o)
        boxes = [_box(o) for o in objs]
        if where == "left":
            v = min(b[0] for b in boxes)
            for o in objs:
                o.HoriOrientPosition = v
        elif where == "right":
            v = max(b[0] + b[2] for b in boxes)
            for o, b in zip(objs, boxes):
                o.HoriOrientPosition = v - b[2]
        elif where == "center":
            lo = min(b[0] for b in boxes)
            hi = max(b[0] + b[2] for b in boxes)
            c = (lo + hi) // 2
            for o, b in zip(objs, boxes):
                o.HoriOrientPosition = c - b[2] // 2
        elif where == "top":
            v = min(b[1] for b in boxes)
            for o in objs:
                o.VertOrientPosition = v
        elif where == "bottom":
            v = max(b[1] + b[3] for b in boxes)
            for o, b in zip(objs, boxes):
                o.VertOrientPosition = v - b[3]
        elif where == "middle":
            lo = min(b[1] for b in boxes)
            hi = max(b[1] + b[3] for b in boxes)
            c = (lo + hi) // 2
            for o, b in zip(objs, boxes):
                o.VertOrientPosition = c - b[3] // 2
    finally:
        um.leaveUndoContext()
    return True


def distribute(m, objs, axis):
    """Even gaps between three or more objects ('h' or 'v')."""
    if len(objs) < 3:
        return False
    um = m.getUndoManager()
    um.enterUndoContext("Distribute Objects")
    try:
        for o in objs:
            _make_free(o)
        i = 0 if axis == "h" else 1
        items = sorted(((_box(o), o) for o in objs), key=lambda t: t[0][i])
        first, last = items[0][0], items[-1][0]
        total = sum(b[2 + i] for b, _o in items)
        span = (last[i] + last[2 + i]) - first[i]
        gap = (span - total) / float(len(items) - 1)
        pos = first[i]
        for b, o in items:
            if axis == "h":
                o.HoriOrientPosition = int(pos)
            else:
                o.VertOrientPosition = int(pos)
            pos += b[2 + i] + gap
    finally:
        um.leaveUndoContext()
    return True


# ------------------------------------------------------------ selection pane
class SelectionPane(Pane):
    TITLE = "Selection"
    WIDTH = 260

    def __init__(self, win):
        Pane.__init__(self, win)
        bar = Gtk.Box(spacing=4)
        for label, cb in (("Show All", lambda: self.show_all_objects(True)),
                          ("Hide All", lambda: self.show_all_objects(False))):
            b = Gtk.Button(label=label)
            b.connect("clicked", lambda _b, cb=cb: cb())
            bar.pack_start(b, False, False, 0)
        for icon, tip, d in (("pan-up-symbolic", "Bring Forward", 1),
                             ("pan-down-symbolic", "Send Backward", -1)):
            b = Gtk.Button()
            b.add(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.MENU))
            b.set_tooltip_text(tip)
            b.connect("clicked", lambda _b, d=d: self.reorder(d))
            bar.pack_end(b, False, False, 0)
        self.pack_start(bar, False, False, 0)
        self.store = Gtk.ListStore(str, bool, object)
        self.tv = Gtk.TreeView(model=self.store)
        self.tv.set_headers_visible(False)
        self.tv.get_selection().set_mode(Gtk.SelectionMode.MULTIPLE)
        name = Gtk.CellRendererText()
        name.set_property("editable", True)
        name.set_property("ellipsize", Pango.EllipsizeMode.END)
        name.connect("edited", self._renamed)
        col = Gtk.TreeViewColumn("", name, text=0)
        col.set_expand(True)
        self.tv.append_column(col)
        eye = Gtk.CellRendererPixbuf()
        eyecol = Gtk.TreeViewColumn("", eye)
        eyecol.set_cell_data_func(eye, self._eye)
        self.tv.append_column(eyecol)
        self.tv.connect("button-press-event", self._click)
        self._muted = False
        self.tv.get_selection().connect("changed", self._selected)
        sw = Gtk.ScrolledWindow()
        sw.add(self.tv)
        self.pack_start(sw, True, True, 0)

    def _eye(self, col, cell, model, it, data):
        cell.set_property("icon-name", "view-reveal-symbolic" if model[it][1] else
                          "view-conceal-symbolic")

    def on_shown(self):
        self.refresh()

    def refresh(self):
        m = self.model
        if m is None:
            return
        self._muted = True
        self.store.clear()
        for i, o in enumerate(all_objects(m)):
            try:
                vis = bool(o.Visible)
            except Exception:
                vis = True
            self.store.append([display_name(o, i), vis, o])
        self._muted = False

    def _click(self, tv, ev):
        res = tv.get_path_at_pos(int(ev.x), int(ev.y))
        if not res:
            return False
        path, col = res[0], res[1]
        if col is tv.get_column(1) and ev.button == 1:
            row = self.store[path]
            row[1] = not row[1]
            try:
                row[2].Visible = row[1]
            except Exception as e:
                print("visible:", e)
            return True
        return False

    def _selected(self, sel):
        if self._muted:
            return
        model, paths = sel.get_selected_rows()
        objs = [model[p][2] for p in paths if model[p][1]]
        if objs:
            try:
                select(self.model, objs)
            except Exception as e:
                print("select objects:", e)
            GLib.timeout_add(120, lambda: (self.win.update_object_tabs(), False)[1])

    def _renamed(self, cell, path, text):
        text = text.strip()
        if not text:
            return
        try:
            self.store[path][2].Name = text
            self.store[path][0] = text
        except Exception as e:
            self.win.dialogs.message("The name couldn't be changed: %s" % e)

    def show_all_objects(self, on):
        for row in self.store:
            try:
                row[2].Visible = on
                row[1] = on
            except Exception:
                pass

    def reorder(self, delta):
        model, paths = self.tv.get_selection().get_selected_rows()
        for p in paths:
            o = model[p][2]
            try:
                o.ZOrder = max(0, o.ZOrder + delta)
            except Exception:
                pass
        self.refresh()
