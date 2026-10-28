"""Insert extras: Screenshot (screen clipping), Icons (from the system icon
themes), Quick Tables, and simple SmartArt graphics."""
import glob
import json
import os
import shutil
import subprocess
import tempfile

from gi.repository import Gdk, GdkPixbuf, GLib, Gtk

from . import bridge, docapi


# ------------------------------------------------------------ screenshot
def _grab_screen():
    """The whole screen as a GdkPixbuf (gnome-screenshot when it's there,
    otherwise the X root window)."""
    path = tempfile.mktemp(prefix="folio-shot-", suffix=".png")
    tool = shutil.which("gnome-screenshot")
    if tool:
        try:
            subprocess.run([tool, "-f", path], timeout=10, check=False)
            if os.path.exists(path):
                pb = GdkPixbuf.Pixbuf.new_from_file(path)
                os.remove(path)
                return pb
        except Exception:
            pass
    root = Gdk.get_default_root_window()
    w, h = root.get_width(), root.get_height()
    return Gdk.pixbuf_get_from_window(root, 0, 0, w, h)


def screenshot(win, clip=True):
    win.iconify()

    def capture():
        pb = _grab_screen()
        win.deiconify()
        win.present()
        if pb is None:
            win.dialogs.message("The screen couldn't be captured.")
            return False
        if not clip:
            _insert_pixbuf(win, pb)
        else:
            ClipWindow(win, pb)
        return False
    GLib.timeout_add(700, capture)


def _insert_pixbuf(win, pb):
    path = tempfile.mktemp(prefix="folio-shot-", suffix=".png")
    pb.savev(path, "png", [], [])
    if getattr(win.engine, "native", False):
        from .native import objects
        objects.insert_picture_path(win, path)
        os.unlink(path)
        return
    m = win.engine.model
    win.engine.sync(lambda: docapi.insert_picture(m, path))


class ClipWindow(Gtk.Window):
    """Screen Clipping: drag a rectangle over the frozen screen."""

    def __init__(self, win, pb):
        Gtk.Window.__init__(self)
        self.win, self.pb = win, pb
        self.set_decorated(False)
        self.fullscreen()
        self.set_keep_above(True)
        self.start = self.cur = None
        area = Gtk.DrawingArea()
        area.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK |
                        Gdk.EventMask.POINTER_MOTION_MASK)
        area.connect("draw", self._draw)
        area.connect("button-press-event", self._press)
        area.connect("motion-notify-event", self._motion)
        area.connect("button-release-event", self._release)
        self.connect("key-press-event", lambda w, e: e.keyval == Gdk.KEY_Escape and
                     self.destroy())
        self.add(area)
        self.area = area
        self.show_all()
        w = self.get_window()
        if w is not None:
            w.set_cursor(Gdk.Cursor.new_from_name(w.get_display(), "crosshair"))

    def _draw(self, a, cr):
        Gdk.cairo_set_source_pixbuf(cr, self.pb, 0, 0)
        cr.paint()
        cr.set_source_rgba(1, 1, 1, 0.45)
        cr.rectangle(0, 0, self.pb.get_width(), self.pb.get_height())
        if self.start and self.cur:
            x0, y0 = self.start
            x1, y1 = self.cur
            cr.rectangle(min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0))
            cr.set_fill_rule(1)
        cr.fill()
        if self.start and self.cur:
            cr.set_source_rgb(0.9, 0.1, 0.1)
            cr.set_line_width(1)
            cr.rectangle(min(x0, x1) + 0.5, min(y0, y1) + 0.5, abs(x1 - x0), abs(y1 - y0))
            cr.stroke()
        return False

    def _press(self, a, ev):
        self.start = self.cur = (ev.x, ev.y)

    def _motion(self, a, ev):
        if self.start:
            self.cur = (ev.x, ev.y)
            a.queue_draw()

    def _release(self, a, ev):
        if not self.start:
            return
        x0, y0 = self.start
        x1, y1 = ev.x, ev.y
        self.destroy()
        x, y = int(min(x0, x1)), int(min(y0, y1))
        w, h = int(abs(x1 - x0)), int(abs(y1 - y0))
        if w < 4 or h < 4:
            return
        w = min(w, self.pb.get_width() - x)
        h = min(h, self.pb.get_height() - y)
        _insert_pixbuf(self.win, self.pb.new_subpixbuf(x, y, w, h).copy())


