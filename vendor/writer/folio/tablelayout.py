"""Table Layout tab: cell size, alignment grid, text direction, cell margins,
sort, repeat header rows, convert to text, formulas, AutoFit."""
import re

from gi.repository import Gtk

from . import bridge, docapi
from .widgets import FDialog, LengthSpin, combo, grid, heading


def current(m):
    vc = docapi.read_cursor(m)
    try:
        return vc.TextTable, vc.Cell
    except Exception:
        return None, None


def _rc(name):
    """'B3' -> (row 2, col 1). Nested names ('A1.1.1') use the outer part."""
    mm = re.match(r"([A-Za-z]+)(\d+)", name)
    letters, num = mm.group(1), int(mm.group(2))
    col = 0
    for ch in letters.upper():
        col = col * 26 + (ord(ch) - 64)
    return num - 1, col - 1


def _name(row, col):
    s = ""
    col += 1
    while col:
        col, rem = divmod(col - 1, 26)
        s = chr(65 + rem) + s
    return "%s%d" % (s, row + 1)


def _selected_cells(m, t):
    """Names of the selected cells (or the cell with the cursor)."""
    try:
        sel = docapi.controller(m).getSelection()
        names = getattr(sel, "CellRangeName", None) if hasattr(sel, "CellRangeName") else None
    except Exception:
        names = None
    vc = docapi.read_cursor(m)
    try:
        sel = docapi.controller(m).getSelection()
        rn = sel.getRangeName() if hasattr(sel, "getRangeName") else None
    except Exception:
        rn = None
    try:
        if rn and ":" in rn:
            c1, c2 = rn.split(":")
        else:
            rng = vc.getStart()
            c1 = rng.Cell.CellName
            c2 = vc.getEnd().Cell.CellName
    except Exception:
        try:
            c1 = c2 = vc.Cell.CellName
        except Exception:
            return []
    r1, k1 = _rc(c1)
    r2, k2 = _rc(c2)
    out = []
    for r in range(min(r1, r2), max(r1, r2) + 1):
        for k in range(min(k1, k2), max(k1, k2) + 1):
            out.append(_name(r, k))
    return [n for n in out if n in t.getCellNames()] or [c1]


# ------------------------------------------------------------ size
def _table_width(m, t):
    """The table's real width (a full-width table reports a bogus Width)."""
    if t.HoriOrient == 6:
        ps = docapi.page_setup(m)
        return ps["width"] - ps["left"] - ps["right"] - t.LeftMargin - t.RightMargin
    return t.Width


def cell_size(m):
    t, cell = current(m)
    if t is None:
        return None
    r, c = _rc(cell.CellName)
    row = t.getRows().getByIndex(r)
    seps = list(t.TableColumnSeparators or ())
    width = _table_width(m, t)
    rel = t.TableColumnRelativeSum or 10000
    pos = [0] + [s.Position for s in seps] + [rel]
    c = min(c, len(pos) - 2)
    col_w = int((pos[c + 1] - pos[c]) * width / rel)
    h = row.Height
    if row.IsAutoHeight and h < 300:
        # automatic height: show what one line of text takes
        try:
            pt = cell.createTextCursor().CharHeight or 11
        except Exception:
            pt = 11
        h = int(pt * 1.22 * 2540 / 72) + cell.TopBorderDistance + cell.BottomBorderDistance
    return h, col_w


def set_row_height(m, h):
    t, cell = current(m)
    if t is None:
        return
    rows = {_rc(n)[0] for n in _selected_cells(m, t)}
    for r in rows:
        row = t.getRows().getByIndex(r)
        row.IsAutoHeight = False
        row.Height = int(h)


def set_col_width(m, w):
    t, cell = current(m)
    if t is None:
        return
    _r, c = _rc(cell.CellName)
    seps = list(t.TableColumnSeparators or ())
    if not seps:
        return
    rel = t.TableColumnRelativeSum or 10000
    width = _table_width(m, t)
    pos = [0] + [s.Position for s in seps] + [rel]
    if c >= len(pos) - 1:
        return
    new = int(w * rel / width)
    delta = new - (pos[c + 1] - pos[c])
    if c < len(seps):
        # move this column's right edge; the next column absorbs the change
        lo = pos[c] + 50
        hi = pos[c + 2] - 50 if c + 2 < len(pos) else rel - 50
        seps[c].Position = max(lo, min(hi, seps[c].Position + delta))
    else:
        seps[c - 1].Position = max(pos[c - 1] + 50, seps[c - 1].Position - delta)
    t.TableColumnSeparators = tuple(seps)


