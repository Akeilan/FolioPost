"""Table dialogs: Split Cells, Convert Text to Table, Table Properties,
borders for the whole table."""
from gi.repository import Gtk

from . import bridge, docapi
from .widgets import FDialog, LengthSpin, color_button, combo, grid, heading


def _table(m):
    vc = docapi.view_cursor(m)
    try:
        return vc.TextTable, vc.Cell
    except Exception:
        return None, None


class TableDialogs:
    def split_cells(self):
        m = self._model_or_warn()
        if m is None:
            return
        table, cell = _table(m)
        if table is None:
            self.message("Put the cursor in a table cell first.")
            return
        d = FDialog(self.win, "Split Cells")
        cols = Gtk.SpinButton.new_with_range(1, 63, 1)
        rows = Gtk.SpinButton.new_with_range(1, 99, 1)
        cols.set_value(2)
        rows.set_value(1)
        d.add(grid([["Number of _columns:", cols], ["Number of _rows:", rows]]))
        if d.ask() == Gtk.ResponseType.OK:
            c, r = int(cols.get_value()), int(rows.get_value())
            try:
                if c > 1:
                    cur = table.createCursorByCellName(cell.CellName)
                    cur.splitRange(c - 1, False)
                if r > 1:
                    cur = table.createCursorByCellName(cell.CellName)
                    cur.splitRange(r - 1, True)
            except Exception as e:
                self.message("The cells couldn't be split: %s" % e)
        d.done()

    def split_table(self):
        self.eng.command(".uno:SplitTable", {"Type": ("short", 1)})

    def text_to_table(self):
        m = self._model_or_warn()
        if m is None:
            return
        vc = docapi.view_cursor(m)
        text = vc.getString()
        if not text.strip():
            self.message("Select the text you want to convert to a table first.")
            return
        lines = [l for l in text.replace("\r", "\n").split("\n")]
        while lines and not lines[-1].strip():
            lines.pop()
        d = FDialog(self.win, "Convert Text to Table")
        d.add(heading("Table size"))
        cols = Gtk.SpinButton.new_with_range(1, 63, 1)
        rows_lab = Gtk.Label(label=str(len(lines)), xalign=0)
        d.add(grid([["Number of _columns:", cols], ["Number of rows:", rows_lab]]))
        d.add(heading("Separate text at"))
        seps = {}
        grp = None
        box = Gtk.Box(spacing=12)
        for key, label in (("para", "_Paragraphs"), ("comma", "Co_mmas"), ("tab", "_Tabs"),
                           ("other", "_Other:")):
            rb = Gtk.RadioButton.new_with_mnemonic_from_widget(grp, label)
            grp = grp or rb
            seps[key] = rb
            box.pack_start(rb, False, False, 0)
        other = Gtk.Entry(text="-")
        other.set_width_chars(3)
        box.pack_start(other, False, False, 0)
        d.add(box)

        def sep():
            if seps["comma"].get_active():
                return ","
            if seps["tab"].get_active():
                return "\t"
            if seps["other"].get_active():
                return other.get_text()[:1] or "-"
            return None

        def guess(*_):
            s = sep()
            n = max((len(l.split(s)) for l in lines), default=1) if s else 1
            cols.set_value(n)
        for rb in seps.values():
            rb.connect("toggled", guess)
        (seps["tab"] if any("\t" in l for l in lines) else
         seps["comma"] if all("," in l for l in lines) else seps["para"]).set_active(True)
        guess()
        if d.ask() == Gtk.ResponseType.OK:
            s = sep()
            ncols = int(cols.get_value())
            data = [(l.split(s) if s else [l]) for l in lines]
            vc.setString("")
            table = m.createInstance("com.sun.star.text.TextTable")
            table.initialize(max(1, len(data)), ncols)
            vc.getText().insertTextContent(vc, table, False)
            for r, row in enumerate(data):
                for c in range(ncols):
                    val = row[c].strip() if c < len(row) else ""
                    table.getCellByPosition(c, r).setString(val)
        d.done()

    def table_borders(self, kind="all"):
        m = self._model_or_warn()
        if m is None:
            return
        table, _cell = _table(m)
        if table is None:
            return
        tb = table.TableBorder2
        line = bridge.struct("com.sun.star.table.BorderLine2", Color=0, LineWidth=18,
                             OuterLineWidth=18)
        none = bridge.struct("com.sun.star.table.BorderLine2")
        outer = kind in ("all", "outside")
        inner = kind in ("all", "inside")
        for side, on in (("TopLine", outer), ("BottomLine", outer), ("LeftLine", outer),
                         ("RightLine", outer), ("HorizontalLine", inner),
                         ("VerticalLine", inner)):
            setattr(tb, side, line if on else none)
            setattr(tb, "Is" + side + "Valid", True)
        table.TableBorder2 = tb

    def table_properties(self, page=0):
        from .tabledraw import properties_dialog
        return properties_dialog(self.win, page)

    def insert_cells(self):
        from .tabledraw import insert_cells_dialog
        insert_cells_dialog(self.win)

    def select_cell(self):
        m = self.model
        if m is None:
            return
        vc = docapi.view_cursor(m)
        try:
            t, c = vc.TextTable, vc.Cell
            cur = t.createCursorByCellName(c.CellName)
            docapi.controller(m).select(cur)
        except Exception:
            pass

    def _old_table_properties(self):
        m = self._model_or_warn()
        if m is None:
            return
        table, cell = _table(m)
        if table is None:
            self.message("Put the cursor in a table first.")
            return
        d = FDialog(self.win, "Table Properties")
        nb = Gtk.Notebook()
        d.add(nb)
        # table
        p1 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        p1.set_border_width(10)
        p1.pack_start(heading("Size"), False, False, 0)
        rel = Gtk.SpinButton.new_with_range(10, 100, 1)
        try:
            rel.set_value(table.RelativeWidth or 100)
        except Exception:
            rel.set_value(100)
        p1.pack_start(grid([["Preferred _width (%):", rel]]), False, False, 0)
        p1.pack_start(heading("Alignment"), False, False, 0)
        hori = {0: 0, 1: 1, 2: 2, 3: 3}
        align = combo(["Left", "Center", "Right"], {3: 0, 2: 1, 1: 2}.get(table.HoriOrient, 0)
                      if table.HoriOrient in (1, 2, 3) else 0)
        p1.pack_start(align, False, False, 0)
        # row
        p2 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        p2.set_border_width(10)
        vc = docapi.view_cursor(m)
        rows = table.getRows()
        row_index = int("".join(ch for ch in cell.CellName if ch.isdigit()) or "1") - 1
        row = rows.getByIndex(row_index)
        auto = Gtk.CheckButton(label="Specify height:")
        auto.set_active(not row.IsAutoHeight)
        height = LengthSpin(row.Height or 500, 0, 55880)
        p2.pack_start(grid([[auto, height]]), False, False, 0)
        # cell
        p3 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        p3.set_border_width(10)
        p3.pack_start(heading("Vertical alignment"), False, False, 0)
        valign = combo(["Top", "Center", "Bottom"], {0: 0, 1: 0, 2: 1, 3: 2}.get(cell.VertOrient, 0))
        p3.pack_start(valign, False, False, 0)
        shade = color_button(cell.BackColor if cell.BackColor != -1 else -1, auto_label="No Color")
        p3.pack_start(grid([["Shading:", shade]]), False, False, 0)
        nb.append_page(p1, Gtk.Label(label="Table"))
        nb.append_page(p2, Gtk.Label(label="Row"))
        nb.append_page(p3, Gtk.Label(label="Cell"))
        if d.ask() == Gtk.ResponseType.OK:
            try:
                ho = {0: 3, 1: 2, 2: 1}[align.get_active()]
                if rel.get_value() < 100:
                    table.HoriOrient = ho
                    table.RelativeWidth = int(rel.get_value())
                else:
                    table.HoriOrient = 6     # full width
                row.IsAutoHeight = not auto.get_active()
                if auto.get_active():
                    row.Height = height.mm100
                cell.VertOrient = {0: 1, 1: 2, 2: 3}[valign.get_active()]
                cell.BackColor = -1 if shade.color is None or shade.color < 0 else shade.color
            except Exception as e:
                self.message("Some table properties couldn't be applied: %s" % e)
        d.done()

    # Engine dialogs that slipped through map onto ours
    ENGINE_DIALOGS = {"Split Cells": "split_cells", "Convert Text to Table": "text_to_table",
                      "Split Table": "split_table", "Insert Table": "insert_table_dialog",
                      "Table Properties": "table_properties", "Font": "font_dialog",
                      "Paragraph": "paragraph_dialog", "Find and Replace": "replace",
                      "Insert Bookmark": "bookmark", "Bookmark": "bookmark",
                      "Hyperlink": "hyperlink", "Special Characters": "symbol_dialog",
                      "Word and Character Count": "word_count", "Page Style": "page_setup",
                      "Zoom & View Layout": "zoom_dialog", "Insert Caption": "caption",
                      "Insert Fields": "field_dialog", "Fields": "field_dialog",
                      "Insert Footnote/Endnote": None, "Options": "options"}

    def engine_dialog(self, title):
        target = self.ENGINE_DIALOGS.get(title)
        if target:
            getattr(self, target)()