# ------------------------------------------------------------ icons
ICON_DIRS = ["/usr/share/icons/Adwaita/scalable", "/usr/share/icons/Adwaita/symbolic",
             "/usr/share/icons/hicolor/scalable", "/usr/share/icons/Yaru/scalable",
             "/usr/share/icons/ZorinBlue-Light/scalable"]
CATEGORY_NAMES = {"actions": "Actions", "apps": "Apps", "categories": "Categories",
                  "devices": "Devices", "emblems": "Emblems", "emotes": "Faces",
                  "mimetypes": "Files", "places": "Places", "status": "Status", "ui": "Interface"}


def icon_files():
    out = {}
    for base in ICON_DIRS:
        if not os.path.isdir(base):
            continue
        for path in glob.glob(os.path.join(base, "*", "*.svg")):
            cat = os.path.basename(os.path.dirname(path))
            name = os.path.splitext(os.path.basename(path))[0].replace("-symbolic", "")
            out.setdefault((cat, name), path)
    return out


def icons_dialog(win):
    from .widgets import FDialog
    files = icon_files()
    if not files:
        win.dialogs.message("No icon collections were found on this computer.")
        return
    d = FDialog(win, "Insert Icons", buttons=(("Insert", Gtk.ResponseType.OK),
                                             ("Cancel", Gtk.ResponseType.CANCEL)))
    d.set_resizable(True)
    d.set_default_size(720, 520)
    search = Gtk.SearchEntry()
    search.set_placeholder_text("Search icons")
    cats = Gtk.Box(spacing=4)
    catsel = {"v": None}
    d.add(search)
    d.add(cats)
    flow = Gtk.FlowBox()
    flow.set_max_children_per_line(10)
    flow.set_selection_mode(Gtk.SelectionMode.MULTIPLE)
    flow.set_activate_on_single_click(False)
    sw = Gtk.ScrolledWindow()
    sw.set_size_request(680, 400)
    sw.add(flow)
    d.add(sw, expand=True)
    count = Gtk.Label(xalign=0)
    d.add(count)
    keys = sorted(files, key=lambda k: (k[0], k[1]))
    allcats = sorted({c for c, _n in keys})
    for c in ["All"] + allcats:
        b = Gtk.ToggleButton(label=CATEGORY_NAMES.get(c, c.capitalize()))
        b.connect("toggled", lambda w, c=c: (w.get_active() and (catsel.__setitem__(
            "v", None if c == "All" else c), [x.set_active(False) for x in cats.get_children()
                                              if x is not w], fill())))
        cats.pack_start(b, False, False, 0)

    def fill(*_):
        for ch in flow.get_children():
            flow.remove(ch)
        q = search.get_text().strip().lower()
        shown = 0
        for c, n in keys:
            if catsel["v"] and c != catsel["v"]:
                continue
            if q and q not in n.lower():
                continue
            try:
                pb = GdkPixbuf.Pixbuf.new_from_file_at_size(files[(c, n)], 40, 40)
            except Exception:
                continue
            img = Gtk.Image.new_from_pixbuf(pb)
            img.set_tooltip_text(n.replace("-", " "))
            img.path = files[(c, n)]
            flow.add(img)
            shown += 1
            if shown >= 400:
                break
        flow.show_all()
        count.set_text("%d icons%s" % (shown, " (showing the first 400)" if shown >= 400 else
                                       ""))
    search.connect("search-changed", fill)
    fill()
    r = d.ask()
    picks = [ch.get_child().path for ch in flow.get_selected_children()]
    d.done()
    if r != Gtk.ResponseType.OK or not picks:
        return
    if getattr(win.engine, "native", False):
        from .native import objects
        for p in picks:
            objects.insert_picture_path(win, p, size_pt=72)
        return
    m = win.engine.model

    def go():
        for p in picks:
            obj = docapi.insert_picture(m, p)
            try:
                obj.Size = bridge.struct("com.sun.star.awt.Size", Width=2540, Height=2540)
            except Exception:
                pass
    win.engine.sync(go)


# ------------------------------------------------------------ quick tables
QUICK_TABLES = ["Calendar 1", "Double Table", "Matrix", "Tabular List", "With Subheads 1"]


