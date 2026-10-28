"""Draw Table and Eraser (Table Layout > Draw), the Insert Cells dialog and
the full Table Properties dialog."""
import math

from gi.repository import Gdk, GLib, Gtk

from . import bridge, docapi
from .widgets import FDialog, LengthSpin, color_button, combo, grid, heading


def _cell_at(win, x, y):
    """Put the cursor at view pixel (x, y); return (table, cell name) or None."""
    eng = win.engine
    tx, ty = eng.px_to_twips(x, y)
    eng.click_at(tx, ty)
    try:
        vc = docapi.read_cursor(eng.model)
        t, c = vc.TextTable, vc.Cell
        if t is None or c is None:
            return None
        return t, c.CellName
    except Exception:
        return None


class TableDrawMode:
    """'draw': drag a rectangle to make a table, drag a line inside a table to
    split cells. 'erase': click a cell border to merge the cells beside it."""

    def __init__(self, win):
        self.win = win
        self.tool = None
        self.start = None
        self.cur = None
        view = win.engine.view
        view.connect("button-press-event", self._press)
        view.connect("motion-notify-event", self._motion)
        view.connect("button-release-event", self._release)
        view.connect_after("draw", self._draw)

    @property
    def active(self):
        return self.tool is not None

    def begin(self, tool):
        if self.tool == tool:
            self.stop()
            return
        self.tool = tool
        w = self.win.engine.view.get_window()
        if w is not None:
            try:
                w.set_cursor(Gdk.Cursor.new_from_name(w.get_display(),
                                                      "pencil" if tool == "draw" else "cell"))
            except Exception:
                pass
        self.win.status.flash("Drag to draw a table or a line inside one. Esc to stop."
                              if tool == "draw" else
                              "Click a line between cells to merge them. Esc to stop.")
        for k, b in getattr(self.win, "table_draw_buttons", {}).items():
            b.apply_state("true" if k == tool else "false")

    def stop(self):
        self.tool = None
        self.start = self.cur = None
        w = self.win.engine.view.get_window()
        if w is not None:
            w.set_cursor(None)
        for b in getattr(self.win, "table_draw_buttons", {}).values():
            b.apply_state("false")
        self.win.engine.view.queue_draw()

    def key(self, event):
        if self.active and event.keyval == Gdk.KEY_Escape:
            self.stop()
            return True
        return False

    def _press(self, view, ev):
        if not self.active or ev.button != 1:
            return False
        self.start = self.cur = (ev.x, ev.y)
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
        (x0, y0), (x1, y1) = self.start, (ev.x, ev.y)
        self.start = self.cur = None
        view.queue_draw()
        tool = self.tool
        GLib.idle_add(lambda: (self._apply(tool, x0, y0, x1, y1), False)[1])
        return True

    def _draw(self, view, cr):
        if not self.active or self.start is None or self.cur is None:
            return False
        (x0, y0), (x1, y1) = self.start, self.cur
        cr.set_source_rgb(0.1, 0.1, 0.1)
        cr.set_line_width(1)
        cr.set_dash([3, 2])
        if self.tool == "draw":
            if abs(x1 - x0) > 12 and abs(y1 - y0) > 12:
                cr.rectangle(min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0))
            elif abs(x1 - x0) >= abs(y1 - y0):
                cr.move_to(x0, y0)
                cr.line_to(x1, y0)
            else:
                cr.move_to(x0, y0)
                cr.line_to(x0, y1)
            cr.stroke()
        return False

    # ------------------------------------------------------------ actions
    def _apply(self, tool, x0, y0, x1, y1):
        m = self.win.engine.model
        if m is None:
            return
        if tool == "erase":
            self._erase(m, x1, y1)
            return
        dx, dy = abs(x1 - x0), abs(y1 - y0)
        here = _cell_at(self.win, (x0 + x1) / 2, (y0 + y1) / 2)
        if here is None:
            if dx > 12 and dy > 12:
                GLib.timeout_add(120, lambda: (self._new_table(m, x0, y0, x1, y1), False)[1])
            return
        GLib.timeout_add(120, lambda: (self._split(m, dx >= dy), False)[1])

    def _new_table(self, m, x0, y0, x1, y1):
        from . import tablestyles
        eng = self.win.engine
        tx, ty = eng.px_to_twips(min(x0, x1), min(y0, y1))
        eng.click_at(tx, ty)

        def go():
            t = tablestyles.insert_table(m, 1, 1)
            z = eng.view.get_zoom() or 1.0
            to_mm = lambda px: int(px * 15 / z * 2540 / 1440)   # noqa: E731
            try:
                t.HoriOrient = 3                     # left, with an indent
                t.Width = max(500, to_mm(abs(x1 - x0)))
                t.getRows().getByIndex(0).Height = max(300, to_mm(abs(y1 - y0)))
                t.getRows().getByIndex(0).IsAutoHeight = True
            except Exception as e:
                print("draw table:", e)
            return False
        GLib.timeout_add(120, go)

    def _split(self, m, horizontal_line):
        vc = docapi.read_cursor(m)
        try:
            t, c = vc.TextTable, vc.Cell
            cur = t.createCursorByCellName(c.CellName)
            um = m.getUndoManager()
            um.enterUndoContext("Draw Table")
            try:
                # a horizontal line splits the cell into rows
                cur.splitRange(1, horizontal_line)
            finally:
                um.leaveUndoContext()
        except Exception as e:
            print("split cell:", e)

    def _erase(self, m, x, y):
        """Merge the cells on both sides of the line nearest the click."""
        here = _cell_at(self.win, x, y)
        if here is None:
            return
        best = None
        for dx, dy, d in ((0, -7, "up"), (0, 7, "down"), (-7, 0, "left"), (7, 0, "right")):
            other = _cell_at(self.win, x + dx, y + dy)
            if other is not None and other[0] == here[0] and other[1] != here[1]:
                best = (d, other[1])
                break
        if best is None:
            self.win.status.flash("Click on a line between two cells.")
            return
        table, name = here
        try:
            names = sorted([name, best[1]], key=lambda n: _cell_key(n))
            cur = table.createCursorByCellName(names[0])
            cur.gotoCellByName(names[1], True)
            um = m.getUndoManager()
            um.enterUndoContext("Eraser")
            try:
                cur.mergeRange()
            finally:
                um.leaveUndoContext()
        except Exception as e:
            print("erase:", e)