def autofit(m, how):
    """'contents' / 'window' / 'fixed'."""
    t, _c = current(m)
    if t is None:
        return
    if how == "window":
        t.HoriOrient = 6         # FULL: as wide as the text area
    elif how == "fixed":
        w = t.Width
        t.HoriOrient = 0         # NONE
        t.Width = w
    return how == "contents"     # caller runs the engine's optimal width


# ------------------------------------------------------------ alignment
def align_cells(m, horiz, vert):
    t, _c = current(m)
    if t is None:
        return
    for n in _selected_cells(m, t):
        cell = t.getCellByName(n)
        if vert is not None:
            cell.VertOrient = {"top": 1, "center": 2, "bottom": 3}[vert]
        if horiz is not None:
            cur = cell.createTextCursor()
            cur.gotoStart(False)
            cur.gotoEnd(True)
            cur.ParaAdjust = {"left": 0, "center": 3, "right": 1}[horiz]


def text_direction(m):
    """Cycle horizontal -> rotated down -> rotated up."""
    t, cell = current(m)
    if t is None:
        return
    order = [0, 2, 5]       # LR_TB, TB_RL, BT_LR
    try:
        cur = cell.WritingMode
    except Exception:
        cur = 0
    nxt = order[(order.index(cur) + 1) % 3] if cur in order else 2
    for n in _selected_cells(m, t):
        try:
            t.getCellByName(n).WritingMode = nxt
        except Exception as e:
            print("text direction:", e)


def cell_margins(m):
    t, cell = current(m)
    if t is None:
        return None
    return (cell.TopBorderDistance, cell.BottomBorderDistance, cell.LeftBorderDistance,
            cell.RightBorderDistance)


def set_cell_margins(m, top, bottom, left, right):
    t, _c = current(m)
    if t is None:
        return
    for n in t.getCellNames():
        c = t.getCellByName(n)
        c.TopBorderDistance = int(top)
        c.BottomBorderDistance = int(bottom)
        c.LeftBorderDistance = int(left)
        c.RightBorderDistance = int(right)


# ------------------------------------------------------------ data
def repeat_header(m):
    t, _c = current(m)
    if t is None:
        return False
    on = not t.RepeatHeadline
    t.RepeatHeadline = on
    try:
        t.HeaderRowCount = 1 if on else 0
    except Exception:
        pass
    return on


def is_repeat_header(m):
    t, _c = current(m)
    return bool(t is not None and t.RepeatHeadline)


def table_text(t):
    rows = t.getRows().getCount()
    cols = t.getColumns().getCount()
    out = []
    for r in range(rows):
        row = []
        for c in range(cols):
            n = _name(r, c)
            row.append(t.getCellByName(n).getString() if n in t.getCellNames() else "")
        out.append(row)
    return out


def convert_to_text(m, sep="\t"):
    t, _c = current(m)
    if t is None:
        return
    data = table_text(t)
    um = m.getUndoManager()
    um.enterUndoContext("Convert Table to Text")
    try:
        text = m.getText()
        lines = []
        for row in data:
            if sep == "\n":
                lines.extend(row)
            else:
                lines.append(sep.join(row))
        prev = None
        en = text.createEnumeration()
        while en.hasMoreElements():
            el = en.nextElement()
            if el.supportsService("com.sun.star.text.TextTable") and \
                    el.getName() == t.getName():
                break
            prev = el
        if prev is not None:
            cur = text.createTextCursorByRange(prev.getEnd())
            for line in lines:
                text.insertControlCharacter(cur, 0, False)
                text.insertString(cur, line, False)
        else:
            text.insertTextContentBefore(m.createInstance("com.sun.star.text.Paragraph"), t)
            cur = text.createTextCursor()
            cur.gotoStart(False)
            for i, line in enumerate(lines):
                if i:
                    text.insertControlCharacter(cur, 0, False)
                text.insertString(cur, line, False)
        text.removeTextContent(t)
    finally:
        um.leaveUndoContext()