def quick_table(m, name):
    from . import tablestyles
    import calendar
    import datetime
    if name == "Calendar 1":
        today = datetime.date.today()
        vc = docapi.view_cursor(m)
        vc.getText().insertString(vc, today.strftime("%B %Y"), False)
        vc.getText().insertControlCharacter(vc, 0, False)
        weeks = calendar.Calendar(6).monthdayscalendar(today.year, today.month)
        t = tablestyles.insert_table(m, len(weeks) + 1, 7)
        for c, day in enumerate(["S", "M", "T", "W", "T", "F", "S"]):
            t.getCellByPosition(c, 0).setString(day)
        for r, week in enumerate(weeks, start=1):
            for c, day in enumerate(week):
                t.getCellByPosition(c, r).setString(str(day) if day else "")
        return t
    data = {
        "Double Table": [["College", "New students", "Graduating students", "Change"],
                         ["Cedar University", "110", "103", "+7"],
                         ["Elm College", "223", "214", "+9"],
                         ["Maple Academy", "197", "120", "+77"],
                         ["Pine College", "134", "121", "+13"],
                         ["Total", "998", "908", "90"]],
        "Matrix": [["City or Town", "Point A", "Point B", "Point C", "Point D"],
                   ["Point A", "—", "", "", ""], ["Point B", "87", "—", "", ""],
                   ["Point C", "64", "56", "—", ""], ["Point D", "37", "32", "91", "—"]],
        "Tabular List": [["ITEM", "NEEDED"], ["Books", "1"], ["Magazines", "3"],
                         ["Notebooks", "1"], ["Paper pads", "1"], ["Pens", "3"],
                         ["Pencils", "2"], ["Highlighter", "2 colors"], ["Scissors", "1 pair"]],
        "With Subheads 1": [["College", "New students", "Graduating students", "Change"],
                            ["Undergraduate", "", "", ""],
                            ["Cedar University", "110", "103", "+7"],
                            ["Oak Institute", "202", "210", "-8"],
                            ["Graduate", "", "", ""],
                            ["Cedar University", "24", "20", "+4"],
                            ["Total", "336", "333", "3"]],
    }[name]
    t = tablestyles.insert_table(m, len(data), len(data[0]))
    for r, row in enumerate(data):
        for c, val in enumerate(row):
            t.getCellByPosition(c, r).setString(val)
    try:
        tablestyles.apply(m, "list", tablestyles.ACCENTS[1] if hasattr(
            tablestyles, "ACCENTS") else 0x4472C4, {"header": True, "banded_rows": True,
                                                    "first_col": False, "total":
                                                    name in ("Double Table", "With Subheads 1"),
                                                    "last_col": False, "banded_cols": False},
                          t=t)
    except Exception as e:
        print("quick table style:", e)
    return t


# ------------------------------------------------------------ SmartArt
LAYOUTS = [("List", "Basic Block List", "blocks"), ("List", "Vertical Box List", "vlist"),
           ("Process", "Basic Process", "process"),
           ("Process", "Basic Chevron Process", "chevron"),
           ("Process", "Step Up Process", "stepup"),
           ("Cycle", "Basic Cycle", "cycle"), ("Cycle", "Basic Radial", "radial"),
           ("Hierarchy", "Organization Chart", "hierarchy"),
           ("Hierarchy", "Horizontal Hierarchy", "hhierarchy"),
           ("Relationship", "Basic Venn", "venn"), ("Matrix", "Basic Matrix", "matrix"),
           ("Matrix", "Grid Matrix", "gridmatrix"),
           ("Pyramid", "Basic Pyramid", "pyramid"), ("Pyramid", "Inverted Pyramid", "invpyramid"),
           ("Picture", "Picture Caption List", "picturelist")]
CATEGORIES = ["All", "List", "Process", "Cycle", "Hierarchy", "Relationship", "Matrix",
              "Pyramid", "Picture"]
STYLES = [("Simple Fill", {}), ("White Outline", {"line": 0xFFFFFF, "lw": 53}),
          ("Subtle Effect", {"alpha": 15}), ("Moderate Effect", {"shadow": True}),
          ("Intense Effect", {"shadow": True, "line": 0x000000, "lw": 26})]
