"""Table styles (Table Design tab): Plain, Grid and List families in the
theme accent colours, with the Table Style Options (header row, banded rows,
first column...). One function describes every cell, so the gallery
thumbnails and the document use the same rules."""
import json

from . import bridge, docapi

ACCENTS = [("", 0x000000), ("Accent 1", 0x4472C4), ("Accent 2", 0xED7D31),
           ("Accent 3", 0xA5A5A5), ("Accent 4", 0xFFC000), ("Accent 5", 0x5B9BD5),
           ("Accent 6", 0x70AD47)]

PLAIN = [("Table Grid", "grid"), ("Plain Table 1", "plain1"), ("Plain Table 2", "plain2"),
         ("Plain Table 3", "plain3"), ("Plain Table 4", "plain4")]
GRID = [("Grid Table 1 Light", "grid1"), ("Grid Table 2", "grid2"), ("Grid Table 3", "grid3"),
        ("Grid Table 4", "grid4"), ("Grid Table 5 Dark", "grid5")]
LIST = [("List Table 1 Light", "list1"), ("List Table 2", "list2"), ("List Table 3", "list3"),
        ("List Table 4", "list4"), ("List Table 5 Dark", "list5")]

DEFAULT_OPTS = {"header": True, "total": False, "banded_rows": True, "first_col": True,
                "last_col": False, "banded_cols": False}

WHITE, BLACK = 0xFFFFFF, 0x000000


def tint(c, t):
    """Mix colour c with white: t=0 -> c, t=1 -> white."""
    r, g, b = (c >> 16) & 255, (c >> 8) & 255, c & 255
    r, g, b = (int(v + (255 - v) * t) for v in (r, g, b))
    return (r << 16) | (g << 8) | b


def all_styles():
    """[(section, [(name, kind, accent)])]"""
    out = [("Plain Tables", [(n, k, BLACK) for n, k in PLAIN])]
    for section, family in (("Grid Tables", GRID), ("List Tables", LIST)):
        items = []
        for n, k in family:
            for an, ac in ACCENTS:
                items.append(("%s%s" % (n, " - " + an if an else ""), k, ac))
        out.append((section, items))
    return out


def cell(kind, accent, opts, r, c, rows, cols):
    """How one cell looks: dict(fill, color, bold, top, bottom, left, right), each
    border None or (width_pt, colour)."""
    o = dict(DEFAULT_OPTS, **(opts or {}))
    head = o["header"] and r == 0
    total = o["total"] and r == rows - 1 and rows > 1
    first = o["first_col"] and c == 0
    last = o["last_col"] and c == cols - 1 and cols > 1
    body_r = r - (1 if o["header"] else 0)
    band_r = o["banded_rows"] and not head and not total and body_r % 2 == 0
    band_c = o["banded_cols"] and not head and not total and c % 2 == 0
    a = accent if accent != BLACK else 0x000000
    gray = accent == BLACK
    light = tint(a, 0.8) if not gray else 0xF2F2F2
    mid = tint(a, 0.6) if not gray else 0xBFBFBF
    dark = tint(a, 0.4) if not gray else 0x7F7F7F
    s = dict(fill=-1, color=-1, bold=head or total or first or last,
             top=None, bottom=None, left=None, right=None)
    thin = 0.5

    def box(color, w=thin):
        for side in ("top", "bottom", "left", "right"):
            s[side] = (w, color)

    if kind == "grid":
        box(BLACK)
        s["bold"] = False
    elif kind == "plain1":
        box(0xBFBFBF)
        if band_r or band_c:
            s["fill"] = 0xF2F2F2
    elif kind == "plain2":
        s["bottom"] = (thin, 0x7F7F7F)
        if r == 0:
            s["top"] = (thin, 0x7F7F7F)
        if c > 0 and o["banded_cols"]:
            s["left"] = (thin, 0x7F7F7F)
    elif kind == "plain3":
        if head:
            s["bottom"] = (thin, 0x7F7F7F)
        if band_r or band_c:
            s["fill"] = 0xF2F2F2
    elif kind == "plain4":
        if band_r or band_c:
            s["fill"] = 0xF2F2F2
    elif kind == "grid1":
        box(mid)
        if head:
            s["bottom"] = (1.5, dark)
        if total:
            s["top"] = (1.5, dark)
    elif kind == "grid2":
        s["top"] = s["bottom"] = (thin, dark)
        if c > 0:
            s["left"] = (thin, dark)
        if head:
            s["top"] = None
            s["bottom"] = (1.5, dark)
        if band_r or band_c:
            s["fill"] = light
    elif kind == "grid3":
        box(dark)
        if head:
            s["top"] = s["left"] = s["right"] = None
        if band_r or band_c:
            s["fill"] = light
    elif kind == "grid4":
        box(dark)
        if band_r or band_c:
            s["fill"] = light
        if head:
            s["fill"], s["color"] = a, WHITE
            box(a)
    elif kind == "grid5":
        box(WHITE)
        s["fill"] = mid if (band_r or band_c) else light
        if head or first or last or total:
            s["fill"], s["color"] = a, WHITE
    elif kind == "list1":
        if head:
            s["bottom"] = (thin, dark)
        if total:
            s["top"] = (thin, dark)
        if band_r or band_c:
            s["fill"] = light
    elif kind == "list2":
        s["top"] = s["bottom"] = (thin, dark)
        if band_r or band_c:
            s["fill"] = light
    elif kind == "list3":
        if r == 0:
            s["top"] = (thin, a)
        if r == rows - 1:
            s["bottom"] = (thin, a)
        if c == 0:
            s["left"] = (thin, a)
        if c == cols - 1:
            s["right"] = (thin, a)
        if head:
            s["fill"], s["color"] = a, WHITE
        if total:
            s["top"] = (1.5, a)
    elif kind == "list4":
        s["top"] = s["bottom"] = (thin, dark)
        if c == 0:
            s["left"] = (thin, dark)
        if c == cols - 1:
            s["right"] = (thin, dark)
        if band_r or band_c:
            s["fill"] = light
        if head:
            s["fill"], s["color"] = a, WHITE
            s["top"] = s["bottom"] = s["left"] = s["right"] = (thin, a)
    elif kind == "list5":
        s["fill"], s["color"] = a, WHITE
        if head:
            s["bottom"] = (2.25, WHITE)
        if first and not head:
            s["right"] = (thin, WHITE)
        if band_r and not head:
            s["top"] = s["bottom"] = (thin, WHITE)
    if kind != "grid" and head and kind in ("plain3",):
        s["caps"] = True
    if total and kind not in ("grid1", "list1", "list3", "list5"):
        s["top"] = (1.5, dark if not gray else BLACK)
    return s