def _cell_key(name):
    col = "".join(ch for ch in name.split(".")[0] if ch.isalpha())
    row = "".join(ch for ch in name.split(".")[0] if ch.isdigit())
    n = 0
    for ch in col:
        n = n * 26 + (ord(ch.upper()) - 64)
    return (int(row or 0), n)


# ------------------------------------------------------------ Insert Cells
def insert_cells_dialog(win):
    m = win.engine.model
    if m is None:
        return
    vc = docapi.read_cursor(m)
    try:
        t, c = vc.TextTable, vc.Cell
    except Exception:
        t = c = None
    if t is None:
        win.dialogs.message("Put the cursor in a table first.")
        return
    d = FDialog(win, "Insert Cells")
    r1 = Gtk.RadioButton.new_with_mnemonic(None, "Shift cells r_ight")
    r2 = Gtk.RadioButton.new_with_mnemonic_from_widget(r1, "Shift cells _down")
    r3 = Gtk.RadioButton.new_with_mnemonic_from_widget(r1, "Insert entire _row")
    r4 = Gtk.RadioButton.new_with_mnemonic_from_widget(r1, "Insert entire _column")
    r2.set_active(True)
    for r in (r1, r2, r3, r4):
        d.add(r)
    res = d.ask()
    choice = [r1, r2, r3, r4].index(next(r for r in (r1, r2, r3, r4) if r.get_active()))
    d.done()
    if res != Gtk.ResponseType.OK:
        return
    if choice == 2:
        win.actions.cmd(".uno:InsertRowsBefore")
    elif choice == 3:
        win.actions.cmd(".uno:InsertColumnsBefore")
    else:
        um = m.getUndoManager()
        um.enterUndoContext("Insert Cells")
        try:
            shift_cells(t, c.CellName, down=choice == 1)
        finally:
            um.leaveUndoContext()


def shift_cells(t, name, down=True):
    """Make room at a cell: its column (or row) moves on by one cell, adding a
    row (or column) at the end."""
    rows, cols = t.getRows().getCount(), t.getColumns().getCount()
    col, row = _pos(t, name)
    if down:
        t.getRows().insertByIndex(rows, 1)
        for r in range(rows, row, -1):
            _copy(t.getCellByPosition(col, r - 1), t.getCellByPosition(col, r))
    else:
        t.getColumns().insertByIndex(cols, 1)
        for cc in range(cols, col, -1):
            _copy(t.getCellByPosition(cc - 1, row), t.getCellByPosition(cc, row))
    t.getCellByPosition(col, row).setString("")