SMART_COLORS = [0x4472C4, 0xED7D31, 0xA5A5A5, 0xFFC000, 0x5B9BD5, 0x70AD47]
DEFAULT_LINES = {"blocks": ["Text", "Text", "Text", "Text", "Text"],
                 "process": ["Text", "Text", "Text"], "cycle": ["Text"] * 5,
                 "hierarchy": ["Text", "\tText", "\tText", "\tText"],
                 "venn": ["Text", "Text", "Text"], "pyramid": ["Text", "Text", "Text"],
                 "vlist": ["Text", "Text", "Text"], "chevron": ["Text", "Text", "Text"],
                 "stepup": ["Text", "Text", "Text"], "radial": ["Text", "\tText", "\tText",
                                                              "\tText", "\tText"],
                 "hhierarchy": ["Text", "\tText", "\tText"],
                 "matrix": ["Text", "Text", "Text", "Text"],
                 "gridmatrix": ["Text", "Text", "Text", "Text"],
                 "invpyramid": ["Text", "Text", "Text"],
                 "picturelist": ["Text", "Text", "Text"]}


def _key(name):
    return "SmartArt:" + name


def smartart_info(m, obj):
    try:
        return json.loads(docapi._doc_setting(m, _key(obj.Name), "") or "null")
    except Exception:
        return None


def is_smartart(m, obj):
    try:
        return obj.Name.startswith("SmartArt ") and smartart_info(m, obj) is not None
    except Exception:
        return False


def smartart_of(m, obj):
    """The SmartArt graphic obj is, or is a shape of (None otherwise)."""
    if obj is None:
        return None
    if is_smartart(m, obj):
        return obj
    try:
        dp = m.getDrawPage()
        for i in range(dp.getCount()):
            o = dp.getByIndex(i)
            if (o.Name or "").startswith("SmartArt ") and hasattr(o, "getCount"):
                for k in range(o.getCount()):
                    if o.getByIndex(k) == obj:
                        return o if is_smartart(m, o) else None
    except Exception:
        pass
    return None