# ---------------------------------------------------------------- document
def _key(t):
    return "TableStyle:" + t.getName()


def get_style(m, t):
    v = docapi._doc_setting(m, _key(t), "")
    try:
        d = json.loads(v) if v else {}
    except ValueError:
        d = {}
    return d.get("kind", "grid"), d.get("accent", BLACK), dict(DEFAULT_OPTS, **d.get("opts", {}))


def apply(m, kind=None, accent=None, opts=None, t=None):
    t = t or docapi.table_at_cursor(m)
    if t is None:
        return False
    k0, a0, o0 = get_style(m, t)
    kind = kind or k0
    accent = a0 if accent is None else accent
    o = dict(o0, **(opts or {}))
    um = m.getUndoManager()
    um.enterUndoContext("Table Style")
    try:
        rows = t.getRows().getCount()
        cols = t.getColumns().getCount()
        empty = bridge.struct("com.sun.star.table.BorderLine2")
        try:
            tb = t.TableBorder2
            for side in ("Top", "Bottom", "Left", "Right", "Horizontal", "Vertical"):
                setattr(tb, side + "Line", empty)
                setattr(tb, "Is%sLineValid" % side, True)
            t.TableBorder2 = tb
        except Exception as e:
            print("table border:", e)
        for r in range(rows):
            for c in range(cols):
                try:
                    ce = t.getCellByPosition(c, r)
                except Exception:
                    continue           # merged cells
                s = cell(kind, accent, o, r, c, rows, cols)
                ce.BackColor = s["fill"]
                try:
                    ce.BackTransparent = s["fill"] == -1
                except Exception:
                    pass
                for side in ("top", "bottom", "left", "right"):
                    b = s[side]
                    setattr(ce, side.capitalize() + "Border",
                            docapi._line(b[0], b[1]) if b else empty)
                cur = ce.createTextCursor()
                cur.gotoStart(False)
                cur.gotoEnd(True)
                cur.CharColor = s["color"]
                cur.CharWeight = 150.0 if s["bold"] else 100.0
                cur.CharCaseMap = 1 if s.get("caps") else 0
                # table styles use single spacing with no space after
                cur.ParaBottomMargin = 0
                cur.ParaTopMargin = 0
                ls = cur.ParaLineSpacing
                ls.Mode, ls.Height = 0, 100
                cur.ParaLineSpacing = ls
        try:
            t.RepeatHeadline = bool(o["header"])
        except Exception:
            pass
        docapi._set_doc_setting(m, _key(t), json.dumps({"kind": kind, "accent": accent,
                                                         "opts": o}))
    finally:
        um.leaveUndoContext()
    return True


def set_option(m, name, value):
    t = docapi.table_at_cursor(m)
    if t is None:
        return False
    return apply(m, opts={name: bool(value)}, t=t)


def options(m):
    t = docapi.table_at_cursor(m)
    if t is None:
        return None
    return get_style(m, t)


def insert_table(m, rows, cols):
    """Insert a table with the default 'Table Grid' look, as one undo step,
    and put the cursor in its first cell."""
    um = m.getUndoManager()
    um.enterUndoContext("Insert Table")
    try:
        vc = docapi.view_cursor(m)
        t = m.createInstance("com.sun.star.text.TextTable")
        t.initialize(int(rows), int(cols))
        vc.getText().insertTextContent(vc, t, False)
        # cells use the Normal style, like the original (not centred headings)
        for name in t.getCellNames():
            cur = t.getCellByName(name).createTextCursor()
            cur.gotoEnd(True)
            cur.ParaStyleName = "Standard"
        apply(m, "grid", BLACK, dict(DEFAULT_OPTS), t=t)
        vc.gotoRange(t.getCellByPosition(0, 0).getStart(), False)
        return t
    finally:
        um.leaveUndoContext()