def _pos(t, name):
    for r in range(t.getRows().getCount()):
        for c in range(t.getColumns().getCount()):
            try:
                if t.getCellByPosition(c, r).CellName == name:
                    return c, r
            except Exception:
                pass
    return 0, 0


def _copy(src, dst):
    dst.setString(src.getString())
    for p in ("BackColor", "VertOrient"):
        try:
            setattr(dst, p, getattr(src, p))
        except Exception:
            pass


# ------------------------------------------------------------ Table Properties
def properties_dialog(win, page=0):
    from .widgets import fmt_len
    m = win.engine.model
    if m is None:
        return
    vc = docapi.read_cursor(m)
    try:
        table, cell = vc.TextTable, vc.Cell
    except Exception:
        table = cell = None
    if table is None:
        win.dialogs.message("Put the cursor in a table first.")
        return
    state = {"row": _pos(table, cell.CellName)[1], "col": _pos(table, cell.CellName)[0]}
    d = FDialog(win, "Table Properties")
    nb = Gtk.Notebook()
    d.add(nb, expand=True)
    ps = docapi.page_setup(m)
    text_width = ps["width"] - ps["left"] - ps["right"]

    # --- Table
    p1 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin=10)
    p1.pack_start(heading("Size"), False, False, 0)
    pref = Gtk.CheckButton.new_with_mnemonic("Preferred _width:")
    full = table.HoriOrient == 6
    width_now = text_width if full else (table.Width or text_width)
    pref.set_active(not full)
    width = LengthSpin(width_now, 100, 558800)
    measure = combo(["Centimeters", "Percent"], 0)
    p1.pack_start(grid([[pref, width, "Measure in:", measure]]), False, False, 0)
    p1.pack_start(heading("Alignment"), False, False, 0)
    align = combo(["Left", "Center", "Right"], {3: 0, 7: 0, 0: 0, 2: 1, 1: 2}.get(
        table.HoriOrient, 0))
    indent = LengthSpin(table.LeftMargin or 0, -50000, 50000)
    p1.pack_start(grid([["Alignment:", align, "Indent from left:", indent]]), False, False, 0)
    p1.pack_start(heading("Text wrapping"), False, False, 0)
    wrap_none = Gtk.RadioButton.new_with_mnemonic(None, "_None")
    wrap_around = Gtk.RadioButton.new_with_mnemonic_from_widget(wrap_none, "Aro_und")
    wrap_around.set_sensitive(False)
    wrap_around.set_tooltip_text("Tables always flow with the text in this document.")
    hb = Gtk.Box(spacing=16)
    hb.pack_start(wrap_none, False, False, 0)
    hb.pack_start(wrap_around, False, False, 0)
    p1.pack_start(hb, False, False, 0)
    bb = Gtk.Box(spacing=6)
    borders = Gtk.Button.new_with_mnemonic("_Borders and Shading...")
    borders.connect("clicked", lambda *_: win.run("paragraph-borders"))
    opts = Gtk.Button.new_with_mnemonic("_Options...")
    from . import tablelayout as TL
    opts.connect("clicked", lambda *_: TL.cell_margins_dialog(win))
    bb.pack_end(opts, False, False, 0)
    bb.pack_end(borders, False, False, 0)
    p1.pack_end(bb, False, False, 0)

    def width_unit(*_):
        if measure.get_active() == 1:
            width.set_tooltip_text("%d%%" % round(100.0 * width.mm100 / text_width))
    measure.connect("changed", width_unit)

    # --- Row
    rows = table.getRows()
    p2 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin=10)
    row_label = Gtk.Label(xalign=0)
    p2.pack_start(row_label, False, False, 0)
    p2.pack_start(heading("Size"), False, False, 0)
    spec_h = Gtk.CheckButton.new_with_mnemonic("_Specify height:")
    height = LengthSpin(500, 0, 55880)
    hrule = combo(["At least", "Exactly"], 0)
    p2.pack_start(grid([[spec_h, height, "Row height is:", hrule]]), False, False, 0)
    p2.pack_start(heading("Options"), False, False, 0)
    allow = Gtk.CheckButton.new_with_mnemonic("Allow row to brea_k across pages")
    header = Gtk.CheckButton.new_with_mnemonic("Repeat as _header row at the top of each page")
    p2.pack_start(allow, False, False, 0)
    p2.pack_start(header, False, False, 0)
    nav2 = Gtk.Box(spacing=6)
    prev_r = Gtk.Button.new_with_mnemonic("_Previous Row")
    next_r = Gtk.Button.new_with_mnemonic("_Next Row")
    nav2.pack_start(prev_r, False, False, 0)
    nav2.pack_start(next_r, False, False, 0)
    p2.pack_start(nav2, False, False, 0)
    row_edits = {}

    def save_row():
        row_edits[state["row"]] = {"spec": spec_h.get_active(), "h": height.mm100,
                                   "exact": hrule.get_active() == 1,
                                   "allow": allow.get_active()}

    def load_row():
        i = state["row"]
        row_label.set_markup("<b>Row %d:</b>" % (i + 1))
        row = rows.getByIndex(i)
        e = row_edits.get(i)
        if e is None:
            e = {"spec": not row.IsAutoHeight or (row.Height or 0) > 0,
                 "h": row.Height or 500, "exact": not row.IsAutoHeight,
                 "allow": bool(getattr(row, "IsSplitAllowed", True))}
        spec_h.set_active(e["spec"])
        height.set_mm100(e["h"]) if hasattr(height, "set_mm100") else height.set_value(e["h"])
        hrule.set_active(1 if e["exact"] else 0)
        allow.set_active(e["allow"])
        header.set_active(bool(table.RepeatHeadline) and i < max(1, getattr(
            table, "HeaderRowCount", 1) or 1))
        prev_r.set_sensitive(i > 0)
        next_r.set_sensitive(i < rows.getCount() - 1)

    def step_row(n):
        save_row()
        state["row"] = max(0, min(rows.getCount() - 1, state["row"] + n))
        load_row()
    prev_r.connect("clicked", lambda *_: step_row(-1))
    next_r.connect("clicked", lambda *_: step_row(1))
    load_row()

    # --- Column
    p3 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin=10)
    col_label = Gtk.Label(xalign=0)
    p3.pack_start(col_label, False, False, 0)
    p3.pack_start(heading("Size"), False, False, 0)
    spec_w = Gtk.CheckButton.new_with_mnemonic("Preferred _width:")
    col_w = LengthSpin(2000, 50, 558800)
    p3.pack_start(grid([[spec_w, col_w]]), False, False, 0)
    nav3 = Gtk.Box(spacing=6)
    prev_c = Gtk.Button.new_with_mnemonic("_Previous Column")
    next_c = Gtk.Button.new_with_mnemonic("_Next Column")
    nav3.pack_start(prev_c, False, False, 0)
    nav3.pack_start(next_c, False, False, 0)
    p3.pack_start(nav3, False, False, 0)
    col_edits = {}
    widths = column_widths(table, width_now)

    def load_col():
        i = state["col"]
        col_label.set_markup("<b>Column %d:</b>" % (i + 1))
        w = col_edits.get(i, widths[i] if i < len(widths) else 2000)
        spec_w.set_active(i in col_edits)
        _set(col_w, w)
        prev_c.set_sensitive(i > 0)
        next_c.set_sensitive(i < len(widths) - 1)

    def save_col():
        if spec_w.get_active():
            col_edits[state["col"]] = col_w.mm100

    def step_col(n):
        save_col()
        state["col"] = max(0, min(len(widths) - 1, state["col"] + n))
        load_col()
    prev_c.connect("clicked", lambda *_: step_col(-1))
    next_c.connect("clicked", lambda *_: step_col(1))
    col_w.connect("value-changed", lambda *_: spec_w.set_active(True))
    load_col()

    # --- Cell
    p4 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin=10)
    p4.pack_start(heading("Vertical alignment"), False, False, 0)
    valign = combo(["Top", "Center", "Bottom"], {0: 0, 1: 0, 2: 1, 3: 2}.get(
        cell.VertOrient, 0))
    p4.pack_start(valign, False, False, 0)
    shade = color_button(cell.BackColor if cell.BackColor != -1 else -1,
                         auto_label="No Color")
    p4.pack_start(grid([["Shading:", shade]]), False, False, 0)
    cm = Gtk.Button.new_with_mnemonic("_Options...")
    cm.set_halign(Gtk.Align.END)
    cm.connect("clicked", lambda *_: TL.cell_margins_dialog(win))
    p4.pack_end(cm, False, False, 0)

    # --- Alt Text
    p5 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin=10)
    title = Gtk.Entry()
    desc = Gtk.TextView()
    desc.set_wrap_mode(Gtk.WrapMode.WORD)
    desc.set_size_request(-1, 90)
    try:
        title.set_text(table.Title or "")
        desc.get_buffer().set_text(table.Description or "")
    except Exception:
        pass
    p5.pack_start(Gtk.Label(label="Title:", xalign=0), False, False, 0)
    p5.pack_start(title, False, False, 0)
    p5.pack_start(Gtk.Label(label="Description:", xalign=0), False, False, 0)
    fr = Gtk.Frame()
    fr.add(desc)
    p5.pack_start(fr, True, True, 0)

    for page_w, label in ((p1, "_Table"), (p2, "_Row"), (p3, "Col_umn"), (p4, "C_ell"),
                          (p5, "Alt Te_xt")):
        nb.append_page(page_w, Gtk.Label.new_with_mnemonic(label))
    nb.show_all()
    nb.set_current_page(page)
    res = d.ask()
    save_row()
    save_col()
    vals = {"pref": pref.get_active(), "width": width.mm100, "align": align.get_active(),
            "indent": indent.mm100, "valign": valign.get_active(), "shade": shade.color,
            "header": header.get_active(), "title": title.get_text(),
            "desc": desc.get_buffer().get_text(*desc.get_buffer().get_bounds(), False)}
    d.done()
    if res != Gtk.ResponseType.OK:
        return
    um = m.getUndoManager()
    um.enterUndoContext("Table Properties")
    try:
        if vals["pref"]:
            table.HoriOrient = {0: 7, 1: 2, 2: 1}[vals["align"]] if vals["align"] else 7
            table.Width = vals["width"]
            if vals["align"] == 0:
                table.LeftMargin = vals["indent"]
        else:
            table.HoriOrient = 6
        for i, e in row_edits.items():
            row = rows.getByIndex(i)
            if e["spec"]:
                row.Height = e["h"]
                row.IsAutoHeight = not e["exact"]
            else:
                row.IsAutoHeight = True
            try:
                row.IsSplitAllowed = e["allow"]
            except Exception:
                pass
        if vals["header"] != bool(table.RepeatHeadline):
            table.RepeatHeadline = vals["header"]
        if col_edits:
            set_column_widths(table, col_edits, widths)
        cell.VertOrient = {0: 1, 1: 2, 2: 3}[vals["valign"]]
        cell.BackColor = -1 if vals["shade"] is None or vals["shade"] < 0 else vals["shade"]
        for p, v in (("Title", vals["title"]), ("Description", vals["desc"])):
            try:
                setattr(table, p, v)
            except Exception:
                pass
    except Exception as e:
        win.dialogs.message("Some table properties couldn't be applied: %s" % e)
    finally:
        um.leaveUndoContext()


def _set(spin, mm100):
    if hasattr(spin, "set_mm100"):
        spin.set_mm100(mm100)
    else:
        spin.set_value(mm100)


def column_widths(table, total):
    """Column widths (mm100) of the first row."""
    try:
        seps = list(table.TableColumnSeparators)
        rel = table.TableColumnRelativeSum
    except Exception:
        return [total]
    edges = [0] + [s.Position for s in seps] + [rel]
    return [int((b - a) * total / float(rel)) for a, b in zip(edges, edges[1:])]


def set_column_widths(table, edits, widths):
    seps = list(table.TableColumnSeparators)
    rel = table.TableColumnRelativeSum
    total = sum(widths)
    new = list(widths)
    for i, w in edits.items():
        if i < len(new):
            diff = w - new[i]
            new[i] = w
            if i + 1 < len(new):                 # the next column gives way
                new[i + 1] = max(100, new[i + 1] - diff)
    s = sum(new) or 1
    pos = 0
    for k, sep in enumerate(seps):
        pos += new[k]
        sep.Position = int(pos * rel / float(s))
    table.TableColumnSeparators = tuple(seps)
    if abs(s - total) > 50 and table.HoriOrient != 6:
        table.Width = s