def _build(m, layout, lines, color, width=14000, height=8000):
    """[(shape spec)] for the layout: (kind, x, y, w, h, fill, text, alpha)."""
    items = [(len(l) - len(l.lstrip("\t")), l.strip()) for l in lines if l.strip()]
    tops = [t for lvl, t in items if lvl == 0] or ["Text"]
    n = len(tops)
    out = []
    if layout == "blocks":
        cols = min(3, n)
        rows = (n + cols - 1) // cols
        bw, bh = width / cols, height / rows
        for i, t in enumerate(tops):
            r, c = divmod(i, cols)
            out.append(("rectangle", c * bw + 150, r * bh + 150, bw - 300, bh - 300, color, t, 0))
    elif layout == "process":
        bw = width / (n * 1.5 - 0.5)
        for i, t in enumerate(tops):
            x = i * bw * 1.5
            out.append(("round-rectangle", x, height * 0.3, bw, height * 0.4, color, t, 0))
            if i < n - 1:
                out.append(("right-arrow", x + bw * 1.08, height * 0.42, bw * 0.34,
                            height * 0.16, 0xBFBFBF, "", 0))
    elif layout == "cycle":
        import math
        rx, ry = width / 2 - 1600, height / 2 - 1000
        cx, cy = width / 2, height / 2
        for i, t in enumerate(tops):
            a = -math.pi / 2 + i * 2 * math.pi / n
            out.append(("ellipse", cx + rx * math.cos(a) - 1300, cy + ry * math.sin(a) - 800,
                        2600, 1600, color, t, 0))
            a2 = a + math.pi / n
            out.append(("right-arrow", cx + rx * 0.82 * math.cos(a2) - 400,
                        cy + ry * 0.82 * math.sin(a2) - 200, 800, 400, 0xBFBFBF, "", 0))
    elif layout == "hierarchy":
        root = items[0][1] if items else "Text"
        kids = [t for lvl, t in items[1:] if lvl >= 1] or ["Text"]
        bw = min(3600, width / max(1, len(kids)) - 400)
        out.append(("rectangle", width / 2 - bw / 2, 300, bw, 1800, color, root, 0))
        span = len(kids) * (bw + 400) - 400
        x0 = width / 2 - span / 2
        for i, t in enumerate(kids):
            x = x0 + i * (bw + 400)
            out.append(("rectangle", x, 3600, bw, 1800, color, t, 0))
            out.append(("line", width / 2, 2100, x + bw / 2 - width / 2, 1500, 0x808080, "",
                        0))
    elif layout == "venn":
        import math
        rr = min(width, height) * 0.32
        cx, cy = width / 2, height / 2
        for i, t in enumerate(tops):
            a = -math.pi / 2 + i * 2 * math.pi / n
            out.append(("ellipse", cx + rr * 0.55 * math.cos(a) - rr,
                        cy + rr * 0.55 * math.sin(a) - rr, rr * 2, rr * 2,
                        SMART_COLORS[i % len(SMART_COLORS)], t, 45))
    elif layout == "pyramid":
        lh = height / n
        for i, t in enumerate(tops):
            w = width * (i + 1) / n
            out.append(("trapezoid" if i else "isosceles-triangle", width / 2 - w / 2,
                        i * lh, w, lh - 60, color, t, 0))
    elif layout == "invpyramid":
        lh = height / n
        for i, t in enumerate(tops):
            w = width * (n - i) / n
            out.append(("rectangle", width / 2 - w / 2, i * lh, w, lh - 60, color, t, 0))
    elif layout == "vlist":
        bh = height / n
        for i, t in enumerate(tops):
            out.append(("round-rectangle", 300, i * bh + 100, width - 600, bh - 200, color,
                        t, 0))
    elif layout == "chevron":
        bw = width / n
        for i, t in enumerate(tops):
            out.append(("chevron", i * bw, height * 0.3, bw * 1.05, height * 0.4, color, t, 0))
    elif layout == "stepup":
        bw = width / n
        for i, t in enumerate(tops):
            h = height * (0.4 + 0.6 * (i + 1) / n)
            out.append(("rectangle", i * bw + 100, height - h, bw - 200, h, color, t, 0))
    elif layout == "radial":
        import math
        center = items[0][1] if items else "Text"
        kids = [t for lvl, t in items[1:] if lvl >= 1] or ["Text"]
        cx, cy = width / 2, height / 2
        out.append(("ellipse", cx - 1500, cy - 1500, 3000, 3000, color, center, 0))
        r = min(width, height) / 2 - 1100
        for i, t in enumerate(kids):
            a = -math.pi / 2 + i * 2 * math.pi / len(kids)
            out.append(("ellipse", cx + r * math.cos(a) - 1000, cy + r * math.sin(a) - 1000,
                        2000, 2000, color, t, 0))
    elif layout == "hhierarchy":
        root = items[0][1] if items else "Text"
        kids = [t for lvl, t in items[1:] if lvl >= 1] or ["Text"]
        bh = min(1800, height / max(1, len(kids)) - 300)
        out.append(("rectangle", 300, height / 2 - bh / 2, 3600, bh, color, root, 0))
        span = len(kids) * (bh + 300) - 300
        y0 = height / 2 - span / 2
        for i, t in enumerate(kids):
            y = y0 + i * (bh + 300)
            out.append(("rectangle", width - 3900, y, 3600, bh, color, t, 0))
            out.append(("line", 3900, height / 2, width - 7800, y + bh / 2 - height / 2,
                        0x808080, "", 0))
    elif layout in ("matrix", "gridmatrix"):
        cells = tops[:4] + ["Text"] * (4 - min(4, len(tops)))
        bw, bh = width / 2, height / 2
        for i, t in enumerate(cells):
            r, c = divmod(i, 2)
            gap = 60 if layout == "gridmatrix" else 200
            out.append(("rectangle" if layout == "gridmatrix" else "round-rectangle",
                        c * bw + gap, r * bh + gap, bw - 2 * gap, bh - 2 * gap,
                        SMART_COLORS[i % len(SMART_COLORS)] if layout == "matrix" else color,
                        t, 0))
    elif layout == "picturelist":
        bw = width / n
        for i, t in enumerate(tops):
            out.append(("rectangle", i * bw + 200, 200, bw - 400, height * 0.6, 0xD9E2F3,
                        "[Picture]", 0))
            out.append(("rectangle", i * bw + 200, height * 0.65, bw - 400, height * 0.25,
                        color, t, 0))
    return out


def _items(lines):
    return [(len(l) - len(l.lstrip("\t")), l.strip()) for l in lines if l.strip()]


def _lines(items):
    return ["\t" * lvl + t for lvl, t in items]


def _block(items, i):
    """The item and its sub-items: (start, end)."""
    lvl = items[i][0]
    j = i + 1
    while j < len(items) and items[j][0] > lvl:
        j += 1
    return i, j