def sort_table(m, column, descending=False, header=True, numeric=False):
    """Sort the body rows by one column. Cell text moves; the table's look
    (banding, borders) stays with the positions, as in the original."""
    t, _c = current(m)
    if t is None:
        return
    data = table_text(t)
    first = 1 if header else 0
    body = data[first:]
    if len(body) < 2:
        return

    def key(row):
        v = row[column] if column < len(row) else ""
        if numeric:
            n = _num(v)
            return (n is None, n if n is not None else 0)
        return (v == "", v.lower())
    body.sort(key=key, reverse=descending)
    if descending:
        # keep empty cells last either way
        body = [r for r in body if key(r)[0] is False] + [r for r in body if key(r)[0]]
    um = m.getUndoManager()
    um.enterUndoContext("Sort")
    try:
        names = set(t.getCellNames())
        for i, row in enumerate(body):
            for c, v in enumerate(row):
                n = _name(first + i, c)
                if n in names:
                    cell = t.getCellByName(n)
                    if cell.getString() != v:
                        cell.setString(v)
    finally:
        um.leaveUndoContext()


FUNCS = ("SUM", "AVERAGE", "COUNT", "MAX", "MIN", "PRODUCT")


def default_formula(m):
    """=SUM(ABOVE) if there are numbers above, else =SUM(LEFT), like the original."""
    t, cell = current(m)
    if t is None:
        return "=SUM(ABOVE)"
    r, c = _rc(cell.CellName)
    for rr in range(r):
        n = _name(rr, c)
        if n in t.getCellNames() and _num(t.getCellByName(n).getString()) is not None:
            return "=SUM(ABOVE)"
    return "=SUM(LEFT)"


def _num(s):
    try:
        return float(s.replace(",", "").replace("$", "").replace("€", "").strip())
    except ValueError:
        return None


def insert_formula(m, formula):
    """=FUNC(ABOVE|LEFT|BELOW|RIGHT) or =FUNC(A1:B3) -> a live table formula."""
    t, cell = current(m)
    if t is None:
        return False
    f = formula.strip().lstrip("=")
    mm = re.match(r"(\w+)\s*\(\s*([^)]*)\)", f)
    if not mm:
        cell.setFormula(f)
        return True
    fn, arg = mm.group(1).upper(), mm.group(2).strip().upper()
    r, c = _rc(cell.CellName)
    rows = t.getRows().getCount()
    cols = t.getColumns().getCount()
    if arg == "ABOVE":
        rng = "%s:%s" % (_name(0, c), _name(r - 1, c)) if r else None
    elif arg == "BELOW":
        rng = "%s:%s" % (_name(r + 1, c), _name(rows - 1, c)) if r < rows - 1 else None
    elif arg == "LEFT":
        rng = "%s:%s" % (_name(r, 0), _name(r, c - 1)) if c else None
    elif arg == "RIGHT":
        rng = "%s:%s" % (_name(r, c + 1), _name(r, cols - 1)) if c < cols - 1 else None
    else:
        rng = arg
    if not rng:
        return False
    engine_fn = {"SUM": "sum", "AVERAGE": "mean", "COUNT": "count", "MAX": "max",
                 "MIN": "min", "PRODUCT": "product"}.get(fn, "sum")
    cell.setFormula("%s <%s>" % (engine_fn, rng))
    return True