def edit_items(lines, op, cur=None):
    """Add Shape After / Before / Above / Below, Promote, Demote, Move Up /
    Down on the item `cur` (the last one when none is selected)."""
    items = _items(lines)
    if not items:
        items = [(0, "Text")]
    i = len(items) - 1 if cur is None or cur >= len(items) else cur
    lvl = items[i][0]
    a, b = _block(items, i)
    if op == "after":
        items.insert(b, (lvl, "Text"))
    elif op == "before":
        items.insert(a, (lvl, "Text"))
    elif op == "above":
        for k in range(a, b):
            items[k] = (items[k][0] + 1, items[k][1])
        items.insert(a, (lvl, "Text"))
    elif op == "below":
        items.insert(b, (lvl + 1, "Text"))
    elif op == "bullet":
        items.insert(b, (lvl + 1, "Text"))
    elif op == "promote" and lvl > 0:
        for k in range(a, b):
            items[k] = (items[k][0] - 1, items[k][1])
    elif op == "demote" and i > 0 and items[i - 1][0] >= lvl:
        for k in range(a, b):
            items[k] = (items[k][0] + 1, items[k][1])
    elif op == "up":
        p = i - 1
        while p >= 0 and items[p][0] > lvl:
            p -= 1
        if p >= 0 and items[p][0] == lvl:
            blk = items[a:b]
            del items[a:b]
            items[p:p] = blk
    elif op == "down":
        if b < len(items) and items[b][0] == lvl:
            _a2, b2 = _block(items, b)
            blk = items[a:b]
            del items[a:b]
            pos = b2 - (b - a)
            items[pos:pos] = blk
    return _lines(items)


def insert_smartart(win, layout, lines=None, color=None, replace=None, extra=None):
    """Insert (or redraw) a SmartArt graphic: a group of shapes. extra:
    {'style': n, 'rtl': bool, 'colorful': bool}."""
    from . import drawing
    m = win.engine.model
    lines = lines or DEFAULT_LINES[layout]
    color = color or SMART_COLORS[0]
    extra = dict(extra or {})
    style = STYLES[extra.get("style", 0) % len(STYLES)][1]
    rtl = extra.get("rtl", False)
    colorful = extra.get("colorful", False)
    um = m.getUndoManager()
    um.enterUndoContext("SmartArt")
    try:
        page_no, ox, oy = 1, 2540, 3000
        name = None
        if replace is not None:
            name = replace.Name
            try:
                page_no = replace.AnchorPageNo or 1
                ox, oy = replace.HoriOrientPosition, replace.VertOrientPosition
            except Exception:
                pass
            m.getDrawPage().remove(replace)
        else:
            try:
                page_no = docapi.read_cursor(m).getPage()
                ps = docapi.page_setup(m)
                ox, oy = ps["left"], ps["top"] + 1000
            except Exception:
                pass
        coll = bridge.create("com.sun.star.drawing.ShapeCollection")
        k_item = 0
        for kind, x, y, w, h, fill, text, alpha in _build(m, layout, lines, color):
            if rtl:
                x = 14000 - x - w if kind != "line" else 14000 - x
                if kind == "line":
                    w = -w
                if kind == "right-arrow":
                    kind = "left-arrow"
            if colorful and text and fill == color:
                fill = SMART_COLORS[k_item % len(SMART_COLORS)]
            if text:
                k_item += 1
            if style.get("alpha") and not alpha:
                alpha = style["alpha"]
            if kind == "line":
                sh = drawing.insert_shape(m, "line", page_no, int(ox + x), int(oy + y), int(w),
                                          int(h))
                sh.LineColor = fill
            else:
                sh = drawing.insert_shape(m, kind, page_no, int(ox + x), int(oy + y), int(w),
                                          int(h))
                sh.FillColor = fill
                sh.LineColor = style.get("line", 0xFFFFFF)
                if style.get("lw"):
                    sh.LineWidth = style["lw"]
                if style.get("shadow"):
                    try:
                        sh.Shadow = True
                        sh.ShadowColor = 0x808080
                        sh.ShadowXDistance = sh.ShadowYDistance = 100
                        sh.ShadowTransparence = 50
                    except Exception:
                        pass
                if alpha:
                    sh.FillTransparence = alpha
                size = sh.Size
                for prop in ("TextAutoGrowHeight", "TextAutoGrowWidth"):
                    try:
                        setattr(sh, prop, False)
                    except Exception:
                        pass
                if text:
                    sh.setString(text)
                    sh.Size = size
                    try:
                        sh.CharColor = 0xFFFFFF if not alpha else 0x262626
                        sh.CharHeight = 14.0
                        sh.ParaAdjust = 3
                        sh.TextVerticalAdjust = bridge.enum(
                            "com.sun.star.drawing.TextVerticalAdjust", "CENTER")
                    except Exception:
                        pass
            coll.add(sh)
        group = m.getDrawPage().group(coll)
        if name is None:
            n = 1
            dp = m.getDrawPage()
            names = {dp.getByIndex(i).Name for i in range(dp.getCount())}
            while "SmartArt %d" % n in names:
                n += 1
            name = "SmartArt %d" % n
        group.Name = name
        docapi._set_doc_setting(m, _key(name), json.dumps(
            dict(extra, layout=layout, lines=lines, color=color)))
        docapi.controller(m).select(group)
        return group
    finally:
        um.leaveUndoContext()