# ------------------------------------------------------------ dialogs
def sort_dialog(win):
    m = win.engine.model
    t, _c = current(m) if m else (None, None)
    if t is None:
        return
    data = table_text(t)
    header_names = data[0] if data else []
    d = FDialog(win, "Sort")
    has_header = Gtk.RadioButton.new_with_mnemonic(None, "Header _row")
    no_header = Gtk.RadioButton.new_with_mnemonic_from_widget(has_header, "No header ro_w")

    def names():
        if has_header.get_active():
            return [h or "Column %d" % (i + 1) for i, h in enumerate(header_names)]
        return ["Column %d" % (i + 1) for i in range(len(header_names))]
    by = combo(names(), 0)
    typ = combo(["Text", "Number"], 0)
    asc = Gtk.RadioButton.new_with_mnemonic(None, "_Ascending")
    desc = Gtk.RadioButton.new_with_mnemonic_from_widget(asc, "_Descending")
    d.add(heading("Sort by"))
    d.add(grid([[by, "_Type:", typ], [None, asc, desc]]))
    d.add(heading("My list has"))
    b = Gtk.Box(spacing=12)
    b.pack_start(has_header, False, False, 0)
    b.pack_start(no_header, False, False, 0)
    d.add(b)

    def relabel(*_):
        i = by.get_active()
        by.remove_all()
        for n in names():
            by.append_text(n)
        by.set_active(max(0, i))
    has_header.connect("toggled", relabel)
    if d.ask() == Gtk.ResponseType.OK:
        win.engine.sync(lambda: sort_table(m, max(0, by.get_active()), desc.get_active(),
                                           has_header.get_active(), typ.get_active() == 1))
    d.done()


def convert_dialog(win):
    m = win.engine.model
    t, _c = current(m) if m else (None, None)
    if t is None:
        return
    d = FDialog(win, "Convert Table To Text")
    d.add(heading("Separate text with"))
    para = Gtk.RadioButton.new_with_mnemonic(None, "_Paragraph marks")
    tabs = Gtk.RadioButton.new_with_mnemonic_from_widget(para, "_Tabs")
    commas = Gtk.RadioButton.new_with_mnemonic_from_widget(para, "Co_mmas")
    other = Gtk.RadioButton.new_with_mnemonic_from_widget(para, "_Other:")
    oe = Gtk.Entry(text="-")
    oe.set_width_chars(3)
    tabs.set_active(True)
    for w in (para, tabs, commas):
        d.add(w)
    ob = Gtk.Box(spacing=6)
    ob.pack_start(other, False, False, 0)
    ob.pack_start(oe, False, False, 0)
    d.add(ob)
    if d.ask() == Gtk.ResponseType.OK:
        sep = "\n" if para.get_active() else "\t" if tabs.get_active() else \
            ", " if commas.get_active() else (oe.get_text() or "-")
        win.engine.sync(lambda: convert_to_text(m, sep))
    d.done()


def formula_dialog(win):
    m = win.engine.model
    t, _c = current(m) if m else (None, None)
    if t is None:
        return
    d = FDialog(win, "Formula")
    e = Gtk.Entry(text=default_formula(m))
    e.set_width_chars(36)
    e.set_activates_default(True)
    fmt = combo(["", "#,##0", "#,##0.00", "$#,##0.00", "0%", "0.00%"], 0)
    paste = combo(["Paste function"] + list(FUNCS), 0)

    def put(*_):
        i = paste.get_active()
        if i > 0:
            e.set_text("=" + FUNCS[i - 1] + "()")
            e.set_position(len(e.get_text()) - 1)
            e.grab_focus()
    paste.connect("changed", put)
    d.add(grid([["_Formula:", None], [e, None], ["_Number format:", fmt],
                ["Paste f_unction:", paste]]))
    if d.ask() == Gtk.ResponseType.OK:
        text = e.get_text()
        number_format = fmt.get_active_text()

        def go():
            ok = insert_formula(m, text)
            if not ok:
                win.dialogs.message("Syntax Error or no numbers to calculate.")
                return
            if number_format:
                t2, cell = current(m)
                try:
                    cell.NumberFormat = docapi._number_format(m, number_format)
                except Exception:
                    pass
        win.engine.sync(go)
    d.done()


def cell_margins_dialog(win):
    m = win.engine.model
    cur = cell_margins(m) if m else None
    if cur is None:
        return
    d = FDialog(win, "Table Options")
    spins = [LengthSpin(v, 0, 25400) for v in cur]
    d.add(heading("Default cell margins"))
    d.add(grid([["_Top:", spins[0], "_Left:", spins[2]],
                ["_Bottom:", spins[1], "_Right:", spins[3]]]))
    if d.ask() == Gtk.ResponseType.OK:
        vals = [s.mm100 for s in spins]
        win.engine.sync(lambda: set_cell_margins(m, *vals))
    d.done()