def smartart_dialog(win):
    from .widgets import FDialog
    d = FDialog(win, "Choose a SmartArt Graphic")
    hb = Gtk.Box(spacing=10)
    cats = Gtk.ListBox()
    for c in CATEGORIES:
        row = Gtk.ListBoxRow()
        row.add(Gtk.Label(label=c, xalign=0, margin=6))
        cats.add(row)
    hb.pack_start(cats, False, False, 0)
    lb = Gtk.ListBox()
    shown = list(range(len(LAYOUTS)))

    def fill_layouts(*_):
        row = cats.get_selected_row()
        c = CATEGORIES[row.get_index()] if row else "All"
        for ch in lb.get_children():
            lb.remove(ch)
        shown[:] = [i for i, (cat, _n, _k) in enumerate(LAYOUTS) if c in ("All", cat)]
        for i in shown:
            r = Gtk.ListBoxRow()
            r.add(Gtk.Label(label=LAYOUTS[i][1], xalign=0, margin=6))
            lb.add(r)
        lb.show_all()
        if shown:
            lb.select_row(lb.get_row_at_index(0))
    cats.connect("row-selected", fill_layouts)
    lsw = Gtk.ScrolledWindow()
    lsw.set_size_request(200, 260)
    lsw.add(lb)
    preview = Gtk.DrawingArea()
    preview.set_size_request(380, 260)
    title = Gtk.Label(xalign=0)
    sel = {"i": 0}

    def draw(a, cr):
        W, H = a.get_allocated_width(), a.get_allocated_height()
        cr.set_source_rgb(1, 1, 1)
        cr.paint()
        layout = LAYOUTS[sel["i"]][2]
        sx, sy = W / 15000.0, H / 9000.0
        import math
        for kind, x, y, w, h, fill, text, alpha in _build(None, layout, DEFAULT_LINES[layout],
                                                            SMART_COLORS[0]):
            r, g, b = ((fill >> 16) & 255) / 255.0, ((fill >> 8) & 255) / 255.0, \
                (fill & 255) / 255.0
            cr.set_source_rgba(r, g, b, 1 - alpha / 100.0)
            X, Y, Wd, Ht = 400 * sx + x * sx, 400 * sy + y * sy, w * sx, h * sy
            if kind == "ellipse":
                cr.save()
                cr.translate(X + Wd / 2, Y + Ht / 2)
                cr.scale(max(1, Wd / 2), max(1, Ht / 2))
                cr.arc(0, 0, 1, 0, 2 * math.pi)
                cr.restore()
                cr.fill()
            elif kind == "line":
                cr.move_to(X, Y)
                cr.line_to(X + Wd, Y + Ht)
                cr.stroke()
            else:
                cr.rectangle(X, Y, Wd, Ht)
                cr.fill()
        return False
    preview.connect("draw", draw)

    def pick(_lb, row):
        if row is None:
            return
        sel["i"] = shown[row.get_index()]
        title.set_markup("<b>%s</b>" % LAYOUTS[sel["i"]][1])
        preview.queue_draw()
    lb.connect("row-selected", pick)
    lb.connect("row-activated", lambda *_: d.response(Gtk.ResponseType.OK))
    hb.pack_start(lsw, False, False, 0)
    v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    fr = Gtk.Frame()
    fr.add(preview)
    v.pack_start(fr, True, True, 0)
    v.pack_start(title, False, False, 0)
    hb.pack_start(v, True, True, 0)
    d.add(hb, expand=True)
    cats.select_row(cats.get_row_at_index(0))
    r = d.ask()
    idx = sel["i"]
    d.done()
    if r == Gtk.ResponseType.OK:
        if getattr(win.engine, "native", False):
            from .native import smartart
            smartart.insert(win, LAYOUTS[idx][2])
        else:
            win.engine.sync(lambda: insert_smartart(win, LAYOUTS[idx][2]))


def text_pane(win, group):
    """Type your text here: one line per shape (Tab for a level below)."""
    from .widgets import FDialog
    m = win.engine.model
    info = smartart_info(m, group)
    if info is None:
        return
    d = FDialog(win, "Type your text here")
    tv = Gtk.TextView()
    tv.set_size_request(360, 220)
    tv.get_buffer().set_text("\n".join(info["lines"]))
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
        win.engine.sync(lambda: insert_smartart(win, info["layout"], lines, info["color"],
                                                replace=group))
    d.done()


def _extra(info):
    return {k: v for k, v in info.items() if k not in ("layout", "lines", "color")}


def change_layout(win, group, layout=None, color=None, **extra):
    m = win.engine.model
    info = smartart_info(m, group)
    if info is None:
        return
    ex = _extra(info)
    ex.update(extra)
    if color is not None:
        ex["colorful"] = False
    insert_smartart(win, layout or info["layout"], info["lines"], color or info["color"],
                    replace=group, extra=ex)


def _current_item(m, group):
    """Which item (shape with text) of the graphic is selected, if any."""
    try:
        sel = docapi.controller(m).getSelection()
        if sel is None or sel == group:
            return None
        shp = sel.getByIndex(0) if hasattr(sel, "getByIndex") else sel
        k = 0
        for i in range(group.getCount()):
            sh = group.getByIndex(i)
            if not sh.getString():
                continue
            if sh == shp:
                return k
            k += 1
    except Exception:
        pass
    return None


def edit_graphic(win, group, op):
    m = win.engine.model
    info = smartart_info(m, group)
    if info is None:
        return
    lines = edit_items(info["lines"], op, _current_item(m, group))
    insert_smartart(win, info["layout"], lines, info["color"], replace=group,
                    extra=_extra(info))


def reset_graphic(win, group):
    m = win.engine.model
    info = smartart_info(m, group)
    if info is None:
        return
    insert_smartart(win, info["layout"], info["lines"], SMART_COLORS[0], replace=group)


def convert_to_text(win, group):
    m = win.engine.model
    info = smartart_info(m, group)
    if info is None:
        return
    um = m.getUndoManager()
    um.enterUndoContext("Convert to Text")
    try:
        anchor = None
        try:
            anchor = group.getAnchor()
        except Exception:
            pass
        m.getDrawPage().remove(group)
        vc = docapi.view_cursor(m)
        if anchor is not None:
            vc.gotoRange(anchor.getStart(), False)
        text = vc.getText()
        cur = text.createTextCursorByRange(vc.getStart())
        items = _items(info["lines"])
        for lvl, t in items:
            text.insertString(cur, t, False)
            text.insertControlCharacter(cur, 0, False)
        c = text.createTextCursorByRange(vc.getStart())
        c.gotoRange(cur.getStart(), True)
        docapi.controller(m).select(c)
    finally:
        um.leaveUndoContext()
    win.actions.do_bullets()

    def levels():
        vc2 = docapi.view_cursor(m)
        en = vc2.createEnumeration() if hasattr(vc2, "createEnumeration") else None
        c2 = vc2.getText().createTextCursorByRange(vc2.getStart())
        c2.gotoRange(vc2.getEnd(), True)
        en = c2.createEnumeration()
        for (lvl, _t) in items:
            if not en.hasMoreElements():
                break
            p = en.nextElement()
            try:
                p.NumberingLevel = lvl
            except Exception:
                pass
    win.engine.sync(levels)


def convert_to_shapes(win, group):
    m = win.engine.model
    try:
        docapi._set_doc_setting(m, _key(group.Name), "")
        n = 1
        dp = m.getDrawPage()
        names = {dp.getByIndex(i).Name for i in range(dp.getCount())}
        while "Group %d" % n in names:
            n += 1
        group.Name = "Group %d" % n
        docapi.controller(m).select(group)
        win.update_object_tabs()
    except Exception as e:
        print("convert to shapes:", e)
